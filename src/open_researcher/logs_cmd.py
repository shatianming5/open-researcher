"""Logs subcommand — view agent logs."""

import sys
import time
from pathlib import Path

import typer

logs_app = typer.Typer(help="View agent logs.")


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

    lines = log_path.read_text().splitlines()

    if errors:
        lines = [line for line in lines if "error" in line.lower() or "traceback" in line.lower()]

    for line in lines[-last:]:
        print(line)

    if follow:
        try:
            with open(log_path) as f:
                f.seek(0, 2)  # seek to end
                while True:
                    line = f.readline()
                    if line:
                        if errors and "error" not in line.lower():
                            continue
                        print(line, end="")
                    else:
                        time.sleep(0.5)
        except KeyboardInterrupt:
            pass
