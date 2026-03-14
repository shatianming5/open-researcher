"""Tests for the WorkerManager."""

import csv
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from open_researcher.control_plane import issue_control_command
from open_researcher.gpu_manager import GPUManager
from open_researcher.idea_pool import IdeaPool
from open_researcher.worker import WorkerManager
from open_researcher.worker_plugins import (
    FailureMemoryPlugin,
    GPUAllocation,
    GPUAllocatorPlugin,
    WorkerRuntimePlugins,
    WorkspaceIsolationError,
)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(path), capture_output=True, check=True)
    (path / "hello.py").write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(["git", "add", "hello.py"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=str(path), capture_output=True, check=True)


def _make_research_dir(tmp: Path) -> Path:
    """Set up a minimal research directory."""
    _init_git_repo(tmp)
    research = tmp / ".research"
    research.mkdir()
    return research


def _make_idea_pool(research: Path, ideas: list[dict]) -> IdeaPool:
    """Create an idea_pool.json with given ideas."""
    pool_path = research / "idea_pool.json"
    pool_path.write_text(json.dumps({"ideas": ideas}, indent=2))
    return IdeaPool(pool_path)


def _write_executable(path: Path, content: str = "#!/bin/sh\nexit 0\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


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


def test_worker_manager_stops_on_unschedulable_pending_idea():
    class NeverFitAllocator:
        default_memory_per_worker_mb = 4096

        def worker_slots(self, max_workers: int):
            return [None] * max_workers

        def select_claimable_idea(self, pending_ideas: list[dict]) -> str | None:
            return str(pending_ideas[0]["id"]) if pending_ideas else None

        def allocate_for_idea(self, worker_id: str, idea: dict, preferred=None):
            return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        ideas = [
            {
                "id": "idea-001",
                "description": "Needs unavailable resource",
                "status": "pending",
                "priority": 1,
                "result": None,
                "source": "graph",
                "category": "graph",
                "gpu_hint": 1,
                "created_at": "2026-01-01T00:00:00",
            }
        ]
        idea_pool = _make_idea_pool(research, ideas)
        output_lines = []
        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=None,
            idea_pool=idea_pool,
            agent_factory=MagicMock(),
            max_workers=1,
            on_output=output_lines.append,
            runtime_plugins=WorkerRuntimePlugins(gpu_allocator=NeverFitAllocator()),
        )

        # Patch sleep and random to make deadlock retries instant
        with patch("open_researcher.worker.time.sleep"), \
             patch("open_researcher.worker.random.uniform", return_value=0.0):
            wm.start()
            wm.join(timeout=10)

        assert all(not worker.is_alive() for worker in wm._workers)
        assert wm.resource_deadlocks >= 1
        assert idea_pool.summary()["pending"] == 1
        assert any("deadlock" in line.lower() for line in output_lines)


def test_worker_manager_handles_agent_failure():
    """Failed agent runs should mark ideas as done with verdict=crash."""
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
        assert summary["skipped"] == 0
        assert summary["done"] == 1


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


def test_worker_manager_passes_conda_runtime_env_from_bootstrap_state(monkeypatch):
    monkeypatch.delenv("CONDA_EXE", raising=False)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        conda_root = tmp_path / "miniconda3"
        env_prefix = conda_root / "envs" / "iraod"
        (env_prefix / "conda-meta").mkdir(parents=True)
        python_shim = env_prefix / "bin" / "python"
        conda_shim = conda_root / "bin" / "conda"
        _write_executable(python_shim)
        _write_executable(conda_shim)
        (research / "bootstrap_state.json").write_text(
            json.dumps(
                {
                    "python_env": {
                        "executable": str(python_shim),
                        "source": "config.bootstrap.python",
                    }
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "Conda runtime env",
                    "status": "pending",
                    "priority": 1,
                    "claimed_by": None,
                    "assigned_experiment": None,
                    "result": None,
                    "source": "graph",
                    "category": "graph",
                    "gpu_hint": "auto",
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
        )

        seen_env: dict[str, str] = {}

        def mock_agent_factory():
            agent = MagicMock()

            def run_side_effect(workdir, on_output=None, program_file="program.md", env=None, **kwargs):
                seen_env.update(env or {})
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

        assert Path(seen_env["CONDA_EXE"]).resolve() == conda_shim.resolve()
        assert Path(seen_env["CONDA_PREFIX"]).resolve() == env_prefix.resolve()
        path_parts = seen_env["PATH"].split(os.pathsep)
        assert Path(path_parts[0]).resolve() == (env_prefix / "bin").resolve()
        assert (conda_root / "bin").resolve() in {Path(item).resolve() for item in path_parts[:3]}


def test_worker_manager_reconciles_stale_running_ideas_and_gpu_reservations():
    class TrackingManager:
        def __init__(self, status_rows: list[dict]) -> None:
            self._status = status_rows
            self.released: list[dict] = []

        def refresh(self):
            return self._status

        def release_reservations(self, reservations):
            self.released.extend(reservations)
            release_ids = {
                (str(item.get("host", "")), int(item.get("device", -1)), str(item.get("id", "")))
                for item in reservations
            }
            for gpu in self._status:
                host = str(gpu.get("host", "")).strip()
                device = int(gpu.get("device", -1))
                gpu["reservations"] = [
                    item
                    for item in gpu.get("reservations", [])
                    if (host, device, str(item.get("id", ""))) not in release_ids
                ]

    class NoopAllocator:
        default_memory_per_worker_mb = 4096

        def __init__(self, manager) -> None:
            self.manager = manager

        def worker_slots(self, max_workers: int):
            return []

        def select_claimable_idea(self, pending_ideas: list[dict]) -> str | None:
            return None

        def allocate_for_idea(self, worker_id: str, idea: dict, preferred=None):
            return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        results_path = research / "results.tsv"
        results_path.write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n",
            encoding="utf-8",
        )
        secondary = json.dumps(
            {
                "_open_researcher_trace": {
                    "frontier_id": "frontier-001",
                    "idea_id": "idea-001",
                    "execution_id": "exec-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                }
            }
        )
        with results_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(
                [
                    "2026-03-13T00:00:00Z",
                    "abc1234",
                    "mAP",
                    "0.321000",
                    secondary,
                    "keep",
                    "stale result",
                ]
            )

        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "stale finished run",
                    "status": "running",
                    "priority": 1,
                    "claimed_by": "worker-0",
                    "claim_token": "claim-1",
                    "execution_id": "exec-001",
                    "frontier_id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "protocol": "research-v1",
                    "created_at": "2026-01-01T00:00:00",
                },
                {
                    "id": "idea-002",
                    "description": "stale unfinished run",
                    "status": "running",
                    "priority": 2,
                    "claimed_by": "worker-1",
                    "claim_token": "claim-2",
                    "execution_id": "exec-002",
                    "frontier_id": "frontier-002",
                    "hypothesis_id": "hyp-002",
                    "experiment_spec_id": "spec-002",
                    "protocol": "research-v1",
                    "created_at": "2026-01-01T00:00:00",
                },
            ],
        )
        manager = TrackingManager(
            [
                {
                    "host": "local",
                    "device": 4,
                    "memory_total": 49140,
                    "memory_used": 0,
                    "memory_free": 48520,
                    "utilization": 0,
                    "reservations": [
                        {
                            "id": "res-1",
                            "tag": "worker-0",
                            "kind": "experiment",
                            "execution_id": "exec-001",
                            "frontier_id": "frontier-001",
                        }
                    ],
                },
                {
                    "host": "local",
                    "device": 5,
                    "memory_total": 49140,
                    "memory_used": 0,
                    "memory_free": 48520,
                    "utilization": 0,
                    "reservations": [
                        {
                            "id": "res-2",
                            "tag": "worker-1",
                            "kind": "experiment",
                            "execution_id": "exec-002",
                            "frontier_id": "frontier-002",
                        }
                    ],
                },
                {
                    "host": "local",
                    "device": 6,
                    "memory_total": 49140,
                    "memory_used": 0,
                    "memory_free": 48520,
                    "utilization": 0,
                    "reservations": [
                        {
                            "id": "pin-6",
                            "tag": "user_pinned_excluded",
                            "kind": "user_pin",
                        }
                    ],
                },
            ]
        )
        output_lines: list[str] = []
        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=None,
            idea_pool=idea_pool,
            agent_factory=lambda: MagicMock(),
            max_workers=1,
            on_output=output_lines.append,
            runtime_plugins=WorkerRuntimePlugins(gpu_allocator=NoopAllocator(manager)),
        )

        wm._reconcile_parallel_runtime_state()

        ideas = {item["id"]: item for item in idea_pool.all_ideas()}
        assert ideas["idea-001"]["status"] == "done"
        assert ideas["idea-001"]["result"] == {"metric_value": 0.321, "verdict": "kept"}
        assert ideas["idea-002"]["status"] == "pending"
        assert len(manager.released) == 2
        assert {item["id"] for item in manager.released} == {"res-1", "res-2"}
        assert manager._status[2]["reservations"][0]["id"] == "pin-6"
        assert any("Reconciled stale running idea idea-001" in line for line in output_lines)
        assert any("Released 2 stale GPU reservation" in line for line in output_lines)


