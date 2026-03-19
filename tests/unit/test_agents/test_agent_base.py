import pytest

pytestmark = pytest.mark.asyncio

async def test_fake_agent_conforms_to_protocol():
    from open_researcher.plugins.agents.base import AgentAdapter
    class FakeAgent(AgentAdapter):
        name = "fake"
        def check_installed(self): return True
        def run(self, repo_path, program_file, *, on_output=None, env=None): return 0
        def terminate(self): pass
    agent = FakeAgent()
    assert agent.name == "fake"
    assert agent.check_installed() is True
    assert agent.run("/tmp", "test.md") == 0

async def test_agents_plugin_registers_and_discovers():
    from open_researcher.kernel.kernel import Kernel
    from open_researcher.plugins.agents import AgentsPlugin
    from open_researcher.plugins.agents.base import AgentAdapter

    class FakeAgent(AgentAdapter):
        name = "fake"
        def check_installed(self): return True
        def run(self, repo_path, program_file, **kw): return 0
        def terminate(self): pass

    plugin = AgentsPlugin()
    plugin.register_adapter(FakeAgent)
    k = Kernel(db_path=":memory:")
    await k.boot([plugin])
    agent = plugin.get_agent("fake")
    assert agent.name == "fake"
    with pytest.raises(KeyError):
        plugin.get_agent("nonexistent")
    await k.shutdown()
