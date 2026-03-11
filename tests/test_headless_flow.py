"""Tests for headless bootstrap flow."""

import json
import subprocess
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml


def _make_git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=str(tmp_path), capture_output=True)
    return tmp_path


def _set_bootstrap_auto_prepare(repo_path: Path, enabled: bool) -> None:
    config_path = repo_path / ".research" / "config.yaml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    payload.setdefault("bootstrap", {})
    payload["bootstrap"]["auto_prepare"] = enabled
    config_path.write_text(yaml.dump(payload), encoding="utf-8")


def test_headless_scout_phase(tmp_path):
    """Headless mode should run scout agent and emit structured events."""
    _make_git_repo(tmp_path)

    mock_agent = MagicMock()
    mock_agent.name = "mock-agent"
    mock_agent.run.return_value = 0
    mock_agent.terminate = MagicMock()

    buf = StringIO()

    with patch("open_researcher.headless._resolve_agent", return_value=mock_agent):
        from open_researcher.headless import do_start_headless

        do_start_headless(
            repo_path=tmp_path,
            goal="test goal",
            max_experiments=0,
            agent_name=None,
            tag="test",
            stream=buf,
        )

    output = buf.getvalue()
    lines = [json.loads(line) for line in output.strip().splitlines() if line.strip()]
    events = [r["event"] for r in lines]
    assert "session_started" in events
    assert "scout_started" in events


def test_headless_max_experiments_limit(tmp_path):
    """Headless research-v1 mode should stop after max_experiments."""
    _make_git_repo(tmp_path)

    scout_agent = MagicMock()
    scout_agent.name = "scout"
    scout_agent.terminate = MagicMock()

    def scout_run(workdir, on_output=None, program_file="program.md", env=None):
        _set_bootstrap_auto_prepare(workdir, False)
        return 0

    scout_agent.run.side_effect = scout_run

    manager_agent = MagicMock()
    manager_agent.name = "manager"
    manager_agent.terminate = MagicMock()

    def manager_run(workdir, on_output=None, program_file="program.md", env=None):
        graph_path = workdir / ".research" / "research_graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        if not graph["frontier"]:
            graph["hypotheses"].append({"id": "hyp-001", "summary": "Limit test"})
            graph["experiment_specs"].append({"id": "spec-001", "hypothesis_id": "hyp-001"})
            graph["frontier"].append(
                {
                    "id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "description": "Limit test",
                    "priority": 1,
                    "status": "draft",
                    "claim_state": "candidate",
                }
            )
            graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        return 0

    manager_agent.run.side_effect = manager_run

    critic_agent = MagicMock()
    critic_agent.name = "critic"
    critic_agent.terminate = MagicMock()

    def critic_run(workdir, on_output=None, program_file="program.md", env=None):
        graph_path = workdir / ".research" / "research_graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        for row in graph["frontier"]:
            if row["status"] == "draft":
                row["status"] = "approved"
                graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
                return 0
        return 0

    critic_agent.run.side_effect = critic_run

    exp_agent = MagicMock()
    exp_agent.name = "exp"
    exp_agent.terminate = MagicMock()

    def exp_run(workdir, on_output=None, program_file="program.md", env=None):
        pool_path = workdir / ".research" / "idea_pool.json"
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        for idea in pool["ideas"]:
            if idea["status"] == "pending":
                idea["status"] = "done"
                idea["result"] = {"metric_value": 1.0, "verdict": "kept"}
                idea["finished_at"] = "2026-03-11T10:00:00Z"
        pool_path.write_text(json.dumps(pool, indent=2), encoding="utf-8")
        (workdir / ".research" / "results.tsv").write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
            "2026-03-11T10:00:00Z\tabc123\tmetric\t1.0\t{}\tkeep\tLimit test\n",
            encoding="utf-8",
        )
        return 0

    exp_agent.run.side_effect = exp_run

    buf = StringIO()

    with patch(
        "open_researcher.headless._resolve_agent",
        side_effect=[scout_agent, manager_agent, critic_agent, exp_agent],
    ):
        from open_researcher.headless import do_start_headless

        do_start_headless(
            repo_path=tmp_path,
            goal="test",
            max_experiments=1,
            agent_name=None,
            tag="test",
            workers=1,
            stream=buf,
        )

    output = buf.getvalue()
    lines = [json.loads(line) for line in output.strip().splitlines() if line.strip()]
    events = [r["event"] for r in lines]
    assert "limit_reached" in events


