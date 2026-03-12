"""Tests for the demo command."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from paperfarm.demo_cmd import _build_idea_pool, _build_results_tsv, _populate_research, _setup_demo_repo


def test_build_results_tsv():
    """Results TSV has correct structure."""
    from datetime import datetime, timezone

    tsv = _build_results_tsv(datetime.now(timezone.utc))
    lines = tsv.strip().split("\n")
    assert lines[0].startswith("timestamp\t")
    # 15 experiments + header
    assert len(lines) == 16
    # Check columns
    for line in lines[1:]:
        parts = line.split("\t")
        assert len(parts) == 7


def test_build_idea_pool():
    """Idea pool has correct structure."""
    pool = _build_idea_pool()
    assert "ideas" in pool
    assert len(pool["ideas"]) == 8
    statuses = {i["status"] for i in pool["ideas"]}
    assert "pending" in statuses
    assert "done" in statuses
    assert "running" in statuses
    for idea in pool["ideas"]:
        assert "assigned_experiment" not in idea
        assert "claimed_by" not in idea


def test_populate_research():
    """All expected files are created in .research/."""
    with tempfile.TemporaryDirectory() as tmp:
        research = Path(tmp) / ".research"
        research.mkdir()
        _populate_research(research)

        assert (research / "results.tsv").exists()
        assert (research / "idea_pool.json").exists()
        assert (research / "activity.json").exists()
        assert (research / "config.yaml").exists()
        assert (research / "control.json").exists()
        assert (research / "events.jsonl").exists()
        assert (research / "project-understanding.md").exists()
        assert (research / "literature.md").exists()
        assert (research / "evaluation.md").exists()
        assert (research / "gpu_status.json").exists()
        assert (research / "scripts").is_dir()

        # Validate JSON files parse correctly
        json.loads((research / "idea_pool.json").read_text())
        json.loads((research / "activity.json").read_text())
        json.loads((research / "control.json").read_text())
        json.loads((research / "gpu_status.json").read_text())
        assert (research / "events.jsonl").read_text() == ""


def test_demo_cli_help():
    """Demo command is registered and shows in help."""
    result = subprocess.run(
        [sys.executable, "-m", "paperfarm.cli", "--help"],
        capture_output=True,
        text=True,
    )
    assert "demo" in result.stdout


def test_demo_cli_serve_option():
    """Demo command exposes --serve and --port options."""
    result = subprocess.run(
        [sys.executable, "-m", "paperfarm.cli", "demo", "--help"],
        capture_output=True,
        text=True,
    )
    assert "--serve" in result.stdout
    assert "--port" in result.stdout


def test_setup_demo_repo_creates_git_and_research(tmp_path):
    """_setup_demo_repo creates a git repo and .research/ with sample files."""
    _setup_demo_repo(tmp_path)

    assert (tmp_path / ".git").is_dir()
    assert (tmp_path / ".research").is_dir()
    assert (tmp_path / ".research" / "results.tsv").exists()
    assert (tmp_path / ".research" / "idea_pool.json").exists()
    assert (tmp_path / ".research" / "control.json").exists()
    assert (tmp_path / "train.py").exists()
    assert (tmp_path / "model.py").exists()


def test_do_demo_serve_missing_import_prints_error(capsys):
    """do_demo(serve=True) prints a helpful error when textual-serve is absent."""
    from paperfarm.demo_cmd import do_demo

    with patch.dict("sys.modules", {"textual_serve": None, "textual_serve.server": None}):
        do_demo(serve=True)

    captured = capsys.readouterr()
    assert "textual-serve" in captured.out


def test_do_demo_serve_launches_server(tmp_path):
    """do_demo(serve=True) constructs a Server and calls serve()."""
    mock_server_instance = MagicMock()
    mock_server_class = MagicMock(return_value=mock_server_instance)
    mock_textual_serve = MagicMock()
    mock_textual_serve.Server = mock_server_class

    with patch.dict("sys.modules", {"textual_serve": MagicMock(), "textual_serve.server": mock_textual_serve}):
        with patch("paperfarm.demo_cmd._setup_demo_repo"):
            with patch("paperfarm.demo_cmd._populate_research"):
                from paperfarm.demo_cmd import do_demo

                do_demo(serve=True, port=9999)

    mock_server_class.assert_called_once()
    call_args = mock_server_class.call_args
    assert call_args[1].get("port") == 9999 or (len(call_args[0]) > 1 and call_args[0][1] == 9999)
    mock_server_instance.serve.assert_called_once()
