"""Comprehensive tests for paperfarm.state.ResearchState."""

from __future__ import annotations

import json

import yaml
import pytest

from paperfarm.state import (
    ResearchState,
    _DEFAULT_CONFIG,
    _DEFAULT_ACTIVITY,
    _RESULTS_FIELDS,
    _deep_merge,
    _default_graph,
)


# ---------------------------------------------------------------------------
# TestConfig
# ---------------------------------------------------------------------------


class TestConfig:
    """Tests for config.yaml loading with defaults merging."""

    def test_load_default_when_missing(self, tmp_path):
        state = ResearchState(tmp_path)
        cfg = state.load_config()
        assert cfg["protocol"] == "research-v1"
        assert cfg["metrics"]["primary"]["name"] == ""
        assert cfg["metrics"]["primary"]["direction"] == "maximize"
        assert cfg["workers"]["max"] == 0
        assert cfg["workers"]["gpu_mem_per_worker_mb"] == 8192
        assert cfg["limits"]["max_rounds"] == 20
        assert cfg["agent"]["name"] == "claude-code"

    def test_load_existing_merges_with_defaults(self, tmp_path):
        user_cfg = {
            "metrics": {"primary": {"name": "accuracy", "direction": "maximize"}},
            "workers": {"max": 4},
        }
        (tmp_path / "config.yaml").write_text(yaml.dump(user_cfg), encoding="utf-8")
        state = ResearchState(tmp_path)
        cfg = state.load_config()
        assert cfg["metrics"]["primary"]["name"] == "accuracy"
        assert cfg["workers"]["max"] == 4
        assert cfg["workers"]["gpu_mem_per_worker_mb"] == 8192  # default preserved
        assert cfg["limits"]["max_rounds"] == 20  # default preserved

    def test_load_corrupt_yaml_returns_defaults(self, tmp_path):
        (tmp_path / "config.yaml").write_text("{{invalid yaml::", encoding="utf-8")
        state = ResearchState(tmp_path)
        cfg = state.load_config()
        assert cfg["protocol"] == "research-v1"

    def test_load_non_dict_yaml_returns_defaults(self, tmp_path):
        (tmp_path / "config.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
        state = ResearchState(tmp_path)
        cfg = state.load_config()
        assert cfg["protocol"] == "research-v1"


# ---------------------------------------------------------------------------
# TestGraph
# ---------------------------------------------------------------------------


class TestGraph:
    def test_load_default_when_missing(self, tmp_path):
        state = ResearchState(tmp_path)
        graph = state.load_graph()
        assert graph["repo_profile"] == {}
        assert graph["hypotheses"] == []
        assert graph["frontier"] == []
        assert graph["counters"]["hypothesis"] == 0
        assert graph["counters"]["spec"] == 0
        assert graph["counters"]["claim"] == 0

    def test_save_and_load_roundtrip(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        graph = _default_graph()
        graph["hypotheses"].append({"id": "h1", "text": "test"})
        graph["counters"]["hypothesis"] = 1
        state.save_graph(graph)

        loaded = state.load_graph()
        assert len(loaded["hypotheses"]) == 1
        assert loaded["hypotheses"][0]["id"] == "h1"
        assert loaded["counters"]["hypothesis"] == 1

    def test_load_corrupt_json_returns_default(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "graph.json").write_text("not json", encoding="utf-8")
        state = ResearchState(tmp_path)
        graph = state.load_graph()
        assert graph["hypotheses"] == []

    def test_load_non_dict_json_returns_default(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "graph.json").write_text("[1,2,3]", encoding="utf-8")
        state = ResearchState(tmp_path)
        graph = state.load_graph()
        assert graph["hypotheses"] == []


# ---------------------------------------------------------------------------
# TestResults
# ---------------------------------------------------------------------------


class TestResults:
    def test_empty_when_missing(self, tmp_path):
        state = ResearchState(tmp_path)
        assert state.load_results() == []

    def test_append_and_load(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        state.append_result({
            "worker": "w0", "frontier_id": "f1", "status": "keep",
            "metric": "accuracy", "value": "0.95", "description": "baseline",
        })
        rows = state.load_results()
        assert len(rows) == 1
        assert rows[0]["worker"] == "w0"
        assert rows[0]["value"] == "0.95"
        assert rows[0]["timestamp"] != ""

    def test_append_multiple(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        for i in range(5):
            state.append_result({
                "worker": f"w{i}", "frontier_id": f"f{i}",
                "status": "keep" if i % 2 == 0 else "discard",
                "metric": "loss", "value": str(float(i) / 10),
            })
        rows = state.load_results()
        assert len(rows) == 5

    def test_append_with_explicit_timestamp(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        state.append_result({"timestamp": "2026-01-01T00:00:00+00:00", "worker": "w0", "status": "keep"})
        rows = state.load_results()
        assert rows[0]["timestamp"] == "2026-01-01T00:00:00+00:00"

    def test_load_empty_file(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "results.tsv").write_text("", encoding="utf-8")
        state = ResearchState(tmp_path)
        assert state.load_results() == []


# ---------------------------------------------------------------------------
# TestActivity
# ---------------------------------------------------------------------------


class TestActivity:
    def test_default_when_missing(self, tmp_path):
        state = ResearchState(tmp_path)
        act = state.load_activity()
        assert act["phase"] == "idle"
        assert act["round"] == 0
        assert act["control"]["paused"] is False
        assert act["control"]["skip_current"] is False
        assert act["workers"] == []

    def test_update_phase(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        state.update_phase("running", round_num=3)
        act = state.load_activity()
        assert act["phase"] == "running"
        assert act["round"] == 3

    def test_update_worker(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        state.update_worker("w0", status="running", gpu=0, frontier_id="f-001")
        act = state.load_activity()
        assert isinstance(act["workers"], list)
        assert len(act["workers"]) == 1
        assert act["workers"][0]["id"] == "w0"
        assert act["workers"][0]["status"] == "running"
        assert act["workers"][0]["gpu"] == 0

        # Update same worker
        state.update_worker("w0", status="done")
        act = state.load_activity()
        assert len(act["workers"]) == 1
        assert act["workers"][0]["status"] == "done"
        assert act["workers"][0]["gpu"] == 0  # preserved

    def test_is_paused(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        assert state.is_paused() is False
        state.set_paused(True)
        assert state.is_paused() is True
        state.set_paused(False)
        assert state.is_paused() is False

    def test_consume_skip(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        assert state.consume_skip() is False
        state.set_skip_current(True)
        act = state.load_activity()
        assert act["control"]["skip_current"] is True
        assert state.consume_skip() is True
        assert state.consume_skip() is False

    def test_save_activity_public(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        act = state.load_activity()
        act["control"]["skip_current"] = True
        state.save_activity(act)
        assert state.load_activity()["control"]["skip_current"] is True

    def test_load_corrupt_activity(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "activity.json").write_text("{bad json", encoding="utf-8")
        state = ResearchState(tmp_path)
        act = state.load_activity()
        assert act["phase"] == "idle"


# ---------------------------------------------------------------------------
# TestLog
# ---------------------------------------------------------------------------


class TestLog:
    def test_empty_when_missing(self, tmp_path):
        state = ResearchState(tmp_path)
        assert state.tail_log() == []

    def test_append_and_tail(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        state.append_log({"type": "skill_started", "skill": "scout"})
        state.append_log({"type": "output", "text": "hello"})
        entries = state.tail_log()
        assert len(entries) == 2
        assert entries[0]["type"] == "skill_started"
        assert "ts" in entries[0]

    def test_tail_limit(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        for i in range(100):
            state.append_log({"type": "output", "i": i})
        entries = state.tail_log(n=5)
        assert len(entries) == 5
        assert entries[0]["i"] == 95

    def test_append_preserves_explicit_ts(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        state.append_log({"type": "custom", "ts": "2026-01-01T00:00:00+00:00"})
        entries = state.tail_log()
        assert entries[0]["ts"] == "2026-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# TestSummary
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_with_empty_state(self, tmp_path):
        state = ResearchState(tmp_path)
        s = state.summary()
        assert s["phase"] == "idle"
        assert s["round"] == 0
        assert s["hypotheses"] == 0
        assert s["experiments_total"] == 0
        assert s["experiments_done"] == 0
        assert s["experiments_running"] == 0
        assert s["results_count"] == 0
        assert s["best_value"] == "—"
        assert s["workers"] == []
        assert s["paused"] is False

    def test_summary_with_populated_state(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = ResearchState(tmp_path)
        state.update_phase("researching", round_num=2)
        state.update_worker("w0", status="running")
        state.append_result({"status": "keep", "metric": "acc", "value": "0.9"})
        state.append_result({"status": "discard", "metric": "acc", "value": "0.5"})
        state.append_result({"status": "keep", "metric": "acc", "value": "0.95"})

        graph = _default_graph()
        graph["hypotheses"] = [{"id": "h1"}, {"id": "h2"}]
        graph["frontier"] = [
            {"id": "f1", "status": "running"},
            {"id": "f2", "status": "archived"},
            {"id": "f3", "status": "approved"},
        ]
        state.save_graph(graph)

        s = state.summary()
        assert s["phase"] == "researching"
        assert s["round"] == 2
        assert s["hypotheses"] == 2
        assert s["experiments_total"] == 3
        assert s["experiments_done"] == 1
        assert s["experiments_running"] == 1
        assert s["results_count"] == 3
        assert s["best_value"] == "0.95"


# ---------------------------------------------------------------------------
# TestDeepMerge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_empty_override(self):
        base = {"a": 1, "b": {"c": 2}}
        assert _deep_merge(base, {}) == base

    def test_flat_override(self):
        assert _deep_merge({"a": 1, "b": 2}, {"b": 99}) == {"a": 1, "b": 99}

    def test_nested_override(self):
        assert _deep_merge({"x": {"y": 1, "z": 2}}, {"x": {"z": 99}}) == {"x": {"y": 1, "z": 99}}

    def test_new_keys_added(self):
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_original_not_mutated(self):
        base = {"a": {"b": 1}}
        _deep_merge(base, {"a": {"b": 99}})
        assert base["a"]["b"] == 1
