"""Typed events emitted by the core research loop."""

from dataclasses import dataclass
from typing import Callable, Literal, TypeAlias

PhaseName = Literal["init", "scouting", "preparing", "reviewing", "experimenting", "done"]
LogLevel = Literal["info", "error"]


@dataclass(slots=True)
class SessionStarted:
    goal: str
    max_experiments: int
    repo: str


@dataclass(slots=True)
class ScoutStarted:
    pass


@dataclass(slots=True)
class AgentOutput:
    phase: PhaseName
    detail: str


@dataclass(slots=True)
class ScoutCompleted:
    exit_code: int


@dataclass(slots=True)
class ScoutFailed:
    exit_code: int


@dataclass(slots=True)
class ReviewAutoConfirmed:
    pass


@dataclass(slots=True)
class PrepareStarted:
    repo_profile: str
    working_dir: str
    python_executable: str


@dataclass(slots=True)
class PrepareStepStarted:
    step: str
    command: str
    source: str = ""


@dataclass(slots=True)
class PrepareStepCompleted:
    step: str
    status: str
    log_path: str = ""
    detail: str = ""


@dataclass(slots=True)
class PrepareCompleted:
    status: str
    unresolved: int = 0


@dataclass(slots=True)
class PrepareFailed:
    step: str
    detail: str


@dataclass(slots=True)
class RoleFailed:
    role: str
    exit_code: int


@dataclass(slots=True)
class ManagerCycleStarted:
    cycle: int


@dataclass(slots=True)
class HypothesisProposed:
    count: int
    hypothesis_ids: list[str] | None = None


@dataclass(slots=True)
class ExperimentSpecCreated:
    count: int
    experiment_spec_ids: list[str] | None = None


@dataclass(slots=True)
class CriticReviewStarted:
    stage: str


@dataclass(slots=True)
class FrontierSynced:
    frontier_items: int
    items: list[dict] | None = None


@dataclass(slots=True)
class ExperimentPreflightFailed:
    rejected_count: int
    items: list[dict] | None = None


@dataclass(slots=True)
class ExperimentStarted:
    experiment_num: int
    max_experiments: int
    frontier_id: str = ""
    idea_id: str = ""
    execution_id: str = ""
    hypothesis_id: str = ""
    experiment_spec_id: str = ""
    selection_reason_code: str = ""


@dataclass(slots=True)
class ExperimentCompleted:
    experiment_num: int
    exit_code: int
    frontier_id: str = ""
    idea_id: str = ""
    execution_id: str = ""
    hypothesis_id: str = ""
    experiment_spec_id: str = ""
    selection_reason_code: str = ""


@dataclass(slots=True)
class EvidenceRecorded:
    evidence_created: int
    items: list[dict] | None = None


@dataclass(slots=True)
class ClaimUpdated:
    count: int
    items: list[dict] | None = None


@dataclass(slots=True)
class ReproductionRequested:
    count: int
    items: list[dict] | None = None


@dataclass(slots=True)
class MemoryUpdated:
    ideation_memory: int
    experiment_memory: int


@dataclass(slots=True)
class NoPendingIdeas:
    pass


@dataclass(slots=True)
class LimitReached:
    max_experiments: int


@dataclass(slots=True)
class CrashLimitReached:
    max_crashes: int


@dataclass(slots=True)
class PhaseTransition:
    next_phase: str


@dataclass(slots=True)
class AllIdeasProcessed:
    pass


@dataclass(slots=True)
class SessionCompleted:
    pass


@dataclass(slots=True)
class SessionFailed:
    failed_role: str
    exit_code: int


ResearchEvent: TypeAlias = (
    SessionStarted
    | ScoutStarted
    | AgentOutput
    | ScoutCompleted
    | ScoutFailed
    | PrepareStarted
    | PrepareStepStarted
    | PrepareStepCompleted
    | PrepareCompleted
    | PrepareFailed
    | ReviewAutoConfirmed
    | RoleFailed
    | ManagerCycleStarted
    | HypothesisProposed
    | ExperimentSpecCreated
    | CriticReviewStarted
    | FrontierSynced
    | ExperimentPreflightFailed
    | ExperimentStarted
    | ExperimentCompleted
    | EvidenceRecorded
    | ClaimUpdated
    | ReproductionRequested
    | MemoryUpdated
    | NoPendingIdeas
    | LimitReached
    | CrashLimitReached
    | PhaseTransition
    | AllIdeasProcessed
    | SessionCompleted
    | SessionFailed
)
EventHandler = Callable[[ResearchEvent], None]


