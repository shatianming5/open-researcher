# Open Researcher

> **Let AI agents run experiments in any repo while you sleep.**

Open Researcher is a CLI framework that sets up automated research workflows in any git repository. Point it at your project, pick an AI agent, and let it autonomously understand your code, design evaluation metrics, establish baselines, and run experiments — keeping what works, discarding what doesn't.

Unlike tools locked to specific repo formats, Open Researcher works with **any** project — ML training, performance optimization, algorithm design, or anything with measurable outcomes.

## See It in Action

Try the interactive demo — no agent or API key needed:

```bash
pip install open-researcher
open-researcher demo
```

<!-- TUI Dashboard Screenshot — replace with actual screenshot/GIF -->
```
┌─ Open Researcher ──────────────────────────────────────────────────────┐
│ Experiments: 15 │ Kept: 10 │ Discarded: 3 │ Crashed: 1 │ Best: 0.329 │
├─ Overview ─ Ideas ─ Charts ─ Logs ─ Docs ──────────────────────────────┤
│                                                                        │
│  ▌ Experiment Agent  experimenting                                     │
│  ▌ Running: sliding window attention (idea-003)                        │
│  ▌ ████████████████████░░░░░░░░  62%  (5/8 ideas)                     │
│                                                                        │
│  Recent Experiments:                                                   │
│  #15  final-tune      keep     val_loss=0.329  ↓ Fine-tune LR 1e-5    │
│  #14  kv-cache        keep     val_loss=0.335  ↓ KV-cache optim       │
│  #13  mixup-aug       discard  val_loss=0.355  ↑ MixUp augmentation   │
│  #12  batch-x2        keep     val_loss=0.338  ↓ Double batch size    │
│  #11  flash-attn      keep     val_loss=0.343  ↓ FlashAttention-2     │
│                                                                        │
│  [p]ause [r]esume [s]kip [a]dd idea [g]pu [q]uit                      │
└────────────────────────────────────────────────────────────────────────┘
```

**5 tabs**: Overview (stats + progress) · Ideas (pool management) · Charts (metric trends) · Logs (live agent output with diff coloring) · Docs (project understanding, literature, evaluation)

## Quick Start

### Zero-Config Start (Recommended)

One command does everything — init, analyze your project, confirm the plan, then run experiments:

```bash
cd your-project
open-researcher start
```

This launches a **3-phase flow**:

1. **Scout** — AI agent analyzes your codebase, searches related work, designs evaluation metrics
2. **Review** — You review the analysis in an interactive TUI and confirm or edit the plan
3. **Experiment** — Agent runs experiments autonomously, keeping what improves metrics

### Headless Mode

Run without TUI — perfect for scripts, CI, or monitoring with external tools:

```bash
open-researcher start --headless --goal "reduce val_loss below 0.3" --max-experiments 20
```

Outputs structured **JSON Lines** to stdout, one event per line:

```json
{"ts": "2026-03-10T12:34:56Z", "level": "info", "phase": "scouting", "event": "scout_started"}
{"ts": "2026-03-10T12:45:00Z", "level": "info", "phase": "experimenting", "event": "experiment_completed", "idea": "idea-001", "metric_value": 0.95, "experiment_num": 3, "max_experiments": 20}
{"ts": "2026-03-10T12:50:00Z", "level": "info", "phase": "done", "event": "limit_reached", "detail": "Max experiments (20) reached"}
```

Also writes to `.research/events.jsonl` for persistent logging.

### Manual Step-by-Step

```bash
pip install open-researcher

cd your-project
open-researcher init                      # Initialize .research/ directory
open-researcher run --agent claude-code   # Launch with TUI dashboard
# Go to sleep. Check results in the morning:
open-researcher status --sparkline
open-researcher results --chart primary
```

## How It Works

Open Researcher generates a `.research/` directory in your repo with:

