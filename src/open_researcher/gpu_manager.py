"""GPU manager — detect, allocate, and release GPUs (local + remote)."""

import json
import subprocess
from pathlib import Path


class GPUManager:
    """Manage GPU allocation across local and remote hosts."""

    def __init__(self, status_file: Path, remote_hosts: list[dict] | None = None):
        self.status_file = status_file
        self.remote_hosts = remote_hosts or []

    def _read(self) -> dict:
        if self.status_file.exists():
            try:
                return json.loads(self.status_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"gpus": []}

    def _write(self, data: dict) -> None:
        self.status_file.write_text(json.dumps(data, indent=2))

    def _parse_nvidia_smi(self, output: str, host: str = "local") -> list[dict]:
        gpus = []
        for line in output.strip().splitlines()[1:]:
            parts = [p.strip().replace(" MiB", "").replace(" %", "") for p in line.split(",")]
            if len(parts) < 5:
                continue
            try:
                gpus.append({
                    "host": host,
                    "device": int(parts[0]),
                    "memory_total": int(parts[1]),
                    "memory_used": int(parts[2]),
                    "memory_free": int(parts[3]),
                    "utilization": int(parts[4]),
                    "allocated_to": None,
                })
            except (ValueError, IndexError):
                continue
        return gpus

    def detect_local(self) -> list[dict]:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.total,memory.used,memory.free,utilization.gpu",
             "--format=csv"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return []
        return self._parse_nvidia_smi(result.stdout, host="local")

    def detect_remote(self, host: str, user: str) -> list[dict]:
        cmd = (
            "nvidia-smi --query-gpu=index,memory.total,memory.used,memory.free,utilization.gpu "
            "--format=csv"
        )
        result = subprocess.run(
            ["ssh", f"{user}@{host}", cmd],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []
        return self._parse_nvidia_smi(result.stdout, host=host)

    def refresh(self) -> list[dict]:
        all_gpus = self.detect_local()
        for rh in self.remote_hosts:
            try:
                all_gpus.extend(self.detect_remote(rh["host"], rh["user"]))
            except (subprocess.TimeoutExpired, OSError):
                continue
        old = self._read()
        old_alloc = {(g["host"], g["device"]): g.get("allocated_to") for g in old["gpus"]}
        for g in all_gpus:
            key = (g["host"], g["device"])
            if key in old_alloc:
                g["allocated_to"] = old_alloc[key]
        data = {"gpus": all_gpus}
        self._write(data)
        return all_gpus

    def allocate(self, tag: str | None = None) -> tuple[str, int] | None:
        gpus = self.refresh()
        free_gpus = [g for g in gpus if g["allocated_to"] is None]
        if not free_gpus:
            return None
        best = max(free_gpus, key=lambda g: g["memory_free"])
        best["allocated_to"] = tag
        self._write({"gpus": gpus})
        return (best["host"], best["device"])

    def release(self, host: str, device: int) -> None:
        data = self._read()
        for g in data["gpus"]:
            if g["host"] == host and g["device"] == device:
                g["allocated_to"] = None
        self._write(data)

    def allocate_group(self, count: int = 1, tag: str | None = None) -> list[tuple[str, int]] | None:
        """Allocate a group of N GPUs sorted by most free memory. Returns None if not enough."""
        gpus = self.refresh()
        free_gpus = [g for g in gpus if g["allocated_to"] is None]
        if len(free_gpus) < count:
            return None
        free_gpus.sort(key=lambda g: g["memory_free"], reverse=True)
        selected = free_gpus[:count]
        for g in selected:
            g["allocated_to"] = tag
        self._write({"gpus": gpus})
        return [(g["host"], g["device"]) for g in selected]

    def release_group(self, gpu_list: list[tuple[str, int]]) -> None:
        """Release a group of GPUs."""
        for host, device in gpu_list:
            self.release(host, device)

    def status(self) -> list[dict]:
        return self._read()["gpus"]
