"""Agent adapter registry — discover, list, and instantiate agents."""

from open_researcher.agents.base import AgentAdapter

_REGISTRY: dict[str, type[AgentAdapter]] = {}


def register(cls: type[AgentAdapter]) -> type[AgentAdapter]:
    """Decorator to register an agent adapter class."""
    _REGISTRY[cls.name] = cls
    return cls


def list_agents() -> dict[str, type[AgentAdapter]]:
    """Return all registered agent adapter classes."""
    _ensure_loaded()
    return dict(_REGISTRY)


def get_agent(name: str, config: dict | None = None) -> AgentAdapter:
    """Instantiate an agent adapter by name. Raises KeyError if unknown."""
    _ensure_loaded()
    if name not in _REGISTRY:
        raise KeyError(f"Unknown agent: {name!r}. Available: {', '.join(_REGISTRY)}")
    return _REGISTRY[name](config=config)


def detect_agent(configs: dict | None = None) -> AgentAdapter | None:
    """Auto-detect the first installed agent. Returns None if none found."""
    _ensure_loaded()
    configs = configs or {}
    preference = ["claude-code", "codex", "aider", "opencode", "kimi-cli", "gemini-cli"]
    for agent_name in preference:
        if agent_name in _REGISTRY:
            adapter = _REGISTRY[agent_name](config=configs.get(agent_name))
            if adapter.check_installed():
                return adapter
    return None


_loaded = False


def _ensure_loaded():
    """Lazy-load all built-in adapters to populate the registry."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    from open_researcher.agents import (
        aider,  # noqa: F401
        claude_code,  # noqa: F401
        codex,  # noqa: F401
        gemini,  # noqa: F401
        kimi,  # noqa: F401
        opencode,  # noqa: F401
    )
