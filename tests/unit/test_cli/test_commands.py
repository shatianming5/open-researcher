"""Tests for the CLI command registry."""
import pytest


def test_command_registry_register_and_get():
    from open_researcher.plugins.cli.commands import CommandRegistry, CommandSpec

    registry = CommandRegistry()
    spec = CommandSpec(name="run", help="Run a research session")
    registry.register(spec)

    result = registry.get("run")
    assert result.name == "run"
    assert result.help == "Run a research session"


def test_command_registry_get_missing():
    from open_researcher.plugins.cli.commands import CommandRegistry

    registry = CommandRegistry()
    with pytest.raises(KeyError, match="not registered"):
        registry.get("nonexistent")


def test_command_registry_all():
    from open_researcher.plugins.cli.commands import CommandRegistry, CommandSpec

    registry = CommandRegistry()
    registry.register(CommandSpec(name="run", help="Run"))
    registry.register(CommandSpec(name="status", help="Show status"))

    all_cmds = registry.all()
    assert len(all_cmds) == 2
    assert registry.names() == ["run", "status"]


def test_command_spec_with_options():
    from open_researcher.plugins.cli.commands import CommandSpec, OptionSpec

    spec = CommandSpec(
        name="run",
        help="Run a session",
        options=[
            OptionSpec(name="--config", type=str, default="default.yaml", help="Config file"),
            OptionSpec(name="--parallel", type=int, default=1, help="Parallel workers"),
        ],
    )
    assert len(spec.options) == 2
    assert spec.options[0].name == "--config"
    assert spec.options[1].default == 1