def test_headless_empty_frontier_completes_session(tmp_path):
    """Headless research-v1 should still complete when manager produces no frontier."""
    _make_git_repo(tmp_path)

    mock_agent = MagicMock()
    mock_agent.name = "mock-agent"
    mock_agent.terminate = MagicMock()

    def mock_run(workdir, on_output=None, program_file="program.md", env=None):
        if program_file == "scout_program.md":
            _set_bootstrap_auto_prepare(workdir, False)
        return 0

    mock_agent.run.side_effect = mock_run

    buf = StringIO()

    with patch("open_researcher.headless._resolve_agent", return_value=mock_agent):
        from open_researcher.headless import do_start_headless

        do_start_headless(
            repo_path=tmp_path,
            goal="test empty frontier",
            max_experiments=0,
            agent_name=None,
            tag="test",
            workers=1,
            stream=buf,
        )

    output = buf.getvalue()
    lines = [json.loads(line) for line in output.strip().splitlines() if line.strip()]
    events = [r["event"] for r in lines]
    assert "session_started" in events
    assert "scout_started" in events
    assert "scout_completed" in events
    assert "no_pending_ideas" in events
    assert "session_completed" in events


def test_headless_scout_failure_stops(tmp_path):
    """If scout fails, headless should stop and emit scout_failed."""
    _make_git_repo(tmp_path)

    mock_agent = MagicMock()
    mock_agent.name = "mock-agent"
    mock_agent.run.return_value = 1  # Scout fails
    mock_agent.terminate = MagicMock()

    buf = StringIO()

    with patch("open_researcher.headless._resolve_agent", return_value=mock_agent):
        from open_researcher.headless import do_start_headless

        do_start_headless(
            repo_path=tmp_path,
            goal="test failure",
            max_experiments=0,
            agent_name=None,
            tag="test",
            stream=buf,
        )

    output = buf.getvalue()
    lines = [json.loads(line) for line in output.strip().splitlines() if line.strip()]
    events = [r["event"] for r in lines]
    assert "scout_failed" in events
    assert "session_failed" in events
    assert "session_completed" not in events


def test_headless_research_v1_emits_manager_and_critic_events(tmp_path):
    _make_git_repo(tmp_path)

    from open_researcher.init_cmd import do_init

    do_init(tmp_path, tag="test")
    _set_bootstrap_auto_prepare(tmp_path, False)
    config_path = tmp_path / ".research" / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["research"]["protocol"] = "research-v1"
    config_path.write_text(yaml.dump(config))

    scout_agent = MagicMock()
    scout_agent.name = "scout"
    scout_agent.terminate = MagicMock()

    def scout_run(workdir, on_output=None, program_file="program.md", env=None):
        _set_bootstrap_auto_prepare(workdir, False)
        return 0

    scout_agent.run.side_effect = scout_run

    manager_agent = MagicMock()
    manager_agent.name = "manager"
    manager_agent.terminate = MagicMock()

    def manager_run(workdir, on_output=None, program_file="program.md", env=None):
        graph_path = workdir / ".research" / "research_graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        if not graph["frontier"]:
            graph["hypotheses"].append({"id": "hyp-001", "summary": "Cache parser state"})
            graph["experiment_specs"].append({"id": "spec-001", "hypothesis_id": "hyp-001"})
            graph["frontier"].append(
                {
                    "id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "description": "Cache parser state",
                    "priority": 1,
                    "status": "draft",
                    "claim_state": "candidate",
                }
            )
            graph_path.write_text(json.dumps(graph, indent=2))
        return 0

    manager_agent.run.side_effect = manager_run

    critic_agent = MagicMock()
    critic_agent.name = "critic"
    critic_agent.terminate = MagicMock()

    def critic_run(workdir, on_output=None, program_file="program.md", env=None):
        graph_path = workdir / ".research" / "research_graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        for row in graph["frontier"]:
            if row["status"] == "draft":
                row["status"] = "approved"
                graph_path.write_text(json.dumps(graph, indent=2))
                return 0
            if row["status"] == "needs_post_review":
                row["status"] = "archived"
                row["claim_state"] = "promoted"
                graph["claim_updates"].append(
                    {
                        "id": "claim-001",
                        "hypothesis_id": "hyp-001",
                        "transition": "promote",
                        "confidence": "high",
                    }
                )
                graph_path.write_text(json.dumps(graph, indent=2))
                return 0
        return 0

    critic_agent.run.side_effect = critic_run

    exp_agent = MagicMock()
    exp_agent.name = "exp"
    exp_agent.terminate = MagicMock()

    def exp_run(workdir, on_output=None, program_file="program.md", env=None):
        pool_path = workdir / ".research" / "idea_pool.json"
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        for idea in pool["ideas"]:
            if idea["status"] == "pending":
                idea["status"] = "done"
                idea["result"] = {"metric_value": 1.0, "verdict": "kept"}
                idea["finished_at"] = "2026-03-11T10:00:00Z"
        pool_path.write_text(json.dumps(pool, indent=2))
        (workdir / ".research" / "results.tsv").write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
            "2026-03-11T10:00:00Z\tabc123\tmetric\t1.0\t{}\tkeep\tCache parser state\n"
        )
        return 0

    exp_agent.run.side_effect = exp_run

    buf = StringIO()

    with patch(
        "open_researcher.headless._resolve_agent",
        side_effect=[scout_agent, manager_agent, critic_agent, exp_agent],
    ):
        from open_researcher.headless import do_start_headless

        do_start_headless(
            repo_path=tmp_path,
            goal="test graph protocol",
            max_experiments=1,
            agent_name="codex",
            tag="test",
            workers=1,
            stream=buf,
        )

    lines = [json.loads(line) for line in buf.getvalue().strip().splitlines() if line.strip()]
    events = [row["event"] for row in lines]
    assert "manager_cycle_started" in events
    assert "critic_review_started" in events
    assert "frontier_synced" in events
    assert "evidence_recorded" in events

    frontier_record = next(row for row in lines if row["event"] == "frontier_synced")
    assert frontier_record["items"][0]["frontier_id"] == "frontier-001"
    assert frontier_record["items"][0]["execution_id"].startswith("exec-")
    assert frontier_record["items"][0]["reason_code"] == "manager_refresh"

    started_record = next(row for row in lines if row["event"] == "experiment_started")
    assert started_record["frontier_id"] == "frontier-001"
    assert started_record["execution_id"].startswith("exec-")
    assert started_record["reason_code"] == "manager_refresh"

    completed_record = next(row for row in lines if row["event"] == "experiment_completed")
    assert completed_record["frontier_id"] == "frontier-001"
    assert completed_record["execution_id"] == started_record["execution_id"]
    assert completed_record["reason_code"] == "manager_refresh"

    evidence_record = next(row for row in lines if row["event"] == "evidence_recorded")
    assert evidence_record["items"][0]["frontier_id"] == "frontier-001"
    assert evidence_record["items"][0]["execution_id"] == started_record["execution_id"]
    assert evidence_record["items"][0]["reason_code"] == "result_observed"

    claim_record = next(row for row in lines if row["event"] == "claim_updated")
    assert claim_record["items"][0]["frontier_id"] == "frontier-001"
    assert claim_record["items"][0]["execution_id"] == started_record["execution_id"]
    assert claim_record["items"][0]["reason_code"] == "unspecified"


