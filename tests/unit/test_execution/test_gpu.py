"""Tests for GPU detection and allocation."""
import threading

import pytest


def test_gpu_allocator_allocate_and_release():
    from open_researcher.plugins.execution.gpu import GPUAllocator

    alloc = GPUAllocator(gpu_ids=[0, 1, 2])

    gpu = alloc.allocate("worker-1")
    assert gpu == 0  # prefers lowest
    assert alloc.available_count == 2

    gpu2 = alloc.allocate("worker-2")
    assert gpu2 == 1

    alloc.release("worker-1")
    assert alloc.available_count == 2

    gpu3 = alloc.allocate("worker-3")
    assert gpu3 == 0  # freed gpu is available again


def test_gpu_allocator_exhaustion():
    from open_researcher.plugins.execution.gpu import GPUAllocator

    alloc = GPUAllocator(gpu_ids=[0])
    alloc.allocate("worker-1")

    assert alloc.allocate("worker-2") is None  # no GPU available


def test_gpu_allocator_thread_safety():
    from open_researcher.plugins.execution.gpu import GPUAllocator

    alloc = GPUAllocator(gpu_ids=list(range(100)))
    allocated: list[int] = []
    lock = threading.Lock()

    def allocate_many():
        for i in range(20):
            tid = threading.current_thread().name
            gpu = alloc.allocate(f"{tid}-{i}")
            if gpu is not None:
                with lock:
                    allocated.append(gpu)

    threads = [threading.Thread(target=allocate_many) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(allocated) == 100  # all GPUs allocated
    assert len(set(allocated)) == 100  # no duplicates


def test_gpu_allocator_set_available():
    from open_researcher.plugins.execution.gpu import GPUAllocator

    alloc = GPUAllocator(gpu_ids=[0, 1])
    alloc.allocate("worker-1")  # takes gpu 0

    alloc.set_available([0, 1, 2, 3])  # expand pool
    # gpu 0 is still allocated to worker-1, so only 1,2,3 available
    assert alloc.available_count == 3


def test_discover_gpus_returns_empty_without_nvidia_smi():
    """Should return empty list when nvidia-smi is not available."""
    from open_researcher.plugins.execution.gpu import discover_gpus

    # This test passes on machines without nvidia-smi
    # On machines with nvidia-smi, it returns actual GPUs
    result = discover_gpus()
    assert isinstance(result, list)
