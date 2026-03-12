"""Tests for CLI workflow option normalization."""

import pytest

from paperfarm.workflow_options import build_workflow_selection


def test_build_workflow_selection_defaults():
    selection = build_workflow_selection(agent=None)
    assert selection.frontend_mode == "interactive"
    assert selection.workers is None
    assert selection.primary_agent_name is None


def test_build_workflow_selection_workers_passthrough():
    selection = build_workflow_selection(agent="codex", workers=2)
    assert selection.workers == 2
    assert selection.primary_agent_name == "codex"


def test_build_workflow_selection_headless_deprecated_flag_adds_notice():
    selection = build_workflow_selection(agent="codex", headless=True)
    assert selection.frontend_mode == "headless"
    assert len(selection.notices) == 1


def test_build_workflow_selection_rejects_invalid_mode():
    with pytest.raises(ValueError):
        build_workflow_selection(agent=None, mode="batch")


def test_build_workflow_selection_rejects_invalid_workers():
    with pytest.raises(ValueError):
        build_workflow_selection(agent=None, workers=0)