| File | Purpose |
|------|---------|
| `program.md` | Agent instructions — the full research workflow |
| `scout_program.md` | Scout agent instructions — project analysis phase |
| `idea_program.md` | Idea agent instructions — hypothesis generation |
| `experiment_program.md` | Experiment agent instructions — run & evaluate |
| `config.yaml` | Mode, metrics, timeout, experiment limits, agent settings |
| `project-understanding.md` | Agent fills: what the project does |
| `research-strategy.md` | Agent fills: research direction and focus areas |
| `literature.md` | Agent fills: related work and prior art |
| `evaluation.md` | Agent fills: how to measure improvement |
| `idea_pool.json` | Idea queue with priority, status, claims |
| `results.tsv` | Experiment log (timestamp, commit, metrics, status) |
| `control.json` | Runtime control commands (pause/resume/skip) |
| `activity.json` | Real-time agent status for TUI display |

### The Scout → Review → Experiment Flow

```
Phase 0: Bootstrap
  └─ Auto-init .research/ if needed, load config

Phase 1: Goal Input
  └─ Optional research goal (TUI modal or --goal flag)

Phase 2: Scout Analysis
  ├─ Read codebase → project-understanding.md
  ├─ Search related work → literature.md
  ├─ Define strategy → research-strategy.md
  └─ Design evaluation → evaluation.md + config.yaml

Phase 3: Human Review (TUI only, auto-confirmed in headless)
  ├─ Review all Scout outputs
  └─ Confirm, edit, or re-analyze

Phase 4: Experiment Loop
  ├─ Single-Agent: runs full program.md
  └─ Dual-Agent (--multi):
     ├─ Idea Agent: generates 1 hypothesis → idea_pool.json
     └─ Experiment Agent: implements, tests, evaluates → results.tsv
     └─ Repeat until no ideas left or --max-experiments reached
```

Each experiment is a git commit. Successful experiments stay; failed ones are rolled back. Everything is logged in `results.tsv`.

## Safety First

Open Researcher treats your repo with care:

- Every experiment is an **isolated git commit** — nothing is lost
- Failed experiments are **automatically rolled back** via `git reset`
- **Timeout watchdog** kills runaway experiments
- **Crash counter** auto-pauses after N consecutive failures
- **Max experiments** limit stops after a set number of experiments
- **Collaborative mode** pauses for human review between phases
- **Control plane** supports pause / resume / skip via `control.json`
- **Failure memory** tracks past failures to improve fix strategies
- Parallel workers run in **isolated git worktrees** — they can't interfere with each other

## Supported Agents

