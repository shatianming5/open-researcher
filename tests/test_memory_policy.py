"""Tests for history-aware frontier retrieval and policy ranking."""

from paperfarm.memory_policy import apply_history_policy, build_family_key


def test_apply_history_policy_prefers_existing_repro_branch():
    graph = {
        "hypotheses": [{"id": "hyp-001", "summary": "Seed locking reduces variance"}],
        "experiment_specs": [
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
        ],
        "claim_updates": [],
    }
    frontier = [
        {
            "id": "frontier-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "priority": 2,
            "status": "needs_repro",
            "claim_state": "needs_repro",
            "repro_required": True,
            "description": "Reproduce the fixed-seed win",
        },
        {
            "id": "frontier-002",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-002",
            "priority": 1,
            "status": "approved",
            "claim_state": "candidate",
            "description": "Try another shallow variant",
        },
    ]

    updated = apply_history_policy(frontier, graph, {"ideation_memory": [], "experiment_memory": []})
    penalized = next(row for row in updated if row["id"] == "frontier-002")

    assert penalized["policy_state"] == "prefer_repro"
    assert penalized["policy_reason"] == "existing repro pending"
    assert penalized["runtime_priority"] == 3


def test_apply_history_policy_penalizes_repeated_failures_from_memory():
    graph = {
        "hypotheses": [{"id": "hyp-001", "summary": "Cache manifest reads"}],
        "experiment_specs": [
            {
                "id": "spec-001",
                "hypothesis_id": "hyp-001",
                "summary": "Cache manifest reads",
                "attribution_focus": "manifest parser",
                "expected_signal": "latency down",
            }
        ],
        "claim_updates": [],
    }
    frontier = [
        {
            "id": "frontier-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "priority": 1,
            "status": "approved",
            "claim_state": "candidate",
            "description": "Retry manifest cache",
        }
    ]
    family_key = build_family_key(frontier[0], graph["hypotheses"][0], graph["experiment_specs"][0])
    memory = {
        "ideation_memory": [
            {
                "source_claim_update": "claim-001",
                "frontier_id": "frontier-old-001",
                "family_key": family_key,
                "outcome": "reject",
                "reason_code": "contradicted_by_result",
                "summary": "manifest cache no-op",
            },
            {
                "source_claim_update": "claim-002",
                "frontier_id": "frontier-old-002",
                "family_key": family_key,
                "outcome": "downgrade",
                "reason_code": "regression_detected",
                "summary": "manifest cache regressed tests",
            },
        ],
        "experiment_memory": [],
    }

    updated = apply_history_policy(frontier, graph, memory)

    assert updated[0]["policy_state"] == "repeat_failure_risk"
    assert updated[0]["policy_reason"] == "family has 2 negative outcomes"
    assert updated[0]["runtime_priority"] == 4


def test_apply_history_policy_marks_same_cycle_duplicates():
    graph = {
        "hypotheses": [{"id": "hyp-001", "summary": "Lock dataloader order"}],
        "experiment_specs": [
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
        ],
        "claim_updates": [],
    }
    frontier = [
        {
            "id": "frontier-001",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-001",
            "priority": 1,
            "status": "draft",
            "claim_state": "candidate",
            "description": "Primary version",
        },
        {
            "id": "frontier-002",
            "hypothesis_id": "hyp-001",
            "experiment_spec_id": "spec-002",
            "priority": 2,
            "status": "draft",
            "claim_state": "candidate",
            "description": "Duplicate version",
        },
    ]

    updated = apply_history_policy(frontier, graph, {"ideation_memory": [], "experiment_memory": []})
    keeper = next(row for row in updated if row["id"] == "frontier-001")
    duplicate = next(row for row in updated if row["id"] == "frontier-002")

    assert keeper["policy_state"] == "neutral"
    assert duplicate["policy_state"] == "duplicate_same_cycle"
    assert duplicate["runtime_priority"] == 5
    assert "frontier-001" in duplicate["policy_reason"]
