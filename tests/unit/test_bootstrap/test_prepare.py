"""Tests for bootstrap preparation and state management."""
import time
import pytest
from pathlib import Path


def test_bootstrap_state_lifecycle():
    from open_researcher.plugins.bootstrap.prepare import BootstrapState

    state = BootstrapState()
    assert not state.is_ready
    assert state.started_at == 0.0

    state.mark_started()
    assert state.started_at > 0

    state.mark_step_completed("detect_repo")
    state.mark_step_completed("install_deps")
    assert len(state.steps_completed) == 2

    state.mark_ready()
    assert state.is_ready
    assert state.completed_at >= state.started_at


def test_bootstrap_state_tracks_failures():
    from open_researcher.plugins.bootstrap.prepare import BootstrapState

    state = BootstrapState()
    state.mark_step_failed("install_deps")
    assert "install_deps" in state.steps_failed
    assert not state.is_ready


def test_run_preparation_command_success(tmp_path):
    from open_researcher.plugins.bootstrap.prepare import run_preparation_command

    success, output = run_preparation_command(
        ["echo", "hello"],
        cwd=tmp_path,
    )
    assert success is True
    assert "hello" in output


def test_run_preparation_command_failure(tmp_path):
    from open_researcher.plugins.bootstrap.prepare import run_preparation_command

    success, output = run_preparation_command(
        ["false"],  # always returns exit code 1
        cwd=tmp_path,
    )
    assert success is False


def test_run_preparation_command_not_found(tmp_path):
    from open_researcher.plugins.bootstrap.prepare import run_preparation_command

    success, output = run_preparation_command(
        ["nonexistent_command_xyz"],
        cwd=tmp_path,
    )
    assert success is False
    assert "not found" in output.lower()
