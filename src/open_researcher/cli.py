"""Open Researcher CLI — research workflow framework for AI agents."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from open_researcher.bootstrap import format_bootstrap_dry_run
from open_researcher.config import ResearchConfig, load_config
from open_researcher.config_cmd import config_app
from open_researcher.hub_cmd import hub_app
from open_researcher.ideas_cmd import ideas_app
from open_researcher.logs_cmd import logs_app
from open_researcher.workflow_options import build_workflow_selection

console = Console()

app = typer.Typer(
    name="open-researcher",
    help=(
        "Research workflow framework for AI agents.\n\n"
        "Quick start:\n"
        "  1. open-researcher run          Launch or resume research (TUI)\n"
        "  2. open-researcher status        Check current progress\n"
        "  3. open-researcher results       View experiment results\n"
        "  4. open-researcher doctor        Health check\n"
        "  5. open-researcher demo          Try with sample data\n"
    ),
)

app.add_typer(ideas_app, name="ideas")
app.add_typer(config_app, name="config")
app.add_typer(logs_app, name="logs")
app.add_typer(hub_app, name="hub")


def _print_notices(notices: list[str]) -> None:
    for notice in notices:
        console.print(f"[dim]{notice}[/dim]")


def _print_bootstrap_dry_run(
    repo_path: Path,
    *,
    frontend_mode: str,
    goal: str | None,
    max_experiments: int,
    workers: int | None,
) -> None:
    cfg = ResearchConfig()
    console.print("[bold]Workflow:[/bold] bootstrap")
    console.print(f"[bold]Frontend:[/bold] {frontend_mode}")
    console.print(f"[bold]Working directory:[/bold] {repo_path}")
    if workers is not None:
        console.print(f"[bold]Workers:[/bold] {workers}")
    if goal:
        console.print(f"[bold]Goal:[/bold] {goal}")
    if max_experiments > 0:
        console.print(f"[bold]Max experiments:[/bold] {max_experiments}")
    for line in format_bootstrap_dry_run(repo_path, repo_path / ".research", cfg):
        console.print(line)
    console.print("\n[dim]Dry run -- no bootstrap or agent launch performed.[/dim]")


def _print_continue_dry_run(
    repo_path: Path,
    *,
    frontend_mode: str,
    workers: int | None,
    max_experiments: int,
) -> None:
    research_dir = repo_path / ".research"
    console.print("[bold]Workflow:[/bold] continue")
    console.print(f"[bold]Frontend:[/bold] {frontend_mode}")
    console.print(f"[bold]Working directory:[/bold] {repo_path}")
    if workers is not None:
        console.print(f"[bold]Workers:[/bold] {workers}")
    if max_experiments > 0:
        console.print(f"[bold]Max experiments:[/bold] {max_experiments}")
    try:
        cfg = load_config(research_dir, strict=True)
        for line in format_bootstrap_dry_run(repo_path, research_dir, cfg):
            console.print(line)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
    console.print("\n[dim]Dry run -- no runtime launched.[/dim]")


def _dispatch_workflow(
    *,
    repo_path: Path,
    agent: str | None,
    workers: Optional[int],
    mode: str = "interactive",
    headless: bool = False,
    tag: str | None = None,
    goal: str | None = None,
    max_experiments: int = 0,
    token_budget: int = 0,
    dry_run: bool = False,
    force_bootstrap: bool = False,
) -> None:
    try:
        selection = build_workflow_selection(
            agent=agent,
            mode=mode,
            headless=headless,
            workers=workers,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    _print_notices(selection.notices)
    research_dir = repo_path / ".research"
    use_bootstrap_flow = force_bootstrap or not research_dir.is_dir() or tag is not None

    if research_dir.is_dir() and not force_bootstrap and goal is not None:
        console.print("[red]--goal is only valid when bootstrapping a new workflow.[/red]")
        raise typer.Exit(code=1)

    if use_bootstrap_flow:
        if selection.frontend_mode == "headless" and not goal:
            console.print("[red]--goal is required when using `--mode headless`.[/red]")
            raise typer.Exit(code=1)
        if dry_run:
            _print_bootstrap_dry_run(
                repo_path,
                frontend_mode=selection.frontend_mode,
                goal=goal,
                max_experiments=max_experiments,
                workers=selection.workers,
            )
            return
        if not force_bootstrap:
            if not research_dir.is_dir():
                console.print("[dim]No `.research/` found; bootstrapping before run.[/dim]")
            else:
                console.print("[dim]Using bootstrap workflow for this run.[/dim]")
        if selection.frontend_mode == "headless":
            from open_researcher.headless import do_start_headless

            try:
                exit_code = do_start_headless(
                    repo_path=repo_path,
                    goal=goal or "",
                    max_experiments=max_experiments,
                    token_budget=token_budget,
                    agent_name=selection.primary_agent_name,
                    tag=tag,
                    workers=selection.workers,
                )
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(code=1)
            if exit_code:
                raise typer.Exit(code=exit_code)
            return

        from open_researcher.run_cmd import do_start

        try:
            exit_code = do_start(
                repo_path=repo_path,
                agent_name=selection.primary_agent_name,
                tag=tag,
                workers=selection.workers,
                goal=goal,
                max_experiments=max_experiments,
                token_budget=token_budget,
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)
        if exit_code:
            raise typer.Exit(code=exit_code)
        return

    if selection.frontend_mode == "headless":
        if dry_run:
            _print_continue_dry_run(
                repo_path,
                frontend_mode=selection.frontend_mode,
                workers=selection.workers,
                max_experiments=max_experiments,
            )
            return
        from open_researcher.headless import do_run_headless

        try:
            exit_code = do_run_headless(
                repo_path=repo_path,
                agent_name=selection.primary_agent_name,
                max_experiments=max_experiments,
                token_budget=token_budget,
                workers=selection.workers,
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)
        if exit_code:
            raise typer.Exit(code=exit_code)
    else:
        from open_researcher.run_cmd import do_run

        try:
            exit_code = do_run(
                repo_path=repo_path,
                agent_name=selection.primary_agent_name,
                dry_run=dry_run,
                workers=selection.workers,
                max_experiments=max_experiments,
                token_budget=token_budget,
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1)
        if exit_code:
            raise typer.Exit(code=exit_code)


@app.command()
def demo(
    serve: bool = typer.Option(False, "--serve", help="Serve the TUI in a browser via textual-serve."),
    port: int = typer.Option(8000, "--port", help="Port for the web server (only used with --serve)."),
):
    """Launch the TUI with sample data — no agent or project needed."""
    from open_researcher.demo_cmd import do_demo

    do_demo(serve=serve, port=port)


@app.command()
def init(tag: str = typer.Option(None, help="Experiment tag (e.g. mar8). Defaults to today's date.")):
    """Initialize .research/ directory in the current repo.

    \b
    Examples:
      open-researcher init               # auto-tag with today's date
      open-researcher init --tag mar10   # use custom tag
    """
    from open_researcher.init_cmd import do_init

    do_init(repo_path=Path.cwd(), tag=tag)


@app.command()
def status(
    sparkline: bool = typer.Option(False, "--sparkline", help="Show metric sparkline"),
):
    """Show current research progress.

    \b
    Examples:
      open-researcher status                # summary with experiment counts
      open-researcher status --sparkline    # include metric trend sparkline
    """
    from open_researcher.status_cmd import print_status

    print_status(Path.cwd(), sparkline=sparkline)


@app.command()
def results(
    chart: str = typer.Option(None, "--chart", help="Show chart for metric (use 'primary' or metric name)"),
    json_out: bool = typer.Option(False, "--json", help="Output as JSON"),
    last: int = typer.Option(None, "--last", help="Show only last N experiments"),
):
    """Print experiment results table.

    \b
    Examples:
      open-researcher results                    # full table
      open-researcher results --chart primary     # metric trend chart
      open-researcher results --last 5            # last 5 experiments
      open-researcher results --json              # machine-readable JSON
    """
    from open_researcher.results_cmd import print_results, print_results_chart, print_results_json

    if json_out:
        print_results_json(Path.cwd())
    elif chart is not None:
        metric = chart if chart else None
        print_results_chart(Path.cwd(), metric=metric, last=last)
    else:
        print_results(Path.cwd())


@app.command()
def export():
    """Export experiment report as Markdown.

    \b
    Examples:
      open-researcher export    # writes report to .research/report.md
    """
    from open_researcher.export_cmd import do_export

    do_export(Path.cwd())


@app.command()
def doctor():
    """Run health checks on the research environment.

    \b
    Examples:
      open-researcher doctor    # check agents, GPU, .research/ integrity
    """
    from open_researcher.doctor_cmd import print_doctor

    print_doctor(Path.cwd())


@app.command()
def run(
    agent: str = typer.Option(None, help="Agent to use (claude-code, codex, aider, opencode, kimi-cli, gemini-cli)."),
    tag: str = typer.Option(None, help="Experiment tag when bootstrapping a new workflow."),
    mode: str = typer.Option(
        "interactive",
        "--mode",
        help="Run mode: `interactive` (TUI) or `headless` (requires --goal).",
    ),
    headless: bool = typer.Option(False, "--headless", hidden=True, help="Deprecated; use `--mode headless`."),
    workers: Optional[int] = typer.Option(
        None,
        "--workers",
        help="Experiment worker count. `1` runs serially, `>1` enables parallel experiment workers.",
    ),
    goal: str = typer.Option(None, "--goal", help="Research goal (required for headless; only valid on first run)."),
    max_experiments: int = typer.Option(0, "--max-experiments", help="Stop after N experiments (0 = unlimited)."),
    token_budget: int = typer.Option(0, "--token-budget", help="Stop/warn after N total tokens (0 = unlimited)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the command without executing."),
):
    """Launch or resume the research workflow.

    \b
    First run (bootstrap): creates .research/, analyzes the repo, and starts experimenting.
    Subsequent runs: resumes the existing workflow from where it left off.

    \b
    Examples:
      open-researcher run                          # Interactive TUI, auto-detect agent
      open-researcher run --agent claude-code      # Use a specific agent
      open-researcher run --mode headless --goal "reduce val_loss"  # Headless mode
      open-researcher run --dry-run                # Preview without executing
      open-researcher run --max-experiments 10     # Stop after 10 experiments
    """
    _dispatch_workflow(
        repo_path=Path.cwd(),
        agent=agent,
        tag=tag,
        mode=mode,
        headless=headless,
        workers=workers,
        goal=goal,
        max_experiments=max_experiments,
        token_budget=token_budget,
        dry_run=dry_run,
    )


@app.command(hidden=True)
def start(
    agent: str = typer.Option(None, help="Agent to use (claude-code, codex, aider, opencode, kimi-cli, gemini-cli)."),
    tag: str = typer.Option(None, help="Experiment tag (e.g. mar10). Defaults to today's date."),
    mode: str = typer.Option("interactive", "--mode", help="Run mode: `interactive` or `headless`."),
    headless: bool = typer.Option(False, "--headless", hidden=True, help="Deprecated; use `--mode headless`."),
    workers: Optional[int] = typer.Option(
        None,
        "--workers",
        help="Experiment worker count. `1` runs serially, `>1` enables parallel experiment workers.",
    ),
    goal: str = typer.Option(None, "--goal", help="Research goal (required for `--mode headless`)."),
    max_experiments: int = typer.Option(0, "--max-experiments", help="Stop after N experiments (0 = unlimited)."),
    token_budget: int = typer.Option(0, "--token-budget", help="Stop/warn after N total tokens (0 = unlimited)."),
):
    """Legacy alias for bootstrap mode; prefer `run` for both new and existing workflows."""
    typer.echo("`start` is deprecated; use `run` instead.", err=True)
    _dispatch_workflow(
        repo_path=Path.cwd(),
        agent=agent,
        tag=tag,
        mode=mode,
        headless=headless,
        workers=workers,
        goal=goal,
        max_experiments=max_experiments,
        token_budget=token_budget,
        force_bootstrap=True,
    )


if __name__ == "__main__":
    app()
