# Project Audit Matrix

## 1. Current State Snapshot

- Execution backlog derived from this audit lives in `docs/project_remediation_backlog.md`.
- Shipping entrypoint is `run`; `start` still exists as a hidden compatibility alias.
- Public docs/examples now use `run`; `start` prints an explicit deprecation notice for legacy callers.
- Shipping execution still flows through the file-backed compatibility runtime (`run_cmd.py`, `headless.py`, `legacy_*` modules).
- The microkernel/plugin architecture is the intended direction, but it is not yet the default product path.
- TUI icon contract: render ASCII-safe symbols when `NO_COLOR` is set or `TERM=dumb`; otherwise render Unicode symbols.
- Current validation snapshot:
  - `ruff check src tests`: pass
  - `python3 -m open_researcher.cli --help`: pass
  - `python3 -m open_researcher.cli run --dry-run`: pass
  - `python3 -m open_researcher.cli doctor`: pass with warnings
  - `pytest -q`: pass (`767 passed`)
  - `python3 -m open_researcher.benchmark_smoke examples/code-perf --desc 'benchmark smoke baseline'`: pass
  - `python3 -m open_researcher.benchmark_smoke examples/cartpole --desc 'benchmark smoke baseline'`: pass
  - `python3 -m open_researcher.benchmark_smoke examples/code-perf --desc 'benchmark smoke rerun'`: pass
- Current notable warnings:
  - `bootstrap expected paths`: not configured
  - several agent binaries missing in this environment
  - GPU path unverified on this machine (`nvidia-smi` missing)

## 2. Product Surface Matrix

| Surface | What it does | Must keep? | Can simplify? | Can remove? | Notes |
|---|---|---|---|---|---|
| `run` | Main bootstrap/resume command | Yes | No | No | Core product surface |
| `start` hidden alias | Old bootstrap alias | Not long-term | Yes | Yes, later | Keep only until docs/examples stop using it |
| `init` | Creates `.research/` scaffolding | Yes | Small | No | Needed for manual setup and tests |
| `doctor` | Integrity and environment health checks | Yes | No | No | Release gate surface |
| `status` | Progress summary | Yes | Small | No | Needed for non-TUI monitoring |
| `results` | Result viewing and charting | Yes | Small | No | Needed for evidence inspection |
| `export` | Markdown report export | Useful | Yes | Maybe | Not core to runtime correctness |
| `demo` | Demo data + TUI demo | Optional | Yes | Maybe | Good for adoption, not core correctness |
| `ideas` | Backlog inspection | Useful | Yes | Maybe | Can be absorbed into `status` later |
| `logs` | Agent log access | Useful | Yes | No | Important for debugging |
| `hub` | Hub/registry workflow | Optional | Yes | Maybe | Valuable, but not required for core local loop |
| TUI `Command` tab | Main operational cockpit | Yes | No | No | Best interactive control surface |
| TUI `Execution` tab | Trend and recent runs | Yes | Small | No | Needed for result comprehension |
| TUI `Logs` tab | Trace-aware runtime logs | Yes | Small | No | Needed for operator trust/debugging |
| TUI `Docs` tab | Research docs workbench | Useful | Yes | Maybe | Could be simplified if maintenance cost stays high |
| Goal modal | Interactive goal capture | Useful | Yes | Maybe | Headless already bypasses it |
| Review screen | Human confirmation/edit after Scout | Yes in interactive mode | Yes | No | Can be simpler, but should exist |
| Parallel workers | Multi-worker experiment execution | Yes for advanced mode | No | No | Keep as advanced/runtime capability |
| GPU packing/allocation | Resource-aware worker scheduling | Optional for MVP, required for scale | Yes | Maybe for MVP | Do not remove if multi-GPU remains a product promise |
| Worktree isolation | Isolated experiment safety | Yes | No | No | Safety-critical for real runs |

## 3. Phase Responsibilities and Acceptance

### Phase 0: Goal / Session Kickoff

| Owner | Task | Acceptance | Must keep? | Simplify/remove note |
|---|---|---|---|---|
| CLI / user | select mode, agent, goal, workers, budget | valid config resolved; headless requires explicit goal; repo path is valid | Yes | Public flags should stay high-level; avoid exposing internal knobs |

### Phase 1: Scout

| Owner | Task | Acceptance | Must keep? | Simplify/remove note |
|---|---|---|---|---|
| Scout agent | understand repo, related work, strategy, evaluation contract, bootstrap hints | writes `project-understanding.md`, `literature.md`, `research-strategy.md`, `evaluation.md`; fills `config.yaml.metrics.primary.*` and `bootstrap.*`; updates `activity.json` | Yes | Web search can be optional; literature can be shortened; separate docs can be merged later if maintenance cost is too high |

