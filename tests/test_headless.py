"""Tests for headless mode logger."""

import json
from io import StringIO

from open_researcher.headless import HeadlessLogger


def test_emit_writes_jsonl_to_stream():
    """emit() should write a single JSON line to the stream."""
    buf = StringIO()
    logger = HeadlessLogger(stream=buf)
    logger.emit("info", "scouting", "scout_started", detail="analyzing")
    line = buf.getvalue().strip()
    record = json.loads(line)
    assert record["level"] == "info"
    assert record["phase"] == "scouting"
    assert record["event"] == "scout_started"
    assert record["detail"] == "analyzing"
    assert "ts" in record


def test_emit_writes_to_log_file(tmp_path):
    """emit() should also write to log file when provided."""
    log_path = tmp_path / "events.jsonl"
    buf = StringIO()
    logger = HeadlessLogger(stream=buf, log_path=log_path)
    logger.emit("info", "experimenting", "experiment_started", idea="idea-001")
    logger.close()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "experiment_started"
    assert record["idea"] == "idea-001"


def test_emit_extra_kwargs():
    """Extra keyword arguments appear in the JSON record."""
    buf = StringIO()
    logger = HeadlessLogger(stream=buf)
    logger.emit(
        "info",
        "experimenting",
        "experiment_completed",
        idea="idea-002",
        metric_value=0.95,
        experiment_num=3,
        max_experiments=10,
    )
    record = json.loads(buf.getvalue().strip())
    assert record["metric_value"] == 0.95
    assert record["experiment_num"] == 3
    assert record["max_experiments"] == 10


def test_make_output_callback():
    """make_output_callback returns a callable that emits agent_output events."""
    buf = StringIO()
    logger = HeadlessLogger(stream=buf)
    cb = logger.make_output_callback("experimenting")
    cb("[exp] Running experiment #1")
    record = json.loads(buf.getvalue().strip())
    assert record["event"] == "agent_output"
    assert record["detail"] == "[exp] Running experiment #1"


def test_emit_assigns_monotonic_seq_and_high_precision_ts():
    buf = StringIO()
    logger = HeadlessLogger(stream=buf)
    logger.emit("info", "init", "first")
    logger.emit("info", "init", "second")

    first, second = [json.loads(line) for line in buf.getvalue().strip().splitlines()]
    assert second["seq"] == first["seq"] + 1
    assert "." in first["ts"]
