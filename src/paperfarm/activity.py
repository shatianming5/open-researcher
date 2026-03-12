"""Activity monitor — track real-time agent status via activity.json."""

from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from paperfarm.storage import atomic_write_json, locked_read_json, locked_update_json


class ActivityMonitor:
    """Read/write activity.json for agent status tracking."""

    def __init__(self, research_dir: Path):
        self.path = research_dir / "activity.json"
        self._lock = FileLock(str(self.path) + ".lock")

    # ---- low-level helpers ------------------------------------------------

    def _read_locked(self) -> dict:
        """Read activity JSON under lock; returns empty dict on missing/corrupt."""
        return locked_read_json(self.path, self._lock, default=dict)

    def _write(self, data: dict) -> None:
        """Atomic write (caller must already hold the lock)."""
        atomic_write_json(self.path, data)

    # ---- public API (signatures unchanged) --------------------------------

    def update(self, agent_key: str, **kwargs) -> None:
        def _do(data):
            entry = data.get(agent_key, {})
            entry.update(kwargs)
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()
            data[agent_key] = entry

        locked_update_json(self.path, self._lock, _do, default=dict)

    def get(self, agent_key: str) -> dict | None:
        data = self._read_locked()
        return data.get(agent_key)

    def update_worker(self, agent_key: str, worker_id: str, **kwargs) -> None:
        """Update or add a worker entry within an agent's activity."""

        def _do(data):
            entry = data.get(agent_key, {})
            workers = entry.get("workers", [])
            found = False
            for w in workers:
                if w.get("id") == worker_id:
                    w.update(kwargs)
                    w["updated_at"] = datetime.now(timezone.utc).isoformat()
                    found = True
                    break
            if not found:
                worker = {"id": worker_id, **kwargs, "updated_at": datetime.now(timezone.utc).isoformat()}
                workers.append(worker)
            active_workers = [
                worker
                for worker in workers
                if str(worker.get("status", "")).strip() not in {"", "idle"}
            ]
            if active_workers:
                entry["status"] = "running"
                entry["detail"] = f"{len(active_workers)} active worker(s)"
                entry["active_workers"] = len(active_workers)
            else:
                entry["active_workers"] = 0
            entry["workers"] = workers
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()
            data[agent_key] = entry

        locked_update_json(self.path, self._lock, _do, default=dict)

    def remove_worker(self, agent_key: str, worker_id: str) -> None:
        """Remove a worker entry."""

        def _do(data):
            entry = data.get(agent_key, {})
            workers = entry.get("workers", [])
            entry["workers"] = [w for w in workers if w.get("id") != worker_id]
            active_workers = [
                worker
                for worker in entry["workers"]
                if str(worker.get("status", "")).strip() not in {"", "idle"}
            ]
            entry["active_workers"] = len(active_workers)
            if not active_workers and str(entry.get("status", "")).strip() == "running":
                entry["status"] = "idle"
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()
            data[agent_key] = entry

        locked_update_json(self.path, self._lock, _do, default=dict)

    def get_all(self) -> dict:
        return self._read_locked()
