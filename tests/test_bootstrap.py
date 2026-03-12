"""Tests for bootstrap resolution and auto-prepare."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

from open_researcher.bootstrap import (
    format_bootstrap_dry_run,
    read_bootstrap_state,
    resolve_bootstrap_plan,
    run_bootstrap_prepare,
)
from open_researcher.config import ResearchConfig


def _py_inline(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


def test_resolve_bootstrap_plan_detects_python_defaults(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    research = tmp_path / ".research"
    research.mkdir()

    plan = resolve_bootstrap_plan(tmp_path, research, ResearchConfig())

    assert plan["repo_profile"]["kind"] == "python"
    assert plan["python_env"]["source"] == "auto-create .venv"
    assert "pip install -r requirements.txt" in plan["install"]["command"]
    assert plan["smoke"]["command"] == "pytest -q"
    assert plan["status"] == "resolved"
    assert plan["errors"] == []
    assert plan["unresolved"] == []


def test_resolve_bootstrap_plan_disabled_marks_steps_disabled(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    research = tmp_path / ".research"
    research.mkdir()
    cfg = ResearchConfig(bootstrap_auto_prepare=False)

    plan = resolve_bootstrap_plan(tmp_path, research, cfg)

    assert plan["status"] == "disabled"
    assert plan["errors"] == []
    assert plan["unresolved"] == []
    assert plan["install"]["status"] == "disabled"
    assert plan["data"]["status"] == "disabled"
    assert plan["smoke"]["status"] == "disabled"


def test_run_bootstrap_prepare_executes_install_data_and_smoke(tmp_path: Path) -> None:
    research = tmp_path / ".research"
    research.mkdir()
    smoke_command = (
        "from pathlib import Path; "
        "assert Path('install.ok').exists(); "
        "assert Path('data/ready.txt').exists(); "
        "print('smoke ok')"
    )
    cfg = ResearchConfig(
        bootstrap_auto_prepare=True,
        bootstrap_install_command=_py_inline("from pathlib import Path; Path('install.ok').write_text('ok')"),
        bootstrap_data_command=_py_inline(
            "from pathlib import Path; Path('data').mkdir(exist_ok=True); Path('data/ready.txt').write_text('ok')"
        ),
        bootstrap_smoke_command=_py_inline(smoke_command),
        bootstrap_expected_paths=["data/ready.txt"],
    )

    seen_events: list[str] = []
    code, state = run_bootstrap_prepare(
        tmp_path,
        research,
        cfg,
        on_prepare_event=lambda event: seen_events.append(type(event).__name__),
    )

    assert code == 0
    assert state["status"] == "completed"
    assert (tmp_path / "install.ok").exists()
    assert (tmp_path / "data" / "ready.txt").exists()
    assert (research / "prepare.log").exists()
    persisted = read_bootstrap_state(research / "bootstrap_state.json")
    assert persisted["status"] == "completed"
    assert persisted["install"]["status"] == "completed"
    assert persisted["data"]["status"] == "completed"
    assert persisted["smoke"]["status"] == "completed"
    assert persisted["expected_path_status"][0]["exists"] is True
    assert seen_events[0] == "PrepareStarted"
    assert "PrepareStepStarted" in seen_events
    assert seen_events[-1] == "PrepareCompleted"


def test_run_bootstrap_prepare_fails_when_expected_paths_missing_without_data_step(tmp_path: Path) -> None:
    research = tmp_path / ".research"
    research.mkdir()
    cfg = ResearchConfig(
        bootstrap_auto_prepare=True,
        bootstrap_expected_paths=["data/missing.txt"],
    )

    plan = resolve_bootstrap_plan(tmp_path, research, cfg)
    assert plan["status"] == "unresolved"
    assert any("Expected paths are missing" in item for item in plan["unresolved"])

    code, state = run_bootstrap_prepare(tmp_path, research, cfg)
    assert code == 1
    assert state["status"] == "failed"
    assert any("Expected paths are missing" in item for item in state["errors"])


def test_run_bootstrap_prepare_reuses_ready_workspace_before_install_and_data(tmp_path: Path) -> None:
    research = tmp_path / ".research"
    research.mkdir()
    cfg = ResearchConfig(
        bootstrap_auto_prepare=True,
        bootstrap_install_command=_py_inline("raise SystemExit(9)"),
        bootstrap_data_command=_py_inline("raise SystemExit(8)"),
        bootstrap_smoke_command=_py_inline("print('ready already')"),
        bootstrap_expected_paths=["data/not-there.txt"],
    )

    plan = resolve_bootstrap_plan(tmp_path, research, cfg)
    assert plan["status"] == "resolved"
    assert plan["warnings"] == []
    assert plan["unresolved"] == []

    code, state = run_bootstrap_prepare(tmp_path, research, cfg)

    assert code == 0
    assert state["status"] == "completed"
    assert state["install"]["status"] == "skipped"
    assert state["data"]["status"] == "skipped"
    assert state["smoke"]["status"] == "completed"
    assert any("smoke succeeded" in item.lower() or "smoke passed" in item.lower() for item in state["warnings"])
    persisted = read_bootstrap_state(research / "bootstrap_state.json")
    assert persisted["status"] == "completed"
    assert persisted["install"]["status"] == "skipped"
    assert persisted["data"]["status"] == "skipped"
    assert persisted["smoke"]["status"] == "completed"
    assert any("smoke" in item.lower() for item in persisted["warnings"])
    prepare_log = (research / "prepare.log").read_text(encoding="utf-8")
    assert "smoke_preflight" in prepare_log
    assert "install ==" not in prepare_log
    assert "data ==" not in prepare_log


def test_run_bootstrap_prepare_retries_smoke_before_falling_back_to_install(tmp_path: Path) -> None:
    research = tmp_path / ".research"
    research.mkdir()
    smoke_command = (
        "from pathlib import Path; "
        "marker = Path('.smoke_retry_once'); "
        "already_failed = marker.exists(); "
        "marker.write_text('1'); "
        "raise SystemExit(0 if already_failed else 1)"
    )
    cfg = ResearchConfig(
        bootstrap_auto_prepare=True,
        bootstrap_install_command=_py_inline("raise SystemExit(9)"),
        bootstrap_data_command=_py_inline("raise SystemExit(8)"),
        bootstrap_smoke_command=_py_inline(smoke_command),
    )

    code, state = run_bootstrap_prepare(tmp_path, research, cfg)

    assert code == 0
    assert state["status"] == "completed"
    assert state["install"]["status"] == "skipped"
    assert state["data"]["status"] == "skipped"
    assert state["smoke"]["status"] == "completed"
    assert any("retry" in item.lower() for item in state["warnings"])
    prepare_log = (research / "prepare.log").read_text(encoding="utf-8")
    assert "smoke_preflight ==" in prepare_log
    assert "smoke_preflight_retry_2 ==" in prepare_log
    assert "install ==" not in prepare_log
    assert "data ==" not in prepare_log


def test_run_bootstrap_prepare_explicit_smoke_retries_in_ambient_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    research = tmp_path / ".research"
    research.mkdir()
    smoke_command = (
        "import os; "
        "from pathlib import Path; "
        "active = bool(os.environ.get('VIRTUAL_ENV')); "
        "(not active) and Path('ambient.ok').write_text('ok'); "
        "print('ambient smoke ok' if not active else 'project env blocked'); "
        "raise SystemExit(7 if active else 0)"
    )
    cfg = ResearchConfig(
        bootstrap_auto_prepare=True,
        bootstrap_install_command=_py_inline("raise SystemExit(9)"),
        bootstrap_data_command=_py_inline("raise SystemExit(8)"),
        bootstrap_smoke_command=_py_inline(smoke_command),
    )

    code, state = run_bootstrap_prepare(tmp_path, research, cfg)

    assert code == 0
    assert state["status"] == "completed"
    assert state["install"]["status"] == "skipped"
    assert state["data"]["status"] == "skipped"
    assert state["smoke"]["status"] == "completed"
    assert (tmp_path / "ambient.ok").exists()
    assert any("ambient environment" in item.lower() for item in state["warnings"])
    prepare_log = (research / "prepare.log").read_text(encoding="utf-8")
    assert "[env_mode=project]" in prepare_log
    assert "[env_mode=ambient]" in prepare_log
    assert "install ==" not in prepare_log
    assert "data ==" not in prepare_log


def test_run_bootstrap_prepare_explicit_smoke_failfast_suppresses_install_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    research = tmp_path / ".research"
    research.mkdir()
    seen_events: list[tuple[str, str]] = []
    cfg = ResearchConfig(
        bootstrap_auto_prepare=True,
        bootstrap_smoke_command=_py_inline("raise SystemExit(7)"),
    )

    code, state = run_bootstrap_prepare(
        tmp_path,
        research,
        cfg,
        on_prepare_event=lambda event: seen_events.append((type(event).__name__, getattr(event, "step", ""))),
    )

    assert code == 1
    assert state["status"] == "failed"
    assert state["smoke"]["status"] == "failed"
    assert state["install"]["status"] == "skipped"
    assert state["data"]["status"] == "skipped"
    assert "install fallback suppressed" in state["smoke"]["detail"].lower()
    assert ("PrepareFailed", "smoke") in seen_events
    assert ("PrepareStepStarted", "install") not in seen_events
    prepare_log = (research / "prepare.log").read_text(encoding="utf-8")
    assert "smoke_preflight ==" in prepare_log
    assert "smoke_preflight_retry_2 ==" in prepare_log
    assert "[env_mode=project]" in prepare_log
    assert "[env_mode=ambient]" in prepare_log
    assert "install ==" not in prepare_log
    assert "data ==" not in prepare_log


def test_run_bootstrap_prepare_resets_step_runtime_state_between_runs(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_install_flag.py").write_text(
        "from pathlib import Path\n\n"
        "def test_install_flag() -> None:\n"
        "    assert Path('install.ok').exists()\n",
        encoding="utf-8",
    )
    research = tmp_path / ".research"
    research.mkdir()
    first_cfg = ResearchConfig(
        bootstrap_auto_prepare=True,
        bootstrap_install_command=_py_inline("from pathlib import Path; Path('install.ok').write_text('ok')"),
    )

    code, _ = run_bootstrap_prepare(tmp_path, research, first_cfg)
    assert code == 0
    first_state = read_bootstrap_state(research / "bootstrap_state.json")
    assert first_state["install"]["status"] == "completed"
    assert first_state["install"]["started_at"]
    assert first_state["install"]["finished_at"]

    second_cfg = ResearchConfig(
        bootstrap_auto_prepare=True,
        bootstrap_install_command=_py_inline("raise SystemExit(9)"),
        bootstrap_smoke_command=_py_inline("print('ready already')"),
    )

    code, _ = run_bootstrap_prepare(tmp_path, research, second_cfg)

    assert code == 0
    second_state = read_bootstrap_state(research / "bootstrap_state.json")
    assert second_state["install"]["status"] == "skipped"
    assert second_state["install"]["started_at"] == ""
    assert second_state["install"]["finished_at"] == ""
    assert second_state["install"]["detail"] != "Completed successfully"


def test_format_bootstrap_dry_run_surfaces_expected_paths_and_unresolved(tmp_path: Path) -> None:
    research = tmp_path / ".research"
    research.mkdir()
    cfg = ResearchConfig(
        bootstrap_auto_prepare=True,
        bootstrap_expected_paths=["data/missing.txt"],
    )

    lines = format_bootstrap_dry_run(tmp_path, research, cfg)
    rendered = "\n".join(lines)

    assert "Expected paths:" in rendered
    assert "data/missing.txt" in rendered
    assert "Unresolved:" in rendered
