"""Stress tests for GPU scheduling: concurrency, race conditions, and edge cases.

These tests target the critical issues found during deep analysis:
1. reserve_group() refresh-then-lock race window
2. No stale reservation timeout/cleanup
3. _read() without lock protection
4. release failure silently swallowed
5. nvidia-smi parsing edge cases
6. Concurrent overcommit scenarios
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from open_researcher.plugins.execution.legacy_gpu import GPUManager

NVIDIA_SMI_4GPU = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
0, 49140 MiB, 0 MiB, 49140 MiB, 0 %
1, 49140 MiB, 0 MiB, 49140 MiB, 0 %
2, 49140 MiB, 0 MiB, 49140 MiB, 0 %
3, 49140 MiB, 0 MiB, 49140 MiB, 0 %
"""

NVIDIA_SMI_2GPU = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
0, 24576 MiB, 0 MiB, 24576 MiB, 0 %
1, 24576 MiB, 0 MiB, 24576 MiB, 0 %
"""


@pytest.fixture
def gpu_file(tmp_path):
    return tmp_path / "gpu_status.json"


@pytest.fixture
def mgr(gpu_file):
    return GPUManager(gpu_file)


# ---------------------------------------------------------------------------
# 1. Concurrent reserve_group race: refresh() outside lock
# ---------------------------------------------------------------------------


def test_concurrent_reserve_group_no_double_booking(gpu_file):
    """Two threads reserving exclusive GPUs must not claim the same device.

    This tests the race window where refresh() runs outside the lock, so two
    threads can both see the same GPU as free before either acquires the lock.
    """
    mgr = GPUManager(gpu_file)
    results = []
    errors = []

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)

        barrier = threading.Barrier(2)

        def reserve_one(worker_id):
            try:
                barrier.wait(timeout=5)
                res = mgr.reserve_group(
                    count=1,
                    tag=f"worker-{worker_id}",
                    memory_mb=4096,
                    shareable=False,
                    exclusive=True,
                )
                results.append(res)
            except Exception as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(reserve_one, i) for i in range(2)]
            for f in as_completed(futures):
                f.result()

    assert not errors, f"Unexpected errors: {errors}"

    successful = [r for r in results if r is not None]
    assert len(successful) == 2

    # Each reservation should be on a different device
    devices = set()
    for res in successful:
        for item in res:
            devices.add((item["host"], item["device"]))
    assert len(devices) == 2, f"Double-booked! Devices: {devices}"


def test_concurrent_reserve_group_overcommit_rejected(gpu_file):
    """4 threads competing for 2 exclusive GPUs: exactly 2 succeed, 2 get None."""
    mgr = GPUManager(gpu_file)
    results = []

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)

        barrier = threading.Barrier(4)

        def reserve_one(worker_id):
            barrier.wait(timeout=5)
            return mgr.reserve_group(
                count=1,
                tag=f"worker-{worker_id}",
                memory_mb=4096,
                shareable=False,
                exclusive=True,
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(reserve_one, i) for i in range(4)]
            results = [f.result() for f in as_completed(futures)]

    successful = [r for r in results if r is not None]
    failed = [r for r in results if r is None]

    assert len(successful) == 2, f"Expected 2 successful, got {len(successful)}"
    assert len(failed) == 2, f"Expected 2 failed, got {len(failed)}"

    # No double-booking
    devices = set()
    for res in successful:
        for item in res:
            devices.add((item["host"], item["device"]))
    assert len(devices) == 2


def test_concurrent_allocate_release_cycle_consistency(gpu_file):
    """Rapid allocate-release cycles across 4 threads must leave no orphans."""
    mgr = GPUManager(gpu_file)
    CYCLES = 10

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_4GPU)

        def cycle(worker_id):
            for _ in range(CYCLES):
                res = mgr.reserve_group(
                    count=1,
                    tag=f"worker-{worker_id}",
                    memory_mb=4096,
                    shareable=False,
                    exclusive=True,
                )
                if res is not None:
                    mgr.release_reservations(res)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(cycle, i) for i in range(4)]
            for f in as_completed(futures):
                f.result()

    # After all cycles, no reservations should remain
    data = json.loads(gpu_file.read_text())
    for gpu in data["gpus"]:
        assert gpu["reservations"] == [], (
            f"Orphan reservation on device {gpu['device']}: {gpu['reservations']}"
        )


# ---------------------------------------------------------------------------
# 2. Stale reservation detection
# ---------------------------------------------------------------------------


def test_stale_reservation_blocks_until_ttl_reap(gpu_file):
    """A crashed worker's reservation blocks new allocations until TTL expires.

    With TTL disabled (ttl=0), the reservation persists indefinitely.
    """
    mgr = GPUManager(gpu_file, reservation_ttl_minutes=0)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)

        # Worker reserves a GPU
        res = mgr.reserve_group(
            count=1,
            tag="crashed-worker",
            memory_mb=4096,
            shareable=False,
            exclusive=True,
        )
        assert res is not None

        # Simulate crash: worker dies without calling release.
        # New worker tries to reserve 2 exclusive GPUs — should fail
        # because the stale reservation blocks GPU 0.
        res2 = mgr.reserve_group(
            count=2,
            tag="new-worker",
            memory_mb=4096,
            shareable=False,
            exclusive=True,
        )
        assert res2 is None

    # The stale reservation is still present (TTL disabled)
    data = json.loads(gpu_file.read_text())
    stale = [
        gpu for gpu in data["gpus"]
        if any(r["tag"] == "crashed-worker" for r in gpu.get("reservations", []))
    ]
    assert len(stale) == 1


def test_ttl_reaps_old_reservations_on_refresh(gpu_file):
    """refresh() automatically cleans up reservations older than the TTL."""
    from datetime import timedelta


    # Create a manager with a very short TTL for testing
    mgr = GPUManager(gpu_file, reservation_ttl_minutes=1)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)
        mgr.refresh()

    # Manually inject a reservation with a started_at 10 minutes ago
    old_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    data = json.loads(gpu_file.read_text())
    data["gpus"][0]["reservations"] = [
        {
            "id": "res-stale",
            "tag": "crashed-worker",
            "memory_mb": 4096,
            "gpu_count": 1,
            "shareable": False,
            "exclusive": True,
            "kind": "experiment",
            "started_at": old_time,
        }
    ]
    gpu_file.write_text(json.dumps(data), encoding="utf-8")

    # refresh() should reap the stale reservation
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)
        gpus = mgr.refresh()

    # Stale reservation should be gone
    for gpu in gpus:
        assert gpu["reservations"] == [], (
            f"Stale reservation not reaped on device {gpu['device']}: {gpu['reservations']}"
        )


def test_ttl_preserves_fresh_reservations(gpu_file):
    """refresh() must NOT reap reservations that are still within TTL."""
    mgr = GPUManager(gpu_file, reservation_ttl_minutes=60)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)

        res = mgr.reserve_group(
            count=1,
            tag="active-worker",
            memory_mb=4096,
            shareable=False,
            exclusive=True,
        )
        assert res is not None

        # Refresh again — the fresh reservation should survive
        gpus = mgr.refresh()

    gpu0 = next(g for g in gpus if g["device"] == 0)
    assert len(gpu0["reservations"]) == 1
    assert gpu0["reservations"][0]["tag"] == "active-worker"


def test_ttl_disabled_preserves_all_reservations(gpu_file):
    """With reservation_ttl_minutes=0, no reservations are ever reaped."""
    from datetime import timedelta

    mgr = GPUManager(gpu_file, reservation_ttl_minutes=0)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)
        mgr.refresh()

    # Inject an ancient reservation (7 days old)
    old_time = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    data = json.loads(gpu_file.read_text())
    data["gpus"][0]["reservations"] = [
        {
            "id": "res-ancient",
            "tag": "ancient-worker",
            "memory_mb": 4096,
            "gpu_count": 1,
            "shareable": False,
            "exclusive": True,
            "kind": "experiment",
            "started_at": old_time,
        }
    ]
    gpu_file.write_text(json.dumps(data), encoding="utf-8")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)
        gpus = mgr.refresh()

    gpu0 = next(g for g in gpus if g["device"] == 0)
    assert len(gpu0["reservations"]) == 1, "TTL=0 should preserve all reservations"


def test_ttl_reaps_only_expired_reservations(gpu_file):
    """Mixed reservations: only the expired one gets reaped."""
    from datetime import timedelta

    mgr = GPUManager(gpu_file, reservation_ttl_minutes=30)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)
        mgr.refresh()

    now = datetime.now(timezone.utc)
    data = json.loads(gpu_file.read_text())
    data["gpus"][0]["reservations"] = [
        {
            "id": "res-stale",
            "tag": "old-worker",
            "memory_mb": 4096,
            "gpu_count": 1,
            "shareable": True,
            "exclusive": False,
            "kind": "experiment",
            "started_at": (now - timedelta(minutes=60)).isoformat(),
        },
        {
            "id": "res-fresh",
            "tag": "new-worker",
            "memory_mb": 4096,
            "gpu_count": 1,
            "shareable": True,
            "exclusive": False,
            "kind": "experiment",
            "started_at": (now - timedelta(minutes=5)).isoformat(),
        },
    ]
    gpu_file.write_text(json.dumps(data), encoding="utf-8")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)
        gpus = mgr.refresh()

    gpu0 = next(g for g in gpus if g["device"] == 0)
    assert len(gpu0["reservations"]) == 1
    assert gpu0["reservations"][0]["tag"] == "new-worker"


# ---------------------------------------------------------------------------
# 3. _read() without lock — partial JSON resilience
# ---------------------------------------------------------------------------


def test_read_handles_corrupt_json(gpu_file):
    """_read() gracefully handles truncated/corrupt JSON files."""
    gpu_file.write_text("{\"gpus\": [", encoding="utf-8")
    mgr = GPUManager(gpu_file)
    data = mgr._read()
    assert data == {"gpus": []}


def test_read_handles_empty_file(gpu_file):
    gpu_file.write_text("", encoding="utf-8")
    mgr = GPUManager(gpu_file)
    data = mgr._read()
    assert data == {"gpus": []}


def test_read_handles_non_dict_json(gpu_file):
    gpu_file.write_text("[1, 2, 3]", encoding="utf-8")
    mgr = GPUManager(gpu_file)
    data = mgr._read()
    assert data == {"gpus": []}


def test_read_handles_missing_file(gpu_file):
    mgr = GPUManager(gpu_file)
    data = mgr._read()
    assert data == {"gpus": []}


# ---------------------------------------------------------------------------
# 4. Release robustness
# ---------------------------------------------------------------------------


def test_release_reservations_idempotent(gpu_file):
    """Releasing the same reservation twice should not error or corrupt state."""
    mgr = GPUManager(gpu_file)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)

        res = mgr.reserve_group(
            count=1,
            tag="worker-0",
            memory_mb=4096,
            shareable=False,
            exclusive=True,
        )
        assert res is not None

        # Release once
        mgr.release_reservations(res)

        # Release again — should be a no-op, not an error
        mgr.release_reservations(res)

    data = json.loads(gpu_file.read_text())
    for gpu in data["gpus"]:
        assert gpu["reservations"] == []


def test_release_with_empty_list(mgr):
    """release_reservations([]) should be a safe no-op."""
    mgr.release_reservations([])


def test_release_with_invalid_reservation_format(gpu_file):
    """release_reservations with bad data should not corrupt status file."""
    mgr = GPUManager(gpu_file)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)
        mgr.refresh()

    # Release with malformed reservation objects
    mgr.release_reservations([{"invalid": "data"}, {}])

    # Status file should still be valid
    data = json.loads(gpu_file.read_text())
    assert "gpus" in data


# ---------------------------------------------------------------------------
# 5. nvidia-smi parsing edge cases
# ---------------------------------------------------------------------------


def test_parse_nvidia_smi_empty_output(mgr):
    parsed = mgr._parse_nvidia_smi("", host="local")
    assert parsed == []


def test_parse_nvidia_smi_header_only(mgr):
    header = "index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]\n"
    parsed = mgr._parse_nvidia_smi(header, host="local")
    assert parsed == []


def test_parse_nvidia_smi_incomplete_row(mgr):
    output = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
0, 24576 MiB, 2048 MiB
"""
    parsed = mgr._parse_nvidia_smi(output, host="local")
    assert parsed == []


