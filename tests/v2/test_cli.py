"""Tests for open_researcher_v2.cli — typer CLI entry-points."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from open_researcher_v2.cli import app, _auto_tag, _deploy_scripts

runner = CliRunner()


# ---------------------------------------------------------------------------
# Import / smoke
# ---------------------------------------------------------------------------


class TestImport:
    """Verify the CLI module can be imported without side-effects."""

    def test_import_app(self):
        from open_researcher_v2 import cli  # noqa: F811

        assert hasattr(cli, "app")

    def test_import_commands(self):
        from open_researcher_v2.cli import run, status, results, review, inject, constrain  # noqa: F811

        assert callable(run)
        assert callable(status)
        assert callable(results)
        assert callable(review)
        assert callable(inject)
        assert callable(constrain)

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

    def test_run_help_shows_mode(self):
        """run --help shows the --mode option."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--mode" in result.output


# ---------------------------------------------------------------------------
# review command
# ---------------------------------------------------------------------------


class TestReviewCommand:
    """Tests for the ``review`` subcommand."""

    def test_review_shows_no_pending_when_none(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        result = runner.invoke(app, ["review", str(tmp_path)])
        assert result.exit_code == 0
        assert "No pending review" in result.output

    def test_review_shows_pending_review(self, tmp_path):
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review(
            {"type": "hypothesis_review", "requested_at": "2026-03-19T14:00:00Z"}
        )
        result = runner.invoke(app, ["review", str(tmp_path)])
        assert result.exit_code == 0
        assert "hypothesis_review" in result.output

    def test_review_skip_clears_review(self, tmp_path):
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review(
            {"type": "frontier_review", "requested_at": "2026-03-19T14:00:00Z"}
        )
        result = runner.invoke(app, ["review", str(tmp_path), "--skip"])
        assert result.exit_code == 0
        assert state.get_awaiting_review() is None

    def test_review_approve_all_clears_review(self, tmp_path):
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review(
            {"type": "result_review", "requested_at": "2026-03-19T14:00:00Z"}
        )
        result = runner.invoke(app, ["review", str(tmp_path), "--approve-all"])
        assert result.exit_code == 0
        assert state.get_awaiting_review() is None

    def test_review_no_research_dir(self, tmp_path):
        """review exits with error if .research/ does not exist."""
        result = runner.invoke(app, ["review", str(tmp_path)])
        assert result.exit_code != 0
        assert "No .research directory" in result.output

    def test_review_reject_marks_frontier_items(self, tmp_path):
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review(
            {"type": "frontier_review", "requested_at": "2026-03-19T14:00:00Z"}
        )
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "frontier-001", "status": "approved"},
            {"id": "frontier-002", "status": "approved"},
        ]
        state.save_graph(graph)
        result = runner.invoke(app, ["review", str(tmp_path), "--reject", "frontier-001"])
        assert result.exit_code == 0
        updated = state.load_graph()
        assert updated["frontier"][0]["status"] == "rejected"
        assert updated["frontier"][1]["status"] == "approved"

    def test_review_priority_updates_frontier(self, tmp_path):
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review(
            {"type": "frontier_review", "requested_at": "2026-03-19T14:00:00Z"}
        )
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "frontier-001", "priority": 1},
        ]
        state.save_graph(graph)
        result = runner.invoke(
            app, ["review", str(tmp_path), "--priority", "frontier-001=5"]
        )
        assert result.exit_code == 0
        updated = state.load_graph()
        assert updated["frontier"][0]["priority"] == 5

    def test_review_approve_all_archives_needs_post_review(self, tmp_path):
        """--approve-all transitions needs_post_review items to archived."""
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review(
            {"type": "result_review", "requested_at": "2026-03-19T14:00:00Z"}
        )
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "frontier-001", "status": "needs_post_review"},
            {"id": "frontier-002", "status": "approved"},
        ]
        state.save_graph(graph)
        result = runner.invoke(app, ["review", str(tmp_path), "--approve-all"])
        assert result.exit_code == 0
        updated = state.load_graph()
        assert updated["frontier"][0]["status"] == "archived"
        assert updated["frontier"][1]["status"] == "approved"

    def test_review_archive_marks_items(self, tmp_path):
        """--archive transitions specific items to archived."""
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review(
            {"type": "result_review", "requested_at": "2026-03-19T14:00:00Z"}
        )
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "frontier-001", "status": "needs_post_review"},
            {"id": "frontier-002", "status": "needs_post_review"},
        ]
        state.save_graph(graph)
        result = runner.invoke(
            app, ["review", str(tmp_path), "--archive", "frontier-001"]
        )
        assert result.exit_code == 0
        updated = state.load_graph()
        assert updated["frontier"][0]["status"] == "archived"
        assert updated["frontier"][1]["status"] == "needs_post_review"
        assert state.get_awaiting_review() is None

    def test_review_default_shows_frontier_table(self, tmp_path):
        """Default review shows items needing review."""
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review(
            {"type": "result_review", "requested_at": "2026-03-19T14:00:00Z"}
        )
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "frontier-001", "status": "needs_post_review", "description": "test exp"},
        ]
        state.save_graph(graph)
        result = runner.invoke(app, ["review", str(tmp_path)])
        assert result.exit_code == 0
        assert "frontier-001" in result.output
        assert "needs_post_review" in result.output