### Phase 2: Prepare

| Owner | Task | Acceptance | Must keep? | Simplify/remove note |
|---|---|---|---|---|
| Runtime + bootstrap logic | resolve python/install/data/smoke and make repo runnable | `bootstrap_state.json` exists; `prepare.log` exists; smoke passes or runtime stops before experiment loop; unresolved items are explicit | Yes | Do not remove; this is the difference between "looks smart" and "can actually run" |

### Phase 3: Review

| Owner | Task | Acceptance | Must keep? | Simplify/remove note |
|---|---|---|---|---|
| User + review screen | inspect Scout outputs and prepare readiness, then confirm or reanalyze | user can confirm, edit, or reanalyze; headless may auto-confirm | Yes for interactive mode | UI can be simpler; edit affordances can stay minimal |

### Phase 4: Manager

| Owner | Task | Acceptance | Must keep? | Simplify/remove note |
|---|---|---|---|---|
| Manager agent | maintain a small frontier of hypotheses/specs/rows | graph remains schema-valid; frontier stays small and actionable; no duplicate/speculative spam; does not rewrite evidence/claims history | Yes | Frontier richness can be simplified, but "small decision-ready frontier" is core |

### Phase 5: Critic Preflight

| Owner | Task | Acceptance | Must keep? | Simplify/remove note |
|---|---|---|---|---|
| Critic agent | review draft frontier rows before execution | each draft row becomes `approved` or `rejected`; reason is explicit; multi-axis or unmeasurable work is blocked | Yes | Must keep; otherwise runtime will accumulate noisy or invalid experiments |

### Phase 6: Experiment

| Owner | Task | Acceptance | Must keep? | Simplify/remove note |
|---|---|---|---|---|
| Experiment agent | execute exactly one claimed row, make the smallest causal change, evaluate, record result, rollback if needed | exactly one row executed; graph ids preserved; metric recorded; `results.tsv` updated; backlog row updated; runtime artifacts not committed; rollback occurs on discard/crash | Yes | Must keep; this is the product's core claim |

### Phase 7: Critic Post-Review

| Owner | Task | Acceptance | Must keep? | Simplify/remove note |
|---|---|---|---|---|
| Critic agent | judge post-run evidence and update claim state | evidence reliability set; exactly one `claim_update` appended; frontier row transitions correctly; overclaiming avoided | Yes | Must keep if the product claims "research" rather than "random autotuning" |

### Phase 8: Runtime Control

| Owner | Task | Acceptance | Must keep? | Simplify/remove note |
|---|---|---|---|---|
| Runtime | pause/resume/skip, crash limit, timeout, token budget, phase gating | control actions persist; crash/timeout gates stop unsafe loops; event stream remains coherent | Yes | Token-budget policy can be simpler; pause/resume/skip and timeout should remain |

## 4. Benchmark Portfolio

### Required benchmark classes

| Class | Candidate examples | Why it matters | Must keep? | Simplify/remove note |
|---|---|---|---|---|
| Deterministic CPU micro-benchmark | `examples/code-perf` | validates metric extraction, result recording, rollback, low-cost loop behavior | Yes | Need at least one |
| Deterministic CPU/short RL loop | `examples/cartpole` | validates repeated experiment loop on a small but non-trivial task | Yes | Need at least one |
| Short single-GPU training loop | `examples/cifar10-speedrun`, `examples/nanogpt` | validates bootstrap, short training, metric improvement, reproducibility | Yes | Need at least one |
| Mid-cost realistic training/eval | `examples/hf-glue`, `examples/yolo-tiny` | validates evaluation contract under more real workflows | Yes before broad claims | Can pick one initially |
| Heavy or systems benchmark | `examples/whisper-finetune`, `examples/liger-kernel` | validates long-run stability, GPU/system path, resource-awareness | Yes before claiming scale or systems optimization | Can defer until core path is stable |

### Benchmark acceptance per class

| Gate | Acceptance | Must keep? |
|---|---|---|
| Benchmark definition | primary metric, direction, extraction rule, baseline method, smoke command are explicit | Yes |
| Smoke | finishes quickly and records one valid metric end-to-end | Yes |
| Partial run | baseline + 1 to 3 experiments complete without state corruption | Yes |
| Full run | at least one sustained session reaches intended experiment count or stop condition cleanly | Yes |
| Reproducibility | rerun on same benchmark does not corrupt state and yields same phase/control semantics | Yes |
| Unified benchmark harness | one command to run all examples | Useful | No, but strongly recommended |

### Recommended release basket

- Minimum basket before strong public claims:
  - `code-perf`
  - `cartpole`
  - one of `nanogpt` / `cifar10-speedrun`
  - one of `yolo-tiny` / `hf-glue`
