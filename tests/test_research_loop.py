"""Tests for the core research loop extraction."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from open_researcher.config import ResearchConfig
from open_researcher.control_plane import issue_control_command
from open_researcher.research_events import (
    AllIdeasProcessed,
    ClaimUpdated,
    CriticReviewStarted,
    EvidenceRecorded,
    ExperimentCompleted,
    ExperimentPreflightFailed,
    ExperimentStarted,
    FrontierSynced,
    HypothesisProposed,
    ManagerCycleStarted,
    MemoryUpdated,
    NoPendingIdeas,
)
from open_researcher.research_graph import ResearchGraphStore
from open_researcher.research_loop import ResearchLoop


def _setup_repo(tmp_path: Path) -> tuple[Path, Path]:
    research = tmp_path / ".research"
    research.mkdir()
    (research / "experiment_program.md").write_text("# experiment")
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    )
    (research / "idea_pool.json").write_text(json.dumps({"ideas": []}, indent=2))
    return tmp_path, research


def test_run_graph_protocol_emits_graph_events_and_updates_memory(tmp_path):
    repo_path, research = _setup_repo(tmp_path)
    (research / "manager_program.md").write_text("# manager")
    (research / "critic_program.md").write_text("# critic")
    graph_store = ResearchGraphStore(research / "research_graph.json")
    graph_store.ensure_exists()

    cfg = ResearchConfig(protocol="research-v1", primary_metric="accuracy", direction="higher_is_better")
    events = []

    manager_agent = MagicMock()
    critic_agent = MagicMock()
    exp_agent = MagicMock()

    manager_calls = {"count": 0}

    def manager_run(workdir, on_output=None, program_file="program.md", **kwargs):
        manager_calls["count"] += 1
        graph = graph_store.read()
        if manager_calls["count"] == 1:
            graph["hypotheses"].append({"id": "hyp-001", "summary": "Cache hot path lookups"})
            graph["experiment_specs"].append({"id": "spec-001", "hypothesis_id": "hyp-001"})
            graph["frontier"].append(
                {
                    "id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "description": "Cache hot path lookups",
                    "priority": 1,
                    "status": "draft",
                    "claim_state": "candidate",
                }
            )
            graph_store.path.write_text(json.dumps(graph, indent=2))
        return 0

    def critic_run(workdir, on_output=None, program_file="program.md", **kwargs):
        graph = graph_store.read()
        draft_rows = [item for item in graph["frontier"] if item["status"] == "draft"]
        if draft_rows:
            draft_rows[0]["status"] = "approved"
            graph_store.path.write_text(json.dumps(graph, indent=2))
            return 0

        review_rows = [item for item in graph["frontier"] if item["status"] == "needs_post_review"]
        if review_rows:
            review_rows[0]["status"] = "archived"
            review_rows[0]["claim_state"] = "promoted"
            review_rows[0]["repro_required"] = False
            graph["claim_updates"].append(
                {
                    "id": "claim-001",
                    "hypothesis_id": "hyp-001",
                    "transition": "promote",
                    "confidence": "high",
                }
            )
            graph_store.path.write_text(json.dumps(graph, indent=2))
        return 0

    def exp_run(workdir, on_output=None, program_file="program.md", **kwargs):
        pool_path = workdir / ".research" / "idea_pool.json"
        pool = json.loads(pool_path.read_text(encoding="utf-8"))
        for idea in pool["ideas"]:
            if idea["status"] == "pending":
                idea["status"] = "done"
                idea["result"] = {"metric_value": 0.91, "verdict": "kept"}
                idea["finished_at"] = "2026-03-11T10:00:00Z"
        pool_path.write_text(json.dumps(pool, indent=2))
        (workdir / ".research" / "results.tsv").write_text(
            "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
            "2026-03-11T10:00:00Z\tabc123\taccuracy\t0.91\t{}\tkeep\tCache hot path lookups\n"
        )
        return 0

    manager_agent.run.side_effect = manager_run
    critic_agent.run.side_effect = critic_run
    exp_agent.run.side_effect = exp_run

    loop = ResearchLoop(repo_path, research, cfg, events.append)
    exit_codes = loop.run_graph_protocol(manager_agent, critic_agent, exp_agent)

    assert exit_codes == {"manager": 0, "critic": 0, "exp": 0}
    event_types = [type(event) for event in events if not hasattr(event, "detail")]
    assert ManagerCycleStarted in event_types
    assert HypothesisProposed in event_types
    assert CriticReviewStarted in event_types
    assert FrontierSynced in event_types
    assert ExperimentStarted in event_types
    assert ExperimentCompleted in event_types
    assert EvidenceRecorded in event_types
    assert ClaimUpdated in event_types
    assert MemoryUpdated in event_types
    assert NoPendingIdeas in event_types
    assert AllIdeasProcessed in event_types

    hypothesis_event = next(event for event in events if isinstance(event, HypothesisProposed))
    assert hypothesis_event.hypothesis_ids == ["hyp-001"]

    frontier_event = next(event for event in events if isinstance(event, FrontierSynced))
    assert frontier_event.items
    assert frontier_event.items[0]["frontier_id"] == "frontier-001"
    assert frontier_event.items[0]["execution_id"].startswith("exec-")
    assert frontier_event.items[0]["reason_code"] == "manager_refresh"

    started_event = next(event for event in events if isinstance(event, ExperimentStarted))
    assert started_event.frontier_id == "frontier-001"
    assert started_event.idea_id == "idea-001"
    assert started_event.execution_id.startswith("exec-")
    assert started_event.selection_reason_code == "manager_refresh"

    completed_event = next(event for event in events if isinstance(event, ExperimentCompleted))
    assert completed_event.frontier_id == "frontier-001"
    assert completed_event.execution_id == started_event.execution_id

    evidence_event = next(event for event in events if isinstance(event, EvidenceRecorded))
    assert evidence_event.items
    assert evidence_event.items[0]["frontier_id"] == "frontier-001"
    assert evidence_event.items[0]["execution_id"] == started_event.execution_id
    assert evidence_event.items[0]["reason_code"] == "result_observed"

    claim_event = next(event for event in events if isinstance(event, ClaimUpdated))
    assert claim_event.items
    assert claim_event.items[0]["frontier_id"] == "frontier-001"
    assert claim_event.items[0]["execution_id"] == started_event.execution_id
    assert claim_event.items[0]["reason_code"] == "unspecified"


def test_run_graph_protocol_emits_preflight_rejection_trace(tmp_path):
    repo_path, research = _setup_repo(tmp_path)
    (research / "manager_program.md").write_text("# manager")
    (research / "critic_program.md").write_text("# critic")
    graph_store = ResearchGraphStore(research / "research_graph.json")
    graph_store.ensure_exists()

    cfg = ResearchConfig(protocol="research-v1")
    events = []

    manager_agent = MagicMock()
    critic_agent = MagicMock()
    exp_agent = MagicMock()

    def manager_run(workdir, on_output=None, program_file="program.md", **kwargs):
        graph = graph_store.read()
        if not graph["frontier"]:
            graph["hypotheses"].append({"id": "hyp-001", "summary": "Reject me"})
            graph["experiment_specs"].append({"id": "spec-001", "hypothesis_id": "hyp-001"})
            graph["frontier"].append(
                {
                    "id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "description": "Reject me",
                    "priority": 1,
                    "status": "draft",
                    "claim_state": "candidate",
                }
            )
            graph_store.path.write_text(json.dumps(graph, indent=2))
        return 0

    def critic_run(workdir, on_output=None, program_file="program.md", **kwargs):
        graph = graph_store.read()
        graph["frontier"][0]["status"] = "rejected"
        graph["frontier"][0]["review_reason_code"] = "no_eval_plan"
        graph_store.path.write_text(json.dumps(graph, indent=2))
        return 0

    manager_agent.run.side_effect = manager_run
    critic_agent.run.side_effect = critic_run
    exp_agent.run.return_value = 0

    loop = ResearchLoop(repo_path, research, cfg, events.append)
    exit_codes = loop.run_graph_protocol(manager_agent, critic_agent, exp_agent)

    assert exit_codes == {"manager": 0, "critic": 0}
    rejected_event = next(event for event in events if isinstance(event, ExperimentPreflightFailed))
    assert rejected_event.items
    assert rejected_event.items[0]["frontier_id"] == "frontier-001"
    assert rejected_event.items[0]["reason_code"] == "no_eval_plan"


def test_run_graph_protocol_marks_bare_nonzero_experiment_as_failure(tmp_path):
    repo_path, research = _setup_repo(tmp_path)
    (research / "manager_program.md").write_text("# manager")
    (research / "critic_program.md").write_text("# critic")
    graph_store = ResearchGraphStore(research / "research_graph.json")
    graph_store.ensure_exists()

    cfg = ResearchConfig(protocol="research-v1")
    events = []

    manager_agent = MagicMock()
    critic_agent = MagicMock()
    exp_agent = MagicMock()

    def manager_run(workdir, on_output=None, program_file="program.md", **kwargs):
        graph = graph_store.read()
        if not graph["frontier"]:
            graph["hypotheses"] = [{"id": "hyp-001", "summary": "Crashy experiment"}]
            graph["experiment_specs"] = [{"id": "spec-001", "hypothesis_id": "hyp-001", "summary": "Crashy experiment"}]
            graph["frontier"] = [
                {
                    "id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "description": "Crashy experiment",
                    "priority": 1,
                    "status": "draft",
                    "claim_state": "candidate",
                }
            ]
            graph_store.path.write_text(json.dumps(graph, indent=2))
        return 0

    def critic_run(workdir, on_output=None, program_file="program.md", **kwargs):
        graph = graph_store.read()
        if graph["frontier"] and graph["frontier"][0]["status"] == "draft":
            graph["frontier"][0]["status"] = "approved"
            graph_store.path.write_text(json.dumps(graph, indent=2))
            return 0
        if graph["frontier"] and graph["frontier"][0]["status"] == "needs_post_review":
            graph["frontier"][0]["status"] = "archived"
            graph_store.path.write_text(json.dumps(graph, indent=2))
        return 0

    manager_agent.run.side_effect = manager_run
    critic_agent.run.side_effect = critic_run
    exp_agent.run.return_value = 1

    loop = ResearchLoop(repo_path, research, cfg, events.append)
    exit_codes = loop.run_graph_protocol(manager_agent, critic_agent, exp_agent, max_experiments=1)

    graph = graph_store.read()
    assert exit_codes["exp"] == 1
    assert loop.had_experiment_failure is True
    assert graph["frontier"][0]["terminal_status"] == "skipped"
    assert any("marked the claimed backlog item as skipped/crash" in getattr(event, "detail", "") for event in events)


def test_run_graph_protocol_consumes_skip_current_before_serial_experiment(tmp_path):
    repo_path, research = _setup_repo(tmp_path)
    (research / "manager_program.md").write_text("# manager")
    (research / "critic_program.md").write_text("# critic")
    graph_store = ResearchGraphStore(research / "research_graph.json")
    graph_store.ensure_exists()

    cfg = ResearchConfig(protocol="research-v1")
    events = []

    manager_agent = MagicMock()
    critic_agent = MagicMock()
    exp_agent = MagicMock()

    def manager_run(workdir, on_output=None, program_file="program.md", **kwargs):
        graph = graph_store.read()
        if not graph["frontier"]:
            graph["hypotheses"] = [{"id": "hyp-001", "summary": "Skip me"}]
            graph["experiment_specs"] = [{"id": "spec-001", "hypothesis_id": "hyp-001", "summary": "Skip me"}]
            graph["frontier"] = [
                {
                    "id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "description": "Skip me",
                    "priority": 1,
                    "status": "draft",
                    "claim_state": "candidate",
                }
            ]
            graph_store.path.write_text(json.dumps(graph, indent=2))
        return 0

    def critic_run(workdir, on_output=None, program_file="program.md", **kwargs):
        graph = graph_store.read()
        if graph["frontier"] and graph["frontier"][0]["status"] == "draft":
            graph["frontier"][0]["status"] = "approved"
            graph_store.path.write_text(json.dumps(graph, indent=2))
            return 0
        if graph["frontier"] and graph["frontier"][0]["status"] == "needs_post_review":
            graph["frontier"][0]["status"] = "archived"
            graph_store.path.write_text(json.dumps(graph, indent=2))
        return 0

    manager_agent.run.side_effect = manager_run
    critic_agent.run.side_effect = critic_run
    exp_agent.run.return_value = 0

    issue_control_command(research / "control.json", command="skip_current", source="test")

    loop = ResearchLoop(repo_path, research, cfg, events.append)
    exit_codes = loop.run_graph_protocol(manager_agent, critic_agent, exp_agent, max_experiments=1)

    pool = json.loads((research / "idea_pool.json").read_text(encoding="utf-8"))
    assert exit_codes == {"manager": 0, "critic": 0}
    assert exp_agent.run.call_count == 0
    assert pool["ideas"] == []
    assert any("skip_current" in getattr(event, "detail", "") for event in events)


def test_run_graph_protocol_waits_for_resume_before_manager_cycle(tmp_path):
    repo_path, research = _setup_repo(tmp_path)
    (research / "manager_program.md").write_text("# manager")
    (research / "critic_program.md").write_text("# critic")
    graph_store = ResearchGraphStore(research / "research_graph.json")
    graph_store.ensure_exists()

    cfg = ResearchConfig(protocol="research-v1")
    events = []

    manager_agent = MagicMock()
    critic_agent = MagicMock()
    exp_agent = MagicMock()
    manager_started = threading.Event()

    def manager_run(workdir, on_output=None, program_file="program.md", **kwargs):
        manager_started.set()
        graph = graph_store.read()
        graph["hypotheses"] = []
        graph_store.path.write_text(json.dumps(graph, indent=2))
        return 0

    manager_agent.run.side_effect = manager_run
    critic_agent.run.return_value = 0
    exp_agent.run.return_value = 0

    issue_control_command(research / "control.json", command="pause", source="test")

    loop = ResearchLoop(repo_path, research, cfg, events.append)
    stop = threading.Event()
    thread = threading.Thread(
        target=lambda: loop.run_graph_protocol(manager_agent, critic_agent, exp_agent, stop=stop),
        daemon=True,
    )
    thread.start()
    time.sleep(0.3)
    assert manager_started.is_set() is False

    issue_control_command(research / "control.json", command="resume", source="test")
    thread.join(timeout=5)
    assert manager_started.is_set() is True


def test_run_graph_protocol_bootstraps_parallel_baseline_before_worker_batch(tmp_path):
    repo_path, research = _setup_repo(tmp_path)
    (research / "manager_program.md").write_text("# manager")
    (research / "critic_program.md").write_text("# critic")
    (research / "experiment_progress.json").write_text(json.dumps({"phase": "init"}))
    graph_store = ResearchGraphStore(research / "research_graph.json")
    graph_store.ensure_exists()

    cfg = ResearchConfig(
        protocol="research-v1",
        max_workers=4,
        primary_metric="speedup_ratio",
        direction="higher_is_better",
    )
    events = []

    manager_agent = MagicMock()
    critic_agent = MagicMock()
    exp_agent = MagicMock()
    parallel_calls = []

    def manager_run(workdir, on_output=None, program_file="program.md", **kwargs):
        graph = graph_store.read()
        if not graph["frontier"]:
            graph["hypotheses"] = [{"id": "hyp-001", "summary": "Bootstrap parallel baseline"}]
            graph["experiment_specs"] = [
                {
                    "id": "spec-001",
                    "hypothesis_id": "hyp-001",
                    "summary": "Bootstrap parallel baseline",
                }
            ]
            graph["frontier"] = [
                {
                    "id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "description": "Bootstrap parallel baseline",
                    "priority": 1,
                    "status": "draft",
                    "claim_state": "candidate",
                }
            ]
            graph_store.path.write_text(json.dumps(graph, indent=2))
        return 0

    def critic_run(workdir, on_output=None, program_file="program.md", **kwargs):
        graph = graph_store.read()
        if graph["frontier"] and graph["frontier"][0]["status"] == "draft":
            graph["frontier"][0]["status"] = "approved"
            graph_store.path.write_text(json.dumps(graph, indent=2))
        return 0

    def exp_run(workdir, on_output=None, program_file="program.md", **kwargs):
        progress = research / "experiment_progress.json"
        payload = json.loads(progress.read_text())
        if payload.get("phase") != "experimenting":
            progress.write_text(json.dumps({"phase": "experimenting"}))
        return 0

    def parallel_batch_runner(**kwargs):
        parallel_calls.append(json.loads((research / "experiment_progress.json").read_text())["phase"])
        return {
            "experiments_completed": 1,
            "exit_code": 0,
            "failed_runs": 0,
            "started_runs": 1,
            "fatal_errors": 0,
            "running_after": 0,
        }

    manager_agent.run.side_effect = manager_run
    critic_agent.run.side_effect = critic_run
    exp_agent.run.side_effect = exp_run

    loop = ResearchLoop(repo_path, research, cfg, events.append)
    exit_codes = loop.run_graph_protocol(
        manager_agent,
        critic_agent,
        exp_agent,
        max_experiments=1,
        parallel_batch_runner=parallel_batch_runner,
    )

    assert exit_codes == {"manager": 0, "critic": 0, "exp": 0}
    assert parallel_calls == ["experimenting"]
    assert exp_agent.run.call_count == 1