def test_parse_nvidia_smi_non_numeric_values(mgr):
    output = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
N/A, N/A MiB, N/A MiB, N/A MiB, N/A %
"""
    parsed = mgr._parse_nvidia_smi(output, host="local")
    assert parsed == []


def test_parse_nvidia_smi_mixed_valid_invalid(mgr):
    output = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
0, 24576 MiB, 2048 MiB, 22528 MiB, 10 %
BAD_LINE
1, 24576 MiB, 0 MiB, 24576 MiB, 5 %
"""
    parsed = mgr._parse_nvidia_smi(output, host="local")
    assert len(parsed) == 2
    assert parsed[0]["device"] == 0
    assert parsed[1]["device"] == 1


def test_parse_nvidia_smi_extra_whitespace(mgr):
    output = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
  0 ,  24576 MiB ,  2048 MiB ,  22528 MiB ,  10 %
"""
    parsed = mgr._parse_nvidia_smi(output, host="local")
    assert len(parsed) == 1
    assert parsed[0]["device"] == 0
    assert parsed[0]["memory_free"] == 22528


# ---------------------------------------------------------------------------
# 6. Refresh preserves reservations from prior state
# ---------------------------------------------------------------------------


def test_refresh_preserves_existing_reservations(gpu_file):
    """refresh() must merge new hardware state with existing reservations."""
    mgr = GPUManager(gpu_file)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_2GPU)

        # First: reserve GPU 0
        res = mgr.reserve_group(
            count=1,
            tag="active-job",
            memory_mb=4096,
            shareable=False,
            exclusive=True,
        )
        assert res is not None

        # Now refresh again (simulating periodic refresh)
        gpus = mgr.refresh()

    # The reservation on GPU 0 must still be there
    gpu0 = next(g for g in gpus if g["device"] == 0)
    assert len(gpu0["reservations"]) == 1
    assert gpu0["reservations"][0]["tag"] == "active-job"


# ---------------------------------------------------------------------------
# 7. Memory accounting and packing
# ---------------------------------------------------------------------------


def test_effective_free_memory_with_multiple_reservations(gpu_file):
    """effective_free_memory accounts for all reservations on a GPU."""
    mgr = GPUManager(gpu_file)
    gpu = {
        "host": "local",
        "device": 0,
        "memory_total": 49140,
        "memory_used": 0,
        "memory_free": 49140,
        "reservations": [
            {"id": "r1", "tag": "a", "memory_mb": 10000},
            {"id": "r2", "tag": "b", "memory_mb": 15000},
        ],
    }
    assert mgr.effective_free_memory(gpu) == 49140 - 10000 - 15000


def test_packing_rejects_when_free_insufficient(gpu_file):
    """_packable returns False when requested memory exceeds free after reservations."""
    mgr = GPUManager(gpu_file, allow_same_gpu_packing=True)
    gpu = {
        "host": "local",
        "device": 0,
        "memory_total": 24000,
        "memory_used": 0,
        "memory_free": 24000,
        "reservations": [
            {"id": "r1", "tag": "a", "memory_mb": 20000, "shareable": True, "exclusive": False},
        ],
    }
    # Only 4000 MiB free, requesting 8000
    assert mgr._packable(gpu, memory_mb=8000, shareable=True, exclusive=False) is False
    # Requesting 4000 should fit
    assert mgr._packable(gpu, memory_mb=4000, shareable=True, exclusive=False) is True


def test_packing_blocked_by_exclusive_reservation(gpu_file):
    """Cannot pack onto a GPU that has an exclusive reservation."""
    mgr = GPUManager(gpu_file, allow_same_gpu_packing=True)
    gpu = {
        "host": "local",
        "device": 0,
        "memory_total": 49000,
        "memory_used": 0,
        "memory_free": 49000,
        "reservations": [
            {"id": "r1", "tag": "a", "memory_mb": 4096, "shareable": False, "exclusive": True},
        ],
    }
    assert mgr._packable(gpu, memory_mb=4096, shareable=True, exclusive=False) is False


# ---------------------------------------------------------------------------
# 8. CUDA_VISIBLE_DEVICES scope interaction
# ---------------------------------------------------------------------------


def test_allowed_devices_restricts_reserve_candidates(gpu_file):
    """When allowed_local_devices is set, only those devices are available."""
    mgr = GPUManager(gpu_file, allowed_local_devices={2, 3})

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_4GPU)

        res = mgr.reserve_group(
            count=2,
            tag="scoped-worker",
            memory_mb=4096,
            shareable=False,
            exclusive=True,
        )

    assert res is not None
    devices = {item["device"] for item in res}
    assert devices == {2, 3}


def test_allowed_devices_none_allows_all(gpu_file):
    """When allowed_local_devices is None, all detected GPUs are available."""
    mgr = GPUManager(gpu_file, allowed_local_devices=None)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_4GPU)
        gpus = mgr.detect_local()

    assert len(gpus) == 4


# ---------------------------------------------------------------------------
# 9. High-contention concurrent reserve+release stress test
# ---------------------------------------------------------------------------


def test_high_contention_reserve_release_no_corruption(gpu_file):
    """8 threads × 20 cycles of reserve/release must not corrupt JSON state.

    This simulates a long-running system with many workers rapidly coming and going.
    """
    mgr = GPUManager(gpu_file)
    THREADS = 8
    CYCLES = 20
    errors = []

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_4GPU)
        mgr.refresh()  # Seed initial state

        def worker(wid):
            for i in range(CYCLES):
                try:
                    res = mgr.reserve_group(
                        count=1,
                        tag=f"w{wid}-c{i}",
                        memory_mb=4096,
                        shareable=True,
                        exclusive=False,
                    )
                    if res is not None:
                        # Simulate short job
                        mgr.release_reservations(res)
                except Exception as exc:
                    errors.append((wid, i, exc))

        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            futures = [executor.submit(worker, wid) for wid in range(THREADS)]
            for f in as_completed(futures):
                f.result()

    assert not errors, f"Errors during stress test: {errors}"

    # Validate final state is well-formed JSON
    data = json.loads(gpu_file.read_text())
    assert "gpus" in data
    for gpu in data["gpus"]:
        assert isinstance(gpu.get("reservations"), list)


# ---------------------------------------------------------------------------
# 10. Normalization edge cases
# ---------------------------------------------------------------------------


def test_normalize_payload_rejects_non_dict(mgr):
    result = mgr._normalize_payload("not a dict")
    assert result == {"gpus": []}


def test_normalize_payload_handles_missing_gpus(mgr):
    result = mgr._normalize_payload({"other": "data"})
    assert result == {"gpus": []}


def test_normalize_reservation_user_pin_forces_exclusive(mgr):
    res = mgr._normalize_reservation({"kind": "user_pin", "shareable": True, "exclusive": False})
    assert res["exclusive"] is True
    assert res["shareable"] is False


def test_normalize_gpu_row_migrates_legacy_allocated_to(mgr):
    row = {
        "host": "local",
        "device": 0,
        "memory_total": 24000,
        "memory_used": 0,
        "memory_free": 24000,
        "allocated_to": "legacy-tag",
    }
    normalized = mgr._normalize_gpu_row(row)
    assert len(normalized["reservations"]) == 1
    assert normalized["reservations"][0]["tag"] == "legacy-tag"
    assert normalized["reservations"][0]["kind"] == "legacy"
    assert normalized["allocated_to"] == "legacy-tag"


# ---------------------------------------------------------------------------
# 11. GPUAllocatorPlugin integration
# ---------------------------------------------------------------------------


def test_allocator_plugin_release_failure_is_not_raised(gpu_file):
    """GPUAllocatorPlugin.release() must not raise even if manager throws."""
    from open_researcher.worker_plugins import GPUAllocation, GPUAllocatorPlugin

    class ExplodingManager:
        allow_same_gpu_packing = True

        def release_reservations(self, reservations):
            raise RuntimeError("Simulated storage failure")

        def refresh(self):
            return []

        def effective_free_mb(self, gpu):
            return 0

        def plan_slots(self, max_workers, memory_mb):
            return [None]

    plugin = GPUAllocatorPlugin(ExplodingManager(), default_memory_per_worker_mb=4096)
    allocation = GPUAllocation(
        reservations=[{"id": "res-1", "host": "local", "device": 0, "memory_mb": 4096}]
    )

    # Should not raise
    plugin.release(allocation)


def test_allocator_plugin_allocate_returns_none_on_manager_error(gpu_file):
    """allocate_for_idea returns None when manager.reserve raises."""
    from open_researcher.worker_plugins import GPUAllocatorPlugin

    class BrokenManager:
        allow_same_gpu_packing = True

        def refresh(self):
            return [{"host": "local", "device": 0, "memory_total": 49000, "memory_free": 49000, "reservations": []}]

        def effective_free_mb(self, gpu):
            return int(gpu.get("memory_free", 0))

        def plan_slots(self, max_workers, memory_mb):
            return [{"host": "local", "device": 0}]

        def reserve(self, worker_id, request, **kwargs):
            raise OSError("Disk full")

        def release_reservations(self, reservations):
            pass

    plugin = GPUAllocatorPlugin(BrokenManager(), default_memory_per_worker_mb=4096)
    idea = {"id": "idea-1", "resource_request": {"gpu_count": 1, "gpu_mem_mb": 4096}}

    result = plugin.allocate_for_idea("worker-0", idea)
    assert result is None


# ---------------------------------------------------------------------------
# 12. parse_visible_cuda_devices edge cases
# ---------------------------------------------------------------------------


def test_parse_visible_cuda_devices_variants():
    from open_researcher.plugins.execution.legacy_gpu import parse_visible_cuda_devices

    assert parse_visible_cuda_devices(None) is None
    assert parse_visible_cuda_devices("") is None
    assert parse_visible_cuda_devices("0") == frozenset({0})
    assert parse_visible_cuda_devices("0,1,2") == frozenset({0, 1, 2})
    assert parse_visible_cuda_devices("GPU-abc") is None  # UUID format
    assert parse_visible_cuda_devices("0,,1") == frozenset({0, 1})  # Empty token
    assert parse_visible_cuda_devices(" 2 , 3 ") == frozenset({2, 3})  # Whitespace


# ---------------------------------------------------------------------------
# 13. Remote GPU reservation preservation on network timeout
# ---------------------------------------------------------------------------


NVIDIA_SMI_LOCAL_2GPU = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
0, 24576 MiB, 0 MiB, 24576 MiB, 0 %
1, 24576 MiB, 0 MiB, 24576 MiB, 0 %
"""


