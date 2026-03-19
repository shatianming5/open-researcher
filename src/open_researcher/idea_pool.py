"""Idea backlog for default flow plus concurrent claim support for parallel workers."""

import copy
import logging
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from open_researcher.resource_scheduler import (
    DEFAULT_DURATION_MINUTES,
    normalize_execution_shape,
    normalize_expected_duration_minutes,
    normalize_resource_request,
    sort_pending_ideas,
)
from open_researcher.storage import atomic_write_json, locked_read_json, locked_update_json

logger = logging.getLogger(__name__)


def _default_pool() -> dict:
    return {"ideas": []}


class IdeaBacklog:
    """Read/write the serial idea backlog with atomic file updates."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = FileLock(str(path) + ".lock")

    # ---- low-level helpers ------------------------------------------------

    def _read_locked(self) -> dict:
        """Read idea pool JSON under lock; returns default on missing/corrupt."""
        return locked_read_json(self.path, self._lock, default=_default_pool)

    def _write(self, data: dict) -> None:
        """Atomic write (caller must already hold the lock)."""
        atomic_write_json(self.path, data)

    def _next_id(self, data: dict) -> str:
        existing = [i["id"] for i in data["ideas"]]
        n = 1
        while f"idea-{n:03d}" in existing:
            n += 1
        return f"idea-{n:03d}"

    def _atomic_update(self, updater) -> dict:
        """Lock file, read, apply updater function, write back, return updater result."""
        _data, result = locked_update_json(self.path, self._lock, updater, default=_default_pool)
        return result

    def _clear_live_parallel_runtime_state(self, idea: dict) -> None:
        idea.pop("assigned_experiment", None)
        idea.pop("claimed_by", None)
        idea.pop("claim_token", None)
        idea.pop("claim_token_seq", None)

    def _clear_parallel_runtime_state(self, idea: dict) -> None:
        self._clear_live_parallel_runtime_state(idea)
        idea.pop("finished_claim_token", None)
        idea.pop("finished_claim_token_seq", None)

    def _finalize_terminal_status(self, idea: dict) -> None:
        idea["finished_at"] = datetime.now(timezone.utc).isoformat()
        ct = idea.get("claim_token")
        if ct is not None:
            idea["finished_claim_token"] = ct
            idea["finished_claim_token_seq"] = idea.get("claim_token_seq")
        self._clear_live_parallel_runtime_state(idea)

    def _clear_terminal_status(self, idea: dict) -> None:
        idea.pop("finished_at", None)
        idea.pop("finished_claim_token", None)
        idea.pop("finished_claim_token_seq", None)

    # ---- public serial backlog API ----------------------------------------

    def add(
        self,
        description: str,
        source: str = "original",
        category: str = "general",
        priority: int = 5,
        gpu_hint: int | str = "auto",
        resource_request: dict | None = None,
        execution_shape: dict | None = None,
        expected_duration_minutes: int = DEFAULT_DURATION_MINUTES,
        workload_label: str = "",
        resource_profile: str = "",
    ) -> dict:
        def _do(data):
            idea = {
                "id": self._next_id(data),
                "description": description,
                "source": source,
                "category": category,
                "priority": priority,
                "status": "pending",
                "gpu_hint": gpu_hint,
                "resource_request": normalize_resource_request(
                    resource_request,
                    default_gpu_mem_mb=0,
                    fallback_gpu_hint=gpu_hint,
                ),
                "execution_shape": normalize_execution_shape(execution_shape),
                "expected_duration_minutes": normalize_expected_duration_minutes(expected_duration_minutes),
                "workload_label": str(workload_label or "").strip(),
                "resource_profile": str(resource_profile or "").strip(),
                "result": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            data["ideas"].append(idea)
            return idea

        return self._atomic_update(_do)

    def list_by_status(self, status: str) -> list[dict]:
        data = self._read_locked()
        filtered = [i for i in data["ideas"] if i["status"] == status]
        filtered.sort(key=lambda x: x["priority"])
        return filtered

    def all_ideas(self) -> list[dict]:
        return self._read_locked()["ideas"]

    def pending_ideas(
        self,
        *,
        default_gpu_mem_mb: int = 0,
        backfill_threshold_minutes: int = 30,
    ) -> list[dict]:
        data = self._read_locked()
        pending = [i for i in data["ideas"] if i.get("status") == "pending"]
        return sort_pending_ideas(
            pending,
            default_gpu_mem_mb=default_gpu_mem_mb,
            default_duration_minutes=DEFAULT_DURATION_MINUTES,
            backfill_threshold_minutes=backfill_threshold_minutes,
        )

    def update_status(self, idea_id: str, status: str) -> bool:
        def _do(data):
            for idea in data["ideas"]:
                if idea["id"] == idea_id:
                    idea["status"] = status
                    if status in {"done", "skipped"}:
                        self._finalize_terminal_status(idea)
                    else:
                        self._clear_terminal_status(idea)
                        self._clear_live_parallel_runtime_state(idea)
                    return True
            return False

        return bool(self._atomic_update(_do))

    def mark_done(self, idea_id: str, metric_value: float | None, verdict: str) -> bool:
        return self.mark_done_with_context(idea_id, metric_value, verdict)

    def mark_done_with_context(
        self,
        idea_id: str,
        metric_value: float | None,
        verdict: str,
        *,
        claim_token: str | None = None,
        resource_observation: dict | None = None,
    ) -> bool:
        def _do(data):
            for idea in data["ideas"]:
                if idea["id"] != idea_id:
                    continue
                if claim_token is not None:
                    current = str(idea.get("claim_token") or idea.get("finished_claim_token") or "")
                    if current != str(claim_token):
                        return False
                    claimed_at = idea.get("claimed_at") or idea.get("started_at")
                    if claimed_at:
                        try:
                            age_seconds = (
                                datetime.now(timezone.utc) - datetime.fromisoformat(claimed_at)
                            ).total_seconds()
                            if age_seconds > 1800:  # 30 minutes
                                logger.warning("Claim token for %s expired (age=%.0fs)", idea.get("id"), age_seconds)
                                return False
                        except (ValueError, TypeError):
                            pass
                idea["status"] = "done"
                idea["result"] = {"metric_value": metric_value, "verdict": verdict}
                if isinstance(resource_observation, dict) and resource_observation:
                    idea["resource_observation"] = copy.deepcopy(resource_observation)
                self._finalize_terminal_status(idea)
                return True
            return False

        return bool(self._atomic_update(_do))

    def delete(self, idea_id: str) -> None:
        def _do(data):
            data["ideas"] = [i for i in data["ideas"] if i["id"] != idea_id]

        self._atomic_update(_do)

    def update_priority(self, idea_id: str, priority: int) -> None:
        def _do(data):
            for idea in data["ideas"]:
                if idea["id"] == idea_id:
                    idea["priority"] = priority
                    break

        self._atomic_update(_do)

    def summary(self) -> dict:
        data = self._read_locked()
        ideas = data["ideas"]
        return {
            "pending": sum(1 for i in ideas if i["status"] == "pending"),
            "running": sum(1 for i in ideas if i["status"] == "running"),
            "done": sum(1 for i in ideas if i["status"] == "done"),
            "skipped": sum(1 for i in ideas if i["status"] == "skipped"),
            "total": len(ideas),
        }


class IdeaPool(IdeaBacklog):
    """Concurrent idea pool used by advanced parallel workers."""

    def _next_claim_token(self, data: dict, worker_id: str) -> tuple[int, str]:
        raw_seq = data.get("claim_token_seq", 0)
        try:
            current_seq = int(raw_seq)
        except (TypeError, ValueError):
            # Recover from corrupted seq by scanning existing tokens
            ideas = data.get("ideas", data.get("backlog", []))
            max_found = 0
            for idea in ideas:
                token = str(idea.get("claim_token") or idea.get("finished_claim_token") or "")
                if token.startswith("claim-"):
                    try:
                        seq_part = int(token.split(":")[0].replace("claim-", ""))
                        max_found = max(max_found, seq_part)
                    except (ValueError, IndexError):
                        pass
            current_seq = max_found
            logger.warning("claim_token_seq corrupted (was %r), recovered to %d", raw_seq, current_seq)
        next_seq = max(current_seq, 0) + 1
        data["claim_token_seq"] = next_seq
        return next_seq, f"claim-{next_seq:09d}:{worker_id}"

    def claim_idea(self, worker_id: str) -> dict | None:
        """Atomically claim the highest-priority pending idea for a worker."""

        def _do(data):
            pending = sort_pending_ideas(
                [i for i in data["ideas"] if i["status"] == "pending"],
                default_gpu_mem_mb=0,
                default_duration_minutes=DEFAULT_DURATION_MINUTES,
                backfill_threshold_minutes=30,
            )
            if not pending:
                return None
            target_id = pending[0]["id"]
            for idea in data["ideas"]:
                if idea["id"] == target_id and idea["status"] == "pending":
                    claim_seq, claim_token = self._next_claim_token(data, worker_id)
                    idea["status"] = "running"
                    idea["claimed_by"] = worker_id
                    idea["claim_token_seq"] = claim_seq
                    idea["claim_token"] = claim_token
                    idea["started_at"] = datetime.now(timezone.utc).isoformat()
                    return copy.deepcopy(idea)
            return None

        _data, result = locked_update_json(self.path, self._lock, _do, default=_default_pool)
        return result

    def claim_specific_idea(self, idea_id: str, worker_id: str) -> dict | None:
        """Atomically claim one specific pending idea if it is still available."""

        def _do(data):
            for idea in data["ideas"]:
                if idea.get("id") != idea_id or idea.get("status") != "pending":
                    continue
                claim_seq, claim_token = self._next_claim_token(data, worker_id)
                idea["status"] = "running"
                idea["claimed_by"] = worker_id
                idea["claim_token_seq"] = claim_seq
                idea["claim_token"] = claim_token
                idea["started_at"] = datetime.now(timezone.utc).isoformat()
                return copy.deepcopy(idea)
            return None

        _data, result = locked_update_json(self.path, self._lock, _do, default=_default_pool)
        return result

    def update_status(
        self,
        idea_id: str,
        status: str,
        experiment: int | None = None,
        claim_token: str | None = None,
        resource_observation: dict | None = None,
    ) -> bool:
        def _do(data):
            for idea in data["ideas"]:
                if idea["id"] != idea_id:
                    continue
                if claim_token is not None:
                    if str(idea.get("claim_token") or "") != str(claim_token):
                        return False
                    claimed_at = idea.get("claimed_at") or idea.get("started_at")
                    if claimed_at:
                        try:
                            age_seconds = (
                                datetime.now(timezone.utc) - datetime.fromisoformat(claimed_at)
                            ).total_seconds()
                            if age_seconds > 1800:  # 30 minutes
                                logger.warning("Claim token for %s expired (age=%.0fs)", idea.get("id"), age_seconds)
                                return False
                        except (ValueError, TypeError):
                            pass
                idea["status"] = status
                if experiment is not None:
                    idea["assigned_experiment"] = experiment
                if isinstance(resource_observation, dict) and resource_observation:
                    idea["resource_observation"] = copy.deepcopy(resource_observation)
                if status in {"done", "skipped"}:
                    idea["finished_at"] = datetime.now(timezone.utc).isoformat()
                    idea["finished_claim_token"] = idea.get("claim_token")
                    idea["finished_claim_token_seq"] = idea.get("claim_token_seq")
                    self._clear_live_parallel_runtime_state(idea)
                elif status == "pending":
                    self._clear_terminal_status(idea)
                    self._clear_live_parallel_runtime_state(idea)
                return True
            return False

        return bool(self._atomic_update(_do))

    def mark_done(
        self,
        idea_id: str,
        metric_value: float | None,
        verdict: str,
        claim_token: str | None = None,
        resource_observation: dict | None = None,
    ) -> bool:
        def _do(data):
            for idea in data["ideas"]:
                if idea["id"] != idea_id:
                    continue
                if claim_token is not None:
                    current = str(idea.get("claim_token") or idea.get("finished_claim_token") or "")
                    if current != str(claim_token):
                        return False
                    claimed_at = idea.get("claimed_at") or idea.get("started_at")
                    if claimed_at:
                        try:
                            age_seconds = (
                                datetime.now(timezone.utc) - datetime.fromisoformat(claimed_at)
                            ).total_seconds()
                            if age_seconds > 1800:  # 30 minutes
                                logger.warning("Claim token for %s expired (age=%.0fs)", idea.get("id"), age_seconds)
                                return False
                        except (ValueError, TypeError):
                            pass
                idea["status"] = "done"
                idea["result"] = {"metric_value": metric_value, "verdict": verdict}
                if isinstance(resource_observation, dict) and resource_observation:
                    idea["resource_observation"] = copy.deepcopy(resource_observation)
                idea["finished_at"] = datetime.now(timezone.utc).isoformat()
                idea["finished_claim_token"] = idea.get("claim_token") or idea.get("finished_claim_token")
                idea["finished_claim_token_seq"] = idea.get("claim_token_seq") or idea.get("finished_claim_token_seq")
                self._clear_live_parallel_runtime_state(idea)
                return True
            return False

        return bool(self._atomic_update(_do))
