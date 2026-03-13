"""Tests for parallel execution configuration."""


def test_parallel_batch_config_defaults():
    from open_researcher.plugins.execution.parallel import ParallelBatchConfig

    cfg = ParallelBatchConfig()
    assert cfg.max_workers == 1
    assert cfg.gpu_ids == []
    assert cfg.timeout_seconds == 3600


def test_batch_result_defaults():
    from open_researcher.plugins.execution.parallel import BatchResult

    result = BatchResult()
    assert result.completed == 0
    assert result.failed == 0
    assert result.results == []


def test_batch_result_accumulation():
    from open_researcher.plugins.execution.parallel import BatchResult

    result = BatchResult(completed=3, failed=1, results=[{"id": 1}, {"id": 2}])
    assert result.completed == 3
    assert len(result.results) == 2
