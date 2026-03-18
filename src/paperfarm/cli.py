"""CLI entry-points for PaperFarm.

Provides three commands via :pypi:`typer`:

* ``run``     — launch a research session (serial, parallel, or TUI)
* ``status``  — display a snapshot of the current session state
* ``results`` — show the experiment results ledger
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="paperfarm",
    help="Sow ideas, run experiments, harvest better code.",
)
console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auto_tag() -> str:
    """Generate a session tag like ``r-20260318-153042``."""
    return "r-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _resolve_research_dir(repo: Path) -> Path:
    """Return the ``.research`` directory inside *repo*."""
    return repo / ".research"


def _deploy_scripts(research_dir: Path) -> None:
    """Copy bundled helper scripts into .research/scripts/."""
    scripts_src = Path(__file__).parent / "skills" / "scripts"
    scripts_dst = research_dir / "scripts"
    scripts_dst.mkdir(parents=True, exist_ok=True)
    for name in ("record.py", "rollback.sh"):
        src = scripts_src / name
        dst = scripts_dst / name
        if src.exists():
            dst.write_bytes(src.read_bytes())
            if name.endswith(".sh"):
                dst.chmod(0o755)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@app.command()
def run(
    repo: Path = typer.Argument(..., help="Path to target repo"),
    goal: str = typer.Option("", help="Research goal"),
    tag: str = typer.Option("", help="Session tag"),
    workers: int = typer.Option(0, help="Max parallel workers (0=serial)"),
    headless: bool = typer.Option(False, help="Run without TUI"),
    agent_name: str = typer.Option("claude-code", help="Agent to use"),
) -> None:
    """Launch or resume a research session."""
    # Validate repo
    if not repo.is_dir():
        console.print(f"[red]Error:[/red] repo path does not exist: {repo}")
        raise typer.Exit(code=1)

    # Create .research dir and deploy helper scripts
    research_dir = _resolve_research_dir(repo)
    research_dir.mkdir(parents=True, exist_ok=True)
    _deploy_scripts(research_dir)

    # Auto-generate tag if not provided
    if not tag:
        tag = _auto_tag()

    # Lazy imports to keep module-load fast
    from .agent import Agent, create_agent  # noqa: E402
    from .skill_runner import SkillRunner  # noqa: E402
    from .state import ResearchState  # noqa: E402

    state = ResearchState(research_dir)
    adapter = create_agent(agent_name)
    agent = Agent(adapter)

    if headless:
        # -- headless mode (serial or parallel) --
        if workers > 0:
            from .parallel import WorkerPool  # noqa: E402

            # Load experiment skill content for parallel workers
            runner = SkillRunner(
                repo, state, agent, goal=goal, tag=tag,
                on_output=lambda line: console.print(line, end=""),
            )
            # First run bootstrap
            rc = runner.run_bootstrap()
            if rc != 0:
                console.print(f"[red]Bootstrap failed (rc={rc})[/red]")
                raise typer.Exit(code=rc)

            # Then run parallel pool
            pool = WorkerPool(
                repo_path=repo,
                state=state,
                agent_factory=lambda: Agent(create_agent(agent_name)),
                skill_content="",
                max_workers=workers,
                on_output=lambda line: console.print(line, end=""),
            )
            pool.run()
            pool.wait()
        else:
            # Serial mode
            runner = SkillRunner(
                repo, state, agent, goal=goal, tag=tag,
                on_output=lambda line: console.print(line, end=""),
            )
            rc = runner.run_serial()
            if rc != 0:
                console.print(f"[red]Session ended with rc={rc}[/red]")
                raise typer.Exit(code=rc)
    else:
        # -- TUI mode --
        from .tui.app import ResearchApp  # noqa: E402

        runner = SkillRunner(
            repo, state, agent, goal=goal, tag=tag,
        )
        tui_app = ResearchApp(
            repo_path=str(repo),
            state=state,
            runner=runner.run_serial,
        )
        tui_app.run()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command()
def status(
    repo: Path = typer.Argument(..., help="Path to target repo"),
) -> None:
    """Display a snapshot of the current research session state."""
    research_dir = _resolve_research_dir(repo)
    if not research_dir.is_dir():
        console.print(f"[red]No .research directory found at {repo}[/red]")
        raise typer.Exit(code=1)

    from .state import ResearchState  # noqa: E402

    state = ResearchState(research_dir)
    summary = state.summary()

    table = Table(title="Research Status")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Phase", str(summary.get("phase", "idle")))
    table.add_row("Round", str(summary.get("round", 0)))
    table.add_row("Hypotheses", str(summary.get("hypotheses", 0)))
    table.add_row("Experiments (total)", str(summary.get("experiments_total", 0)))
    table.add_row("Experiments (done)", str(summary.get("experiments_done", 0)))
    table.add_row("Experiments (running)", str(summary.get("experiments_running", 0)))
    table.add_row("Results", str(summary.get("results_count", 0)))
    table.add_row("Best value", str(summary.get("best_value", "—")))
    table.add_row("Paused", str(summary.get("paused", False)))

    console.print(table)


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


@app.command()
def results(
    repo: Path = typer.Argument(..., help="Path to target repo"),
) -> None:
    """Display experiment results from the results ledger."""
    research_dir = _resolve_research_dir(repo)
    if not research_dir.is_dir():
        console.print(f"[red]No .research directory found at {repo}[/red]")
        raise typer.Exit(code=1)

    from .state import ResearchState  # noqa: E402

    state = ResearchState(research_dir)
    rows = state.load_results()

    if not rows:
        console.print("[dim]No results recorded yet.[/dim]")
        return

    table = Table(title="Experiment Results")
    # Use columns from the first row (or default fields)
    columns = list(rows[0].keys()) if rows else []
    for col in columns:
        table.add_column(col, style="cyan" if col == "frontier_id" else "")

    for row in rows:
        table.add_row(*(row.get(c, "") for c in columns))

    console.print(table)
