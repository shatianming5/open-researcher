# open_researcher_v2 Acceptance Matrix

## Scope

- This document evaluates only:
  - `src/open_researcher_v2/`
  - `tests/v2/`
- It does not evaluate the larger `open_researcher` shipping runtime.
- Current local baseline observed during this audit:
  - `pytest -q tests/v2`
  - `153 passed in 3.08s`

## Design Philosophy

`open_researcher_v2` should only be considered "passing" when it behaves like a real research orchestrator, not just a green test skeleton.

The current design philosophy visible from the code and bundled skill prompts is:

1. Explicit research loop:
   - `scout -> manager -> critic -> experiment -> critic`
2. One causal change per experiment:
   - no broad refactors disguised as experiments
3. Evaluation-first:
   - the metric, direction, and evaluation command must be explicit before conclusions are trusted
4. Small decision-ready frontier:
   - do not flood the system with vague ideas
5. Evidence over hype:
   - results must be reviewable, attributable, and reproducible enough to support claims
6. Observable runtime:
   - state, logs, results, and worker ownership must be externally inspectable
7. Operator control:
   - pause, resume, skip, status, and result inspection must work without guesswork
8. Honest capability boundaries:
   - mock coverage is useful, but it does not count as benchmark proof
   - README-only benchmark profiles do not count as runnable real repos

## Current Verified Fixes

These fixes are now reflected in the current code and should be considered when judging `v2`:

| Area | Current implementation evidence | Result |
|---|---|---|
| Parallel worker call contract | `WorkerPool` now calls `Agent.run(workdir=..., program_content=..., program_file=..., env=..., on_output=...)` instead of the old mismatched signature | the earlier hard interface mismatch is fixed |
| Parallel skill payload | headless parallel mode now composes the `experiment` program and passes it into the worker pool | workers now at least receive a real prompt payload |
| GPU memory config handoff | CLI reads `workers.gpu_mem_per_worker_mb` from config and passes it to `WorkerPool` | better alignment between config and runtime |
| Frontier finalize race reduction | `finalize_experiment()` now updates graph state under `_claim_lock` | reduces concurrent load-modify-save races |
| TUI log compatibility | `LogPanel` now accepts both `event/line` and `type/message|msg` formats | log rendering is less fragile |
| TUI runner failure visibility | background runner exceptions are now appended to log state as `runner_error` | failure visibility is better than before |
| Frontier priority parsing | `FrontierPanel` now guards non-numeric priority values | TUI is more robust under imperfect state |
| Agent termination | `AgentAdapter.terminate()` now includes SIGKILL fallback after SIGTERM timeout | long-running agent shutdown is more defensible |

## Remaining High-Risk Gaps

| Gap | Why it still matters |
|---|---|
| No benchmark harness in `v2` | benchmark success still depends on ad hoc setup, not a frozen acceptance path |
| No benchmark basket frozen in code/config | "works" can still mean different things on different repos |
| Prompt/runtime state contract drift still exists | prompts still mention `research_graph.json`, `events.jsonl`, `control.json`, `idea_pool.json`, `experiment_progress.json`, while runtime state centers on `graph.json`, `log.jsonl`, and `activity.json` |
| Prompt/runtime helper-script drift still exists | the experiment prompt expects `.research/scripts/record.py`, `rollback.sh`, and `launch_detached.py`, but `v2` does not scaffold these helpers |
| No CLI preflight for missing agent binary | real users can still fail late instead of early |
| Parallel path still lacks real benchmark proof | fixed interface does not equal proven correctness on real repos |
| Most heavier benchmark profiles are README-only targets | they must not be counted as passed until a real runnable target and pinned procedure exist |

## 1. Full Lifecycle Acceptance

This section lists every runtime phase that currently exists or is implied by the `v2` design.

### Phase 0: Repo Admission

| Item | What must happen | Strict pass condition | Current status |
|---|---|---|---|
| Target repo path validation | `run` rejects a non-directory repo path | explicit non-zero exit and readable error | Pass |
| `.research/` bootstrapping | runtime creates `.research/` when absent | directory exists immediately after startup | Pass |
| Repo eligibility check | target repo must have a meaningful evaluation surface | benchmark is not admitted unless metric, command, and artifact contract are frozen | Not enforced in code |
| Git eligibility for advanced mode | parallel/worktree targets must be real git repos | `git worktree` operations succeed in the target repo | Helper code exists; real benchmark proof missing |

