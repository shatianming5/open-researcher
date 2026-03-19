"""CLI entry-points for Open-Researcher v2.

Provides commands via :pypi:`typer`:

* ``run``       — launch a research session (serial, parallel, or TUI)
* ``status``    — display a snapshot of the current session state
* ``results``   — show the experiment results ledger
* ``review``    — show or act on a pending human review
* ``inject``    — inject a human-authored experiment into the frontier
* ``constrain`` — add user constraints for the research direction
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="open-researcher",
    help="Let AI agents run experiments while you sleep.",
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
    mode: str = typer.Option("", help="Interaction mode: autopilot or checkpoint"),
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

    # Apply --mode override to config
    if mode:
        import yaml

        config_path = research_dir / "config.yaml"
        cfg: dict = {}
        if config_path.exists():
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        cfg.setdefault("interaction", {})["mode"] = mode
        config_path.write_text(yaml.dump(cfg), encoding="utf-8")

    adapter = create_agent(agent_name)
    agent = Agent(adapter)

    runner = SkillRunner(
        repo, state, agent, goal=goal, tag=tag,
        on_output=lambda line: console.print(line, end="") if headless else None,
    )

    if headless:
        # -- headless mode (serial or parallel) --
        if workers > 0:
            from .parallel import WorkerPool  # noqa: E402

            config = state.load_config()
            gpu_mem = config.get("workers", {}).get("gpu_mem_per_worker_mb", 8192)

            def _make_pool() -> WorkerPool:
                return WorkerPool(
                    repo_path=repo,
                    state=state,
                    agent_factory=lambda: Agent(create_agent(agent_name)),
                    skill_content=runner._compose_program("experiment"),
                    max_workers=workers,
                    gpu_mem_per_worker_mb=gpu_mem,
                    on_output=lambda line: console.print(line, end=""),
                )

            rc = runner.run_parallel(_make_pool)
            if rc != 0:
                console.print(f"[red]Session ended with rc={rc}[/red]")
                raise typer.Exit(code=rc)
        else:
            # Serial mode
            rc = runner.run_serial()
            if rc != 0:
                console.print(f"[red]Session ended with rc={rc}[/red]")
                raise typer.Exit(code=rc)
    else:
        # -- TUI mode --
        from .tui.app import ResearchApp  # noqa: E402

        if workers > 0:
            from .parallel import WorkerPool  # noqa: E402

            config = state.load_config()
            gpu_mem = config.get("workers", {}).get("gpu_mem_per_worker_mb", 8192)

            def _make_pool_tui() -> WorkerPool:
                return WorkerPool(
                    repo_path=repo,
                    state=state,
                    agent_factory=lambda: Agent(create_agent(agent_name)),
                    skill_content=runner._compose_program("experiment"),
                    max_workers=workers,
                    gpu_mem_per_worker_mb=gpu_mem,
                    on_output=lambda line: state.append_log(
                        {"event": "output", "message": line.rstrip()}
                    ),
                )

            tui_runner = lambda: runner.run_parallel(_make_pool_tui)
        else:
            tui_runner = runner.run_serial

        tui_app = ResearchApp(
            repo_path=str(repo),
            state=state,
            runner=tui_runner,
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


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------


@app.command()
def review(
    repo: Path = typer.Argument(..., help="Path to target repo"),
    skip: bool = typer.Option(False, help="Skip the pending review"),
    approve_all: bool = typer.Option(False, "--approve-all", help="Approve all and continue"),
    reject: list[str] = typer.Option([], help="Reject specific frontier IDs"),
    priority: list[str] = typer.Option([], help="Set priority: FRONTIER_ID=PRIORITY"),
) -> None:
    """Show or act on a pending human review."""
    from .state import ResearchState

    research_dir = _resolve_research_dir(repo)
    if not research_dir.is_dir():
        console.print("[red]No .research directory found[/red]")
        raise typer.Exit(code=1)

    state = ResearchState(research_dir)
    pending = state.get_awaiting_review()

    if pending is None:
        console.print("[dim]No pending review.[/dim]")
        return

    review_type = pending.get("type", "unknown")
    requested_at = pending.get("requested_at", "")

    if skip:
        state.clear_awaiting_review()
        state.append_log({"event": "review_skipped", "review_type": review_type})
        console.print(f"Skipped review: {review_type}")
        return

    if approve_all:
        state.clear_awaiting_review()
        state.append_log({"event": "review_completed", "review_type": review_type})
        console.print(f"Approved: {review_type}")
        return

    if reject:
        graph = state.load_graph()
        for fid in reject:
            for item in graph.get("frontier", []):
                if item.get("id") == fid:
                    item["status"] = "rejected"
        state.save_graph(graph)
        state.clear_awaiting_review()
        state.append_log({"event": "review_completed", "review_type": review_type})
        console.print(f"Rejected {reject} and approved remaining")
        return

    if priority:
        graph = state.load_graph()
        for spec in priority:
            fid, _, pval = spec.partition("=")
            for item in graph.get("frontier", []):
                if item.get("id") == fid:
                    item["priority"] = int(pval)
        state.save_graph(graph)
        console.print(f"Updated priorities: {priority}")
        return

    # Default: show pending review info
    console.print(f"[bold]Pending review:[/bold] {review_type}")
    console.print(f"[dim]Requested at: {requested_at}[/dim]")
    console.print()
    console.print("Actions:")
    console.print("  --approve-all    Approve and continue")
    console.print("  --skip           Skip this review")
    console.print("  --reject ID      Reject a frontier item")
    console.print("  --priority ID=N  Adjust priority")


# ---------------------------------------------------------------------------
# inject
# ---------------------------------------------------------------------------


@app.command()
def inject(
    repo: Path = typer.Argument(..., help="Path to target repo"),
    desc: str = typer.Option(..., help="Experiment description"),
    priority: int = typer.Option(3, help="Priority (1-5, higher=first)"),
) -> None:
    """Inject a human-authored experiment into the frontier."""
    from .state import ResearchState

    research_dir = _resolve_research_dir(repo)
    if not research_dir.is_dir():
        console.print("[red]No .research directory found[/red]")
        raise typer.Exit(code=1)

    state = ResearchState(research_dir)
    graph = state.load_graph()
    counter = graph.get("counters", {}).get("frontier", 0) + 1
    item = {
        "id": f"frontier-{counter:03d}",
        "description": desc,
        "priority": priority,
        "status": "approved",
        "selection_reason_code": "human_injected",
        "hypothesis_id": "",
        "experiment_spec_id": "",
    }
    graph.setdefault("frontier", []).append(item)
    graph.setdefault("counters", {})["frontier"] = counter
    state.save_graph(graph)
    state.append_log({"event": "human_injected", "frontier_id": item["id"]})
    console.print(f"Injected: {item['id']} — {desc}")


# ---------------------------------------------------------------------------
# constrain
# ---------------------------------------------------------------------------


@app.command()
def constrain(
    repo: Path = typer.Argument(..., help="Path to target repo"),
    add: str = typer.Option("", help="Add a constraint"),
) -> None:
    """Add user constraints for the research direction."""
    from .state import ResearchState

    research_dir = _resolve_research_dir(repo)
    if not research_dir.is_dir():
        console.print("[red]No .research directory found[/red]")
        raise typer.Exit(code=1)

    state = ResearchState(research_dir)
    path = research_dir / "user_constraints.md"

    if add:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"- {add}\n")
        state.append_log({"event": "goal_updated"})
        console.print(f"Added constraint: {add}")
    else:
        if path.exists():
            console.print(path.read_text(encoding="utf-8"))
        else:
            console.print("[dim]No constraints set.[/dim]")
