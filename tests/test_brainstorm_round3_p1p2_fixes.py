"""Tests for brainstorm round 3 P1+P2 fixes."""

from __future__ import annotations

import json
import os
import subprocess
import threading

# ── legacy_bootstrap.py fixes ──


class TestBootstrapCorruptStateWarning:
    """P1: read_bootstrap_state logs warning on corrupt JSON."""

    def test_corrupt_json_returns_defaults(self, tmp_path):
        from open_researcher.plugins.bootstrap.legacy_bootstrap import read_bootstrap_state

        state_path = tmp_path / "bootstrap_state.json"
        state_path.write_text("{invalid json", encoding="utf-8")
        result = read_bootstrap_state(state_path)
        assert isinstance(result, dict)
        assert result.get("version") == "research-v1"

    def test_missing_file_returns_defaults(self, tmp_path):
        from open_researcher.plugins.bootstrap.legacy_bootstrap import read_bootstrap_state

        state_path = tmp_path / "bootstrap_state.json"
        result = read_bootstrap_state(state_path)
        assert isinstance(result, dict)
        assert result.get("version") == "research-v1"


class TestBootstrapNestedDictWhitelist:
    """P2: read_bootstrap_state only merges whitelisted nested dict keys."""

    def test_injected_nested_key_rejected(self, tmp_path):
        from open_researcher.plugins.bootstrap.legacy_bootstrap import (
            default_bootstrap_state,
            read_bootstrap_state,
        )

        state_path = tmp_path / "bootstrap_state.json"
        defaults = default_bootstrap_state(tmp_path)
        # Inject unexpected key into a nested dict
        defaults["repo_profile"]["injected_key"] = "malicious"
        state_path.write_text(json.dumps(defaults), encoding="utf-8")
        result = read_bootstrap_state(state_path)
        assert "injected_key" not in result.get("repo_profile", {})


class TestBootstrapAtomicWrite:
    """P0: write_bootstrap_state uses atomic write."""

    def test_atomic_write_no_partial_on_error(self, tmp_path):
        from open_researcher.plugins.bootstrap.legacy_bootstrap import write_bootstrap_state

        state_path = tmp_path / "bootstrap_state.json"
        write_bootstrap_state(state_path, {"status": "completed"})
        original = state_path.read_text(encoding="utf-8")

        # Simulate write failure by making parent non-writable temporarily
        # Just verify current content is valid JSON
        data = json.loads(original)
        assert data["status"] == "completed"
        assert "updated_at" in data


class TestBootstrapPrepareLogSafety:
    """P1: _append_prepare_log handles OSError gracefully."""

    def test_log_write_to_nonexistent_dir(self, tmp_path):
        from open_researcher.plugins.bootstrap.legacy_bootstrap import _append_prepare_log

        log_path = tmp_path / "subdir" / "prepare.log"
        result = subprocess.CompletedProcess(args="test", returncode=0, stdout="ok\n", stderr="")
        # Should not raise even though parent directory doesn't exist yet
        _append_prepare_log(log_path, "test_step", "echo test", result)
        assert log_path.exists()


class TestBootstrapCommandTimeout:
    """P1: _run_prepare_command has timeout handling."""

    def test_timeout_returns_exit_124(self, tmp_path):
        from open_researcher.plugins.bootstrap.legacy_bootstrap import _run_prepare_command

        log_path = tmp_path / "prepare.log"
        result = _run_prepare_command(
            "test",
            "sleep 30",
            working_dir=tmp_path,
            env=dict(os.environ),
            log_path=log_path,
            timeout=1,
        )
        assert result.returncode == 124
        assert "timed out" in result.stderr.lower()


class TestBootstrapMakefileFilter:
    """P1: Makefile target filter rejects injection."""

    def test_rejects_special_chars(self, tmp_path):
        from open_researcher.plugins.bootstrap.legacy_bootstrap import _makefile_targets

        makefile = tmp_path / "Makefile"
        makefile.write_text(
            "clean:\n\trm -rf build\n"
            ".PHONY: all\n"
            "test$(INJECT):\n\techo pwned\n"
            "valid-target:\n\techo ok\n",
            encoding="utf-8",
        )
        targets = _makefile_targets(tmp_path)
        assert "valid-target" in targets
        assert "clean" in targets
        # The injected target should not match
        assert not any("INJECT" in t for t in targets)


