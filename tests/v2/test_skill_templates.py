"""Tests verifying skill templates use v2 file references only.

This is the critical audit test — ensures zero v1 file references remain
in any skill template under src/open_researcher_v2/skills/.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SKILLS_DIR = (
    Path(__file__).resolve().parents[2]
    / "src" / "open_researcher_v2" / "skills"
)

# v1 file names that must NOT appear in v2 skill templates
V1_FILE_PATTERNS = [
    r"research_graph\.json",
    r"idea_pool\.json",
    r"research_memory\.json",
    r"events\.jsonl",
    r"control\.json",
    r"experiment_progress\.json",
    r"failure_memory_ledger\.json",
]

# v1 env var patterns
V1_ENV_PATTERNS = [
    r"OPEN_RESEARCHER_BOOTSTRAP_ONLY",
    r"OPEN_RESEARCHER_FRONTIER_ID",
    r"OPEN_RESEARCHER_IDEA_ID",
    r"OPEN_RESEARCHER_SINGLE_GPU_SATURATION",
    r"OPEN_RESEARCHER_SATURATION_CONTEXT_PATH",
    r"OPEN_RESEARCHER_MEMORY_POLICY",
    r"OPEN_RESEARCHER_FAILURE_CLASS",
    r"OPEN_RESEARCHER_FIRST_FIX_ACTION",
    r"OPEN_RESEARCHER_RANKED_FIXES",
]

# v1 activity format (per-agent top-level keys)
V1_ACTIVITY_PATTERNS = [
    r'"scout_agent"',
    r'"manager_agent"',
    r'"critic_agent"',
    r'"experiment_agent"',
]


def _get_skill_files() -> list[Path]:
    """Return all .md skill files."""
    return sorted(SKILLS_DIR.glob("*.md"))


class TestNoV1FileReferences:
    """Ensure no v1 file names appear in skill templates."""

    @pytest.fixture(params=_get_skill_files(), ids=lambda p: p.name)
    def skill_file(self, request) -> Path:
        return request.param

    @pytest.mark.parametrize("pattern", V1_FILE_PATTERNS, ids=V1_FILE_PATTERNS)
    def test_no_v1_file_reference(self, skill_file, pattern):
        content = skill_file.read_text(encoding="utf-8")
        matches = re.findall(pattern, content)
        assert not matches, (
            f"{skill_file.name} still references v1 file: {matches}"
        )


class TestNoV1EnvVars:
    """Ensure no v1 OPEN_RESEARCHER_* env vars appear in skill templates."""

    @pytest.fixture(params=_get_skill_files(), ids=lambda p: p.name)
    def skill_file(self, request) -> Path:
        return request.param

    @pytest.mark.parametrize("pattern", V1_ENV_PATTERNS, ids=V1_ENV_PATTERNS)
    def test_no_v1_env_var(self, skill_file, pattern):
        content = skill_file.read_text(encoding="utf-8")
        matches = re.findall(pattern, content)
        assert not matches, (
            f"{skill_file.name} still references v1 env var: {matches}"
        )


class TestNoV1ActivityFormat:
    """Ensure skill templates don't use per-agent activity.json keys."""

    @pytest.fixture(params=_get_skill_files(), ids=lambda p: p.name)
    def skill_file(self, request) -> Path:
        return request.param

    @pytest.mark.parametrize("pattern", V1_ACTIVITY_PATTERNS, ids=V1_ACTIVITY_PATTERNS)
    def test_no_v1_activity_key(self, skill_file, pattern):
        content = skill_file.read_text(encoding="utf-8")
        matches = re.findall(pattern, content)
        assert not matches, (
            f"{skill_file.name} still uses v1 activity format: {matches}"
        )


class TestV2FileReferencesPresent:
    """Verify skill templates reference the correct v2 file names."""

    def test_scout_references_graph_json(self):
        content = (SKILLS_DIR / "scout.md").read_text(encoding="utf-8")
        assert "graph.json" in content

    def test_manager_references_graph_json(self):
        content = (SKILLS_DIR / "manager.md").read_text(encoding="utf-8")
        assert "graph.json" in content

    def test_manager_references_log_jsonl(self):
        content = (SKILLS_DIR / "manager.md").read_text(encoding="utf-8")
        assert "log.jsonl" in content

    def test_manager_references_results_tsv(self):
        content = (SKILLS_DIR / "manager.md").read_text(encoding="utf-8")
        assert "results.tsv" in content

    def test_critic_references_graph_json(self):
        content = (SKILLS_DIR / "critic.md").read_text(encoding="utf-8")
        assert "graph.json" in content

    def test_critic_references_log_jsonl(self):
        content = (SKILLS_DIR / "critic.md").read_text(encoding="utf-8")
        assert "log.jsonl" in content

    def test_experiment_references_graph_json(self):
        content = (SKILLS_DIR / "experiment.md").read_text(encoding="utf-8")
        assert "graph.json" in content

    def test_experiment_references_record_py(self):
        content = (SKILLS_DIR / "experiment.md").read_text(encoding="utf-8")
        assert "scripts/record.py" in content

    def test_experiment_references_rollback_sh(self):
        content = (SKILLS_DIR / "experiment.md").read_text(encoding="utf-8")
        assert "scripts/rollback.sh" in content

    def test_experiment_references_activity_json(self):
        content = (SKILLS_DIR / "experiment.md").read_text(encoding="utf-8")
        assert "activity.json" in content

    def test_experiment_references_assigned_experiment(self):
        """experiment.md must describe the Assigned Experiment mechanism."""
        content = (SKILLS_DIR / "experiment.md").read_text(encoding="utf-8")
        assert "Assigned Experiment" in content


class TestScriptDeployment:
    """Verify helper scripts are bundled in the correct location."""

    def test_record_py_exists(self):
        assert (SKILLS_DIR / "scripts" / "record.py").exists()

    def test_rollback_sh_exists(self):
        assert (SKILLS_DIR / "scripts" / "rollback.sh").exists()

    def test_record_py_has_main(self):
        content = (SKILLS_DIR / "scripts" / "record.py").read_text(encoding="utf-8")
        assert "def main" in content
        assert "__main__" in content


class TestCliDeployment:
    """Verify cli.py includes _deploy_scripts function."""

    def test_deploy_scripts_defined(self):
        cli_path = SKILLS_DIR.parent / "cli.py"
        content = cli_path.read_text(encoding="utf-8")
        assert "_deploy_scripts" in content

    def test_deploy_scripts_called_in_run(self):
        cli_path = SKILLS_DIR.parent / "cli.py"
        content = cli_path.read_text(encoding="utf-8")
        # Must be called after research_dir.mkdir
        assert "_deploy_scripts(research_dir)" in content


class TestParallelContextPassing:
    """Verify parallel.py injects assigned experiment context."""

    def test_parallel_includes_assigned_section(self):
        parallel_path = SKILLS_DIR.parent / "parallel.py"
        content = parallel_path.read_text(encoding="utf-8")
        assert "## Assigned Experiment" in content
        assert "json.dumps" in content

    def test_parallel_imports_json(self):
        parallel_path = SKILLS_DIR.parent / "parallel.py"
        content = parallel_path.read_text(encoding="utf-8")
        assert "import json" in content
