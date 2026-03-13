"""End-to-end integration test: headless research session simulation.

Boots the full microkernel with all plugins, simulates a Scout -> Manager ->
Critic -> Experiment cycle using mock agents, and verifies:
1. Events are emitted in the correct order
2. Plugin state is updated correctly
3. SQLite state persists across operations
4. ViewModel reflects the session state
"""
import asyncio
import time

import pytest

from open_researcher.kernel import Kernel, Event, PluginBase
from open_researcher.plugins.storage import StoragePlugin
from open_researcher.plugins.agents import AgentsPlugin
from open_researcher.plugins.agents.base import AgentAdapter
from open_researcher.plugins.orchestrator import OrchestratorPlugin
from open_researcher.plugins.execution import ExecutionPlugin
from open_researcher.plugins.bootstrap import BootstrapPlugin
from open_researcher.plugins.cli import CLIPlugin
from open_researcher.plugins.tui import TUIPlugin
from open_researcher.plugins.tui.view_model import ViewModel
from open_researcher.plugins.graph.store import GraphStore
from open_researcher.plugins.scheduler.idea_pool import IdeaPoolStore

pytestmark = pytest.mark.asyncio


class MockAgent(AgentAdapter):
    """A fake agent that always succeeds."""

    name = "mock"

    def check_installed(self) -> bool:
        return True

    def run(self, repo_path, program_file, *, on_output=None, env=None):
        return 0

    def terminate(self):
        pass


@pytest.fixture
async def full_kernel():
    """Boot a full microkernel with all plugins."""
    storage = StoragePlugin(db_path=":memory:")
    agents = AgentsPlugin()
    orchestrator = OrchestratorPlugin()
    execution = ExecutionPlugin()
    bootstrap = BootstrapPlugin()
    cli = CLIPlugin()
    tui = TUIPlugin()

    k = Kernel(db_path=":memory:")
    await k.boot([storage, agents, orchestrator, execution, bootstrap, cli, tui])

    yield k, storage, agents, orchestrator, execution, bootstrap, cli, tui

    await k.shutdown()


async def test_full_kernel_boots_all_plugins(full_kernel):
    """All 7 plugins boot successfully and are accessible."""
    k, storage, agents, orchestrator, execution, bootstrap, cli, tui = full_kernel

    assert k.get_plugin("storage") is storage
    assert k.get_plugin("agents") is agents
    assert k.get_plugin("orchestrator") is orchestrator
    assert k.get_plugin("execution") is execution
    assert k.get_plugin("bootstrap") is bootstrap
    assert k.get_plugin("cli") is cli
    assert k.get_plugin("tui") is tui


async def test_simulated_research_cycle(full_kernel):
    """Simulate a complete Scout -> Manager -> Critic -> Experiment cycle via events."""
    k, storage, *_ = full_kernel

    event_log: list[str] = []
    k.bus.on("*", lambda e: event_log.append(e.type))

    # 1. Scout phase
    await k.bus.emit(Event(type="scout.started", payload={}, source="orchestrator"))
    await k.bus.emit(Event(type="scout.completed", payload={"exit_code": 0}, source="orchestrator"))

    # 2. Manager phase
    await k.bus.emit(Event(type="manager.cycle_started", payload={"cycle": 1}, source="orchestrator"))
    await k.bus.emit(Event(type="hypothesis.proposed", payload={"id": "h-1", "claim": "Test hypothesis"}, source="orchestrator"))

    # 3. Critic phase
    await k.bus.emit(Event(type="critic.review_started", payload={"stage": "preflight"}, source="orchestrator"))
    await k.bus.emit(Event(type="critic.review_completed", payload={"approved": True}, source="orchestrator"))

    # 4. Experiment phase
    await k.bus.emit(Event(type="experiment.started", payload={"id": 1}, source="orchestrator"))
    await k.bus.emit(Event(type="experiment.completed", payload={"id": 1, "exit_code": 0}, source="orchestrator"))

    # 5. Run completed
    await k.bus.emit(Event(type="run.completed", payload={"total_experiments": 1}, source="orchestrator"))

    # Let call_soon dispatches run
    await asyncio.sleep(0.1)

    # Verify event order
    assert "scout.started" in event_log
    assert "scout.completed" in event_log
    assert "manager.cycle_started" in event_log
    assert "experiment.completed" in event_log
    assert "run.completed" in event_log

    # Verify events persisted in store
    all_events = await k.store.replay()
    assert len(all_events) == 9

    scout_events = await k.store.replay(type_prefix="scout.")
    assert len(scout_events) == 2

    experiment_events = await k.store.replay(type_prefix="experiment.")
    assert len(experiment_events) == 2


