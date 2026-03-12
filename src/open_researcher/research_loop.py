"""Core research loop shared by TUI and headless entrypoints."""

from __future__ import annotations

import csv
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock

from open_researcher.activity import ActivityMonitor
from open_researcher.config import ResearchConfig
from open_researcher.crash_counter import CrashCounter
from open_researcher.git_identity import ensure_local_git_identity
from open_researcher.git_safety import (
    GitWorkspaceError,
    capture_clean_workspace_snapshot,
    ensure_clean_workspace,
    rollback_workspace,
)
from open_researcher.graph_context import enforce_context_token_limit, filter_graph_for_context
from open_researcher.parallel_runtime import estimate_parallel_frontier_target
from open_researcher.phase_gate import PhaseGate
from open_researcher.research_events import (
    AgentOutput,
    AllIdeasProcessed,
    ClaimUpdated,
    CrashLimitReached,
    CriticReviewStarted,
    EventHandler,
    EvidenceRecorded,
    ExperimentCompleted,
    ExperimentPreflightFailed,
    ExperimentSpecCreated,
    ExperimentStarted,
    FrontierSynced,
    HypothesisProposed,
    LimitReached,
    ManagerCycleStarted,
    MemoryUpdated,
    NoPendingIdeas,
    PhaseTransition,
    ReproductionRequested,
    RoleFailed,
    ScoutCompleted,
    ScoutFailed,
    ScoutStarted,
    TokenBudgetExceeded,
    TokenBudgetWarning,
    TokenMetricsUpdated,
)
from open_researcher.research_graph import ResearchGraphStore
from open_researcher.research_memory import ResearchMemoryStore
from open_researcher.results_cmd import load_results, write_final_results_tsv
from open_researcher.role_programs import resolve_role_program_file
from open_researcher.storage import atomic_write_json, locked_read_json
from open_researcher.token_tracking import (
    BudgetCheckResult,
    TokenLedger,
    TokenMetrics,
    save_ledger,
)
from open_researcher.watchdog import TimeoutWatchdog


def read_latest_status(research_dir: Path) -> str:
    """Read the latest status from results.tsv (last non-header line)."""
    results_path = research_dir / "results.tsv"
    if not results_path.exists():
        return ""
    try:
        with results_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    except (OSError, UnicodeDecodeError):
        return ""
    if not rows:
        return ""
    return str(rows[-1].get("status", "")).strip()


def set_paused(research_dir: Path, reason: str) -> None:
    """Pause the current research session with a reason."""
    from open_researcher.control_plane import issue_control_command

    issue_control_command(
        research_dir / "control.json",
        command="pause",
        source="watchdog",
        reason=reason,
    )


def has_pending_ideas(research_dir: Path) -> bool:
    """Check whether the idea pool still contains pending ideas."""
    from open_researcher.idea_pool import IdeaBacklog

    pool = IdeaBacklog(research_dir / "idea_pool.json")
    return pool.summary().get("pending", 0) > 0


