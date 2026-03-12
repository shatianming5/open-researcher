"""Shared Textual session helpers for bootstrap and existing-workflow entrypoints."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from paperfarm.tui.app import ResearchApp
    from paperfarm.tui.events import TUIEventRenderer

logger = logging.getLogger(__name__)

CleanupCallback = Callable[[], None]
SessionSetup = Callable[
    ["ResearchApp", "TUIEventRenderer | None"],
    Iterable[CleanupCallback] | None,
]


def start_daemon(target: Callable[[], None]) -> threading.Thread:
    """Run one target in a daemon thread."""
    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread


def run_tui_session(
    repo_path: Path,
    *,
    setup: SessionSetup,
    research_dir: Path | None = None,
    initial_phase: str = "experimenting",
) -> None:
    """Create the shared Textual app shell, run setup, and guarantee cleanup."""
    from paperfarm.tui.app import ResearchApp
    from paperfarm.tui.events import TUIEventRenderer

    cleanup_callbacks: list[CleanupCallback] = []
    app_ref: dict[str, ResearchApp] = {}
    renderer_ref: dict[str, TUIEventRenderer | None] = {"renderer": None}

    def on_ready() -> None:
        extra_cleanup = setup(app_ref["app"], renderer_ref["renderer"])
        if extra_cleanup:
            cleanup_callbacks.extend(extra_cleanup)

    app = ResearchApp(
        repo_path,
        on_ready=on_ready,
        initial_phase=initial_phase,
    )
    app_ref["app"] = app

    if research_dir is not None:
        renderer_ref["renderer"] = TUIEventRenderer(app, research_dir)

    try:
        app.run()
    finally:
        for callback in reversed(cleanup_callbacks):
            try:
                callback()
            except Exception:
                logger.debug("Session cleanup callback failed", exc_info=True)
        renderer = renderer_ref["renderer"]
        if renderer is not None:
            renderer.close()


def print_exit_summary(
    console: Console,
    exit_codes: dict[str, int],
    labels: list[tuple[str, str]],
    *,
    show_missing: bool = False,
) -> None:
    """Render a consistent success/error summary for one or more agents."""
    for key, label in labels:
        if not show_missing and key not in exit_codes:
            continue
        code = exit_codes.get(key, -1)
        if code == 0:
            console.print(f"[green]{label} completed successfully.[/green]")
        else:
            console.print(f"[red]{label} exited with code {code}.[/red]")
