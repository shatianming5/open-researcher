"""Tests for the BootstrapPlugin lifecycle."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_bootstrap_plugin_lifecycle():
    from open_researcher.kernel import Kernel
    from open_researcher.plugins.storage import StoragePlugin
    from open_researcher.plugins.bootstrap import BootstrapPlugin

    storage = StoragePlugin(db_path=":memory:")
    bootstrap = BootstrapPlugin()

    k = Kernel(db_path=":memory:")
    await k.boot([storage, bootstrap])

    assert bootstrap.kernel is k

    await k.shutdown()


async def test_bootstrap_plugin_not_started():
    from open_researcher.plugins.bootstrap import BootstrapPlugin

    plugin = BootstrapPlugin()
    with pytest.raises(RuntimeError, match="not started"):
        _ = plugin.kernel