class ResearchLoop:
    """Run the core Scout -> Manager/Critic/Experiment loop and emit typed events."""

    def __init__(
        self,
        repo_path: Path,
        research_dir: Path,
        cfg: ResearchConfig,
        emit: EventHandler,
        *,
        has_pending_ideas_fn=has_pending_ideas,
        read_latest_status_fn=read_latest_status,
        pause_fn=set_paused,
    ):
        self.repo_path = repo_path
        self.research_dir = research_dir
        self.cfg = cfg
        self.emit = emit
        self._has_pending_ideas = has_pending_ideas_fn
        self._read_latest_status = read_latest_status_fn
        self._pause = pause_fn
        self.last_failed_role: str | None = None
        self.last_stop_reason: str | None = None
        self.last_finished_all = False
        self.last_exit_codes: dict[str, int] = {}
        self.last_experiments_completed = 0
        self.had_experiment_failure = False
        self.last_experiment_failure_code: int | None = None
        self.token_ledger = TokenLedger()

    def _effective_max_experiments(self, override: int | None = None) -> int:
        if override is not None and override > 0:
            return override
        return self.cfg.max_experiments

    def _make_output_callback(self, phase: str):
        def on_output(line: str) -> None:
            self.emit(AgentOutput(phase=phase, detail=line))

        return on_output

    def _check_token_budget(self) -> BudgetCheckResult | None:
        """Check token budget and return action with reason, or None if within budget."""
        if self.cfg.token_budget <= 0:
            return None
        ratio = self.token_ledger.cumulative.tokens_total / self.cfg.token_budget
        if ratio >= 1.0:
            return BudgetCheckResult(action=self.cfg.budget_policy, reason="exceeded", ratio=ratio)
        if ratio >= self.cfg.budget_warning_threshold:
            return BudgetCheckResult(action="warn", reason="threshold", ratio=ratio)
        return None

    def _accumulate_token_metrics(
        self,
        agent,
        phase: str,
        experiment_num: int | None = None,
    ) -> None:
        """Read agent's last_token_metrics and accumulate into ledger."""
        metrics = getattr(agent, "last_token_metrics", None)
        if not isinstance(metrics, TokenMetrics):
            return
        self.token_ledger.record(metrics, phase=phase, experiment_num=experiment_num)
        budget_remaining = None
        if self.cfg.token_budget > 0:
            budget_remaining = max(0, self.cfg.token_budget - self.token_ledger.cumulative.tokens_total)
        self.emit(TokenMetricsUpdated(
            phase=phase,
            experiment_num=experiment_num,
            tokens_input=metrics.tokens_input,
            tokens_output=metrics.tokens_output,
            tokens_total=metrics.tokens_total,
            budget_remaining=budget_remaining,
        ))
        save_ledger(self.token_ledger, self.research_dir / "token_ledger.json")

    def _apply_budget_check(self) -> str | None:
        """Check budget and apply policy. Returns 'stop' if loop should break, else None."""
        result = self._check_token_budget()
        if result is None:
            return None
        if result.reason == "threshold":
            self.emit(TokenBudgetWarning(
                tokens_used=self.token_ledger.cumulative.tokens_total,
                token_budget=self.cfg.token_budget,
                ratio=result.ratio,
            ))
            return None
        # reason == "exceeded"
        self.emit(TokenBudgetExceeded(
            tokens_used=self.token_ledger.cumulative.tokens_total,
            token_budget=self.cfg.token_budget,
            policy=result.action,
        ))
        if result.action == "stop":
            return "stop"
        if result.action == "pause":
            msg = f"Token budget exceeded ({self.token_ledger.cumulative.tokens_total:,} tokens)"
            self._pause(self.research_dir, msg)
        return None

    @contextmanager
    def _pruned_graph_context(self, graph_store):
        """Temporarily replace research_graph.json with a pruned version for agent consumption."""
        if self.cfg.context_token_limit <= 0:
            yield
            return
        graph_path = graph_store.path
        backup_path = graph_path.with_suffix(".json.bak")
        try:
            full_graph = graph_store.read()
            filtered = filter_graph_for_context(full_graph)
            filtered = enforce_context_token_limit(filtered, self.cfg.context_token_limit)
            import shutil
            shutil.copy2(graph_path, backup_path)
            atomic_write_json(graph_path, filtered)
            yield
        finally:
            if backup_path.exists():
                import shutil
                shutil.move(str(backup_path), str(graph_path))

    def _run_agent(
        self, agent, *, phase: str, program_file: str, error_tag: str, env: dict[str, str] | None = None
    ) -> int:
        try:
            return agent.run(
                self.repo_path,
                on_output=self._make_output_callback(phase),
                program_file=program_file,
                env=env,
            )
        except Exception as exc:
            self.emit(AgentOutput(phase=phase, detail=f"[{error_tag}] Agent error: {exc}"))
            return 1

    @staticmethod
    def _rows_by_id(rows: list[dict]) -> dict[str, dict]:
        indexed: dict[str, dict] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id", "")).strip()
            if row_id and row_id not in indexed:
                indexed[row_id] = row
        return indexed

    @classmethod
    def _new_rows_by_id(cls, before: dict, after: dict, key: str) -> list[dict]:
        before_ids = set(cls._rows_by_id(before.get(key, [])).keys())
        fresh: list[dict] = []
        for row in after.get(key, []):
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id", "")).strip()
            if row_id and row_id not in before_ids:
                fresh.append(row)
        return fresh

    @staticmethod
    def _frontier_trace(row: dict) -> dict:
        review_reason = str(row.get("review_reason_code", "")).strip()
        selection_reason = str(row.get("selection_reason_code", "")).strip()
        return {
            "frontier_id": str(row.get("id", "")).strip(),
            "idea_id": str(row.get("idea_id", "")).strip(),
            "execution_id": str(row.get("active_execution_id", "") or row.get("last_execution_id", "")).strip(),
            "hypothesis_id": str(row.get("hypothesis_id", "")).strip(),
            "experiment_spec_id": str(row.get("experiment_spec_id", "")).strip(),
            "claim_state": str(row.get("claim_state", "")).strip(),
            "selection_reason_code": selection_reason,
            "review_reason_code": review_reason,
            "reason_code": review_reason if review_reason and review_reason != "unspecified" else selection_reason,
            "repro_required": bool(row.get("repro_required", False)),
        }

    @classmethod
    def _claim_trace(cls, row: dict, frontier_rows: list[dict]) -> dict:
        trace = {
            "claim_update_id": str(row.get("id", "")).strip(),
            "frontier_id": str(row.get("frontier_id", "")).strip(),
            "execution_id": str(row.get("execution_id", "")).strip(),
            "hypothesis_id": str(row.get("hypothesis_id", "")).strip(),
            "experiment_spec_id": str(row.get("experiment_spec_id", "")).strip(),
            "transition": str(row.get("transition", "")).strip(),
            "confidence": str(row.get("confidence", "")).strip(),
            "reason_code": str(row.get("reason_code", "")).strip(),
        }
        if trace["frontier_id"] and trace["execution_id"] and trace["experiment_spec_id"]:
            return trace

        hypothesis_id = trace["hypothesis_id"]
        if not hypothesis_id:
            return trace

        matching_frontier = [
            item
            for item in frontier_rows
            if isinstance(item, dict) and str(item.get("hypothesis_id", "")).strip() == hypothesis_id
        ]
        if len(matching_frontier) != 1:
            return trace

        frontier_trace = cls._frontier_trace(matching_frontier[0])
        if not trace["frontier_id"]:
            trace["frontier_id"] = frontier_trace["frontier_id"]
        if not trace["execution_id"]:
            trace["execution_id"] = frontier_trace["execution_id"]
        if not trace["experiment_spec_id"]:
            trace["experiment_spec_id"] = frontier_trace["experiment_spec_id"]
        return trace

    @classmethod
    def _frontier_status_delta(
        cls,
        before: dict,
        after: dict,
        *,
        target_status: str,
    ) -> list[dict]:
        before_rows = cls._rows_by_id(before.get("frontier", []))
        changed: list[dict] = []
        for row in after.get("frontier", []):
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id", "")).strip()
            if not row_id:
                continue
            status = str(row.get("status", "")).strip()
            before_status = str(before_rows.get(row_id, {}).get("status", "")).strip()
            if status == target_status and before_status != target_status:
                changed.append(cls._frontier_trace(row))
        return changed

    @classmethod
    def _new_reproduction_requests(cls, before: dict, after: dict) -> list[dict]:
        before_rows = cls._rows_by_id(before.get("frontier", []))
        requested: list[dict] = []
        for row in after.get("frontier", []):
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id", "")).strip()
            if not row_id:
                continue
            after_status = str(row.get("status", "")).strip()
            after_repro = bool(row.get("repro_required", False))
            if not after_repro or after_status not in {"approved", "needs_repro"}:
                continue
            before_row = before_rows.get(row_id, {})
            before_repro = bool(before_row.get("repro_required", False))
            before_status = str(before_row.get("status", "")).strip()
            if not before_repro or before_status not in {"approved", "needs_repro"}:
                requested.append(cls._frontier_trace(row))
        return requested

    def _peek_pending_idea_trace(self) -> dict:
        pool_path = self.research_dir / "idea_pool.json"
        pool_data = locked_read_json(
            pool_path,
            FileLock(str(pool_path) + ".lock"),
            default=lambda: {"ideas": []},
        )
        ideas = pool_data.get("ideas", []) if isinstance(pool_data, dict) else []
        candidates = [
            item
            for item in ideas
            if isinstance(item, dict) and str(item.get("status", "")).strip() in {"pending", "running"}
        ]
        if not candidates:
            return {}
        candidates.sort(
            key=lambda item: (
                int(item.get("priority", 9999) or 9999),
                str(item.get("id", "")),
            )
        )
        item = candidates[0]
        return {
            "frontier_id": str(item.get("frontier_id", "")).strip(),
            "idea_id": str(item.get("id", "")).strip(),
            "execution_id": str(item.get("execution_id", "")).strip(),
            "hypothesis_id": str(item.get("hypothesis_id", "")).strip(),
            "experiment_spec_id": str(item.get("experiment_spec_id", "")).strip(),
            "selection_reason_code": str(item.get("selection_reason_code", "")).strip(),
        }

    @staticmethod
    def _trace_env(trace: dict) -> dict[str, str]:
        env = {
            "OPEN_RESEARCHER_PROTOCOL": "research-v1",
            "OPEN_RESEARCHER_FRONTIER_ID": str(trace.get("frontier_id", "")).strip(),
            "OPEN_RESEARCHER_IDEA_ID": str(trace.get("idea_id", "")).strip(),
            "OPEN_RESEARCHER_EXECUTION_ID": str(trace.get("execution_id", "")).strip(),
            "OPEN_RESEARCHER_HYPOTHESIS_ID": str(trace.get("hypothesis_id", "")).strip(),
            "OPEN_RESEARCHER_EXPERIMENT_SPEC_ID": str(trace.get("experiment_spec_id", "")).strip(),
        }
        return {key: value for key, value in env.items() if value}

    @staticmethod
    def _idea_trace(item: dict) -> dict:
        return {
            "frontier_id": str(item.get("frontier_id", "")).strip(),
            "idea_id": str(item.get("id", "")).strip(),
            "execution_id": str(item.get("execution_id", "")).strip(),
            "hypothesis_id": str(item.get("hypothesis_id", "")).strip(),
            "experiment_spec_id": str(item.get("experiment_spec_id", "")).strip(),
            "selection_reason_code": str(item.get("selection_reason_code", "")).strip(),
        }

    def _read_experiment_phase(self) -> str:
        progress_path = self.research_dir / "experiment_progress.json"
        if not progress_path.exists():
            return "init"
        try:
            payload = json.loads(progress_path.read_text())
        except (OSError, json.JSONDecodeError):
            return "init"
        return str(payload.get("phase", "init") or "init").strip() or "init"

    def _read_control_state(self) -> dict:
        from open_researcher.control_plane import read_control

        return read_control(self.research_dir / "control.json")

    def _wait_until_unpaused(self, stop_event: threading.Event) -> bool:
        while not stop_event.is_set():
            ctrl = self._read_control_state()
            if not bool(ctrl.get("paused", False)):
                return True
            time.sleep(0.2)
        return False

    def _consume_skip_current(self, *, source: str) -> bool:
        from open_researcher.control_plane import consume_skip_current

        return consume_skip_current(self.research_dir / "control.json", source=source)

    def _skip_next_pending_idea(self) -> dict | None:
        from open_researcher.idea_pool import IdeaBacklog

        pool = IdeaBacklog(self.research_dir / "idea_pool.json")
        pending = pool.list_by_status("pending")
        if not pending:
            return None
        idea = pending[0]
        if not pool.update_status(str(idea.get("id", "")).strip(), "skipped"):
            return None
        skipped = dict(idea)
        skipped["status"] = "skipped"
        return skipped

    def _enforce_runtime_controls(
        self,
        stop_event: threading.Event,
        *,
        allow_skip: bool,
        source: str,
    ) -> str | None:
        if not self._wait_until_unpaused(stop_event):
            return "stopped"
        if allow_skip and self._consume_skip_current(source=source):
            skipped = self._skip_next_pending_idea()
            if skipped is not None:
                trace = self._idea_trace(skipped)
                self.emit(
                    AgentOutput(
                        phase="experimenting",
                        detail=(
                            "Runtime consumed skip_current and marked "
                            f"{trace.get('idea_id') or trace.get('frontier_id') or 'current item'} as skipped."
                        ),
                    )
                )
            return "skipped"
        return None

    def _latest_result_status_since(self, before_count: int) -> str:
        rows = load_results(self.repo_path)
        if len(rows) <= before_count:
            return ""
        latest = rows[-1] if rows else {}
        if not isinstance(latest, dict):
            return ""
        return str(latest.get("status", "")).strip()

    def _mark_failed_serial_idea(self, trace: dict) -> None:
        from open_researcher.idea_pool import IdeaBacklog

        idea_id = str(trace.get("idea_id", "")).strip()
        if not idea_id:
            return
        pool = IdeaBacklog(self.research_dir / "idea_pool.json")
        pool.update_status(idea_id, "skipped")

    def _restore_serial_idea_pending(self, trace: dict) -> None:
        from open_researcher.idea_pool import IdeaBacklog

        idea_id = str(trace.get("idea_id", "")).strip()
        if not idea_id:
            return
        pool = IdeaBacklog(self.research_dir / "idea_pool.json")
        pool.update_status(idea_id, "pending")

    def _run_serial_experiment_batch(
        self,
        exp_agent,
        *,
        experiments_completed: int,
        effective_max: int,
        crash_counter: CrashCounter,
        phase_gate: PhaseGate,
        stop_event: threading.Event,
    ) -> tuple[int, int | None, str | None]:
        watchdog = TimeoutWatchdog(self.cfg.timeout, on_timeout=lambda: exp_agent.terminate())
        last_code: int | None = None
        try:
            while not stop_event.is_set() and self._has_pending_ideas(self.research_dir):
                control_action = self._enforce_runtime_controls(
                    stop_event,
                    allow_skip=True,
                    source="serial_runtime",
                )
                if control_action == "stopped":
                    return experiments_completed, last_code, "stopped"
                if control_action == "skipped":
                    continue

                trace = self._peek_pending_idea_trace()
                try:
                    workspace_snapshot = capture_clean_workspace_snapshot(self.repo_path)
                except GitWorkspaceError as exc:
                    self.emit(AgentOutput(phase="experimenting", detail=f"Fatal runtime safety error: {exc}"))
                    self.had_experiment_failure = True
                    self.last_experiment_failure_code = 1
                    return experiments_completed, 1, "experiment_failed"

                experiments_completed += 1
                results_before_count = len(load_results(self.repo_path))
                self.emit(
                    ExperimentStarted(
                        experiment_num=experiments_completed,
                        max_experiments=effective_max,
                        frontier_id=trace.get("frontier_id", ""),
                        idea_id=trace.get("idea_id", ""),
                        execution_id=trace.get("execution_id", ""),
                        hypothesis_id=trace.get("hypothesis_id", ""),
                        experiment_spec_id=trace.get("experiment_spec_id", ""),
                        selection_reason_code=trace.get("selection_reason_code", ""),
                    )
                )

                watchdog.reset()
                try:
                    code = self._run_agent(
                        exp_agent,
                        phase="experimenting",
                        program_file=resolve_role_program_file(self.research_dir, "experiment"),
                        error_tag="exp",
                        env=self._trace_env(trace),
                    )
                finally:
                    watchdog.stop()
                self._accumulate_token_metrics(exp_agent, phase="experimenting", experiment_num=experiments_completed)

                last_code = code
                self.emit(
                    ExperimentCompleted(
                        experiment_num=experiments_completed,
                        exit_code=code,
                        frontier_id=trace.get("frontier_id", ""),
                        idea_id=trace.get("idea_id", ""),
                        execution_id=trace.get("execution_id", ""),
                        hypothesis_id=trace.get("hypothesis_id", ""),
                        experiment_spec_id=trace.get("experiment_spec_id", ""),
                        selection_reason_code=trace.get("selection_reason_code", ""),
                    )
                )
                if self._apply_budget_check() == "stop":
                    self.last_stop_reason = "token_budget"
                    return experiments_completed, last_code, "token_budget"

                status = self._latest_result_status_since(results_before_count)
                try:
                    if last_code != 0 or status in {"discard", "crash"}:
                        rollback_workspace(self.repo_path, workspace_snapshot)
                    elif last_code == 0:
                        ensure_clean_workspace(self.repo_path, context="after successful experiment")
                except GitWorkspaceError as exc:
                    self.emit(AgentOutput(phase="experimenting", detail=f"Fatal runtime safety error: {exc}"))
                    if last_code == 0:
                        self._restore_serial_idea_pending(trace)
                    self.had_experiment_failure = True
                    self.last_experiment_failure_code = 1
                    return experiments_completed, 1, "experiment_failed"
                if last_code != 0:
                    self.had_experiment_failure = True
                    self.last_experiment_failure_code = last_code
                    if not status:
                        self._mark_failed_serial_idea(trace)
                        status = "crash"
                        self.emit(
                            AgentOutput(
                                phase="experimenting",
                                detail=(
                                    "Experiment exited non-zero without recording a result row; "
                                    "runtime marked the claimed backlog item as skipped/crash."
                                ),
                            )
                        )
                if status and crash_counter.record(status):
                    self._pause(
                        self.research_dir,
                        f"Crash limit reached: {self.cfg.max_crashes} consecutive crashes",
                    )
                    self.emit(CrashLimitReached(max_crashes=self.cfg.max_crashes))
                    return experiments_completed, last_code, "crash_limit"

                if effective_max > 0 and experiments_completed >= effective_max:
                    self.emit(LimitReached(max_experiments=effective_max))
                    return experiments_completed, last_code, "limit"

                phase = phase_gate.check()
                if phase:
                    self.emit(PhaseTransition(next_phase=phase))
                    return experiments_completed, last_code, "phase_transition"
        finally:
            watchdog.stop()

        return experiments_completed, last_code, None

    def _ensure_parallel_experiment_ready(
        self,
        *,
        stop_event: threading.Event,
        phase_gate: PhaseGate,
    ) -> tuple[int | None, str | None]:
        phase = self._read_experiment_phase()
        if phase == "experimenting":
            return None, None
        if not self._wait_until_unpaused(stop_event):
            return None, "stopped"
        self.emit(
            AgentOutput(
                phase="experimenting",
                detail=(
                    "Parallel runtime promoted experiment_progress.json to "
                    "'experimenting'; shared bootstrap stays repo-level and "
                    "anchor/reference evidence runs as frontier work."
                ),
            )
        )
        try:
            atomic_write_json(self.research_dir / "experiment_progress.json", {"phase": "experimenting"})
        except OSError as exc:
            self.emit(AgentOutput(phase="experimenting", detail=f"Failed to set parallel phase: {exc}"))
            return 1, "experiment_failed"
        phase_transition = phase_gate.check()
        if phase_transition:
            self.emit(PhaseTransition(next_phase=phase_transition))
            return 0, "phase_transition"
        return 0, None

    def _frontier_projection_target(self, *, parallel_batch_runner=None) -> int:
        target = max(int(self.cfg.manager_batch_size or 1), 1)
        if parallel_batch_runner is None:
            return target
        try:
            return max(target, estimate_parallel_frontier_target(self.research_dir, self.cfg))
        except Exception:
            return target

    def _make_parallel_callbacks(
        self,
        *,
        starting_experiment_num: int,
        crash_counter: CrashCounter,
        phase_gate: PhaseGate,
    ):
        run_numbers: dict[tuple[str, str], int] = {}
        lock = threading.Lock()
        started_counter = starting_experiment_num
        stop_reason = {"value": None}

        def on_started(item: dict) -> None:
            nonlocal started_counter
            trace = self._idea_trace(item)
            with lock:
                started_counter += 1
                run_num = started_counter
                run_numbers[(trace["idea_id"], trace["execution_id"])] = run_num
            self.emit(
                ExperimentStarted(
                    experiment_num=run_num,
                    max_experiments=self._effective_max_experiments(),
                    frontier_id=trace["frontier_id"],
                    idea_id=trace["idea_id"],
                    execution_id=trace["execution_id"],
                    hypothesis_id=trace["hypothesis_id"],
                    experiment_spec_id=trace["experiment_spec_id"],
                    selection_reason_code=trace["selection_reason_code"],
                )
            )

        def on_finished(item: dict) -> bool:
            trace = self._idea_trace(item)
            key = (trace["idea_id"], trace["execution_id"])
            with lock:
                run_num = run_numbers.pop(key, starting_experiment_num + 1)
            exit_code = int(item.get("exit_code", 0) or 0)
            self.emit(
                ExperimentCompleted(
                    experiment_num=run_num,
                    exit_code=exit_code,
                    frontier_id=trace["frontier_id"],
                    idea_id=trace["idea_id"],
                    execution_id=trace["execution_id"],
                    hypothesis_id=trace["hypothesis_id"],
                    experiment_spec_id=trace["experiment_spec_id"],
                    selection_reason_code=trace["selection_reason_code"],
                )
            )

            # Accumulate token metrics from parallel worker
            token_data = item.get("_token_metrics")
            if token_data:
                metrics = TokenMetrics(
                    tokens_input=token_data["tokens_input"],
                    tokens_output=token_data["tokens_output"],
                )
                with lock:
                    self.token_ledger.record(metrics, phase="experimenting", experiment_num=run_num)
                    save_ledger(self.token_ledger, self.research_dir / "token_ledger.json")
                budget_remaining = None
                if self.cfg.token_budget > 0:
                    budget_remaining = max(0, self.cfg.token_budget - self.token_ledger.cumulative.tokens_total)
                self.emit(TokenMetricsUpdated(
                    phase="experimenting",
                    experiment_num=run_num,
                    tokens_input=metrics.tokens_input,
                    tokens_output=metrics.tokens_output,
                    tokens_total=metrics.tokens_total,
                    budget_remaining=budget_remaining,
                ))

            item_status = str(item.get("status", "")).strip()
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            verdict = str(result.get("verdict", "")).strip()
            status_for_crash = ""
            if exit_code != 0 or item_status == "skipped":
                status_for_crash = "crash"
            elif verdict in {"discarded", "discard"}:
                status_for_crash = "discard"
            elif verdict in {"kept", "keep"}:
                status_for_crash = "keep"
            elif verdict == "completed":
                status_for_crash = self._read_latest_status(self.research_dir)
            if exit_code != 0:
                self.had_experiment_failure = True
                self.last_experiment_failure_code = exit_code
            if status_for_crash and crash_counter.record(status_for_crash):
                self._pause(
                    self.research_dir,
                    f"Crash limit reached: {self.cfg.max_crashes} consecutive crashes",
                )
                self.emit(CrashLimitReached(max_crashes=self.cfg.max_crashes))
                stop_reason["value"] = "crash_limit"
                return True

            phase = phase_gate.check()
            if phase:
                self.emit(PhaseTransition(next_phase=phase))
                stop_reason["value"] = "phase_transition"
                return True
            return False

        return on_started, on_finished, stop_reason

    def run_scout(self, agent) -> int:
        """Run the Scout phase once."""
        self.emit(ScoutStarted())
        code = self._run_agent(
            agent,
            phase="scouting",
            program_file="scout_program.md",
            error_tag="scout",
        )
        self._accumulate_token_metrics(agent, phase="scouting")
        self.emit(ScoutCompleted(exit_code=code))
        if code != 0:
            self.emit(ScoutFailed(exit_code=code))
        return code

    def run_graph_protocol(
        self,
        manager_agent,
        critic_agent,
        exp_agent,
        *,
        stop: threading.Event | None = None,
        max_experiments: int | None = None,
        parallel_batch_runner=None,
    ) -> dict[str, int]:
        """Run the research-v1 manager/critic/experiment orchestration."""
        self.last_failed_role = None
        self.last_stop_reason = None
        self.last_finished_all = False
        self.last_exit_codes = {}
        self.last_experiments_completed = 0
        self.had_experiment_failure = False
        self.last_experiment_failure_code = None
        stop_event = stop or threading.Event()
        effective_max = self._effective_max_experiments(max_experiments)
        crash_counter = CrashCounter(self.cfg.max_crashes)
        phase_gate = PhaseGate(self.research_dir, self.cfg.mode)
        graph_store = ResearchGraphStore(self.research_dir / "research_graph.json")
        memory_store = ResearchMemoryStore(self.research_dir / "research_memory.json")
        activity_monitor = ActivityMonitor(self.research_dir)
        graph_store.ensure_exists()
        memory_store.ensure_exists()
        ensure_local_git_identity(self.repo_path)

        exit_codes: dict[str, int] = {}
        experiments_completed = 0
        cycle = 0
        finished_all = False

        while not stop_event.is_set():
            control_action = self._enforce_runtime_controls(
                stop_event,
                allow_skip=False,
                source="manager_runtime",
            )
            if control_action == "stopped":
                self.last_stop_reason = "stopped"
                break

            cycle += 1
            before_manager = graph_store.read()
            self.emit(ManagerCycleStarted(cycle=cycle))
            manager_code = self._run_agent(
                manager_agent,
                phase="experimenting",
                program_file=resolve_role_program_file(self.research_dir, "manager"),
                error_tag="manager",
            )
            self._accumulate_token_metrics(manager_agent, phase="experimenting")
            if self._apply_budget_check() == "stop":
                self.last_stop_reason = "token_budget"
                break
            exit_codes["manager"] = manager_code
            if manager_code != 0:
                self.emit(RoleFailed(role="manager", exit_code=manager_code))
                self.last_failed_role = "manager"
                self.last_stop_reason = "manager_failed"
                break

            after_manager = graph_store.read()
            new_hypotheses = self._new_rows_by_id(before_manager, after_manager, "hypotheses")
            if new_hypotheses:
                self.emit(
                    HypothesisProposed(
                        count=len(new_hypotheses),
                        hypothesis_ids=[
                            str(row.get("id", "")).strip() for row in new_hypotheses if str(row.get("id", "")).strip()
                        ],
                    )
                )
            new_specs = self._new_rows_by_id(before_manager, after_manager, "experiment_specs")
            if new_specs:
                self.emit(
                    ExperimentSpecCreated(
                        count=len(new_specs),
                        experiment_spec_ids=[
                            str(row.get("id", "")).strip() for row in new_specs if str(row.get("id", "")).strip()
                        ],
                    )
                )
            history_policy = graph_store.apply_history_policy(memory_store.read())
            if history_policy["updated"]:
                self.emit(
                    AgentOutput(
                        phase="experimenting",
                        detail=f"History policy updated {history_policy['updated']} frontier row(s).",
                    )
                )

            if graph_store.has_frontier_status(graph_store.PREFLIGHT_FRONTIER_STATUSES):
                control_action = self._enforce_runtime_controls(
                    stop_event,
                    allow_skip=False,
                    source="critic_preflight_runtime",
                )
                if control_action == "stopped":
                    self.last_stop_reason = "stopped"
                    break
                self.emit(CriticReviewStarted(stage="preflight"))
                before_preflight = graph_store.read()
                critic_code = self._run_agent(
                    critic_agent,
                    phase="experimenting",
                    program_file=resolve_role_program_file(self.research_dir, "critic"),
                    error_tag="critic",
                )
                exit_codes["critic"] = critic_code
                self._accumulate_token_metrics(critic_agent, phase="experimenting")
                if critic_code != 0:
                    self.emit(RoleFailed(role="critic", exit_code=critic_code))
                    self.last_failed_role = "critic"
                    self.last_stop_reason = "critic_failed"
                    break
                if self._apply_budget_check() == "stop":
                    self.last_stop_reason = "token_budget"
                    break
                after_preflight = graph_store.read()
                rejected_items = self._frontier_status_delta(
                    before_preflight,
                    after_preflight,
                    target_status="rejected",
                )
                if rejected_items:
                    self.emit(
                        ExperimentPreflightFailed(
                            rejected_count=len(rejected_items),
                            items=rejected_items,
                        )
                    )
                unresolved_drafts = [
                    self._frontier_trace(row)
                    for row in after_preflight.get("frontier", [])
                    if isinstance(row, dict) and str(row.get("status", "")).strip() == "draft"
                ]
                if unresolved_drafts:
                    self.emit(
                        AgentOutput(
                            phase="experimenting",
                            detail=(
                                "Preflight critic exited without resolving draft frontier items: "
                                + ", ".join(item["frontier_id"] for item in unresolved_drafts if item["frontier_id"])
                            ),
                        )
                    )
                    exit_codes["critic"] = 1
                    self.emit(RoleFailed(role="critic", exit_code=1))
                    self.last_failed_role = "critic"
                    self.last_stop_reason = "critic_preflight_unresolved"
                    break

            if parallel_batch_runner is not None:
                bootstrap_code, bootstrap_stop_reason = self._ensure_parallel_experiment_ready(
                    stop_event=stop_event,
                    phase_gate=phase_gate,
                )
                if bootstrap_code not in {None, 0}:
                    exit_codes["exp"] = int(bootstrap_code)
                    self.had_experiment_failure = True
                    self.last_experiment_failure_code = int(bootstrap_code)
                    self.emit(RoleFailed(role="experiment", exit_code=int(bootstrap_code)))
                    self.last_failed_role = "experiment"
                    self.last_stop_reason = bootstrap_stop_reason or "experiment_failed"
                    break
                if bootstrap_stop_reason == "stopped":
                    self.last_stop_reason = "stopped"
                    break
                if bootstrap_stop_reason == "phase_transition":
                    self.last_stop_reason = "phase_transition"
                    break

            frontier_sync = graph_store.sync_idea_pool(
                self.research_dir / "idea_pool.json",
                max_items=self._frontier_projection_target(parallel_batch_runner=parallel_batch_runner),
            )
            self.emit(
                FrontierSynced(
                    frontier_items=frontier_sync["frontier_items"],
                    items=frontier_sync.get("items"),
                )
            )
            if frontier_sync["frontier_items"] > 0:
                activity_monitor.update(
                    "experiment_agent",
                    status="queued",
                    detail=f"{frontier_sync['frontier_items']} frontier item(s) ready for execution",
                    idea="",
                )

            if not graph_store.has_executable_frontier():
                activity_monitor.update(
                    "experiment_agent",
                    status="idle",
                    detail="no executable frontier items",
                    idea="",
                )
                self.emit(NoPendingIdeas())
                finished_all = True
                break

            if parallel_batch_runner is not None:
                remaining = effective_max - experiments_completed if effective_max > 0 else None
                on_started, on_finished, stop_reason_ref = self._make_parallel_callbacks(
                    starting_experiment_num=experiments_completed,
                    crash_counter=crash_counter,
                    phase_gate=phase_gate,
                )
                parallel_result = parallel_batch_runner(
                    stop=stop_event,
                    max_claims=remaining,
                    on_experiment_started=on_started,
                    on_experiment_finished=on_finished,
                )
                experiments_completed += int(parallel_result.get("experiments_completed", 0))
                exit_codes["exp"] = int(parallel_result.get("exit_code", 0))
                if int(parallel_result.get("failed_runs", 0) or 0) > 0 or exit_codes["exp"] != 0:
                    self.had_experiment_failure = True
                    self.last_experiment_failure_code = exit_codes["exp"] or 1
                stop_reason = stop_reason_ref["value"] or parallel_result.get("stop_reason")
                if self._apply_budget_check() == "stop":
                    self.last_stop_reason = "token_budget"
                    break
            else:
                experiments_completed, last_code, stop_reason = self._run_serial_experiment_batch(
                    exp_agent,
                    experiments_completed=experiments_completed,
                    effective_max=effective_max,
                    crash_counter=crash_counter,
                    phase_gate=phase_gate,
                    stop_event=stop_event,
                )
                if last_code is not None:
                    exit_codes["exp"] = last_code

            absorb = graph_store.absorb_experiment_outcomes(
                self.research_dir / "idea_pool.json",
                load_results(self.repo_path),
                primary_metric=self.cfg.primary_metric,
                direction=self.cfg.direction,
                repro_policy=self.cfg.critic_repro_policy,
            )
            if absorb["evidence_created"]:
                self.emit(
                    EvidenceRecorded(
                        evidence_created=absorb["evidence_created"],
                        items=absorb.get("items"),
                    )
                )
            write_final_results_tsv(self.repo_path)

            if graph_store.has_frontier_status(graph_store.POST_REVIEW_FRONTIER_STATUSES):
                control_action = self._enforce_runtime_controls(
                    stop_event,
                    allow_skip=False,
                    source="critic_post_runtime",
                )
                if control_action == "stopped":
                    self.last_stop_reason = "stopped"
                    break
                self.emit(CriticReviewStarted(stage="post_run"))
                before_post = graph_store.read()
                critic_code = self._run_agent(
                    critic_agent,
                    phase="experimenting",
                    program_file=resolve_role_program_file(self.research_dir, "critic"),
                    error_tag="critic",
                )
                exit_codes["critic"] = critic_code
                self._accumulate_token_metrics(critic_agent, phase="experimenting")
                if critic_code != 0:
                    self.emit(RoleFailed(role="critic", exit_code=critic_code))
                    self.last_failed_role = "critic"
                    self.last_stop_reason = "critic_failed"
                    break
                if self._apply_budget_check() == "stop":
                    self.last_stop_reason = "token_budget"
                    break
                after_post = graph_store.read()
                new_claims = self._new_rows_by_id(before_post, after_post, "claim_updates")
                if new_claims:
                    self.emit(
                        ClaimUpdated(
                            count=len(new_claims),
                            items=[self._claim_trace(row, after_post.get("frontier", [])) for row in new_claims],
                        )
                    )
                repro_items = self._new_reproduction_requests(before_post, after_post)
                if repro_items:
                    self.emit(ReproductionRequested(count=len(repro_items), items=repro_items))
                history_policy = graph_store.apply_history_policy(memory_store.read())
                if history_policy["updated"]:
                    self.emit(
                        AgentOutput(
                            phase="experimenting",
                            detail=f"History policy updated {history_policy['updated']} frontier row(s).",
                        )
                    )
                frontier_sync = graph_store.sync_idea_pool(
                    self.research_dir / "idea_pool.json",
                    max_items=self._frontier_projection_target(parallel_batch_runner=parallel_batch_runner),
                )
                self.emit(
                    FrontierSynced(
                        frontier_items=frontier_sync["frontier_items"],
                        items=frontier_sync.get("items"),
                    )
                )
                if frontier_sync["frontier_items"] > 0:
                    activity_monitor.update(
                        "experiment_agent",
                        status="queued",
                        detail=(f"{frontier_sync['frontier_items']} frontier item(s) queued after critic review"),
                        idea="",
                    )
                else:
                    activity_monitor.update(
                        "experiment_agent",
                        status="idle",
                        detail="no pending ideas after critic review",
                        idea="",
                    )
                if any(
                    [
                        self.cfg.enable_repo_type_prior,
                        self.cfg.enable_ideation_memory,
                        self.cfg.enable_experiment_memory,
                    ]
                ):
                    memory_result = memory_store.absorb_graph(
                        after_post,
                        repo_profile=after_post.get("repo_profile", {}),
                        include_repo_type_prior=self.cfg.enable_repo_type_prior,
                        include_ideation=self.cfg.enable_ideation_memory,
                        include_experiment=self.cfg.enable_experiment_memory,
                    )
                    self.emit(
                        MemoryUpdated(
                            ideation_memory=memory_result["ideation_memory"],
                            experiment_memory=memory_result["experiment_memory"],
                        )
                    )
                write_final_results_tsv(self.repo_path)

            if stop_reason is not None:
                self.last_stop_reason = self.last_stop_reason or stop_reason
                break

            if effective_max > 0 and experiments_completed >= effective_max:
                self.last_stop_reason = self.last_stop_reason or "limit"
                break

        if finished_all:
            self.emit(AllIdeasProcessed())
            self.last_stop_reason = self.last_stop_reason or "all_ideas_processed"
        self.last_finished_all = finished_all
        if self.had_experiment_failure and int(exit_codes.get("exp", 0) or 0) == 0:
            exit_codes["exp"] = self.last_experiment_failure_code or 1
        self.last_exit_codes = dict(exit_codes)
        self.last_experiments_completed = experiments_completed
        return exit_codes