def event_name(event: ResearchEvent) -> str:
    """Return the stable event name used by renderers and logs."""
    if isinstance(event, SessionStarted):
        return "session_started"
    if isinstance(event, ScoutStarted):
        return "scout_started"
    if isinstance(event, AgentOutput):
        return "agent_output"
    if isinstance(event, ScoutCompleted):
        return "scout_completed"
    if isinstance(event, ScoutFailed):
        return "scout_failed"
    if isinstance(event, PrepareStarted):
        return "prepare_started"
    if isinstance(event, PrepareStepStarted):
        return "prepare_step_started"
    if isinstance(event, PrepareStepCompleted):
        return "prepare_step_completed"
    if isinstance(event, PrepareCompleted):
        return "prepare_completed"
    if isinstance(event, PrepareFailed):
        return "prepare_failed"
    if isinstance(event, ReviewAutoConfirmed):
        return "auto_confirmed"
    if isinstance(event, RoleFailed):
        return "role_failed"
    if isinstance(event, ManagerCycleStarted):
        return "manager_cycle_started"
    if isinstance(event, HypothesisProposed):
        return "hypothesis_proposed"
    if isinstance(event, ExperimentSpecCreated):
        return "experiment_spec_created"
    if isinstance(event, CriticReviewStarted):
        return "critic_review_started"
    if isinstance(event, FrontierSynced):
        return "frontier_synced"
    if isinstance(event, ExperimentPreflightFailed):
        return "experiment_preflight_failed"
    if isinstance(event, ExperimentStarted):
        return "experiment_started"
    if isinstance(event, ExperimentCompleted):
        return "experiment_completed"
    if isinstance(event, EvidenceRecorded):
        return "evidence_recorded"
    if isinstance(event, ClaimUpdated):
        return "claim_updated"
    if isinstance(event, ReproductionRequested):
        return "reproduction_requested"
    if isinstance(event, MemoryUpdated):
        return "memory_updated"
    if isinstance(event, NoPendingIdeas):
        return "no_pending_ideas"
    if isinstance(event, LimitReached):
        return "limit_reached"
    if isinstance(event, CrashLimitReached):
        return "crash_limit"
    if isinstance(event, PhaseTransition):
        return "phase_transition"
    if isinstance(event, AllIdeasProcessed):
        return "all_ideas_processed"
    if isinstance(event, SessionCompleted):
        return "session_completed"
    if isinstance(event, SessionFailed):
        return "session_failed"
    raise TypeError(f"Unsupported event type: {type(event)!r}")


def event_phase(event: ResearchEvent) -> PhaseName:
    """Return the logical workflow phase for an event."""
    if isinstance(event, SessionStarted):
        return "init"
    if isinstance(event, (ScoutStarted, ScoutCompleted, ScoutFailed)):
        return "scouting"
    if isinstance(event, (PrepareStarted, PrepareStepStarted, PrepareStepCompleted, PrepareCompleted, PrepareFailed)):
        return "preparing"
    if isinstance(event, ReviewAutoConfirmed):
        return "reviewing"
    if isinstance(event, RoleFailed):
        return "experimenting"
    if isinstance(event, AgentOutput):
        return event.phase
    if isinstance(
        event,
        (
            ManagerCycleStarted,
            HypothesisProposed,
            ExperimentSpecCreated,
            CriticReviewStarted,
            FrontierSynced,
            ExperimentPreflightFailed,
            ExperimentStarted,
            ExperimentCompleted,
            EvidenceRecorded,
            ClaimUpdated,
            ReproductionRequested,
            MemoryUpdated,
            NoPendingIdeas,
            LimitReached,
            CrashLimitReached,
            PhaseTransition,
        ),
    ):
        return "experimenting"
    if isinstance(event, (AllIdeasProcessed, SessionCompleted, SessionFailed)):
        return "done"
    raise TypeError(f"Unsupported event type: {type(event)!r}")


def event_level(event: ResearchEvent) -> LogLevel:
    """Return the default log level for an event."""
    if isinstance(
        event,
        (ScoutFailed, PrepareFailed, RoleFailed, CrashLimitReached, ExperimentPreflightFailed, SessionFailed),
    ):
        return "error"
    return "info"


