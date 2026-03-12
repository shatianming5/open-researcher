"""Tests for phase gate."""

import json

import pytest

from paperfarm.phase_gate import PhaseGate


@pytest.fixture
def research_dir(tmp_path):
    d = tmp_path / ".research"
    d.mkdir()
    return d


def _write_progress(research_dir, phase):
    """Helper to write experiment_progress.json with a given phase."""
    path = research_dir / "experiment_progress.json"
    path.write_text(json.dumps({"phase": phase}))


def test_phase_gate_detects_transition(research_dir):
    """In collaborative mode, a phase transition should pause and return the new phase."""
    _write_progress(research_dir, "init")
    gate = PhaseGate(research_dir, mode="collaborative")

    # Transition to a new phase
    _write_progress(research_dir, "training")
    result = gate.check()
    assert result == "training"

    # Verify control.json was written with paused state
    ctrl_path = research_dir / "control.json"
    assert ctrl_path.exists()
    ctrl = json.loads(ctrl_path.read_text())
    assert ctrl["paused"] is True
    assert "training" in ctrl["pause_reason"]
    event_log = research_dir / "events.jsonl"
    records = [json.loads(line) for line in event_log.read_text().splitlines() if line.strip()]
    assert records[-1]["phase"] == "control"
    assert records[-1]["command"] == "pause"


def test_phase_gate_noop_in_autonomous(research_dir):
    """In autonomous mode, phase transitions should NOT cause a pause."""
    _write_progress(research_dir, "init")
    gate = PhaseGate(research_dir, mode="autonomous")

    # Transition to a new phase
    _write_progress(research_dir, "training")
    result = gate.check()
    assert result is None

    # control.json should NOT exist
    ctrl_path = research_dir / "control.json"
    assert not ctrl_path.exists()


def test_phase_gate_no_duplicate_trigger(research_dir):
    """Checking the same phase twice should only trigger once."""
    _write_progress(research_dir, "init")
    gate = PhaseGate(research_dir, mode="collaborative")

    # First transition
    _write_progress(research_dir, "evaluation")
    result1 = gate.check()
    assert result1 == "evaluation"

    # Same phase again -- should not trigger
    result2 = gate.check()
    assert result2 is None
