"""Token tracking, cost estimation, and budget management."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from filelock import FileLock

from open_researcher.storage import atomic_write_json

# ---------------------------------------------------------------------------
# Task 1: TokenMetrics and TokenLedger
# ---------------------------------------------------------------------------


@dataclass
class TokenMetrics:
    """Token usage counters for a single agent invocation."""

    tokens_input: int = 0
    tokens_output: int = 0

    @property
    def tokens_total(self) -> int:
        return self.tokens_input + self.tokens_output

    def add(self, other: TokenMetrics) -> TokenMetrics:
        """Return a new TokenMetrics that is the sum of self and other."""
        return TokenMetrics(
            tokens_input=self.tokens_input + other.tokens_input,
            tokens_output=self.tokens_output + other.tokens_output,
        )

    def to_dict(self) -> dict:
        return {
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "tokens_total": self.tokens_total,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TokenMetrics:
        return cls(
            tokens_input=d.get("tokens_input", 0),
            tokens_output=d.get("tokens_output", 0),
        )


@dataclass
class TokenLedger:
    """Accumulates token usage across phases and experiments within a session."""

    cumulative: TokenMetrics = field(default_factory=TokenMetrics)
    per_phase: dict[str, TokenMetrics] = field(default_factory=dict)
    per_experiment: dict[int, TokenMetrics] = field(default_factory=dict)

    def record(
        self,
        metrics: TokenMetrics,
        phase: str,
        experiment_num: int | None = None,
    ) -> None:
        """Accumulate *metrics* into cumulative, per-phase, and (optionally) per-experiment buckets."""
        self.cumulative = self.cumulative.add(metrics)

        if phase in self.per_phase:
            self.per_phase[phase] = self.per_phase[phase].add(metrics)
        else:
            self.per_phase[phase] = TokenMetrics(metrics.tokens_input, metrics.tokens_output)

        if experiment_num is not None:
            if experiment_num in self.per_experiment:
                self.per_experiment[experiment_num] = self.per_experiment[experiment_num].add(metrics)
            else:
                self.per_experiment[experiment_num] = TokenMetrics(metrics.tokens_input, metrics.tokens_output)

    def to_dict(self) -> dict:
        return {
            "cumulative": self.cumulative.to_dict(),
            "per_phase": {k: v.to_dict() for k, v in self.per_phase.items()},
            # JSON requires string keys; convert int keys to str
            "per_experiment": {str(k): v.to_dict() for k, v in self.per_experiment.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> TokenLedger:
        return cls(
            cumulative=TokenMetrics.from_dict(d.get("cumulative", {})),
            per_phase={k: TokenMetrics.from_dict(v) for k, v in d.get("per_phase", {}).items()},
            # Restore int keys from the string-keyed JSON representation
            per_experiment={int(k): TokenMetrics.from_dict(v) for k, v in d.get("per_experiment", {}).items()},
        )


# ---------------------------------------------------------------------------
# Task 2: BudgetCheckResult and cost estimation
# ---------------------------------------------------------------------------

MODEL_RATES: dict[str, dict[str, float]] = {
    "claude-sonnet-4-5-20250514": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-haiku-3-5-20241022": {"input": 0.80, "output": 4.0},
    "default": {"input": 3.0, "output": 15.0},
}


@dataclass
class BudgetCheckResult:
    """Result of a budget threshold check."""

    action: str  # "warn" | "pause" | "stop"
    reason: str  # "threshold" | "exceeded"
    ratio: float  # current_cost / budget_limit


def estimate_cost(metrics: TokenMetrics, model: str = "") -> float:
    """Return the estimated USD cost for *metrics* given the model's pricing.

    Falls back to the "default" rate for unknown model names.
    """
    rates = MODEL_RATES.get(model, MODEL_RATES["default"])
    input_cost = (metrics.tokens_input / 1_000_000) * rates["input"]
    output_cost = (metrics.tokens_output / 1_000_000) * rates["output"]
    return input_cost + output_cost


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in *text*.

    Uses tiktoken when available; falls back to a simple heuristic (len // 4).
    """
    try:
        import tiktoken  # type: ignore[import]

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Task 3: TokenLedger persistence
# ---------------------------------------------------------------------------


def save_ledger(ledger: TokenLedger, path: Path) -> None:
    """Persist *ledger* to *path* atomically under a file lock."""
    lock = FileLock(str(path) + ".lock")
    with lock:
        atomic_write_json(path, ledger.to_dict())


def load_ledger(path: Path) -> TokenLedger:
    """Load a TokenLedger from *path* under a file lock.

    Returns an empty TokenLedger if the file does not exist or is corrupt.
    """
    lock = FileLock(str(path) + ".lock")
    with lock:
        if not path.exists():
            return TokenLedger()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TokenLedger.from_dict(data)
        except (json.JSONDecodeError, OSError, KeyError):
            return TokenLedger()