def event_payload(event: ResearchEvent) -> dict:
    """Return event-specific payload fields for structured renderers."""
    if isinstance(event, SessionStarted):
        return {
            "goal": event.goal,
            "max_experiments": event.max_experiments,
            "repo": event.repo,
        }
    if isinstance(event, AgentOutput):
        return {"detail": event.detail}
    if isinstance(event, ScoutCompleted):
        return {"exit_code": event.exit_code}
    if isinstance(event, ScoutFailed):
        return {"exit_code": event.exit_code}
    if isinstance(event, PrepareStarted):
        return {
            "repo_profile": event.repo_profile,
            "working_dir": event.working_dir,
            "python_executable": event.python_executable,
        }
    if isinstance(event, PrepareStepStarted):
        return {
            "step": event.step,
            "command": event.command,
            "source": event.source,
        }
    if isinstance(event, PrepareStepCompleted):
        return {
            "step": event.step,
            "status": event.status,
            "log_path": event.log_path,
            "detail": event.detail,
        }
    if isinstance(event, PrepareCompleted):
        return {"status": event.status, "unresolved": event.unresolved}
    if isinstance(event, PrepareFailed):
        return {"step": event.step, "detail": event.detail}
    if isinstance(event, RoleFailed):
        return {"role": event.role, "exit_code": event.exit_code}
    if isinstance(event, ManagerCycleStarted):
        return {"cycle": event.cycle}
    if isinstance(event, HypothesisProposed):
        payload = {"count": event.count}
        if event.hypothesis_ids:
            payload["hypothesis_ids"] = event.hypothesis_ids
        return payload
    if isinstance(event, ExperimentSpecCreated):
        payload = {"count": event.count}
        if event.experiment_spec_ids:
            payload["experiment_spec_ids"] = event.experiment_spec_ids
        return payload
    if isinstance(event, CriticReviewStarted):
        return {"stage": event.stage}
    if isinstance(event, FrontierSynced):
        payload = {"frontier_items": event.frontier_items}
        if event.items:
            payload["items"] = event.items
        return payload
    if isinstance(event, ExperimentPreflightFailed):
        payload = {"rejected_count": event.rejected_count}
        if event.items:
            payload["items"] = event.items
        return payload
    if isinstance(event, ExperimentStarted):
        payload = {
            "experiment_num": event.experiment_num,
            "max_experiments": event.max_experiments,
            "frontier_id": event.frontier_id,
            "idea_id": event.idea_id,
            "execution_id": event.execution_id,
            "hypothesis_id": event.hypothesis_id,
            "experiment_spec_id": event.experiment_spec_id,
            "selection_reason_code": event.selection_reason_code,
            "reason_code": event.selection_reason_code,
        }
        return {key: value for key, value in payload.items() if value not in {"", None}}
    if isinstance(event, ExperimentCompleted):
        payload = {
            "experiment_num": event.experiment_num,
            "exit_code": event.exit_code,
            "frontier_id": event.frontier_id,
            "idea_id": event.idea_id,
            "execution_id": event.execution_id,
            "hypothesis_id": event.hypothesis_id,
            "experiment_spec_id": event.experiment_spec_id,
            "selection_reason_code": event.selection_reason_code,
            "reason_code": event.selection_reason_code,
        }
        return {key: value for key, value in payload.items() if value not in {"", None}}
    if isinstance(event, EvidenceRecorded):
        payload = {"evidence_created": event.evidence_created}
        if event.items:
            payload["items"] = event.items
        return payload
    if isinstance(event, ClaimUpdated):
        payload = {"count": event.count}
        if event.items:
            payload["items"] = event.items
        return payload
    if isinstance(event, ReproductionRequested):
        payload = {"count": event.count}
        if event.items:
            payload["items"] = event.items
        return payload
    if isinstance(event, MemoryUpdated):
        return {
            "ideation_memory": event.ideation_memory,
            "experiment_memory": event.experiment_memory,
        }
    if isinstance(event, SessionFailed):
        return {
            "failed_role": event.failed_role,
            "exit_code": event.exit_code,
        }
    if isinstance(event, LimitReached):
        return {
            "max_experiments": event.max_experiments,
            "detail": f"Max experiments ({event.max_experiments}) reached",
        }
    if isinstance(event, CrashLimitReached):
        return {
            "max_crashes": event.max_crashes,
            "detail": f"Crash limit ({event.max_crashes}) reached",
        }
    if isinstance(event, PhaseTransition):
        return {"phase": event.next_phase}
    return {}