def test_refresh_preserves_remote_gpu_on_timeout(gpu_file):
    """When a remote host times out during refresh(), its GPU reservations
    must NOT be silently discarded."""
    import subprocess as sp

    # Seed state with a remote GPU + reservation
    seed = {
        "gpus": [
            {
                "host": "local", "device": 0,
                "memory_total": 24576, "memory_used": 0, "memory_free": 24576,
                "utilization": 0, "reservations": [],
            },
            {
                "host": "remote-a", "device": 0,
                "memory_total": 49140, "memory_used": 0, "memory_free": 49140,
                "utilization": 0,
                "reservations": [
                    {
                        "id": "res-remote-active",
                        "tag": "active-remote-job",
                        "memory_mb": 8192,
                        "gpu_count": 1,
                        "shareable": False,
                        "exclusive": True,
                        "kind": "experiment",
                        "started_at": datetime.now(timezone.utc).isoformat(),
                    }
                ],
            },
        ]
    }
    gpu_file.write_text(json.dumps(seed), encoding="utf-8")

    mgr = GPUManager(
        gpu_file,
        remote_hosts=[{"host": "remote-a", "user": "testuser"}],
        reservation_ttl_minutes=60,
    )

    def fake_subprocess_run(cmd, **kwargs):
        # Local nvidia-smi succeeds
        if "ssh" not in cmd:
            return MagicMock(returncode=0, stdout=NVIDIA_SMI_LOCAL_2GPU)
        # Remote ssh times out
        raise sp.TimeoutExpired(cmd, timeout=10)

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        gpus = mgr.refresh()

    # Local GPUs should be refreshed
    local_gpus = [g for g in gpus if g["host"] == "local"]
    assert len(local_gpus) == 2

    # Remote GPU should be preserved with its reservation
    remote_gpus = [g for g in gpus if g["host"] == "remote-a"]
    assert len(remote_gpus) == 1, "Remote GPU was dropped on timeout"
    assert len(remote_gpus[0]["reservations"]) == 1, "Remote reservation was lost"
    assert remote_gpus[0]["reservations"][0]["tag"] == "active-remote-job"


