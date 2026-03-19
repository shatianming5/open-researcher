"""Tests for the event adapter that bridges old events to kernel EventBus."""
import asyncio
from dataclasses import dataclass

import pytest


def test_event_type_name_conversion():
    from open_researcher.plugins.orchestrator.event_adapter import _event_type_name

    @dataclass
    class ScoutStarted:
        pass

    @dataclass
    class ExperimentCompleted:
        exit_code: int = 0

    @dataclass
    class ManagerCycleStarted:
        cycle: int = 1

    assert _event_type_name(ScoutStarted()) == "scout.started"
    assert _event_type_name(ExperimentCompleted()) == "experiment.completed"
    assert _event_type_name(ManagerCycleStarted()) == "manager.cycle_started"


@pytest.mark.asyncio
async def test_bus_emitter_creates_kernel_events():
    from open_researcher.kernel import Kernel
    from open_researcher.plugins.orchestrator.event_adapter import make_bus_emitter

    @dataclass
    class ScoutStarted:
        pass

    k = Kernel(db_path=":memory:")
    await k.store.open()

    emitter = make_bus_emitter(k.bus)

    emitter(ScoutStarted())
    await asyncio.sleep(0.1)

    events = await k.store.replay(type_prefix="scout.")
    assert len(events) == 1
    assert events[0].type == "scout.started"
    assert events[0].source == "orchestrator"
    await k.store.close()


@pytest.mark.asyncio
async def test_orchestrator_plugin_lifecycle():
    from open_researcher.kernel import Kernel
    from open_researcher.plugins.orchestrator import OrchestratorPlugin
    from open_researcher.plugins.storage import StoragePlugin

    storage = StoragePlugin(db_path=":memory:")
    orch = OrchestratorPlugin()

    k = Kernel(db_path=":memory:")
    await k.boot([storage, orch])

    assert orch.kernel is k

    await k.shutdown()
