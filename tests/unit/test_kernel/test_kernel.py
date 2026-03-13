"""Tests for the Kernel orchestrator."""
import asyncio
import pytest

pytestmark = pytest.mark.asyncio


async def test_kernel_boot_and_shutdown():
    from open_researcher.kernel.kernel import Kernel
    from open_researcher.kernel.plugin import PluginBase

    started = []
    stopped = []

    class P(PluginBase):
        name = "p"
        dependencies: list[str] = []

        async def start(self, kernel):
            started.append(self.name)

        async def stop(self):
            stopped.append(self.name)

    k = Kernel(db_path=":memory:")
    await k.boot([P()])
    assert started == ["p"]

    await k.shutdown()
    assert stopped == ["p"]


async def test_kernel_emits_events():
    from open_researcher.kernel.event import Event
    from open_researcher.kernel.kernel import Kernel

    k = Kernel(db_path=":memory:")
    await k.boot([])

    received = []
    k.bus.on("test.*", lambda e: received.append(e))
    await k.bus.emit(Event(type="test.ping", payload={"msg": "hi"}))
    await asyncio.sleep(0.05)

    assert len(received) == 1
    assert received[0].payload["msg"] == "hi"
    await k.shutdown()


async def test_kernel_get_plugin():
    from open_researcher.kernel.kernel import Kernel
    from open_researcher.kernel.plugin import PluginBase

    class P(PluginBase):
        name = "myplug"
        dependencies: list[str] = []
        async def start(self, kernel): pass

    k = Kernel(db_path=":memory:")
    await k.boot([P()])
    assert k.get_plugin("myplug").name == "myplug"
    await k.shutdown()


async def test_kernel_boot_respects_dependency_order():
    from open_researcher.kernel.kernel import Kernel
    from open_researcher.kernel.plugin import PluginBase

    order = []

    class A(PluginBase):
        name = "a"
        dependencies: list[str] = []
        async def start(self, kernel): order.append("a")
        async def stop(self): pass

    class B(PluginBase):
        name = "b"
        dependencies = ["a"]
        async def start(self, kernel): order.append("b")
        async def stop(self): pass

    k = Kernel(db_path=":memory:")
    await k.boot([B(), A()])
    assert order == ["a", "b"]
    await k.shutdown()