def test_headless_manager_failure_emits_session_failed(tmp_path):
    _make_git_repo(tmp_path)

    scout_agent = MagicMock()
    scout_agent.name = "scout"
    scout_agent.terminate = MagicMock()

    def scout_run(workdir, on_output=None, program_file="program.md", env=None):
        _set_bootstrap_auto_prepare(workdir, False)
        return 0

    scout_agent.run.side_effect = scout_run

    manager_agent = MagicMock()
    manager_agent.name = "manager"
    manager_agent.run.return_value = 1
    manager_agent.terminate = MagicMock()

    critic_agent = MagicMock()
    critic_agent.name = "critic"
    critic_agent.run.return_value = 0
    critic_agent.terminate = MagicMock()

    exp_agent = MagicMock()
    exp_agent.name = "exp"
    exp_agent.run.return_value = 0
    exp_agent.terminate = MagicMock()

    buf = StringIO()

    with patch(
        "open_researcher.headless._resolve_agent",
        side_effect=[scout_agent, manager_agent, critic_agent, exp_agent],
    ):
        from open_researcher.headless import do_start_headless

        exit_code = do_start_headless(
            repo_path=tmp_path,
            goal="test failure semantics",
            max_experiments=0,
            agent_name=None,
            tag="test",
            stream=buf,
        )

    lines = [json.loads(line) for line in buf.getvalue().strip().splitlines() if line.strip()]
    events = [row["event"] for row in lines]
    assert exit_code == 1
    assert "role_failed" in events
    assert "session_failed" in events
    assert "session_completed" not in events


