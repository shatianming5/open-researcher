"""Tests for the Review screen."""

import json
from pathlib import Path


def test_review_screen_import():
    """ReviewScreen should be importable."""
    from open_researcher.tui.review import ReviewScreen

    assert ReviewScreen is not None


def test_review_screen_is_screen():
    """ReviewScreen should be a Textual Screen."""
    from textual.screen import Screen

    from open_researcher.tui.review import ReviewScreen

    assert issubclass(ReviewScreen, Screen)


def test_review_screen_loads_files(tmp_path):
    """ReviewScreen should load strategy, evaluation, and understanding files."""
    from open_researcher.tui.review import load_review_data

    research = tmp_path / ".research"
    research.mkdir()
    (research / "project-understanding.md").write_text("# Understanding\nThis is a test project.")
    (research / "research-strategy.md").write_text("## Research Direction\nOptimize training.")
    (research / "evaluation.md").write_text("## Primary Metric\nval_loss (lower_is_better)")
    (research / "config.yaml").write_text("metrics:\n  primary:\n    name: val_loss\n    direction: lower_is_better\n")

    data = load_review_data(research)
    assert "test project" in data["understanding"]
    assert "Optimize training" in data["strategy"]
    assert "val_loss" in data["evaluation"]
    assert data["metric_name"] == "val_loss"
    assert data["metric_direction"] == "lower_is_better"


def test_review_screen_handles_missing_files(tmp_path):
    """ReviewScreen should handle missing files gracefully."""
    from open_researcher.tui.review import load_review_data

    research = tmp_path / ".research"
    research.mkdir()

    data = load_review_data(research)
    assert data["understanding"] == ""
    assert data["strategy"] == ""
    assert data["evaluation"] == ""
