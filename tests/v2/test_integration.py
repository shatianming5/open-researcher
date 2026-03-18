"""End-to-end integration tests for the v2 research loop.

Tests the full serial flow (bootstrap + rounds) and parallel frontier
claiming using mock agent adapters that never spawn real subprocesses.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from open_researcher_v2.agent import Agent, AgentAdapter
from open_researcher_v2.parallel import WorkerPool
from open_researcher_v2.skill_runner import SkillRunner
from open_researcher_v2.state import ResearchState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with a .research directory."""
    subprocess.run(
        ["git", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    research_dir = tmp_path / ".research"
    research_dir.mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture()
def mock_adapter() -> MagicMock:
    """Return a MagicMock that behaves like an AgentAdapter with run returning 0.

    The mock's ``run`` side effect writes a placeholder program file so that
    Agent.run's write-then-run workflow succeeds, and returns 0.
    """
    adapter = MagicMock(spec=AgentAdapter)
    adapter.run.return_value = 0
    return adapter


# ---------------------------------------------------------------------------
# TestFullSerialFlow
# ---------------------------------------------------------------------------


class TestFullSerialFlow:
    """Integration tests for the serial skill loop: bootstrap + rounds."""

    def test_bootstrap_then_one_round(self, repo: Path, mock_adapter: MagicMock):
        """Bootstrap (1 agent call) then one round (4 agent calls) = 5 total.

        The log should contain 10 events: 5 skill_started + 5 skill_completed.
        """
        state = ResearchState(repo / ".research")
        agent = Agent(mock_adapter)
        runner = SkillRunner(
            repo, state, agent,
            goal="improve accuracy",
            tag="int-test",
        )

        rc_boot = runner.run_bootstrap()
        assert rc_boot == 0

        rc_round = runner.run_one_round(1)
        assert rc_round == 0

        # 1 bootstrap (scout) + 4 round steps (manager, critic, experiment, critic)
        assert mock_adapter.run.call_count == 5

        # Check log events
        log = state.tail_log(200)
        skill_events = [e for e in log if e.get("event") in ("skill_started", "skill_completed")]
        assert len(skill_events) == 10  # 5 starts + 5 completes

    def test_full_serial_with_limit(self, repo: Path, mock_adapter: MagicMock):
        """run_serial() with max_rounds=2: 1 bootstrap + 2*4 round steps = 9 calls.

        Phase should be 'idle' after completion (run_serial sets it at the end).
        """
        import yaml

        config_path = repo / ".research" / "config.yaml"
        config_path.write_text(
            yaml.dump({"limits": {"max_rounds": 2}}),
            encoding="utf-8",
        )

        state = ResearchState(repo / ".research")
        agent = Agent(mock_adapter)
        runner = SkillRunner(
            repo, state, agent,
            goal="maximize reward",
            tag="serial-test",
        )

        rc = runner.run_serial()
        assert rc == 0

        # 1 (scout) + 2 * 4 (rounds) = 9
        assert mock_adapter.run.call_count == 9

        # Phase should be idle after completion
        activity = state.load_activity()
        assert activity["phase"] == "idle"

    def test_pause_stops_progress(self, repo: Path, mock_adapter: MagicMock):
        """When paused is set, run_one_round should make 0 agent calls."""
        state = ResearchState(repo / ".research")
        state.set_paused(True)

        agent = Agent(mock_adapter)
        runner = SkillRunner(
            repo, state, agent,
            goal="test pause",
            tag="pause-test",
        )

        rc = runner.run_one_round(1)

        # -2 indicates paused
        assert rc == -2
        assert mock_adapter.run.call_count == 0

    def test_skip_current_skips_round(self, repo: Path, mock_adapter: MagicMock):
        """When skip_current is set, run_one_round should skip with no calls."""
        state = ResearchState(repo / ".research")
        state.set_skip_current(True)

        agent = Agent(mock_adapter)
        runner = SkillRunner(
            repo, state, agent,
            goal="test skip",
            tag="skip-test",
        )

        rc = runner.run_one_round(1)

        assert rc == -1
        assert mock_adapter.run.call_count == 0
        # Skip flag should have been consumed
        assert not state.consume_skip()

    def test_serial_stops_on_frontier_complete(self, repo: Path, mock_adapter: MagicMock):
        """If all frontier items are terminal, run_serial stops early."""
        import yaml

        config_path = repo / ".research" / "config.yaml"
        config_path.write_text(
            yaml.dump({"limits": {"max_rounds": 10}}),
            encoding="utf-8",
        )

        state = ResearchState(repo / ".research")

        # Pre-populate graph with fully-done frontier
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "f-1", "status": "archived"},
            {"id": "f-2", "status": "rejected"},
        ]
        state.save_graph(graph)

        agent = Agent(mock_adapter)
        runner = SkillRunner(
            repo, state, agent,
            goal="frontier check",
            tag="frontier-test",
        )

        rc = runner.run_serial()
        assert rc == 0

        # 1 bootstrap + 1 round * 4 steps = 5
        # Stops after first round because frontier is all done
        assert mock_adapter.run.call_count == 5


# ---------------------------------------------------------------------------
# TestParallelClaiming
# ---------------------------------------------------------------------------


