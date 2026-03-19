## Tree
- `src/open_researcher/`: main package and current shipping runtime
- `src/open_researcher/agents/`: adapters for Claude Code, Codex CLI, Aider, OpenCode, Kimi CLI, Gemini CLI
- `src/open_researcher/tui/`: Textual app, review screen, view-model, widgets, styles
- `src/open_researcher/kernel/`: microkernel primitives (`EventBus`, `EventStore`, plugin registry)
- `src/open_researcher/plugins/`: in-progress pluginized architecture (storage, graph, scheduler, bootstrap, execution, orchestrator, cli, tui)
- `src/open_researcher/templates/`: `.research/` config and role-program templates
- `src/open_researcher/scripts/`: helper scripts copied into `.research/scripts/`
- `tests/`: large pytest suite spanning CLI, bootstrap, runtime, TUI, kernel, plugins, workers
- `examples/`: benchmark-style target repos and usage guides
- `docs/`: architecture notes, design plans, audits, and this inventory
- `analysis/`: internal reviews / audit notes, not product code

## Entry Points
- `pyproject.toml`: publishes `open-researcher` and `paperfarm` entrypoints
- `src/open_researcher/cli.py`: real CLI entry; `run` is the main workflow command, `start` remains as a hidden deprecated bootstrap alias
- `src/open_researcher/run_cmd.py`: interactive bootstrap/resume path with Textual TUI
- `src/open_researcher/headless.py`: headless bootstrap/resume path with JSONL events
- `src/open_researcher/init_cmd.py`: creates `.research/` scaffolding, templates, scripts
- `src/open_researcher/doctor_cmd.py`: environment and `.research/` health checks
- `src/open_researcher/status_cmd.py`: progress / phase summary reader
- `src/open_researcher/results_cmd.py`: results table, chart, and derived final-results view
- `src/open_researcher/demo_cmd.py`: local demo workspace + TUI demo
- `src/open_researcher/kernel/kernel.py`: microkernel boot/shutdown entry for plugin tests
- `src/open_researcher/benchmark_smoke.py`: deterministic lightweight benchmark smoke runner for release-gate examples

## Core Modules
- `src/open_researcher/run_cmd.py`: shipping interactive orchestration path; still drives the legacy file-backed runtime
- `src/open_researcher/headless.py`: shipping non-TUI orchestration path; emits canonical JSONL events
- `src/open_researcher/plugins/orchestrator/legacy_loop.py`: actual Scout -> Prepare -> Review -> Experiment loop used by `run` / `headless`
- `src/open_researcher/plugins/bootstrap/legacy_bootstrap.py`: repo detection, env resolution, install/data/smoke planning and execution
- `src/open_researcher/plugins/graph/legacy_store.py`: canonical file-backed `research_graph.json` compatibility layer used by the runtime
- `src/open_researcher/research_memory.py`: long-horizon ideation / experiment memory
- `src/open_researcher/results_cmd.py`: raw `results.tsv` plus critic-aware `final_results.tsv`
- `src/open_researcher/graph_protocol.py`: backfills and refreshes generated `.research/` scaffold files and helper scripts for research-v1 repos
- `src/open_researcher/tui/app.py`: 4-tab command center (`Command / Execution / Logs / Docs`)
- `src/open_researcher/tui/widgets.py`: most UI rendering logic; also contains backward-compatible `IdeaListPanel`
- `src/open_researcher/kernel/` + `src/open_researcher/plugins/*`: new microkernel/plugin architecture, currently real in tests and partial modules, not the primary product execution path
- Compatibility shims:
  - `src/open_researcher/bootstrap.py`
  - `src/open_researcher/research_loop.py`
  - `src/open_researcher/research_graph.py`
  - `src/open_researcher/parallel_runtime.py`
  - `src/open_researcher/gpu_manager.py`
  - `src/open_researcher/worktree.py`
  These re-export migrated implementations for backward compatibility.

## Config & Data
- Main runtime config: `.research/config.yaml`
- Key config surfaces:
  - `experiment.timeout`
  - `experiment.max_experiments`
  - `experiment.max_parallel_workers`
  - `metrics.primary.name`
  - `metrics.primary.direction`
  - `bootstrap.install_command`
  - `bootstrap.data_command`
  - `bootstrap.smoke_command`
  - `bootstrap.expected_paths`
  - `research.protocol`
  - `roles.scout_agent|manager_agent|critic_agent|experiment_agent`
- Main runtime artifacts under `.research/`:
  - `bootstrap_state.json`
  - `prepare.log`
  - `results.tsv`
  - `final_results.tsv`
  - `events.jsonl`
  - `control.json`
  - `activity.json`
  - `idea_pool.json`
  - `research_graph.json`
  - `research_memory.json`
  - `.internal/role_programs/*.md`
- External runtime assumptions:
  - must run inside a git repo
  - needs at least one supported agent CLI installed
  - parallel mode depends on git worktree support; GPU support is optional but affects worker packing
  - examples are benchmark scenarios and now document `run`; `start` remains only for backward compatibility

## How To Run
```bash
pip install -e ".[dev]"

python3 -m open_researcher.cli --help
python3 -m open_researcher.cli run --dry-run
python3 -m open_researcher.cli doctor
python3 -m open_researcher.benchmark_smoke examples/code-perf
python3 -m open_researcher.benchmark_smoke examples/cartpole
pytest -q
ruff check src tests
make package-check
```

## Risks / Unknowns
- The shipping workflow still uses the legacy file-backed runtime path; the microkernel/plugin path is present but not yet the default execution path.
- Several top-level modules are now compatibility re-exports, so the codebase carries both “new home” and “old import path” at once.
- Bootstrap readiness depends heavily on inferred install/data/smoke commands; unresolved data/setup steps can still leave a repo only partially runnable.
- Example READMEs are product-facing benchmark guides, so they need explicit smoke coverage; `code-perf` and `cartpole` now have a deterministic benchmark smoke path, but the training-style basket still needs partial/full validation.
