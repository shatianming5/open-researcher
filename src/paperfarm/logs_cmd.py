"""Logs subcommand — view agent logs."""

import time
from collections import deque
from pathlib import Path

import typer

logs_app = typer.Typer(help="View agent logs.")


def _is_error_line(line: str) -> bool:
    """Unified filter for error lines."""
    lower = line.lower()
    return "error" in lower or "traceback" in lower


@logs_app.callback(invoke_without_command=True)
def show_logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    errors: bool = typer.Option(False, "--errors", help="Only show error lines"),
    last: int = typer.Option(50, "--last", "-n", help="Number of lines to show"),
) -> None:
    """View agent logs from .research/run.log."""
    log_path = Path.cwd() / ".research" / "run.log"
    if not log_path.exists():
        print("No log file found at .research/run.log")
        raise SystemExit(1)

    # Use deque to read only the last N lines without loading entire file
    with open(log_path) as f:
        if errors:
            last_lines = deque(
                (line for line in f if _is_error_line(line)),
                maxlen=last,
            )
        else:
            last_lines = deque(f, maxlen=last)

    for line in last_lines:
        print(line, end="" if line.endswith("\n") else "\n")

    if follow:
        try:
            with open(log_path) as f:
                f.seek(0, 2)  # seek to end
                while True:
                    line = f.readline()
                    if line:
                        if errors and not _is_error_line(line):
                            continue
                        print(line, end="")
                    else:
                        time.sleep(0.5)
        except KeyboardInterrupt:
            pass
