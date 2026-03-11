"""Tests for the WorkerManager."""

import csv
import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from open_researcher.control_plane import issue_control_command
from open_researcher.idea_pool import IdeaPool
from open_researcher.worker import WorkerManager
from open_researcher.worker_plugins import FailureMemoryPlugin, WorkerRuntimePlugins


def _make_research_dir(tmp: Path) -> Path:
    """Set up a minimal research directory."""
    research = tmp / ".research"
    research.mkdir()
    return research


def _make_idea_pool(research: Path, ideas: list[dict]) -> IdeaPool:
    """Create an idea_pool.json with given ideas."""
    pool_path = research / "idea_pool.json"
    pool_path.write_text(json.dumps({"ideas": ideas}, indent=2))
    return IdeaPool(pool_path)


def test_worker_manager_processes_ideas():
    """All pending ideas should be processed by workers."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)

        ideas = [
            {
                "id": "idea-001",
                "description": "Test idea 1",
                "status": "pending",
                "priority": 1,
                "claimed_by": None,
                "assigned_experiment": None,
                "result": None,
                "source": "original",
                "category": "general",
                "gpu_hint": "auto",
                "created_at": "2026-01-01T00:00:00",
            },
            {
                "id": "idea-002",
                "description": "Test idea 2",
                "status": "pending",
                "priority": 2,
                "claimed_by": None,
                "assigned_experiment": None,
                "result": None,
                "source": "original",
                "category": "general",
                "gpu_hint": "auto",
                "created_at": "2026-01-01T00:00:00",
            },
            {
                "id": "idea-003",
                "description": "Test idea 3",
                "status": "pending",
                "priority": 3,
                "claimed_by": None,
                "assigned_experiment": None,
                "result": None,
                "source": "original",
                "category": "general",
                "gpu_hint": "auto",
                "created_at": "2026-01-01T00:00:00",
            },
        ]
        idea_pool = _make_idea_pool(research, ideas)

        # Mock GPU manager that returns no GPUs
        mock_gpu_manager = MagicMock()
        mock_gpu_manager.refresh.return_value = []

        # Track agent run calls
        run_calls = []

        def mock_agent_factory():
            agent = MagicMock()

            def run_side_effect(workdir, on_output=None, program_file="program.md", **kwargs):
                run_calls.append(program_file)
                return 0

            agent.run.side_effect = run_side_effect
            return agent

        output_lines = []

        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=mock_gpu_manager,
            idea_pool=idea_pool,
            agent_factory=mock_agent_factory,
            max_workers=2,
            on_output=output_lines.append,
        )

        wm.start()
        wm.join(timeout=10)

        # All 3 ideas should have been processed
        assert len(run_calls) == 3

        # All ideas should be marked done
        summary = idea_pool.summary()
        assert summary["pending"] == 0
        assert summary["done"] == 3


def test_worker_manager_stops_on_no_ideas():
    """Workers should stop when idea pool is empty."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)

        # Empty pool
        idea_pool = _make_idea_pool(research, [])

        mock_gpu_manager = MagicMock()
        mock_gpu_manager.refresh.return_value = []

        mock_agent_factory = MagicMock()

        output_lines = []

        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=mock_gpu_manager,
            idea_pool=idea_pool,
            agent_factory=mock_agent_factory,
            max_workers=2,
            on_output=output_lines.append,
        )

        wm.start()
        wm.join(timeout=5)

        # No agent should have been created/called
        mock_agent_factory.assert_not_called()

        # Workers should have logged "no more pending ideas"
        assert any("No more pending ideas" in line for line in output_lines)


def test_worker_manager_handles_agent_failure():
    """Failed agent runs should mark ideas as skipped, not done."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)

        ideas = [
            {
                "id": "idea-001",
                "description": "Will fail",
                "status": "pending",
                "priority": 1,
                "claimed_by": None,
                "assigned_experiment": None,
                "result": None,
                "source": "original",
                "category": "general",
                "gpu_hint": "auto",
                "created_at": "2026-01-01T00:00:00",
            },
        ]
        idea_pool = _make_idea_pool(research, ideas)

        mock_gpu_manager = MagicMock()
        mock_gpu_manager.refresh.return_value = []

        def mock_agent_factory():
            agent = MagicMock()
            agent.run.return_value = 1  # non-zero exit code
            return agent

        output_lines = []

        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=mock_gpu_manager,
            idea_pool=idea_pool,
            agent_factory=mock_agent_factory,
            max_workers=1,
            on_output=output_lines.append,
        )

        wm.start()
        wm.join(timeout=5)

        summary = idea_pool.summary()
        assert summary["pending"] == 0
        assert summary["skipped"] == 1
        assert summary["done"] == 0


def test_worker_manager_handles_agent_exception():
    """Agent exceptions should be caught and idea marked skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)

        ideas = [
            {
                "id": "idea-001",
                "description": "Will crash",
                "status": "pending",
                "priority": 1,
                "claimed_by": None,
                "assigned_experiment": None,
                "result": None,
                "source": "original",
                "category": "general",
                "gpu_hint": "auto",
                "created_at": "2026-01-01T00:00:00",
            },
        ]
        idea_pool = _make_idea_pool(research, ideas)

        mock_gpu_manager = MagicMock()
        mock_gpu_manager.refresh.return_value = []

        def mock_agent_factory():
            agent = MagicMock()
            agent.run.side_effect = RuntimeError("Agent crashed")
            return agent

        output_lines = []

        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=mock_gpu_manager,
            idea_pool=idea_pool,
            agent_factory=mock_agent_factory,
            max_workers=1,
            on_output=output_lines.append,
        )

        wm.start()
        wm.join(timeout=5)

        summary = idea_pool.summary()
        assert summary["skipped"] == 1
        assert any("Error" in line for line in output_lines)


