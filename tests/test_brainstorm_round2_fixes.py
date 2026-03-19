"""Tests for brainstorm round-2 bug fixes:

1. _finalize_terminal_status() preserves finished_at and finished_claim_token
2. mark_done() idempotency (retry with same claim_token succeeds)
3. TokenLedger loaded from disk on ResearchLoop init
4. Config int() coercion for timeout / max_crashes / max_experiments / max_workers / search_interval
"""


import pytest

from open_researcher.config import load_config
from open_researcher.idea_pool import IdeaBacklog, IdeaPool
from open_researcher.token_tracking import TokenLedger, TokenMetrics, load_ledger, save_ledger

# ---------------------------------------------------------------------------
# Bug 1 & 2: idea_pool _finalize_terminal_status and mark_done idempotency
# ---------------------------------------------------------------------------


@pytest.fixture()
def backlog(tmp_path):
    return IdeaBacklog(tmp_path / "backlog.json")


@pytest.fixture()
def pool(tmp_path):
    return IdeaPool(tmp_path / "pool.json")


class TestFinalizeTerminalStatus:
    """Bug 1: _finalize_terminal_status should preserve finished_at and claim tokens."""

    def test_update_status_done_preserves_finished_at(self, backlog):
        idea = backlog.add("test idea")
        backlog.update_status(idea["id"], "done")
        ideas = backlog.all_ideas()
        done = [i for i in ideas if i["id"] == idea["id"]][0]
        assert done["status"] == "done"
        assert done.get("finished_at") is not None, "finished_at must be preserved after update_status('done')"

    def test_update_status_skipped_preserves_finished_at(self, backlog):
        idea = backlog.add("test idea")
        backlog.update_status(idea["id"], "skipped")
        ideas = backlog.all_ideas()
        done = [i for i in ideas if i["id"] == idea["id"]][0]
        assert done["status"] == "skipped"
        assert done.get("finished_at") is not None

    def test_mark_done_with_context_preserves_finished_at(self, backlog):
        idea = backlog.add("test idea")
        backlog.mark_done_with_context(idea["id"], 0.95, "good")
        ideas = backlog.all_ideas()
        done = [i for i in ideas if i["id"] == idea["id"]][0]
        assert done.get("finished_at") is not None

    def test_update_status_done_preserves_finished_claim_token(self, backlog):
        """When an idea has a claim_token, update_status('done') should save it to finished_claim_token."""
        idea = backlog.add("test idea")
        # Manually set claim_token to simulate parallel claim
        def _set_claim(data):
            for i in data["ideas"]:
                if i["id"] == idea["id"]:
                    i["claim_token"] = "tok-123"
                    i["claim_token_seq"] = 7
                    i["status"] = "running"
        backlog._atomic_update(_set_claim)

        backlog.update_status(idea["id"], "done")
        ideas = backlog.all_ideas()
        done = [i for i in ideas if i["id"] == idea["id"]][0]
        assert done.get("finished_claim_token") == "tok-123"
        assert done.get("finished_claim_token_seq") == 7
        # Live tokens should be cleared
        assert done.get("claim_token") is None
        assert done.get("claim_token_seq") is None

    def test_update_status_pending_clears_all(self, backlog):
        """Resetting to pending should clear both terminal and live state."""
        idea = backlog.add("test idea")
        backlog.update_status(idea["id"], "done")
        backlog.update_status(idea["id"], "pending")
        ideas = backlog.all_ideas()
        reset = [i for i in ideas if i["id"] == idea["id"]][0]
        assert reset["status"] == "pending"
        assert reset.get("finished_at") is None
        assert reset.get("finished_claim_token") is None


class TestMarkDoneIdempotency:
    """Bug 2: mark_done() should succeed on retry with the same claim_token."""

    def test_backlog_mark_done_idempotent_with_claim_token(self, backlog):
        idea = backlog.add("test idea")
        # Set claim token
        def _set_claim(data):
            for i in data["ideas"]:
                if i["id"] == idea["id"]:
                    i["claim_token"] = "tok-abc"
                    i["status"] = "running"
        backlog._atomic_update(_set_claim)

        # First call
        ok1 = backlog.mark_done_with_context(idea["id"], 0.9, "good", claim_token="tok-abc")
        assert ok1 is True

        # Retry with same token — should succeed (idempotent)
        ok2 = backlog.mark_done_with_context(idea["id"], 0.9, "good", claim_token="tok-abc")
        assert ok2 is True, "mark_done retry with same claim_token must succeed"

    def test_backlog_mark_done_rejects_wrong_token(self, backlog):
        idea = backlog.add("test idea")
        def _set_claim(data):
            for i in data["ideas"]:
                if i["id"] == idea["id"]:
                    i["claim_token"] = "tok-abc"
                    i["status"] = "running"
        backlog._atomic_update(_set_claim)

        ok = backlog.mark_done_with_context(idea["id"], 0.9, "good", claim_token="tok-WRONG")
        assert ok is False

    def test_pool_mark_done_idempotent_with_claim_token(self, pool):
        pool.add("test idea")
        # Claim the idea using the parallel API
        claimed = pool.claim_idea(worker_id="w1")
        assert claimed is not None
        token = claimed.get("claim_token")
        assert token

        # First mark_done
        ok1 = pool.mark_done(claimed["id"], 0.9, "good", claim_token=token)
        assert ok1 is True

        # Retry — should succeed
        ok2 = pool.mark_done(claimed["id"], 0.9, "good", claim_token=token)
        assert ok2 is True, "IdeaPool.mark_done retry with same claim_token must succeed"

    def test_pool_mark_done_rejects_wrong_token(self, pool):
        pool.add("test idea")
        claimed = pool.claim_idea(worker_id="w1")
        assert claimed is not None
        ok = pool.mark_done(claimed["id"], 0.9, "good", claim_token="bogus")
        assert ok is False

    def test_pool_mark_done_preserves_finished_claim_token_on_retry(self, pool):
        """On retry, finished_claim_token should remain the original token."""
        pool.add("test idea")
        claimed = pool.claim_idea(worker_id="w1")
        token = claimed["claim_token"]

        pool.mark_done(claimed["id"], 0.9, "good", claim_token=token)
        pool.mark_done(claimed["id"], 0.95, "better", claim_token=token)

        ideas = pool.all_ideas()
        done = [i for i in ideas if i["id"] == claimed["id"]][0]
        assert done.get("finished_claim_token") == token


