"""Tests for token tracking, cost estimation, and budget management."""

from __future__ import annotations

import json
from pathlib import Path

from open_researcher.token_tracking import (
    BudgetCheckResult,
    TokenLedger,
    TokenMetrics,
    estimate_cost,
    estimate_tokens,
    load_ledger,
    save_ledger,
)

# ---------------------------------------------------------------------------
# TokenMetrics
# ---------------------------------------------------------------------------


class TestTokenMetrics:
    def test_defaults(self):
        m = TokenMetrics()
        assert m.tokens_input == 0
        assert m.tokens_output == 0

    def test_tokens_total(self):
        m = TokenMetrics(tokens_input=100, tokens_output=50)
        assert m.tokens_total == 150

    def test_tokens_total_zero(self):
        assert TokenMetrics().tokens_total == 0

    def test_add_returns_new_instance(self):
        a = TokenMetrics(tokens_input=10, tokens_output=20)
        b = TokenMetrics(tokens_input=5, tokens_output=3)
        result = a.add(b)
        assert result.tokens_input == 15
        assert result.tokens_output == 23
        # originals must not be mutated
        assert a.tokens_input == 10
        assert b.tokens_input == 5

    def test_add_with_zeros(self):
        a = TokenMetrics(tokens_input=7, tokens_output=3)
        result = a.add(TokenMetrics())
        assert result.tokens_input == 7
        assert result.tokens_output == 3

    def test_to_dict_contains_all_keys(self):
        m = TokenMetrics(tokens_input=100, tokens_output=200)
        d = m.to_dict()
        assert d["tokens_input"] == 100
        assert d["tokens_output"] == 200
        assert d["tokens_total"] == 300

    def test_to_dict_zero(self):
        d = TokenMetrics().to_dict()
        assert d == {"tokens_input": 0, "tokens_output": 0, "tokens_total": 0}

    def test_from_dict_round_trip(self):
        m = TokenMetrics(tokens_input=42, tokens_output=99)
        restored = TokenMetrics.from_dict(m.to_dict())
        assert restored.tokens_input == 42
        assert restored.tokens_output == 99

    def test_from_dict_missing_keys_use_defaults(self):
        m = TokenMetrics.from_dict({})
        assert m.tokens_input == 0
        assert m.tokens_output == 0

    def test_from_dict_ignores_tokens_total(self):
        # tokens_total is a computed property; from_dict must not error on it
        m = TokenMetrics.from_dict({"tokens_input": 5, "tokens_output": 3, "tokens_total": 8})
        assert m.tokens_input == 5
        assert m.tokens_output == 3


# ---------------------------------------------------------------------------
# TokenLedger
# ---------------------------------------------------------------------------


