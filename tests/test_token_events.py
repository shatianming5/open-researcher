from open_researcher.research_events import (
    TokenBudgetExceeded,
    TokenBudgetWarning,
    TokenMetricsUpdated,
    event_level,
    event_name,
    event_payload,
    event_phase,
)


def test_token_metrics_updated_event():
    e = TokenMetricsUpdated(
        phase="experimenting",
        experiment_num=1,
        tokens_input=100,
        tokens_output=50,
        tokens_total=150,
        budget_remaining=9850,
    )
    assert event_name(e) == "token_metrics_updated"
    assert event_phase(e) == "experimenting"
    assert event_level(e) == "info"
    payload = event_payload(e)
    assert payload["tokens_total"] == 150
    assert payload["budget_remaining"] == 9850


def test_token_metrics_updated_no_experiment():
    e = TokenMetricsUpdated(
        phase="scouting",
        experiment_num=None,
        tokens_input=100,
        tokens_output=50,
        tokens_total=150,
        budget_remaining=None,
    )
    assert event_phase(e) == "scouting"
    payload = event_payload(e)
    assert "experiment_num" not in payload


def test_token_budget_warning_event():
    e = TokenBudgetWarning(tokens_used=8000, token_budget=10000, ratio=0.8)
    assert event_name(e) == "token_budget_warning"
    assert event_level(e) == "warning"
    payload = event_payload(e)
    assert payload["ratio"] == 0.8
    assert "detail" in payload


def test_token_budget_exceeded_event():
    e = TokenBudgetExceeded(tokens_used=10500, token_budget=10000, policy="stop")
    assert event_name(e) == "token_budget_exceeded"
    assert event_level(e) == "error"
    payload = event_payload(e)
    assert payload["policy"] == "stop"
    assert "detail" in payload
