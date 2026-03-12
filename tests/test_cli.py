"""Tests for the CLI entry point."""

import re
from pathlib import Path

from typer.testing import CliRunner

from open_researcher.cli import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_init_via_cli():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        result = runner.invoke(app, ["init", "--tag", "test1"])
        assert result.exit_code == 0
        assert Path(".research").is_dir()
        assert Path(".research/scout_program.md").exists()
        assert Path(".research/.internal/role_programs/manager.md").exists()


def test_init_refuses_duplicate():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        Path(".research").mkdir()
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 1


def test_status_without_research():
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1


def test_results_without_research():
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["results"])
        assert result.exit_code == 1


def test_export_without_research():
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["export"])
        assert result.exit_code == 1


def test_run_without_research():
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 1


def test_run_dry_run():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        result = runner.invoke(app, ["init", "--tag", "clitest"])
        assert result.exit_code == 0

        from unittest.mock import MagicMock, patch

        mock_agent = MagicMock()
        mock_agent.name = "mock-agent"
        mock_agent.build_command.return_value = ["mock-cmd", "--test"]

        with patch("open_researcher.run_cmd.detect_agent", return_value=mock_agent):
            result = runner.invoke(app, ["run", "--dry-run"])
            assert result.exit_code == 0
            assert "mock-agent" in result.stdout
            assert "Bootstrap auto-prepare" in result.stdout
            assert "Smoke:" in result.stdout


def test_run_bootstrap_dry_run_prints_prepare_resolution():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        result = runner.invoke(app, ["run", "--dry-run", "--mode", "headless", "--goal", "speed up eval"])

        assert result.exit_code == 0
        assert "Workflow:" in result.stdout
        assert "Bootstrap auto-prepare" in result.stdout
        assert "Dry run" in result.stdout


def test_start_without_git():
    """start should fail without git repo."""
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["start"])
        assert result.exit_code == 1


def test_start_help():
    """start --help should show the command."""
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    plain = _plain(result.stdout)
    assert "start" in plain.lower() or "Start" in plain


def test_start_headless_requires_goal():
    """start --mode headless without --goal should fail."""
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        result = runner.invoke(app, ["start", "--mode", "headless"])
        assert result.exit_code != 0
        assert "goal" in result.stdout.lower() or "goal" in str(result.exception).lower()


def test_start_headless_help():
    """start --help should show high-level mode and worker flags."""
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    plain = _plain(result.stdout)
    assert "--mode" in plain
    assert "--workers" in plain
    assert "--max-experiments" in plain
    assert "--goal" in plain


def test_hidden_start_flags_are_absent_from_help():
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    plain = _plain(result.stdout)
    assert "--multi" not in plain
    assert "--idea-agent" not in plain
    assert "--exp-agent" not in plain
    assert "--headless" not in plain


def test_run_help_shows_workers_not_multi():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    plain = _plain(result.stdout)
    assert "--workers" in plain
    assert "--mode" in plain
    assert "--goal" in plain
    assert "--max-experiments" in plain
    assert "--multi" not in plain


def test_run_without_research_bootstraps_to_start_flow():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        from unittest.mock import patch

        with patch("open_researcher.run_cmd.do_start", return_value=None) as mock_start:
            result = runner.invoke(app, ["run"])

        assert result.exit_code == 0
        mock_start.assert_called_once()


def test_run_mode_headless_routes_to_headless_bootstrap():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        from unittest.mock import patch

        with patch("open_researcher.headless.do_start_headless", return_value=None) as mock_headless:
            result = runner.invoke(
                app,
                ["run", "--mode", "headless", "--goal", "test goal", "--workers", "2"],
            )

        assert result.exit_code == 0
        mock_headless.assert_called_once()
        kwargs = mock_headless.call_args.kwargs
        assert kwargs["workers"] == 2


def test_run_deprecated_headless_flag_routes_to_headless_bootstrap():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        from unittest.mock import patch

        with patch("open_researcher.headless.do_start_headless", return_value=None) as mock_headless:
            result = runner.invoke(
                app,
                ["run", "--headless", "--goal", "test goal", "--workers", "2"],
            )

        assert result.exit_code == 0
        assert "--headless` is deprecated" in result.stdout
        mock_headless.assert_called_once()
        kwargs = mock_headless.call_args.kwargs
        assert kwargs["workers"] == 2


