"""GPU detection and allocation for experiment workers."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class GPUSnapshot:
    """Snapshot of a single GPU's state."""

    gpu_id: int
    name: str = ""
    memory_total_mb: int = 0
    memory_used_mb: int = 0
    utilization_pct: int = 0


def discover_gpus() -> list[GPUSnapshot]:
    """Detect available GPUs using nvidia-smi. Returns empty list if unavailable."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        gpus: list[GPUSnapshot] = []
        for line in result.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                gpus.append(
                    GPUSnapshot(
                        gpu_id=int(parts[0]),
                        name=parts[1],
                        memory_total_mb=int(parts[2]),
                        memory_used_mb=int(parts[3]),
                        utilization_pct=int(parts[4]),
                    )
                )
        return gpus
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


class GPUAllocator:
    """Thread-safe GPU allocation tracker."""

    def __init__(self, gpu_ids: list[int] | None = None) -> None:
        self._lock = Lock()
        self._available: set[int] = set(gpu_ids) if gpu_ids else set()
        self._allocated: dict[str, int] = {}  # worker_id -> gpu_id

    def set_available(self, gpu_ids: list[int]) -> None:
        """Update the set of available GPUs, preserving current allocations."""
        with self._lock:
            self._available = set(gpu_ids) - set(self._allocated.values())

    def allocate(self, worker_id: str) -> int | None:
        """Allocate a GPU to a worker. Returns gpu_id or None."""
        with self._lock:
            if not self._available:
                return None
            gpu_id = min(self._available)  # prefer lowest id
            self._available.discard(gpu_id)
            self._allocated[worker_id] = gpu_id
            return gpu_id

    def release(self, worker_id: str) -> None:
        """Release a worker's GPU back to the pool."""
        with self._lock:
            gpu_id = self._allocated.pop(worker_id, None)
            if gpu_id is not None:
                self._available.add(gpu_id)

    def allocated_gpu(self, worker_id: str) -> int | None:
        """Return the GPU id allocated to a worker, or None."""
        with self._lock:
            return self._allocated.get(worker_id)

    @property
    def available_count(self) -> int:
        """Number of GPUs currently available for allocation."""
        with self._lock:
            return len(self._available)
