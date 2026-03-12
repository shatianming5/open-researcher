"""Atomic file IO utilities for concurrent access safety."""

import json
import os
import tempfile
from pathlib import Path

from filelock import FileLock


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically: temp file -> fsync -> os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, obj: object) -> None:
    """Write JSON atomically."""
    atomic_write_text(path, json.dumps(obj, indent=2))


def locked_read_json(path: Path, lock: FileLock, default: object = None) -> object:
    """Read JSON under file lock. Returns *default* on missing/corrupt file."""
    with lock:
        if not path.exists():
            return default() if callable(default) else default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default() if callable(default) else default


def locked_update_json(
    path: Path,
    lock: FileLock,
    updater,
    default: object = None,
):
    """Read-modify-write JSON atomically under file lock.

    *updater(data)* receives the current data and may return a value.
    The (possibly mutated) *data* is written back atomically.
    Returns (data, updater_result).
    """
    with lock:
        if not path.exists():
            data = default() if callable(default) else default
        else:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = default() if callable(default) else default
        result = updater(data)
        atomic_write_json(path, data)
        return data, result


def locked_append_text(path: Path, lock: FileLock, line: str) -> None:
    """Append a line to a text file under file lock with fsync."""
    with lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