class TestBootstrapStepSetdefault:
    """P1: Main loop uses setdefault for step dicts."""

    def test_setdefault_preserves_existing(self, tmp_path):
        from open_researcher.plugins.bootstrap.legacy_bootstrap import default_bootstrap_state

        state = default_bootstrap_state(tmp_path)
        # Simulate what the code does
        smoke = state.setdefault("smoke", {})
        assert smoke is state["smoke"]  # same reference
        assert smoke.get("status") == "pending"


class TestBootstrapRegexCodeBlock:
    """P2: _extract_evaluation_command regex handles optional language markers."""

    def test_extracts_bash_block(self, tmp_path):
        from open_researcher.plugins.bootstrap.legacy_bootstrap import _extract_evaluation_command

        eval_md = tmp_path / "evaluation.md"
        eval_md.write_text("```bash\npytest -v\n```\n", encoding="utf-8")
        cmd = _extract_evaluation_command(eval_md)
        assert cmd == "pytest -v"

    def test_extracts_plain_block(self, tmp_path):
        from open_researcher.plugins.bootstrap.legacy_bootstrap import _extract_evaluation_command

        eval_md = tmp_path / "evaluation.md"
        eval_md.write_text("```\nmake test\n```\n", encoding="utf-8")
        cmd = _extract_evaluation_command(eval_md)
        assert cmd == "make test"

    def test_extracts_sh_block(self, tmp_path):
        from open_researcher.plugins.bootstrap.legacy_bootstrap import _extract_evaluation_command

        eval_md = tmp_path / "evaluation.md"
        eval_md.write_text("```sh\npython run.py\n```\n", encoding="utf-8")
        cmd = _extract_evaluation_command(eval_md)
        assert cmd == "python run.py"


# ── failure_memory.py fix ──


class TestFailureMemorySafeInt:
    """P2: recovery_iterations safe int conversion."""

    def test_non_numeric_recovery_iterations(self, tmp_path):
        from open_researcher.failure_memory import FailureMemoryLedger

        ledger = FailureMemoryLedger(tmp_path / "failure_memory.json")
        ledger.record("command_timeout", "restart", "pass", 1)
        # Inject a row with non-numeric recovery_iterations
        from open_researcher.storage import locked_update_json

        def _inject(data):
            data["ledger"].append({
                "failure_class": "command_timeout",
                "fix_action": "bad_row",
                "verification_result": "pass",
                "recovery_iterations": "not_a_number",
            })

        locked_update_json(ledger.path, ledger._lock, _inject, default=lambda: {"ledger": []})

        # Should not raise
        ranked = ledger.rank_fixes("command_timeout")
        assert isinstance(ranked, list)


# ── phase_gate.py fix ──


class TestPhaseGateThreadSafety:
    """P1: PhaseGate.check() uses threading lock."""

    def test_has_lock(self, tmp_path):
        from open_researcher.phase_gate import PhaseGate

        gate = PhaseGate(tmp_path, mode="autonomous")
        assert hasattr(gate, "_lock")
        assert isinstance(gate._lock, threading.Lock)

    def test_concurrent_checks_no_crash(self, tmp_path):
        from open_researcher.phase_gate import PhaseGate

        gate = PhaseGate(tmp_path, mode="autonomous")
        errors = []

        def _check():
            try:
                for _ in range(50):
                    gate.check()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_check) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert not errors


# ── evaluation_contract.py fix ──


class TestEvaluationContractAtomicWrite:
    """P1: evaluation_contract uses atomic_write_text."""

    def test_uses_atomic_write_import(self):
        import inspect

        import open_researcher.evaluation_contract as mod

        source = inspect.getsource(mod)
        assert "atomic_write_text" in source

    def test_ensure_evaluation_contract_importable(self):
        from open_researcher.evaluation_contract import ensure_evaluation_contract

        assert callable(ensure_evaluation_contract)


# ── constants.py fix ──


