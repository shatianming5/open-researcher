"""Event-backed control-plane commands with a compatibility control snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from filelock import FileLock

from open_researcher.event_journal import next_seq_unlocked, now_iso
from open_researcher.storage import atomic_write_json

ControlCommand = Literal["pause", "resume", "skip_current", "clear_skip"]

_VALID_COMMANDS: tuple[ControlCommand, ...] = (
    "pause",
    "resume",
    "skip_current",
    "clear_skip",
)
_IDEMPOTENCY_WINDOW = 64


def _default_control() -> dict:
    return {
        "paused": False,
        "skip_current": False,
        "control_seq": 0,
        "applied_command_ids": [],
        "event_count": 0,
    }


def _load_control_snapshot(ctrl_path: Path) -> dict:
    default = _default_control()
    if not ctrl_path.exists():
        return default
    try:
        payload = json.loads(ctrl_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
    if not isinstance(payload, dict):
        return default

    merged = dict(payload)
    merged["paused"] = bool(merged.get("paused", False))
    merged["skip_current"] = bool(merged.get("skip_current", False))
    seq = merged.get("control_seq", 0)
    try:
        merged["control_seq"] = max(int(seq), 0)
    except (TypeError, ValueError):
        merged["control_seq"] = 0
    event_count = merged.get("event_count", 0)
    try:
        merged["event_count"] = max(int(event_count), 0)
    except (TypeError, ValueError):
        merged["event_count"] = 0

    ids = merged.get("applied_command_ids", [])
    if not isinstance(ids, list):
        ids = []
    merged["applied_command_ids"] = [str(item) for item in ids if str(item).strip()][-_IDEMPOTENCY_WINDOW:]
    return merged


def _event_log_path(ctrl_path: Path) -> Path:
    return ctrl_path.with_name("events.jsonl")


def _control_event_record(
    *,
    event_seq: int,
    command: ControlCommand,
    seq: int,
    source: str,
    reason: str | None,
    command_id: str | None,
    state: dict,
) -> dict:
    return {
        "seq": int(event_seq),
        "ts": now_iso(),
        "level": "info",
        "phase": "control",
        "event": "control_command",
        "command": command,
        "source": str(source).strip() or "unknown",
        "reason": str(reason).strip() if reason else "",
        "command_id": str(command_id or "").strip(),
        "control_seq": int(seq),
        "paused": bool(state.get("paused", False)),
        "skip_current": bool(state.get("skip_current", False)),
    }


def _append_event_unlocked(events_path: Path, record: dict) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _apply_state(
    ctrl: dict,
    *,
    command: ControlCommand,
    seq: int,
    source: str,
    reason: str | None,
    command_id: str | None,
) -> None:
    if command == "pause":
        ctrl["paused"] = True
        if reason:
            ctrl["pause_reason"] = str(reason)
    elif command == "resume":
        ctrl["paused"] = False
        ctrl.pop("pause_reason", None)
    elif command == "skip_current":
        ctrl["skip_current"] = True
    elif command == "clear_skip":
        ctrl["skip_current"] = False

    ctrl["control_seq"] = int(seq)
    ctrl["last_command"] = command
    ctrl["last_command_source"] = str(source).strip() or "unknown"
    ctrl["last_command_id"] = str(command_id or "").strip()
    ctrl["updated_at"] = now_iso()

    normalized_id = str(command_id or "").strip()
    if normalized_id:
        applied_ids = list(ctrl.get("applied_command_ids", []))
        applied_ids.append(normalized_id)
        ctrl["applied_command_ids"] = applied_ids[-_IDEMPOTENCY_WINDOW:]


def _replay_control_state_unlocked(
    ctrl_path: Path,
    events_path: Path,
    *,
    use_snapshot_fallback: bool,
) -> dict:
    snapshot = _load_control_snapshot(ctrl_path)
    if not events_path.exists():
        return snapshot if use_snapshot_fallback else _default_control()

    ctrl = _default_control()
    event_count = 0
    for line in events_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(record, dict):
            continue
        if record.get("phase") != "control" or record.get("event") != "control_command":
            continue

        event_count += 1
        try:
            seq = int(record.get("control_seq", 0))
        except (TypeError, ValueError):
            continue
        command = str(record.get("command", "")).strip()
        if command not in _VALID_COMMANDS:
            continue
        _apply_state(
            ctrl,
            command=command,  # type: ignore[arg-type]
            seq=seq,
            source=str(record.get("source", "unknown")),
            reason=str(record.get("reason", "") or "") or None,
            command_id=str(record.get("command_id", "") or "") or None,
        )
        ctrl["event_count"] = event_count

    if event_count == 0:
        return snapshot if use_snapshot_fallback else _default_control()
    return ctrl


def read_control(ctrl_path: Path) -> dict:
    """Read control state derived from the event log, with snapshot fallback."""
    events_path = _event_log_path(ctrl_path)
    lock = FileLock(str(events_path) + ".lock")
    with lock:
        ctrl = _replay_control_state_unlocked(
            ctrl_path,
            events_path,
            use_snapshot_fallback=True,
        )
        atomic_write_json(ctrl_path, ctrl)
        return ctrl


def _apply_locked_command(
    ctrl: dict,
    *,
    command: ControlCommand,
    seq: int,
    source: str,
    reason: str | None,
    command_id: str | None,
) -> dict:
    if command not in _VALID_COMMANDS:
        raise ValueError(f"Unsupported control command: {command!r}")
    if seq <= 0:
        raise ValueError(f"control sequence id must be positive, got {seq!r}")

    current_seq = int(ctrl.get("control_seq", 0))
    normalized_id = str(command_id or "").strip()
    applied_ids = list(ctrl.get("applied_command_ids", []))

    if normalized_id and normalized_id in applied_ids:
        return {
            "applied": False,
            "duplicate_suppressed": True,
            "out_of_order": False,
            "control_seq": current_seq,
            "command_id": normalized_id,
        }

    if seq <= current_seq:
        return {
            "applied": False,
            "duplicate_suppressed": True,
            "out_of_order": True,
            "control_seq": current_seq,
            "command_id": normalized_id,
        }

    _apply_state(
        ctrl,
        command=command,
        seq=seq,
        source=source,
        reason=reason,
        command_id=normalized_id or None,
    )

    return {
        "applied": True,
        "duplicate_suppressed": False,
        "out_of_order": False,
        "control_seq": int(ctrl["control_seq"]),
        "command_id": normalized_id,
    }


def apply_control_command(
    ctrl_path: Path,
    *,
    command: ControlCommand,
    seq: int,
    source: str,
    reason: str | None = None,
    command_id: str | None = None,
) -> dict:
    """Apply a command with an explicit sequence id under lock."""
    events_path = _event_log_path(ctrl_path)
    lock = FileLock(str(events_path) + ".lock")
    with lock:
        ctrl = _replay_control_state_unlocked(
            ctrl_path,
            events_path,
            use_snapshot_fallback=False,
        )
        result = _apply_locked_command(
            ctrl,
            command=command,
            seq=seq,
            source=source,
            reason=reason,
            command_id=command_id,
        )
        if result["applied"]:
            ctrl["event_count"] = int(ctrl.get("event_count", 0)) + 1
            event_seq = next_seq_unlocked(events_path)
            _append_event_unlocked(
                events_path,
                _control_event_record(
                    event_seq=event_seq,
                    command=command,
                    seq=seq,
                    source=source,
                    reason=reason,
                    command_id=command_id,
                    state=ctrl,
                ),
            )
        atomic_write_json(ctrl_path, ctrl)
    return {**result, "state": ctrl}


def issue_control_command(
    ctrl_path: Path,
    *,
    command: ControlCommand,
    source: str,
    reason: str | None = None,
    command_id: str | None = None,
) -> dict:
    """Issue the next monotonic command id and apply atomically."""
    events_path = _event_log_path(ctrl_path)
    lock = FileLock(str(events_path) + ".lock")
    with lock:
        ctrl = _replay_control_state_unlocked(
            ctrl_path,
            events_path,
            use_snapshot_fallback=False,
        )
        next_seq = int(ctrl.get("control_seq", 0)) + 1
        result = _apply_locked_command(
            ctrl,
            command=command,
            seq=next_seq,
            source=source,
            reason=reason,
            command_id=command_id,
        )
        if result["applied"]:
            ctrl["event_count"] = int(ctrl.get("event_count", 0)) + 1
            event_seq = next_seq_unlocked(events_path)
            _append_event_unlocked(
                events_path,
                _control_event_record(
                    event_seq=event_seq,
                    command=command,
                    seq=next_seq,
                    source=source,
                    reason=reason,
                    command_id=command_id,
                    state=ctrl,
                ),
            )
        atomic_write_json(ctrl_path, ctrl)
    return {**result, "state": ctrl}


def consume_skip_current(ctrl_path: Path, *, source: str) -> bool:
    """Atomically clear a pending skip_current flag and record the clear event."""
    events_path = _event_log_path(ctrl_path)
    lock = FileLock(str(events_path) + ".lock")
    with lock:
        ctrl = _replay_control_state_unlocked(
            ctrl_path,
            events_path,
            use_snapshot_fallback=True,
        )
        if not bool(ctrl.get("skip_current", False)):
            atomic_write_json(ctrl_path, ctrl)
            return False

        next_seq = int(ctrl.get("control_seq", 0)) + 1
        result = _apply_locked_command(
            ctrl,
            command="clear_skip",
            seq=next_seq,
            source=source,
            reason="runtime consumed skip_current",
            command_id=None,
        )
        if result["applied"]:
            ctrl["event_count"] = int(ctrl.get("event_count", 0)) + 1
            event_seq = next_seq_unlocked(events_path)
            _append_event_unlocked(
                events_path,
                _control_event_record(
                    event_seq=event_seq,
                    command="clear_skip",
                    seq=next_seq,
                    source=source,
                    reason="runtime consumed skip_current",
                    command_id=None,
                    state=ctrl,
                ),
            )
        atomic_write_json(ctrl_path, ctrl)
        return bool(result["applied"])