### Phase 1: Agent Admission

| Item | What must happen | Strict pass condition | Current status |
|---|---|---|---|
| Adapter creation | selected agent name maps to a supported adapter | invalid agent name fails deterministically | Pass |
| Binary availability | selected CLI binary must exist | fail before session start if binary missing | Not enforced in CLI |
| Output streaming | agent stdout is visible to headless or log sink | real session emits runtime-visible output | Implemented, real proof still needed |
| Clean termination | runtime can stop a running agent | terminate path returns with SIGTERM or SIGKILL fallback | Implemented |

### Phase 2: Scout

| Item | What must happen | Strict pass condition | Current status |
|---|---|---|---|
| Repo understanding | scout reads codebase and writes understanding artifacts | `.research/scout.md` prompt is executed and the expected docs appear | Prompt exists; real benchmark proof missing |
| Strategy output | repo analysis results in a bounded research direction | output is specific enough to drive manager/critic without vague filler | Prompt-defined, not code-enforced |
| Evaluation contract seeding | primary metric and evaluation command are defined | no benchmark may proceed unless metric and direction are explicit | Prompt-defined, not code-enforced |
| Resource capability discovery | scout records whether repo is CPU, single-GPU, or multi-GPU shaped | resource hints are factual and repo-grounded | Prompt-defined, not code-enforced |

### Phase 3: Manager

| Item | What must happen | Strict pass condition | Current status |
|---|---|---|---|
| Hypothesis management | manager proposes or refines hypotheses | graph remains schema-valid and hypotheses stay testable | Prompt-defined |
| Frontier curation | manager keeps a small actionable frontier | frontier is small, concrete, and execution-facing | Prompt-defined |
| Evaluation hygiene | manager repairs missing metric contract before proposing work | no draft frontier is left unmeasurable | Prompt-defined |
| Resource-scoped planning | manager does not invent unsupported launch shapes | specs remain within repo-supported runtime knobs | Prompt-defined |

### Phase 4: Critic Preflight

| Item | What must happen | Strict pass condition | Current status |
|---|---|---|---|
| Measurement gating | critic blocks unmeasurable work | no draft item reaches execution without an evaluation contract | Prompt-defined |
| Scope gating | critic blocks multi-axis or confounded changes | broad or ambiguous changes are rejected | Prompt-defined |
| Explicit reasoning | approval/rejection is recorded with a short reason | every decision is explainable and evidence-linked | Prompt-defined |

### Phase 5: Experiment

| Item | What must happen | Strict pass condition | Current status |
|---|---|---|---|
| Single-item execution | experiment runs exactly one claimed frontier item | no merged or widened experiment scope | Prompt-defined |
| Minimal change axis | experiment keeps attribution clean | one causal axis per experiment | Prompt-defined |
| Evaluation | metric is extracted from a real command | result row contains a real metric or an explicit crash/error state | Runtime stores rows; real extraction proof missing |
| Result decision | experiment records keep vs discard vs error correctly | `results.tsv` and frontier state agree | Partially implemented |
| Repro and crash handling | transient errors are retried and systematic failures are marked correctly | crash class is distinguishable from normal discard | Prompt-defined, not runtime-enforced |

### Phase 6: Critic Post-Review

| Item | What must happen | Strict pass condition | Current status |
|---|---|---|---|
| Evidence assessment | critic reviews the result and updates claim state | no optimistic upgrade without explicit evidence | Prompt-defined |
| Claim transition | exactly one claim decision follows each post-reviewable experiment | frontier and claim state remain coherent | Prompt-defined |
| Reproduction skepticism | promising but weak results become `needs_repro`, not automatic promotion | overclaiming is prevented | Prompt-defined |

### Phase 7: Monitoring and Operator Control

