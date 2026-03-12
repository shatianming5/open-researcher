"""Config subcommand — view and validate research configuration."""

from pathlib import Path

import typer
from rich.console import Console
from rich.syntax import Syntax

config_app = typer.Typer(help="View and manage research configuration.")


@config_app.command()
def show() -> None:
    """Show current configuration."""
    config_path = Path.cwd() / ".research" / "config.yaml"
    if not config_path.exists():
        print("[ERROR] No .research/config.yaml found.")
        raise SystemExit(1)
    console = Console()
    text = config_path.read_text()
    console.print(Syntax(text, "yaml"))


@config_app.command()
def validate() -> None:
    """Validate configuration completeness."""
    from paperfarm.config import load_config

    research = Path.cwd() / ".research"
    if not research.exists():
        print("[ERROR] No .research/ directory found.")
        raise SystemExit(1)
    cfg = load_config(research)
    console = Console()
    issues: list[str] = []
    if not cfg.primary_metric:
        issues.append("metrics.primary.name is empty")
    if not cfg.direction:
        issues.append("metrics.primary.direction is empty")
    if issues:
        for issue in issues:
            console.print(f"[yellow]WARN:[/yellow] {issue}")
    else:
        console.print("[green]Configuration is valid.[/green]")
