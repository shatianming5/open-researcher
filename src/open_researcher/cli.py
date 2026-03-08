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
    typer.echo("status called")


@app.command()
def results():
    """Print experiment results table."""
    typer.echo("results called")


@app.command()
def dashboard(port: int = typer.Option(8384, help="Dashboard port")):
    """Launch web dashboard."""
    typer.echo(f"dashboard called on port {port}")


@app.command()
def export():
    """Export experiment report as Markdown."""
    typer.echo("export called")


if __name__ == "__main__":
    app()
