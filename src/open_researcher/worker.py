"""Parallel worker manager -- run experiments across multiple GPUs."""

import hashlib
import json
import logging
import os
import random
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from filelock import FileLock

from open_researcher.activity import ActivityMonitor
from open_researcher.bootstrap import command_env_for_python, read_bootstrap_state
from open_researcher.config import load_config
from open_researcher.control_plane import consume_skip_current, read_control
from open_researcher.gpu_manager import GPUManager
from open_researcher.idea_pool import IdeaPool
from open_researcher.plugins.orchestrator.safety import (
    GitWorkspaceError,
    capture_clean_workspace_snapshot,
    ensure_clean_workspace,
    rollback_workspace,
)
from open_researcher.resource_scheduler import classify_single_gpu_saturation_status
from open_researcher.results_cmd import augment_result_secondary_metrics, load_results
from open_researcher.role_programs import resolve_role_program_file
from open_researcher.storage import atomic_write_json
from open_researcher.watchdog import TimeoutWatchdog
from open_researcher.worker_plugins import (
    WorkerRuntimePlugins,
    WorkspaceIsolationError,
    build_default_worker_plugins,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DetachedRunOutcome:
    """Outcome of monitoring a detached long-running experiment."""

    matched_row: dict | None = None
    result_status: str = ""
    run_code: int = 1
    should_requeue: bool = False
    stop_after_finalize: bool = False
    """When True, signals the worker manager to stop all workers after finalizing this run."""


@dataclass(slots=True)
class GPURunTelemetry:
    """Observed device memory usage for one experiment run."""

    baseline_memory_used_mb: int | None = None
    peak_memory_used_mb: int | None = None
    peak_task_memory_mb: int | None = None
    samples: int = 0


class WorkerManager:
    """Orchestrate parallel experiment workers across GPUs."""

    def __init__(
        self,
        repo_path: Path,
        research_dir: Path,
        gpu_manager: GPUManager | None,
        idea_pool: IdeaPool,
        agent_factory: Callable,
        max_workers: int,
        on_output: Callable[[str], None],
        runtime_plugins: WorkerRuntimePlugins | None = None,
        stop_event: threading.Event | None = None,
        max_claims: int | None = None,
        timeout_seconds: int = 0,
        on_experiment_started: Callable[[dict], None] | None = None,
        on_experiment_finished: Callable[[dict], bool | None] | None = None,
        backfill_threshold_minutes: int = 30,
    ):
        self.repo_path = repo_path
        self.research_dir = research_dir
        self.idea_pool = idea_pool
        self.agent_factory = agent_factory
        self.max_workers = max_workers
        self.on_output = on_output
        self._stop = threading.Event()
        self._external_stop = stop_event
        self._workers: list[threading.Thread] = []
        self._activity = ActivityMonitor(research_dir)
        self._plugins = runtime_plugins or build_default_worker_plugins(
            repo_path=repo_path,
            research_dir=research_dir,
            gpu_manager=gpu_manager,
        )
        self._max_claims = max_claims if max_claims and max_claims > 0 else None
        self._timeout_seconds = max(float(timeout_seconds or 0), 0.0)
        self._claims_started = 0
        self._claim_lock = threading.Lock()
        self._on_experiment_started = on_experiment_started
        self._on_experiment_finished = on_experiment_finished
        self._fatal_errors = 0
        self._fatal_lock = threading.Lock()
        self._backfill_threshold_minutes = max(int(backfill_threshold_minutes or 0), 1)
        self._resource_deadlocks = 0
        self._resource_deadlock_lock = threading.Lock()
        self._runtime_shell_env = self._resolve_runtime_shell_env()

    def start(self) -> None:
        """Start worker threads based on available GPUs."""
        self._stop.clear()
        self._workers.clear()
        self._activity.clear_workers("experiment_agent", status="idle", detail="0 active worker(s)", idea="")
        self._reconcile_parallel_runtime_state()
        slots: list[dict | None]
        if self._plugins.gpu_allocator is not None:
            slots = self._plugins.gpu_allocator.worker_slots(self.max_workers)
        else:
            n_workers = max(self.max_workers, 1) if self.max_workers > 0 else 1
            slots = [None] * n_workers

        for i, gpu in enumerate(slots):
            t = threading.Thread(target=self._worker_loop, args=(i, gpu), daemon=True)
            t.start()
            self._workers.append(t)
        self.on_output(f"[system] Started {len(slots)} worker(s)")

    def stop(self) -> None:
        """Signal all workers to stop."""
        self._stop.set()

    def _should_stop(self) -> bool:
        return self._stop.is_set() or (self._external_stop is not None and self._external_stop.is_set())

    def _reserve_claim_slot(self) -> bool:
        if self._max_claims is None:
            return True
        with self._claim_lock:
            if self._claims_started >= self._max_claims:
                return False
            self._claims_started += 1
            return True

    def _release_claim_slot(self) -> None:
        if self._max_claims is None:
            return
        with self._claim_lock:
            self._claims_started = max(self._claims_started - 1, 0)

    @staticmethod
    def _safe_float(value) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_secondary_metrics(row: dict) -> dict:
        raw = row.get("secondary_metrics", "{}") if isinstance(row, dict) else "{}"
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _current_idea_state(self, idea_id: str) -> dict:
        return next(
            (item for item in self.idea_pool.all_ideas() if item.get("id") == idea_id),
            {},
        )

    def _find_matching_result_row(
        self,
        repo_path: Path,
        *,
        results_before_count: int,
        idea: dict,
    ) -> dict | None:
        _results_lock = FileLock(str(repo_path / ".research" / "results.tsv.lock"), timeout=10)
        with _results_lock:
            rows = load_results(repo_path)
        expected_idea_id = str(idea.get("id", "")).strip()
        expected_execution_id = str(idea.get("execution_id", "")).strip()
        expected_frontier_id = str(idea.get("frontier_id", "")).strip()
        if not expected_idea_id:
            return None
        for row in reversed(rows[max(results_before_count, 0) :]):
            secondary = self._parse_secondary_metrics(row)
            trace = secondary.get("_open_researcher_trace", {})
            if not isinstance(trace, dict):
                continue
            if str(trace.get("idea_id", "")).strip() != expected_idea_id:
                continue
            if expected_execution_id and str(trace.get("execution_id", "")).strip() != expected_execution_id:
                continue
            if expected_frontier_id and str(trace.get("frontier_id", "")).strip() != expected_frontier_id:
                continue
            return row
        return None

    @staticmethod
    def _terminal_result_present(idea_state: dict) -> bool:
        status = str(idea_state.get("status", "")).strip()
        if status == "skipped":
            return True
        if status != "done":
            return False
        result = idea_state.get("result")
        if not isinstance(result, dict):
            return False
        verdict = str(result.get("verdict", "")).strip()
        metric = WorkerManager._safe_float(result.get("metric_value"))
        return verdict in {"kept", "discarded", "crash"} or metric is not None

    @staticmethod
    def _result_payload_from_row(row: dict) -> tuple[float | None, str]:
        status = str(row.get("status", "")).strip()
        metric_value = WorkerManager._safe_float(row.get("metric_value"))
        verdict = {
            "keep": "kept",
            "discard": "discarded",
            "crash": "crash",
        }.get(status, "completed")
        return metric_value, verdict

    @staticmethod
    def _result_status_from_row(row: dict | None) -> str:
        if not isinstance(row, dict):
            return ""
        return str(row.get("status", "")).strip()

    @staticmethod
    def _status_requires_rollback(status: str) -> bool:
        return status in {"discard", "crash"}

    def _return_idea_to_pending(self, idea_id: str, *, claim_token: str) -> bool:
        applied = self.idea_pool.update_status(idea_id, "pending", claim_token=claim_token or None)
        if applied:
            return True
        current = self._current_idea_state(idea_id)
        finished_claim_token = str(current.get("finished_claim_token", "")).strip()
        if (
            claim_token
            and finished_claim_token == claim_token
            and str(current.get("status", "")).strip() in {"done", "skipped"}
        ):
            return self.idea_pool.update_status(idea_id, "pending")
        return False

    @staticmethod
    def _safe_state_component(value: str, fallback: str) -> str:
        raw = str(value or "").strip()
        cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw)
        if not cleaned:
            return fallback
        if cleaned != raw:
            cleaned = cleaned + "_" + hashlib.md5(raw.encode()).hexdigest()[:8]
        return cleaned

    def _detached_state_path(self, idea: dict) -> Path:
        idea_id = self._safe_state_component(str(idea.get("id", "")).strip(), "idea")
        execution_id = self._safe_state_component(str(idea.get("execution_id", "")).strip(), "exec")
        return self.research_dir / "runtime" / f"{idea_id}__{execution_id}.json"

    def _load_detached_state(self, idea: dict) -> dict | None:
        path = self._detached_state_path(idea)
        if not path.exists():
            return None
        lock = FileLock(str(path) + ".lock", timeout=5)
        with lock:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                return None
        if not isinstance(data, dict):
            return None
        expected_idea_id = str(idea.get("id", "")).strip()
        expected_execution_id = str(idea.get("execution_id", "")).strip()
        if expected_idea_id and str(data.get("idea_id", "")).strip() not in {"", expected_idea_id}:
            return None
        if expected_execution_id and str(data.get("execution_id", "")).strip() not in {"", expected_execution_id}:
            return None
        payload = dict(data)
        payload["_state_path"] = str(path)
        return payload

    def _write_detached_state(self, idea: dict, payload: dict) -> None:
        path = self._detached_state_path(idea)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(path) + ".lock", timeout=5)
        with lock:
            atomic_write_json(path, payload)

    def _saturation_context_path(self, idea: dict) -> Path:
        idea_id = self._safe_state_component(str(idea.get("id", "")).strip(), "idea")
        execution_id = self._safe_state_component(str(idea.get("execution_id", "")).strip(), "exec")
        return self.research_dir / "runtime" / f"{idea_id}__{execution_id}__saturation_context.json"

    def _saturation_selection_path(self, idea: dict) -> Path:
        idea_id = self._safe_state_component(str(idea.get("id", "")).strip(), "idea")
        execution_id = self._safe_state_component(str(idea.get("execution_id", "")).strip(), "exec")
        return self.research_dir / "runtime" / f"{idea_id}__{execution_id}__saturation_selection.json"

    def _write_saturation_context(self, idea: dict, allocation) -> str:
        context = dict(getattr(allocation, "saturation_context", {}) or {})
        if not context:
            return ""
        context.update(
            {
                "idea_id": str(idea.get("id", "")).strip(),
                "execution_id": str(idea.get("execution_id", "")).strip(),
                "frontier_id": str(idea.get("frontier_id", "")).strip(),
                "selected_profile": str(context.get("selected_profile", "")).strip(),
                "default_profile": str(
                    context.get("default_profile", "")
                    or getattr(allocation, "selected_profile", {}).get("name", "")
                    or idea.get("resource_profile", "")
                ).strip(),
                "execution_shape": getattr(allocation, "execution_shape", {}) or context.get("execution_shape", {}),
            }
        )
        path = self._saturation_context_path(idea)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, context)
        return str(path)

    def _load_saturation_selection(self, idea: dict) -> dict:
        path = self._saturation_selection_path(idea)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    @staticmethod
    def _local_gpu_memory_snapshot(devices: list[dict]) -> dict[int, dict[str, int]]:
        if not devices or any(str(item.get("host", "local")).strip() not in {"", "local"} for item in devices):
            return {}
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,memory.total,memory.used,memory.free",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (FileNotFoundError, OSError):
            return {}
        if result.returncode != 0:
            return {}
        requested = {
            int(item.get("device", -1))
            for item in devices
            if isinstance(item, dict) and str(item.get("host", "local")).strip() in {"", "local"}
        }
        snapshot: dict[int, dict[str, int]] = {}
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                device = int(parts[0])
                total_mb = int(parts[1])
                used_mb = int(parts[2])
                free_mb = int(parts[3])
            except ValueError:
                continue
            if device not in requested:
                continue
            snapshot[device] = {
                "memory_total": total_mb,
                "memory_used": used_mb,
                "memory_free": free_mb,
            }
        return snapshot

    def _start_gpu_telemetry_monitor(self, allocation) -> tuple[GPURunTelemetry, Callable[[], None] | None]:
        telemetry = GPURunTelemetry()
        devices = list(getattr(allocation, "devices", []) or [])
        if not devices:
            return telemetry, None
        initial = self._local_gpu_memory_snapshot(devices)
        if not initial:
            return telemetry, None
        baseline_used = sum(int(item.get("memory_used", 0) or 0) for item in initial.values())
        telemetry.baseline_memory_used_mb = baseline_used
        telemetry.peak_memory_used_mb = baseline_used
        telemetry.peak_task_memory_mb = 0
        stop_event = threading.Event()

        def _sample_once() -> None:
            snapshot = self._local_gpu_memory_snapshot(devices)
            if not snapshot:
                return
            total_used = sum(int(item.get("memory_used", 0) or 0) for item in snapshot.values())
            telemetry.samples += 1
            telemetry.peak_memory_used_mb = max(int(telemetry.peak_memory_used_mb or 0), total_used)
            baseline = int(telemetry.baseline_memory_used_mb or 0)
            telemetry.peak_task_memory_mb = max(int(telemetry.peak_task_memory_mb or 0), max(total_used - baseline, 0))

        def _poll() -> None:
            while not stop_event.wait(0.5):
                _sample_once()

        thread = threading.Thread(target=_poll, daemon=True)
        thread.start()

        def _stop() -> None:
            stop_event.set()
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning("GPU telemetry monitor thread did not exit within timeout")
            _sample_once()

        return telemetry, _stop

    @staticmethod
    def _detached_process_alive(state: dict | None) -> bool:
        if not isinstance(state, dict):
            return False
        try:
            pid = int(state.get("pid", 0) or 0)
        except (TypeError, ValueError):
            return False
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _terminate_detached_process(self, state: dict, *, wid: str, reason: str, sig: int = signal.SIGTERM) -> None:
        pid = 0
        pgid = 0
        try:
            pid = int(state.get("pid", 0) or 0)
        except (TypeError, ValueError):
            pid = 0
        try:
            pgid = int(state.get("pgid", 0) or 0)
        except (TypeError, ValueError):
            pgid = 0

        sent = False
        if pgid > 0:
            try:
                os.killpg(pgid, sig)
                sent = True
            except ProcessLookupError:
                sent = False
            except OSError:
                sent = False
        if not sent and pid > 0:
            try:
                os.kill(pid, sig)
                sent = True
            except ProcessLookupError:
                sent = False
            except OSError:
                sent = False
        if sent:
            self.on_output(f"[{wid}] Sent signal {int(sig)} to detached run for {reason}")
            wait_started = time.monotonic()
            while time.monotonic() - wait_started < 5.0:
                if not self._detached_process_alive(state):
                    return
                time.sleep(0.1)
            if sig != signal.SIGKILL:
                self._terminate_detached_process(state, wid=wid, reason=reason, sig=signal.SIGKILL)

    def _monitor_detached_run(
        self,
        *,
        wid: str,
        idea: dict,
        workdir: Path,
        results_before_count: int,
        claim_token: str,
        run_started_at: float | None,
    ) -> DetachedRunOutcome:
        state_wait_started = time.monotonic()
        state = self._load_detached_state(idea)
        while state is None and not self._should_stop():
            if time.monotonic() - state_wait_started >= 2.0:
                break
            time.sleep(0.1)
            state = self._load_detached_state(idea)
        if state is None:
            return DetachedRunOutcome(
                matched_row=None,
                result_status="",
                run_code=1,
                should_requeue=True,
                stop_after_finalize=True,
            )

        self.on_output(
            f"[{wid}] Monitoring detached run for {idea['id']} via {Path(state['_state_path']).name}"
        )
        self._activity.update_worker(
            "experiment_agent",
            wid,
            status="monitoring",
            idea=str(idea.get("description", ""))[:50],
            detached_state=str(state.get("_state_path", "")).strip(),
        )
        deadline = (
            float(run_started_at) + self._timeout_seconds
            if run_started_at is not None and self._timeout_seconds > 0
            else None
        )
        while True:
            state = self._load_detached_state(idea) or state
            alive = self._detached_process_alive(state)
            active = alive or (bool(state.get("active", False)) and not state.get("pid"))
            matched_row = self._find_matching_result_row(
                workdir,
                results_before_count=results_before_count,
                idea=idea,
            )
            result_status = self._result_status_from_row(matched_row)

            if matched_row is not None and not alive:
                return DetachedRunOutcome(
                    matched_row=matched_row,
                    result_status=result_status,
                    run_code=0,
                )

            if deadline is not None and time.monotonic() >= deadline:
                self.on_output(f"[{wid}] Detached run for {idea['id']} exceeded timeout; terminating")
                self._terminate_detached_process(state, wid=wid, reason=str(idea.get("id", "")).strip())
                state = dict(state)
                state.update(
                    {
                        "active": False,
                        "status": "timed_out",
                        "exit_code": 124,
                        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                )
                self._write_detached_state(idea, state)
                return DetachedRunOutcome(
                    matched_row=None,
                    result_status="",
                    run_code=124,
                    should_requeue=True,
                    stop_after_finalize=True,
                )

            if self._should_stop():
                self.on_output(f"[{wid}] Stop requested while monitoring detached run for {idea['id']}")
                self._terminate_detached_process(
                    state,
                    wid=wid,
                    reason=str(idea.get("id", "")).strip(),
                )
                return DetachedRunOutcome(
                    matched_row=None,
                    result_status="",
                    run_code=1,
                    should_requeue=True,
                    stop_after_finalize=True,
                )

            if not active:
                detached_exit = self._safe_float(state.get("exit_code"))
                exit_code = int(detached_exit) if detached_exit is not None else 1
                self.on_output(
                    f"[{wid}] Detached run for {idea['id']} exited without recording a result"
                )
                reapplied = self._return_idea_to_pending(
                    str(idea.get("id", "")).strip(),
                    claim_token=claim_token,
                )
                if reapplied:
                    self.on_output(f"[{wid}] Detached run failure released {idea['id']} back to pending")
                else:
                    self.on_output(
                        f"[{wid}] Claim race detected for {idea['id']}; pending release suppressed after detached run"
                    )
                return DetachedRunOutcome(
                    matched_row=None,
                    result_status="",
                    run_code=exit_code if exit_code != 0 else 1,
                    should_requeue=False,
                    stop_after_finalize=True,
                )

            time.sleep(0.5)

    def join(self, timeout: float | None = None) -> None:
        """Wait for all worker threads to finish."""
        for t in self._workers:
            t.join(timeout=timeout)
        if all(not thread.is_alive() for thread in self._workers):
            self._activity.clear_workers("experiment_agent", status="idle", detail="0 active worker(s)", idea="")

    @property
    def fatal_errors(self) -> int:
        with self._fatal_lock:
            return self._fatal_errors

    def _record_fatal_error(self) -> None:
        with self._fatal_lock:
            self._fatal_errors += 1

    @property
    def resource_deadlocks(self) -> int:
        with self._resource_deadlock_lock:
            return self._resource_deadlocks

    def _record_resource_deadlock(self) -> None:
        with self._resource_deadlock_lock:
            self._resource_deadlocks += 1

    def _wait_until_unpaused(self) -> bool:
        while not self._should_stop():
            ctrl = read_control(self.research_dir / "control.json")
            if not bool(ctrl.get("paused", False)):
                return True
            time.sleep(0.2)
        return False

    def _resolve_runtime_shell_env(self) -> dict[str, str]:
        python_executable = ""
        try:
            state = read_bootstrap_state(self.research_dir / "bootstrap_state.json")
            python_executable = str(state.get("python_env", {}).get("executable", "")).strip()
        except Exception:
            python_executable = ""
        if not python_executable:
            try:
                cfg = load_config(self.research_dir, strict=False)
                candidate = str(getattr(cfg, "bootstrap_python", "") or "").strip()
                if candidate:
                    path = Path(candidate)
                    if not path.is_absolute():
                        path = (self.repo_path / candidate).resolve()
                    python_executable = str(path)
            except Exception:
                python_executable = ""
        if not python_executable:
            return {}
        resolved = command_env_for_python(python_executable)
        overrides: dict[str, str] = {}
        for key in ("PATH", "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_EXE"):
            value = str(resolved.get(key, "")).strip()
            if value:
                overrides[key] = value
        return overrides

    def _active_detached_runtime_refs(self) -> tuple[set[str], set[str], set[str]]:
        runtime_dir = self.research_dir / "runtime"
        idea_ids: set[str] = set()
        execution_ids: set[str] = set()
        frontier_ids: set[str] = set()
        if not runtime_dir.exists():
            return idea_ids, execution_ids, frontier_ids
        for path in runtime_dir.glob("*.json"):
            name = path.name
            if name.endswith("__saturation_context.json") or name.endswith("__saturation_selection.json"):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            if not self._detached_process_alive(payload):
                continue
            idea_id = str(payload.get("idea_id", "")).strip()
            execution_id = str(payload.get("execution_id", "")).strip()
            frontier_id = str(payload.get("frontier_id", "")).strip()
            if idea_id:
                idea_ids.add(idea_id)
            if execution_id:
                execution_ids.add(execution_id)
            if frontier_id:
                frontier_ids.add(frontier_id)
        return idea_ids, execution_ids, frontier_ids

    @staticmethod
    def _reservation_matches_runtime(
        reservation: dict, *, idea_ids: set[str], execution_ids: set[str], frontier_ids: set[str]
    ) -> bool:
        idea_id = str(reservation.get("idea_id", "")).strip()
        execution_id = str(reservation.get("execution_id", "")).strip()
        frontier_id = str(reservation.get("frontier_id", "")).strip()
        return bool(
            (idea_id and idea_id in idea_ids)
            or (execution_id and execution_id in execution_ids)
            or (frontier_id and frontier_id in frontier_ids)
        )

    @staticmethod
    def _is_reconcilable_experiment_reservation(reservation: dict) -> bool:
        kind = str(reservation.get("kind", "")).strip()
        tag = str(reservation.get("tag", "")).strip()
        if kind == "experiment":
            return True
        return bool(tag.startswith("worker-") and kind in {"", "legacy"})

    def _reconcile_parallel_runtime_state(self) -> None:
        allocator = self._plugins.gpu_allocator
        active_idea_ids, active_execution_ids, active_frontier_ids = self._active_detached_runtime_refs()
        restored_pending = 0
        finalized_done = 0
        for idea in self.idea_pool.all_ideas():
            if str(idea.get("status", "")).strip() != "running":
                continue
            idea_id = str(idea.get("id", "")).strip()
            execution_id = str(idea.get("execution_id", "")).strip()
            frontier_id = str(idea.get("frontier_id", "")).strip()
            if (
                (idea_id and idea_id in active_idea_ids)
                or (execution_id and execution_id in active_execution_ids)
                or (frontier_id and frontier_id in active_frontier_ids)
            ):
                continue
            matched_row = self._find_matching_result_row(
                self.repo_path,
                results_before_count=0,
                idea=idea,
            )
            if matched_row is not None:
                metric_value, verdict = self._result_payload_from_row(matched_row)
                if self.idea_pool.mark_done(idea_id, metric_value=metric_value, verdict=verdict):
                    finalized_done += 1
                    self.on_output(
                        f"[system] Reconciled stale running idea {idea_id} to done from existing recorded result"
                    )
                    continue
            if self.idea_pool.update_status(idea_id, "pending"):
                restored_pending += 1
                self.on_output(f"[system] Requeued stale running idea {idea_id} back to pending")

        released = 0
        if allocator is not None:
            try:
                status = allocator.manager.refresh()
            except Exception:
                status = []
            stale_reservations: list[dict] = []
            for gpu in status if isinstance(status, list) else []:
                for reservation in gpu.get("reservations", []):
                    if not isinstance(reservation, dict):
                        continue
                    if not self._is_reconcilable_experiment_reservation(reservation):
                        continue
                    if self._reservation_matches_runtime(
                        reservation,
                        idea_ids=active_idea_ids,
                        execution_ids=active_execution_ids,
                        frontier_ids=active_frontier_ids,
                    ):
                        continue
                    stale_reservations.append(
                        {
                            "host": str(gpu.get("host", "local")).strip() or "local",
                            "device": int(gpu.get("device", 0) or 0),
                            **reservation,
                        }
                    )
            if stale_reservations:
                allocator.manager.release_reservations(stale_reservations)
                allocator.manager.refresh()
                released = len(stale_reservations)
                self.on_output(
                    f"[system] Released {released} stale GPU reservation(s) from previous interrupted runs"
                )

        if restored_pending or finalized_done or released:
            self._activity.clear_workers("experiment_agent", status="idle", detail="0 active worker(s)", idea="")
            self._activity.update(
                "experiment_agent",
                status="idle",
                detail=(
                    "reconciled stale runtime state "
                    f"(pending={restored_pending}, done={finalized_done}, released_gpu={released})"
                ),
                idea="",
            )

    def _claim_next_runnable_idea(self, worker_name: str, slot_hint: dict | None):
        allocator = self._plugins.gpu_allocator
        if allocator is None:
            idea = self.idea_pool.claim_idea(worker_name)
            return idea, None, None

        pending = self.idea_pool.pending_ideas(
            default_gpu_mem_mb=allocator.default_memory_per_worker_mb,
            backfill_threshold_minutes=self._backfill_threshold_minutes,
        )
        if not pending:
            return None, None, None

        preferred_id = allocator.select_claimable_idea(pending)
        if preferred_id:
            pending = sorted(
                pending,
                key=lambda item: 0 if str(item.get("id", "")).strip() == preferred_id else 1,
            )

        blocked = False
        for candidate in pending:
            claimed = self.idea_pool.claim_specific_idea(str(candidate.get("id", "")).strip(), worker_name)
            if claimed is None:
                continue
            allocation = allocator.allocate_for_idea(worker_name, claimed, preferred=slot_hint)
            if allocation is not None:
                return claimed, allocation, None
            blocked = True
            claim_token = str(claimed.get("claim_token", "")).strip()
            self.idea_pool.update_status(claimed["id"], "pending", claim_token=claim_token or None)
        if blocked:
            summary = self.idea_pool.summary()
            if int(summary.get("running", 0) or 0) <= 0:
                return None, None, "resource_deadlock"
            return None, None, "waiting_resources"
        return None, None, None

    @staticmethod
    def _resource_observation(
        idea: dict,
        allocation,
        *,
        duration_seconds: float | None,
        gpu_telemetry: GPURunTelemetry | None = None,
        saturation_selection: dict | None = None,
    ) -> dict:
        observation: dict = {}
        if duration_seconds is not None:
            observation["duration_minutes"] = max(duration_seconds, 0.0) / 60.0
        if allocation is not None:
            reservations = allocation.reservations if getattr(allocation, "reservations", None) else []
            if reservations:
                observation["devices"] = [
                    {"host": str(item.get("host", "")).strip(), "device": int(item.get("device", 0))}
                    for item in reservations
                ]
                observation["gpu_count_allocated"] = len(reservations)
                observation["gpu_mem_reserved_mb"] = sum(int(item.get("memory_mb", 0) or 0) for item in reservations)
            if getattr(allocation, "resource_request", None):
                observation["resource_request"] = allocation.resource_request
            if getattr(allocation, "selected_profile", None):
                selected_profile = getattr(allocation, "selected_profile", {}) or {}
                profile_name = str(selected_profile.get("name", "")).strip()
                if profile_name:
                    observation["selected_resource_profile"] = profile_name
                expected_memory_mb = int(selected_profile.get("expected_memory_mb", 0) or 0)
                if expected_memory_mb > 0:
                    observation["expected_peak_gpu_mem_mb"] = expected_memory_mb
            if getattr(allocation, "saturation_context", None):
                saturation_context = getattr(allocation, "saturation_context", {}) or {}
                budget_mb = int(saturation_context.get("gpu_budget_mb", 0) or 0)
                headroom_mb = int(saturation_context.get("headroom_mb", 0) or 0)
                if budget_mb > 0:
                    observation["gpu_budget_mb"] = budget_mb
                if headroom_mb > 0:
                    observation["gpu_headroom_mb"] = headroom_mb
                if saturation_context:
                    observation["single_gpu_saturation"] = True
        if idea.get("execution_shape"):
            observation["execution_shape"] = idea.get("execution_shape")
        if idea.get("workload_label"):
            observation["workload_label"] = str(idea.get("workload_label", "")).strip()
        if idea.get("resource_profile"):
            observation["resource_profile"] = str(idea.get("resource_profile", "")).strip()
        if getattr(allocation, "execution_shape", None):
            observation["execution_shape"] = getattr(allocation, "execution_shape")
        if isinstance(saturation_selection, dict) and saturation_selection:
            qualification_attempts = int(saturation_selection.get("qualification_attempts", 0) or 0)
            if qualification_attempts > 0:
                observation["qualification_attempts"] = qualification_attempts
            selected_profile = str(
                saturation_selection.get("selected_profile", "")
                or saturation_selection.get("selected_resource_profile", "")
            ).strip()
            if selected_profile:
                observation["selected_resource_profile"] = selected_profile
            expected_peak = int(saturation_selection.get("expected_peak_gpu_mem_mb", 0) or 0)
            if expected_peak > 0:
                observation["expected_peak_gpu_mem_mb"] = expected_peak
        if gpu_telemetry is not None and gpu_telemetry.peak_task_memory_mb is not None:
            observation["observed_peak_gpu_mem_mb"] = max(int(gpu_telemetry.peak_task_memory_mb or 0), 0)
        if observation.get("single_gpu_saturation"):
            observation["saturation_status"] = classify_single_gpu_saturation_status(
                gpu_budget_mb=int(observation.get("gpu_budget_mb", 0) or 0),
                observed_peak_gpu_mem_mb=(
                    int(observation.get("observed_peak_gpu_mem_mb", 0) or 0)
                    if "observed_peak_gpu_mem_mb" in observation
                    else None
                ),
                expected_peak_gpu_mem_mb=(
                    int(observation.get("expected_peak_gpu_mem_mb", 0) or 0)
                    if "expected_peak_gpu_mem_mb" in observation
                    else None
                ),
            )
        return observation

    def _resource_secondary_metrics_patch(
        self,
        idea: dict,
        allocation,
        *,
        gpu_telemetry: GPURunTelemetry | None,
        saturation_selection: dict | None,
    ) -> dict:
        observation = self._resource_observation(
            idea,
            allocation,
            duration_seconds=None,
            gpu_telemetry=gpu_telemetry,
            saturation_selection=saturation_selection,
        )
        return {"_open_researcher_resources": observation} if observation else {}

    def _worker_loop(self, worker_id: int, gpu: dict | None) -> None:
        wid = f"worker-{worker_id}"
        allocation = None
        try:
            while not self._should_stop():
                if not self._wait_until_unpaused():
                    break
                if not self._reserve_claim_slot():
                    self.on_output(f"[{wid}] Claim budget exhausted, stopping")
                    break
                idea, allocation, resource_state = self._claim_next_runnable_idea(wid, gpu)
                if not idea:
                    self._release_claim_slot()
                    if resource_state == "waiting_resources":
                        self._activity.update_worker(
                            "experiment_agent",
                            wid,
                            status="waiting_resources",
                            idea="",
                        )
                        self.on_output(f"[{wid}] No runnable ideas fit current resources, waiting")
                        time.sleep(0.5)
                        continue
                    if resource_state == "resource_deadlock":
                        self._activity.update_worker(
                            "experiment_agent",
                            wid,
                            status="idle",
                            idea="",
                        )
                        self._record_resource_deadlock()
                        # Retry with random backoff before giving up
                        retried = False
                        for _attempt in range(3):
                            backoff = random.uniform(5, 30)
                            self.on_output(f"[{wid}] Resource deadlock, retrying in {backoff:.0f}s...")
                            time.sleep(backoff)
                            if self._should_stop():
                                break
                            idea, allocation, resource_state = self._claim_next_runnable_idea(wid, gpu)
                            if idea or resource_state != "resource_deadlock":
                                retried = True
                                break
                        if not retried:
                            self.on_output(f"[{wid}] Resource deadlock persists after 3 retries, stopping")
                            self.stop()
                            break
                        if not idea:
                            continue
                        # Fall through to experiment execution with the newly claimed idea
                    else:
                        self.on_output(f"[{wid}] No more pending ideas, stopping")
                        break

                idea_description = str(idea.get("description", ""))
                claim_token = str(idea.get("claim_token", "")).strip()
                memory_context = None
                workspace = None
                workdir = self.repo_path
                workspace_snapshot = None
                run_code = 1
                notify_finished = True
                stop_after_finalize = False
                run_started_at = None
                gpu_telemetry = GPURunTelemetry()
                stop_gpu_telemetry: Callable[[], None] | None = None
                saturation_selection: dict = {}
                _token_metrics = None
                try:
                    if not self._wait_until_unpaused():
                        applied = self.idea_pool.update_status(idea["id"], "pending", claim_token=claim_token or None)
                        if not applied:
                            self.on_output(f"[{wid}] Stop requested while pausing; claim release skipped")
                        notify_finished = False
                        break

                    ctrl = read_control(self.research_dir / "control.json")
                    if ctrl.get("skip_current"):
                        applied = self.idea_pool.update_status(idea["id"], "skipped", claim_token=claim_token or None)
                        if applied:
                            consume_skip_current(self.research_dir / "control.json", source=f"{wid}:runtime")
                            self.on_output(f"[{wid}] Consumed skip_current for {idea['id']}")
                        else:
                            self.on_output(f"[{wid}] Claim race on skip for {idea['id']}; flag preserved")
                        run_code = 0
                        continue

                    try:
                        memory_context = (
                            self._plugins.failure_memory.prepare(idea_description, wid)
                            if self._plugins.failure_memory is not None
                            else None
                        )
                    except Exception as exc:
                        logger.info("Failure memory prepare failed: %s", exc)
                        memory_context = None
                    failure_class = memory_context.failure_class if memory_context is not None else "general_failure"
                    ranked_fix_actions = memory_context.ranked_fix_actions if memory_context is not None else []
                    first_fix_action = (
                        memory_context.first_fix_action if memory_context is not None else "generate_new_plan"
                    )
                    for line in memory_context.log_lines if memory_context is not None else []:
                        self.on_output(line)

                    self._activity.update_worker(
                        "experiment_agent",
                        wid,
                        status="running",
                        idea=idea_description[:50],
                        failure_class=failure_class,
                        memory_policy="rank_historical_success" if memory_context is not None else "disabled",
                        ranked_fixes=ranked_fix_actions[:3],
                        first_fix_action=first_fix_action,
                        gpu_reservations=(allocation.reservations if allocation is not None else []),
                        workload_label=str(idea.get("workload_label", "")).strip(),
                        resource_profile=str(
                            getattr(allocation, "selected_profile", {}).get("name", "")
                            if allocation is not None
                            else idea.get("resource_profile", "")
                        ).strip()
                        or str(idea.get("resource_profile", "")).strip(),
                        saturation_mode=bool(
                            getattr(allocation, "saturation_context", {}) if allocation is not None else {}
                        ),
                        gpu_budget_mb=(
                            int(getattr(allocation, "saturation_context", {}).get("gpu_budget_mb", 0) or 0)
                            if allocation is not None
                            else 0
                        ),
                    )
                    logger.debug(
                        "Activity state updated: worker=%s expected_status=running idea=%s",
                        wid, idea_description[:50],
                    )
                    self.on_output(f"[{wid}] Running: {idea_description[:60]}")
                    gpu_env = allocation.env if allocation is not None else {}
                    for line in allocation.log_lines if allocation is not None else []:
                        self.on_output(line)
                    if gpu_env:
                        self.on_output(f"[{wid}] Using GPU env: {gpu_env}")

                    workspace = (
                        self._plugins.workspace_isolation.acquire(wid, str(idea["id"]))
                        if self._plugins.workspace_isolation is not None
                        else None
                    )
                    workdir = workspace.workdir if workspace is not None else self.repo_path
                    for line in workspace.log_lines if workspace is not None else []:
                        self.on_output(line)
                    workspace_snapshot = capture_clean_workspace_snapshot(workdir)
                    saturation_context_path = (
                        self._write_saturation_context(idea, allocation) if allocation is not None else ""
                    )
                    gpu_telemetry, stop_gpu_telemetry = self._start_gpu_telemetry_monitor(allocation)

                    if self._on_experiment_started is not None:
                        try:
                            self._on_experiment_started(dict(idea))
                        except Exception:
                            logger.debug("Experiment start callback failed", exc_info=True)

                    agent = self.agent_factory()
                    _results_lock = FileLock(str(workdir / ".research" / "results.tsv.lock"), timeout=10)
                    with _results_lock:
                        results_before_count = len(load_results(workdir))
                    timed_out = False

                    def _on_timeout() -> None:
                        nonlocal timed_out
                        timed_out = True
                        self.on_output(f"[{wid}] Experiment timeout after {self._timeout_seconds}s; terminating agent")
                        try:
                            agent.terminate()
                        except Exception:
                            logger.debug("Agent terminate failed after timeout", exc_info=True)

                    watchdog = TimeoutWatchdog(
                        self._timeout_seconds,
                        on_timeout=_on_timeout,
                    )
                    run_env = {
                        **self._runtime_shell_env,
                        **gpu_env,
                        "OPEN_RESEARCHER_MEMORY_POLICY": (
                            "rank_historical_success" if memory_context is not None else "disabled"
                        ),
                        "OPEN_RESEARCHER_FAILURE_CLASS": failure_class,
                        "OPEN_RESEARCHER_RANKED_FIXES": ",".join(ranked_fix_actions[:3]),
                        "OPEN_RESEARCHER_FIRST_FIX_ACTION": first_fix_action,
                        "OPEN_RESEARCHER_PROTOCOL": "research-v1",
                        "OPEN_RESEARCHER_FRONTIER_ID": str(idea.get("frontier_id", "")).strip(),
                        "OPEN_RESEARCHER_IDEA_ID": str(idea.get("id", "")).strip(),
                        "OPEN_RESEARCHER_EXECUTION_ID": str(idea.get("execution_id", "")).strip(),
                        "OPEN_RESEARCHER_HYPOTHESIS_ID": str(idea.get("hypothesis_id", "")).strip(),
                        "OPEN_RESEARCHER_EXPERIMENT_SPEC_ID": str(idea.get("experiment_spec_id", "")).strip(),
                        "OPEN_RESEARCHER_RESOURCE_PROFILE": str(
                            getattr(allocation, "selected_profile", {}).get("name", "")
                            if allocation is not None
                            else idea.get("resource_profile", "")
                        ).strip()
                        or str(idea.get("resource_profile", "")).strip(),
                        "OPEN_RESEARCHER_WORKLOAD_LABEL": str(idea.get("workload_label", "")).strip(),
                        "OPEN_RESEARCHER_SATURATION_CONTEXT_PATH": saturation_context_path,
                    }
                    run_env = {key: value for key, value in run_env.items() if value}
                    watchdog.reset()
                    run_started_at = time.monotonic()
                    try:
                        code = agent.run(
                            workdir,
                            on_output=self.on_output,
                            program_file=resolve_role_program_file(self.research_dir, "experiment"),
                            env=run_env,
                        )
                    finally:
                        watchdog.stop()
                        if stop_gpu_telemetry is not None:
                            stop_gpu_telemetry()
                    run_code = int(code)
                    _token_metrics = getattr(agent, "last_token_metrics", None)
                    saturation_selection = self._load_saturation_selection(idea)
                    strict_result_tracking = str(idea.get("protocol", "")).strip() == "research-v1"
                    current_state = self._current_idea_state(str(idea.get("id", "")))
                    matched_row = None
                    result_status = ""
                    should_requeue = False
                    if code == 0:
                        if strict_result_tracking:
                            matched_row = self._find_matching_result_row(
                                workdir,
                                results_before_count=results_before_count,
                                idea=idea,
                            )
                            result_status = self._result_status_from_row(matched_row)
                            if matched_row is not None:
                                augment_result_secondary_metrics(
                                    workdir,
                                    row=matched_row,
                                    patch=self._resource_secondary_metrics_patch(
                                        idea,
                                        allocation,
                                        gpu_telemetry=gpu_telemetry,
                                        saturation_selection=saturation_selection,
                                    ),
                                )
                                metric_value, verdict = self._result_payload_from_row(matched_row)
                                if not self._terminal_result_present(current_state):
                                    applied = self.idea_pool.mark_done(
                                        idea["id"],
                                        metric_value=metric_value,
                                        verdict=verdict,
                                        claim_token=claim_token or None,
                                        resource_observation=self._resource_observation(
                                            idea,
                                            allocation,
                                            duration_seconds=(
                                                time.monotonic() - run_started_at
                                                if run_started_at is not None
                                                else None
                                            ),
                                            gpu_telemetry=gpu_telemetry,
                                            saturation_selection=saturation_selection,
                                        ),
                                    )
                                    if not applied:
                                        self.on_output(
                                            f"[{wid}] Claim race detected for {idea['id']}; "
                                            "winner already finalized, cleanup applied"
                                        )
                            elif self._terminal_result_present(current_state):
                                pass
                            else:
                                detached_outcome = self._monitor_detached_run(
                                    wid=wid,
                                    idea=idea,
                                    workdir=workdir,
                                    results_before_count=results_before_count,
                                    claim_token=claim_token,
                                    run_started_at=run_started_at,
                                )
                                matched_row = detached_outcome.matched_row
                                result_status = detached_outcome.result_status
                                if matched_row is not None:
                                    augment_result_secondary_metrics(
                                        workdir,
                                        row=matched_row,
                                        patch=self._resource_secondary_metrics_patch(
                                            idea,
                                            allocation,
                                            gpu_telemetry=gpu_telemetry,
                                            saturation_selection=saturation_selection,
                                        ),
                                    )
                                    metric_value, verdict = self._result_payload_from_row(matched_row)
                                    current_state = self._current_idea_state(str(idea.get("id", "")))
                                    if not self._terminal_result_present(current_state):
                                        applied = self.idea_pool.mark_done(
                                            idea["id"],
                                            metric_value=metric_value,
                                            verdict=verdict,
                                            claim_token=claim_token or None,
                                            resource_observation=self._resource_observation(
                                                idea,
                                                allocation,
                                                duration_seconds=(
                                                    time.monotonic() - run_started_at
                                                    if run_started_at is not None
                                                    else None
                                                ),
                                                gpu_telemetry=gpu_telemetry,
                                                saturation_selection=saturation_selection,
                                            ),
                                        )
                                        if not applied:
                                            self.on_output(
                                                f"[{wid}] Claim race detected for {idea['id']}; "
                                                "winner already finalized after detached monitor"
                                            )
                                    run_code = detached_outcome.run_code
                                else:
                                    should_requeue = detached_outcome.should_requeue
                                    if should_requeue:
                                        reapplied = self._return_idea_to_pending(
                                            idea["id"],
                                            claim_token=claim_token,
                                        )
                                        if reapplied:
                                            self.on_output(
                                                f"[{wid}] No recorded result for {idea['id']} despite zero exit; "
                                                "released claim back to pending"
                                            )
                                        else:
                                            self.on_output(
                                                f"[{wid}] Claim race detected for {idea['id']}; "
                                                "pending release suppressed, cleanup applied"
                                            )
                                    if timed_out:
                                        run_code = 124
                                    else:
                                        run_code = detached_outcome.run_code
                                    stop_after_finalize = detached_outcome.stop_after_finalize
                        else:
                            applied = self.idea_pool.mark_done(
                                idea["id"],
                                metric_value=None,
                                verdict="completed",
                                claim_token=claim_token or None,
                                resource_observation=self._resource_observation(
                                    idea,
                                    allocation,
                                    duration_seconds=(
                                        time.monotonic() - run_started_at if run_started_at is not None else None
                                    ),
                                    gpu_telemetry=gpu_telemetry,
                                    saturation_selection=saturation_selection,
                                ),
                            )
                            if not applied:
                                self.on_output(
                                    f"[{wid}] Claim race detected for {idea['id']}; "
                                    "winner already finalized, cleanup applied"
                                )
                    else:
                        if not self._terminal_result_present(current_state):
                            applied = self.idea_pool.mark_done_with_context(
                                idea["id"],
                                metric_value=None,
                                verdict="crash",
                                claim_token=claim_token or None,
                                resource_observation=self._resource_observation(
                                    idea,
                                    allocation,
                                    duration_seconds=(
                                        time.monotonic() - run_started_at if run_started_at is not None else None
                                    ),
                                    gpu_telemetry=gpu_telemetry,
                                    saturation_selection=saturation_selection,
                                ),
                            )
                            if not applied:
                                self.on_output(
                                    f"[{wid}] Claim race detected for {idea['id']}; "
                                    "crash write suppressed, cleanup applied"
                                )
                    if (
                        workspace_snapshot is not None
                        and (run_code != 0 or self._status_requires_rollback(result_status))
                    ):
                        rollback_workspace(workdir, workspace_snapshot)
                    if workspace_snapshot is not None and should_requeue:
                        rollback_workspace(workdir, workspace_snapshot)
                    if (
                        workspace_snapshot is not None
                        and run_code == 0
                        and not should_requeue
                        and not self._status_requires_rollback(result_status)
                    ):
                        ensure_clean_workspace(workdir, context="after successful experiment")
                except (GitWorkspaceError, WorkspaceIsolationError) as exc:
                    self.on_output(f"[{wid}] Fatal runtime safety error: {exc}")
                    reapplied = self._return_idea_to_pending(idea["id"], claim_token=claim_token)
                    if not reapplied:
                        self.on_output(
                            f"[{wid}] Claim race detected for {idea['id']}; "
                            "pending release suppressed after safety error"
                        )
                    run_code = 1
                    self._record_fatal_error()
                    self.stop()
                except Exception as exc:
                    self.on_output(f"[{wid}] Error: {exc}")
                    applied = self.idea_pool.update_status(
                        idea["id"],
                        "skipped",
                        claim_token=claim_token or None,
                        resource_observation=self._resource_observation(
                            idea,
                            allocation,
                            duration_seconds=(
                                time.monotonic() - run_started_at if run_started_at is not None else None
                            ),
                            gpu_telemetry=gpu_telemetry,
                            saturation_selection=saturation_selection,
                        ),
                    )
                    if not applied:
                        self.on_output(
                            f"[{wid}] Claim race detected for {idea['id']}; error skip suppressed, cleanup applied"
                        )
                    run_code = 1
                finally:
                    latest_idea = dict(idea)
                    try:
                        if stop_gpu_telemetry is not None:
                            stop_gpu_telemetry()
                            stop_gpu_telemetry = None
                        if self._plugins.failure_memory is not None and memory_context is not None:
                            self._plugins.failure_memory.record(memory_context, run_code)
                    except Exception as exc:
                        logger.info("Failure memory record failed: %s", exc)
                    if workspace is not None:
                        try:
                            workspace.cleanup()
                        except WorkspaceIsolationError as exc:
                            self._record_fatal_error()
                            self.on_output(str(exc))
                            self.stop()
                        if workdir != self.repo_path:
                            self.on_output(f"[{wid}] Worktree cleaned up")
                    try:
                        latest_idea = next(
                            (item for item in self.idea_pool.all_ideas() if item.get("id") == idea.get("id")),
                            dict(idea),
                        )
                        latest_idea["exit_code"] = run_code
                        latest_idea["worker_id"] = wid
                        if stop_after_finalize:
                            latest_idea["retry_requested"] = True
                        if _token_metrics is not None:
                            latest_idea["_token_metrics"] = {
                                "tokens_input": _token_metrics.tokens_input,
                                "tokens_output": _token_metrics.tokens_output,
                            }
                    finally:
                        try:
                            if self._plugins.gpu_allocator is not None and allocation is not None:
                                try:
                                    self._plugins.gpu_allocator.release(allocation)
                                except Exception:
                                    logger.error("GPU release failed for allocation %s", allocation, exc_info=True)
                        finally:
                            self._release_claim_slot()
                    if notify_finished and self._on_experiment_finished is not None:
                        try:
                            should_stop = bool(self._on_experiment_finished(latest_idea))
                        except Exception:
                            logger.debug("Experiment finished callback failed", exc_info=True)
                            should_stop = False
                        if should_stop:
                            self.stop()
                    if stop_after_finalize:
                        self.stop()
        except Exception as exc:
            self._record_fatal_error()
            self.on_output(f"[{wid}] Fatal worker error: {exc}")
            logger.debug("Fatal worker loop error", exc_info=True)
            # Best-effort GPU release for the current allocation before stopping.
            try:
                if self._plugins.gpu_allocator is not None and allocation is not None:
                    self._plugins.gpu_allocator.release(allocation)
                    self.on_output(f"[{wid}] Released GPU after fatal error")
            except Exception:
                logger.debug("GPU release in fatal error handler failed", exc_info=True)
            finally:
                self._release_claim_slot()
            self.stop()
        finally:
            self._activity.remove_worker("experiment_agent", wid)