| Item | What must happen | Strict pass condition | Current status |
|---|---|---|---|
| Phase visibility | operator can tell where the loop currently is | `status` and TUI show the same phase and round | Pass on current local tests |
| Work visibility | operator can see frontier and worker ownership | tables reflect actual state file content | Pass for current schema |
| Pause | operator can stop new work from starting | pause flag persists and workers stop claiming new work | Implemented, mock-proven |
| Resume | operator can continue after pause | paused workers or serial loop continue cleanly | Implemented, mock-proven |
| Skip | operator can request current work to be skipped | skip flag is consumed exactly once | Implemented, mock-proven |
| Failure visibility | operator can see background runner failures | `runner_error` reaches `log.jsonl` and TUI | Partially improved |

### Phase 8: Parallel Runtime

| Item | What must happen | Strict pass condition | Current status |
|---|---|---|---|
| GPU detection | runtime discovers available GPUs and free memory | malformed or missing `nvidia-smi` does not corrupt scheduling | Pass by test |
| Slot packing | workers are assigned based on free GPU memory budget | slot count respects `max_workers` and memory budget | Pass by test |
| Worktree creation | each worker gets an isolated worktree | worktree exists and shared `.research/` symlink is correct | Pass by test |
| Frontier claiming | workers atomically claim different approved items | no duplicate claim under concurrent access | Pass by test |
| Finalization | worker completion updates frontier and result ledger | no lost result row and no frontier regression | Pass by mock-based test |
| Real parallel execution | a real agent runs successfully in isolated worktrees | benchmark-level proof on a real repo | Not proven |

### Phase 9: Status and Results Surfaces

| Item | What must happen | Strict pass condition | Current status |
|---|---|---|---|
| Summary generation | `status` uses the same state that TUI shows | counts and best value are coherent | Pass |
| Result inspection | `results` reflects `results.tsv` exactly | rows render without hidden truncation of meaning | Pass |
| Best-value summary | best result is derived from kept rows only | summary behavior is explicit and documented | Implemented, but intentionally narrow |

### Phase 10: Shutdown and Resume

| Item | What must happen | Strict pass condition | Current status |
|---|---|---|---|
| Serial completion | `run_serial()` exits cleanly on stop conditions | phase ends in `idle` unless explicitly paused | Pass by test |
| Worker stop | pool stop signal terminates worker loop | workers end in `stopped` and no corruption remains | Pass by test |
| Interrupted session resume | restart continues coherent work instead of duplicating or losing it | real benchmark proof required | Not proven |

## 2. Full Feature Inventory

This section enumerates the concrete functionality currently present in `v2`.

### 2.1 Module and Feature Inventory

| Module | Feature surface | What it currently does | Strict acceptance method |
|---|---|---|---|
| `agent.py` | adapter registry | exposes Claude Code, Codex, Aider, Gemini adapters | create each adapter, validate name mapping, validate install check behavior |
| `agent.py` | subprocess launcher | runs agent CLI with merged env and streamed output | run with a real installed agent against a tiny repo and verify line streaming |
| `agent.py` | termination | sends SIGTERM then SIGKILL fallback | run a hanging command via test adapter and confirm cleanup |
| `cli.py` | `run` | serial, parallel-headless, or TUI startup | exercise all 3 startup modes on eligible repos |
| `cli.py` | `status` | reads summary table from `.research/` | compare table output with raw files |
| `cli.py` | `results` | renders `results.tsv` rows | compare rendered table with ledger contents |
| `skill_runner.py` | protocol loading | loads `skills/protocol.yaml` | mutate protocol fixture and confirm it drives steps correctly |
| `skill_runner.py` | program composition | injects `[GOAL]` and `[TAG]` into prompts | verify emitted prompt files contain substitutions |
| `skill_runner.py` | serial loop | executes bootstrap then rounds | real-agent serial benchmark smoke |
| `skill_runner.py` | result persistence contract | serial path does not itself parse metrics or append `results.tsv`; it depends on the agent obeying the prompt contract | real-agent serial benchmark smoke must verify a real result row appears |
| `skill_runner.py` | control semantics | respects pause, skip, frontier-complete, max rounds | real run plus mock tests |
| `state.py` | config defaults | deep-merges config with defaults | direct state tests and fixture configs |
| `state.py` | graph persistence | reads/writes `graph.json` under lock | concurrent write/read stress test plus real-run state diff |
| `state.py` | results ledger | appends and reads `results.tsv` | rerun same benchmark twice and verify append-only behavior |
| `state.py` | activity state | tracks phase, round, workers, pause, skip | compare TUI and raw file after live controls |
| `state.py` | structured log | appends and tails `log.jsonl` | confirm live session produces readable log schema |
| `parallel.py` | GPU detection | parses `nvidia-smi` | CPU host tests and GPU host real validation |
| `parallel.py` | worktree lifecycle | create/cleanup shared `.research` worktrees | real git repo benchmark in parallel mode |
| `parallel.py` | frontier claiming | atomically claims approved items by priority | multi-worker real run with 2+ approved items |
| `parallel.py` | finalize | marks row `needs_post_review` and appends result | run worker completion and inspect graph + ledger |
| `tui/app.py` | app shell | runs polling TUI and background runner | mount app, watch live serial run |
| `tui/app.py` | operator controls | pause/resume/skip actions | use live session and inspect resulting state |
| `tui/widgets.py` | stats/phase display | renders current top-level state | compare with raw summary |
| `tui/widgets.py` | frontier/worker tables | renders sorted work and worker ownership | compare with graph/activity files |
| `tui/widgets.py` | log renderer | renders both `event/line` and `type/message` | feed both schemas and verify display |
| `tui/widgets.py` | metric chart | plots kept numeric result values | use mixed result ledger and verify only valid kept rows appear |

