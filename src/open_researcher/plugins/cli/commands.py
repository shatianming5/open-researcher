"""Command registry for the CLI plugin.

Each command is a thin wrapper that emits events through the kernel bus,
delegating actual work to the appropriate plugins.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CommandSpec:
    """Specification for a CLI command."""

    name: str
    help: str
    handler: Callable[..., Any] | None = None
    options: list[OptionSpec] = field(default_factory=list)


@dataclass
class OptionSpec:
    """Specification for a CLI command option."""

    name: str
    type: type = str
    default: Any = None
    help: str = ""
    required: bool = False


class CommandRegistry:
    """Collects CLI command definitions for lazy Typer registration."""

    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def register(self, spec: CommandSpec) -> None:
        self._commands[spec.name] = spec

    def get(self, name: str) -> CommandSpec:
        try:
            return self._commands[name]
        except KeyError:
            raise KeyError(f"Command {name!r} not registered") from None

    def all(self) -> list[CommandSpec]:
        return list(self._commands.values())

    def names(self) -> list[str]:
        return list(self._commands.keys())