# ---------------------------------------------------------------------------
# Bug 3: TokenLedger should be loaded from disk on ResearchLoop init
# ---------------------------------------------------------------------------


def test_load_ledger_round_trip(tmp_path):
    """save_ledger → load_ledger should restore token counts."""
    path = tmp_path / "token_ledger.json"
    ledger = TokenLedger()
    metrics = TokenMetrics(tokens_input=100, tokens_output=50)
    ledger.record(metrics, phase="scout", experiment_num=1)
    save_ledger(ledger, path)

    loaded = load_ledger(path)
    assert loaded.cumulative.tokens_total == 150


def test_load_ledger_missing_file(tmp_path):
    """Missing file returns empty ledger, not error."""
    loaded = load_ledger(tmp_path / "nonexistent.json")
    assert loaded.cumulative.tokens_total == 0


def test_research_loop_loads_ledger_from_disk(tmp_path):
    """ResearchLoop.__init__ should use load_ledger, not bare TokenLedger()."""
    # Prepare a persisted ledger
    ledger_path = tmp_path / "token_ledger.json"
    ledger = TokenLedger()
    metrics = TokenMetrics(tokens_input=500, tokens_output=300)
    ledger.record(metrics, phase="scout", experiment_num=1)
    save_ledger(ledger, ledger_path)

    from open_researcher.config import ResearchConfig
    from open_researcher.plugins.orchestrator.legacy_loop import ResearchLoop

    cfg = ResearchConfig()
    loop = ResearchLoop(
        repo_path=tmp_path,
        research_dir=tmp_path,
        cfg=cfg,
        emit=lambda e: None,
        has_pending_ideas_fn=lambda: False,
        read_latest_status_fn=lambda: "idle",
        pause_fn=lambda reason: None,
    )
    assert loop.token_ledger.cumulative.tokens_total == 800, (
        "ResearchLoop should load persisted token counts, not start from zero"
    )


# ---------------------------------------------------------------------------
# Bug 4: Config int() coercion
# ---------------------------------------------------------------------------


def _write_config(tmp_path, yaml_text):
    """Write a config.yaml inside a directory and return the directory path."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml_text)
    return tmp_path


def test_config_timeout_coerced_to_int(tmp_path):
    """timeout field from YAML string should be coerced to int."""
    d = _write_config(tmp_path, "experiment:\n  timeout: '300'\n")
    cfg = load_config(d)
    assert cfg.timeout == 300
    assert isinstance(cfg.timeout, int)


def test_config_timeout_invalid_falls_back(tmp_path):
    """Invalid (empty) timeout should fall back to default 600."""
    d = _write_config(tmp_path, "experiment:\n  timeout: ''\n")
    cfg = load_config(d)
    assert cfg.timeout == 600


def test_config_max_crashes_coerced(tmp_path):
    d = _write_config(tmp_path, "experiment:\n  max_consecutive_crashes: '5'\n")
    cfg = load_config(d)
    assert cfg.max_crashes == 5
    assert isinstance(cfg.max_crashes, int)


def test_config_max_experiments_coerced(tmp_path):
    d = _write_config(tmp_path, "experiment:\n  max_experiments: '10'\n")
    cfg = load_config(d)
    assert cfg.max_experiments == 10
    assert isinstance(cfg.max_experiments, int)


def test_config_max_workers_coerced(tmp_path):
    d = _write_config(tmp_path, "experiment:\n  max_parallel_workers: '4'\n")
    cfg = load_config(d)
    assert cfg.max_workers == 4
    assert isinstance(cfg.max_workers, int)


def test_config_search_interval_coerced(tmp_path):
    d = _write_config(tmp_path, "research:\n  search_interval: '10'\n")
    cfg = load_config(d)
    assert cfg.search_interval == 10
    assert isinstance(cfg.search_interval, int)
