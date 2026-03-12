"""TUI-specific aggregated view models for research-v1."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from open_researcher.event_journal import EventJournal
from open_researcher.results_cmd import load_results
from open_researcher.status_cmd import parse_research_state


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _short_text(value: str, *, limit: int = 72) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _load_json_object(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_json_list(path: Path, key: str) -> list[dict]:
    payload = _load_json_object(path)
    rows = payload.get(key, [])
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


@dataclass(slots=True)
class SessionChrome:
    branch: str
    protocol: str
    mode: str
    phase: str
    phase_label: str
    paused: bool
    skip_current: bool
    primary_metric: str
    direction: str
    baseline_value: float | None
    current_value: float | None
    best_value: float | None
    total: int
    keep: int
    discard: int
    crash: int
    frontier_runnable: int
    config_error: str = ""
    graph_error: str = ""
    tokens_used: int = 0
    token_budget: int = 0
    estimated_cost: float = 0.0


@dataclass(slots=True)
class GraphSummary:
    hypotheses: int = 0
    experiment_specs: int = 0
    evidence: int = 0
    claims: int = 0
    frontier_total: int = 0
    frontier_runnable: int = 0
    frontier_status_counts: dict[str, int] = field(default_factory=dict)
    repo_type_priors: int = 0
    ideation_memory: int = 0
    experiment_memory: int = 0


@dataclass(slots=True)
class BootstrapSummary:
    status: str = "pending"
    working_dir: str = "."
    python_executable: str = ""
    install_status: str = "pending"
    data_status: str = "pending"
    smoke_status: str = "pending"
    log_path: str = ""
    errors: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    missing_paths: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FrontierCard:
    frontier_id: str
    execution_id: str
    idea_id: str
    priority: int
    status: str
    claim_state: str
    repro_required: bool
    hypothesis_summary: str
    spec_summary: str
    description: str
    attribution_focus: str
    expected_signal: str
    risk_level: str
    reason_code: str
    metric_value: str = ""
    manager_priority: int = 0
    runtime_priority: int = 0
    policy_state: str = "neutral"
    policy_reason: str = ""


@dataclass(slots=True)
class FrontierDetail:
    frontier: FrontierCard
    hypothesis_id: str
    hypothesis_rationale: str
    expected_evidence: list[str] = field(default_factory=list)
    experiment_spec_id: str = ""
    change_plan: str = ""
    evaluation_plan: str = ""
    primary_metric: str = ""
    direction: str = ""
    baseline_value: float | None = None
    current_value: float | None = None
    global_best_value: float | None = None
    latest_metric_value: float | None = None
    best_metric_value: float | None = None
    metric_samples: int = 0
    evidence_reliability_counts: dict[str, int] = field(default_factory=dict)
    evidence: list[EvidenceItem] = field(default_factory=list)
    claims: list[ClaimItem] = field(default_factory=list)


@dataclass(slots=True)
class RoleStatus:
    key: str
    label: str
    status: str
    detail: str
    frontier_id: str
    execution_id: str
    worker_count: int
    updated_at: str


@dataclass(slots=True)
class EvidenceItem:
    evidence_id: str
    frontier_id: str
    execution_id: str
    reliability: str
    reason_code: str
    description: str
    metric_value: str


@dataclass(slots=True)
class ClaimItem:
    claim_update_id: str
    frontier_id: str
    execution_id: str
    transition: str
    confidence: str
    reason_code: str


@dataclass(slots=True)
class ExecutionSummary:
    primary_metric: str
    baseline_value: float | None
    current_value: float | None
    best_value: float | None
    total: int
    keep: int
    discard: int
    crash: int
    recent_results: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class LineageItem:
    relation: str
    parent_id: str
    child_id: str
    parent_summary: str
    child_summary: str


@dataclass(slots=True)
class TimelineItem:
    ts: str
    event: str
    phase: str
    frontier_id: str
    execution_id: str
    reason_code: str
    detail: str


@dataclass(slots=True)
class DocNavItem:
    filename: str
    title: str
    available: bool
    dynamic: bool
    preview: str
    group: str = "Research Notes"


@dataclass(slots=True)
class DashboardState:
    session: SessionChrome
    bootstrap: BootstrapSummary
    graph: GraphSummary
    frontiers: list[FrontierCard]
    frontier_details: dict[str, FrontierDetail]
    roles: list[RoleStatus]
    evidence: list[EvidenceItem]
    claims: list[ClaimItem]
    lineage: list[LineageItem]
    timeline: list[TimelineItem]
    execution: ExecutionSummary
    trace_banner: str


@dataclass(slots=True)
class DocsWorkbenchState:
    current_file: str
    items: list[DocNavItem]


def _build_role_status(key: str, label: str, activity: dict | None) -> RoleStatus:
    activity = activity if isinstance(activity, dict) else {}
    workers = activity.get("workers", [])
    worker_count = len(workers) if isinstance(workers, list) else 0
    return RoleStatus(
        key=key,
        label=label,
        status=str(activity.get("status", "idle") or "idle").strip() or "idle",
        detail=_short_text(str(activity.get("detail", "")).strip(), limit=88),
        frontier_id=str(activity.get("frontier_id", "") or activity.get("idea", "")).strip(),
        execution_id=str(activity.get("execution_id", "")).strip(),
        worker_count=worker_count,
        updated_at=str(activity.get("updated_at", "")).strip(),
    )


def _frontier_from_projected_idea(idea: dict) -> FrontierCard:
    reason_code = str(idea.get("review_reason_code", "")).strip()
    if not reason_code or reason_code == "unspecified":
        reason_code = str(idea.get("selection_reason_code", "")).strip() or "manager_refresh"
    raw_metric = idea.get("result", {}).get("metric_value") if isinstance(idea.get("result"), dict) else None
    metric_value = ""
    if raw_metric not in ("", None):
        metric_value = str(raw_metric)
    return FrontierCard(
        frontier_id=str(idea.get("frontier_id", "")).strip() or str(idea.get("id", "")).strip(),
        execution_id=str(idea.get("execution_id", "")).strip(),
        idea_id=str(idea.get("id", "")).strip(),
        priority=_safe_int(idea.get("runtime_priority", idea.get("priority", 5)), 5),
        status=str(idea.get("status", "pending") or "pending").strip() or "pending",
        claim_state=str(idea.get("claim_state", "candidate") or "candidate").strip() or "candidate",
        repro_required=bool(idea.get("repro_required", False)),
        hypothesis_summary=_short_text(idea.get("hypothesis_summary", ""), limit=72),
        spec_summary=_short_text(
            idea.get("spec_summary", "") or idea.get("description", ""),
            limit=72,
        ),
        description=_short_text(idea.get("description", ""), limit=86),
        attribution_focus=_short_text(idea.get("attribution_focus", ""), limit=70),
        expected_signal=_short_text(idea.get("expected_signal", ""), limit=70),
        risk_level=str(idea.get("risk_level", "")).strip() or "medium",
        reason_code=reason_code,
        metric_value=metric_value,
        manager_priority=_safe_int(idea.get("manager_priority", idea.get("priority", 5)), 5),
        runtime_priority=_safe_int(idea.get("runtime_priority", idea.get("priority", 5)), 5),
        policy_state=str(idea.get("policy_state", "neutral") or "neutral").strip() or "neutral",
        policy_reason=_short_text(idea.get("policy_reason", ""), limit=88),
    )


def _frontier_from_graph_row(frontier: dict, hypotheses: dict[str, dict], specs: dict[str, dict]) -> FrontierCard:
    hypothesis = hypotheses.get(str(frontier.get("hypothesis_id", "")).strip(), {})
    spec = specs.get(str(frontier.get("experiment_spec_id", "")).strip(), {})
    reason_code = str(frontier.get("review_reason_code", "")).strip()
    if not reason_code or reason_code == "unspecified":
        reason_code = str(frontier.get("selection_reason_code", "")).strip() or "manager_refresh"
    metric_value = ""
    raw_metric = frontier.get("metric_value")
    if raw_metric not in ("", None):
        metric_value = str(raw_metric)
    return FrontierCard(
        frontier_id=str(frontier.get("id", "")).strip(),
        execution_id=str(frontier.get("active_execution_id", "") or frontier.get("last_execution_id", "")).strip(),
        idea_id=str(frontier.get("idea_id", "")).strip(),
        priority=_safe_int(frontier.get("runtime_priority", frontier.get("priority", 5)), 5),
        status=str(frontier.get("status", "draft")).strip() or "draft",
        claim_state=str(frontier.get("claim_state", "candidate")).strip() or "candidate",
        repro_required=bool(frontier.get("repro_required", False)),
        hypothesis_summary=_short_text(hypothesis.get("summary", ""), limit=72),
        spec_summary=_short_text(
            spec.get("summary", "") or frontier.get("description", ""),
            limit=72,
        ),
        description=_short_text(frontier.get("description", ""), limit=86),
        attribution_focus=_short_text(
            frontier.get("attribution_focus", "") or spec.get("attribution_focus", ""),
            limit=70,
        ),
        expected_signal=_short_text(spec.get("expected_signal", ""), limit=70),
        risk_level=str(spec.get("risk_level", "")).strip() or "medium",
        reason_code=reason_code,
        metric_value=metric_value,
        manager_priority=_safe_int(frontier.get("manager_priority", frontier.get("priority", 5)), 5),
        runtime_priority=_safe_int(frontier.get("runtime_priority", frontier.get("priority", 5)), 5),
        policy_state=str(frontier.get("policy_state", "neutral") or "neutral").strip() or "neutral",
        policy_reason=_short_text(frontier.get("policy_reason", ""), limit=88),
    )


def _build_frontier_detail(
    card: FrontierCard,
    *,
    frontier_row: dict | None,
    hypothesis: dict | None,
    spec: dict | None,
    evidence_rows: list[dict],
    claim_rows: list[dict],
    primary_metric: str,
    direction: str,
    baseline_value: float | None,
    current_value: float | None,
    global_best_value: float | None,
) -> FrontierDetail:
    hypothesis = hypothesis if isinstance(hypothesis, dict) else {}
    spec = spec if isinstance(spec, dict) else {}
    metric_values = [
        _safe_float(row.get("metric_value"))
        for row in evidence_rows
        if _safe_float(row.get("metric_value")) is not None
    ]
    latest_metric_value = metric_values[-1] if metric_values else None
    best_metric_value = None
    if metric_values:
        best_metric_value = min(metric_values) if direction == "lower_is_better" else max(metric_values)
    reliability_counts: dict[str, int] = {}
    for row in evidence_rows:
        reliability = str(row.get("reliability", "")).strip() or "pending_critic"
        reliability_counts[reliability] = reliability_counts.get(reliability, 0) + 1

    evidence = [
        EvidenceItem(
            evidence_id=str(row.get("id", "")).strip(),
            frontier_id=str(row.get("frontier_id", "")).strip(),
            execution_id=str(row.get("execution_id", "")).strip(),
            reliability=str(row.get("reliability", "")).strip() or "pending_critic",
            reason_code=str(row.get("reason_code", "")).strip() or "unspecified",
            description=_short_text(
                row.get("description", "") or row.get("kind", "result_row"),
                limit=96,
            ),
            metric_value="" if row.get("metric_value") in ("", None) else str(row.get("metric_value")),
        )
        for row in evidence_rows[-6:]
    ]
    evidence.reverse()

    claims = [
        ClaimItem(
            claim_update_id=str(row.get("id", "")).strip(),
            frontier_id=str(row.get("frontier_id", "")).strip(),
            execution_id=str(row.get("execution_id", "")).strip(),
            transition=str(row.get("transition", "")).strip() or "needs_repro",
            confidence=str(row.get("confidence", "")).strip() or "pending",
            reason_code=str(row.get("reason_code", "")).strip() or "unspecified",
        )
        for row in claim_rows[-6:]
    ]
    claims.reverse()

    frontier_row = frontier_row if isinstance(frontier_row, dict) else {}
    expected_evidence = hypothesis.get("expected_evidence", [])
    if not isinstance(expected_evidence, list):
        expected_evidence = []

    return FrontierDetail(
        frontier=card,
        hypothesis_id=str(frontier_row.get("hypothesis_id", "") or hypothesis.get("id", "")).strip(),
        hypothesis_rationale=str(hypothesis.get("rationale", "")).strip(),
        expected_evidence=[str(item).strip() for item in expected_evidence if str(item).strip()],
        experiment_spec_id=str(frontier_row.get("experiment_spec_id", "") or spec.get("id", "")).strip(),
        change_plan=str(spec.get("change_plan", "")).strip(),
        evaluation_plan=str(spec.get("evaluation_plan", "")).strip(),
        primary_metric=primary_metric,
        direction=direction,
        baseline_value=baseline_value,
        current_value=current_value,
        global_best_value=global_best_value,
        latest_metric_value=latest_metric_value,
        best_metric_value=best_metric_value,
        metric_samples=len(metric_values),
        evidence_reliability_counts=reliability_counts,
        evidence=evidence,
        claims=claims,
    )


def _doc_title(filename: str) -> str:
    stem = filename.replace(".md", "").replace("-", " ")
    return stem.title()


def _doc_group(filename: str) -> str:
    if filename in {"research_graph.md", "research_memory.md", "projected_backlog.md", "bootstrap_state.md"}:
        return "Research State"
    return "Research Notes"


def _doc_preview(path: Path) -> str:
    if not path.exists():
        return "Missing"
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "Unreadable"
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(">") or line.startswith("|"):
            continue
        return _short_text(line, limit=68)
    return "Present"


def build_docs_workbench(
    research_dir: Path, *, current_file: str, doc_files: list[str], dynamic_files: set[str]
) -> DocsWorkbenchState:
    items: list[DocNavItem] = []
    for filename in doc_files:
        dynamic = filename in dynamic_files
        source = {
            "projected_backlog.md": "idea_pool.json",
            "research_graph.md": "research_graph.json",
            "research_memory.md": "research_memory.json",
            "bootstrap_state.md": "bootstrap_state.json",
        }.get(filename, filename)
        path = research_dir / source
        preview = (
            _doc_preview(path)
            if not dynamic
            else (
                "Generated from projected frontier"
                if filename == "projected_backlog.md"
                else "Generated from canonical JSON state"
            )
        )
        items.append(
            DocNavItem(
                filename=filename,
                title=_doc_title(filename),
                available=path.exists(),
                dynamic=dynamic,
                preview=preview,
                group=_doc_group(filename),
            )
        )
    return DocsWorkbenchState(current_file=current_file, items=items)


def build_dashboard_state(
    repo_path: Path,
    *,
    state: dict | None = None,
    ideas: list[dict] | None = None,
    activities: dict | None = None,
    rows: list[dict] | None = None,
    control: dict | None = None,
    trace_banner: str = "",
) -> DashboardState:
    research_dir = repo_path / ".research"
    state = state or parse_research_state(repo_path)
    ideas = ideas or _load_json_list(research_dir / "idea_pool.json", "ideas")
    activities = activities if isinstance(activities, dict) else _load_json_object(research_dir / "activity.json")
    rows = rows or load_results(repo_path)
    control = control if isinstance(control, dict) else {}

    graph_payload = _load_json_object(research_dir / "research_graph.json")
    memory_payload = _load_json_object(research_dir / "research_memory.json")
    bootstrap_payload = state.get("bootstrap") if isinstance(state.get("bootstrap"), dict) else {}
    graph_state = state.get("graph") if isinstance(state.get("graph"), dict) else {}
    graph_frontier_rows = [row for row in graph_payload.get("frontier", []) if isinstance(row, dict)]
    frontier_by_id = {str(row.get("id", "")).strip(): row for row in graph_frontier_rows if isinstance(row, dict)}
    hypotheses_by_id = {
        str(row.get("id", "")).strip(): row for row in graph_payload.get("hypotheses", []) if isinstance(row, dict)
    }
    specs_by_id = {
        str(row.get("id", "")).strip(): row
        for row in graph_payload.get("experiment_specs", [])
        if isinstance(row, dict)
    }

    from open_researcher.config import load_config
    from open_researcher.token_tracking import estimate_cost as _estimate_cost
    from open_researcher.token_tracking import load_ledger

    _cfg = load_config(research_dir)
    _ledger = load_ledger(research_dir / "token_ledger.json")
    _ledger_cost = _estimate_cost(_ledger.cumulative) if _ledger.cumulative.tokens_total > 0 else 0.0

    session = SessionChrome(
        branch=str(state.get("branch", "unknown") or "unknown"),
        protocol=str(state.get("protocol", "") or "research-v1"),
        mode=str(state.get("mode", "") or "autonomous"),
        phase=str(state.get("phase", "") or ""),
        phase_label=str(state.get("phase_label", "") or ""),
        paused=bool(control.get("paused", False)),
        skip_current=bool(control.get("skip_current", False)),
        primary_metric=str(state.get("primary_metric", "") or "metric"),
        direction=str(state.get("direction", "") or ""),
        baseline_value=state.get("baseline_value"),
        current_value=state.get("current_value"),
        best_value=state.get("best_value"),
        total=_safe_int(state.get("total", 0)),
        keep=_safe_int(state.get("keep", 0)),
        discard=_safe_int(state.get("discard", 0)),
        crash=_safe_int(state.get("crash", 0)),
        frontier_runnable=_safe_int(graph_state.get("frontier_runnable", 0)),
        config_error=str(state.get("config_error", "") or ""),
        graph_error=str(graph_state.get("error", "") or ""),
        tokens_used=_ledger.cumulative.tokens_total,
        token_budget=_cfg.token_budget,
        estimated_cost=_ledger_cost,
    )

    graph = GraphSummary(
        hypotheses=_safe_int(graph_state.get("hypotheses", len(graph_payload.get("hypotheses", [])))),
        experiment_specs=_safe_int(graph_state.get("experiment_specs", len(graph_payload.get("experiment_specs", [])))),
        evidence=_safe_int(graph_state.get("evidence", len(graph_payload.get("evidence", [])))),
        claims=_safe_int(graph_state.get("claim_updates", len(graph_payload.get("claim_updates", [])))),
        frontier_total=_safe_int(graph_state.get("frontier_total", len(graph_payload.get("frontier", [])))),
        frontier_runnable=_safe_int(graph_state.get("frontier_runnable", 0)),
        frontier_status_counts=dict(graph_state.get("frontier_status_counts", {}) or {}),
        repo_type_priors=len(memory_payload.get("repo_type_priors", []))
        if isinstance(memory_payload.get("repo_type_priors", []), list)
        else 0,
        ideation_memory=len(memory_payload.get("ideation_memory", []))
        if isinstance(memory_payload.get("ideation_memory", []), list)
        else 0,
        experiment_memory=len(memory_payload.get("experiment_memory", []))
        if isinstance(memory_payload.get("experiment_memory", []), list)
        else 0,
    )

    bootstrap_errors = [str(item) for item in bootstrap_payload.get("errors", [])[:3]]
    bootstrap_unresolved = [str(item) for item in bootstrap_payload.get("unresolved", [])[:3]]
    if bootstrap_payload.get("error"):
        bootstrap_errors = [str(bootstrap_payload.get("error"))]
    missing_expected_paths = [
        str(item.get("path", "")).strip()
        for item in bootstrap_payload.get("expected_path_status", [])
        if isinstance(item, dict) and not item.get("exists") and str(item.get("path", "")).strip()
    ]
    bootstrap = BootstrapSummary(
        status=str(bootstrap_payload.get("status", "")).strip() or ("failed" if bootstrap_errors else "pending"),
        working_dir=str(bootstrap_payload.get("working_dir", ".") or "."),
        python_executable=str(bootstrap_payload.get("python_executable", "")).strip(),
        install_status=str(
            (bootstrap_payload.get("steps", {}) or {}).get("install", {}).get("status", "pending")
        ).strip()
        or "pending",
        data_status=str((bootstrap_payload.get("steps", {}) or {}).get("data", {}).get("status", "pending")).strip()
        or "pending",
        smoke_status=str((bootstrap_payload.get("steps", {}) or {}).get("smoke", {}).get("status", "pending")).strip()
        or "pending",
        log_path=str(bootstrap_payload.get("log_path", "")).strip(),
        errors=bootstrap_errors,
        unresolved=bootstrap_unresolved,
        missing_paths=missing_expected_paths[:3],
    )

    role_map = {
        "manager_agent": _build_role_status(
            "manager_agent",
            "Research Manager",
            activities.get("manager_agent") or activities.get("idea_agent"),
        ),
        "critic_agent": _build_role_status("critic_agent", "Research Critic", activities.get("critic_agent")),
        "experiment_agent": _build_role_status(
            "experiment_agent",
            "Experiment Agent",
            activities.get("experiment_agent"),
        ),
    }
    roles = [role_map["manager_agent"], role_map["critic_agent"], role_map["experiment_agent"]]

    frontiers: list[FrontierCard] = []
    sorted_ideas = sorted(
        [idea for idea in ideas if isinstance(idea, dict)],
        key=lambda idea: (
            _safe_int(idea.get("runtime_priority", idea.get("priority", 9999)), 9999),
            _safe_int(idea.get("manager_priority", idea.get("priority", 9999)), 9999),
            str(idea.get("id", "")),
        ),
    )
    for idea in sorted_ideas[:8]:
        frontiers.append(_frontier_from_projected_idea(idea))

    if not frontiers:
        graph_frontier = list(graph_frontier_rows)
        graph_frontier.sort(
            key=lambda row: (
                _safe_int(row.get("runtime_priority", row.get("priority", 9999)), 9999),
                _safe_int(row.get("manager_priority", row.get("priority", 9999)), 9999),
                str(row.get("id", "")),
            )
        )
        for row in graph_frontier[:8]:
            frontiers.append(_frontier_from_graph_row(row, hypotheses_by_id, specs_by_id))

    evidence_rows = [row for row in graph_payload.get("evidence", []) if isinstance(row, dict)]
    claims_rows = [row for row in graph_payload.get("claim_updates", []) if isinstance(row, dict)]
    branch_relations = [row for row in graph_payload.get("branch_relations", []) if isinstance(row, dict)]

    evidence_items = [
        EvidenceItem(
            evidence_id=str(row.get("id", "")).strip(),
            frontier_id=str(row.get("frontier_id", "")).strip(),
            execution_id=str(row.get("execution_id", "")).strip(),
            reliability=str(row.get("reliability", "")).strip() or "pending_critic",
            reason_code=str(row.get("reason_code", "")).strip() or "unspecified",
            description=_short_text(
                row.get("description", "") or row.get("kind", "result_row"),
                limit=74,
            ),
            metric_value="" if row.get("metric_value") in ("", None) else str(row.get("metric_value")),
        )
        for row in evidence_rows[-4:]
    ]
    evidence_items.reverse()

    claim_items = [
        ClaimItem(
            claim_update_id=str(row.get("id", "")).strip(),
            frontier_id=str(row.get("frontier_id", "")).strip(),
            execution_id=str(row.get("execution_id", "")).strip(),
            transition=str(row.get("transition", "")).strip() or "needs_repro",
            confidence=str(row.get("confidence", "")).strip() or "pending",
            reason_code=str(row.get("reason_code", "")).strip() or "unspecified",
        )
        for row in claims_rows[-4:]
    ]
    claim_items.reverse()

    frontier_details: dict[str, FrontierDetail] = {}
    for card in frontiers:
        frontier_row = frontier_by_id.get(card.frontier_id, {})
        hypothesis_id = str(frontier_row.get("hypothesis_id", "")).strip()
        spec_id = str(frontier_row.get("experiment_spec_id", "")).strip()
        detail = _build_frontier_detail(
            card,
            frontier_row=frontier_row,
            hypothesis=hypotheses_by_id.get(hypothesis_id, {}),
            spec=specs_by_id.get(spec_id, {}),
            evidence_rows=[row for row in evidence_rows if str(row.get("frontier_id", "")).strip() == card.frontier_id],
            claim_rows=[row for row in claims_rows if str(row.get("frontier_id", "")).strip() == card.frontier_id],
            primary_metric=session.primary_metric,
            direction=session.direction,
            baseline_value=session.baseline_value,
            current_value=session.current_value,
            global_best_value=session.best_value,
        )
        frontier_details[card.frontier_id] = detail

    lineage_items = [
        LineageItem(
            relation=str(row.get("relation", "")).strip() or "refines",
            parent_id=str(row.get("parent_hypothesis_id", "")).strip(),
            child_id=str(row.get("child_hypothesis_id", "")).strip(),
            parent_summary=_short_text(
                hypotheses_by_id.get(str(row.get("parent_hypothesis_id", "")).strip(), {}).get("summary", ""),
                limit=52,
            ),
            child_summary=_short_text(
                hypotheses_by_id.get(str(row.get("child_hypothesis_id", "")).strip(), {}).get("summary", ""),
                limit=52,
            ),
        )
        for row in branch_relations[-5:]
    ]
    lineage_items.reverse()

    timeline_items: list[TimelineItem] = []
    journal = EventJournal(research_dir / "events.jsonl")
    records = journal.read_records()
    interesting_events = {
        "manager_cycle_started",
        "frontier_synced",
        "experiment_started",
        "experiment_completed",
        "evidence_recorded",
        "claim_updated",
        "reproduction_requested",
        "role_failed",
        "session_failed",
    }
    for record in records[::-1]:
        event_name = str(record.get("event", "")).strip()
        if event_name not in interesting_events:
            continue
        detail = ""
        if event_name == "manager_cycle_started":
            detail = f"cycle {record.get('cycle', '?')}"
        elif event_name == "frontier_synced":
            detail = f"{record.get('frontier_items', 0)} runnable"
        elif event_name == "experiment_started":
            detail = f"run #{record.get('experiment_num', '?')} started"
        elif event_name == "experiment_completed":
            detail = f"run #{record.get('experiment_num', '?')} finished code={record.get('exit_code', '?')}"
        elif event_name == "evidence_recorded":
            detail = f"{record.get('evidence_created', 0)} evidence"
        elif event_name == "claim_updated":
            detail = f"{record.get('count', 0)} claim"
        elif event_name == "reproduction_requested":
            detail = f"{record.get('count', 0)} repro"
        elif event_name in {"role_failed", "session_failed"}:
            detail = f"code={record.get('exit_code', '?')}"

        timeline_items.append(
            TimelineItem(
                ts=str(record.get("ts", "")).strip(),
                event=event_name,
                phase=str(record.get("phase", "")).strip(),
                frontier_id=str(record.get("frontier_id", "")).strip(),
                execution_id=str(record.get("execution_id", "")).strip(),
                reason_code=str(record.get("reason_code", "")).strip(),
                detail=detail,
            )
        )
        if len(timeline_items) >= 6:
            break

    execution = ExecutionSummary(
        primary_metric=session.primary_metric,
        baseline_value=session.baseline_value,
        current_value=session.current_value,
        best_value=session.best_value,
        total=session.total,
        keep=session.keep,
        discard=session.discard,
        crash=session.crash,
        recent_results=rows[-8:],
    )

    return DashboardState(
        session=session,
        bootstrap=bootstrap,
        graph=graph,
        frontiers=frontiers,
        frontier_details=frontier_details,
        roles=roles,
        evidence=evidence_items,
        claims=claim_items,
        lineage=lineage_items,
        timeline=timeline_items,
        execution=execution,
        trace_banner=trace_banner,
    )