### 2.2 Runtime Files and Their Meaning

| File | Current runtime role | Must exist by which gate |
|---|---|---|
| `.research/config.yaml` | runtime config defaults and overrides | real-agent serial smoke gate |
| `.research/graph.json` | canonical graph/frontier state for current code | real-agent serial smoke gate |
| `.research/results.tsv` | append-only result ledger | benchmark smoke gate |
| `.research/activity.json` | phase, round, worker, pause, skip state | any live session gate |
| `.research/log.jsonl` | structured runtime log | any live session gate |
| `.research/*.lock` | file locks for graph/activity/log/results | not user-facing, but must appear under concurrent writes |

### 2.3 Prompt-Defined but Not Yet Runtime-Guaranteed Files

The following are part of the design intent in prompts, but are not yet canonical in the runtime implementation:

| Prompt-facing file | Prompt role expects it | Runtime reality |
|---|---|---|
| `.research/research_graph.json` | manager / critic / experiment / scout | runtime uses `.research/graph.json` |
| `.research/events.jsonl` | manager / critic / experiment | runtime uses `.research/log.jsonl` |
| `.research/control.json` | manager / critic / experiment | runtime embeds control in `.research/activity.json` |
| `.research/idea_pool.json` | manager / experiment | runtime frontier source is `graph.json` |
| `.research/experiment_progress.json` | experiment | no canonical runtime writer exists in `v2` code |
| `.research/scripts/record.py` | experiment | no canonical scaffold path exists in `v2` code |
| `.research/scripts/rollback.sh` | experiment | no canonical scaffold path exists in `v2` code |
| `.research/scripts/launch_detached.py` | experiment | no canonical scaffold path exists in `v2` code |

Strict rule:

- `v2` does not count as fully passing at the logic layer until these contracts are unified or explicitly bridged.

## 3. Benchmark Basket

Benchmark choice is the core credibility layer for `v2`.

### 3.1 Admission Rules

A repo only counts as a valid `v2` benchmark when all of the following are true:

1. It is a real runnable repo, not just a README.
2. It is committed or pinned to a specific git revision.
3. It has a single explicit primary metric.
4. Metric direction is explicit.
5. Evaluation command is explicit.
6. Smoke command is explicit.
7. Expected artifacts are explicit.
8. Hardware class is explicit.
9. Reset/cleanup rule is explicit.
10. The evaluation result is machine-checkable from stdout or a stable artifact.
11. Any helper scripts or control artifacts assumed by the experiment contract must either exist or be replaced by a unified runtime-native equivalent.

Strict non-negotiable rule:

- A README-only target does not count as a passed benchmark, even if the README describes a realistic workflow.

### 3.2 Current Benchmark Basket Status

