"""GPU manager — detect, reserve, and release GPUs (local + remote)."""

from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock

from open_researcher.storage import atomic_write_json


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GPUManager:
    """Manage GPU reservations across local and remote hosts."""

    def __init__(
        self,
        status_file: Path,
        remote_hosts: list[dict] | None = None,
        *,
        allow_same_gpu_packing: bool = True,
    ):
        self.status_file = status_file
        self.remote_hosts = remote_hosts or []
        self.allow_same_gpu_packing = allow_same_gpu_packing
        self._lock = FileLock(str(status_file) + ".lock")

    def _default_payload(self) -> dict:
        return {"gpus": []}

    def _read(self) -> dict:
        if self.status_file.exists():
            try:
                return self._normalize_payload(json.loads(self.status_file.read_text()))
            except (json.JSONDecodeError, OSError):
                pass
        return self._default_payload()

    def _write(self, data: dict) -> None:
        atomic_write_json(self.status_file, self._normalize_payload(data))

    def _normalize_payload(self, payload: Any) -> dict:
        data = payload if isinstance(payload, dict) else self._default_payload()
        rows = data.get("gpus", [])
        if not isinstance(rows, list):
            rows = []
        return {"gpus": [self._normalize_gpu_row(row) for row in rows if isinstance(row, dict)]}

    def _normalize_gpu_row(self, row: dict) -> dict:
        reservations = row.get("reservations")
        if not isinstance(reservations, list):
            reservations = []
            legacy_tag = str(row.get("allocated_to") or "").strip()
            if legacy_tag:
                reservations.append(
                    {
                        "id": f"legacy-{legacy_tag}",
                        "tag": legacy_tag,
                        "memory_mb": max(int(row.get("memory_total") or 0), 0),
                        "gpu_count": 1,
                        "shareable": False,
                        "exclusive": True,
                        "kind": "legacy",
                        "started_at": "",
                    }
                )
        normalized_reservations = [self._normalize_reservation(item) for item in reservations if isinstance(item, dict)]
        normalized = {
            "host": str(row.get("host", "local") or "local").strip() or "local",
            "device": int(row.get("device", 0) or 0),
            "memory_total": max(int(row.get("memory_total", 0) or 0), 0),
            "memory_used": max(int(row.get("memory_used", 0) or 0), 0),
            "memory_free": max(int(row.get("memory_free", 0) or 0), 0),
            "utilization": max(int(row.get("utilization", 0) or 0), 0),
            "reservations": normalized_reservations,
        }
        normalized["allocated_to"] = normalized_reservations[0]["tag"] if normalized_reservations else None
        normalized["reserved_memory_mb"] = sum(int(item.get("memory_mb", 0) or 0) for item in normalized_reservations)
        return normalized

    def _normalize_reservation(self, item: dict) -> dict:
        shareable = bool(item.get("shareable", True))
        exclusive = bool(item.get("exclusive", False))
        if exclusive:
            shareable = False
        return {
            "id": str(item.get("id") or f"res-{uuid.uuid4().hex}").strip(),
            "tag": str(item.get("tag", "") or "").strip(),
            "memory_mb": max(int(item.get("memory_mb", 0) or 0), 0),
            "gpu_count": max(int(item.get("gpu_count", 1) or 1), 1),
            "shareable": shareable,
            "exclusive": exclusive,
            "kind": str(item.get("kind", "experiment") or "experiment").strip() or "experiment",
            "started_at": str(item.get("started_at", "") or "").strip(),
            "frontier_id": str(item.get("frontier_id", "") or "").strip(),
            "execution_id": str(item.get("execution_id", "") or "").strip(),
            "idea_id": str(item.get("idea_id", "") or "").strip(),
            "worker_id": str(item.get("worker_id", "") or "").strip(),
            "resource_profile": str(item.get("resource_profile", "") or "").strip(),
            "workload_label": str(item.get("workload_label", "") or "").strip(),
        }

    def _parse_nvidia_smi(self, output: str, host: str = "local") -> list[dict]:
        gpus = []
        for line in output.strip().splitlines()[1:]:
            parts = [p.strip().replace(" MiB", "").replace(" %", "") for p in line.split(",")]
            if len(parts) < 5:
                continue
            try:
                gpus.append(
                    {
                        "host": host,
                        "device": int(parts[0]),
                        "memory_total": int(parts[1]),
                        "memory_used": int(parts[2]),
                        "memory_free": int(parts[3]),
                        "utilization": int(parts[4]),
                        "reservations": [],
                    }
                )
            except (ValueError, IndexError):
                continue
        return gpus

    def detect_local(self) -> list[dict]:
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,memory.total,memory.used,memory.free,utilization.gpu",
                    "--format=csv",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, OSError):
            return []
        if result.returncode != 0:
            return []
        return self._parse_nvidia_smi(result.stdout, host="local")

    def detect_remote(self, host: str, user: str) -> list[dict]:
        cmd = "nvidia-smi --query-gpu=index,memory.total,memory.used,memory.free,utilization.gpu --format=csv"
        result = subprocess.run(
            ["ssh", f"{user}@{host}", cmd],
            capture_output=True,
            text=True,
            timeout=10,
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
        with self._lock:
            old = self._read()
            old_reservations = {
                (g["host"], g["device"]): g.get("reservations", []) for g in old.get("gpus", []) if isinstance(g, dict)
            }
            merged = []
            for gpu in all_gpus:
                key = (gpu["host"], gpu["device"])
                gpu["reservations"] = old_reservations.get(key, [])
                merged.append(self._normalize_gpu_row(gpu))
            self._write({"gpus": merged})
        return merged

    def _packable(self, gpu: dict, *, memory_mb: int, shareable: bool, exclusive: bool) -> bool:
        reservations = gpu.get("reservations", [])
        if not isinstance(reservations, list):
            reservations = []
        if exclusive and reservations:
            return False
        if not self.allow_same_gpu_packing and reservations:
            return False
        if any(bool(item.get("exclusive", False)) or not bool(item.get("shareable", True)) for item in reservations):
            return False
        if reservations and not shareable:
            return False
        return self.effective_free_memory(gpu) >= max(int(memory_mb or 0), 0)

    def effective_free_memory(self, gpu: dict) -> int:
        reserved = sum(int(item.get("memory_mb", 0) or 0) for item in gpu.get("reservations", []))
        return max(int(gpu.get("memory_free", 0) or 0) - reserved, 0)

    def effective_free_mb(self, gpu: dict) -> int:
        return self.effective_free_memory(gpu)

    def estimate_packable_slots(self, *, default_memory_mb: int) -> int:
        gpus = self.refresh()
        budget = max(int(default_memory_mb or 0), 0)
        if budget <= 0:
            return len(gpus)
        slots = 0
        for gpu in gpus:
            if any(
                bool(item.get("exclusive", False)) or not bool(item.get("shareable", True))
                for item in gpu.get("reservations", [])
            ):
                continue
            free_mb = self.effective_free_memory(gpu)
            if self.allow_same_gpu_packing:
                slots += max(free_mb // budget, 0)
            elif not gpu.get("reservations") and free_mb >= budget:
                slots += 1
        return slots

    def plan_slots(self, *, max_workers: int, memory_mb: int) -> list[dict | None]:
        requested = max(int(max_workers or 0), 0)
        if requested <= 0:
            return []
        gpus = self.refresh()
        if not gpus:
            return [None] * requested
        budget = max(int(memory_mb or 0), 1)
        slots: list[dict | None] = []
        for gpu in gpus:
            reservations = gpu.get("reservations", [])
            if any(
                bool(item.get("exclusive", False)) or not bool(item.get("shareable", True)) for item in reservations
            ):
                continue
            if self.allow_same_gpu_packing:
                packable = max(self.effective_free_memory(gpu) // budget, 0)
            else:
                packable = 1 if not reservations and self.effective_free_memory(gpu) >= budget else 0
            for slot_index in range(packable):
                slots.append(
                    {
                        "host": gpu.get("host", "local"),
                        "device": gpu.get("device", 0),
                        "slot_index": slot_index,
                    }
                )
        if not slots:
            return [None]
        return slots[:requested]

    def can_fit_request(
        self,
        *,
        count: int,
        memory_mb: int,
        shareable: bool,
        exclusive: bool,
    ) -> bool:
        gpus = self.refresh()
        candidates = [
            gpu for gpu in gpus if self._packable(gpu, memory_mb=memory_mb, shareable=shareable, exclusive=exclusive)
        ]
        return len(candidates) >= max(int(count or 0), 1)

    def reserve_group(
        self,
        *,
        count: int = 1,
        tag: str | None = None,
        memory_mb: int = 0,
        shareable: bool = True,
        exclusive: bool = False,
        kind: str = "experiment",
        metadata: dict | None = None,
        preferred: dict | None = None,
    ) -> list[dict] | None:
        self.refresh()
        group_count = max(int(count or 0), 1)
        request_memory = max(int(memory_mb or 0), 0)
        meta = metadata if isinstance(metadata, dict) else {}
        with self._lock:
            data = self._read()
            gpus = [self._normalize_gpu_row(gpu) for gpu in data.get("gpus", []) if isinstance(gpu, dict)]
            candidates_by_host: dict[str, list[tuple[int, int, tuple[str, int], dict]]] = {}
            for gpu in gpus:
                if not self._packable(gpu, memory_mb=request_memory, shareable=shareable, exclusive=exclusive):
                    continue
                leftover = self.effective_free_memory(gpu) - request_memory
                if request_memory <= 0 and exclusive:
                    leftover = -self.effective_free_memory(gpu)
                preferred_match = (
                    0
                    if preferred
                    and str(preferred.get("host", "")).strip() == str(gpu["host"])
                    and int(preferred.get("device", -1)) == int(gpu["device"])
                    else 1
                )
                host = str(gpu["host"])
                candidates_by_host.setdefault(host, []).append(
                    (preferred_match, leftover, (str(gpu["host"]), int(gpu["device"])), gpu)
                )
            host_plans: list[tuple[int, int, str, list[tuple[int, int, tuple[str, int], dict]]]] = []
            for host, host_candidates in candidates_by_host.items():
                host_candidates.sort(key=lambda item: (item[0], item[1], item[2][1]))
                if len(host_candidates) < group_count:
                    continue
                selected = host_candidates[:group_count]
                host_plans.append(
                    (
                        min(item[0] for item in selected),
                        sum(item[1] for item in selected),
                        host,
                        selected,
                    )
                )
            if not host_plans:
                return None
            host_plans.sort(key=lambda item: (item[0], item[1], item[2]))
            selected = host_plans[0][3]

            reservations: list[dict] = []
            selected_keys = {(host, device) for _, _, (host, device), _ in selected}
            for gpu in gpus:
                key = (str(gpu["host"]), int(gpu["device"]))
                if key not in selected_keys:
                    continue
                reservation = self._normalize_reservation(
                    {
                        "id": f"res-{uuid.uuid4().hex}",
                        "tag": str(tag or "").strip(),
                        "memory_mb": request_memory,
                        "gpu_count": group_count,
                        "shareable": shareable,
                        "exclusive": exclusive,
                        "kind": kind,
                        "started_at": _utc_now(),
                        "frontier_id": meta.get("frontier_id", ""),
                        "execution_id": meta.get("execution_id", ""),
                        "idea_id": meta.get("idea_id", ""),
                        "worker_id": meta.get("worker_id", ""),
                        "resource_profile": meta.get("resource_profile", ""),
                        "workload_label": meta.get("workload_label", ""),
                    }
                )
                gpu.setdefault("reservations", []).append(reservation)
                reservations.append({"host": gpu["host"], "device": gpu["device"], **reservation})
            self._write({"gpus": gpus})
            return reservations

    def reserve(
        self,
        tag: str,
        request: dict,
        *,
        metadata: dict | None = None,
        preferred: dict | None = None,
    ) -> list[dict] | None:
        return self.reserve_group(
            count=max(int(request.get("gpu_count", 0) or 0), 1),
            tag=tag,
            memory_mb=max(int(request.get("gpu_mem_mb", 0) or 0), 0),
            shareable=bool(request.get("shareable", True)) and not bool(request.get("exclusive", False)),
            exclusive=bool(request.get("exclusive", False)),
            kind=str((metadata or {}).get("kind", "experiment") or "experiment"),
            metadata=metadata,
            preferred=preferred,
        )

    def release_reservations(self, reservations: list[dict]) -> None:
        if not reservations:
            return
        release_ids = {
            (str(item.get("host", "")), int(item.get("device", -1)), str(item.get("id", "")))
            for item in reservations
            if str(item.get("host", "")).strip() and str(item.get("id", "")).strip()
        }
        with self._lock:
            data = self._read()
            for gpu in data.get("gpus", []):
                host = str(gpu.get("host", "")).strip()
                device = int(gpu.get("device", -1))
                gpu["reservations"] = [
                    item
                    for item in gpu.get("reservations", [])
                    if (host, device, str(item.get("id", ""))) not in release_ids
                ]
            self._write(data)

    def allocate(self, tag: str | None = None) -> tuple[str, int] | None:
        self.refresh()
        with self._lock:
            data = self._read()
            gpus = [self._normalize_gpu_row(gpu) for gpu in data.get("gpus", []) if isinstance(gpu, dict)]
            free_gpus = [gpu for gpu in gpus if not gpu.get("reservations")]
            if not free_gpus:
                return None
            free_gpus.sort(
                key=lambda gpu: (
                    -self.effective_free_memory(gpu),
                    int(gpu.get("utilization", 0) or 0),
                    str(gpu.get("host", "")),
                    int(gpu.get("device", 0)),
                )
            )
            chosen = free_gpus[0]
            reservation = self._normalize_reservation(
                {
                    "id": f"res-{uuid.uuid4().hex}",
                    "tag": str(tag or "").strip(),
                    "memory_mb": 0,
                    "gpu_count": 1,
                    "shareable": False,
                    "exclusive": True,
                    "kind": "legacy",
                    "started_at": _utc_now(),
                }
            )
            chosen.setdefault("reservations", []).append(reservation)
            self._write({"gpus": gpus})
            return str(chosen["host"]), int(chosen["device"])

    def release(self, host: str, device: int) -> None:
        with self._lock:
            data = self._read()
            for gpu in data.get("gpus", []):
                if str(gpu.get("host")) == str(host) and int(gpu.get("device", -1)) == int(device):
                    gpu["reservations"] = []
            self._write(data)

    def allocate_group(self, count: int = 1, tag: str | None = None) -> list[tuple[str, int]] | None:
        requested = max(int(count or 0), 0)
        if requested <= 0:
            return []
        self.refresh()
        with self._lock:
            data = self._read()
            gpus = [self._normalize_gpu_row(gpu) for gpu in data.get("gpus", []) if isinstance(gpu, dict)]
            free_gpus = [gpu for gpu in gpus if not gpu.get("reservations")]
            if len(free_gpus) < requested:
                return None
            free_gpus.sort(
                key=lambda gpu: (
                    -self.effective_free_memory(gpu),
                    int(gpu.get("utilization", 0) or 0),
                    str(gpu.get("host", "")),
                    int(gpu.get("device", 0)),
                )
            )
            selected = free_gpus[:requested]
            for gpu in selected:
                reservation = self._normalize_reservation(
                    {
                        "id": f"res-{uuid.uuid4().hex}",
                        "tag": str(tag or "").strip(),
                        "memory_mb": 0,
                        "gpu_count": requested,
                        "shareable": False,
                        "exclusive": True,
                        "kind": "legacy",
                        "started_at": _utc_now(),
                    }
                )
                gpu.setdefault("reservations", []).append(reservation)
            self._write({"gpus": gpus})
            return [(str(gpu["host"]), int(gpu["device"])) for gpu in selected]

    def release_group(self, gpu_list: list[tuple[str, int]]) -> None:
        with self._lock:
            data = self._read()
            release_set = {(str(host), int(device)) for host, device in gpu_list}
            for gpu in data.get("gpus", []):
                if (str(gpu.get("host", "")), int(gpu.get("device", -1))) in release_set:
                    gpu["reservations"] = []
            self._write(data)

    def status(self) -> list[dict]:
        with self._lock:
            return self._read()["gpus"]
