import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from open_researcher.export_cmd import generate_report
from open_researcher.init_cmd import do_init
from open_researcher.results_cmd import load_results
from open_researcher.status_cmd import parse_research_state


def test_full_workflow():
    """Test init -> record -> status -> results -> export."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Setup git repo with a commit
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=tmpdir, capture_output=True)
        Path(tmpdir, "train.py").write_text("print('hello')")
        subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=tmpdir, capture_output=True)

        repo = Path(tmpdir)

        # 1. Init
        do_init(repo, tag="test1")
        assert (repo / ".research" / "scout_program.md").exists()
        assert (repo / ".research" / ".internal" / "role_programs" / "manager.md").exists()
        assert (repo / ".research" / "scripts" / "record.py").exists()

        # 2. Simulate agent filling in config
        config_path = repo / ".research" / "config.yaml"
        config = yaml.safe_load(config_path.read_text())
        config["metrics"]["primary"]["name"] = "accuracy"
        config["metrics"]["primary"]["direction"] = "higher_is_better"
        config_path.write_text(yaml.dump(config))

        # 3. Record baseline
        record_script = repo / ".research" / "scripts" / "record.py"
        result = subprocess.run(
            [
                sys.executable,
                str(record_script),
                "--metric",
                "accuracy",
                "--value",
                "0.85",
                "--status",
                "keep",
                "--desc",
                "baseline",
            ],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"record failed: {result.stderr}"

        # 4. Record an experiment
        result = subprocess.run(
            [
                sys.executable,
                str(record_script),
                "--metric",
                "accuracy",
                "--value",
                "0.87",
                "--secondary",
                '{"f1": 0.86}',
                "--status",
                "keep",
                "--desc",
                "increase LR",
            ],
            cwd=tmpdir,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        # 5. Check status
        state = parse_research_state(repo)
        assert state["total"] == 2
        assert state["keep"] == 2
        assert state["current_value"] == 0.87
        assert state["baseline_value"] == 0.85

        # 6. Check results
        rows = load_results(repo)
        assert len(rows) == 2

        # 7. Check export
        report = generate_report(repo)
        assert "accuracy" in report
        assert "baseline" in report
        assert "increase LR" in report


def test_research_v1_init_creates_all_runtime_files(tmp_path):
    """Verify init creates all files needed for the research-v1 runtime."""
    import json as json_mod

    from open_researcher.init_cmd import do_init

    (tmp_path / ".git").mkdir()
    do_init(repo_path=tmp_path, tag="test")
    research = tmp_path / ".research"

    assert (research / "config.yaml").exists()
    assert (research / "results.tsv").exists()

    assert (research / "idea_pool.json").exists()
    assert (research / "activity.json").exists()
    assert (research / "control.json").exists()
    assert (research / "scout_program.md").exists()
    assert (research / ".internal" / "role_programs" / "manager.md").exists()
    assert (research / ".internal" / "role_programs" / "critic.md").exists()
    assert (research / ".internal" / "role_programs" / "experiment.md").exists()

    # Verify idea_pool.json structure
    pool = json_mod.loads((research / "idea_pool.json").read_text())
    assert pool == {"ideas": []}

    # Verify control.json structure
    ctrl = json_mod.loads((research / "control.json").read_text())
    assert ctrl["paused"] is False
    assert ctrl["skip_current"] is False


def test_idea_pool_workflow(tmp_path):
    """Test the full idea lifecycle: add -> pick -> run -> done."""
    import json as json_mod

    from open_researcher.idea_pool import IdeaBacklog

    pool_file = tmp_path / "idea_pool.json"
    pool_file.write_text(json_mod.dumps({"ideas": []}))
    pool = IdeaBacklog(pool_file)

    # Add ideas
    pool.add("cosine LR", source="literature", category="training", priority=1)
    pool.add("dropout 0.3", source="original", category="regularization", priority=2)

    # Pick highest priority
    pending = pool.list_by_status("pending")
    assert pending[0]["description"] == "cosine LR"
    assert "claimed_by" not in pending[0]
    assert "assigned_experiment" not in pending[0]

    # Mark running
    pool.update_status(pending[0]["id"], "running")
    assert pool.summary()["running"] == 1
    running = pool.list_by_status("running")
    assert "assigned_experiment" not in running[0]

    # Mark done
    pool.mark_done(pending[0]["id"], metric_value=0.87, verdict="kept")
    assert pool.summary()["done"] == 1
    assert pool.summary()["pending"] == 1
