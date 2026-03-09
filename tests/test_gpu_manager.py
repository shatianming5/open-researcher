"""Tests for GPU manager."""

import json
from unittest.mock import MagicMock, patch

import pytest

from open_researcher.gpu_manager import GPUManager


@pytest.fixture
def gpu_file(tmp_path):
    return tmp_path / "gpu_status.json"


@pytest.fixture
def mgr(gpu_file):
    return GPUManager(gpu_file)


NVIDIA_SMI_OUTPUT = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
0, 24576 MiB, 2048 MiB, 22528 MiB, 10 %
1, 24576 MiB, 20000 MiB, 4576 MiB, 95 %
"""


def test_detect_local_gpus(mgr):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_OUTPUT)
        gpus = mgr.detect_local()
    assert len(gpus) == 2
    assert gpus[0]["device"] == 0
    assert gpus[0]["memory_free"] == 22528
    assert gpus[1]["memory_free"] == 4576


def test_detect_local_no_nvidia_smi(mgr):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        gpus = mgr.detect_local()
    assert gpus == []


def test_allocate_picks_most_free(mgr):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_OUTPUT)
        result = mgr.allocate()
    assert result is not None
    host, device = result
    assert host == "local"
    assert device == 0


def test_allocate_writes_status(mgr, gpu_file):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_OUTPUT)
        mgr.allocate(tag="exp-001")
    data = json.loads(gpu_file.read_text())
    allocated = [g for g in data["gpus"] if g["allocated_to"] == "exp-001"]
    assert len(allocated) == 1


def test_release(mgr, gpu_file):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_OUTPUT)
        mgr.allocate(tag="exp-001")
        mgr.release("local", 0)
    data = json.loads(gpu_file.read_text())
    g = [g for g in data["gpus"] if g["device"] == 0][0]
    assert g["allocated_to"] is None


def test_status(mgr, gpu_file):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_OUTPUT)
        mgr.refresh()
    status = mgr.status()
    assert len(status) == 2


NVIDIA_SMI_4GPU = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
0, 24576 MiB, 2048 MiB, 22528 MiB, 10 %
1, 24576 MiB, 3000 MiB, 21576 MiB, 15 %
2, 24576 MiB, 20000 MiB, 4576 MiB, 95 %
3, 24576 MiB, 1000 MiB, 23576 MiB, 5 %
"""


def test_allocate_group(mgr):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_4GPU)
        result = mgr.allocate_group(count=2, tag="exp-multi")
    assert result is not None
    assert len(result) == 2
    devices = [r[1] for r in result]
    assert 3 in devices
    assert 0 in devices


def test_allocate_group_not_enough(mgr):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_OUTPUT)
        result = mgr.allocate_group(count=5, tag="exp-big")
    assert result is None


def test_allocate_group_single(mgr):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_OUTPUT)
        result = mgr.allocate_group(count=1, tag="exp-single")
    assert result is not None
    assert len(result) == 1


def test_release_group(mgr, gpu_file):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=NVIDIA_SMI_4GPU)
        gpus = mgr.allocate_group(count=2, tag="exp-multi")
        mgr.release_group(gpus)
    data = json.loads(gpu_file.read_text())
    for g in data["gpus"]:
        assert g["allocated_to"] is None