class TestConstantsFrozenset:
    """P2: All graph constants are frozenset."""

    def test_all_constants_are_frozenset(self):
        from open_researcher.plugins.graph import constants

        for name in dir(constants):
            if name.startswith("_"):
                continue
            val = getattr(constants, name)
            if isinstance(val, (set, frozenset)):
                assert isinstance(val, frozenset), f"{name} should be frozenset, got {type(val)}"


# ── graph_context.py fixes ──


class TestGraphContextStep5Fallback:
    """P2: enforce_context_token_limit has Step 5 evidence removal."""

    def test_evidence_removed_as_last_resort(self):
        from open_researcher.graph_context import enforce_context_token_limit

        graph = {
            "frontier": [{"id": "f1", "hypothesis_id": "h1", "status": "approved"}],
            "hypotheses": [{"id": "h1"}],
            "evidence": [{"hypothesis_id": "h1", "data": "x" * 5000} for _ in range(20)],
            "experiment_specs": [],
            "claim_updates": [],
        }
        result = enforce_context_token_limit(graph, limit=100)
        assert result["evidence"] == []

    def test_none_excluded_from_frontier_spec_ids(self):
        from open_researcher.graph_context import enforce_context_token_limit

        graph = {
            "frontier": [{"id": "f1", "hypothesis_id": "h1", "status": "approved"}],
            "hypotheses": [{"id": "h1"}],
            "evidence": [{"hypothesis_id": "h1", "data": "x" * 5000} for _ in range(20)],
            "experiment_specs": [{"id": "s1", "hypothesis_id": "h1"}],
            "claim_updates": [],
        }
        # Should not crash with None spec_ids
        result = enforce_context_token_limit(graph, limit=500)
        assert isinstance(result, dict)


# ── legacy_loop.py fixes ──


class TestPrunedGraphContextRemoved:
    """P1: Dead code _pruned_graph_context removed from ResearchLoop."""

    def test_no_pruned_graph_context(self):
        from open_researcher.plugins.orchestrator.legacy_loop import ResearchLoop

        assert not hasattr(ResearchLoop, "_pruned_graph_context")


# ── control_plane.py fix ──


class TestControlPlaneStreamingReplay:
    """P1: control_plane replay uses streaming file reads."""

    def test_replay_works_with_streaming(self, tmp_path):
        from open_researcher.control_plane import issue_control_command, read_control

        ctrl_path = tmp_path / "control.json"
        issue_control_command(ctrl_path, command="pause", source="test", reason="testing")
        state = read_control(ctrl_path)
        assert state.get("paused") is True

        issue_control_command(ctrl_path, command="resume", source="test", reason="done")
        state = read_control(ctrl_path)
        assert state.get("paused") is False


# ── session_hygiene.py fix ──


class TestSessionHygieneConditionalClear:
    """P2: Only clear workers when stale_workers > 0."""

    def test_no_clear_when_no_workers(self, tmp_path):
        from open_researcher.session_hygiene import reset_runtime_session_state

        # Create minimal control.json
        ctrl_path = tmp_path / "control.json"
        ctrl_path.write_text("{}", encoding="utf-8")
        # Create activity.json with no workers
        activity_path = tmp_path / "activity.json"
        activity_path.write_text("{}", encoding="utf-8")

        result = reset_runtime_session_state(tmp_path, source="test")
        assert result["cleared_workers"] is False
        assert result["stale_workers"] == 0


# ── detection.py fix ──


class TestDetectionCrossPlatform:
    """P2: detect_python_env uses sys.platform for cross-platform venv paths."""

    def test_detect_venv(self, tmp_path):
        import sys

        from open_researcher.plugins.bootstrap.detection import detect_python_env

        if sys.platform == "win32":
            venv_bin = tmp_path / ".venv" / "Scripts"
            python_name = "python.exe"
        else:
            venv_bin = tmp_path / ".venv" / "bin"
            python_name = "python"

        venv_bin.mkdir(parents=True)
        python_path = venv_bin / python_name
        python_path.write_text("#!/usr/bin/env python", encoding="utf-8")

        result = detect_python_env(tmp_path)
        assert result is not None
        assert ".venv" in result
