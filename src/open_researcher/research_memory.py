"""Structured long-horizon memory for research-v1 runs."""

from __future__ import annotations

from pathlib import Path

from filelock import FileLock

from open_researcher.storage import locked_read_json, locked_update_json


def _default_memory() -> dict:
    return {
        "version": "research-v1",
        "repo_type_priors": [],
        "ideation_memory": [],
        "experiment_memory": [],
        "seen_claim_updates": [],
        "seen_evidence": [],
    }


class ResearchMemoryStore:
    """Persist multi-layer memory derived from graph outcomes."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = FileLock(str(path) + ".lock")

    def _normalize(self, payload: object) -> dict:
        data = payload if isinstance(payload, dict) else _default_memory()
        normalized = dict(_default_memory())
        normalized.update(data)
        normalized["version"] = "research-v1"
        for key in ["repo_type_priors", "ideation_memory", "experiment_memory", "seen_claim_updates", "seen_evidence"]:
            value = normalized.get(key)
            normalized[key] = value if isinstance(value, list) else []
        return normalized

    def ensure_exists(self) -> None:
        def _do(data):
            normalized = self._normalize(data)
            data.clear()
            data.update(normalized)

        locked_update_json(self.path, self._lock, _do, default=_default_memory)

    def read(self) -> dict:
        return self._normalize(locked_read_json(self.path, self._lock, default=_default_memory))

    def absorb_graph(
        self,
        graph: dict,
        *,
        repo_profile: dict | None = None,
        include_repo_type_prior: bool = True,
        include_ideation: bool = True,
        include_experiment: bool = True,
    ) -> dict:
        """Derive compact ideation and experiment memories from graph state."""
        profile = repo_profile or graph.get("repo_profile", {})
        profile_key = str(profile.get("profile_key", "general_code")).strip() or "general_code"
        hypotheses = {
            str(item.get("id", "")).strip(): item for item in graph.get("hypotheses", []) if isinstance(item, dict)
        }
        evidence = {
            str(item.get("id", "")).strip(): item for item in graph.get("evidence", []) if isinstance(item, dict)
        }

        def _do(data):
            normalized = self._normalize(data)
            priors = normalized["repo_type_priors"]
            if include_repo_type_prior and not any(
                str(item.get("profile_key", "")).strip() == profile_key for item in priors if isinstance(item, dict)
            ):
                priors.append(
                    {
                        "profile_key": profile_key,
                        "task_family": str(profile.get("task_family", "general_code")).strip() or "general_code",
                        "primary_metric": str(profile.get("primary_metric", "")).strip(),
                        "direction": str(profile.get("direction", "")).strip(),
                    }
                )

            for update in graph.get("claim_updates", []):
                if not isinstance(update, dict):
                    continue
                update_id = str(update.get("id", "")).strip()
                if not update_id or update_id in normalized["seen_claim_updates"]:
                    continue
                if include_ideation:
                    hypothesis = hypotheses.get(str(update.get("hypothesis_id", "")).strip(), {})
                    normalized["ideation_memory"].append(
                        {
                            "source_claim_update": update_id,
                            "frontier_id": str(update.get("frontier_id", "")).strip(),
                            "profile_key": profile_key,
                            "hypothesis_id": str(update.get("hypothesis_id", "")).strip(),
                            "experiment_spec_id": str(update.get("experiment_spec_id", "")).strip(),
                            "execution_id": str(update.get("execution_id", "")).strip(),
                            "summary": str(
                                hypothesis.get("summary", "")
                                or hypothesis.get("description", "")
                                or update.get("summary", "")
                            ).strip(),
                            "outcome": str(update.get("transition", "")).strip() or "observed",
                            "confidence": str(update.get("confidence", "")).strip() or "pending",
                            "reason_code": str(update.get("reason_code", "")).strip() or "unspecified",
                        }
                    )
                normalized["seen_claim_updates"].append(update_id)

            for row in graph.get("evidence", []):
                if not isinstance(row, dict):
                    continue
                evidence_id = str(row.get("id", "")).strip()
                if not evidence_id or evidence_id in normalized["seen_evidence"]:
                    continue
                if include_experiment:
                    source_row = evidence.get(evidence_id, row)
                    normalized["experiment_memory"].append(
                        {
                            "source_evidence": evidence_id,
                            "frontier_id": str(source_row.get("frontier_id", "")).strip(),
                            "idea_id": str(source_row.get("idea_id", "")).strip(),
                            "execution_id": str(source_row.get("execution_id", "")).strip(),
                            "profile_key": profile_key,
                            "experiment_spec_id": str(source_row.get("experiment_spec_id", "")).strip(),
                            "summary": str(source_row.get("description", "")).strip(),
                            "reliability": str(source_row.get("reliability", "")).strip() or "pending_critic",
                            "reason_code": str(source_row.get("reason_code", "")).strip() or "unspecified",
                            "status": str(source_row.get("status", "")).strip(),
                            "primary_metric": str(source_row.get("primary_metric", "")).strip(),
                            "metric_value": source_row.get("metric_value"),
                        }
                    )
                normalized["seen_evidence"].append(evidence_id)

            data.clear()
            data.update(normalized)
            return {
                "repo_type_priors": len(normalized["repo_type_priors"]),
                "ideation_memory": len(normalized["ideation_memory"]),
                "experiment_memory": len(normalized["experiment_memory"]),
            }

        _data, result = locked_update_json(self.path, self._lock, _do, default=_default_memory)
        return result
