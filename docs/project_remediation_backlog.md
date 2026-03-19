# Project Remediation Backlog

## Goal

Turn the current repository from "mostly working, partially migrated, not yet fully proven" into a state that is:

- green at the code/test layer
- honest at the docs/CLI contract layer
- proven on smoke + partial + full benchmark layers
- simpler on the default path
- safe to continue migrating away from compatibility shims

## Prioritization Rules

- `P0`: must complete before calling the repo "green" or broadly recommending it.
- `P1`: should complete before making strong product claims about real-project usability and medium-cost benchmark reliability.
- `P2`: deletion / architecture closure / scale-up work after P0-P1 are proven.

## Non-Goals Until After P1

- web dashboard
- flashy TUI polish beyond core readability
- new benchmark categories beyond the minimum release basket
- deeper plugin marketing before the plugin path is actually the shipping path

## P0

| ID | Goal | Why now | Affected phases | Acceptance | Simplify / remove effect | Depends on |
|---|---|---|---|---|---|---|
| `P0-01` | Restore fully green local quality baseline | Current `pytest -q` still fails on TUI icon contract, so the repo is not actually green | Phase 8 runtime control, TUI surface | `ruff check src tests` passes; `pytest -q` passes; decide and document ASCII-vs-Unicode TUI contract; tests match implementation | Prevents false confidence; may simplify TUI rendering expectations | None |
| `P0-02` | Freeze public CLI/documentation contract around `run` | Public entry is `run`, but examples still advertise hidden `start` alias | Phase 0 kickoff, docs/examples | README/examples/public docs use `run`; hidden `start` is marked deprecated only; no public example depends on it | Makes `start` removable later | `P0-01` not required |
| `P0-03` | Add a real benchmark smoke gate | Current audit proved CLI/help/doctor, but not one true end-to-end benchmark run | Phase 1-7 full pipeline | At least `code-perf` and `cartpole` each complete one smoke run end-to-end; `.research/` artifacts are coherent; one valid metric row is recorded; rerun does not corrupt state | Establishes a truthful baseline and may reveal removable complexity that does not help smoke success | `P0-01`, `P0-02` |
| `P0-04` | Tighten bootstrap readiness contract | Current dry run can still report "ready" with unresolved data path; prepare must mean truly runnable | Phase 2 prepare | Define explicit prepare-ready semantics; unresolved install/data/smoke gaps are surfaced deterministically; `doctor` and runtime agree; smoke success vs expected paths precedence is documented and tested | May simplify bootstrap decision logic by removing ambiguous "probably ready" states | `P0-03` helpful |
| `P0-05` | Close core state-consistency risks on the file-backed runtime | Current shipping path still depends on mutable JSON/TSV coordination and is where trust can be lost fastest | Phase 2 prepare, Phase 6 experiment, Phase 8 control | Critical file updates for idea/activity/control/results/GPU state use safe atomic/locked patterns; concurrent read/write corruption tests exist for the shipping path; no silent partial-state regressions in smoke runs | Reduces need for defensive UI workarounds and shrinks future migration risk | `P0-01` |
| `P0-06` | Add a release gate command/path that reflects reality | Need one authoritative "can this repo ship?" path, not scattered commands | All phases | One documented local gate runs lint + tests + CLI smoke + benchmark smoke + doctor; result is easy to report in CI and in releases | Simplifies release decisions; avoids overreading README/demo success | `P0-01` to `P0-05` |
| `P0-07` | Define the minimum release benchmark basket | Benchmark choice is core to product credibility, so it cannot stay ad hoc | All experimental phases | Release basket is fixed and documented: `code-perf`, `cartpole`, one of `nanogpt/cifar10-speedrun`, one of `hf-glue/yolo-tiny`; each has smoke acceptance | Prevents benchmark sprawl and lets low-value examples stay out of the release gate | `P0-03` |

Status update on 2026-03-18: `P0-01` is complete.
- Evidence: `ruff check src tests` passed, `pytest -q` passed (`767 passed`), and the TUI icon contract is now documented and covered by dedicated ASCII/Unicode tests.

