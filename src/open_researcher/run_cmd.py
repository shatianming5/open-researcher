"""Run command — launch an AI agent to execute the research workflow."""

import sys
import threading
import time
from pathlib import Path

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from open_researcher.agents import detect_agent, get_agent
from open_researcher.status_cmd import parse_research_state

console = Console()

_MAX_OUTPUT_LINES = 15


def _build_stats_panel(repo_path: Path) -> Panel:
    """Build the top panel showing experiment statistics."""
    try:
        state = parse_research_state(repo_path)
    except Exception:
        return Panel("[dim]Waiting for data...[/dim]", title="Stats")

    from open_researcher.status_cmd import PHASE_NAMES

    lines = []
    phase = state.get("phase", 1)
    lines.append(f"[bold]Phase:[/bold] {PHASE_NAMES.get(phase, 'Unknown')}")
    lines.append(f"[bold]Branch:[/bold] {state.get('branch', 'N/A')}    [bold]Mode:[/bold] {state.get('mode', 'N/A')}")

    total = state.get("total", 0)
    if total > 0:
        lines.append(
            f"[bold]Experiments:[/bold] {total} total | "
            f"[green]{state['keep']} kept[/green] | "
            f"[yellow]{state['discard']} discarded[/yellow] | "
            f"[red]{state['crash']} crashed[/red]"
        )
        pm = state.get("primary_metric", "")
        direction = state.get("direction", "")
        arrow = "\u2191" if direction == "higher_is_better" else "\u2193"
        lines.append(f"[bold]Primary Metric:[/bold] {pm} {arrow}")
        if state.get("baseline_value") is not None:
            lines.append(f"  Baseline: {state['baseline_value']:.4f}   Current: {state.get('current_value', 0):.4f}   Best: {state.get('best_value', 0):.4f}")

        recent = state.get("recent", [])
        if recent:
            lines.append("")
            for r in recent[-5:]:
                st = r["status"]
                color = {"keep": "green", "discard": "yellow", "crash": "red"}.get(st, "white")
                lines.append(f"  [{color}][{st}][/{color}] {r['description']}  {r['primary_metric']}={r['metric_value']}")
    else:
        lines.append("[dim]No experiments yet -- agent is starting...[/dim]")

    return Panel("\n".join(lines), title="Open Researcher", border_style="blue")


def _build_output_panel(output_lines: list[str], agent_name: str) -> Panel:
    """Build the bottom panel showing agent stdout."""
    text = "\n".join(output_lines[-_MAX_OUTPUT_LINES:]) if output_lines else "[dim]Waiting for agent output...[/dim]"
    return Panel(text, title=f"Agent: {agent_name}", border_style="green")


def do_run(repo_path: Path, agent_name: str | None, dry_run: bool) -> None:
    """Execute the research workflow using an AI agent."""
    research = repo_path / ".research"
    if not research.is_dir():
        console.print("[red]Error:[/red] .research/ not found. Run 'open-researcher init' first.")
        raise SystemExit(1)

    program_md = research / "program.md"
    if not program_md.exists():
        console.print("[red]Error:[/red] .research/program.md not found.")
        raise SystemExit(1)

    # Resolve agent
    if agent_name:
        try:
            agent = get_agent(agent_name)
        except KeyError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)
    else:
        agent = detect_agent()
        if agent is None:
            console.print(
                "[red]Error:[/red] No supported AI agent found.\n"
                "Install one of: claude (Claude Code), codex, aider, opencode\n"
                "Or specify with: open-researcher run --agent <name>"
            )
            raise SystemExit(1)
        console.print(f"[green]Auto-detected agent:[/green] {agent.name}")

    # Dry run
    if dry_run:
        cmd = agent.build_command(program_md, repo_path)
        console.print(f"[bold]Agent:[/bold] {agent.name}")
        console.print(f"[bold]Command:[/bold] {' '.join(cmd[:3])}...")
        console.print(f"[bold]Working directory:[/bold] {repo_path}")
        console.print("\n[dim]Dry run -- no agent launched.[/dim]")
        return

    # Launch agent with TUI
    console.print(f"[green]Launching {agent.name}...[/green]")
    output_lines: list[str] = []
    agent_done = threading.Event()
    exit_code = 0

    def _run_agent():
        nonlocal exit_code

        def on_output(line: str):
            output_lines.append(line)
            log_path = research / "run.log"
            with open(log_path, "a") as f:
                f.write(line + "\n")

        exit_code = agent.run(repo_path, on_output=on_output)
        agent_done.set()

    agent_thread = threading.Thread(target=_run_agent, daemon=True)
    agent_thread.start()

    try:
        with Live(console=console, refresh_per_second=1, transient=True) as live:
            while not agent_done.is_set():
                layout = Layout()
                layout.split_column(
                    Layout(name="stats", ratio=2),
                    Layout(name="output", ratio=1),
                )
                layout["stats"].update(_build_stats_panel(repo_path))
                layout["output"].update(_build_output_panel(output_lines, agent.name))
                live.update(layout)
                agent_done.wait(timeout=1.0)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        raise SystemExit(130)

    agent_thread.join(timeout=5)

    if exit_code == 0:
        console.print(f"\n[green]Agent {agent.name} completed successfully.[/green]")
    else:
        console.print(f"\n[red]Agent {agent.name} exited with code {exit_code}.[/red]")

    # Print final status
    from open_researcher.status_cmd import print_status
    print_status(repo_path)
