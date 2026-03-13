"""Advanced parallel worker runtime — compatibility re-export.

This module has been migrated to ``open_researcher.plugins.execution.legacy_parallel``.
This file re-exports all public names for backward compatibility.
"""

from open_researcher.plugins.execution.legacy_parallel import (  # noqa: F401
    ParallelRuntimeProfile,
    build_parallel_worker_plugins,
    estimate_parallel_frontier_target,
    resolve_parallel_runtime_profile,
    resolve_parallel_worker_count,
    run_parallel_experiment_batch,
)