Status update on 2026-03-18: `P0-02` is complete.
- Evidence: public README/examples/demo asset now use `run`; `start` emits a deprecation notice; `pytest -q tests/test_cli.py` passed (`29 passed`); `ruff check src tests` passed.

Status update on 2026-03-18: `P0-03` is complete.
- Evidence:
  - Added `python3 -m open_researcher.benchmark_smoke` as a deterministic lightweight benchmark smoke runner for release-gate examples.
  - `ensure_graph_protocol_artifacts()` now backfills and refreshes generated `.research/` runtime scaffold files, including `.research/scripts/record.py`, so existing example repos do not keep stale helper scripts.
  - `pytest -q tests/test_graph_protocol.py tests/test_record.py tests/test_benchmark_smoke.py` passed (`9 passed`).
  - `python3 -m open_researcher.benchmark_smoke examples/code-perf --desc 'benchmark smoke baseline'` passed and recorded a valid metric row in `examples/code-perf/.research/results.tsv`.
  - `python3 -m open_researcher.benchmark_smoke examples/cartpole --desc 'benchmark smoke baseline'` passed and recorded a valid metric row in `examples/cartpole/.research/results.tsv`.
  - `python3 -m open_researcher.benchmark_smoke examples/code-perf --desc 'benchmark smoke rerun'` appended a second valid row and updated `examples/code-perf/.research/final_results.tsv` without corrupting state.

### P0 Exit Criteria

- repo is code-green
- public docs no longer rely on hidden/legacy entrypoints
- at least 2 lightweight real smoke benchmarks pass
- prepare/readiness semantics are explicit
- one repeatable release gate exists

## P1

| ID | Goal | Why now | Affected phases | Acceptance | Simplify / remove effect | Depends on |
|---|---|---|---|---|---|---|
| `P1-01` | Prove a partial-run benchmark gate | Smoke alone does not prove loop stability, restart behavior, or result credibility | Phase 4 manager, Phase 5 critic preflight, Phase 6 experiment, Phase 7 critic post-review, Phase 8 control | At least one training-style benchmark (`nanogpt` or `cifar10-speedrun`) completes baseline + 3 experiments + restart/resume cleanly; evidence/claim/result states remain coherent | Helps identify which advanced controls are actually necessary on the default path | `P0` complete |
| `P1-02` | Make phase contracts executable and testable, not only prompt-defined | Agent phase tasks are documented, but runtime acceptance is still only partially enforced by code | Phase 1-8 | For each phase, define required output artifacts/state transitions and add validation tests or doctor checks; prompt/template expectations and runtime checks align | Lets future prompt simplification happen safely; may remove redundant prompt text | `P0-04`, `P1-01` |
| `P1-03` | Standardize experiment evidence/artifact outputs | Current evidence exists, but full artifact discipline is not yet release-grade | Phase 6 experiment, Phase 7 critic post-review | Every experiment produces consistent metric/eval/result evidence; report/export can point to concrete artifacts; secondary metrics are preserved coherently | May simplify critic logic by reducing guesswork from logs/results | `P1-01` |
| `P1-04` | Simplify the default TUI to the minimum operator-trust surface | TUI is valuable, but the monolith and excess/legacy affordances raise maintenance cost | Phase 3 review, Phase 8 runtime control | Keep `Command/Execution/Logs/Docs`; ensure each tab has a clear minimal reason to exist; split `widgets.py` by responsibility enough to stop drift; remove or defer low-value decorative behavior | Simplifies TUI maintenance; can remove stale/duplicated widgets later | `P0-01`, `P1-02` |
| `P1-05` | Validate advanced runtime on a real GPU host | Product promises include workers/GPU behavior, but current machine cannot verify them | Phase 2 prepare, Phase 6 experiment, Phase 8 control | On a GPU machine, `doctor` reports valid driver/devices; at least one GPU benchmark smoke or partial run passes; worktree isolation and GPU assignment are observed to be correct | Clarifies what remains optional vs required in advanced mode | `P0`, preferably `P1-01` |
| `P1-06` | Migrate internal imports away from top-level compatibility shims | Compatibility files are still used by shipping code, so deletion is currently unsafe | All phases, architecture layer | Shipping modules import plugin/kernel locations directly where intended; remaining shims are tracked explicitly; no behavior change | Makes later deletion possible and shrinks the "two codebases in one repo" problem | `P0` complete |
| `P1-07` | Add a benchmark runner matrix for smoke + partial | Benchmark coverage needs to become repeatable, not memory-based | All experimental phases | One documented command or script runs the release basket in smoke/partial modes and records pass/fail with artifact links | Simplifies future regression detection and reduces manual validation load | `P0-07`, `P1-01` |