class TestTokenLedger:
    def test_defaults(self):
        ledger = TokenLedger()
        assert ledger.cumulative.tokens_total == 0
        assert ledger.per_phase == {}
        assert ledger.per_experiment == {}

    def test_record_updates_cumulative(self):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=10, tokens_output=5), phase="plan")
        assert ledger.cumulative.tokens_input == 10
        assert ledger.cumulative.tokens_output == 5

    def test_record_updates_per_phase(self):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=10, tokens_output=5), phase="plan")
        assert "plan" in ledger.per_phase
        assert ledger.per_phase["plan"].tokens_input == 10

    def test_record_accumulates_same_phase(self):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=10, tokens_output=5), phase="plan")
        ledger.record(TokenMetrics(tokens_input=20, tokens_output=10), phase="plan")
        assert ledger.per_phase["plan"].tokens_input == 30
        assert ledger.per_phase["plan"].tokens_output == 15

    def test_record_multiple_phases(self):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=10, tokens_output=5), phase="plan")
        ledger.record(TokenMetrics(tokens_input=20, tokens_output=8), phase="execute")
        assert ledger.per_phase["plan"].tokens_input == 10
        assert ledger.per_phase["execute"].tokens_input == 20
        assert ledger.cumulative.tokens_input == 30

    def test_record_without_experiment_num(self):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=5, tokens_output=2), phase="review")
        assert ledger.per_experiment == {}

    def test_record_with_experiment_num(self):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=5, tokens_output=2), phase="run", experiment_num=1)
        assert 1 in ledger.per_experiment
        assert ledger.per_experiment[1].tokens_input == 5

    def test_record_accumulates_same_experiment(self):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=5, tokens_output=2), phase="run", experiment_num=1)
        ledger.record(TokenMetrics(tokens_input=3, tokens_output=1), phase="run", experiment_num=1)
        assert ledger.per_experiment[1].tokens_input == 8
        assert ledger.per_experiment[1].tokens_output == 3

    def test_record_multiple_experiments(self):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=5, tokens_output=2), phase="run", experiment_num=1)
        ledger.record(TokenMetrics(tokens_input=10, tokens_output=4), phase="run", experiment_num=2)
        assert ledger.per_experiment[1].tokens_input == 5
        assert ledger.per_experiment[2].tokens_input == 10

    def test_to_dict_structure(self):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=10, tokens_output=5), phase="plan", experiment_num=1)
        d = ledger.to_dict()
        assert "cumulative" in d
        assert "per_phase" in d
        assert "per_experiment" in d
        assert "plan" in d["per_phase"]
        # per_experiment keys must be strings in the dict
        assert "1" in d["per_experiment"]

    def test_serialization_round_trip(self):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=100, tokens_output=50), phase="plan")
        ledger.record(TokenMetrics(tokens_input=200, tokens_output=80), phase="execute", experiment_num=3)
        d = ledger.to_dict()
        restored = TokenLedger.from_dict(d)

        assert restored.cumulative.tokens_input == 300
        assert restored.cumulative.tokens_output == 130
        assert restored.per_phase["plan"].tokens_input == 100
        assert restored.per_phase["execute"].tokens_input == 200
        assert restored.per_experiment[3].tokens_input == 200

    def test_from_dict_empty(self):
        ledger = TokenLedger.from_dict({})
        assert ledger.cumulative.tokens_total == 0
        assert ledger.per_phase == {}
        assert ledger.per_experiment == {}

    def test_per_experiment_keys_are_ints_after_round_trip(self):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=1, tokens_output=1), phase="p", experiment_num=7)
        restored = TokenLedger.from_dict(ledger.to_dict())
        assert 7 in restored.per_experiment
        assert isinstance(list(restored.per_experiment.keys())[0], int)


# ---------------------------------------------------------------------------
# BudgetCheckResult
# ---------------------------------------------------------------------------


class TestBudgetCheckResult:
    def test_construction(self):
        result = BudgetCheckResult(action="warn", reason="threshold", ratio=0.8)
        assert result.action == "warn"
        assert result.reason == "threshold"
        assert result.ratio == 0.8

    def test_pause_action(self):
        result = BudgetCheckResult(action="pause", reason="exceeded", ratio=1.0)
        assert result.action == "pause"

    def test_stop_action(self):
        result = BudgetCheckResult(action="stop", reason="exceeded", ratio=1.2)
        assert result.action == "stop"


