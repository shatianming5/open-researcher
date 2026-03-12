"""Tests for typed TUI event rendering."""

import json

from paperfarm.research_events import (
    ClaimUpdated,
    EvidenceRecorded,
    ExperimentCompleted,
    ExperimentStarted,
    FrontierSynced,
)
from paperfarm.tui.events import TUIEventRenderer


class _DummyApp:
    def __init__(self):
        self.logs: list[str] = []
        self.app_phase = "init"

    def append_log(self, line: str) -> None:
        self.logs.append(line)

    def call_from_thread(self, func, *args):
        return func(*args)


def test_tui_event_renderer_shows_trace_suffixes(tmp_path):
    research_dir = tmp_path / ".research"
    research_dir.mkdir()
    app = _DummyApp()
    renderer = TUIEventRenderer(app, research_dir)

    renderer.on_event(
        FrontierSynced(
            frontier_items=1,
            items=[
                {
                    "frontier_id": "frontier-001",
                    "execution_id": "exec-001",
                    "reason_code": "approved_for_execution",
                }
            ],
        )
    )
    renderer.on_event(
        ExperimentStarted(
            experiment_num=1,
            max_experiments=3,
            frontier_id="frontier-001",
            execution_id="exec-001",
            selection_reason_code="breadth_exploration",
        )
    )
    renderer.on_event(
        ExperimentCompleted(
            experiment_num=1,
            exit_code=0,
            frontier_id="frontier-001",
            execution_id="exec-001",
            selection_reason_code="breadth_exploration",
        )
    )
    renderer.on_event(
        EvidenceRecorded(
            evidence_created=1,
            items=[
                {
                    "evidence_id": "evi-001",
                    "frontier_id": "frontier-001",
                    "execution_id": "exec-001",
                    "reason_code": "result_observed",
                }
            ],
        )
    )
    renderer.on_event(
        ClaimUpdated(
            count=1,
            items=[
                {
                    "claim_update_id": "claim-001",
                    "frontier_id": "frontier-001",
                    "execution_id": "exec-001",
                    "reason_code": "supported_but_needs_repro",
                }
            ],
        )
    )
    renderer.close()

    rendered = "\n".join(app.logs)
    assert "frontier-001 / exec-001 / approved_for_execution" in rendered
    assert "frontier-001 / exec-001 / breadth_exploration" in rendered
    assert "evi-001 / frontier-001 / exec-001 / result_observed" in rendered
    assert "claim-001 / frontier-001 / exec-001 / supported_but_needs_repro" in rendered

    records = [
        json.loads(line)
        for line in (research_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    started = next(row for row in records if row["event"] == "experiment_started")
    assert started["frontier_id"] == "frontier-001"
    assert started["execution_id"] == "exec-001"
    assert started["reason_code"] == "breadth_exploration"
