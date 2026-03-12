"""Shared agent resolution helpers for orchestration entrypoints."""

from rich.console import Console

from paperfarm.agents import detect_agent, get_agent

console = Console()


def resolve_agent(
    agent_name: str | None,
    agent_configs: dict | None = None,
    *,
    detect_agent_fn=detect_agent,
    get_agent_fn=get_agent,
    console_obj: Console | None = None,
):
    """Resolve agent by name or auto-detect, with per-agent config support."""
    configs = agent_configs or {}
    console_ref = console_obj or console

    if agent_name:
        try:
            return get_agent_fn(agent_name, config=configs.get(agent_name))
        except KeyError as exc:
            console_ref.print(f"[red]Error:[/red] {exc}")
            raise SystemExit(1) from exc

    agent = detect_agent_fn(configs=configs)
    if agent is None:
        console_ref.print(
            "[red]Error:[/red] No supported AI agent found.\n"
            "Install one of: claude (Claude Code), codex, aider, opencode, kimi, gemini\n"
            "Or specify with: --agent <name>"
        )
        raise SystemExit(1)

    console_ref.print(f"[green]Auto-detected agent:[/green] {agent.name}")
    return agent
