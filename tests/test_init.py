import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from open_researcher.init_cmd import do_init


@pytest.fixture
def init_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=str(tmp_path), capture_output=True)
    do_init(repo_path=tmp_path, tag="test")
    return tmp_path / ".research"


def test_init_creates_research_directory():
    """init should create .research/ with all expected files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=tmpdir, capture_output=True)

        do_init(repo_path=Path(tmpdir), tag="test1")

        research = Path(tmpdir, ".research")
        assert research.is_dir()
        assert (research / "config.yaml").is_file()
        assert (research / "project-understanding.md").is_file()
        assert (research / "evaluation.md").is_file()
        assert (research / "literature.md").is_file()
        assert (research / "ideas.md").is_file()
        assert (research / "scout_program.md").is_file()
        assert (research / ".internal" / "role_programs" / "manager.md").is_file()
        assert (research / ".internal" / "role_programs" / "critic.md").is_file()
        assert (research / ".internal" / "role_programs" / "experiment.md").is_file()
        assert (research / "results.tsv").is_file()
        assert (research / "final_results.tsv").is_file()
        assert (research / "bootstrap_state.json").is_file()
        assert not (research / "prepare.log").exists()
        assert (research / "scripts" / "record.py").is_file()
        assert (research / "scripts" / "rollback.sh").is_file()
        assert (research / "scripts" / "launch_detached.py").is_file()

        experiment = (research / ".internal" / "role_programs" / "experiment.md").read_text()
        assert "research/test1" in experiment

        # Check results.tsv has header
        results = (research / "results.tsv").read_text()
        assert results.startswith("timestamp\t")
        final_results = (research / "final_results.tsv").read_text()
        assert final_results.startswith("timestamp\t")

        # Check rollback.sh is executable
        assert os.access(research / "scripts" / "rollback.sh", os.X_OK)


def test_init_refuses_if_research_exists():
    """init should refuse if .research/ already exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        Path(tmpdir, ".research").mkdir()

        try:
            do_init(repo_path=Path(tmpdir), tag="test2")
            assert False, "Should have raised"
        except SystemExit:
            pass


def test_init_generates_default_tag():
    """init without tag should use today's date."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmpdir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=tmpdir, capture_output=True)

        do_init(repo_path=Path(tmpdir), tag=None)

        experiment = (Path(tmpdir) / ".research" / ".internal" / "role_programs" / "experiment.md").read_text()
        assert "research/" in experiment


def test_init_fails_without_git_directory(tmp_path):
    """init should fail if .git directory does not exist."""
    with pytest.raises(SystemExit):
        do_init(repo_path=tmp_path, tag="test-nogit")
    # .research should NOT have been created
    assert not (tmp_path / ".research").exists()


def test_init_creates_shared_files(tmp_path):
    """Verify init creates idea_pool.json, activity.json, control.json, and events.jsonl."""
    # Need .git for the new validation
    (tmp_path / ".git").mkdir()
    do_init(repo_path=tmp_path, tag="test")
    research = tmp_path / ".research"

    pool = research / "idea_pool.json"
    assert pool.exists()
    data = json.loads(pool.read_text())
    assert data == {"ideas": []}

    activity = research / "activity.json"
    assert activity.exists()

    control = research / "control.json"
    assert control.exists()
    data = json.loads(control.read_text())
    assert data == {"paused": False, "skip_current": False}

    events = research / "events.jsonl"
    assert events.exists()
    assert events.read_text() == ""

    assert (research / ".internal" / "role_programs" / "manager.md").exists()
    assert (research / ".internal" / "role_programs" / "critic.md").exists()
    assert (research / ".internal" / "role_programs" / "experiment.md").exists()
    assert (research / "research_graph.json").exists()
    assert (research / "research_memory.json").exists()
    assert (research / "bootstrap_state.json").exists()


def test_experiment_program_serial_mode():
    from jinja2 import Environment, PackageLoader

    env = Environment(loader=PackageLoader("open_researcher", "templates"))
    tmpl = env.get_template("experiment_program.md.j2")
    result = tmpl.render(tag="demo")
    assert "Research-v1 Job Runner" in result
    assert "one at a time" in result
    assert "experiment_progress.json" in result
    assert "research/demo" in result
    assert "research-v1" in result
    assert "execute exactly one frontier item" in result
    assert "execution_id" in result
    assert "frontier_id" in result
    assert "Never stage runtime state" in result
    assert "launch_detached.py" in result
    assert "nohup" in result


def test_init_creates_experiment_progress(init_dir):
    """init should create experiment_progress.json with phase=init."""
    progress = init_dir / "experiment_progress.json"
    assert progress.exists()
    data = json.loads(progress.read_text())
    assert data == {"phase": "init"}


def test_init_creates_gpu_status_file(init_dir):
    """init should create gpu_status.json."""
    gpu_file = init_dir / "gpu_status.json"
    assert gpu_file.exists()
    data = json.loads(gpu_file.read_text())
    assert "gpus" in data


def test_init_creates_worktrees_dir(init_dir):
    """init should create .research/worktrees/ directory."""
    worktrees = init_dir / "worktrees"
    assert worktrees.is_dir()


def test_init_excludes_research_from_git(init_dir):
    """init should keep .research out of git history by default."""
    repo = init_dir.parent
    exclude = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    exclude_path = Path(exclude)
    if not exclude_path.is_absolute():
        exclude_path = (repo / exclude_path).resolve()
    contents = (exclude_path / "info" / "exclude").read_text()
    assert "/.research" in contents
    assert "/.research/" in contents


def test_scout_program_template():
    """scout_program.md.j2 should render with goal variable."""
    from jinja2 import Environment, PackageLoader

    env = Environment(loader=PackageLoader("open_researcher", "templates"))
    tmpl = env.get_template("scout_program.md.j2")

    # With goal
    result = tmpl.render(tag="test", goal="reduce val_loss")
    assert "reduce val_loss" in result
    assert "research-strategy.md" in result
    assert "evaluation.md" in result
    assert "project-understanding.md" in result
    assert "Do NOT generate specific experiment ideas" in result

    # Without goal
    result_no_goal = tmpl.render(tag="test", goal="")
    assert "Research Goal" not in result_no_goal


def test_research_strategy_template():
    """research-strategy.md.j2 should render as empty scaffold."""
    from jinja2 import Environment, PackageLoader

    env = Environment(loader=PackageLoader("open_researcher", "templates"))
    tmpl = env.get_template("research-strategy.md.j2")
    result = tmpl.render(tag="test")
    assert "Research Direction" in result
    assert "Focus Areas" in result
    assert "Constraints" in result


def test_init_creates_scout_and_strategy_files(init_dir):
    """init should create scout_program.md and research-strategy.md."""
    assert (init_dir / "scout_program.md").is_file()
    assert (init_dir / "research-strategy.md").is_file()

    scout = (init_dir / "scout_program.md").read_text()
    assert "Scout Program" in scout

    strategy = (init_dir / "research-strategy.md").read_text()
    assert "Research Direction" in strategy