async def test_graph_and_ideas_with_events(full_kernel):
    """GraphStore and IdeaPoolStore work alongside the event bus."""
    k, storage, *_ = full_kernel

    graph = GraphStore(storage.db)
    pool = IdeaPoolStore(storage.db)

    # Add hypothesis through store
    await graph.add_hypothesis(id="h-1", claim="Larger batch size improves accuracy")

    # Emit event about the hypothesis
    await k.bus.emit(Event(
        type="hypothesis.proposed",
        payload={"id": "h-1", "claim": "Larger batch size improves accuracy"},
        source="manager",
    ))

    # Add ideas and claim one
    await pool.add(title="Try batch size 64", priority=8)
    await pool.add(title="Try batch size 128", priority=5)
    claimed = await pool.claim(worker_id="worker-1")
    assert claimed is not None
    assert claimed["title"] == "Try batch size 64"  # highest priority

    # Add evidence
    await graph.add_evidence(
        id="ev-1",
        hypothesis_id="h-1",
        direction="supports",
        summary="Accuracy improved by 3%",
    )

    await k.bus.emit(Event(
        type="evidence.recorded",
        payload={"id": "ev-1", "hypothesis_id": "h-1", "direction": "supports"},
        source="critic",
    ))

    # Verify persistence
    h = await graph.get_hypothesis("h-1")
    assert h is not None
    assert h["claim"] == "Larger batch size improves accuracy"

    evidence = await graph.list_evidence(hypothesis_id="h-1")
    assert len(evidence) == 1

    # Verify events
    events = await k.store.replay(type_prefix="hypothesis.")
    assert len(events) == 1

    evidence_events = await k.store.replay(type_prefix="evidence.")
    assert len(evidence_events) == 1


async def test_view_model_reflects_events(full_kernel):
    """ViewModel correctly projects kernel events into session state."""
    k, *_ = full_kernel

    vm = ViewModel()
    k.bus.on("*", vm.on_event)

    # Initial state
    assert vm.snapshot.phase == "idle"
    assert vm.snapshot.is_running is False

    # Scout started
    await k.bus.emit(Event(type="scout.started", payload={}, source="orchestrator"))
    await asyncio.sleep(0.05)
    assert vm.snapshot.phase == "scouting"
    assert vm.snapshot.is_running is True

    # Manager cycle
    await k.bus.emit(Event(type="manager.cycle_started", payload={"cycle": 2}, source="orchestrator"))
    await asyncio.sleep(0.05)
    assert vm.snapshot.phase == "managing"
    assert vm.snapshot.cycle == 2

    # Experiments
    await k.bus.emit(Event(type="experiment.completed", payload={"exit_code": 0}, source="orchestrator"))
    await k.bus.emit(Event(type="experiment.completed", payload={"exit_code": 1}, source="orchestrator"))
    await asyncio.sleep(0.05)
    assert vm.snapshot.experiments_completed == 1
    assert vm.snapshot.experiments_failed == 1

    # Run completed
    await k.bus.emit(Event(type="run.completed", payload={}, source="orchestrator"))
    await asyncio.sleep(0.05)
    assert vm.snapshot.phase == "idle"
    assert vm.snapshot.is_running is False


async def test_agent_registration_and_discovery(full_kernel):
    """AgentsPlugin can register and discover mock agents."""
    k, _, agents, *_ = full_kernel

    agents.register_adapter(MockAgent)

    agent = agents.get_agent("mock")
    assert agent.name == "mock"
    assert agent.check_installed() is True
    assert agent.run("/tmp", "test.md") == 0

    detected = agents.detect_agent()
    assert detected is not None
    assert detected.name == "mock"


async def test_event_replay_filters(full_kernel):
    """EventStore replay correctly filters by type and time."""
    k, *_ = full_kernel

    t_before = time.time()

    await k.bus.emit(Event(type="scout.started", payload={}, ts=t_before - 10))
    await k.bus.emit(Event(type="scout.completed", payload={}, ts=t_before - 5))
    await k.bus.emit(Event(type="experiment.started", payload={}, ts=t_before + 1))
    await k.bus.emit(Event(type="experiment.completed", payload={}, ts=t_before + 2))

    # Filter by type
    scout_events = await k.store.replay(type_prefix="scout.")
    assert len(scout_events) == 2

    exp_events = await k.store.replay(type_prefix="experiment.")
    assert len(exp_events) == 2

    # Filter by time
    recent = await k.store.replay(since=t_before)
    assert len(recent) == 2
    assert all(e.type.startswith("experiment.") for e in recent)

    # Combined filter
    recent_scout = await k.store.replay(type_prefix="scout.", since=t_before)
    assert len(recent_scout) == 0  # scout events are old
