"""Failure-memory ledger for recurring experiment faults."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from filelock import FileLock

from open_researcher.storage import locked_read_json, locked_update_json

MEMORY_POLICY = "rank_historical_success"


def _default_payload() -> dict:
    return {"memory_policy": MEMORY_POLICY, "ledger": []}


def classify_failure(description: str) -> str:
    """Map an idea description to a coarse failure class."""
    text = (description or "").strip().lower()
    if not text:
        return "general_failure"
    if "timeout" in text or "hang" in text or "stuck" in text:
        return "command_timeout"
    if "artifact" in text or "missing file" in text or "manifest" in text:
        return "missing_artifacts"
    if "test" in text or "assert" in text or "failing" in text:
        return "failing_tests"
    if "oom" in text or "memory" in text:
        return "resource_exhaustion"
    return "general_failure"


class FailureMemoryLedger:
    """Persist and rank historical fixes by failure class."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = FileLock(str(path) + ".lock")

    def _read(self) -> dict:
        data = locked_read_json(self.path, self._lock, default=_default_payload)
        if not isinstance(data, dict):
            return _default_payload()
        data.setdefault("memory_policy", MEMORY_POLICY)
        ledger = data.get("ledger")
        if not isinstance(ledger, list):
            data["ledger"] = []
        return data

    def rank_fixes(self, failure_class: str) -> list[dict]:
        """Return ranked historical fixes for a failure class."""
        data = self._read()
        rows = data.get("ledger", [])
        stats: dict[str, dict] = defaultdict(
            lambda: {
                "fix_action": "",
                "success_count": 0,
                "attempt_count": 0,
                "average_recovery_iterations": 999.0,
            }
        )
        totals: dict[str, int] = defaultdict(int)
        counts: dict[str, int] = defaultdict(int)
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("failure_class", "")) != failure_class:
                continue
            fix_action = str(row.get("fix_action", "")).strip()
            if not fix_action:
                continue
            verification = str(row.get("verification_result", "")).strip().lower()
            recovery_iterations = int(row.get("recovery_iterations", 1) or 1)
            entry = stats[fix_action]
            entry["fix_action"] = fix_action
            entry["attempt_count"] += 1
            if verification == "pass":
                entry["success_count"] += 1
            totals[fix_action] += max(recovery_iterations, 1)
            counts[fix_action] += 1

        ranked = []
        for fix_action, entry in stats.items():
            if counts[fix_action] > 0:
                entry["average_recovery_iterations"] = round(totals[fix_action] / counts[fix_action], 3)
            ranked.append(entry)

        ranked.sort(
            key=lambda item: (
                -int(item.get("success_count", 0)),
                float(item.get("average_recovery_iterations", 999.0)),
                str(item.get("fix_action", "")),
            )
        )
        return ranked

    def select_first_fix(self, failure_class: str) -> str:
        """Select the first remediation action from ranked historical fixes."""
        ranked = self.rank_fixes(failure_class)
        if ranked:
            return str(ranked[0]["fix_action"])
        return "generate_new_plan"

    def record(
        self,
        failure_class: str,
        fix_action: str,
        verification_result: str,
        recovery_iterations: int,
    ) -> dict:
        """Append a compact ledger entry and return it."""
        entry = {
            "failure_class": str(failure_class).strip() or "general_failure",
            "fix_action": str(fix_action).strip() or "generate_new_plan",
            "verification_result": ("pass" if str(verification_result).strip().lower() == "pass" else "fail"),
            "recovery_iterations": max(int(recovery_iterations), 1),
        }

        def _do(data):
            if not isinstance(data, dict):
                data = _default_payload()
            data["memory_policy"] = MEMORY_POLICY
            ledger = data.get("ledger")
            if not isinstance(ledger, list):
                ledger = []
            ledger.append(entry)
            data["ledger"] = ledger

        locked_update_json(self.path, self._lock, _do, default=_default_payload)
        return entry