def test_refresh_does_not_duplicate_remote_gpu_on_success(gpu_file):
    """When a remote host is successfully refreshed, the old entry should
    not also be preserved (no duplication)."""
    seed = {
        "gpus": [
            {
                "host": "remote-a", "device": 0,
                "memory_total": 49140, "memory_used": 0, "memory_free": 49140,
                "utilization": 0, "reservations": [],
            },
        ]
    }
    gpu_file.write_text(json.dumps(seed), encoding="utf-8")

    mgr = GPUManager(
        gpu_file,
        remote_hosts=[{"host": "remote-a", "user": "testuser"}],
    )

    remote_smi = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
0, 49140 MiB, 1000 MiB, 48140 MiB, 5 %
"""

    def fake_subprocess_run(cmd, **kwargs):
        if "ssh" in cmd:
            return MagicMock(returncode=0, stdout=remote_smi)
        return MagicMock(returncode=1, stdout="")  # no local GPUs

    with patch("subprocess.run", side_effect=fake_subprocess_run):
        gpus = mgr.refresh()

    remote_gpus = [g for g in gpus if g["host"] == "remote-a"]
    assert len(remote_gpus) == 1, f"Remote GPU duplicated: {len(remote_gpus)}"
    assert remote_gpus[0]["memory_used"] == 1000  # Updated value


# ---------------------------------------------------------------------------
# 14. _reservation_age_minutes Z-suffix timestamp handling
# ---------------------------------------------------------------------------


def test_reservation_age_handles_z_suffix():
    """_reservation_age_minutes must parse ISO timestamps ending with 'Z'."""
    # Timestamp 10 minutes ago with Z suffix
    from datetime import timedelta

    from open_researcher.plugins.execution.legacy_gpu import _reservation_age_minutes
    ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    ts_z = ts.replace("+00:00", "Z")

    age = _reservation_age_minutes({"started_at": ts_z})
    assert age is not None
    assert 9.0 < age < 11.0, f"Expected ~10 min, got {age}"


def test_reservation_age_handles_plus_offset():
    """_reservation_age_minutes must parse ISO timestamps with +00:00."""
    from datetime import timedelta

    from open_researcher.plugins.execution.legacy_gpu import _reservation_age_minutes

    ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    age = _reservation_age_minutes({"started_at": ts})
    assert age is not None
    assert 4.0 < age < 6.0


def test_reservation_age_returns_none_for_garbage():
    """_reservation_age_minutes returns None for un-parseable timestamps."""
    from open_researcher.plugins.execution.legacy_gpu import _reservation_age_minutes

    assert _reservation_age_minutes({"started_at": ""}) is None
    assert _reservation_age_minutes({"started_at": "not-a-date"}) is None
    assert _reservation_age_minutes({}) is None
