"""Parallel worker manager -- run experiments across multiple GPUs."""

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from paperfarm.activity import ActivityMonitor
from paperfarm.control_plane import consume_skip_current, read_control
from paperfarm.git_safety import (
    GitWorkspaceError,
    capture_clean_workspace_snapshot,
    ensure_clean_workspace,
    rollback_workspace,
)
from paperfarm.gpu_manager import GPUManager
from paperfarm.idea_pool import IdeaPool
from paperfarm.results_cmd import load_results
from paperfarm.watchdog import TimeoutWatchdog
from paperfarm.worker_plugins import (
    WorkerRuntimePlugins,
    WorkspaceIsolationError,
    build_default_worker_plugins,
)

logger = logging.getLogger(__name__)


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

    def start(self) -> None:
        """Start worker threads based on available GPUs."""
        self._stop.clear()
        self._workers.clear()
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

    def join(self, timeout: float | None = None) -> None:
        """Wait for all worker threads to finish."""
        for t in self._workers:
            t.join(timeout=timeout)

    @property
    def fatal_errors(self) -> int:
        with self._fatal_lock:
            return self._fatal_errors

    def _record_fatal_error(self) -> None:
        with self._fatal_lock:
            self._fatal_errors += 1

    def _wait_until_unpaused(self) -> bool:
        while not self._should_stop():
            ctrl = read_control(self.research_dir / "control.json")
            if not bool(ctrl.get("paused", False)):
                return True
            time.sleep(0.2)
        return False

    def _claim_next_runnable_idea(self, worker_name: str, slot_hint: dict | None):
        allocator = self._plugins.gpu_allocator
        if allocator is None:
            idea = self.idea_pool.claim_idea(worker_name)
            return idea, None, False

        pending = self.idea_pool.pending_ideas(
            default_gpu_mem_mb=allocator.default_memory_per_worker_mb,
            backfill_threshold_minutes=self._backfill_threshold_minutes,
        )
        if not pending:
            return None, None, False

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
                return claimed, allocation, False
            blocked = True
            claim_token = str(claimed.get("claim_token", "")).strip()
            self.idea_pool.update_status(claimed["id"], "pending", claim_token=claim_token or None)
        return None, None, blocked

    @staticmethod
    def _resource_observation(idea: dict, allocation, *, duration_seconds: float | None) -> dict:
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
        if idea.get("execution_shape"):
            observation["execution_shape"] = idea.get("execution_shape")
        if idea.get("workload_label"):
            observation["workload_label"] = str(idea.get("workload_label", "")).strip()
        if idea.get("resource_profile"):
            observation["resource_profile"] = str(idea.get("resource_profile", "")).strip()
        return observation

    def _worker_loop(self, worker_id: int, gpu: dict | None) -> None:
        wid = f"worker-{worker_id}"
        try:
            while not self._should_stop():
                if not self._wait_until_unpaused():
                    break
                if not self._reserve_claim_slot():
                    self.on_output(f"[{wid}] Claim budget exhausted, stopping")
                    break
                idea, allocation, resource_blocked = self._claim_next_runnable_idea(wid, gpu)
                if not idea:
                    self._release_claim_slot()
                    if resource_blocked:
                        self._activity.update_worker(
                            "experiment_agent",
                            wid,
                            status="waiting_resources",
                            idea="",
                        )
                        self.on_output(f"[{wid}] No runnable ideas fit current resources, waiting")
                        time.sleep(0.5)
                        continue
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
                try:
                    if not self._wait_until_unpaused():
                        applied = self.idea_pool.update_status(idea["id"], "pending", claim_token=claim_token or None)
                        if not applied:
                            self.on_output(f"[{wid}] Stop requested while pausing; claim release skipped")
                        notify_finished = False
                        break

                    if consume_skip_current(self.research_dir / "control.json", source=f"{wid}:runtime"):
                        self.on_output(f"[{wid}] Consumed skip_current for {idea['id']}")
                        applied = self.idea_pool.update_status(idea["id"], "skipped", claim_token=claim_token or None)
                        if not applied:
                            self.on_output(
                                f"[{wid}] Claim race detected for {idea['id']}; skip write suppressed, cleanup applied"
                            )
                        run_code = 0
                        continue

                    memory_context = (
                        self._plugins.failure_memory.prepare(idea_description, wid)
                        if self._plugins.failure_memory is not None
                        else None
                    )
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
                        resource_profile=str(idea.get("resource_profile", "")).strip(),
                    )
                    self.on_output(f"[{wid}] Running: {idea_description[:60]}")
                    gpu_env = allocation.env if allocation is not None else {}
                    for line in allocation.log_lines if allocation is not None else []:
                        self.on_output(line)
                    if gpu_env:
                        self.on_output(f"[{wid}] Using GPU env: {gpu_env}")

                    _token_metrics = None
                    workspace = (
                        self._plugins.workspace_isolation.acquire(wid, str(idea["id"]))
                        if self._plugins.workspace_isolation is not None
                        else None
                    )
                    workdir = workspace.workdir if workspace is not None else self.repo_path
                    for line in workspace.log_lines if workspace is not None else []:
                        self.on_output(line)
                    workspace_snapshot = capture_clean_workspace_snapshot(workdir)

                    if self._on_experiment_started is not None:
                        try:
                            self._on_experiment_started(dict(idea))
                        except Exception:
                            logger.debug("Experiment start callback failed", exc_info=True)

                    agent = self.agent_factory()
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
                        "OPEN_RESEARCHER_RESOURCE_PROFILE": str(idea.get("resource_profile", "")).strip(),
                        "OPEN_RESEARCHER_WORKLOAD_LABEL": str(idea.get("workload_label", "")).strip(),
                    }
                    run_env = {key: value for key, value in run_env.items() if value}
                    watchdog.reset()
                    run_started_at = time.monotonic()
                    try:
                        code = agent.run(
                            workdir,
                            on_output=self.on_output,
                            program_file="experiment_program.md",
                            env=run_env,
                        )
                    finally:
                        watchdog.stop()
                    run_code = int(code)
                    _token_metrics = getattr(agent, "last_token_metrics", None)
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
                                                time.monotonic() - run_started_at if run_started_at is not None else None
                                            ),
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
                                should_requeue = True
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
                                    run_code = 1
                                stop_after_finalize = True
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
                                ),
                            )
                            if not applied:
                                self.on_output(
                                    f"[{wid}] Claim race detected for {idea['id']}; "
                                    "winner already finalized, cleanup applied"
                                )
                    else:
                        if not self._terminal_result_present(current_state):
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
                                ),
                            )
                            if not applied:
                                self.on_output(
                                    f"[{wid}] Claim race detected for {idea['id']}; "
                                    "skip write suppressed, cleanup applied"
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
                            duration_seconds=(time.monotonic() - run_started_at if run_started_at is not None else None),
                        ),
                    )
                    if not applied:
                        self.on_output(
                            f"[{wid}] Claim race detected for {idea['id']}; error skip suppressed, cleanup applied"
                        )
                    run_code = 1
                finally:
                    try:
                        if self._plugins.failure_memory is not None and memory_context is not None:
                            self._plugins.failure_memory.record(memory_context, run_code)
                    except Exception as exc:
                        logger.debug("Failure memory record failed: %s", exc)
                    if workspace is not None:
                        try:
                            workspace.cleanup()
                        except WorkspaceIsolationError as exc:
                            self._record_fatal_error()
                            self.on_output(str(exc))
                            self.stop()
                        if workdir != self.repo_path:
                            self.on_output(f"[{wid}] Worktree cleaned up")
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
                    if self._plugins.gpu_allocator is not None and allocation is not None:
                        self._plugins.gpu_allocator.release(allocation)
                    self._release_claim_slot()
        except Exception as exc:
            self._record_fatal_error()
            self.on_output(f"[{wid}] Fatal worker error: {exc}")
            logger.debug("Fatal worker loop error", exc_info=True)
            self.stop()
        finally:
            self._activity.update_worker("experiment_agent", wid, status="idle")
