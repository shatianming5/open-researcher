"""Tests for internal role program file helpers."""

from __future__ import annotations

from pathlib import Path

from open_researcher.role_programs import (
    ensure_internal_role_programs,
    internal_role_program_file,
    legacy_role_program_file,
    missing_role_programs,
    resolve_role_program_file,
)


def test_ensure_internal_role_programs_renders_templates_with_context(tmp_path: Path):
    research = tmp_path / ".research"
    research.mkdir()

    ensure_internal_role_programs(research, context={"tag": "demo"})

    manager_path = research / internal_role_program_file("manager")
    critic_path = research / internal_role_program_file("critic")
    exp_path = research / internal_role_program_file("experiment")
    assert manager_path.exists()
    assert critic_path.exists()
    assert exp_path.exists()
    assert "research/demo" in exp_path.read_text(encoding="utf-8")


def test_ensure_internal_role_programs_migrates_from_legacy_files(tmp_path: Path):
    research = tmp_path / ".research"
    research.mkdir()

    legacy = research / legacy_role_program_file("manager")
    legacy.write_text("# legacy-manager\n", encoding="utf-8")

    ensure_internal_role_programs(research)

    internal = research / internal_role_program_file("manager")
    assert internal.read_text(encoding="utf-8") == "# legacy-manager\n"


def test_resolve_role_program_file_prefers_internal_then_legacy(tmp_path: Path):
    research = tmp_path / ".research"
    research.mkdir()

    assert resolve_role_program_file(research, "manager") == internal_role_program_file("manager")

    legacy = research / legacy_role_program_file("manager")
    legacy.write_text("# legacy\n", encoding="utf-8")
    assert resolve_role_program_file(research, "manager") == legacy_role_program_file("manager")

    internal = research / internal_role_program_file("manager")
    internal.parent.mkdir(parents=True, exist_ok=True)
    internal.write_text("# internal\n", encoding="utf-8")
    assert resolve_role_program_file(research, "manager") == internal_role_program_file("manager")


def test_missing_role_programs_reports_unavailable_roles(tmp_path: Path):
    research = tmp_path / ".research"
    research.mkdir()

    # Only manager is present through legacy file.
    (research / legacy_role_program_file("manager")).write_text("# manager\n", encoding="utf-8")

    missing = missing_role_programs(research)
    assert missing == ["critic", "experiment"]