def test_worker_manager_preserves_active_detached_runtime_state():
    class TrackingManager:
        def __init__(self, status_rows: list[dict]) -> None:
            self._status = status_rows
            self.released: list[dict] = []

        def refresh(self):
            return self._status

        def release_reservations(self, reservations):
            self.released.extend(reservations)

    class NoopAllocator:
        default_memory_per_worker_mb = 4096

        def __init__(self, manager) -> None:
            self.manager = manager

        def worker_slots(self, max_workers: int):
            return []

        def select_claimable_idea(self, pending_ideas: list[dict]) -> str | None:
            return None

        def allocate_for_idea(self, worker_id: str, idea: dict, preferred=None):
            return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "detached run still active",
                    "status": "running",
                    "priority": 1,
                    "claimed_by": "worker-0",
                    "claim_token": "claim-1",
                    "execution_id": "exec-001",
                    "frontier_id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "protocol": "research-v1",
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
        )
        sleeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(1.0)"],
            start_new_session=True,
        )
        try:
            runtime_path = research / "runtime" / "idea-001__exec-001.json"
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_path.write_text(
                json.dumps(
                    {
                        "idea_id": "idea-001",
                        "execution_id": "exec-001",
                        "frontier_id": "frontier-001",
                        "active": True,
                        "status": "running",
                        "pid": sleeper.pid,
                        "pgid": sleeper.pid,
                    }
                ),
                encoding="utf-8",
            )
            manager = TrackingManager(
                [
                    {
                        "host": "local",
                        "device": 4,
                        "memory_total": 49140,
                        "memory_used": 0,
                        "memory_free": 48520,
                        "utilization": 0,
                        "reservations": [
                            {
                                "id": "res-1",
                                "tag": "worker-0",
                                "kind": "experiment",
                                "execution_id": "exec-001",
                                "frontier_id": "frontier-001",
                            }
                        ],
                    }
                ]
            )
            wm = WorkerManager(
                repo_path=tmp_path,
                research_dir=research,
                gpu_manager=None,
                idea_pool=idea_pool,
                agent_factory=lambda: MagicMock(),
                max_workers=1,
                on_output=lambda line: None,
                runtime_plugins=WorkerRuntimePlugins(gpu_allocator=NoopAllocator(manager)),
            )

            wm._reconcile_parallel_runtime_state()

            ideas = {item["id"]: item for item in idea_pool.all_ideas()}
            assert ideas["idea-001"]["status"] == "running"
            assert manager.released == []
        finally:
            sleeper.terminate()
            sleeper.wait(timeout=5)


