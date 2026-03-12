"""Canonical hypothesis/evidence graph state for research-v1 runs."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from filelock import FileLock

from open_researcher.memory_policy import apply_history_policy as apply_frontier_history_policy
from open_researcher.memory_policy import build_family_key
from open_researcher.resource_scheduler import (
    is_backfill_candidate,
    normalize_execution_shape,
    normalize_expected_duration_minutes,
    normalize_resource_request,
    utility_density,
)
from open_researcher.storage import locked_read_json, locked_update_json

FRONTIER_STATUSES = {
    "draft",
    "approved",
    "running",
    "needs_post_review",
    "needs_repro",
    "rejected",
    "archived",
}
CLAIM_STATES = {
    "candidate",
    "under_review",
    "promoted",
    "downgraded",
    "rejected",
    "needs_repro",
}
EVIDENCE_RELIABILITY = {"pending_critic", "strong", "weak", "invalid", "needs_repro"}
CLAIM_TRANSITIONS = {"promote", "downgrade", "reject", "needs_repro"}
BRANCH_RELATIONS = {"refines", "combines", "contradicts", "reproduces"}
SELECTION_REASON_CODES = {
    "unspecified",
    "initial_frontier",
    "manager_refresh",
    "breadth_exploration",
    "exploit_positive_signal",
    "surprising_result_followup",
    "reproduction_requested",
    "cost_control",
}
REVIEW_REASON_CODES = {
    "unspecified",
    "approved_for_execution",
    "no_eval_plan",
    "multi_axis_change",
    "too_broad",
    "rollback_risk",
    "weak_attribution",
    "needs_reproduction",
    "strong_evidence",
    "weak_evidence",
    "invalid_result",
    "confounded_signal",
    "contradictory_signal",
    "surprising_improvement",
}
EVIDENCE_REASON_CODES = {
    "unspecified",
    "result_observed",
    "benchmark_delta",
    "test_improvement",
    "test_regression",
    "performance_signal",
    "reproduction_run",
    "confounded_measurement",
}
CLAIM_REASON_CODES = {
    "unspecified",
    "supported_by_strong_evidence",
    "supported_but_needs_repro",
    "confounded_signal",
    "contradicted_by_result",
    "regression_detected",
    "reproduction_requested",
    "noisy_measurement",
}
POLICY_STATES = {
    "neutral",
    "prefer_repro",
    "repeat_failure_risk",
    "duplicate_same_cycle",
}


def _default_graph() -> dict:
    return {
        "version": "research-v1",
        "repo_profile": {
            "profile_key": "general_code",
            "task_family": "general_code",
            "primary_metric": "",
            "direction": "",
            "source": "bootstrap",
            "resource_capabilities": {},
        },
        "hypotheses": [],
        "experiment_specs": [],
        "evidence": [],
        "claim_updates": [],
        "branch_relations": [],
        "frontier": [],
        "counters": {
            "hypothesis": 0,
            "experiment_spec": 0,
            "evidence": 0,
            "claim_update": 0,
            "branch_relation": 0,
            "frontier": 0,
            "idea": 0,
            "execution": 0,
        },
    }


class ResearchGraphStore:
    """Read/write the research-v1 state with atomic updates."""

    EXECUTABLE_FRONTIER_STATUSES = {"approved", "running", "needs_repro"}
    PREFLIGHT_FRONTIER_STATUSES = {"draft"}
    POST_REVIEW_FRONTIER_STATUSES = {"needs_post_review"}

    def __init__(self, path: Path):
        self.path = path
        self._lock = FileLock(str(path) + ".lock")

    def _normalize(self, payload: object) -> dict:
        data = payload if isinstance(payload, dict) else _default_graph()
        normalized = dict(_default_graph())
        normalized.update(data)
        normalized["version"] = "research-v1"
        repo_profile = normalized.get("repo_profile")
        if not isinstance(repo_profile, dict):
            repo_profile = {}
        merged_profile = dict(_default_graph()["repo_profile"])
        merged_profile.update(repo_profile)
        capabilities = merged_profile.get("resource_capabilities")
        merged_profile["resource_capabilities"] = capabilities if isinstance(capabilities, dict) else {}
        normalized["repo_profile"] = merged_profile
        counters = normalized.get("counters")
        if not isinstance(counters, dict):
            counters = {}
        merged_counters = dict(_default_graph()["counters"])
        for key, value in counters.items():
            try:
                merged_counters[key] = max(int(value), 0)
            except (TypeError, ValueError):
                continue
        normalized["counters"] = merged_counters
        hypotheses = normalized.get("hypotheses")
        experiment_specs = normalized.get("experiment_specs")
        evidence = normalized.get("evidence")
        claim_updates = normalized.get("claim_updates")
        branch_relations = normalized.get("branch_relations")
        frontier = normalized.get("frontier")
        normalized["hypotheses"] = self._normalize_hypotheses(hypotheses if isinstance(hypotheses, list) else [])
        normalized["experiment_specs"] = self._normalize_experiment_specs(
            experiment_specs if isinstance(experiment_specs, list) else [],
            normalized["hypotheses"],
        )
        normalized["frontier"] = self._normalize_frontier(
            frontier if isinstance(frontier, list) else [],
            normalized["counters"],
            normalized["hypotheses"],
            normalized["experiment_specs"],
        )
        normalized["evidence"] = self._normalize_evidence(
            evidence if isinstance(evidence, list) else [],
            normalized["frontier"],
            normalized["hypotheses"],
            normalized["experiment_specs"],
        )
        normalized["claim_updates"] = self._normalize_claim_updates(
            claim_updates if isinstance(claim_updates, list) else [],
            normalized["frontier"],
            normalized["hypotheses"],
            normalized["experiment_specs"],
        )
        normalized["branch_relations"] = self._normalize_branch_relations(
            branch_relations if isinstance(branch_relations, list) else []
        )
        self._attach_latest_refs(normalized)
        return normalized

    def _normalize_hypotheses(self, rows: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            hyp_id = str(row.get("id", "")).strip()
            if not hyp_id or hyp_id in seen:
                continue
            seen.add(hyp_id)
            normalized.append(
                {
                    "id": hyp_id,
                    "summary": str(row.get("summary", "") or row.get("description", "")).strip(),
                    "rationale": str(row.get("rationale", "")).strip(),
                    "status": str(row.get("status", "active")).strip() or "active",
                    "parent_hypothesis_ids": self._string_list(row.get("parent_hypothesis_ids")),
                    "expected_evidence": self._string_list(row.get("expected_evidence")),
                    "confidence": str(row.get("confidence", "pending")).strip() or "pending",
                    "tags": self._string_list(row.get("tags")),
                }
            )
        return normalized

    def _normalize_experiment_specs(self, rows: list[dict], hypotheses: list[dict]) -> list[dict]:
        known_hypotheses = {str(row.get("id", "")).strip() for row in hypotheses}
        normalized: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            spec_id = str(row.get("id", "")).strip()
            hypothesis_id = str(row.get("hypothesis_id", "")).strip()
            if not spec_id or spec_id in seen or (hypothesis_id and hypothesis_id not in known_hypotheses):
                continue
            seen.add(spec_id)
            normalized.append(
                {
                    "id": spec_id,
                    "hypothesis_id": hypothesis_id,
                    "summary": str(row.get("summary", "") or row.get("description", "")).strip(),
                    "change_plan": str(row.get("change_plan", "")).strip(),
                    "evaluation_plan": str(row.get("evaluation_plan", "")).strip(),
                    "attribution_focus": str(row.get("attribution_focus", "")).strip(),
                    "expected_signal": str(row.get("expected_signal", "")).strip(),
                    "risk_level": str(row.get("risk_level", "medium")).strip() or "medium",
                    "resource_request": normalize_resource_request(
                        row.get("resource_request"),
                        default_gpu_mem_mb=0,
                        fallback_gpu_hint=row.get("gpu_hint"),
                    ),
                    "execution_shape": normalize_execution_shape(row.get("execution_shape")),
                    "expected_duration_minutes": normalize_expected_duration_minutes(
                        row.get("expected_duration_minutes")
                    ),
                    "resource_profile": str(row.get("resource_profile", "")).strip(),
                    "workload_label": str(row.get("workload_label", "")).strip(),
                    "anchor_role": self._normalize_anchor_role(row.get("anchor_role")),
                }
            )
        return normalized

    def _normalize_evidence(
        self,
        rows: list[dict],
        frontier: list[dict],
        hypotheses: list[dict],
        experiment_specs: list[dict],
    ) -> list[dict]:
        frontier_by_id = {str(row.get("id", "")).strip(): row for row in frontier if isinstance(row, dict)}
        known_hypotheses = {str(row.get("id", "")).strip() for row in hypotheses}
        known_specs = {str(row.get("id", "")).strip() for row in experiment_specs}
        normalized: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            evidence_id = str(row.get("id", "")).strip()
            if not evidence_id or evidence_id in seen:
                continue
            frontier_id = str(row.get("frontier_id", "")).strip()
            hypothesis_id = str(row.get("hypothesis_id", "")).strip()
            spec_id = str(row.get("experiment_spec_id", "")).strip()
            frontier_row = frontier_by_id.get(frontier_id)
            if not frontier_row:
                continue
            if hypothesis_id and hypothesis_id not in known_hypotheses:
                continue
            if spec_id and spec_id not in known_specs:
                continue
            if hypothesis_id and hypothesis_id != str(frontier_row.get("hypothesis_id", "")).strip():
                continue
            if spec_id and spec_id != str(frontier_row.get("experiment_spec_id", "")).strip():
                continue
            seen.add(evidence_id)
            reliability = str(row.get("reliability", "pending_critic")).strip() or "pending_critic"
            if reliability not in EVIDENCE_RELIABILITY:
                reliability = "pending_critic"
            normalized.append(
                {
                    "id": evidence_id,
                    "frontier_id": frontier_id,
                    "idea_id": str(row.get("idea_id", "")).strip(),
                    "execution_id": str(row.get("execution_id", "")).strip(),
                    "hypothesis_id": hypothesis_id or str(frontier_row.get("hypothesis_id", "")).strip(),
                    "experiment_spec_id": spec_id or str(frontier_row.get("experiment_spec_id", "")).strip(),
                    "kind": str(row.get("kind", "result_row")).strip() or "result_row",
                    "primary_metric": str(row.get("primary_metric", "")).strip(),
                    "metric_value": row.get("metric_value"),
                    "status": str(row.get("status", "")).strip(),
                    "description": str(row.get("description", "")).strip(),
                    "timestamp": str(row.get("timestamp", "")).strip(),
                    "commit": str(row.get("commit", "")).strip(),
                    "reliability": reliability,
                    "reason_code": self._normalize_reason_code(
                        row.get("reason_code"),
                        allowed=EVIDENCE_REASON_CODES,
                    ),
                    "result_signature": str(row.get("result_signature", "")).strip(),
                    "resource_observation": self._normalize_resource_observation(row.get("resource_observation")),
                }
            )
        return normalized

    def _normalize_claim_updates(
        self,
        rows: list[dict],
        frontier: list[dict],
        hypotheses: list[dict],
        experiment_specs: list[dict],
    ) -> list[dict]:
        frontier_by_id = {str(row.get("id", "")).strip(): row for row in frontier if isinstance(row, dict)}
        known_hypotheses = {str(row.get("id", "")).strip() for row in hypotheses}
        known_specs = {str(row.get("id", "")).strip() for row in experiment_specs}
        normalized: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            update_id = str(row.get("id", "")).strip()
            if not update_id or update_id in seen:
                continue
            frontier_id = str(row.get("frontier_id", "")).strip()
            hypothesis_id = str(row.get("hypothesis_id", "")).strip()
            spec_id = str(row.get("experiment_spec_id", "")).strip()
            if not hypothesis_id or hypothesis_id not in known_hypotheses:
                continue
            frontier_row = frontier_by_id.get(frontier_id)
            if not frontier_row:
                matching_frontier = [
                    item
                    for item in frontier
                    if isinstance(item, dict) and str(item.get("hypothesis_id", "")).strip() == hypothesis_id
                ]
                if len(matching_frontier) != 1:
                    continue
                frontier_row = matching_frontier[0]
                frontier_id = str(frontier_row.get("id", "")).strip()
                if not spec_id:
                    spec_id = str(frontier_row.get("experiment_spec_id", "")).strip()
            if spec_id and spec_id not in known_specs:
                continue
            if hypothesis_id != str(frontier_row.get("hypothesis_id", "")).strip():
                continue
            if spec_id and spec_id != str(frontier_row.get("experiment_spec_id", "")).strip():
                continue
            seen.add(update_id)
            transition = str(row.get("transition", "needs_repro")).strip() or "needs_repro"
            if transition not in CLAIM_TRANSITIONS:
                transition = "needs_repro"
            normalized.append(
                {
                    "id": update_id,
                    "frontier_id": frontier_id,
                    "hypothesis_id": hypothesis_id,
                    "experiment_spec_id": spec_id or str(frontier_row.get("experiment_spec_id", "")).strip(),
                    "execution_id": str(row.get("execution_id", "")).strip(),
                    "transition": transition,
                    "confidence": str(row.get("confidence", "pending")).strip() or "pending",
                    "reason": str(row.get("reason", "")).strip(),
                    "reason_code": self._normalize_reason_code(
                        row.get("reason_code"),
                        allowed=CLAIM_REASON_CODES,
                    ),
                    "evidence_ids": self._string_list(row.get("evidence_ids")),
                }
            )
        return normalized

    def _normalize_branch_relations(self, rows: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            relation_id = str(row.get("id", "")).strip()
            if not relation_id or relation_id in seen:
                continue
            seen.add(relation_id)
            relation = str(row.get("relation", "refines")).strip() or "refines"
            if relation not in BRANCH_RELATIONS:
                relation = "refines"
            normalized.append(
                {
                    "id": relation_id,
                    "parent_hypothesis_id": str(row.get("parent_hypothesis_id", "")).strip(),
                    "child_hypothesis_id": str(row.get("child_hypothesis_id", "")).strip(),
                    "relation": relation,
                }
            )
        return normalized

    def _normalize_frontier(
        self,
        rows: list[dict],
        counters: dict,
        hypotheses: list[dict],
        experiment_specs: list[dict],
    ) -> list[dict]:
        known_hypotheses = {str(row.get("id", "")).strip() for row in hypotheses}
        hypothesis_by_id = {str(row.get("id", "")).strip(): row for row in hypotheses if isinstance(row, dict)}
        known_specs = {str(row.get("id", "")).strip() for row in experiment_specs}
        spec_by_id = {str(row.get("id", "")).strip(): row for row in experiment_specs if isinstance(row, dict)}
        normalized: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            hypothesis_id = str(row.get("hypothesis_id", "")).strip()
            spec_id = str(row.get("experiment_spec_id", "")).strip()
            if not hypothesis_id or not spec_id:
                continue
            if hypothesis_id not in known_hypotheses or spec_id not in known_specs:
                continue
            frontier_id = str(row.get("id", "")).strip()
            if not frontier_id:
                counters["frontier"] = max(int(counters.get("frontier", 0)), 0) + 1
                frontier_id = f"frontier-{counters['frontier']:03d}"
            if frontier_id in seen:
                continue
            seen.add(frontier_id)
            status = str(row.get("status", "draft")).strip() or "draft"
            if status not in FRONTIER_STATUSES:
                status = "draft"
            claim_state = str(row.get("claim_state", "candidate")).strip() or "candidate"
            if claim_state not in CLAIM_STATES:
                claim_state = "candidate"
            spec_row = spec_by_id.get(spec_id, {})
            hypothesis_row = hypothesis_by_id.get(hypothesis_id, {})
            priority = self._normalize_priority(row.get("priority", row.get("manager_priority", 5)))
            manager_priority = self._normalize_priority(row.get("manager_priority", priority), default=priority)
            runtime_priority = self._normalize_priority(
                row.get("runtime_priority", manager_priority),
                default=manager_priority,
            )
            scores = self._normalize_scores(row.get("scores"))
            family_key = str(row.get("family_key", "")).strip() or build_family_key(
                row,
                hypothesis_row,
                spec_row,
            )
            resource_request = normalize_resource_request(
                row.get("resource_request", spec_row.get("resource_request")),
                default_gpu_mem_mb=0,
                fallback_gpu_hint=row.get("gpu_hint"),
            )
            expected_duration_minutes = normalize_expected_duration_minutes(
                row.get("expected_duration_minutes", spec_row.get("expected_duration_minutes"))
            )
            normalized.append(
                {
                    "id": frontier_id,
                    "idea_id": str(row.get("idea_id", "")).strip(),
                    "hypothesis_id": hypothesis_id,
                    "experiment_spec_id": spec_id,
                    "branch_id": str(row.get("branch_id", "")).strip(),
                    "active_execution_id": str(row.get("active_execution_id", "")).strip(),
                    "last_execution_id": str(row.get("last_execution_id", "")).strip(),
                    "last_evidence_id": str(row.get("last_evidence_id", "")).strip(),
                    "last_claim_update_id": str(row.get("last_claim_update_id", "")).strip(),
                    "family_key": family_key,
                    "description": str(
                        row.get("description", "") or row.get("summary", "") or spec_row.get("summary", "")
                    ).strip(),
                    "priority": priority,
                    "manager_priority": manager_priority,
                    "runtime_priority": runtime_priority,
                    "status": status,
                    "claim_state": claim_state,
                    "policy_state": self._normalize_policy_state(row.get("policy_state")),
                    "policy_reason": str(row.get("policy_reason", "")).strip(),
                    "source": str(row.get("source", "graph")).strip() or "graph",
                    "category": str(row.get("category", "graph")).strip() or "graph",
                    "gpu_hint": row.get("gpu_hint", "auto"),
                    "repro_required": bool(row.get("repro_required", False)),
                    "result": row.get("result"),
                    "result_signature": str(row.get("result_signature", "")).strip(),
                    "evidence_id": str(row.get("evidence_id", "")).strip(),
                    "created_at": str(row.get("created_at", "")).strip(),
                    "updated_at": str(row.get("updated_at", "")).strip(),
                    "started_at": str(row.get("started_at", "")).strip(),
                    "finished_at": str(row.get("finished_at", "")).strip(),
                    "terminal_status": str(row.get("terminal_status", "")).strip(),
                    "primary_metric": str(row.get("primary_metric", "")).strip(),
                    "metric_value": row.get("metric_value"),
                    "review_reason": str(row.get("review_reason", "")).strip(),
                    "selection_reason_code": self._normalize_reason_code(
                        row.get("selection_reason_code"),
                        allowed=SELECTION_REASON_CODES,
                        default="manager_refresh",
                    ),
                    "review_reason_code": self._normalize_reason_code(
                        row.get("review_reason_code"),
                        allowed=REVIEW_REASON_CODES,
                    ),
                    "attribution_focus": str(
                        row.get("attribution_focus", "") or spec_row.get("attribution_focus", "")
                    ).strip(),
                    "scores": scores,
                    "resource_request": resource_request,
                    "execution_shape": normalize_execution_shape(
                        row.get("execution_shape", spec_row.get("execution_shape"))
                    ),
                    "expected_duration_minutes": expected_duration_minutes,
                    "resource_profile": str(
                        row.get("resource_profile", "") or spec_row.get("resource_profile", "")
                    ).strip(),
                    "workload_label": str(row.get("workload_label", "") or spec_row.get("workload_label", "")).strip(),
                    "anchor_role": self._normalize_anchor_role(row.get("anchor_role", spec_row.get("anchor_role"))),
                    "utility_density": utility_density(
                        scores,
                        resource_request=resource_request,
                        expected_duration_minutes=expected_duration_minutes,
                    ),
                    "backfill_candidate": is_backfill_candidate(
                        resource_request=resource_request,
                        expected_duration_minutes=expected_duration_minutes,
                        threshold_minutes=30,
                    ),
                    "resource_observation": self._normalize_resource_observation(row.get("resource_observation")),
                }
            )
        return normalized

    def _frontier_sort_key(self, item: dict) -> tuple:
        return (
            0 if not bool(item.get("backfill_candidate", False)) else 1,
            -float(item.get("utility_density", 0.0) or 0.0),
            int(item.get("runtime_priority", item.get("priority", 9999)) or 9999),
            int(item.get("manager_priority", item.get("priority", 9999)) or 9999),
            normalize_expected_duration_minutes(item.get("expected_duration_minutes")),
            str(item.get("id", "")),
        )

    def _normalize_priority(self, value, *, default: int = 5) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(parsed, 1)

    def _normalize_scores(self, value) -> dict:
        if not isinstance(value, dict):
            return {}
        normalized = {}
        for key in ["expected_value", "attribution", "cost", "diversity"]:
            raw = value.get(key)
            try:
                normalized[key] = max(min(int(raw), 5), 1)
            except (TypeError, ValueError):
                continue
        return normalized

    def _normalize_resource_observation(self, value) -> dict:
        if not isinstance(value, dict):
            return {}
        normalized: dict = {}
        if "duration_minutes" in value:
            normalized["duration_minutes"] = normalize_expected_duration_minutes(value.get("duration_minutes"))
        try:
            if "gpu_mem_reserved_mb" in value:
                normalized["gpu_mem_reserved_mb"] = max(int(value.get("gpu_mem_reserved_mb") or 0), 0)
            if "gpu_count_allocated" in value:
                normalized["gpu_count_allocated"] = max(int(value.get("gpu_count_allocated") or 0), 0)
        except (TypeError, ValueError):
            pass
        if isinstance(value.get("devices"), list):
            devices = []
            for item in value.get("devices", []):
                if not isinstance(item, dict):
                    continue
                host = str(item.get("host", "")).strip()
                try:
                    device = int(item.get("device"))
                except (TypeError, ValueError):
                    continue
                if host:
                    devices.append({"host": host, "device": device})
            if devices:
                normalized["devices"] = devices
        if "resource_request" in value:
            normalized["resource_request"] = normalize_resource_request(value.get("resource_request"))
        if "execution_shape" in value:
            normalized["execution_shape"] = normalize_execution_shape(value.get("execution_shape"))
        if "workload_label" in value:
            normalized["workload_label"] = str(value.get("workload_label", "")).strip()
        if "resource_profile" in value:
            normalized["resource_profile"] = str(value.get("resource_profile", "")).strip()
        return normalized

    def _normalize_anchor_role(self, value) -> str:
        role = str(value or "").strip()
        return "anchor" if role == "anchor" else ""

    def _normalize_policy_state(self, value) -> str:
        state = str(value or "").strip() or "neutral"
        if state not in POLICY_STATES:
            return "neutral"
        return state

    def _string_list(self, value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _normalize_reason_code(self, value, *, allowed: set[str], default: str = "unspecified") -> str:
        reason_code = str(value or "").strip() or default
        if reason_code not in allowed:
            return default
        return reason_code

    def _find_hypothesis(self, hypotheses: list[dict], hypothesis_id: str) -> dict:
        for row in hypotheses:
            if str(row.get("id", "")).strip() == hypothesis_id:
                return row
        return {}

    def _find_experiment_spec(self, specs: list[dict], spec_id: str) -> dict:
        for row in specs:
            if str(row.get("id", "")).strip() == spec_id:
                return row
        return {}

    def _frontier_trace(self, row: dict) -> dict:
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
            "family_key": str(row.get("family_key", "")).strip(),
            "manager_priority": self._normalize_priority(row.get("manager_priority", row.get("priority", 5))),
            "runtime_priority": self._normalize_priority(
                row.get("runtime_priority", row.get("manager_priority", row.get("priority", 5)))
            ),
            "policy_state": self._normalize_policy_state(row.get("policy_state")),
            "policy_reason": str(row.get("policy_reason", "")).strip(),
        }

    def _evidence_trace(self, row: dict) -> dict:
        return {
            "evidence_id": str(row.get("id", "")).strip(),
            "frontier_id": str(row.get("frontier_id", "")).strip(),
            "idea_id": str(row.get("idea_id", "")).strip(),
            "execution_id": str(row.get("execution_id", "")).strip(),
            "hypothesis_id": str(row.get("hypothesis_id", "")).strip(),
            "experiment_spec_id": str(row.get("experiment_spec_id", "")).strip(),
            "reliability": str(row.get("reliability", "")).strip(),
            "reason_code": str(row.get("reason_code", "")).strip(),
        }

    def _claim_trace(self, row: dict) -> dict:
        return {
            "claim_update_id": str(row.get("id", "")).strip(),
            "frontier_id": str(row.get("frontier_id", "")).strip(),
            "execution_id": str(row.get("execution_id", "")).strip(),
            "hypothesis_id": str(row.get("hypothesis_id", "")).strip(),
            "experiment_spec_id": str(row.get("experiment_spec_id", "")).strip(),
            "transition": str(row.get("transition", "")).strip(),
            "confidence": str(row.get("confidence", "")).strip(),
            "reason_code": str(row.get("reason_code", "")).strip(),
        }

    def _next_execution_id(self, counters: dict) -> str:
        counters["execution"] = max(int(counters.get("execution", 0)), 0) + 1
        return f"exec-{counters['execution']:03d}"

    def _attach_latest_refs(self, graph: dict) -> None:
        latest_evidence_by_frontier: dict[str, str] = {}
        latest_claim_by_frontier: dict[str, str] = {}

        for row in graph.get("evidence", []):
            if not isinstance(row, dict):
                continue
            frontier_id = str(row.get("frontier_id", "")).strip()
            evidence_id = str(row.get("id", "")).strip()
            if frontier_id and evidence_id:
                latest_evidence_by_frontier[frontier_id] = evidence_id

        for row in graph.get("claim_updates", []):
            if not isinstance(row, dict):
                continue
            frontier_id = str(row.get("frontier_id", "")).strip()
            claim_id = str(row.get("id", "")).strip()
            if frontier_id and claim_id:
                latest_claim_by_frontier[frontier_id] = claim_id

        for row in graph.get("frontier", []):
            if not isinstance(row, dict):
                continue
            frontier_id = str(row.get("id", "")).strip()
            if not frontier_id:
                continue
            if not str(row.get("last_evidence_id", "")).strip():
                row["last_evidence_id"] = latest_evidence_by_frontier.get(frontier_id, "")
            if not str(row.get("last_claim_update_id", "")).strip():
                row["last_claim_update_id"] = latest_claim_by_frontier.get(frontier_id, "")

    def ensure_exists(self) -> None:
        def _do(data):
            normalized = self._normalize(data)
            data.clear()
            data.update(normalized)

        locked_update_json(self.path, self._lock, _do, default=_default_graph)

    def read(self) -> dict:
        data = locked_read_json(self.path, self._lock, default=_default_graph)
        return self._normalize(data)

    def update_repo_profile(
        self,
        *,
        primary_metric: str,
        direction: str,
    ) -> dict:
        def _do(data):
            normalized = self._normalize(data)
            normalized["repo_profile"]["primary_metric"] = primary_metric or ""
            normalized["repo_profile"]["direction"] = direction or ""
            data.clear()
            data.update(normalized)
            return copy.deepcopy(normalized["repo_profile"])

        _data, result = locked_update_json(self.path, self._lock, _do, default=_default_graph)
        return result

    def pending_frontier(self, statuses: set[str] | None = None, *, max_items: int | None = None) -> list[dict]:
        wanted = statuses or self.EXECUTABLE_FRONTIER_STATUSES
        data = self.read()
        rows = [item for item in data["frontier"] if str(item.get("status", "")) in wanted]
        rows.sort(key=self._frontier_sort_key)
        if max_items is not None and max_items > 0:
            return rows[:max_items]
        return rows

    def has_frontier_status(self, statuses: set[str], *, max_items: int | None = None) -> bool:
        return bool(self.pending_frontier(statuses, max_items=max_items))

    def has_executable_frontier(self, *, max_items: int | None = None) -> bool:
        return self.has_frontier_status(self.EXECUTABLE_FRONTIER_STATUSES, max_items=max_items)

    def sync_idea_pool(self, pool_path: Path, *, max_items: int | None = None) -> dict:
        """Project executable frontier items into compatibility idea_pool.json."""

        def _do(data):
            normalized = self._normalize(data)
            ideas: list[dict] = []
            trace_items: list[dict] = []
            projected = [
                item
                for item in normalized["frontier"]
                if str(item.get("status", "")).strip() in self.EXECUTABLE_FRONTIER_STATUSES
            ]
            projected.sort(key=self._frontier_sort_key)
            if max_items is not None and max_items > 0:
                projected = projected[:max_items]

            for item in projected:
                status = str(item.get("status", "")).strip()
                hypothesis = self._find_hypothesis(
                    normalized["hypotheses"],
                    str(item.get("hypothesis_id", "")).strip(),
                )
                spec = self._find_experiment_spec(
                    normalized["experiment_specs"],
                    str(item.get("experiment_spec_id", "")).strip(),
                )
                idea_id = str(item.get("idea_id", "")).strip()
                if not idea_id:
                    normalized["counters"]["idea"] += 1
                    idea_id = f"idea-{normalized['counters']['idea']:03d}"
                    item["idea_id"] = idea_id
                execution_id = str(item.get("active_execution_id", "")).strip()
                if not execution_id:
                    execution_id = self._next_execution_id(normalized["counters"])
                    item["active_execution_id"] = execution_id
                idea_status = "running" if status == "running" else "pending"
                manager_priority = int(item.get("manager_priority", item.get("priority", 5)) or 5)
                runtime_priority = int(item.get("runtime_priority", manager_priority) or manager_priority)
                ideas.append(
                    {
                        "id": idea_id,
                        "frontier_id": str(item.get("id", "")).strip(),
                        "execution_id": execution_id,
                        "description": str(item.get("description", "")).strip() or str(item.get("summary", "")).strip(),
                        "source": str(item.get("source", "graph")).strip() or "graph",
                        "category": str(item.get("category", "graph")).strip() or "graph",
                        "priority": runtime_priority,
                        "manager_priority": manager_priority,
                        "runtime_priority": runtime_priority,
                        "status": idea_status,
                        "gpu_hint": item.get("gpu_hint", "auto"),
                        "result": item.get("result"),
                        "created_at": item.get("created_at") or item.get("updated_at") or "",
                        "hypothesis_id": str(item.get("hypothesis_id", "")).strip(),
                        "experiment_spec_id": str(item.get("experiment_spec_id", "")).strip(),
                        "branch_id": str(item.get("branch_id", "")).strip(),
                        "family_key": str(item.get("family_key", "")).strip(),
                        "claim_state": str(item.get("claim_state", "candidate")).strip() or "candidate",
                        "repro_required": bool(item.get("repro_required", False)),
                        "policy_state": self._normalize_policy_state(item.get("policy_state")),
                        "policy_reason": str(item.get("policy_reason", "")).strip(),
                        "review_reason": str(item.get("review_reason", "")).strip(),
                        "attribution_focus": str(item.get("attribution_focus", "")).strip()
                        or str(spec.get("attribution_focus", "")).strip(),
                        "scores": item.get("scores", {}),
                        "resource_request": item.get("resource_request", {}),
                        "execution_shape": item.get("execution_shape", {}),
                        "expected_duration_minutes": item.get("expected_duration_minutes", 60),
                        "resource_profile": str(item.get("resource_profile", "")).strip(),
                        "workload_label": str(item.get("workload_label", "")).strip(),
                        "anchor_role": self._normalize_anchor_role(item.get("anchor_role")),
                        "utility_density": float(item.get("utility_density", 0.0) or 0.0),
                        "backfill_candidate": bool(item.get("backfill_candidate", False)),
                        "resource_observation": item.get("resource_observation", {}),
                        "protocol": "research-v1",
                        "hypothesis_summary": str(hypothesis.get("summary", "")).strip(),
                        "hypothesis_rationale": str(hypothesis.get("rationale", "")).strip(),
                        "expected_evidence": hypothesis.get("expected_evidence", []),
                        "spec_summary": str(spec.get("summary", "")).strip(),
                        "change_plan": str(spec.get("change_plan", "")).strip(),
                        "evaluation_plan": str(spec.get("evaluation_plan", "")).strip(),
                        "expected_signal": str(spec.get("expected_signal", "")).strip(),
                        "risk_level": str(spec.get("risk_level", "")).strip(),
                        "selection_reason_code": str(item.get("selection_reason_code", "")).strip()
                        or "manager_refresh",
                        "review_reason_code": str(item.get("review_reason_code", "")).strip() or "unspecified",
                    }
                )
                trace_items.append(self._frontier_trace(item))
            ideas.sort(key=self._frontier_sort_key)
            data.clear()
            data.update(normalized)
            return {"ideas": ideas, "items": trace_items}

        _data, pool_payload = locked_update_json(self.path, self._lock, _do, default=_default_graph)
        pool_lock = FileLock(str(pool_path) + ".lock")

        def _replace_pool(data):
            existing = data if isinstance(data, dict) else {"ideas": []}
            preserved = {key: value for key, value in existing.items() if key != "ideas"}
            preserved["ideas"] = pool_payload["ideas"]
            data.clear()
            data.update(preserved)

        locked_update_json(pool_path, pool_lock, _replace_pool, default=lambda: {"ideas": []})
        return {"frontier_items": len(pool_payload["ideas"]), "items": pool_payload["items"]}

    def apply_history_policy(self, memory_payload: dict) -> dict:
        """Annotate frontier rows with family keys and runtime history policy."""

        def _do(data):
            normalized = self._normalize(data)
            before_rows = {
                str(row.get("id", "")).strip(): {
                    "family_key": str(row.get("family_key", "")).strip(),
                    "manager_priority": int(row.get("manager_priority", row.get("priority", 5)) or 5),
                    "runtime_priority": int(row.get("runtime_priority", row.get("priority", 5)) or 5),
                    "policy_state": self._normalize_policy_state(row.get("policy_state")),
                    "policy_reason": str(row.get("policy_reason", "")).strip(),
                }
                for row in normalized["frontier"]
                if isinstance(row, dict)
            }
            normalized["frontier"] = apply_frontier_history_policy(normalized["frontier"], normalized, memory_payload)
            changed: list[dict] = []
            for row in normalized["frontier"]:
                if not isinstance(row, dict):
                    continue
                frontier_id = str(row.get("id", "")).strip()
                if not frontier_id:
                    continue
                before = before_rows.get(frontier_id, {})
                after = {
                    "family_key": str(row.get("family_key", "")).strip(),
                    "manager_priority": int(row.get("manager_priority", row.get("priority", 5)) or 5),
                    "runtime_priority": int(row.get("runtime_priority", row.get("priority", 5)) or 5),
                    "policy_state": self._normalize_policy_state(row.get("policy_state")),
                    "policy_reason": str(row.get("policy_reason", "")).strip(),
                }
                if after != before:
                    changed.append(self._frontier_trace(row))
            data.clear()
            data.update(normalized)
            return {"updated": len(changed), "items": changed}

        _data, result = locked_update_json(self.path, self._lock, _do, default=_default_graph)
        return result

    def absorb_experiment_outcomes(
        self,
        pool_path: Path,
        results_rows: list[dict],
        *,
        primary_metric: str,
        direction: str,
        repro_policy: str = "best_or_surprising",
    ) -> dict:
        """Pull completed compatibility ideas back into the canonical graph."""

        try:
            pool_data = locked_read_json(pool_path, FileLock(str(pool_path) + ".lock"), default=lambda: {"ideas": []})
        except TypeError:
            pool_data = {"ideas": []}
        ideas = pool_data.get("ideas", []) if isinstance(pool_data, dict) else []
        direction_value = direction or "higher_is_better"

        def _do(data):
            normalized = self._normalize(data)
            evidence_rows = normalized["evidence"]
            created = 0
            completed = 0
            created_items: list[dict] = []
            result_signatures = {
                str(row.get("result_signature", "")).strip() for row in evidence_rows if isinstance(row, dict)
            }
            for idea in ideas:
                if not isinstance(idea, dict):
                    continue
                frontier_ref = str(idea.get("frontier_id", "")).strip()
                spec_id = str(idea.get("experiment_spec_id", "")).strip()
                idea_id = str(idea.get("id", "")).strip()
                execution_ref = str(idea.get("execution_id", "")).strip()
                if not spec_id and not frontier_ref:
                    continue
                frontier_item = self._find_frontier_item(
                    normalized["frontier"],
                    spec_id=spec_id,
                    frontier_id=frontier_ref or None,
                    idea_id=idea_id or None,
                    execution_id=execution_ref or None,
                )
                if frontier_item is None:
                    continue
                idea_status = str(idea.get("status", "")).strip()
                if idea_status == "running":
                    frontier_item["status"] = "running"
                    continue
                if idea_status not in {"done", "skipped"}:
                    continue

                finished_at = str(idea.get("finished_at", "")).strip()
                if (
                    str(frontier_item.get("status", "")).strip() == "needs_post_review"
                    and str(frontier_item.get("finished_at", "")).strip() == finished_at
                ):
                    continue

                row = self._match_results_row(
                    results_rows,
                    idea,
                    result_signatures,
                    frontier_item=frontier_item,
                )
                metric_value = self._safe_float(
                    idea.get("result", {}).get("metric_value") if isinstance(idea.get("result"), dict) else None
                )
                if row is not None:
                    row_metric = self._safe_float(row.get("metric_value"))
                    if row_metric is not None:
                        metric_value = row_metric

                frontier_item["status"] = "needs_post_review"
                frontier_item["result"] = idea.get("result")
                frontier_item["finished_at"] = finished_at
                frontier_item["terminal_status"] = idea_status
                frontier_item["primary_metric"] = primary_metric or ""
                frontier_item["metric_value"] = metric_value
                frontier_item["resource_request"] = normalize_resource_request(
                    idea.get("resource_request", frontier_item.get("resource_request")),
                    default_gpu_mem_mb=0,
                    fallback_gpu_hint=idea.get("gpu_hint"),
                )
                frontier_item["execution_shape"] = normalize_execution_shape(
                    idea.get("execution_shape", frontier_item.get("execution_shape"))
                )
                frontier_item["expected_duration_minutes"] = normalize_expected_duration_minutes(
                    idea.get("expected_duration_minutes", frontier_item.get("expected_duration_minutes"))
                )
                frontier_item["resource_profile"] = str(
                    idea.get("resource_profile", "") or frontier_item.get("resource_profile", "")
                ).strip()
                frontier_item["workload_label"] = str(
                    idea.get("workload_label", "") or frontier_item.get("workload_label", "")
                ).strip()
                frontier_item["resource_observation"] = self._normalize_resource_observation(
                    idea.get("resource_observation")
                )
                execution_id = (
                    str(idea.get("execution_id", "")).strip()
                    or str(frontier_item.get("active_execution_id", "")).strip()
                )
                if not execution_id:
                    execution_id = self._next_execution_id(normalized["counters"])
                if execution_id:
                    frontier_item["last_execution_id"] = execution_id
                frontier_item["active_execution_id"] = ""

                if row is not None:
                    signature = self._result_signature(row)
                    best_before = self._best_result_value(
                        results_rows,
                        direction_value,
                        exclude_signature=signature,
                    )
                    frontier_item["result_signature"] = signature
                    if signature not in result_signatures:
                        normalized["counters"]["evidence"] += 1
                        evidence_id = f"evi-{normalized['counters']['evidence']:03d}"
                        evidence_rows.append(
                            {
                                "id": evidence_id,
                                "frontier_id": str(frontier_item.get("id", "")).strip(),
                                "idea_id": str(idea.get("id", "")).strip(),
                                "execution_id": execution_id,
                                "hypothesis_id": str(frontier_item.get("hypothesis_id", "")).strip(),
                                "experiment_spec_id": spec_id,
                                "kind": "result_row",
                                "primary_metric": primary_metric or row.get("primary_metric", ""),
                                "metric_value": metric_value,
                                "status": row.get("status", ""),
                                "description": row.get("description", ""),
                                "timestamp": row.get("timestamp", ""),
                                "commit": row.get("commit", ""),
                                "reliability": "pending_critic",
                                "reason_code": (
                                    "reproduction_run" if bool(idea.get("repro_required", False)) else "result_observed"
                                ),
                                "result_signature": signature,
                                "resource_observation": self._normalize_resource_observation(
                                    idea.get("resource_observation")
                                ),
                            }
                        )
                        frontier_item["evidence_id"] = evidence_id
                        frontier_item["last_evidence_id"] = evidence_id
                        created += 1
                        result_signatures.add(signature)
                        created_items.append(self._evidence_trace(evidence_rows[-1]))
                else:
                    best_before = self._best_result_value(results_rows, direction_value)

                anchor_pending = self._anchor_frontier_pending(
                    normalized["frontier"],
                    current_frontier_id=str(frontier_item.get("id", "")).strip(),
                )
                frontier_item["repro_required"] = anchor_pending or self._should_require_repro(
                    repro_policy,
                    metric_value=metric_value,
                    best_before=best_before,
                    direction=direction_value,
                    verdict=self._result_verdict(frontier_item),
                )
                completed += 1

            data.clear()
            data.update(normalized)
            return {
                "evidence_created": created,
                "completed_frontier": completed,
                "items": created_items,
            }

        _data, result = locked_update_json(self.path, self._lock, _do, default=_default_graph)
        return result

    def frontier_status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.read()["frontier"]:
            status = str(item.get("status", "")).strip() or "unknown"
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _find_frontier_item(
        self,
        frontier: list[dict],
        *,
        spec_id: str,
        frontier_id: str | None = None,
        idea_id: str | None = None,
        execution_id: str | None = None,
    ) -> dict | None:
        if frontier_id:
            for item in frontier:
                if str(item.get("id", "")).strip() == frontier_id:
                    return item
            return None

        if idea_id:
            matches = [item for item in frontier if str(item.get("idea_id", "")).strip() == idea_id]
            if len(matches) == 1:
                return matches[0]

        if execution_id:
            matches = [
                item
                for item in frontier
                if execution_id
                and execution_id
                in {
                    str(item.get("active_execution_id", "")).strip(),
                    str(item.get("last_execution_id", "")).strip(),
                }
            ]
            if len(matches) == 1:
                return matches[0]

        matches = [item for item in frontier if str(item.get("experiment_spec_id", "")).strip() == spec_id]
        if len(matches) == 1:
            return matches[0]
        return None

    def _match_results_row(
        self,
        rows: list[dict],
        idea: dict,
        seen_signatures: set[str],
        *,
        frontier_item: dict,
    ) -> dict | None:
        frontier_id = str(frontier_item.get("id", "")).strip()
        execution_id = (
            str(idea.get("execution_id", "")).strip() or str(frontier_item.get("last_execution_id", "")).strip()
        )
        idea_id = str(idea.get("id", "")).strip()
        spec_id = (
            str(idea.get("experiment_spec_id", "")).strip() or str(frontier_item.get("experiment_spec_id", "")).strip()
        )
        desc = str(idea.get("description", "")).strip()
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            signature = self._result_signature(row)
            if signature in seen_signatures:
                continue
            trace = self._result_trace(row)
            if execution_id and trace.get("execution_id") == execution_id:
                return row
            if frontier_id and trace.get("frontier_id") == frontier_id:
                return row
            if idea_id and trace.get("idea_id") == idea_id:
                return row
            if (
                spec_id
                and trace.get("experiment_spec_id") == spec_id
                and frontier_id
                and trace.get("frontier_id") == frontier_id
            ):
                return row
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            signature = self._result_signature(row)
            if signature in seen_signatures:
                continue
            if desc and str(row.get("description", "")).strip() == desc:
                return row
        for row in reversed(rows):
            if not isinstance(row, dict):
                continue
            signature = self._result_signature(row)
            if signature not in seen_signatures:
                return row
        return None

    def _result_signature(self, row: dict) -> str:
        payload = self._result_secondary_payload(row)
        result_id = str(payload.get("_open_researcher_result_id", "")).strip()
        if result_id:
            return f"result-id::{result_id}"

        trace = self._result_trace(row, payload=payload)
        execution_id = trace.get("execution_id", "")
        if execution_id:
            return "::".join(
                [
                    "execution",
                    execution_id,
                    str(row.get("timestamp", "")).strip(),
                    str(row.get("commit", "")).strip(),
                    str(row.get("status", "")).strip(),
                ]
            )

        return "::".join(
            [
                str(row.get("timestamp", "")).strip(),
                str(row.get("commit", "")).strip(),
                str(row.get("description", "")).strip(),
                str(row.get("status", "")).strip(),
            ]
        )

    def _result_secondary_payload(self, row: dict) -> dict:
        raw_secondary = row.get("secondary_metrics", "")
        if isinstance(raw_secondary, dict):
            payload = raw_secondary
        else:
            try:
                payload = json.loads(raw_secondary or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
        return payload if isinstance(payload, dict) else {}

    def _result_trace(self, row: dict, *, payload: dict | None = None) -> dict[str, str]:
        payload = payload if isinstance(payload, dict) else self._result_secondary_payload(row)
        trace = payload.get("_open_researcher_trace", {}) if isinstance(payload, dict) else {}
        if not isinstance(trace, dict):
            return {}
        return {
            "frontier_id": str(trace.get("frontier_id", "")).strip(),
            "idea_id": str(trace.get("idea_id", "")).strip(),
            "execution_id": str(trace.get("execution_id", "")).strip(),
            "hypothesis_id": str(trace.get("hypothesis_id", "")).strip(),
            "experiment_spec_id": str(trace.get("experiment_spec_id", "")).strip(),
        }

    def _anchor_frontier_pending(self, frontier_rows: list[dict], *, current_frontier_id: str) -> bool:
        anchor_rows = [
            row
            for row in frontier_rows
            if isinstance(row, dict) and self._normalize_anchor_role(row.get("anchor_role")) == "anchor"
        ]
        if not anchor_rows:
            return False
        for row in anchor_rows:
            frontier_id = str(row.get("id", "")).strip()
            if frontier_id == current_frontier_id:
                continue
            if str(row.get("claim_state", "")).strip() == "promoted":
                continue
            if str(row.get("review_reason_code", "")).strip() == "strong_evidence":
                continue
            return True
        return False

    def _best_result_value(
        self,
        rows: list[dict],
        direction: str,
        *,
        exclude_signature: str | None = None,
    ) -> float | None:
        values = [
            self._safe_float(row.get("metric_value"))
            for row in rows
            if isinstance(row, dict) and (exclude_signature is None or self._result_signature(row) != exclude_signature)
        ]
        clean = [value for value in values if value is not None]
        if not clean:
            return None
        if direction == "lower_is_better":
            return min(clean)
        return max(clean)

    def _should_require_repro(
        self,
        repro_policy: str,
        *,
        metric_value: float | None,
        best_before: float | None,
        direction: str,
        verdict: str,
    ) -> bool:
        if repro_policy == "none":
            return False
        if repro_policy == "always":
            return True
        if metric_value is None:
            return verdict in {"kept", "keep", "completed"}
        if best_before is None:
            return True
        if direction == "lower_is_better":
            return metric_value < best_before
        return metric_value > best_before

    def _result_verdict(self, frontier_item: dict) -> str:
        result = frontier_item.get("result")
        if isinstance(result, dict):
            return str(result.get("verdict", "")).strip().lower()
        return ""

    def _safe_float(self, value) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