### P1 Exit Criteria

- at least one medium-cost benchmark passes a partial run
- phase acceptance is enforced by code/tests, not only prompts
- artifact/evidence outputs are standardized enough for export and review
- internal import migration is underway with a clear deletion path
- advanced GPU/runtime path has at least one real validation

## P2

| ID | Goal | Why now | Affected phases | Acceptance | Simplify / remove effect | Depends on |
|---|---|---|---|---|---|---|
| `P2-01` | Remove hidden `start` alias and stale start-era assets | After docs/examples stop depending on it, the alias becomes pure drag | Phase 0 kickoff, docs/examples | No public docs/examples/scripts rely on `start`; deprecation window is over; alias removed cleanly | Deletes one legacy public surface | `P0-02` complete |
| `P2-02` | Delete top-level compatibility re-export modules | These are useful today, but they should not survive once internal migration is done | Architecture layer across all phases | `bootstrap.py`, `research_loop.py`, `research_graph.py`, `parallel_runtime.py`, `gpu_manager.py`, `worktree.py`, `storage.py`, `research_events.py` are either removed or reduced to truly external-API shims with no internal dependency | Removes duplicated architecture and reduces cognitive load | `P1-06` complete |
| `P2-03` | Choose one shipping architecture path: plugin/kernel or file-backed legacy | Repo currently carries both a target architecture and a still-shipping compatibility runtime | All phases | Decide whether plugin/kernel becomes the primary runtime path or is demoted to a long-term experiment; docs, tests, and product claims align with that decision | Removes structural ambiguity | `P1` complete |
| `P2-04` | Close the benchmark maturity ladder | After smoke and partial are proven, finish the "full real run" proof layer | All experimental phases | At least two release-basket benchmarks pass full runs; one heavy/system benchmark validates long-run behavior if such claims remain in scope | Allows strong product claims about real-project and scale behavior | `P1-07`, `P1-05` |
| `P2-05` | Archive or delete low-value residual complexity | Some surfaces should remain optional, not immortal | TUI/docs/ops surfaces | Explicitly archive or remove stale design assets, stale demos, redundant docs, and low-value UI affordances that survived P0-P1 | Keeps future maintenance cost under control | `P2-03` helpful |

### P2 Exit Criteria

- legacy public entrypoints are removed
- internal compatibility shims are gone or minimized
- one architecture path is clearly the shipping path
- full-run benchmark claims are backed by evidence

## Suggested Execution Order

1. `P0-01` green baseline
2. `P0-02` CLI/docs contract freeze
3. `P0-03` lightweight benchmark smoke proof
4. `P0-04` bootstrap readiness tightening
5. `P0-05` file-backed runtime consistency fixes
6. `P0-06` release gate
7. `P0-07` benchmark basket freeze
8. `P1-01` training partial-run proof
9. `P1-02` executable phase contracts
10. `P1-03` artifact/evidence standardization
11. `P1-04` TUI simplification
12. `P1-05` GPU/advanced runtime proof
13. `P1-06` internal import migration
14. `P1-07` benchmark matrix runner
15. `P2-01` to `P2-05` architecture closure and deletion work

## Immediate Next 5 Tasks

If work starts now, the highest-value concrete sequence is:

1. Fix the TUI icon/test contract and get `pytest -q` green.
2. Update examples and public docs from `start` to `run`.
3. Run and document true smoke passes for `code-perf` and `cartpole`.
4. Tighten prepare/readiness semantics so "ready" always means experimentally runnable.
5. Add one canonical local release gate command that bundles lint, tests, doctor, and smoke benchmarks.
