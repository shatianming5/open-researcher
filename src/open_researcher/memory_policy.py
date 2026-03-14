"""History-driven retrieval, ranking, and policy helpers for research-v1 frontier ordering."""

from __future__ import annotations

import hashlib
import re

POLICY_STATES = {
    "neutral",
    "prefer_repro",
    "repeat_failure_risk",
    "duplicate_same_cycle",
    "crash_prone",
}
NEGATIVE_TRANSITIONS = {"downgrade", "reject"}
POSITIVE_TRANSITIONS = {"promote"}
OPEN_REPRO_STATUSES = {"approved", "running", "needs_repro"}
CANDIDATE_STATUSES = {"draft", "approved", "needs_repro"}
DUPLICATE_STATUSES = {"draft", "approved"}


def _normalize_text(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = sorted({token for token in text.split() if token})
    return " ".join(tokens)


def _safe_priority(value: object, default: int = 5) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 1)


def _policy_state(value: object) -> str:
    state = str(value or "").strip() or "neutral"
    if state not in POLICY_STATES:
        return "neutral"
    return state


def build_family_key(frontier_row: dict, hypothesis: dict, spec: dict) -> str:
    """Build a stable mechanism-family key from frontier semantics."""
    parts = [
        hypothesis.get("summary", ""),
        spec.get("summary", "") or frontier_row.get("description", ""),
        frontier_row.get("attribution_focus", "") or spec.get("attribution_focus", ""),
        frontier_row.get("expected_signal", "") or spec.get("expected_signal", ""),
    ]
    normalized = " ".join(part for part in (_normalize_text(value) for value in parts) if part)
    if not normalized:
        normalized = " ".join(
            part
            for part in (
                _normalize_text(frontier_row.get("hypothesis_id", "")),
                _normalize_text(frontier_row.get("experiment_spec_id", "")),
                _normalize_text(frontier_row.get("id", "")),
            )
            if part
        )
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"fam-{digest}"


def retrieve_history(
    graph: dict,
    memory: dict,
    family_key: str,
    *,
    exclude_frontier_id: str = "",
    limit: int = 5,
) -> dict:
    """Aggregate relevant history for a family from graph + memory."""
    history = {
        "strong_positive_count": 0,
        "negative_count": 0,
        "open_repro_count": 0,
        "crash_count": 0,
        "recent_matches": [],
    }
    if not family_key:
        return history

    frontier_by_id = {
        str(row.get("id", "")).strip(): row
        for row in graph.get("frontier", [])
        if isinstance(row, dict) and str(row.get("family_key", "")).strip() == family_key
    }
    graph_claim_ids: set[str] = set()

    for frontier_id, row in frontier_by_id.items():
        if frontier_id == exclude_frontier_id:
            continue
        status = str(row.get("status", "")).strip()
        claim_state = str(row.get("claim_state", "")).strip()
        if status in OPEN_REPRO_STATUSES and (bool(row.get("repro_required", False)) or claim_state == "needs_repro"):
            history["open_repro_count"] += 1
            history["recent_matches"].append(
                {
                    "kind": "frontier",
                    "frontier_id": frontier_id,
                    "outcome": "needs_repro",
                    "reason_code": str(row.get("review_reason_code", "")).strip()
                    or str(row.get("selection_reason_code", "")).strip()
                    or "unspecified",
                    "summary": str(row.get("description", "")).strip(),
                }
            )

    for row in graph.get("claim_updates", []):
        if not isinstance(row, dict):
            continue
        claim_id = str(row.get("id", "")).strip()
        frontier_id = str(row.get("frontier_id", "")).strip()
        if not claim_id or claim_id in graph_claim_ids or frontier_id == exclude_frontier_id:
            continue
        frontier = frontier_by_id.get(frontier_id)
        if frontier is None:
            continue
        graph_claim_ids.add(claim_id)
        transition = str(row.get("transition", "")).strip()
        if transition in POSITIVE_TRANSITIONS:
            history["strong_positive_count"] += 1
        elif transition in NEGATIVE_TRANSITIONS:
            history["negative_count"] += 1
        reason_code = str(row.get("reason_code", "")).strip()
        if "crash" in reason_code:
            history["crash_count"] += 1
        history["recent_matches"].append(
            {
                "kind": "claim",
                "frontier_id": frontier_id,
                "outcome": transition or "observed",
                "reason_code": reason_code or "unspecified",
                "summary": str(frontier.get("description", "")).strip(),
            }
        )

    for row in memory.get("ideation_memory", []):
        if not isinstance(row, dict):
            continue
        if str(row.get("family_key", "")).strip() != family_key:
            continue
        claim_id = str(row.get("source_claim_update", "")).strip()
        frontier_id = str(row.get("frontier_id", "")).strip()
        if claim_id and claim_id in graph_claim_ids:
            continue
        if frontier_id and frontier_id == exclude_frontier_id:
            continue
        outcome = str(row.get("outcome", "")).strip()
        if outcome in POSITIVE_TRANSITIONS:
            history["strong_positive_count"] += 1
        elif outcome in NEGATIVE_TRANSITIONS:
            history["negative_count"] += 1
        reason_code = str(row.get("reason_code", "")).strip()
        if "crash" in reason_code:
            history["crash_count"] += 1
        history["recent_matches"].append(
            {
                "kind": "memory",
                "frontier_id": frontier_id,
                "outcome": outcome or "observed",
                "reason_code": reason_code or "unspecified",
                "summary": str(row.get("summary", "")).strip(),
            }
        )

    history["recent_matches"] = history["recent_matches"][-limit:]
    return history