| Benchmark id | Repo target | Current repo status | Admission status |
|---|---|---|---|
| `B1-code-perf` | `examples/code-perf` | runnable code exists | admissible now |
| `B2-cartpole` | `examples/cartpole` | runnable code exists | admissible now |
| `B3-cifar10` | `examples/cifar10-speedrun` | README only | not admissible yet |
| `B3-nanogpt` | external `karpathy/nanoGPT` flow described by README | not pinned in current repo | target profile only |
| `B4-hf-glue` | external `huggingface/transformers` flow described by README | not pinned in current repo | target profile only |
| `B4-yolo-tiny` | `examples/yolo-tiny` README profile | README only | not admissible yet |
| `B5-whisper` | `examples/whisper-finetune` README profile | README only | not admissible yet |
| `B5-liger` | external `linkedin/Liger-Kernel` flow described by README | not pinned in current repo | target profile only |

### 3.3 Real Repos to Run Right Now

These are the only benchmark repos that should be counted as immediately runnable inside the current repository tree:

| Benchmark id | Repo path | Metric | Hardware | Why it matters |
|---|---|---|---|---|
| `B1-code-perf` | `examples/code-perf` | `ops_per_sec` | CPU | deterministic micro-benchmark for metric extraction and rerun safety |
| `B2-cartpole` | `examples/cartpole` | `avg_reward` | CPU | repeated-loop benchmark with non-trivial training/evaluation behavior |

### 3.4 Target Real Repos to Promote Next

These are legitimate next-step real repos, but they should not be counted as passed until pinned and fully admitted:

| Benchmark id | Real repo target | Why it fits the design |
|---|---|---|
| `B3-nanogpt` | `karpathy/nanoGPT` | explicit train/eval loop, single-GPU friendly, meaningful scalar metric |
| `B4-hf-glue` | `huggingface/transformers` with SST-2 fine-tuning path | realistic NLP fine-tuning and explicit validation metric |
| `B4-yolo` | a pinned YOLO training repo or a committed local fixture | realistic vision training/eval surface |
| `B5-whisper` | a pinned Whisper fine-tuning repo | longer-run, artifact-heavy speech workload |
| `B5-liger` | `linkedin/Liger-Kernel` | systems benchmark for kernel optimization and GPU/runtime behavior |

## 4. Strict Acceptance Per Benchmark

### 4.1 `B1-code-perf`

Repo:

- `/Users/shatianming/Downloads/open-researcher/examples/code-perf`

Admission:

- must be copied or checked out as a real git repo before advanced acceptance
- `bench.py` must print `ops_per_sec <value>`
- correctness must remain enforced by the assertions inside `bench.py`

Smoke acceptance:

1. Run the benchmark baseline directly:
   - `python bench.py`
2. Start `v2` against a git-backed copy with a real installed agent:
   - `open-researcher-v2 run <repo> --headless --goal "maximize ops_per_sec"`
3. Pass only if all of the following are true:
   - `.research/results.tsv` exists
   - at least one row is appended
   - at least one row contains a real machine-checkable `ops_per_sec` value
   - `graph.json`, `activity.json`, and `log.jsonl` exist
   - `status` command and raw files agree on counts
   - rerunning does not corrupt prior rows

Strict interpretation:

- if the session only records a coarse success status without the real metric, that is only a structural runtime pass
- it does not count as a benchmark smoke pass

Strict partial-run acceptance:

- at least 3 completed experiment cycles
- no corrupted state file
- no duplicate frontier claim for the same active item
- at least one kept result with benchmark correctness still enforced
- best kept `ops_per_sec >= baseline * 1.05`

Why this is strict:

- improvement without preserved correctness does not count
- one appended row alone is not enough if state becomes contradictory

### 4.2 `B2-cartpole`

Repo:

- `/Users/shatianming/Downloads/open-researcher/examples/cartpole`

Admission:

- must be copied or checked out as a real git repo before advanced acceptance
- `train.py` must print `avg_reward <value>`
- environment dependencies must be frozen

Smoke acceptance:

1. Run direct baseline:
   - `python train.py`
2. Run `v2` serial headless with a real agent.
3. Pass only if:
   - at least one result row exists
   - at least one row contains a real machine-checkable `avg_reward` value
   - raw training/eval completes without state corruption
   - `status` and TUI agree with result count
   - `pause`, `resume`, and `skip` semantics remain coherent during a live session

Strict interpretation:

- if the session only records an exit-status row without `avg_reward`, that is only a structural runtime pass
- it does not count as a benchmark smoke pass

