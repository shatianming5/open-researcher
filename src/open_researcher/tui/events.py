"""TUI renderer for typed research loop events."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from open_researcher.event_journal import EventJournal
from open_researcher.log_output import make_safe_output
from open_researcher.research_events import (
    AgentOutput,
    AllIdeasProcessed,
    ClaimUpdated,
    CrashLimitReached,
    CriticReviewStarted,
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
    PrepareCompleted,
    PrepareFailed,
    PrepareStarted,
    PrepareStepCompleted,
    PrepareStepStarted,
    ReproductionRequested,
    ResearchEvent,
    RoleFailed,
    ScoutStarted,
    SessionFailed,
)

if TYPE_CHECKING:
    from open_researcher.tui.app import ResearchApp


class TUIEventRenderer:
    """Render typed research events into the existing unified TUI log."""

    def __init__(self, app: "ResearchApp", research_dir: Path):
        self._app = app
        self._safe_output = make_safe_output(app.append_log, research_dir / "run.log")
        self._journal = EventJournal(research_dir / "events.jsonl")

    def close(self) -> None:
        if hasattr(self._safe_output, "close"):
            self._safe_output.close()
        self._journal.close()

    def make_output_callback(self, phase: str):
        def on_output(line: str) -> None:
            self.on_event(AgentOutput(phase=phase, detail=line))

        return on_output

    def _set_phase(self, phase: str) -> None:
        try:
            self._app.call_from_thread(setattr, self._app, "app_phase", phase)
        except RuntimeError:
            pass

    def _set_trace(self, text: str) -> None:
        clean = str(text or "").strip()
        if not hasattr(self._app, "set_trace_banner"):
            return
        try:
            self._app.call_from_thread(self._app.set_trace_banner, clean)
        except RuntimeError:
            pass

    @staticmethod
    def _id_suffix(ids: list[str] | None) -> str:
        if not ids:
            return ""
        clean = [item for item in ids if item]
        if not clean:
            return ""
        preview = ", ".join(clean[:2])
        if len(clean) > 2:
            preview = f"{preview}, +{len(clean) - 2}"
        return f" [{preview}]"

    @staticmethod
    def _format_trace_suffix(record: dict | None) -> str:
        if not isinstance(record, dict):
            return ""
        parts: list[str] = []
        for key in [
            "claim_update_id",
            "evidence_id",
            "frontier_id",
            "execution_id",
            "reason_code",
        ]:
            value = str(record.get(key, "")).strip()
            if value:
                parts.append(value)
        if not parts:
            return ""
        return f" [{' / '.join(parts)}]"

    def _first_item_suffix(self, items: list[dict] | None) -> str:
        if not items:
            return ""
        for item in items:
            suffix = self._format_trace_suffix(item if isinstance(item, dict) else None)
            if suffix:
                return suffix
        return ""

    def _experiment_suffix(self, event: ExperimentStarted | ExperimentCompleted) -> str:
        return self._format_trace_suffix(
            {
                "frontier_id": event.frontier_id,
                "execution_id": event.execution_id,
                "reason_code": event.selection_reason_code,
            }
        )

    def on_event(self, event: ResearchEvent) -> None:
        self._journal.emit_typed(event)

        if isinstance(event, AgentOutput):
            self._safe_output(event.detail)
            return

        if isinstance(event, ScoutStarted):
            self._set_phase("scouting")
            self._set_trace("Scout agent | repository reconnaissance")
            return

        if isinstance(event, PrepareStarted):
            self._set_phase("preparing")
            self._set_trace(
                f"Prepare | {event.repo_profile} | {event.working_dir} | {event.python_executable}"
            )
            self._safe_output(
                f"[prepare] Starting repo prepare ({event.repo_profile}) in {event.working_dir}."
            )
            return

        if isinstance(event, PrepareStepStarted):
            self._set_phase("preparing")
            self._set_trace(f"Prepare {event.step} | {event.source or 'auto-detected'}")
            self._safe_output(
                f"[prepare] {event.step} -> {event.command}"
            )
            return

        if isinstance(event, PrepareStepCompleted):
            self._set_trace(f"Prepare {event.step} complete | {event.status}")
            suffix = f" ({event.detail})" if event.detail else ""
            self._safe_output(
                f"[prepare] {event.step} completed [{event.status}].{suffix}"
            )
            return

        if isinstance(event, PrepareCompleted):
            self._set_trace(f"Prepare complete | {event.status}")
            self._safe_output(
                f"[prepare] Repo prepare finished [{event.status}]"
                + (f" with {event.unresolved} unresolved item(s)." if event.unresolved else ".")
            )
            return

        if isinstance(event, PrepareFailed):
            self._set_trace(f"Prepare failed | {event.step}")
            self._safe_output(f"[prepare] {event.step} failed: {event.detail}")
            return

        if isinstance(event, ManagerCycleStarted):
            self._set_phase("experimenting")
            self._set_trace(f"Cycle {event.cycle} | Research Manager")
            self._safe_output(f"[system] === Graph cycle {event.cycle}: Starting Research Manager ===")
            return

        if isinstance(event, HypothesisProposed):
            suffix = self._id_suffix(event.hypothesis_ids)
            self._set_trace(f"Manager | hypothesis refresh{suffix}")
            self._safe_output(
                f"[manager] Proposed/updated {event.count} hypothesis item(s)."
                f"{suffix}"
            )
            return

        if isinstance(event, ExperimentSpecCreated):
            suffix = self._id_suffix(event.experiment_spec_ids)
            self._set_trace(f"Manager | experiment specs{suffix}")
            self._safe_output(
                f"[manager] Prepared {event.count} experiment spec(s)."
                f"{suffix}"
            )
            return

        if isinstance(event, CriticReviewStarted):
            self._set_trace(f"Critic | {event.stage} review")
            self._safe_output(f"[critic] Starting {event.stage} review.")
            return

        if isinstance(event, FrontierSynced):
            suffix = self._first_item_suffix(event.items)
            self._set_trace(f"Frontier synced | {event.frontier_items} runnable item(s){suffix}")
            self._safe_output(
                f"[system] Frontier synced ({event.frontier_items} runnable item(s))."
                f"{suffix}"
            )
            return

        if isinstance(event, ExperimentPreflightFailed):
            suffix = self._first_item_suffix(event.items)
            self._set_trace(f"Critic rejected | {event.rejected_count} spec(s){suffix}")
            self._safe_output(
                f"[critic] Rejected {event.rejected_count} experiment spec(s)."
                f"{suffix}"
            )
            return

        if isinstance(event, ExperimentStarted):
            self._set_phase("experimenting")
            suffix = self._experiment_suffix(event)
            self._set_trace(f"Experiment running | run #{event.experiment_num}{suffix}")
            self._safe_output(
                f"[exp] Starting experiment agent (run #{event.experiment_num})..."
                f"{suffix}"
            )
            return

        if isinstance(event, ExperimentCompleted):
            suffix = self._experiment_suffix(event)
            self._set_trace(f"Experiment finished | run #{event.experiment_num} | code={event.exit_code}{suffix}")
            self._safe_output(
                f"[exp] Experiment agent finished (run #{event.experiment_num}, code={event.exit_code})."
                f"{suffix}"
            )
            return

        if isinstance(event, RoleFailed):
            self._set_trace(f"{event.role} failed | code={event.exit_code}")
            self._safe_output(f"[system] {event.role} failed with exit code {event.exit_code}.")
            return

        if isinstance(event, NoPendingIdeas):
            self._set_trace("Research queue drained | no pending frontier items")
            self._safe_output("[system] No projected backlog items remain. Stopping.")
            return

        if isinstance(event, EvidenceRecorded):
            suffix = self._first_item_suffix(event.items)
            self._set_trace(f"Evidence recorded | {event.evidence_created} item(s){suffix}")
            self._safe_output(
                f"[critic] Recorded {event.evidence_created} evidence item(s)."
                f"{suffix}"
            )
            return

        if isinstance(event, ClaimUpdated):
            suffix = self._first_item_suffix(event.items)
            self._set_trace(f"Claim updated | {event.count} item(s){suffix}")
            self._safe_output(
                f"[critic] Updated {event.count} claim(s)."
                f"{suffix}"
            )
            return

        if isinstance(event, ReproductionRequested):
            suffix = self._first_item_suffix(event.items)
            self._set_trace(f"Reproduction requested | {event.count} item(s){suffix}")
            self._safe_output(
                f"[critic] Requested reproduction for {event.count} item(s)."
                f"{suffix}"
            )
            return

        if isinstance(event, MemoryUpdated):
            self._set_trace(
                f"Memory updated | ideation={event.ideation_memory} experiment={event.experiment_memory}"
            )
            self._safe_output(
                f"[system] Memory updated (ideation={event.ideation_memory}, experiment={event.experiment_memory})."
            )
            return

        if isinstance(event, LimitReached):
            self._set_trace(f"Research limit reached | max_experiments={event.max_experiments}")
            self._safe_output(f"[system] Max experiments ({event.max_experiments}) reached. Stopping.")
            return

        if isinstance(event, CrashLimitReached):
            self._set_trace(f"Crash limit reached | max_crashes={event.max_crashes}")
            self._safe_output(
                f"[system] Crash limit reached ({event.max_crashes} consecutive crashes). Pausing."
            )
            return

        if isinstance(event, PhaseTransition):
            self._set_trace(f"Phase transition | {event.next_phase}")
            self._safe_output(f"[system] Phase transition to '{event.next_phase}' — pausing for review.")
            return

        if isinstance(event, AllIdeasProcessed):
            self._set_trace("Research session finished | all cycles complete")
            self._safe_output("[system] All cycles finished.")
            return

        if isinstance(event, SessionFailed):
            self._set_trace(f"Session failed | {event.failed_role} | code={event.exit_code}")
            self._safe_output(
                f"[system] Session failed while running {event.failed_role} (code={event.exit_code})."
            )
