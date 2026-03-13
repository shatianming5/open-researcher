"""Tests for repository and environment detection."""
import pytest
from pathlib import Path


def test_detect_repo_python_project(tmp_path):
    from open_researcher.plugins.bootstrap.detection import detect_repo

    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    (tmp_path / ".git").mkdir()

    info = detect_repo(tmp_path)
    assert info.has_git is True
    assert info.has_python is True
    assert info.has_pyproject is True
    assert "python" in info.languages


def test_detect_repo_empty_dir(tmp_path):
    from open_researcher.plugins.bootstrap.detection import detect_repo

    info = detect_repo(tmp_path)
    assert info.has_git is False
    assert info.has_python is False
    assert info.languages == []


def test_detect_repo_multi_language(tmp_path):
    from open_researcher.plugins.bootstrap.detection import detect_repo

    (tmp_path / "requirements.txt").write_text("pytest\n")
    (tmp_path / "package.json").write_text("{}\n")

    info = detect_repo(tmp_path)
    assert "python" in info.languages
    assert "javascript" in info.languages


def test_detect_python_env_venv(tmp_path):
    from open_researcher.plugins.bootstrap.detection import detect_python_env

    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    python = venv_bin / "python"
    python.write_text("#!/usr/bin/env python3\n")
    python.chmod(0o755)

    result = detect_python_env(tmp_path)
    assert result is not None
    assert ".venv" in result


def test_detect_python_env_falls_back_to_system(tmp_path):
    from open_researcher.plugins.bootstrap.detection import detect_python_env

    # No venv, should find system python
    result = detect_python_env(tmp_path)
    assert result is not None  # system python should exist


def test_command_info_creation():
    from open_researcher.plugins.bootstrap.detection import CommandInfo

    cmd = CommandInfo(
        name="install",
        command=["pip", "install", "-r", "requirements.txt"],
        description="Install dependencies",
    )
    assert cmd.name == "install"
    assert len(cmd.command) == 4