Strict partial-run acceptance:

- baseline + 3 experiment cycles complete
- one deliberate interruption and restart does not duplicate or lose work
- all resulting files remain parseable
- at least one kept result survives post-run review state transition
- best kept `avg_reward >= max(175, baseline + 20)`

Why this is strict:

- RL is noisier than `code-perf`, so state coherence and restart semantics matter as much as raw score

### 4.3 `B3-nanogpt`

Repo:

- pinned clone of `karpathy/nanoGPT`

This benchmark may only enter the basket after all of these are frozen in writing:

- exact commit hash
- install command
- data preparation command
- smoke command
- evaluation command
- metric extraction rule for `val_loss`
- GPU memory class
- expected runtime budget

Smoke acceptance:

- one short smoke run completes end-to-end
- a parseable `val_loss` is recorded
- no prompt/runtime schema mismatch blocks the loop

Strict partial-run acceptance:

- baseline + 3 experiments
- one restart/resume in the middle
- best kept `val_loss <= baseline - 0.02`
- no stranded worktree or broken worker state

### 4.4 `B4-hf-glue`

Repo:

- pinned clone of `huggingface/transformers` using an SST-2 fine-tuning path

Admission requires:

- exact script path and task
- reduced smoke subset
- explicit metric `eval_accuracy`
- stable extraction rule

Smoke acceptance:

- one reduced validation run finishes
- `eval_accuracy` is recorded
- `v2` state remains coherent

Strict partial-run acceptance:

- baseline + 3 experiments
- at least one kept result with `eval_accuracy >= baseline + 0.5 point`
- no broken artifact references

### 4.5 `B4-yolo`

Repo:

- committed local YOLO fixture or pinned external YOLO repo

Admission requires:

- actual training script exists
- actual dataset path and smoke subset exist
- `mAP50` extraction is machine-checkable

Strict partial-run acceptance:

- baseline + 3 experiments
- at least one kept result with `mAP50 >= baseline + 2 points`
- no artifact confusion between train and eval outputs

### 4.6 `B5-whisper`

Repo:

- committed local Whisper fixture or pinned external fine-tuning repo

Admission requires:

- real dataset subset
- explicit WER extraction rule
- artifact retention rules
- GPU class and duration budget

Strict full-run acceptance:

- one smoke run
- one partial run
- one long real run with clean final state
- best kept WER meaningfully better than baseline

### 4.7 `B5-liger`

Repo:

- pinned clone of `linkedin/Liger-Kernel`

Admission requires:

- kernel benchmark command
- reference baseline command
- speedup metric extraction
- GPU host with validated driver/toolchain

Strict parallel/system acceptance:

- worktree isolation proven on a real GPU host
- kernel benchmark completes in a worker-owned worktree
- recorded speedup is attributable to the tested kernel change

## 5. Layered Validation Gates

### 5.1 Code Layer

| Goal | What to run | Strict pass condition | Current status |
|---|---|---|---|
| v2 code-green baseline | `pytest -q tests/v2` | all tests pass | Pass |
| real-agent signature protection | add direct integration tests for real `Agent.run` serial and parallel usage | no mock-only path hides a runtime mismatch | Not fully proven |
| file-schema protection | tests assert actual files written by real sessions | prompts, CLI, TUI, and state layer agree on file contract | Not proven |

### 5.2 Interface Layer

| Goal | What to run | Strict pass condition | Current status |
|---|---|---|---|
| CLI surface | `run`, `status`, `results`, `--help` | every public command is explicit and non-confusing | Mostly pass |
| real missing-agent behavior | select an unavailable agent binary | runtime fails before deeper work begins | Not implemented |
| TUI surface | run live TUI session on admissible repo | no silent UI freeze hides a failed runner | Improved, not fully proven |

### 5.3 Logic Layer

| Goal | What to run | Strict pass condition | Current status |
|---|---|---|---|
| serial loop correctness | `scout -> manager -> critic -> experiment -> critic` on a real repo | phase progression, logs, results, and frontier transitions remain coherent | Mock-proven, real-run proof missing |
| control correctness | live pause/resume/skip on a real benchmark | no duplicate skip, no ghost running state | Mock-proven, real-run proof missing |
| prompt/runtime contract correctness | real agent follows current state files without manual intervention | no role writes the wrong canonical file | Not proven |

