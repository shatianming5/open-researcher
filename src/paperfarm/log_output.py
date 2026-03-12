"""Shared output formatting for TUI log rendering."""

import threading
from pathlib import Path


def classify_line(line: str, phase: str) -> str:
    """Add Rich markup to a log line based on its content."""
    stripped = line.strip()
    escaped = line.replace("[", "\\[")

    if stripped.startswith("[exp]") or stripped.startswith("[idea]"):
        return f"[bold #7dcfff]{escaped}[/bold #7dcfff]"

    if stripped.startswith("diff --git"):
        return f"[bold #c0caf5]{escaped}[/bold #c0caf5]"
    if stripped.startswith("file update:"):
        return f"[bold #bb9af7]{escaped}[/bold #bb9af7]"
    if stripped.startswith("@@"):
        return f"[#e0af68]{escaped}[/#e0af68]"
    if stripped.startswith("+") and not stripped.startswith("+++"):
        return f"[green]{escaped}[/green]"
    if stripped.startswith("-") and not stripped.startswith("---"):
        return f"[red]{escaped}[/red]"

    if "step " in stripped and ("loss" in stripped or "iter" in stripped):
        return f"[#7dcfff]{escaped}[/#7dcfff]"

    if "error" in stripped.lower() or "traceback" in stripped.lower():
        return f"[bold red]{escaped}[/bold red]"

    if phase == "thinking":
        return f"[dim italic]{escaped}[/dim italic]"

    return f"[dim]{escaped}[/dim]"


def make_safe_output(app_log_fn, log_path: Path):
    """Create output callback with log coloring and phase separators."""
    state = {"filtering": False, "prompt_done": False, "phase": "acting"}
    lock = threading.Lock()
    try:
        log_file = open(log_path, "a")  # noqa: SIM115
    except OSError:
        log_file = None

    def on_output(line: str):
        with lock:
            if log_file:
                try:
                    log_file.write(line + "\n")
                    log_file.flush()
                except OSError:
                    pass

            stripped = line.strip()
            if not state["prompt_done"]:
                if stripped == "user":
                    state["filtering"] = True
                    return
                if state["filtering"] and stripped in ("thinking", "assistant"):
                    state["filtering"] = False
                    state["prompt_done"] = True
                    if stripped == "thinking":
                        state["phase"] = "thinking"
                        try:
                            app_log_fn("[#565f89]───── Thinking ─────[/#565f89]")
                        except Exception:
                            pass
                    else:
                        state["phase"] = "acting"
                        try:
                            app_log_fn("[bold #7aa2f7]───── Acting ─────[/bold #7aa2f7]")
                        except Exception:
                            pass
                    return
                if state["filtering"]:
                    return

            if stripped == "thinking":
                state["phase"] = "thinking"
                try:
                    app_log_fn("[#565f89]───── Thinking ─────[/#565f89]")
                except Exception:
                    pass
                return
            if stripped == "assistant":
                state["phase"] = "acting"
                try:
                    app_log_fn("[bold #7aa2f7]───── Acting ─────[/bold #7aa2f7]")
                except Exception:
                    pass
                return
            if stripped == "user":
                state["filtering"] = True
                state["prompt_done"] = False
                return
            if stripped == "":
                return

            colored = classify_line(line, state["phase"])
            try:
                app_log_fn(colored)
            except Exception:
                pass

    def _close():
        if log_file:
            try:
                log_file.close()
            except OSError:
                pass

    on_output.close = _close
    return on_output
