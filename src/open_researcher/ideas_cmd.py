"""Ideas subcommand — manage the idea pool."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from open_researcher.idea_pool import IdeaPool

ideas_app = typer.Typer(help="Manage the idea pool.")


def _get_pool() -> IdeaPool:
    return IdeaPool(Path.cwd() / ".research" / "idea_pool.json")


@ideas_app.command("list")
def list_ideas(
    status: str = typer.Option(None, help="Filter by status"),
    category: str = typer.Option(None, help="Filter by category"),
) -> None:
    """List all ideas."""
    pool = _get_pool()
    ideas = pool.all_ideas()
    if status:
        ideas = [i for i in ideas if i["status"] == status]
    if category:
        ideas = [i for i in ideas if i.get("category") == category]

    console = Console()
    table = Table(title="Ideas")
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Pri")
    table.add_column("Category")
    table.add_column("Description")

    for idea in sorted(ideas, key=lambda x: x.get("priority", 99)):
        table.add_row(
            idea["id"],
            idea["status"],
            str(idea.get("priority", "")),
            idea.get("category", ""),
            idea.get("description", "")[:60],
        )
    console.print(table)


@ideas_app.command()
def add(
    description: str = typer.Argument(..., help="Idea description"),
    category: str = typer.Option("general", help="Idea category"),
    priority: int = typer.Option(5, help="Priority (lower is higher)"),
) -> None:
    """Add a new idea."""
    pool = _get_pool()
    idea = pool.add(description, source="user", category=category, priority=priority)
    print(f"Added: {idea['id']}")


@ideas_app.command()
def delete(idea_id: str = typer.Argument(..., help="Idea ID to delete")) -> None:
    """Delete an idea."""
    pool = _get_pool()
    pool.delete(idea_id)
    print(f"Deleted: {idea_id}")


@ideas_app.command()
def prioritize(
    idea_id: str = typer.Argument(..., help="Idea ID"),
    priority: int = typer.Argument(..., help="New priority value"),
) -> None:
    """Set priority for an idea."""
    pool = _get_pool()
    pool.update_priority(idea_id, priority)
    print(f"Updated {idea_id} priority to {priority}")