### 5.4 Smoke Layer

| Goal | What to run | Strict pass condition | Current status |
|---|---|---|---|
| deterministic CPU smoke | `B1-code-perf` | valid metric-bearing result and coherent state | Not yet proven in `v2` |
| iterative CPU smoke | `B2-cartpole` | valid result and coherent state under a slightly richer training loop | Not yet proven in `v2` |
| parallel worker smoke | 1 approved item in headless parallel mode | worker completes, result recorded, worktree cleaned | Not yet proven with a real agent |

### 5.5 Partial Layer

| Goal | What to run | Strict pass condition | Current status |
|---|---|---|---|
| loop durability | `B1` or `B2` baseline + 3 experiments | no file corruption, no stuck frontier, no contradictory summary | Not proven |
| restart safety | interrupt and restart same benchmark | no duplicated or lost work | Not proven |
| review semantics | post-run status and claims remain coherent | no overclaiming, no invisible result transitions | Not proven |

### 5.6 Full Real Layer

| Goal | What to run | Strict pass condition | Current status |
|---|---|---|---|
| realistic repo usefulness | `B3` and `B4` class repos | at least one real ML repo passes partial gate | Not proven |
| advanced parallel claim | `B5` on real GPU host | 2+ workers, worktree isolation, recorded evidence | Not proven |
| product-grade claim | 2 or more benchmark classes fully mature | repeatable, attributable, and operator-visible | Not proven |

## 6. Exact Acceptance Procedures

### 6.1 Minimal Honest Claim for Today

The strongest honest claim `v2` can make today is:

- it is a green, test-covered research-orchestrator skeleton
- it has a basic CLI and basic monitoring TUI
- it has tested state management and worktree helpers
- it has two immediately admissible local benchmark targets:
  - `B1-code-perf`
  - `B2-cartpole`
- it is not yet benchmark-proven end-to-end on a real agent-driven workflow

### 6.2 What Must Happen Before Saying "v2 passes"

`v2` should only be called "passing" in a strong sense when all of the following are true:

1. Code layer:
   - `pytest -q tests/v2` passes
2. Real-agent layer:
   - at least one installed agent runs `v2` successfully on `B1-code-perf`
3. Smoke layer:
   - `B1-code-perf` smoke passes
   - `B2-cartpole` smoke passes
4. Partial layer:
   - either `B1` or `B2` completes baseline + 3 experiments + restart/resume
5. Contract layer:
   - prompt/runtime state-file naming is unified or explicitly bridged

### 6.3 What Must Happen Before Saying "v2 matches the full design philosophy"

To claim `v2` fully matches its current design philosophy, the bar is stricter:

1. All conditions above are met.
2. Manager, critic, and experiment roles operate on a unified canonical state contract.
3. The benchmark basket is frozen, not ad hoc.
4. At least one real ML repo from `B3` or `B4` passes a partial run.
5. Evidence and claim transitions are inspectable, not only implied.
6. If parallelism is advertised:
   - a real `B5` benchmark passes on a GPU host.

## 7. Immediate Next Validation Work

1. Freeze `B1-code-perf` and `B2-cartpole` as the mandatory current smoke basket.
2. Add a real-agent serial smoke test harness for those two repos.
3. Decide and implement the canonical runtime file contract:
   - either prompts move to `graph.json/log.jsonl/activity.json`
   - or runtime bridges to prompt-facing names
4. Add CLI preflight for missing agent binaries.
5. Promote one real ML repo into an actually admissible `B3` benchmark:
   - preferably pinned `nanoGPT`
6. Only after that, validate parallel mode on a real git-backed benchmark repo.

## 8. Bottom Line

- `open_researcher_v2` is stronger than it was before:
  - the earlier parallel call mismatch is fixed
  - TUI logging is more honest
  - concurrent finalization is safer
- But the acceptance center of gravity is still benchmark reality, not code style.
- Right now, the correct sequence is:
  - freeze the basket
  - prove `B1`
  - prove `B2`
  - unify the state contract
  - then promote one real ML repo
- Until that happens, `v2` should be described as:
  - a repaired and green research-runtime skeleton
  - not yet a benchmark-proven end-to-end research system