| Agent | Command | Status |
|-------|---------|--------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `--agent claude-code` | Supported |
| [Codex CLI](https://github.com/openai/codex) | `--agent codex` | Supported |
| [Aider](https://github.com/paul-gauthier/aider) | `--agent aider` | Supported |
| [OpenCode](https://github.com/opencode-ai/opencode) | `--agent opencode` | Supported |

Auto-detection: If you don't specify `--agent`, Open Researcher finds the first installed one.

### Agent Configuration

Customize agent parameters in `.research/config.yaml`:

```yaml
agents:
  claude-code:
    model: "claude-sonnet-4-5-20250514"   # override model
    allowed_tools: "Edit,Write,Bash,Read,Glob,Grep"
    extra_flags: ["--max-turns", "50"]
  codex:
    model: "gpt-5.2"                      # override default
    sandbox: "suggest"                     # full-auto | suggest | ask
  aider:
    model: "gpt-4o"
    extra_flags: ["--no-git"]
```

## Commands

```bash
# Zero-config start (recommended)
open-researcher start                                  # TUI: Scout → Review → Experiment
open-researcher start --multi                          # Dual-agent mode
open-researcher start --headless --goal "..." --max-experiments 10  # Headless JSON Lines mode

# Manual workflow
open-researcher init [--tag NAME]                      # Initialize .research/ directory
open-researcher run [--agent NAME]                     # Launch AI agent with TUI dashboard
open-researcher run --multi                            # Dual-agent mode (idea + experiment)

# Monitoring
open-researcher status [--sparkline]                   # Show experiment progress
open-researcher results [--chart primary] [--json]     # Print results table or chart
open-researcher logs [--follow] [--errors]             # View agent logs

# Management
open-researcher ideas list                             # List idea pool
open-researcher ideas add "description"                # Add idea manually
open-researcher ideas delete IDEA_ID                   # Remove idea
open-researcher ideas prioritize                       # Re-prioritize ideas
open-researcher config show                            # View/validate configuration
open-researcher export                                 # Export markdown report
open-researcher doctor                                 # Health check environment
open-researcher demo                                   # Try the TUI with sample data
```

## Interactive TUI Dashboard

```bash
open-researcher start
# or
open-researcher run --agent claude-code
```

Rich terminal dashboard with 5 tabs:

- **Overview** — Real-time stats, agent status with progress bar, recent results
- **Ideas** — Idea pool with status, priority, category, metric values
- **Charts** — Metric trend visualization with keep/discard/crash coloring
- **Logs** — Live agent output with diff highlighting and thinking/acting phases
- **Docs** — Auto-refreshing views of project understanding, literature, evaluation, ideas

Keyboard shortcuts: `1-5` switch tabs, `p` pause, `r` resume, `s` skip idea, `a` add idea, `g` GPU status, `q` quit.

## Runtime Controls

| Feature | Description |
|---------|-------------|
| **Timeout watchdog** | Kills experiments exceeding the configured time limit |
| **Crash counter** | Auto-pauses after N consecutive crashes (default: 3) |
| **Max experiments** | Stops after N experiments (`--max-experiments` or `config.yaml`) |
| **Control plane** | Linearized pause / resume / skip commands via `control.json` |
| **Failure memory** | Persistent ledger of past failures, ranked by recovery success |
| **Phase gate** | In collaborative mode, pauses between phase transitions |
| **Parallel workers** | Run experiments across multiple GPUs in isolated worktrees |

## Configuration

Edit `.research/config.yaml`:

```yaml
mode: autonomous              # autonomous | collaborative

experiment:
  timeout: 600                # seconds per experiment before kill
  max_consecutive_crashes: 3  # pause after N consecutive crashes
  max_experiments: 0          # 0 = unlimited; set to N to stop after N experiments
  max_parallel_workers: 0     # 0 = auto (one per GPU), 1 = serial
  worker_agent: ""            # agent for sub-workers (default: same as master)

metrics:
  primary:
    name: ""                  # filled by agent (e.g., "val_loss")
    direction: ""             # higher_is_better | lower_is_better

environment: |
  # Describe how to run commands for this project
  # Local: just run commands directly
  # Remote: ssh user@host "cd /path && ..."
  # Docker: docker exec container_name ...

research:
  web_search: true            # let agent use web search if available
  search_interval: 5          # refresh ideas every N experiments

gpu:
  remote_hosts: []            # for multi-agent GPU allocation

agents:                       # per-agent overrides (optional)
  claude-code:
    model: ""
    allowed_tools: "Edit,Write,Bash,Read,Glob,Grep"
```

## Examples

See [`examples/`](examples/) for complete setups:

- **[nanoGPT](examples/nanogpt/)** — Reduce validation loss in character-level language model training
- **[Liger-Kernel](examples/liger-kernel/)** — Optimize Triton GPU kernels
- **[HF GLUE](examples/hf-glue/)** — Improve HuggingFace Transformers fine-tuning

## Platform Support

macOS, Linux, and Windows (Python 3.10+).

## Development

```bash
git clone https://github.com/open-researcher/open-researcher.git
cd open-researcher
make dev    # install with dev dependencies
make test   # run tests
make lint   # run linter
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [CHANGELOG.md](CHANGELOG.md) for version history.

## License

MIT — see [LICENSE](LICENSE).
