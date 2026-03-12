"""Tests for config reader."""

import pytest
import yaml

from paperfarm.config import ResearchConfig, load_config, require_supported_protocol


@pytest.fixture
def research_dir(tmp_path):
    d = tmp_path / ".research"
    d.mkdir()
    return d


def test_load_config(research_dir):
    """Load config with all fields specified."""
    config_data = {
        "mode": "collaborative",
        "experiment": {
            "timeout": 1200,
            "max_consecutive_crashes": 5,
            "max_parallel_workers": 4,
            "worker_agent": "claude-code",
        },
        "metrics": {
            "primary": {
                "name": "accuracy",
                "direction": "maximize",
            },
        },
        "gpu": {
            "remote_hosts": ["host1:8080", "host2:8080"],
        },
        "research": {
            "web_search": False,
            "search_interval": 10,
        },
    }
    config_path = research_dir / "config.yaml"
    config_path.write_text(yaml.dump(config_data))

    cfg = load_config(research_dir)

    assert cfg.mode == "collaborative"
    assert cfg.timeout == 1200
    assert cfg.max_crashes == 5
    assert cfg.max_workers == 4
    assert cfg.worker_agent == "claude-code"
    assert cfg.primary_metric == "accuracy"
    assert cfg.direction == "maximize"
    assert cfg.web_search is False
    assert cfg.search_interval == 10
    assert cfg.remote_hosts == ["host1:8080", "host2:8080"]
    assert cfg.enable_gpu_allocation is True
    assert cfg.enable_failure_memory is True
    assert cfg.enable_worktree_isolation is True


def test_load_config_defaults(research_dir):
    """Load config with minimal content -- all defaults should apply."""
    config_path = research_dir / "config.yaml"
    config_path.write_text(yaml.dump({"mode": "autonomous"}))

    cfg = load_config(research_dir)

    assert cfg.mode == "autonomous"
    assert cfg.timeout == 600
    assert cfg.max_crashes == 3
    assert cfg.max_workers == 0
    assert cfg.worker_agent == ""
    assert cfg.primary_metric == ""
    assert cfg.direction == ""
    assert cfg.web_search is True
    assert cfg.search_interval == 5
    assert cfg.remote_hosts == []
    assert cfg.enable_gpu_allocation is True
    assert cfg.enable_failure_memory is True
    assert cfg.enable_worktree_isolation is True


def test_load_config_max_experiments(research_dir):
    """max_experiments should be parsed from config."""
    config_data = {
        "experiment": {
            "max_experiments": 20,
        },
    }
    config_path = research_dir / "config.yaml"
    config_path.write_text(yaml.dump(config_data))
    cfg = load_config(research_dir)
    assert cfg.max_experiments == 20


def test_load_config_max_experiments_default(research_dir):
    """max_experiments defaults to 0 (unlimited)."""
    config_path = research_dir / "config.yaml"
    config_path.write_text(yaml.dump({"mode": "autonomous"}))
    cfg = load_config(research_dir)
    assert cfg.max_experiments == 0


def test_load_config_missing_file(research_dir):
    """When config.yaml does not exist, return all defaults."""
    cfg = load_config(research_dir)

    assert isinstance(cfg, ResearchConfig)
    assert cfg.mode == "autonomous"
    assert cfg.timeout == 600
    assert cfg.max_crashes == 3
    assert cfg.max_workers == 0
    assert cfg.worker_agent == ""
    assert cfg.primary_metric == ""
    assert cfg.direction == ""
    assert cfg.web_search is True
    assert cfg.search_interval == 5
    assert cfg.remote_hosts == []
    assert cfg.enable_gpu_allocation is True
    assert cfg.enable_failure_memory is True
    assert cfg.enable_worktree_isolation is True


def test_load_config_runtime_plugin_toggles(research_dir):
    config_data = {
        "runtime": {
            "gpu_allocation": False,
            "failure_memory": False,
            "worktree_isolation": False,
        },
    }
    config_path = research_dir / "config.yaml"
    config_path.write_text(yaml.dump(config_data))

    cfg = load_config(research_dir)

    assert cfg.enable_gpu_allocation is False
    assert cfg.enable_failure_memory is False
    assert cfg.enable_worktree_isolation is False


def test_load_config_graph_protocol_fields(research_dir):
    config_data = {
        "research": {
            "protocol": "research-v1",
            "manager_batch_size": 5,
            "critic_repro_policy": "always",
        },
        "memory": {
            "ideation": False,
            "experiment": True,
            "repo_type_prior": False,
        },
        "roles": {
            "manager_agent": "codex",
            "critic_agent": "claude-code",
        },
    }
    config_path = research_dir / "config.yaml"
    config_path.write_text(yaml.dump(config_data))

    cfg = load_config(research_dir)

    assert cfg.protocol == "research-v1"
    assert cfg.manager_batch_size == 5
    assert cfg.critic_repro_policy == "always"
    assert cfg.enable_ideation_memory is False
    assert cfg.enable_experiment_memory is True
    assert cfg.enable_repo_type_prior is False
    assert cfg.role_agents["manager_agent"] == "codex"
    assert cfg.role_agents["critic_agent"] == "claude-code"


def test_load_config_legacy_protocol_aliases_normalize_to_research_v1(research_dir):
    config_path = research_dir / "config.yaml"

    config_path.write_text(yaml.dump({"research": {"protocol": "graph-v1"}}))
    assert load_config(research_dir).protocol == "research-v1"

    config_path.write_text(yaml.dump({"research": {"protocol": "legacy"}}))
    assert load_config(research_dir).protocol == "research-v1"


def test_load_config_preserves_unknown_protocol_for_validation(research_dir):
    config_path = research_dir / "config.yaml"
    config_path.write_text(yaml.dump({"research": {"protocol": "totally-wrong"}}))

    cfg = load_config(research_dir)

    assert cfg.protocol == "totally-wrong"
    with pytest.raises(ValueError):
        require_supported_protocol(cfg)
