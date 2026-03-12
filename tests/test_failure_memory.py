"""Tests for failure memory ledger ranking and persistence."""

import json

from paperfarm.failure_memory import (
    MEMORY_POLICY,
    FailureMemoryLedger,
    classify_failure,
)


def test_rank_fixes_prefers_success_and_lower_iterations(tmp_path):
    ledger_path = tmp_path / "failure_memory_ledger.json"
    ledger = FailureMemoryLedger(ledger_path)

    ledger.record("failing_tests", "rerun_without_changes", "fail", 3)
    ledger.record("failing_tests", "apply_fix_and_rerun_tests", "pass", 2)
    ledger.record("failing_tests", "apply_fix_and_rerun_tests", "pass", 1)
    ledger.record("failing_tests", "revert_dependency", "pass", 4)

    ranked = ledger.rank_fixes("failing_tests")

    assert [entry["fix_action"] for entry in ranked][:2] == [
        "apply_fix_and_rerun_tests",
        "revert_dependency",
    ]
    assert ranked[0]["success_count"] == 2
    assert ranked[0]["average_recovery_iterations"] == 1.5


def test_record_persists_compact_ledger_fields(tmp_path):
    ledger_path = tmp_path / "failure_memory_ledger.json"
    ledger = FailureMemoryLedger(ledger_path)

    entry = ledger.record(
        failure_class="missing_artifacts",
        fix_action="refresh_manifest_and_verify_artifacts",
        verification_result="pass",
        recovery_iterations=1,
    )

    assert set(entry.keys()) == {
        "failure_class",
        "fix_action",
        "verification_result",
        "recovery_iterations",
    }
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert payload["memory_policy"] == MEMORY_POLICY
    assert payload["ledger"][-1] == entry


def test_classify_failure_keywords():
    assert classify_failure("Training timeout after 500 steps") == "command_timeout"
    assert classify_failure("Missing artifact manifest path") == "missing_artifacts"
    assert classify_failure("failing test assertion in pipeline") == "failing_tests"
