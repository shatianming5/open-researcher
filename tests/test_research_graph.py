"""Tests for research-v1 state stores and compatibility projections."""

import json

from paperfarm.research_graph import ResearchGraphStore
from paperfarm.research_memory import ResearchMemoryStore


def test_graph_store_syncs_executable_frontier_to_idea_pool(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    graph_path = research / "research_graph.json"
    pool_path = research / "idea_pool.json"
    pool_path.write_text(json.dumps({"ideas": []}))

    store = ResearchGraphStore(graph_path)
    store.ensure_exists()
    payload = store.read()
    payload["hypotheses"] = [{"id": "hyp-001", "summary": "Benchmark parser throughput"}]
    payload["experiment_specs"] = [
        {
            "id": "spec-001",
            "hypothesis_id": "hyp-001",
            "summary": "Benchmark parser throughput",
            "change_plan": "Add parser cache around manifest reads",
            "evaluation_plan": "Run throughput benchmark once after warm cache priming",
            "attribution_focus": "parser read path",
            "expected_signal": "lower request latency",
            "risk_level": "low",
        }
    ]
    payload["frontier"] = [
        {
            "id": "frontier-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "description": "Benchmark parser throughput",
            "priority": 1,
            "status": "approved",
            "claim_state": "candidate",
            "selection_reason_code": "initial_frontier",
        }
    ]
    graph_path.write_text(json.dumps(payload, indent=2))

    result = store.sync_idea_pool(pool_path)

    data = json.loads(pool_path.read_text(encoding="utf-8"))
    assert result["frontier_items"] == 1
    assert data["ideas"][0]["status"] == "pending"
    assert data["ideas"][0]["protocol"] == "research-v1"
    assert data["ideas"][0]["frontier_id"] == "frontier-001"
    assert data["ideas"][0]["execution_id"].startswith("exec-")
    assert data["ideas"][0]["hypothesis_id"] == "hyp-001"
    assert data["ideas"][0]["experiment_spec_id"] == "spec-001"
    assert data["ideas"][0]["change_plan"] == "Add parser cache around manifest reads"
    assert data["ideas"][0]["expected_signal"] == "lower request latency"
    assert data["ideas"][0]["selection_reason_code"] == "initial_frontier"


def test_graph_store_absorbs_completed_idea_into_evidence(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    graph_path = research / "research_graph.json"
    pool_path = research / "idea_pool.json"
    store = ResearchGraphStore(graph_path)
    store.ensure_exists()
    payload = store.read()
    payload["hypotheses"] = [{"id": "hyp-001", "summary": "Speed up parser"}]
    payload["experiment_specs"] = [{"id": "spec-001", "hypothesis_id": "hyp-001", "summary": "Tighten cache lookups"}]
    payload["frontier"] = [
        {
            "id": "frontier-001",
            "idea_id": "idea-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "description": "Speed up parser",
            "priority": 1,
            "status": "approved",
            "claim_state": "candidate",
        }
    ]
    graph_path.write_text(json.dumps(payload, indent=2))
    pool_path.write_text(
        json.dumps(
            {
                "ideas": [
                    {
                        "id": "idea-001",
                        "description": "Speed up parser",
                        "status": "done",
                        "priority": 1,
                        "source": "graph",
                        "category": "graph",
                        "gpu_hint": "auto",
                        "result": {"metric_value": 2.5, "verdict": "kept"},
                        "finished_at": "2026-03-11T10:00:00Z",
                        "hypothesis_id": "hyp-001",
                        "experiment_spec_id": "spec-001",
                    }
                ]
            },
            indent=2,
        )
    )

    result = store.absorb_experiment_outcomes(
        pool_path,
        [
            {
                "timestamp": "2026-03-11T10:00:00Z",
                "commit": "abc123",
                "primary_metric": "throughput",
                "metric_value": "2.5",
                "secondary_metrics": "",
                "status": "keep",
                "description": "Speed up parser",
            }
        ],
        primary_metric="throughput",
        direction="higher_is_better",
    )

    graph = store.read()
    assert result["evidence_created"] == 1
    assert graph["evidence"][0]["experiment_spec_id"] == "spec-001"
    assert graph["evidence"][0]["execution_id"] == "exec-001"
    assert graph["evidence"][0]["frontier_id"] == "frontier-001"
    assert graph["evidence"][0]["reason_code"] == "result_observed"
    assert graph["frontier"][0]["status"] == "needs_post_review"
    assert graph["frontier"][0]["last_execution_id"] == "exec-001"
    assert graph["frontier"][0]["active_execution_id"] == ""


def test_memory_store_absorbs_graph_claims_and_evidence(tmp_path):
    memory = ResearchMemoryStore(tmp_path / "research_memory.json")
    memory.ensure_exists()

    result = memory.absorb_graph(
        {
            "repo_profile": {
                "profile_key": "python-cli",
                "task_family": "general_code",
                "primary_metric": "tests",
                "direction": "higher_is_better",
            },
            "frontier": [
                {
                    "id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "family_key": "fam-demo1234",
                }
            ],
            "hypotheses": [{"id": "hyp-001", "summary": "Cache manifest reads"}],
            "evidence": [
                {
                    "id": "evi-001",
                    "frontier_id": "frontier-001",
                    "execution_id": "exec-001",
                    "experiment_spec_id": "spec-001",
                    "description": "manifest cache",
                    "reliability": "strong",
                    "reason_code": "benchmark_delta",
                    "status": "keep",
                    "primary_metric": "tests",
                    "metric_value": 1.0,
                }
            ],
            "claim_updates": [
                {
                    "id": "claim-001",
                    "frontier_id": "frontier-001",
                    "hypothesis_id": "hyp-001",
                    "experiment_spec_id": "spec-001",
                    "execution_id": "exec-001",
                    "transition": "promote",
                    "confidence": "high",
                    "reason_code": "supported_by_strong_evidence",
                }
            ],
        }
    )

    payload = memory.read()
    assert result["repo_type_priors"] == 1
    assert payload["ideation_memory"][0]["outcome"] == "promote"
    assert payload["ideation_memory"][0]["family_key"] == "fam-demo1234"
    assert payload["ideation_memory"][0]["reason_code"] == "supported_by_strong_evidence"
    assert payload["experiment_memory"][0]["reliability"] == "strong"
    assert payload["experiment_memory"][0]["family_key"] == "fam-demo1234"
    assert payload["experiment_memory"][0]["reason_code"] == "benchmark_delta"


def test_graph_store_normalizes_invalid_frontier_and_claim_fields(tmp_path):
    graph_path = tmp_path / "research_graph.json"
    store = ResearchGraphStore(graph_path)
    store.ensure_exists()
    payload = store.read()
    payload["hypotheses"] = [{"id": "hyp-001", "summary": "Tighten cache lookups"}]
    payload["experiment_specs"] = [
        {
            "id": "spec-001",
            "hypothesis_id": "hyp-001",
            "summary": "Tighten cache lookups",
        }
    ]
    payload["frontier"] = [
        {
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "priority": "0",
            "status": "unknown-status",
            "claim_state": "wild",
            "scores": {"expected_value": 9, "cost": 0},
        }
    ]
    payload["claim_updates"] = [
        {
            "id": "claim-001",
            "hypothesis_id": "hyp-001",
            "transition": "mystery",
        }
    ]
    graph_path.write_text(json.dumps(payload, indent=2))

    normalized = store.read()

    assert normalized["frontier"][0]["id"].startswith("frontier-")
    assert normalized["frontier"][0]["description"] == "Tighten cache lookups"
    assert normalized["frontier"][0]["status"] == "draft"
    assert normalized["frontier"][0]["claim_state"] == "candidate"
    assert normalized["frontier"][0]["priority"] == 1
    assert normalized["frontier"][0]["scores"]["expected_value"] == 5
    assert normalized["frontier"][0]["scores"]["cost"] == 1
    assert normalized["claim_updates"][0]["transition"] == "needs_repro"
    assert normalized["frontier"][0]["selection_reason_code"] == "manager_refresh"
    assert normalized["frontier"][0]["review_reason_code"] == "unspecified"
    assert normalized["claim_updates"][0]["reason_code"] == "unspecified"


def test_graph_store_sync_respects_manager_batch_size_projection(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    graph_path = research / "research_graph.json"
    pool_path = research / "idea_pool.json"
    pool_path.write_text(json.dumps({"ideas": []}))

    store = ResearchGraphStore(graph_path)
    store.ensure_exists()
    payload = store.read()
    payload["hypotheses"] = [
        {"id": "hyp-001", "summary": "A"},
        {"id": "hyp-002", "summary": "B"},
    ]
    payload["experiment_specs"] = [
        {"id": "spec-001", "hypothesis_id": "hyp-001", "summary": "A"},
        {"id": "spec-002", "hypothesis_id": "hyp-002", "summary": "B"},
    ]
    payload["frontier"] = [
        {
            "id": "frontier-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "description": "A",
            "priority": 1,
            "status": "approved",
            "claim_state": "candidate",
        },
        {
            "id": "frontier-002",
            "hypothesis_id": "hyp-002",
            "experiment_spec_id": "spec-002",
            "description": "B",
            "priority": 2,
            "status": "approved",
            "claim_state": "candidate",
        },
    ]
    graph_path.write_text(json.dumps(payload, indent=2))

    result = store.sync_idea_pool(pool_path, max_items=1)

    projected = json.loads(pool_path.read_text(encoding="utf-8"))
    assert result["frontier_items"] == 1
    assert len(projected["ideas"]) == 1
    assert projected["ideas"][0]["frontier_id"] == "frontier-001"
    assert len(store.read()["frontier"]) == 2


def test_graph_store_applies_history_policy_before_projection(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    graph_path = research / "research_graph.json"
    pool_path = research / "idea_pool.json"
    pool_path.write_text(json.dumps({"ideas": []}))

    store = ResearchGraphStore(graph_path)
    store.ensure_exists()
    payload = store.read()
    payload["hypotheses"] = [{"id": "hyp-001", "summary": "Seed locking reduces variance"}]
    payload["experiment_specs"] = [
        {
            "id": "spec-001",
            "hypothesis_id": "hyp-001",
            "summary": "Run fixed-seed benchmark",
            "attribution_focus": "evaluation stability",
            "expected_signal": "variance down",
        },
        {
            "id": "spec-002",
            "hypothesis_id": "hyp-001",
            "summary": "Run fixed-seed benchmark",
            "attribution_focus": "evaluation stability",
            "expected_signal": "variance down",
        },
    ]
    payload["frontier"] = [
        {
            "id": "frontier-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "description": "Reproduce the fixed-seed win",
            "priority": 2,
            "status": "needs_repro",
            "claim_state": "needs_repro",
            "repro_required": True,
        },
        {
            "id": "frontier-002",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-002",
            "description": "Try another shallow variant",
            "priority": 1,
            "status": "approved",
            "claim_state": "candidate",
        },
    ]
    graph_path.write_text(json.dumps(payload, indent=2))

    policy = store.apply_history_policy({"ideation_memory": [], "experiment_memory": []})
    result = store.sync_idea_pool(pool_path, max_items=1)
    graph = store.read()
    projected = json.loads(pool_path.read_text(encoding="utf-8"))

    assert policy["updated"] == 1
    assert graph["frontier"][1]["policy_state"] == "prefer_repro"
    assert graph["frontier"][1]["runtime_priority"] == 3
    assert result["frontier_items"] == 1
    assert projected["ideas"][0]["frontier_id"] == "frontier-001"
    assert projected["ideas"][0]["priority"] == 2
    assert projected["ideas"][0]["runtime_priority"] == 2


def test_graph_store_drops_orphan_evidence_and_claim_rows(tmp_path):
    graph_path = tmp_path / "research_graph.json"
    store = ResearchGraphStore(graph_path)
    store.ensure_exists()
    payload = store.read()
    payload["evidence"] = [
        {
            "id": "evi-001",
            "frontier_id": "missing-frontier",
            "hypothesis_id": "missing-hypothesis",
            "experiment_spec_id": "missing-spec",
        }
    ]
    payload["claim_updates"] = [
        {
            "id": "claim-001",
            "frontier_id": "missing-frontier",
            "hypothesis_id": "missing-hypothesis",
            "experiment_spec_id": "missing-spec",
            "transition": "promote",
        }
    ]
    graph_path.write_text(json.dumps(payload, indent=2))

    normalized = store.read()

    assert normalized["evidence"] == []
    assert normalized["claim_updates"] == []


def test_graph_store_marks_new_best_for_repro_request(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    graph_path = research / "research_graph.json"
    pool_path = research / "idea_pool.json"
    store = ResearchGraphStore(graph_path)
    store.ensure_exists()
    payload = store.read()
    payload["hypotheses"] = [{"id": "hyp-001", "summary": "Speed up parser"}]
    payload["experiment_specs"] = [{"id": "spec-001", "hypothesis_id": "hyp-001", "summary": "Parser cache"}]
    payload["frontier"] = [
        {
            "id": "frontier-001",
            "idea_id": "idea-001",
            "active_execution_id": "exec-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "description": "Speed up parser",
            "priority": 1,
            "status": "approved",
            "claim_state": "candidate",
        }
    ]
    graph_path.write_text(json.dumps(payload, indent=2))
    pool_path.write_text(
        json.dumps(
            {
                "ideas": [
                    {
                        "id": "idea-001",
                        "frontier_id": "frontier-001",
                        "execution_id": "exec-001",
                        "description": "Speed up parser",
                        "status": "done",
                        "priority": 1,
                        "result": {"metric_value": 2.5, "verdict": "kept"},
                        "finished_at": "2026-03-11T10:00:00Z",
                        "hypothesis_id": "hyp-001",
                        "experiment_spec_id": "spec-001",
                    }
                ]
            },
            indent=2,
        )
    )

    trace = {
        "_open_researcher_trace": {
            "frontier_id": "frontier-001",
            "idea_id": "idea-001",
            "execution_id": "exec-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
        }
    }
    result = store.absorb_experiment_outcomes(
        pool_path,
        [
            {
                "timestamp": "2026-03-10T10:00:00Z",
                "commit": "base123",
                "primary_metric": "throughput",
                "metric_value": "1.0",
                "secondary_metrics": "{}",
                "status": "keep",
                "description": "baseline",
            },
            {
                "timestamp": "2026-03-11T10:00:00Z",
                "commit": "abc123",
                "primary_metric": "throughput",
                "metric_value": "2.5",
                "secondary_metrics": json.dumps(trace),
                "status": "keep",
                "description": "Speed up parser",
            },
        ],
        primary_metric="throughput",
        direction="higher_is_better",
        repro_policy="best_or_surprising",
    )

    graph = store.read()
    assert result["evidence_created"] == 1
    assert graph["frontier"][0]["repro_required"] is True
    assert graph["frontier"][0]["status"] == "needs_post_review"


def test_graph_store_normalizes_non_numeric_priority_without_crashing(tmp_path):
    graph_path = tmp_path / "research_graph.json"
    store = ResearchGraphStore(graph_path)
    store.ensure_exists()
    payload = store.read()
    payload["hypotheses"] = [{"id": "hyp-001", "summary": "Priority fallback"}]
    payload["experiment_specs"] = [{"id": "spec-001", "hypothesis_id": "hyp-001", "summary": "Priority fallback"}]
    payload["frontier"] = [
        {
            "id": "frontier-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "priority": "high",
            "status": "approved",
            "claim_state": "candidate",
        }
    ]
    graph_path.write_text(json.dumps(payload, indent=2))

    normalized = store.read()

    assert normalized["frontier"][0]["priority"] == 5


def test_graph_store_preserves_frontier_completion_fields(tmp_path):
    graph_path = tmp_path / "research_graph.json"
    store = ResearchGraphStore(graph_path)
    store.ensure_exists()
    payload = store.read()
    payload["hypotheses"] = [{"id": "hyp-001", "summary": "Completion persistence"}]
    payload["experiment_specs"] = [{"id": "spec-001", "hypothesis_id": "hyp-001", "summary": "Completion persistence"}]
    payload["frontier"] = [
        {
            "id": "frontier-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "priority": 1,
            "status": "needs_post_review",
            "claim_state": "candidate",
            "finished_at": "2026-03-11T10:00:00Z",
            "terminal_status": "done",
            "primary_metric": "accuracy",
            "metric_value": 0.91,
        }
    ]
    graph_path.write_text(json.dumps(payload, indent=2))

    normalized = store.read()

    assert normalized["frontier"][0]["finished_at"] == "2026-03-11T10:00:00Z"
    assert normalized["frontier"][0]["terminal_status"] == "done"
    assert normalized["frontier"][0]["primary_metric"] == "accuracy"
    assert normalized["frontier"][0]["metric_value"] == 0.91


def test_graph_store_distinguishes_same_second_results_with_unique_result_ids(tmp_path):
    research = tmp_path / ".research"
    research.mkdir()
    graph_path = research / "research_graph.json"
    pool_path = research / "idea_pool.json"
    store = ResearchGraphStore(graph_path)
    store.ensure_exists()
    payload = store.read()
    payload["hypotheses"] = [
        {"id": "hyp-001", "summary": "A"},
        {"id": "hyp-002", "summary": "B"},
    ]
    payload["experiment_specs"] = [
        {"id": "spec-001", "hypothesis_id": "hyp-001", "summary": "A"},
        {"id": "spec-002", "hypothesis_id": "hyp-002", "summary": "B"},
    ]
    payload["frontier"] = [
        {
            "id": "frontier-001",
            "idea_id": "idea-001",
            "active_execution_id": "exec-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "description": "Same desc",
            "priority": 1,
            "status": "approved",
            "claim_state": "candidate",
        },
        {
            "id": "frontier-002",
            "idea_id": "idea-002",
            "active_execution_id": "exec-002",
            "hypothesis_id": "hyp-002",
            "experiment_spec_id": "spec-002",
            "description": "Same desc",
            "priority": 2,
            "status": "approved",
            "claim_state": "candidate",
        },
    ]
    graph_path.write_text(json.dumps(payload, indent=2))
    pool_path.write_text(
        json.dumps(
            {
                "ideas": [
                    {
                        "id": "idea-001",
                        "frontier_id": "frontier-001",
                        "execution_id": "exec-001",
                        "description": "Same desc",
                        "status": "done",
                        "priority": 1,
                        "result": {"metric_value": 1.0, "verdict": "kept"},
                        "finished_at": "2026-03-11T10:00:00Z",
                        "hypothesis_id": "hyp-001",
                        "experiment_spec_id": "spec-001",
                    },
                    {
                        "id": "idea-002",
                        "frontier_id": "frontier-002",
                        "execution_id": "exec-002",
                        "description": "Same desc",
                        "status": "done",
                        "priority": 2,
                        "result": {"metric_value": 2.0, "verdict": "kept"},
                        "finished_at": "2026-03-11T10:00:00Z",
                        "hypothesis_id": "hyp-002",
                        "experiment_spec_id": "spec-002",
                    },
                ]
            },
            indent=2,
        )
    )

    rows = [
        {
            "timestamp": "2026-03-11T10:00:00Z",
            "commit": "abc123",
            "primary_metric": "score",
            "metric_value": "1.0",
            "secondary_metrics": json.dumps(
                {
                    "_open_researcher_result_id": "result-001",
                    "_open_researcher_trace": {
                        "frontier_id": "frontier-001",
                        "idea_id": "idea-001",
                        "execution_id": "exec-001",
                        "hypothesis_id": "hyp-001",
                        "experiment_spec_id": "spec-001",
                    },
                }
            ),
            "status": "keep",
            "description": "Same desc",
        },
        {
            "timestamp": "2026-03-11T10:00:00Z",
            "commit": "abc123",
            "primary_metric": "score",
            "metric_value": "2.0",
            "secondary_metrics": json.dumps(
                {
                    "_open_researcher_result_id": "result-002",
                    "_open_researcher_trace": {
                        "frontier_id": "frontier-002",
                        "idea_id": "idea-002",
                        "execution_id": "exec-002",
                        "hypothesis_id": "hyp-002",
                        "experiment_spec_id": "spec-002",
                    },
                }
            ),
            "status": "keep",
            "description": "Same desc",
        },
    ]

    result = store.absorb_experiment_outcomes(
        pool_path,
        rows,
        primary_metric="score",
        direction="higher_is_better",
    )

    graph = store.read()
    assert result["evidence_created"] == 2
    assert len(graph["evidence"]) == 2
