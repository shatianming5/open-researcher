import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from open_researcher.dashboard.app import create_app


def _setup_research(tmpdir: str) -> Path:
    research = Path(tmpdir, ".research")
    research.mkdir()
    (research / "config.yaml").write_text(
        "mode: autonomous\nmetrics:\n  primary:\n    name: accuracy\n    direction: higher_is_better\n"
    )
    (research / "results.tsv").write_text(
        "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
        "2026-03-08T10:00:00\ta1b2c3d\taccuracy\t0.850000\t{}\tkeep\tbaseline\n"
    )
    (research / "project-understanding.md").write_text("# Project\nTest")
    (research / "evaluation.md").write_text("# Eval\nTest")
    return Path(tmpdir)


def test_api_status():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _setup_research(tmpdir)
        app = create_app(repo)
        client = TestClient(app)
        resp = client.get("/api/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["primary_metric"] == "accuracy"


def test_api_results():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _setup_research(tmpdir)
        app = create_app(repo)
        client = TestClient(app)
        resp = client.get("/api/results")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["status"] == "keep"


def test_api_docs():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _setup_research(tmpdir)
        app = create_app(repo)
        client = TestClient(app)
        resp = client.get("/api/docs/project-understanding.md")
        assert resp.status_code == 200
        data = resp.json()
        assert "Project" in data["content"]


def test_index_page():
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = _setup_research(tmpdir)
        app = create_app(repo)
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Open Researcher" in resp.text
