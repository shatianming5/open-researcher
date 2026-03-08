"""Open Researcher CLI — research workflow framework for AI agents."""

from pathlib import Path

import typer

app = typer.Typer(
    name="open-researcher",
    help="Research workflow framework for AI agents. "
         "Initialize automated experiment tracking in any repo.",
)


@app.command()
def init(tag: str = typer.Option(None, help="Experiment tag (e.g. mar8). Defaults to today's date.")):
    """Initialize .research/ directory in the current repo."""
    from open_researcher.init_cmd import do_init
    do_init(repo_path=Path.cwd(), tag=tag)


@app.command()
def status():
    """Show current research progress."""
    from open_researcher.status_cmd import print_status
    print_status(Path.cwd())


@app.command()
def results():
    """Print experiment results table."""
    from open_researcher.results_cmd import print_results
    print_results(Path.cwd())


@app.command()
def dashboard(port: int = typer.Option(8384, help="Dashboard port")):
    """Launch web dashboard."""
    import uvicorn
    from open_researcher.dashboard.app import create_app
    web_app = create_app(Path.cwd())
    typer.echo(f"Starting dashboard at http://localhost:{port}")
    uvicorn.run(web_app, host="0.0.0.0", port=port)


@app.command()
def export():
    """Export experiment report as Markdown."""
    from open_researcher.export_cmd import do_export
    do_export(Path.cwd())


if __name__ == "__main__":
    app()
