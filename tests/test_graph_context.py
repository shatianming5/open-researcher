from open_researcher.graph_context import enforce_context_token_limit, filter_graph_for_context


def _sample_graph():
    return {
        "hypotheses": [
            {"id": "h1", "title": "hyp active"},
            {"id": "h2", "title": "hyp with rejected frontier"},
            {"id": "h3", "title": "hyp with no frontier"},
        ],
        "experiment_specs": [
            {"id": "s1", "hypothesis_id": "h1"},
            {"id": "s2", "hypothesis_id": "h2"},
            {"id": "s3", "hypothesis_id": "h3"},
        ],
        "evidence": [
            {"id": "e1", "hypothesis_id": "h1", "metric_value": 0.9},
            {"id": "e2", "hypothesis_id": "h2", "metric_value": 0.5},
            {"id": "e3", "hypothesis_id": "h3", "metric_value": 0.7},
        ],
        "claim_updates": [
            {"id": "c1", "hypothesis_id": "h1"},
            {"id": "c2", "hypothesis_id": "h2"},
        ],
        "frontier": [
            {"id": "f1", "hypothesis_id": "h1", "spec_id": "s1", "status": "approved"},
            {"id": "f2", "hypothesis_id": "h2", "spec_id": "s2", "status": "rejected"},
        ],
        "counters": {"next_id": 10},
    }


def test_filter_removes_rejected_frontier():
    graph = _sample_graph()
    filtered = filter_graph_for_context(graph)
    frontier_ids = [f["id"] for f in filtered["frontier"]]
    assert "f1" in frontier_ids
    assert "f2" not in frontier_ids


def test_filter_keeps_hypotheses_with_active_frontier():
    graph = _sample_graph()
    filtered = filter_graph_for_context(graph)
    hyp_ids = [h["id"] for h in filtered["hypotheses"]]
    assert "h1" in hyp_ids


def test_filter_keeps_hypotheses_with_no_frontier():
    graph = _sample_graph()
    filtered = filter_graph_for_context(graph)
    hyp_ids = [h["id"] for h in filtered["hypotheses"]]
    assert "h3" in hyp_ids


def test_filter_drops_hypotheses_only_rejected_frontier():
    graph = _sample_graph()
    filtered = filter_graph_for_context(graph)
    hyp_ids = [h["id"] for h in filtered["hypotheses"]]
    assert "h2" not in hyp_ids


def test_filter_drops_evidence_for_removed_hypotheses():
    graph = _sample_graph()
    filtered = filter_graph_for_context(graph)
    evidence_hyp_ids = [e["hypothesis_id"] for e in filtered["evidence"]]
    assert "h2" not in evidence_hyp_ids


def test_filter_does_not_mutate_original():
    graph = _sample_graph()
    original_frontier_count = len(graph["frontier"])
    filter_graph_for_context(graph)
    assert len(graph["frontier"]) == original_frontier_count


def test_enforce_context_token_limit_noop_when_under():
    graph = _sample_graph()
    result = enforce_context_token_limit(graph, limit=100000)
    assert len(result["evidence"]) == len(graph["evidence"])


def test_enforce_context_token_limit_trims_evidence():
    graph = _sample_graph()
    graph["evidence"] = [
        {"id": f"e{i}", "hypothesis_id": "h1", "metric_value": 0.5, "detail": "x" * 500} for i in range(100)
    ]
    result = enforce_context_token_limit(graph, limit=500)
    assert len(result["evidence"]) < 100


def test_enforce_context_token_limit_zero_means_unlimited():
    graph = _sample_graph()
    result = enforce_context_token_limit(graph, limit=0)
    assert len(result["evidence"]) == len(graph["evidence"])
