"""Tests for the ExecutionPlugin lifecycle."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_execution_plugin_lifecycle():
    from open_researcher.kernel import Kernel
    from open_researcher.plugins.storage import StoragePlugin
    from open_researcher.plugins.execution import ExecutionPlugin

    storage = StoragePlugin(db_path=":memory:")
    execution = ExecutionPlugin()

    k = Kernel(db_path=":memory:")
    await k.boot([storage, execution])

    assert execution.kernel is k

    await k.shutdown()


async def test_execution_plugin_kernel_not_started():
    from open_researcher.plugins.execution import ExecutionPlugin

    plugin = ExecutionPlugin()
    with pytest.raises(RuntimeError, match="not started"):
        _ = plugin.kernel
