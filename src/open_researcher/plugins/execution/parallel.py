"""Parallel experiment batch execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParallelBatchConfig:
    """Configuration for parallel experiment execution."""

    max_workers: int = 1
    gpu_ids: list[int] = field(default_factory=list)
    timeout_seconds: int = 3600


@dataclass
class BatchResult:
    """Result of a parallel batch execution."""

    completed: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