def apply_history_policy(frontier_rows: list[dict], graph: dict, memory: dict) -> list[dict]:
    """Annotate frontier rows with family keys and runtime policy signals."""
    hypotheses = {
        str(row.get("id", "")).strip(): row for row in graph.get("hypotheses", []) if isinstance(row, dict)
    }
    specs = {str(row.get("id", "")).strip(): row for row in graph.get("experiment_specs", []) if isinstance(row, dict)}
    updated = [dict(row) for row in frontier_rows if isinstance(row, dict)]

    for row in updated:
        manager_priority = _safe_priority(row.get("manager_priority", row.get("priority", 5)), default=5)
        family_key = str(row.get("family_key", "")).strip() or build_family_key(
            row,
            hypotheses.get(str(row.get("hypothesis_id", "")).strip(), {}),
            specs.get(str(row.get("experiment_spec_id", "")).strip(), {}),
        )
        row["family_key"] = family_key
        row["manager_priority"] = manager_priority
        row["runtime_priority"] = manager_priority
        row["policy_state"] = "neutral"
        row["policy_reason"] = ""

    working_graph = dict(graph)
    working_graph["frontier"] = updated

    for row in updated:
        status = str(row.get("status", "")).strip()
        if status not in CANDIDATE_STATUSES:
            continue
        history = retrieve_history(
            working_graph,
            memory,
            str(row.get("family_key", "")).strip(),
            exclude_frontier_id=str(row.get("id", "")).strip(),
        )
        manager_priority = _safe_priority(row.get("manager_priority", row.get("priority", 5)), default=5)
        if history["open_repro_count"] > 0 and not bool(row.get("repro_required", False)):
            row["runtime_priority"] = manager_priority + 2
            row["policy_state"] = "prefer_repro"
            row["policy_reason"] = "existing repro pending"
        elif history["negative_count"] >= 2 and history["strong_positive_count"] == 0:
            row["runtime_priority"] = manager_priority + 3
            row["policy_state"] = "repeat_failure_risk"
            row["policy_reason"] = f"family has {history['negative_count']} negative outcomes"
        elif history.get("crash_count", 0) >= 2 and history.get("strong_positive_count", 0) == 0:
            row["runtime_priority"] = manager_priority + 4
            row["policy_state"] = "crash_prone"
            row["policy_reason"] = f"family has {history['crash_count']} crash outcomes"

    grouped: dict[str, list[dict]] = {}
    for row in updated:
        status = str(row.get("status", "")).strip()
        family_key = str(row.get("family_key", "")).strip()
        if family_key and status in DUPLICATE_STATUSES:
            grouped.setdefault(family_key, []).append(row)

    for family_rows in grouped.values():
        if len(family_rows) <= 1:
            continue
        family_rows.sort(
            key=lambda item: (
                _safe_priority(item.get("runtime_priority", item.get("manager_priority", 5)), default=5),
                _safe_priority(item.get("manager_priority", item.get("priority", 5)), default=5),
                str(item.get("id", "")),
            )
        )
        keeper = family_rows[0]
        keeper_priority = _safe_priority(keeper.get("runtime_priority", keeper.get("manager_priority", 5)), default=5)
        for row in family_rows[1:]:
            duplicate_priority = max(
                _safe_priority(row.get("runtime_priority", row.get("manager_priority", 5)), default=5),
                keeper_priority + 4,
            )
            row["runtime_priority"] = duplicate_priority
            if _policy_state(row.get("policy_state")) == "neutral":
                row["policy_state"] = "duplicate_same_cycle"
                row["policy_reason"] = f"same-cycle duplicate family; keeping {keeper.get('id', '')} first"

    for row in updated:
        row["policy_state"] = _policy_state(row.get("policy_state"))
        row["policy_reason"] = str(row.get("policy_reason", "")).strip()
        row["manager_priority"] = _safe_priority(row.get("manager_priority", row.get("priority", 5)), default=5)
        row["runtime_priority"] = _safe_priority(row.get("runtime_priority", row.get("manager_priority", 5)), default=5)

    return updated