- Scale/system basket before claiming multi-GPU or long-run maturity:
  - `whisper-finetune` or `liger-kernel`

## 5. Validation Gates

| Layer | What to run | Pass standard | Must keep? | Current status |
|---|---|---|---|---|
| Code layer | `ruff check src tests`, `pytest -q` | all green | Yes | Pass: both commands green on 2026-03-18 |
| Interface layer | `cli --help`, `run --dry-run`, `doctor`, key subcommands | commands work, output is coherent, warnings are explicit | Yes | Pass |
| Logic layer | graph/result/control/event consistency checks | no contradictory state across `.research/*` artifacts | Yes | Partially covered by tests and doctor |
| Smoke run layer | run one real lightweight benchmark end-to-end | one valid metric row, clean stop, no corrupted runtime state | Yes | Pass: `code-perf` and `cartpole` smoke passed on 2026-03-18; rerun append safety proved on `code-perf` |
| Partial run layer | 1 benchmark, 3 experiments | baseline + several experiments + restart safety | Yes | Not proven in this audit |
| Full real run layer | 2+ benchmarks, full budget | long-run stability, resume safety, result credibility | Yes before product claims | Not proven in this audit |
| Package smoke | `make package-check` | wheel builds and CLI launches after install | Useful | Not run in this audit |

## 6. Code Retention / Simplify / Remove Matrix

| Code area | Keep now? | Simplify? | Remove later? | Decision rule |
|---|---|---|---|---|
| `src/open_researcher/cli.py` | Yes | Small | No | Public entrypoint |
| `src/open_researcher/run_cmd.py` | Yes | Yes | Not yet | Still shipping interactive runtime |
| `src/open_researcher/headless.py` | Yes | Yes | Not yet | Still shipping headless runtime |
| `src/open_researcher/plugins/orchestrator/legacy_loop.py` | Yes | Yes | Not yet | Actual runtime engine today |
| `src/open_researcher/plugins/bootstrap/legacy_bootstrap.py` | Yes | Yes | Not yet | Actual prepare logic today |
| `src/open_researcher/plugins/graph/legacy_store.py` | Yes | Yes | Not yet | Actual canonical graph store today |
| `src/open_researcher/kernel/*` | Yes | No | No | Target architecture; continue building |
| `src/open_researcher/plugins/storage/*` | Yes | No | No | Most mature plugin path |
| `src/open_researcher/plugins/graph/store.py` | Yes | Small | No | Keep as target SQLite path |
| `src/open_researcher/plugins/scheduler/idea_pool.py` | Yes | Small | No | Keep as target scheduler/store path |
| `src/open_researcher/plugins/bootstrap/__init__.py` | Yes | Yes | No | Keep, but wire to real runtime or stop advertising it as ready |
| `src/open_researcher/plugins/orchestrator/__init__.py` | Yes | Yes | No | Same as above |
| `src/open_researcher/plugins/tui/__init__.py` | Yes | Yes | No | Same as above |
| `src/open_researcher/bootstrap.py` | Temporary | No | Yes | Delete only after all internal imports move to plugin path |
| `src/open_researcher/research_loop.py` | Temporary | No | Yes | Same rule |
| `src/open_researcher/research_graph.py` | Temporary | No | Yes | Same rule |
| `src/open_researcher/parallel_runtime.py` | Temporary | No | Yes | Same rule |
| `src/open_researcher/gpu_manager.py` | Temporary | No | Yes | Same rule |
| `src/open_researcher/worktree.py` | Temporary | No | Yes | Same rule |
| `src/open_researcher/storage.py` | Temporary | No | Yes | Same rule |
| `src/open_researcher/research_events.py` | Temporary | No | Yes | Same rule |
| Hidden `start` CLI alias | Temporary | No | Yes | Delete only after examples/docs stop using it |
| `src/open_researcher/tui/widgets.py` monolith | Yes | Yes | No | Split by widget/panel, but do not delete the functionality |
| Rich TUI polish beyond core readability | Optional | Yes | Maybe | Nice-to-have, not a release gate |
| Historical design docs in `docs/plans/` | Yes | Archive | No | Keep as migration record |

## 7. Immediate Go/No-Go Checklist

- Code-green gate completed on 2026-03-18:
  - `ruff check src tests` passes
  - `pytest -q` passes
  - TUI ASCII-vs-Unicode icon contract is documented and enforced by tests
- Must prove before claiming "works on real projects":
  - at least one partial run benchmark
  - clean restart/resume after interruption
- Must prove before claiming "scales" or "multi-GPU":
  - at least one heavy benchmark
  - validated GPU detection/scheduling path on a GPU machine
  - parallel worker correctness under real worktree isolation
