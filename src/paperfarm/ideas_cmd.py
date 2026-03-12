"""Projected backlog subcommand for the research-v1 compatibility view."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from paperfarm.config import RESEARCH_PROTOCOL, load_config
from paperfarm.idea_pool import IdeaBacklog

ideas_app = typer.Typer(help="Inspect the projected experiment backlog in idea_pool.json.")


def _get_pool() -> IdeaBacklog:
    return IdeaBacklog(Path.cwd() / ".research" / "idea_pool.json")


def _get_protocol() -> str:
    research_dir = Path.cwd() / ".research"
    return load_config(research_dir, strict=True).protocol


def _deny_projection_mutation() -> None:
    console = Console(stderr=True)
    try:
        protocol = _get_protocol()
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    if protocol != RESEARCH_PROTOCOL:
        console.print(
            f"[red]Unsupported research.protocol={protocol!r}.[/red]\n"
            f"[dim]Mutations are disabled because only {RESEARCH_PROTOCOL!r} is supported.[/dim]"
        )
        raise typer.Exit(code=1)
    console.print(
        "[red]idea_pool.json is a read-only projected backlog under research-v1.[/red]\n"
        "[dim]Mutate frontier state through the manager/critic/runtime, not via `ideas add/delete/prioritize`.[/dim]"
    )
    raise typer.Exit(code=1)


@ideas_app.command("list")
def list_ideas(
    status: str = typer.Option(None, help="Filter by status"),
    category: str = typer.Option(None, help="Filter by category"),
) -> None:
    """List the projected backlog rows currently runnable by research-v1."""
    pool = _get_pool()
    ideas = pool.all_ideas()
    if status:
        ideas = [i for i in ideas if i["status"] == status]
    if category:
        ideas = [i for i in ideas if i.get("category") == category]

    console = Console()
    table = Table(title="Projected Backlog")
    table.add_column("ID")
    table.add_column("Frontier")
    table.add_column("Status")
    table.add_column("Pri")
    table.add_column("Reason")
    table.add_column("Description")

    for idea in sorted(ideas, key=lambda x: x.get("priority", 99)):
        table.add_row(
            idea["id"],
            idea.get("frontier_id", ""),
            idea["status"],
            str(idea.get("priority", "")),
            idea.get("reason_code", "") or idea.get("selection_reason_code", ""),
            idea.get("description", "")[:60],
        )
    console.print(table)


@ideas_app.command()
def add(
    description: str = typer.Argument(..., help="Idea description"),
    category: str = typer.Option("general", help="Idea category"),
    priority: int = typer.Option(5, help="Priority (lower is higher)"),
) -> None:
    """Mutation is disabled because the backlog is a projection of research_graph.json."""
    del description, category, priority
    _deny_projection_mutation()


@ideas_app.command()
def delete(idea_id: str = typer.Argument(..., help="Idea ID to delete")) -> None:
    """Mutation is disabled because the backlog is a projection of research_graph.json."""
    del idea_id
    _deny_projection_mutation()


@ideas_app.command()
def prioritize(
    idea_id: str = typer.Argument(..., help="Idea ID"),
    priority: int = typer.Argument(..., help="New priority value"),
) -> None:
    """Mutation is disabled because the backlog is a projection of research_graph.json."""
    del idea_id, priority
    _deny_projection_mutation()