# ---------------------------------------------------------------------------
# inject command
# ---------------------------------------------------------------------------


class TestInjectCommand:
    """Tests for the ``inject`` subcommand."""

    def test_inject_adds_frontier_item(self, tmp_path):
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        result = runner.invoke(
            app,
            ["inject", str(tmp_path), "--desc", "Try __slots__ for hot path", "--priority", "3"],
        )
        assert result.exit_code == 0
        graph = state.load_graph()
        frontier = graph["frontier"]
        assert len(frontier) == 1
        assert frontier[0]["description"] == "Try __slots__ for hot path"
        assert frontier[0]["priority"] == 3
        assert frontier[0]["status"] == "approved"
        assert frontier[0]["selection_reason_code"] == "human_injected"
        assert graph["counters"]["frontier"] == 1

    def test_inject_no_research_dir(self, tmp_path):
        """inject exits with error if .research/ does not exist."""
        result = runner.invoke(
            app, ["inject", str(tmp_path), "--desc", "test"]
        )
        assert result.exit_code != 0
        assert "No .research directory" in result.output

    def test_inject_increments_counter(self, tmp_path):
        """Injecting twice produces distinct frontier IDs."""
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        runner.invoke(app, ["inject", str(tmp_path), "--desc", "First"])
        runner.invoke(app, ["inject", str(tmp_path), "--desc", "Second"])
        graph = state.load_graph()
        assert len(graph["frontier"]) == 2
        assert graph["frontier"][0]["id"] == "frontier-001"
        assert graph["frontier"][1]["id"] == "frontier-002"
        assert graph["counters"]["frontier"] == 2


# ---------------------------------------------------------------------------
# constrain command
# ---------------------------------------------------------------------------


class TestConstrainCommand:
    """Tests for the ``constrain`` subcommand."""

    def test_constrain_adds_constraint(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        result = runner.invoke(
            app, ["constrain", str(tmp_path), "--add", "Do not touch I/O code"]
        )
        assert result.exit_code == 0
        content = (research_dir / "user_constraints.md").read_text()
        assert "Do not touch I/O code" in content

    def test_constrain_appends_multiple(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        (research_dir / "user_constraints.md").write_text("- Existing constraint\n")
        result = runner.invoke(
            app, ["constrain", str(tmp_path), "--add", "Focus on parser only"]
        )
        assert result.exit_code == 0
        content = (research_dir / "user_constraints.md").read_text()
        assert "Existing constraint" in content
        assert "Focus on parser only" in content

    def test_constrain_shows_existing(self, tmp_path):
        """Without --add, constrain displays existing constraints."""
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        (research_dir / "user_constraints.md").write_text("- Constraint A\n- Constraint B\n")
        result = runner.invoke(app, ["constrain", str(tmp_path)])
        assert result.exit_code == 0
        assert "Constraint A" in result.output

    def test_constrain_no_constraints_set(self, tmp_path):
        """Without --add and no file, shows 'No constraints set'."""
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        result = runner.invoke(app, ["constrain", str(tmp_path)])
        assert result.exit_code == 0
        assert "No constraints set" in result.output

    def test_constrain_no_research_dir(self, tmp_path):
        """constrain exits with error if .research/ does not exist."""
        result = runner.invoke(
            app, ["constrain", str(tmp_path), "--add", "test"]
        )
        assert result.exit_code != 0
        assert "No .research directory" in result.output


# ---------------------------------------------------------------------------
# run --mode flag
# ---------------------------------------------------------------------------


class TestScriptDeployment:
    """Tests for _deploy_scripts copying helper scripts to .research/scripts/."""

    def test_deploy_creates_scripts_dir(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        _deploy_scripts(research_dir)
        assert (research_dir / "scripts").is_dir()

    def test_deploy_copies_record_py(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        _deploy_scripts(research_dir)
        record = research_dir / "scripts" / "record.py"
        assert record.exists()
        content = record.read_text(encoding="utf-8")
        assert "def main" in content

    def test_deploy_copies_rollback_sh(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        _deploy_scripts(research_dir)
        rollback = research_dir / "scripts" / "rollback.sh"
        assert rollback.exists()
        import os
        assert os.access(rollback, os.X_OK)

    def test_deploy_is_idempotent(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        _deploy_scripts(research_dir)
        _deploy_scripts(research_dir)
        assert (research_dir / "scripts" / "record.py").exists()
        assert (research_dir / "scripts" / "rollback.sh").exists()


class TestRunModeFlag:
    """Tests for the ``--mode`` flag on the run command."""

    def test_run_mode_in_help(self):
        """run --help includes --mode option."""
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--mode" in result.output
