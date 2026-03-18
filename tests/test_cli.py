"""Tests for paperfarm.cli — typer CLI entry-points."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from paperfarm.cli import app, _auto_tag, _deploy_scripts

runner = CliRunner()


# ---------------------------------------------------------------------------
# Import / smoke
# ---------------------------------------------------------------------------


class TestImport:
    """Verify the CLI module can be imported without side-effects."""

    def test_import_app(self):
        from paperfarm import cli  # noqa: F811

        assert hasattr(cli, "app")

    def test_import_commands(self):
        from paperfarm.cli import run, status, results  # noqa: F811

        assert callable(run)
        assert callable(status)
        assert callable(results)

    def test_auto_tag_format(self):
        tag = _auto_tag()
        assert tag.startswith("r-")
        # r-YYYYMMDD-HHMMSS => 17 chars (r- + 8 + - + 6)
        assert len(tag) == 17


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------


class TestStatusCommand:
    """Tests for the ``status`` subcommand."""

    def test_status_no_research_dir(self, tmp_path):
        """status exits with error if .research/ does not exist."""
        result = runner.invoke(app, ["status", str(tmp_path)])
        assert result.exit_code != 0
        assert "No .research directory" in result.output

    def test_status_with_research_dir(self, tmp_path):
        """status displays a table when .research/ exists."""
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        result = runner.invoke(app, ["status", str(tmp_path)])
        assert result.exit_code == 0
        assert "Phase" in result.output
        assert "idle" in result.output

    def test_status_with_activity(self, tmp_path):
        """status shows current phase from activity.json."""
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        (research_dir / "activity.json").write_text(
            json.dumps({
                "phase": "running",
                "round": 3,
                "workers": [],
                "control": {"paused": False, "skip_current": False},
            })
        )
        result = runner.invoke(app, ["status", str(tmp_path)])
        assert result.exit_code == 0
        assert "running" in result.output


# ---------------------------------------------------------------------------
# results command
# ---------------------------------------------------------------------------


class TestResultsCommand:
    """Tests for the ``results`` subcommand."""

    def test_results_no_research_dir(self, tmp_path):
        """results exits with error if .research/ does not exist."""
        result = runner.invoke(app, ["results", str(tmp_path)])
        assert result.exit_code != 0
        assert "No .research directory" in result.output

    def test_results_empty(self, tmp_path):
        """results shows a message when no results exist."""
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        result = runner.invoke(app, ["results", str(tmp_path)])
        assert result.exit_code == 0
        assert "No results recorded" in result.output

    def test_results_with_data(self, tmp_path):
        """results displays a table with recorded data."""
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        # Write a results.tsv with header and one row
        tsv_content = (
            "timestamp\tworker\tfrontier_id\tstatus\tmetric\tvalue\tdescription\n"
            "2026-03-18T10:00:00Z\tw0\tF-1\tkeep\taccuracy\t0.95\tgood result\n"
        )
        (research_dir / "results.tsv").write_text(tsv_content)
        result = runner.invoke(app, ["results", str(tmp_path)])
        assert result.exit_code == 0
        assert "F-1" in result.output
        assert "0.95" in result.output


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


class TestRunCommand:
    """Tests for the ``run`` subcommand — argument parsing & validation only."""

    def test_run_requires_repo(self):
        """run exits with error when no repo argument is given."""
        result = runner.invoke(app, ["run"])
        assert result.exit_code != 0

    def test_run_nonexistent_repo(self, tmp_path):
        """run exits with error when repo path does not exist."""
        bad_path = tmp_path / "nonexistent"
        result = runner.invoke(app, ["run", str(bad_path)])
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_run_help(self):
        """run --help does not crash and shows options."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--goal" in result.output
        assert "--tag" in result.output
        assert "--workers" in result.output
        assert "--headless" in result.output
        assert "--agent-name" in result.output


# ---------------------------------------------------------------------------
# script deployment
# ---------------------------------------------------------------------------


class TestScriptDeployment:
    """Tests for _deploy_scripts helper."""

    def test_deploys_record_py(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        _deploy_scripts(research_dir)
        record = research_dir / "scripts" / "record.py"
        assert record.exists()
        assert "argparse" in record.read_text()

    def test_deploys_rollback_sh(self, tmp_path):
        import stat

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        _deploy_scripts(research_dir)
        rollback = research_dir / "scripts" / "rollback.sh"
        assert rollback.exists()
        assert rollback.stat().st_mode & stat.S_IXUSR

    def test_idempotent(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        _deploy_scripts(research_dir)
        _deploy_scripts(research_dir)  # second call should not fail
        assert (research_dir / "scripts" / "record.py").exists()