def test_worker_manager_reconcile_clears_stale_activity_workers():
    class TrackingManager:
        def __init__(self, status_rows: list[dict]) -> None:
            self._status = status_rows
            self.released: list[dict] = []

        def refresh(self):
            return self._status

        def release_reservations(self, reservations):
            self.released.extend(reservations)

    class NoopAllocator:
        default_memory_per_worker_mb = 4096

        def __init__(self, manager) -> None:
            self.manager = manager

        def worker_slots(self, max_workers: int):
            return []

        def select_claimable_idea(self, pending_ideas: list[dict]) -> str | None:
            return None

        def allocate_for_idea(self, worker_id: str, idea: dict, preferred=None):
            return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        from open_researcher.activity import ActivityMonitor

        activity = ActivityMonitor(research)
        activity.update_worker("experiment_agent", "worker-0", status="running", idea="idea-001")
        activity.update_worker("experiment_agent", "worker-1", status="running", idea="idea-002")
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "stale unfinished run",
                    "status": "running",
                    "priority": 1,
                    "claim_token": "claim-1",
                    "execution_id": "exec-001",
                    "frontier_id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "protocol": "research-v1",
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
        )
        manager = TrackingManager(
            [
                {
                    "host": "local",
                    "device": 4,
                    "memory_total": 49140,
                    "memory_used": 0,
                    "memory_free": 48520,
                    "utilization": 0,
                    "reservations": [
                        {
                            "id": "res-1",
                            "tag": "worker-0",
                            "kind": "experiment",
                            "execution_id": "exec-001",
                            "frontier_id": "frontier-001",
                        }
                    ],
                }
            ]
        )
        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=None,
            idea_pool=idea_pool,
            agent_factory=lambda: MagicMock(),
            max_workers=1,
            on_output=lambda line: None,
            runtime_plugins=WorkerRuntimePlugins(gpu_allocator=NoopAllocator(manager)),
        )

        wm._reconcile_parallel_runtime_state()

        state = activity.get("experiment_agent")
        assert state["workers"] == []
        assert state["active_workers"] == 0
        assert state["status"] == "idle"