def test_run_existing_research_headless_routes_to_continue_flow():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        Path(".research").mkdir()
        (Path(".research") / "config.yaml").write_text("research:\n  protocol: research-v1\n")
        from unittest.mock import patch

        with patch("open_researcher.headless.do_run_headless", return_value=0) as mock_headless:
            result = runner.invoke(app, ["run", "--mode", "headless", "--workers", "2"])

        assert result.exit_code == 0
        mock_headless.assert_called_once()
        kwargs = mock_headless.call_args.kwargs
        assert kwargs["workers"] == 2


def test_run_existing_research_headless_forwards_token_budget():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        Path(".research").mkdir()
        (Path(".research") / "config.yaml").write_text("research:\n  protocol: research-v1\n")
        from unittest.mock import patch

        with patch("open_researcher.headless.do_run_headless", return_value=0) as mock_headless:
            result = runner.invoke(app, ["run", "--mode", "headless", "--token-budget", "1234"])

        assert result.exit_code == 0
        kwargs = mock_headless.call_args.kwargs
        assert kwargs["token_budget"] == 1234


def test_run_existing_research_headless_dry_run_does_not_launch_runtime():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        Path(".research").mkdir()
        (Path(".research") / "config.yaml").write_text("research:\n  protocol: research-v1\n")
        from unittest.mock import patch

        with patch("open_researcher.headless.do_run_headless") as mock_headless:
            result = runner.invoke(app, ["run", "--mode", "headless", "--dry-run"])

        assert result.exit_code == 0
        assert "Dry run" in result.stdout
        mock_headless.assert_not_called()


def test_run_existing_research_rejects_goal():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        Path(".research").mkdir()
        (Path(".research") / "config.yaml").write_text("research:\n  protocol: research-v1\n")

        result = runner.invoke(app, ["run", "--goal", "should fail"])

        assert result.exit_code == 1
        assert "--goal is only valid" in result.stdout


def test_run_invalid_protocol_prints_friendly_error():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        Path(".research").mkdir()
        (Path(".research") / "config.yaml").write_text("research:\n  protocol: totally-wrong\n")

        result = runner.invoke(app, ["run"])

        assert result.exit_code == 1
        assert "Unsupported research.protocol" in result.stdout


def test_run_interactive_propagates_nonzero_exit_code():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        Path(".research").mkdir()
        (Path(".research") / "config.yaml").write_text("research:\n  protocol: research-v1\n")
        from unittest.mock import patch

        with patch("open_researcher.run_cmd.do_run", return_value=7):
            result = runner.invoke(app, ["run"])

        assert result.exit_code == 7


def test_start_mode_headless_routes_to_headless_entrypoint():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        from unittest.mock import patch

        with patch("open_researcher.headless.do_start_headless", return_value=None) as mock_headless:
            result = runner.invoke(
                app,
                ["start", "--mode", "headless", "--goal", "test goal", "--workers", "2"],
            )

        assert result.exit_code == 0
        mock_headless.assert_called_once()
        kwargs = mock_headless.call_args.kwargs
        assert kwargs["workers"] == 2


def test_start_mode_headless_forwards_token_budget():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        from unittest.mock import patch

        with patch("open_researcher.headless.do_start_headless", return_value=None) as mock_headless:
            result = runner.invoke(
                app,
                ["start", "--mode", "headless", "--goal", "test goal", "--token-budget", "4321"],
            )

        assert result.exit_code == 0
        kwargs = mock_headless.call_args.kwargs
        assert kwargs["token_budget"] == 4321


def test_start_deprecated_headless_flag_routes_to_headless_entrypoint():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        from unittest.mock import patch

        with patch("open_researcher.headless.do_start_headless", return_value=None) as mock_headless:
            result = runner.invoke(
                app,
                ["start", "--headless", "--goal", "test goal", "--workers", "2"],
            )

        assert result.exit_code == 0
        assert "--headless` is deprecated" in result.stdout
        mock_headless.assert_called_once()
        kwargs = mock_headless.call_args.kwargs
        assert kwargs["workers"] == 2


def test_run_workers_route_to_research_runtime():
    with runner.isolated_filesystem():
        Path(".git").mkdir()
        result = runner.invoke(app, ["init", "--tag", "clitest"])
        assert result.exit_code == 0

        from unittest.mock import patch

        with patch("open_researcher.run_cmd.do_run", return_value=None) as mock_run:
            result = runner.invoke(app, ["run", "--workers", "1"])

        assert result.exit_code == 0
        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        assert kwargs["workers"] == 1