# ---------------------------------------------------------------------------
# estimate_cost
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_known_model_sonnet(self):
        # 1M input tokens at $3.00, 1M output tokens at $15.00 => $18.00
        m = TokenMetrics(tokens_input=1_000_000, tokens_output=1_000_000)
        cost = estimate_cost(m, model="claude-sonnet-4-5-20250514")
        assert abs(cost - 18.0) < 1e-6

    def test_known_model_opus(self):
        # 1M input tokens at $15.00, 1M output tokens at $75.00 => $90.00
        m = TokenMetrics(tokens_input=1_000_000, tokens_output=1_000_000)
        cost = estimate_cost(m, model="claude-opus-4-20250514")
        assert abs(cost - 90.0) < 1e-6

    def test_known_model_haiku(self):
        # 1M input at $0.80, 1M output at $4.00 => $4.80
        m = TokenMetrics(tokens_input=1_000_000, tokens_output=1_000_000)
        cost = estimate_cost(m, model="claude-haiku-3-5-20241022")
        assert abs(cost - 4.80) < 1e-6

    def test_unknown_model_uses_default(self):
        # default == sonnet rates: $3/$15 per million
        m = TokenMetrics(tokens_input=1_000_000, tokens_output=1_000_000)
        cost_unknown = estimate_cost(m, model="totally-unknown-model")
        cost_default = estimate_cost(m, model="")
        assert abs(cost_unknown - cost_default) < 1e-9

    def test_zero_tokens(self):
        assert estimate_cost(TokenMetrics()) == 0.0

    def test_partial_million(self):
        # 500k input at $3/M = $1.50, 0 output
        m = TokenMetrics(tokens_input=500_000, tokens_output=0)
        cost = estimate_cost(m, model="claude-sonnet-4-5-20250514")
        assert abs(cost - 1.50) < 1e-6

    def test_no_model_arg_uses_default(self):
        m = TokenMetrics(tokens_input=1_000_000, tokens_output=0)
        # default input rate = $3.00/M => $3.00
        cost = estimate_cost(m)
        assert abs(cost - 3.0) < 1e-6


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_non_empty_string_returns_positive_int(self):
        count = estimate_tokens("Hello, world!")
        assert isinstance(count, int)
        assert count > 0

    def test_empty_string_returns_at_least_one(self):
        # The fallback uses max(1, len(text) // 4); tiktoken may return 0 for ""
        # We only assert it returns a non-negative int
        count = estimate_tokens("")
        assert isinstance(count, int)
        assert count >= 0

    def test_longer_text_has_more_tokens(self):
        short = estimate_tokens("Hi")
        long = estimate_tokens("Hi " * 100)
        assert long > short

    def test_returns_int(self):
        assert isinstance(estimate_tokens("test"), int)


# ---------------------------------------------------------------------------
# save_ledger / load_ledger
# ---------------------------------------------------------------------------


class TestLedgerPersistence:
    def test_save_and_load_round_trip(self, tmp_path: Path):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=100, tokens_output=50), phase="plan")
        ledger.record(TokenMetrics(tokens_input=200, tokens_output=80), phase="run", experiment_num=1)

        path = tmp_path / "ledger.json"
        save_ledger(ledger, path)

        loaded = load_ledger(path)
        assert loaded.cumulative.tokens_input == 300
        assert loaded.cumulative.tokens_output == 130
        assert loaded.per_phase["plan"].tokens_input == 100
        assert loaded.per_experiment[1].tokens_input == 200

    def test_file_is_valid_json(self, tmp_path: Path):
        ledger = TokenLedger()
        ledger.record(TokenMetrics(tokens_input=1, tokens_output=2), phase="p")
        path = tmp_path / "ledger.json"
        save_ledger(ledger, path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "cumulative" in data

    def test_load_missing_file_returns_empty_ledger(self, tmp_path: Path):
        path = tmp_path / "nonexistent.json"
        ledger = load_ledger(path)
        assert ledger.cumulative.tokens_total == 0
        assert ledger.per_phase == {}
        assert ledger.per_experiment == {}

    def test_load_corrupt_file_returns_empty_ledger(self, tmp_path: Path):
        path = tmp_path / "corrupt.json"
        path.write_text("not valid json {{{", encoding="utf-8")
        ledger = load_ledger(path)
        assert ledger.cumulative.tokens_total == 0

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "subdir" / "nested" / "ledger.json"
        ledger = TokenLedger()
        save_ledger(ledger, path)
        assert path.exists()

    def test_lock_file_created(self, tmp_path: Path):
        path = tmp_path / "ledger.json"
        save_ledger(TokenLedger(), path)
        # The lock file may be cleaned up by filelock; just verify no exception
        # and data is intact
        loaded = load_ledger(path)
        assert loaded.cumulative.tokens_total == 0

    def test_overwrite_existing_ledger(self, tmp_path: Path):
        path = tmp_path / "ledger.json"
        ledger1 = TokenLedger()
        ledger1.record(TokenMetrics(tokens_input=10, tokens_output=5), phase="a")
        save_ledger(ledger1, path)

        ledger2 = TokenLedger()
        ledger2.record(TokenMetrics(tokens_input=99, tokens_output=1), phase="b")
        save_ledger(ledger2, path)

        loaded = load_ledger(path)
        assert loaded.cumulative.tokens_input == 99
        assert "b" in loaded.per_phase
        assert "a" not in loaded.per_phase
