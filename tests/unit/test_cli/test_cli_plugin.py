"""Tests for the CLIPlugin lifecycle."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_cli_plugin_lifecycle():
    from open_researcher.kernel import Kernel
    from open_researcher.plugins.storage import StoragePlugin
    from open_researcher.plugins.cli import CLIPlugin

    storage = StoragePlugin(db_path=":memory:")
    cli = CLIPlugin()

    k = Kernel(db_path=":memory:")
    await k.boot([storage, cli])

    assert cli.kernel is k

    await k.shutdown()


async def test_cli_plugin_not_started():
    from open_researcher.plugins.cli import CLIPlugin

    plugin = CLIPlugin()
    with pytest.raises(RuntimeError, match="not started"):
        _ = plugin.kernel