def test_headless_experiment_failure_emits_session_failed(tmp_path):
    _make_git_repo(tmp_path)

    scout_agent = MagicMock()
    scout_agent.name = "scout"
    scout_agent.run.return_value = 0
    scout_agent.terminate = MagicMock()

    manager_agent = MagicMock()
    manager_agent.name = "manager"
    manager_agent.terminate = MagicMock()

    def manager_run(workdir, on_output=None, program_file="program.md", env=None):
        graph_path = workdir / ".research" / "research_graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        if not graph["frontier"]:
            graph["hypotheses"] = [{"id": "hyp-001", "summary": "Failing exp"}]
            graph["experiment_specs"] = [{"id": "spec-001", "hypothesis_id": "hyp-001"}]
            graph["frontier"] = [
                {
                    "id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "description": "Failing exp",
                    "priority": 1,
                    "status": "draft",
                    "claim_state": "candidate",
                }
            ]
            graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        return 0

    manager_agent.run.side_effect = manager_run

    critic_agent = MagicMock()
    critic_agent.name = "critic"
    critic_agent.terminate = MagicMock()

    def critic_run(workdir, on_output=None, program_file="program.md", env=None):
        graph_path = workdir / ".research" / "research_graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        for row in graph["frontier"]:
            if row["status"] == "draft":
                row["status"] = "approved"
        graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        return 0

    critic_agent.run.side_effect = critic_run

    exp_agent = MagicMock()
    exp_agent.name = "exp"
    exp_agent.run.return_value = 1
    exp_agent.terminate = MagicMock()

    buf = StringIO()

    with patch(
        "open_researcher.headless._resolve_agent",
        side_effect=[scout_agent, manager_agent, critic_agent, exp_agent],
    ):
        from open_researcher.headless import do_start_headless

        exit_code = do_start_headless(
            repo_path=tmp_path,
            goal="test exp failure",
            max_experiments=1,
            agent_name=None,
            tag="test",
            stream=buf,
        )

    lines = [json.loads(line) for line in buf.getvalue().strip().splitlines() if line.strip()]
    events = [row["event"] for row in lines]
    assert exit_code == 1
    assert "role_failed" in events
    assert "session_failed" in events
    assert "session_completed" not in events


def test_do_run_headless_continues_existing_workspace_without_scout(tmp_path):
    _make_git_repo(tmp_path)

    from open_researcher.init_cmd import do_init

    do_init(tmp_path, tag="test")
    _set_bootstrap_auto_prepare(tmp_path, False)
    (tmp_path / ".research" / "goal.md").write_text("# Research Goal\n\nContinue existing run.\n", encoding="utf-8")

    manager_agent = MagicMock()
    manager_agent.name = "manager"
    manager_agent.terminate = MagicMock()

    def manager_run(workdir, on_output=None, program_file="program.md", env=None):
        graph_path = workdir / ".research" / "research_graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        graph["hypotheses"] = [{"id": "hyp-001", "summary": "Continue workspace"}]
        graph["experiment_specs"] = [{"id": "spec-001", "hypothesis_id": "hyp-001"}]
        graph["frontier"] = [
            {
                "id": "frontier-001",
                "idea_id": "idea-001",
                "hypothesis_id": "hyp-001",
                "experiment_spec_id": "spec-001",
                "description": "Continue workspace",
                "priority": 1,
                "status": "approved",
                "claim_state": "candidate",
            }
        ]
        graph_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        return 0

    manager_agent.run.side_effect = manager_run

    critic_agent = MagicMock()
    critic_agent.name = "critic"
    critic_agent.run.return_value = 0
    critic_agent.terminate = MagicMock()

    exp_agent = MagicMock()
    exp_agent.name = "exp"
    exp_agent.terminate = MagicMock()

    def exp_run(workdir, on_output=None, program_file="program.md", env=None):
        pool_path = workdir / ".research" / "idea_pool.json"
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        for idea in pool["ideas"]:
            idea["status"] = "done"
            idea["finished_at"] = "2026-03-11T11:00:00Z"
            idea["result"] = {"metric_value": 1.0, "verdict": "kept"}
        pool_path.write_text(json.dumps(pool, indent=2), encoding="utf-8")
        (workdir / ".research" / "results.tsv").write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
            "2026-03-11T11:00:00Z\tabc123\tmetric\t1.0\t{}\tkeep\tContinue workspace\n",
            encoding="utf-8",
        )
        return 0

    exp_agent.run.side_effect = exp_run

    buf = StringIO()

    with patch(
        "open_researcher.headless._resolve_agent",
        side_effect=[manager_agent, critic_agent, exp_agent],
    ):
        from open_researcher.headless import do_run_headless

        exit_code = do_run_headless(
            repo_path=tmp_path,
            max_experiments=1,
            agent_name=None,
            workers=1,
            stream=buf,
        )

    lines = [json.loads(line) for line in buf.getvalue().strip().splitlines() if line.strip()]
    events = [row["event"] for row in lines]
    assert exit_code == 0
    assert "session_started" in events
    assert "scout_started" not in events
    assert "session_completed" in events
