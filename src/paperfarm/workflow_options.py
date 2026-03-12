"""Normalize user-facing workflow options into internal runtime selections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from paperfarm.config import ResearchConfig

FrontendMode = Literal["interactive", "headless"]


@dataclass(slots=True)
class WorkflowSelection:
    """Normalized workflow options for CLI entrypoints."""

    frontend_mode: FrontendMode
    primary_agent_name: str | None
    workers: int | None
    notices: list[str]


def apply_worker_override(cfg: ResearchConfig, workers: int | None) -> ResearchConfig:
    """Apply a CLI worker override onto the loaded config in place."""
    if workers is not None:
        cfg.max_workers = workers
    return cfg


def build_workflow_selection(
    *,
    agent: str | None,
    mode: str | None = None,
    headless: bool = False,
    workers: int | None = None,
) -> WorkflowSelection:
    """Normalize CLI-facing options into a single runtime selection."""
    notices: list[str] = []
    frontend_mode = _normalize_frontend_mode(mode, headless=headless, notices=notices)
    if workers is not None and workers < 1:
        raise ValueError("`--workers` must be >= 1.")

    return WorkflowSelection(
        frontend_mode=frontend_mode,
        primary_agent_name=agent,
        workers=workers,
        notices=notices,
    )


def _normalize_frontend_mode(
    mode: str | None,
    *,
    headless: bool,
    notices: list[str],
) -> FrontendMode:
    normalized = str(mode or "interactive").strip().lower()
    if normalized not in {"interactive", "headless"}:
        raise ValueError("`--mode` must be either `interactive` or `headless`.")
    if headless:
        notices.append("`--headless` is deprecated; use `--mode headless`.")
        if normalized == "interactive":
            normalized = "headless"
    return normalized  # type: ignore[return-value]