def test_worker_manager_join_clears_finished_worker_activity():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "Fast worker cleanup",
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

        from open_researcher.activity import ActivityMonitor

        state = ActivityMonitor(research).get("experiment_agent")
        assert state["workers"] == []
        assert state["active_workers"] == 0
        assert state["status"] == "idle"


def test_gpu_allocator_honors_execution_shape_gpu_scope():
    nvidia_smi_output = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
0, 49140 MiB, 0 MiB, 49140 MiB, 0 %
1, 49140 MiB, 0 MiB, 49140 MiB, 0 %
2, 49140 MiB, 0 MiB, 49140 MiB, 0 %
3, 49140 MiB, 0 MiB, 49140 MiB, 0 %
4, 49140 MiB, 0 MiB, 49140 MiB, 0 %
5, 49140 MiB, 0 MiB, 49140 MiB, 0 %
"""

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        manager = GPUManager(research / "gpu_status.json")
        allocator = GPUAllocatorPlugin(manager, default_memory_per_worker_mb=4096)
        idea = {
            "id": "idea-001",
            "description": "Pinned 2-GPU run",
            "execution_shape": {"gpus": "4,5"},
            "resource_request": {
                "gpu_count": 2,
                "gpu_mem_mb": 4096,
                "exclusive": True,
                "shareable": False,
            },
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=nvidia_smi_output)
            allocation = allocator.allocate_for_idea("worker-0", idea)

        assert allocation is not None
        assert allocation.env["CUDA_VISIBLE_DEVICES"] == "4,5"
        assert {(item["host"], item["device"]) for item in allocation.devices} == {("local", 4), ("local", 5)}


def test_worker_manager_rolls_back_failed_run_in_main_repo():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "Main repo rollback",
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

            def run_side_effect(workdir, on_output=None, program_file="program.md", **kwargs):
                (workdir / "hello.py").write_text("print('mutated')\n", encoding="utf-8")
                return 1

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
            runtime_plugins=WorkerRuntimePlugins(),
        )

        wm.start()
        wm.join(timeout=5)

        summary = idea_pool.summary()
        assert summary["done"] == 1
        assert (tmp_path / "hello.py").read_text(encoding="utf-8") == "print('hello')\n"
        status = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=True,
        )
        assert all(".research" in line for line in status.stdout.splitlines())


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
        assert summary["done"] == 1

        # Not all 19 ideas should have been processed
        summary = idea_pool.summary()
        assert summary["done"] + summary["skipped"] + summary["running"] < 19


def test_worker_manager_releases_gpu_when_setup_raises_before_agent_run():
    class TrackingAllocator:
        default_memory_per_worker_mb = 4096

        def __init__(self) -> None:
            self.released: list[GPUAllocation] = []

        def worker_slots(self, max_workers: int):
            return [None] * max(max_workers, 1)

        def select_claimable_idea(self, pending_ideas: list[dict]) -> str | None:
            return str(pending_ideas[0]["id"]) if pending_ideas else None

        def allocate_for_idea(self, worker_id: str, idea: dict, preferred=None):
            return GPUAllocation(
                host="local",
                device=0,
                reservations=[
                    {
                        "host": "local",
                        "device": 0,
                        "id": "res-test",
                        "tag": worker_id,
                        "memory_mb": 4096,
                        "gpu_count": 1,
                    }
                ],
                resource_request={"gpu_count": 1, "gpu_mem_mb": 4096},
            )

        def release(self, allocation: GPUAllocation) -> None:
            self.released.append(allocation)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "Setup crash with GPU allocation",
                    "status": "pending",
                    "priority": 1,
                    "claimed_by": None,
                    "assigned_experiment": None,
                    "result": None,
                    "source": "graph",
                    "category": "graph",
                    "gpu_hint": 1,
                    "created_at": "2026-01-01T00:00:00",
                }
            ],
        )

        failing_memory = MagicMock(spec=FailureMemoryPlugin)
        failing_memory.prepare.side_effect = RuntimeError("prepare failed")
        allocator = TrackingAllocator()
        output_lines: list[str] = []

        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=None,
            idea_pool=idea_pool,
            agent_factory=lambda: MagicMock(),
            max_workers=1,
            on_output=output_lines.append,
            runtime_plugins=WorkerRuntimePlugins(
                gpu_allocator=allocator,
                failure_memory=failing_memory,
            ),
        )

        wm.start()
        wm.join(timeout=5)

        summary = idea_pool.summary()
        assert summary["done"] == 1
        assert wm.fatal_errors == 0
        assert len(allocator.released) == 1
        assert not any("Fatal worker error" in line for line in output_lines)


def test_worker_manager_stops_when_workspace_isolation_fails():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        idea_pool = _make_idea_pool(
            research,
            [
                {
                    "id": "idea-001",
                    "description": "Isolation failure",
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

        isolation = MagicMock()
        isolation.acquire.side_effect = WorkspaceIsolationError("forced worktree failure")
        agent_factory = MagicMock()
        output_lines = []

        wm = WorkerManager(
            repo_path=tmp_path,
            research_dir=research,
            gpu_manager=None,
            idea_pool=idea_pool,
            agent_factory=agent_factory,
            max_workers=1,
            on_output=output_lines.append,
            runtime_plugins=WorkerRuntimePlugins(workspace_isolation=isolation),
        )

        wm.start()
        wm.join(timeout=5)

        agent_factory.assert_not_called()
        summary = idea_pool.summary()
        assert summary["pending"] == 1
        assert wm.fatal_errors == 1
        assert any("Fatal runtime safety error" in line for line in output_lines)


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
        run_calls = []

        def mock_agent_factory():
            agent = MagicMock()

            def run_side_effect(*args, **kwargs):
                run_calls.append("run")
                return 0

            agent.run.side_effect = run_side_effect
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
            max_claims=3,
            on_output=output_lines.append,
        )

        wm.start()
        wm.join(timeout=5)

        summary = idea_pool.summary()
        assert summary["pending"] == 1
        assert summary["done"] == 0
        assert run_calls == ["run"]
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


def test_worker_manager_augments_result_row_with_single_gpu_saturation_metadata():
    class FixedAllocator:
        default_memory_per_worker_mb = 4096

        def worker_slots(self, max_workers: int):
            return [{"host": "local", "device": 0}]

        def select_claimable_idea(self, pending_ideas: list[dict]) -> str | None:
            return str(pending_ideas[0]["id"]) if pending_ideas else None

        def allocate_for_idea(self, worker_id: str, idea: dict, preferred=None):
            return GPUAllocation(
                host="local",
                device=0,
                devices=[{"host": "local", "device": 0}],
                reservations=[{"host": "local", "device": 0, "memory_mb": 4096}],
                resource_request={"gpu_count": 1, "gpu_mem_mb": 4096, "exclusive": True, "shareable": False},
                selected_profile={"name": "__idea_default__", "expected_memory_mb": 14000},
                execution_shape={"batch_size": 8},
                saturation_context={
                    "gpu_budget_mb": 16000,
                    "headroom_mb": 2048,
                    "qualification_timeout_minutes": 10,
                    "profiles": [{"name": "__idea_default__"}],
                    "qualification_profiles": [{"name": "__idea_default__"}],
                },
                env={
                    "CUDA_VISIBLE_DEVICES": "0",
                    "OPEN_RESEARCHER_SINGLE_GPU_SATURATION": "1",
                    "OPEN_RESEARCHER_AGENT_OWNS_SATURATION_SHAPE": "1",
                    "OPEN_RESEARCHER_GPU_MEMORY_BUDGET_MB": "16000",
                },
            )

        def release(self, allocation):
            return None

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
                    "description": "Saturate one GPU",
                    "status": "pending",
                    "priority": 1,
                    "claimed_by": None,
                    "assigned_experiment": None,
                    "result": None,
                    "source": "graph",
                    "category": "graph",
                    "gpu_hint": 1,
                    "created_at": "2026-01-01T00:00:00",
                    "protocol": "research-v1",
                    "frontier_id": "frontier-001",
                    "execution_id": "exec-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "execution_shape": {"batch_size": 8},
                }
            ],
        )

        def mock_agent_factory():
            agent = MagicMock()

            def run_side_effect(workdir, on_output=None, program_file="program.md", env=None, **kwargs):
                selection_path = research / "runtime" / "idea-001__exec-001__saturation_selection.json"
                selection_path.parent.mkdir(parents=True, exist_ok=True)
                selection_path.write_text(
                    json.dumps(
                        {
                            "selected_profile": "single_gpu_large",
                            "qualification_attempts": 2,
                            "expected_peak_gpu_mem_mb": 15000,
                        }
                    ),
                    encoding="utf-8",
                )
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
                            "mAP",
                            "0.712300",
                            secondary,
                            "keep",
                            "idea-001",
                        ]
                    )
                return 0

            agent.run.side_effect = run_side_effect
            agent.terminate = MagicMock()
            return agent

        call_counter = {"count": 0}

        def fake_gpu_snapshot(devices):
            call_counter["count"] += 1
            used_mb = 1000 if call_counter["count"] == 1 else 16000
            return {0: {"memory_total": 49152, "memory_used": used_mb, "memory_free": 49152 - used_mb}}

        with patch.object(WorkerManager, "_local_gpu_memory_snapshot", side_effect=fake_gpu_snapshot):
            wm = WorkerManager(
                repo_path=tmp_path,
                research_dir=research,
                gpu_manager=None,
                idea_pool=idea_pool,
                agent_factory=mock_agent_factory,
                max_workers=1,
                on_output=lambda line: None,
                runtime_plugins=WorkerRuntimePlugins(gpu_allocator=FixedAllocator()),
            )

            wm.start()
            wm.join(timeout=5)

        rows = list(csv.DictReader(results_path.open(), delimiter="\t"))
        assert len(rows) == 1
        secondary = json.loads(rows[0]["secondary_metrics"])
        resources = secondary["_open_researcher_resources"]
        assert resources["selected_resource_profile"] == "single_gpu_large"
        assert resources["qualification_attempts"] == 2
        assert resources["saturation_status"] == "saturated"
        state = next(item for item in idea_pool.all_ideas() if item["id"] == "idea-001")
        assert state["resource_observation"]["selected_resource_profile"] == "single_gpu_large"


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
        assert summary["done"] == 1
        assert any("Experiment timeout" in line for line in output_lines)


def test_worker_manager_waits_for_registered_detached_run_result():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        results_path = research / "results.tsv"
        results_path.write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n",
            encoding="utf-8",
        )
        idea = {
            "id": "idea-001",
            "description": "Detached long run",
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
        idea_pool = _make_idea_pool(research, [idea])
        output_lines: list[str] = []

        def mock_agent_factory():
            agent = MagicMock()

            def run_side_effect(workdir, on_output=None, program_file="program.md", env=None, **kwargs):
                detached = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(0.4)",
                    ],
                    cwd=str(workdir),
                    start_new_session=True,
                )
                state_path = research / "runtime" / "idea-001__exec-001.json"
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "idea_id": env["OPEN_RESEARCHER_IDEA_ID"],
                            "execution_id": env["OPEN_RESEARCHER_EXECUTION_ID"],
                            "frontier_id": env["OPEN_RESEARCHER_FRONTIER_ID"],
                            "active": True,
                            "status": "running",
                            "pid": detached.pid,
                            "pgid": detached.pid,
                        }
                    ),
                    encoding="utf-8",
                )

                def _record_after_wait() -> None:
                    detached.wait(timeout=5)
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
                    with results_path.open("a", newline="", encoding="utf-8") as handle:
                        writer = csv.writer(handle, delimiter="\t")
                        writer.writerow(
                            [
                                "2026-03-12T12:00:00Z",
                                "abc1234",
                                "mAP",
                                "0.654321",
                                secondary,
                                "keep",
                                "detached-idea",
                            ]
                        )
                    state_path.write_text(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "idea_id": env["OPEN_RESEARCHER_IDEA_ID"],
                                "execution_id": env["OPEN_RESEARCHER_EXECUTION_ID"],
                                "frontier_id": env["OPEN_RESEARCHER_FRONTIER_ID"],
                                "active": False,
                                "status": "completed",
                                "pid": detached.pid,
                                "pgid": detached.pid,
                                "exit_code": 0,
                            }
                        ),
                        encoding="utf-8",
                    )

                threading.Thread(target=_record_after_wait, daemon=True).start()
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
            on_output=output_lines.append,
        )

        wm.start()
        wm.join(timeout=10)

        summary = idea_pool.summary()
        assert summary["done"] == 1
        state = next(item for item in idea_pool.all_ideas() if item["id"] == "idea-001")
        assert state["result"] == {"metric_value": 0.654321, "verdict": "kept"}
        assert any("Monitoring detached run" in line for line in output_lines)


def test_worker_manager_requeues_failed_registered_detached_run_without_result():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        research = _make_research_dir(tmp_path)
        results_path = research / "results.tsv"
        results_path.write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n",
            encoding="utf-8",
        )
        idea = {
            "id": "idea-001",
            "description": "Detached run without result",
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
        idea_pool = _make_idea_pool(research, [idea])
        output_lines: list[str] = []

        def mock_agent_factory():
            agent = MagicMock()

            def run_side_effect(workdir, on_output=None, program_file="program.md", env=None, **kwargs):
                detached = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        "import time; time.sleep(0.2)",
                    ],
                    cwd=str(workdir),
                    start_new_session=True,
                )
                state_path = research / "runtime" / "idea-001__exec-001.json"
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "idea_id": env["OPEN_RESEARCHER_IDEA_ID"],
                            "execution_id": env["OPEN_RESEARCHER_EXECUTION_ID"],
                            "frontier_id": env["OPEN_RESEARCHER_FRONTIER_ID"],
                            "active": True,
                            "status": "running",
                            "pid": detached.pid,
                            "pgid": detached.pid,
                        }
                    ),
                    encoding="utf-8",
                )

                def _close_after_wait() -> None:
                    detached.wait(timeout=5)
                    state_path.write_text(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "idea_id": env["OPEN_RESEARCHER_IDEA_ID"],
                                "execution_id": env["OPEN_RESEARCHER_EXECUTION_ID"],
                                "frontier_id": env["OPEN_RESEARCHER_FRONTIER_ID"],
                                "active": False,
                                "status": "failed",
                                "pid": detached.pid,
                                "pgid": detached.pid,
                                "exit_code": 7,
                            }
                        ),
                        encoding="utf-8",
                    )

                threading.Thread(target=_close_after_wait, daemon=True).start()
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
            max_claims=1,
            on_output=output_lines.append,
        )

        wm.start()
        wm.join(timeout=10)

        summary = idea_pool.summary()
        assert summary["pending"] == 1
        state = next(item for item in idea_pool.all_ideas() if item["id"] == "idea-001")
        assert state["status"] == "pending"
        assert any("Detached run failure released" in line for line in output_lines)