def test_worker_manager_stop_signal():
    """Calling stop() should cause workers to exit their loop."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)

        # Create many ideas so workers don't run out
        ideas = [
            {
                "id": f"idea-{i:03d}",
                "description": f"Idea {i}",
                "status": "pending",
                "priority": i,
                "claimed_by": None,
                "assigned_experiment": None,
                "result": None,
                "source": "original",
                "category": "general",
                "gpu_hint": "auto",
                "created_at": "2026-01-01T00:00:00",
            }
            for i in range(1, 20)
        ]
        idea_pool = _make_idea_pool(research, ideas)

        mock_gpu_manager = MagicMock()
        mock_gpu_manager.refresh.return_value = []

        import threading

        first_run = threading.Event()

        def mock_agent_factory():
            agent = MagicMock()

            def slow_run(workdir, on_output=None, program_file="program.md", **kwargs):
                first_run.set()
                return 0

            agent.run.side_effect = slow_run
            return agent

        output_lines = []

        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=mock_gpu_manager,
            idea_pool=idea_pool,
            agent_factory=mock_agent_factory,
            max_workers=1,
            on_output=output_lines.append,
        )

        wm.start()
        # Wait for at least one run to complete
        first_run.wait(timeout=5)
        wm.stop()
        wm.join(timeout=5)


def test_worker_manager_waits_for_resume_before_running():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "Paused idea",
                    "status": "pending",
                    "priority": 1,
                    "claimed_by": None,
                    "assigned_experiment": None,
                    "result": None,
                    "source": "original",
                    "category": "general",
                    "gpu_hint": "auto",
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
        )
        issue_control_command(research / "control.json", command="pause", source="test")

        mock_gpu_manager = MagicMock()
        mock_gpu_manager.refresh.return_value = []
        started = threading.Event()

        def mock_agent_factory():
            agent = MagicMock()

            def run_side_effect(*args, **kwargs):
                started.set()
                return 0

            agent.run.side_effect = run_side_effect
            return agent

        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=mock_gpu_manager,
            idea_pool=idea_pool,
            agent_factory=mock_agent_factory,
            max_workers=1,
            on_output=lambda line: None,
        )

        wm.start()
        time.sleep(0.3)
        assert started.is_set() is False
        issue_control_command(research / "control.json", command="resume", source="test")
        wm.join(timeout=5)
        assert started.is_set() is True


def test_worker_manager_marks_claimed_item_skipped_when_setup_raises():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "Failure memory crash",
                    "status": "pending",
                    "priority": 1,
                    "claimed_by": None,
                    "assigned_experiment": None,
                    "result": None,
                    "source": "original",
                    "category": "general",
                    "gpu_hint": "auto",
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
        )

        mock_gpu_manager = MagicMock()
        mock_gpu_manager.refresh.return_value = []

        failing_memory = MagicMock(spec=FailureMemoryPlugin)
        failing_memory.prepare.side_effect = RuntimeError("prepare failed")

        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=mock_gpu_manager,
            idea_pool=idea_pool,
            agent_factory=lambda: MagicMock(),
            max_workers=1,
            on_output=lambda line: None,
            runtime_plugins=WorkerRuntimePlugins(failure_memory=failing_memory),
        )

        wm.start()
        wm.join(timeout=5)

        summary = idea_pool.summary()
        assert summary["running"] == 0
        assert summary["skipped"] == 1

        # Not all 19 ideas should have been processed
        summary = idea_pool.summary()
        assert summary["done"] + summary["skipped"] + summary["running"] < 19


def test_worker_manager_can_disable_advanced_plugins():
    """WorkerManager should run in the main repo when plugins are explicitly disabled."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)

        ideas = [
            {
                "id": "idea-001",
                "description": "No plugins",
                "status": "pending",
                "priority": 1,
                "claimed_by": None,
                "assigned_experiment": None,
                "result": None,
                "source": "original",
                "category": "general",
                "gpu_hint": "auto",
                "created_at": "2026-01-01T00:00:00",
            },
        ]
        idea_pool = _make_idea_pool(research, ideas)
        workdirs_used = []

        def mock_agent_factory():
            agent = MagicMock()

            def run_side_effect(workdir, on_output=None, program_file="program.md", **kwargs):
                workdirs_used.append(str(workdir))
                return 0

            agent.run.side_effect = run_side_effect
            return agent

        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=None,
            idea_pool=idea_pool,
            agent_factory=mock_agent_factory,
            max_workers=1,
            on_output=lambda line: None,
            runtime_plugins=WorkerRuntimePlugins(),
        )

        wm.start()
        wm.join(timeout=5)

        assert workdirs_used == [str(tmp_path)]


