#!/usr/bin/env python3
"""Launch and register a detached long-running experiment command."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _safe_component(raw: str, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(raw or "").strip())
    return cleaned or fallback


def _trace_fields() -> dict:
    trace = {
        "frontier_id": os.environ.get("OPEN_RESEARCHER_FRONTIER_ID", "").strip(),
        "idea_id": os.environ.get("OPEN_RESEARCHER_IDEA_ID", "").strip(),
        "execution_id": os.environ.get("OPEN_RESEARCHER_EXECUTION_ID", "").strip(),
        "hypothesis_id": os.environ.get("OPEN_RESEARCHER_HYPOTHESIS_ID", "").strip(),
        "experiment_spec_id": os.environ.get("OPEN_RESEARCHER_EXPERIMENT_SPEC_ID", "").strip(),
    }
    return {key: value for key, value in trace.items() if value}


def _state_path(cwd: Path) -> Path:
    trace = _trace_fields()
    runtime_dir = cwd / ".research" / "runtime"
    idea_id = _safe_component(trace.get("idea_id", ""), "idea")
    execution_id = _safe_component(trace.get("execution_id", ""), "exec")
    return runtime_dir / f"{idea_id}__{execution_id}.json"


def _build_state(*, argv: list[str], cwd: Path, active: bool, status: str, **extra) -> dict:
    trace = _trace_fields()
    payload = {
        "schema_version": 1,
        "active": bool(active),
        "status": str(status).strip(),
        "cwd": str(cwd),
        "argv": list(argv),
        "command": subprocess.list2cmdline(argv),
        "updated_at": _utc_now(),
    }
    payload.update(trace)
    payload.update(extra)
    return payload


def _run_registered_command(state_path: Path, cwd: Path, argv: list[str]) -> int:
    state = _build_state(
        argv=argv,
        cwd=cwd,
        active=True,
        status="running",
        pid=os.getpid(),
        pgid=os.getpgid(0),
        started_at=_utc_now(),
    )
    _atomic_write_json(state_path, state)

    env = os.environ.copy()
    env["OPEN_RESEARCHER_DETACHED_STATE"] = str(state_path)
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        start_new_session=False,
    )

    state["child_pid"] = proc.pid
    _atomic_write_json(state_path, state)

    return_code = proc.wait()
    state.update(
        {
            "active": False,
            "status": "completed" if return_code == 0 else "failed",
            "exit_code": int(return_code),
            "finished_at": _utc_now(),
            "updated_at": _utc_now(),
        }
    )
    _atomic_write_json(state_path, state)
    return int(return_code)


def _launch_detached(state_path: Path, cwd: Path, argv: list[str]) -> int:
    wrapper_cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--internal-runner",
        "--state-file",
        str(state_path),
        "--cwd",
        str(cwd),
        "--",
        *argv,
    ]
    proc = subprocess.Popen(
        wrapper_cmd,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            state = _read_json(state_path)
            try:
                state_exit = int(state.get("exit_code", proc.returncode or 1) or 1)
            except (TypeError, ValueError):
                state_exit = 1
            print(
                f"[ERROR] Detached runner exited before registration (code={state_exit})",
                file=sys.stderr,
            )
            return state_exit
        state = _read_json(state_path)
        try:
            state_pid = int(state.get("pid", 0) or 0)
        except (TypeError, ValueError):
            state_pid = 0
        if bool(state.get("active")) and state_pid == proc.pid:
            print(f"[OK] Detached run registered: pid={proc.pid} state={state_path}")
            return 0
        time.sleep(0.1)

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass
    print(f"[ERROR] Timed out waiting for detached registration: {state_path}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch a long-running experiment in detached mode")
    parser.add_argument("--cwd", default="", help="Working directory for the detached command")
    parser.add_argument("--state-file", default="", help="Explicit detached state path")
    parser.add_argument("--internal-runner", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    argv = list(args.command)
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("[ERROR] Missing detached command. Use -- <cmd> ...", file=sys.stderr)
        return 1

    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd().resolve()
    state_path = Path(args.state_file).resolve() if args.state_file else _state_path(cwd)

    if args.internal_runner:
        return _run_registered_command(state_path, cwd, argv)
    return _launch_detached(state_path, cwd, argv)


if __name__ == "__main__":
    raise SystemExit(main())
