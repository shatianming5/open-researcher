"""Tests for the Plugin protocol and Registry."""
import pytest

pytestmark = pytest.mark.asyncio


async def test_register_and_get_plugin():
    from open_researcher.kernel.plugin import PluginBase, Registry

    class FakePlugin(PluginBase):
        name = "fake"
        dependencies: list[str] = []

        async def start(self, kernel):
            self.started = True

        async def stop(self):
            self.stopped = True

    reg = Registry()
    plugin = FakePlugin()
    reg.register(plugin)
    assert reg.get("fake") is plugin


async def test_get_unknown_plugin_raises():
    from open_researcher.kernel.plugin import Registry

    reg = Registry()
    with pytest.raises(KeyError):
        reg.get("nonexistent")


async def test_topological_sort():
    from open_researcher.kernel.plugin import PluginBase, Registry

    class A(PluginBase):
        name = "a"
        dependencies: list[str] = []
        async def start(self, kernel): pass
        async def stop(self): pass

    class B(PluginBase):
        name = "b"
        dependencies = ["a"]
        async def start(self, kernel): pass
        async def stop(self): pass

    class C(PluginBase):
        name = "c"
        dependencies = ["b"]
        async def start(self, kernel): pass
        async def stop(self): pass

    reg = Registry()
    reg.register(C())
    reg.register(A())
    reg.register(B())

    order = reg.boot_order()
    names = [p.name for p in order]
    assert names.index("a") < names.index("b")
    assert names.index("b") < names.index("c")


async def test_circular_dependency_raises():
    from open_researcher.kernel.plugin import PluginBase, Registry

    class X(PluginBase):
        name = "x"
        dependencies = ["y"]
        async def start(self, kernel): pass
        async def stop(self): pass

    class Y(PluginBase):
        name = "y"
        dependencies = ["x"]
        async def start(self, kernel): pass
        async def stop(self): pass

    reg = Registry()
    reg.register(X())
    reg.register(Y())
    with pytest.raises(ValueError, match="[Cc]ircular"):
        reg.boot_order()


async def test_missing_dependency_raises():
    """Regression: boot_order must fail fast on unregistered dependencies."""
    from open_researcher.kernel.plugin import PluginBase, Registry

    class NeedsMissing(PluginBase):
        name = "needs_missing"
        dependencies = ["does_not_exist"]
        async def start(self, kernel): pass
        async def stop(self): pass

    reg = Registry()
    reg.register(NeedsMissing())
    with pytest.raises(ValueError, match="not registered"):
        reg.boot_order()
