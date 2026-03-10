"""Open Researcher CLI — research workflow framework for AI agents."""

from pathlib import Path

import typer
from rich.console import Console

from open_researcher.config_cmd import config_app
from open_researcher.ideas_cmd import ideas_app
from open_researcher.logs_cmd import logs_app

console = Console()

app = typer.Typer(
    name="open-researcher",
    help="Research workflow framework for AI agents. Initialize automated experiment tracking in any repo.",
)

app.add_typer(ideas_app, name="ideas")
app.add_typer(config_app, name="config")
app.add_typer(logs_app, name="logs")


@app.command()
def demo():
    """Launch the TUI with sample data — no agent or project needed."""
    from open_researcher.demo_cmd import do_demo

    do_demo()


@app.command()
def init(tag: str = typer.Option(None, help="Experiment tag (e.g. mar8). Defaults to today's date.")):
    """Initialize .research/ directory in the current repo."""
    from open_researcher.init_cmd import do_init

    do_init(repo_path=Path.cwd(), tag=tag)


@app.command()
def status(
    sparkline: bool = typer.Option(False, "--sparkline", help="Show metric sparkline"),
):
    """Show current research progress."""
    from open_researcher.status_cmd import print_status

    print_status(Path.cwd(), sparkline=sparkline)


@app.command()
def results(
    chart: str = typer.Option(None, "--chart", help="Show chart for metric (use 'primary' or metric name)"),
    json_out: bool = typer.Option(False, "--json", help="Output as JSON"),
    last: int = typer.Option(None, "--last", help="Show only last N experiments"),
):
    """Print experiment results table."""
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
    """Export experiment report as Markdown."""
    from open_researcher.export_cmd import do_export

    do_export(Path.cwd())


@app.command()
def doctor():
    """Run health checks on the research environment."""
    from open_researcher.doctor_cmd import print_doctor

    print_doctor(Path.cwd())


@app.command()
def run(
    agent: str = typer.Option(None, help="Agent to use (claude-code, codex, aider, opencode)."),
    multi: bool = typer.Option(False, "--multi", help="Enable dual-agent mode (Idea + Experiment)."),
    idea_agent: str = typer.Option(None, "--idea-agent", help="Agent for idea generation (multi mode)."),
    exp_agent: str = typer.Option(None, "--exp-agent", help="Agent for experiments (multi mode)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the command without executing."),
):
    """Launch AI agent(s) to run the research workflow."""
    if multi or idea_agent or exp_agent:
        from open_researcher.run_cmd import do_run_multi

        do_run_multi(
            repo_path=Path.cwd(),
            idea_agent_name=idea_agent or agent,
            exp_agent_name=exp_agent or agent,
            dry_run=dry_run,
        )
    else:
        from open_researcher.run_cmd import do_run

        do_run(repo_path=Path.cwd(), agent_name=agent, dry_run=dry_run)


@app.command()
def start(
    agent: str = typer.Option(None, help="Agent to use (claude-code, codex, aider, opencode)."),
    tag: str = typer.Option(None, help="Experiment tag (e.g. mar10). Defaults to today's date."),
    multi: bool = typer.Option(False, "--multi", help="Enable dual-agent mode (Idea + Experiment)."),
    idea_agent: str = typer.Option(None, "--idea-agent", help="Agent for idea generation (multi mode)."),
    exp_agent: str = typer.Option(None, "--exp-agent", help="Agent for experiments (multi mode)."),
    headless: bool = typer.Option(False, "--headless", help="Run without TUI, output JSON Lines to stdout."),
    goal: str = typer.Option(None, "--goal", help="Research goal (required for --headless)."),
    max_experiments: int = typer.Option(0, "--max-experiments", help="Stop after N experiments (0 = unlimited)."),
):
    """Zero-config start: auto-init, analyze repo, confirm plan, then run experiments."""
    if headless:
        if not goal:
            console.print("[red]--goal is required when using --headless.[/red]")
            raise typer.Exit(code=1)
        from open_researcher.headless import do_start_headless

        do_start_headless(
            repo_path=Path.cwd(),
            goal=goal,
            max_experiments=max_experiments,
            agent_name=agent,
            tag=tag,
            multi=multi,
            idea_agent_name=idea_agent,
            exp_agent_name=exp_agent,
        )
    else:
        from open_researcher.start_cmd import do_start

        do_start(
            repo_path=Path.cwd(),
            agent_name=agent,
            tag=tag,
            multi=multi,
            idea_agent_name=idea_agent,
            exp_agent_name=exp_agent,
        )


if __name__ == "__main__":
    app()