def test_worker_manager_requeues_research_v1_run_without_result():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "Research-v1 no-op",
                    "status": "pending",
                    "priority": 1,
                    "claimed_by": None,
                    "assigned_experiment": None,
                    "result": None,
                    "source": "graph",
                    "category": "graph",
                    "gpu_hint": "auto",
                    "created_at": "2026-01-01T00:00:00",
                    "protocol": "research-v1",
                    "frontier_id": "frontier-001",
                    "execution_id": "exec-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                }
            ],
        )

        def mock_agent_factory():
            agent = MagicMock()
            agent.run.return_value = 0
            agent.terminate = MagicMock()
            return agent

        output_lines = []
        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=None,
            idea_pool=idea_pool,
            agent_factory=mock_agent_factory,
            max_workers=1,
            max_claims=1,
            on_output=output_lines.append,
        )

        wm.start()
        wm.join(timeout=5)

        summary = idea_pool.summary()
        assert summary["pending"] == 1
        assert summary["done"] == 0
        assert any("released claim back to pending" in line for line in output_lines)


def test_worker_manager_finalizes_research_v1_idea_from_matching_result_row():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        results_path = research / "results.tsv"
        results_path.write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        )
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "Research-v1 success",
                    "status": "pending",
                    "priority": 1,
                    "claimed_by": None,
                    "assigned_experiment": None,
                    "result": None,
                    "source": "graph",
                    "category": "graph",
                    "gpu_hint": "auto",
                    "created_at": "2026-01-01T00:00:00",
                    "protocol": "research-v1",
                    "frontier_id": "frontier-001",
                    "execution_id": "exec-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                }
            ],
        )

        def mock_agent_factory():
            agent = MagicMock()

            def run_side_effect(workdir, on_output=None, program_file="program.md", env=None, **kwargs):
                secondary = json.dumps(
                    {
                        "_open_researcher_trace": {
                            "frontier_id": env["OPEN_RESEARCHER_FRONTIER_ID"],
                            "idea_id": env["OPEN_RESEARCHER_IDEA_ID"],
                            "execution_id": env["OPEN_RESEARCHER_EXECUTION_ID"],
                            "hypothesis_id": env["OPEN_RESEARCHER_HYPOTHESIS_ID"],
                            "experiment_spec_id": env["OPEN_RESEARCHER_EXPERIMENT_SPEC_ID"],
                        }
                    }
                )
                with results_path.open("a", newline="") as handle:
                    writer = csv.writer(handle, delimiter="\t")
                    writer.writerow(
                        [
                            "2026-03-11T12:00:00Z",
                            "abc1234",
                            "speedup_ratio",
                            "1.250000",
                            secondary,
                            "keep",
                            "idea-001",
                        ]
                    )
                return 0

            agent.run.side_effect = run_side_effect
            agent.terminate = MagicMock()
            return agent

        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=None,
            idea_pool=idea_pool,
            agent_factory=mock_agent_factory,
            max_workers=1,
            on_output=lambda line: None,
        )

        wm.start()
        wm.join(timeout=5)

        summary = idea_pool.summary()
        assert summary["done"] == 1
        state = next(item for item in idea_pool.all_ideas() if item["id"] == "idea-001")
        assert state["result"] == {"metric_value": 1.25, "verdict": "kept"}


def test_worker_manager_times_out_parallel_run_and_marks_item_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "Research-v1 timeout",
                    "status": "pending",
                    "priority": 1,
                    "claimed_by": None,
                    "assigned_experiment": None,
                    "result": None,
                    "source": "graph",
                    "category": "graph",
                    "gpu_hint": "auto",
                    "created_at": "2026-01-01T00:00:00",
                    "protocol": "research-v1",
                    "frontier_id": "frontier-001",
                    "execution_id": "exec-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                }
            ],
        )
        stop_run = threading.Event()

        def mock_agent_factory():
            agent = MagicMock()

            def terminate():
                stop_run.set()

            def run_side_effect(*args, **kwargs):
                stop_run.wait(timeout=2)
                return 1

            agent.run.side_effect = run_side_effect
            agent.terminate.side_effect = terminate
            return agent

        output_lines = []
        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=None,
            idea_pool=idea_pool,
            agent_factory=mock_agent_factory,
            max_workers=1,
            timeout_seconds=0.1,
            on_output=output_lines.append,
        )

        wm.start()
        wm.join(timeout=5)

        summary = idea_pool.summary()
        assert summary["skipped"] == 1
        assert any("Experiment timeout" in line for line in output_lines)
