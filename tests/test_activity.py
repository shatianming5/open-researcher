"""Tests for activity monitor."""

from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from paperfarm.activity import ActivityMonitor


@pytest.fixture
def research_dir(tmp_path):
    d = tmp_path / ".research"
    d.mkdir()
    return d


@pytest.fixture
def monitor(research_dir):
    return ActivityMonitor(research_dir)


def test_update_and_get(monitor, research_dir):
    monitor.update("manager_agent", status="analyzing", detail="reviewing #7")
    activity = monitor.get("manager_agent")
    assert activity["status"] == "analyzing"
    assert activity["detail"] == "reviewing #7"
    assert "updated_at" in activity


def test_get_missing_agent(monitor):
    assert monitor.get("nonexistent") is None


def test_update_experiment_agent(monitor):
    monitor.update(
        "experiment_agent",
        status="evaluating",
        idea="cosine LR",
        experiment=8,
        gpu={"host": "local", "device": 0},
        branch="exp/cosine-lr",
    )
    act = monitor.get("experiment_agent")
    assert act["status"] == "evaluating"
    assert act["gpu"]["device"] == 0


def test_get_all(monitor):
    monitor.update("manager_agent", status="idle")
    monitor.update("experiment_agent", status="coding")
    all_act = monitor.get_all()
    assert "manager_agent" in all_act
    assert "experiment_agent" in all_act


def test_update_worker(tmp_path):
    from paperfarm.activity import ActivityMonitor

    am = ActivityMonitor(tmp_path)
    am.update_worker("experiment_agent", "w-001", status="coding", idea="idea-001", gpus=[0])
    data = am.get("experiment_agent")
    assert "workers" in data
    assert len(data["workers"]) == 1
    assert data["workers"][0]["id"] == "w-001"
    assert data["workers"][0]["status"] == "coding"


def test_update_worker_multiple(tmp_path):
    from paperfarm.activity import ActivityMonitor

    am = ActivityMonitor(tmp_path)
    am.update_worker("experiment_agent", "w-001", status="coding", idea="idea-001", gpus=[0])
    am.update_worker("experiment_agent", "w-002", status="evaluating", idea="idea-002", gpus=[1, 2])
    data = am.get("experiment_agent")
    assert len(data["workers"]) == 2


def test_remove_worker(tmp_path):
    from paperfarm.activity import ActivityMonitor

    am = ActivityMonitor(tmp_path)
    am.update_worker("experiment_agent", "w-001", status="coding", idea="idea-001", gpus=[0])
    am.remove_worker("experiment_agent", "w-001")
    data = am.get("experiment_agent")
    assert len(data["workers"]) == 0


def test_concurrent_updates(tmp_path):
    """10 threads updating different keys — verify all 10 keys present."""
    am = ActivityMonitor(tmp_path)

    def do_update(i):
        am.update(f"agent_{i}", status=f"status_{i}", detail=f"detail_{i}")

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(do_update, i) for i in range(10)]
        for f in as_completed(futures):
            f.result()  # raise any exceptions

    all_data = am.get_all()
    assert len(all_data) == 10
    for i in range(10):
        key = f"agent_{i}"
        assert key in all_data
        assert all_data[key]["status"] == f"status_{i}"
        assert all_data[key]["detail"] == f"detail_{i}"
