## Tree
- `src/open_researcher/`: main package
- `src/open_researcher/agents/`: Claude Code, Codex, Aider, OpenCode adapters
- `src/open_researcher/tui/`: Textual app, widgets, view-model, review UI
- `src/open_researcher/templates/`: bootstrap/research-v1 prompt and config templates
- `src/open_researcher/scripts/`: runtime helper scripts copied into `.research/scripts/`
- `tests/`: pytest suite across CLI, runtime, TUI, bootstrap, graph, workers
- `docs/`: architecture notes, screenshots, design/plan history, repo inventory
- `examples/`: example target repos and usage patterns
- `imgs/`: README screenshots

## Entry Points
- `pyproject.toml`: publishes `open-researcher = open_researcher.cli:app`
- `src/open_researcher/cli.py`: user-facing CLI for `run/init/status/results/export/doctor/demo`
- `src/open_researcher/run_cmd.py`: interactive runtime bootstrap + TUI path
- `src/open_researcher/headless.py`: headless JSONL runtime path
- `src/open_researcher/init_cmd.py`: creates `.research/` state, templates, scripts
- `src/open_researcher/graph_protocol.py`: ensures research-v1 graph/memory artifacts exist
- `src/open_researcher/status_cmd.py`: reads `.research/` and prints runtime status
- `src/open_researcher/results_cmd.py`: reads raw/derived results and charts
- `src/open_researcher/doctor_cmd.py`: health checks for repo + `.research/` state
- `demo.py` / `src/open_researcher/demo_cmd.py`: TUI demo data population

## Core Modules
- `src/open_researcher/research_loop.py`: central Scout -> Manager -> Critic -> Experiment orchestration
- `src/open_researcher/research_graph.py`: canonical research-v1 graph for hypotheses, specs, frontier, evidence, claims
- `src/open_researcher/research_memory.py`: compact long-horizon memory derived from graph outcomes
- `src/open_researcher/memory_policy.py`: history-aware family retrieval, frontier re-ranking, and policy annotations
- `src/open_researcher/research_events.py`: typed runtime event schema
- `src/open_researcher/event_journal.py`: JSONL event append/read utilities
- `src/open_researcher/bootstrap.py`: repo profile detection, prepare-plan resolution, install/data/smoke execution
- `src/open_researcher/parallel_runtime.py`: worker-batch runner over idea-pool compatibility layer
- `src/open_researcher/worker.py`: worker manager, timeout handling, result reconciliation
- `src/open_researcher/worker_plugins.py`: optional GPU, failure-memory, and worktree isolation plugins
- `src/open_researcher/worktree.py`: external git worktree creation and cleanup
- `src/open_researcher/control_plane.py`: pause/resume/skip command log and snapshot state
- `src/open_researcher/tui/view_model.py`: projects `.research/` files into TUI state
- `src/open_researcher/tui/widgets.py`: renderers for dashboard panels and docs viewer

## Config & Data
- Main config: `.research/config.yaml`
- Important config keys:
  - `experiment.timeout`
  - `experiment.max_experiments`
  - `experiment.max_parallel_workers`
  - `metrics.primary.name`
  - `metrics.primary.direction`
  - `research.protocol`
  - `research.manager_batch_size`
  - `research.critic_repro_policy`
  - `runtime.gpu_allocation`
  - `runtime.failure_memory`
  - `runtime.worktree_isolation`
  - `memory.ideation`
  - `memory.experiment`
  - `memory.repo_type_prior`
  - `roles.scout_agent|manager_agent|critic_agent|experiment_agent`
- Runtime state under `.research/`:
  - `config.yaml`
  - `bootstrap_state.json`
  - `prepare.log`
  - `results.tsv`
  - `final_results.tsv`
  - `events.jsonl`
  - `control.json`
  - `activity.json`
  - `idea_pool.json`
  - `experiment_progress.json`
  - `research_graph.json`
  - `research_memory.json`
  - `gpu_status.json`
- External assumptions:
  - must run inside a git repo
  - needs at least one supported agent CLI on `PATH`
  - parallel mode assumes git worktree support; GPU allocation is optional
  - helper scripts assume POSIX shell for `.research/scripts/rollback.sh`

## How To Run
```bash
pip install -e .[dev]

open-researcher init
open-researcher run
open-researcher run --mode headless --goal "improve latency"
open-researcher run --workers 1
open-researcher run --workers 4
open-researcher status --sparkline
open-researcher results --chart primary
open-researcher doctor
pytest -q
ruff check .
```

## Risks / Unknowns
- The canonical runtime is `research-v1`, but experiment execution still projects through `idea_pool.json` for compatibility with worker code.
- Safety guarantees around git commit/rollback are partly prompt-driven, not obviously enforced by a dedicated runtime guardrail.
- Parallel worker behavior depends on local git worktree semantics and can differ across environments.
- Example READMEs are runnable usage guides, not tested fixtures; drift is possible if CLI flags change again.
