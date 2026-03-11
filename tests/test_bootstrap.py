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
    cfg = ResearchConfig(
        bootstrap_auto_prepare=True,
        bootstrap_install_command=_py_inline("from pathlib import Path; Path('install.ok').write_text('ok')"),
        bootstrap_data_command=_py_inline(
            "from pathlib import Path; Path('data').mkdir(exist_ok=True); Path('data/ready.txt').write_text('ok')"
        ),
        bootstrap_smoke_command=_py_inline(
            "from pathlib import Path; assert Path('install.ok').exists(); assert Path('data/ready.txt').exists(); print('smoke ok')"
        ),
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
        bootstrap_smoke_command=_py_inline("print('smoke only')"),
        bootstrap_expected_paths=["data/missing.txt"],
    )

    plan = resolve_bootstrap_plan(tmp_path, research, cfg)
    assert plan["status"] == "unresolved"
    assert any("Expected paths are missing" in item for item in plan["unresolved"])

    code, state = run_bootstrap_prepare(tmp_path, research, cfg)
    assert code == 1
    assert state["status"] == "failed"
    assert any("Expected paths are missing" in item for item in state["errors"])


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