class TestParallelClaiming:
    """Integration tests for WorkerPool frontier claiming."""

    def test_two_workers_claim_different_items(self, repo: Path):
        """Two workers should each claim a different frontier item."""
        state = ResearchState(repo / ".research")

        # Add 2 approved frontier items
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "exp-1", "status": "approved", "priority": 1, "title": "Experiment 1"},
            {"id": "exp-2", "status": "approved", "priority": 2, "title": "Experiment 2"},
        ]
        state.save_graph(graph)

        # Create WorkerPool (we only use claim_frontier, not the full pool)
        pool = WorkerPool(
            repo_path=repo,
            state=state,
            agent_factory=lambda: None,
            skill_content="placeholder",
            max_workers=2,
        )

        # Claim with two different worker IDs
        item_a = pool.claim_frontier("worker-alpha")
        item_b = pool.claim_frontier("worker-beta")

        # Both should get an item
        assert item_a is not None
        assert item_b is not None

        # They should be different items
        assert item_a["id"] != item_b["id"]

        # Higher priority (exp-2, priority=2) should be claimed first
        assert item_a["id"] == "exp-2"
        assert item_b["id"] == "exp-1"

        # Both should now be "running" in the graph
        graph = state.load_graph()
        statuses = {f["id"]: f["status"] for f in graph["frontier"]}
        assert statuses["exp-1"] == "running"
        assert statuses["exp-2"] == "running"

    def test_claim_returns_none_when_empty(self, repo: Path):
        """claim_frontier returns None when no approved items exist."""
        state = ResearchState(repo / ".research")

        pool = WorkerPool(
            repo_path=repo,
            state=state,
            agent_factory=lambda: None,
            skill_content="placeholder",
            max_workers=1,
        )

        result = pool.claim_frontier("worker-x")
        assert result is None

    def test_claim_skips_non_approved_items(self, repo: Path):
        """claim_frontier should only pick items with status='approved'."""
        state = ResearchState(repo / ".research")

        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "exp-1", "status": "running", "priority": 1},
            {"id": "exp-2", "status": "archived", "priority": 2},
            {"id": "exp-3", "status": "rejected", "priority": 3},
            {"id": "exp-4", "status": "approved", "priority": 0},
        ]
        state.save_graph(graph)

        pool = WorkerPool(
            repo_path=repo,
            state=state,
            agent_factory=lambda: None,
            skill_content="placeholder",
            max_workers=4,
        )

        item = pool.claim_frontier("worker-1")
        assert item is not None
        assert item["id"] == "exp-4"

        # No more approved items
        item2 = pool.claim_frontier("worker-2")
        assert item2 is None

    def test_finalize_experiment_records_result(self, repo: Path):
        """finalize_experiment should update graph and append a result row."""
        state = ResearchState(repo / ".research")

        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "exp-1", "status": "running", "claimed_by": "w0"},
        ]
        state.save_graph(graph)

        pool = WorkerPool(
            repo_path=repo,
            state=state,
            agent_factory=lambda: None,
            skill_content="placeholder",
            max_workers=1,
        )

        pool.finalize_experiment(
            "w0",
            "exp-1",
            {"status": "keep", "metric": "accuracy", "value": "0.95"},
        )

        # Check graph: status should be "needs_post_review"
        graph = state.load_graph()
        frontier_item = graph["frontier"][0]
        assert frontier_item["status"] == "needs_post_review"

        # Check results
        results = state.load_results()
        assert len(results) == 1
        assert results[0]["frontier_id"] == "exp-1"
        assert results[0]["worker"] == "w0"
        assert results[0]["value"] == "0.95"


# ---------------------------------------------------------------------------
# TestEndToEndWithState
# ---------------------------------------------------------------------------


class TestEndToEndWithState:
    """Tests that verify state consistency across bootstrap + rounds."""

    def test_log_captures_all_phases(self, repo: Path, mock_adapter: MagicMock):
        """After a full serial run, the log should contain a complete trace."""
        import yaml

        config_path = repo / ".research" / "config.yaml"
        config_path.write_text(
            yaml.dump({"limits": {"max_rounds": 1}}),
            encoding="utf-8",
        )

        state = ResearchState(repo / ".research")
        agent = Agent(mock_adapter)
        runner = SkillRunner(
            repo, state, agent,
            goal="end-to-end",
            tag="e2e",
        )

        runner.run_serial()

        log = state.tail_log(500)
        events = [e.get("event") for e in log]

        # Bootstrap events
        assert events.count("skill_started") == 5  # 1 scout + 4 loop steps
        assert events.count("skill_completed") == 5

        # Round lifecycle events
        assert "round_started" in events
        assert "round_completed" in events

    def test_summary_reflects_state(self, repo: Path):
        """summary() should reflect the current state of all files."""
        state = ResearchState(repo / ".research")

        # Set up some state
        state.update_phase("running", 3)

        graph = state.load_graph()
        graph["hypotheses"] = [{"id": "h-1"}, {"id": "h-2"}]
        graph["frontier"] = [
            {"id": "f-1", "status": "approved"},
            {"id": "f-2", "status": "running"},
            {"id": "f-3", "status": "archived"},
        ]
        state.save_graph(graph)

        state.append_result({
            "worker": "w0",
            "frontier_id": "f-3",
            "status": "keep",
            "metric": "acc",
            "value": "0.85",
        })

        summary = state.summary()
        assert summary["phase"] == "running"
        assert summary["round"] == 3
        assert summary["hypotheses"] == 2
        assert summary["experiments_total"] == 3
        assert summary["experiments_running"] == 1
        assert summary["experiments_done"] == 1  # only archived counts
        assert summary["results_count"] == 1
        assert summary["best_value"] == "0.85"
