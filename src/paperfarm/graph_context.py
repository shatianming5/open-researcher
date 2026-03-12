"""Graph context pruning for token budget control."""

from __future__ import annotations

import copy
import json

from paperfarm.token_tracking import estimate_tokens

_TERMINAL_STATUSES = frozenset({"rejected", "archived"})


def filter_graph_for_context(graph: dict) -> dict:
    """Remove terminal frontier items and their orphaned hypotheses/evidence/specs."""
    filtered = copy.deepcopy(graph)
    all_frontier = graph.get("frontier", [])

    # Keep frontier items NOT in terminal states
    active_frontier = [f for f in all_frontier if f.get("status") not in _TERMINAL_STATUSES]
    filtered["frontier"] = active_frontier

    # Derive referenced hypothesis/spec IDs from active frontier
    active_hyp_ids = {f.get("hypothesis_id") for f in active_frontier}
    active_spec_ids = {f.get("spec_id") for f in active_frontier}

    # IDs of hypotheses that have ANY frontier link (active or terminal)
    all_frontier_hyp_ids = {f.get("hypothesis_id") for f in all_frontier}

    # Keep hypotheses referenced by active frontier OR not linked to any frontier
    filtered["hypotheses"] = [
        h for h in graph.get("hypotheses", [])
        if h.get("id") in active_hyp_ids or h.get("id") not in all_frontier_hyp_ids
    ]
    referenced_hyp_ids = {h["id"] for h in filtered["hypotheses"]}

    # Keep evidence linked to referenced hypotheses
    filtered["evidence"] = [
        e for e in graph.get("evidence", [])
        if e.get("hypothesis_id") in referenced_hyp_ids
    ]

    # Keep specs referenced by active frontier or referenced hypotheses
    filtered["experiment_specs"] = [
        s for s in graph.get("experiment_specs", [])
        if s.get("id") in active_spec_ids or s.get("hypothesis_id") in referenced_hyp_ids
    ]

    # Keep claim_updates linked to referenced hypotheses
    filtered["claim_updates"] = [
        c for c in graph.get("claim_updates", [])
        if c.get("hypothesis_id") in referenced_hyp_ids
    ]

    return filtered


def _estimate_graph_tokens(graph: dict) -> int:
    """Estimate token count of graph JSON serialization."""
    return estimate_tokens(json.dumps(graph))


def enforce_context_token_limit(graph: dict, limit: int) -> dict:
    """Iteratively trim graph until serialized size fits within token limit."""
    if limit <= 0:
        return graph

    trimmed = copy.deepcopy(graph)

    if _estimate_graph_tokens(trimmed) <= limit:
        return trimmed

    # Step 1: Limit evidence to most recent 5 per hypothesis
    hyp_evidence: dict[str, list] = {}
    for e in trimmed.get("evidence", []):
        hid = e.get("hypothesis_id", "")
        hyp_evidence.setdefault(hid, []).append(e)
    trimmed["evidence"] = []
    for hid, evs in hyp_evidence.items():
        trimmed["evidence"].extend(evs[-5:])

    if _estimate_graph_tokens(trimmed) <= limit:
        return trimmed

    # Step 2: Remove claim_updates
    trimmed["claim_updates"] = []

    if _estimate_graph_tokens(trimmed) <= limit:
        return trimmed

    # Step 3: Limit evidence to 2 per hypothesis
    hyp_evidence2: dict[str, list] = {}
    for e in trimmed.get("evidence", []):
        hid = e.get("hypothesis_id", "")
        hyp_evidence2.setdefault(hid, []).append(e)
    trimmed["evidence"] = []
    for hid, evs in hyp_evidence2.items():
        trimmed["evidence"].extend(evs[-2:])

    if _estimate_graph_tokens(trimmed) <= limit:
        return trimmed

    # Step 4: Keep only frontier-referenced specs
    frontier_spec_ids = {f.get("spec_id") for f in trimmed.get("frontier", [])}
    trimmed["experiment_specs"] = [
        s for s in trimmed.get("experiment_specs", [])
        if s.get("id") in frontier_spec_ids
    ]

    return trimmed
