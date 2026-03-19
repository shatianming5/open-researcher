"""Tests for the TUI ViewModel."""
from open_researcher.kernel.event import Event


def test_initial_snapshot():
    from open_researcher.plugins.tui.view_model import ViewModel

    vm = ViewModel()
    snap = vm.snapshot
    assert snap.phase == "idle"
    assert snap.cycle == 0
    assert snap.experiments_completed == 0
    assert snap.is_running is False


def test_scout_event_updates_phase():
    from open_researcher.plugins.tui.view_model import ViewModel

    vm = ViewModel()
    vm.on_event(Event(type="scout.started", payload={}))

    assert vm.snapshot.phase == "scouting"
    assert vm.snapshot.is_running is True


def test_manager_event_updates_cycle():
    from open_researcher.plugins.tui.view_model import ViewModel

    vm = ViewModel()
    vm.on_event(Event(type="manager.cycle_started", payload={"cycle": 3}))

    assert vm.snapshot.phase == "managing"
    assert vm.snapshot.cycle == 3


def test_experiment_completed_tracks_counts():
    from open_researcher.plugins.tui.view_model import ViewModel

    vm = ViewModel()
    vm.on_event(Event(type="experiment.completed", payload={"exit_code": 0}))
    vm.on_event(Event(type="experiment.completed", payload={"exit_code": 0}))
    vm.on_event(Event(type="experiment.completed", payload={"exit_code": 1}))

    assert vm.snapshot.experiments_completed == 2
    assert vm.snapshot.experiments_failed == 1


def test_run_completed_resets_to_idle():
    from open_researcher.plugins.tui.view_model import ViewModel

    vm = ViewModel()
    vm.on_event(Event(type="scout.started", payload={}))
    assert vm.snapshot.is_running is True

    vm.on_event(Event(type="run.completed", payload={}))
    assert vm.snapshot.phase == "idle"
    assert vm.snapshot.is_running is False


def test_last_event_tracking():
    from open_researcher.plugins.tui.view_model import ViewModel

    vm = ViewModel()
    vm.on_event(Event(type="test.event", payload={}, ts=12345.0))

    assert vm.snapshot.last_event_type == "test.event"
    assert vm.snapshot.last_event_ts == 12345.0
