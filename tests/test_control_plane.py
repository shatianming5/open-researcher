"""Tests for the event-backed control plane."""

import json

from open_researcher.control_plane import issue_control_command, read_control
from open_researcher.event_journal import EventJournal


def test_issue_control_command_writes_event_and_snapshot(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    ctrl_path = research / "control.json"

    result = issue_control_command(
        ctrl_path,
        command="pause",
        source="test",
        reason="manual pause",
    )

    assert result["applied"] is True
    state = json.loads(ctrl_path.read_text())
    assert state["paused"] is True
    assert state["control_seq"] == 1

    event_log = research / "events.jsonl"
    records = [json.loads(line) for line in event_log.read_text().splitlines() if line.strip()]
    assert len(records) == 1
    assert records[0]["seq"] == 1
    assert records[0]["phase"] == "control"
    assert records[0]["event"] == "control_command"
    assert records[0]["command"] == "pause"


def test_read_control_replays_from_events_when_snapshot_is_missing(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    ctrl_path = research / "control.json"

    issue_control_command(ctrl_path, command="pause", source="test", reason="pause once")
    issue_control_command(ctrl_path, command="resume", source="test")
    ctrl_path.unlink()

    state = read_control(ctrl_path)

    assert state["paused"] is False
    assert state["control_seq"] == 2
    assert ctrl_path.exists()


def test_read_control_prefers_event_log_over_stale_snapshot(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    ctrl_path = research / "control.json"
    ctrl_path.write_text(json.dumps({"paused": True, "skip_current": True, "control_seq": 99}))

    issue_control_command(ctrl_path, command="clear_skip", source="test")
    state = read_control(ctrl_path)

    assert state["skip_current"] is False
    assert state["control_seq"] == 1


def test_control_events_preserve_global_event_seq(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    events_path = research / "events.jsonl"
    ctrl_path = research / "control.json"
    journal = EventJournal(events_path)

    first = journal.emit("info", "init", "session_started")
    issue_control_command(ctrl_path, command="pause", source="test")
    second = journal.emit("info", "done", "session_completed")

    assert first["seq"] == 1
    assert second["seq"] == 3

    records = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
    assert [record["seq"] for record in records] == [1, 2, 3]
