<div align="center">

# Open Researcher: Let AI Agents Run Experiments While You Sleep

<p>
  <a href="https://pypi.org/project/open-researcher/"><img alt="PyPI" src="https://img.shields.io/pypi/v/open-researcher?style=flat-square&logo=pypi&logoColor=white" /></a>
  <a href="https://pepy.tech/projects/open-researcher"><img alt="Downloads" src="https://img.shields.io/pepy/dt/open-researcher?style=flat-square&logo=python&logoColor=white" /></a>
  <a href="https://www.python.org/downloads/"><img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" /></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green?style=flat-square" /></a>
  <a href="https://github.com/open-researcher/open-researcher"><img alt="GitHub stars" src="https://img.shields.io/github/stars/open-researcher/open-researcher?style=flat-square&logo=github" /></a>
</p>

<h3>🔬 Point it at any repo — it scouts, experiments, and improves your code autonomously</h3>

[**Quick Start**](#-quick-start) · [**How It Works**](#-how-it-works) · [**Agents**](#-supported-agents) · [**TUI Dashboard**](#-interactive-tui-dashboard) · [**CLI Reference**](#%EF%B8%8F-cli-reference) · [**Configuration**](#%EF%B8%8F-configuration) · [**Examples**](#-examples)

</div>

---

## ✨ Key Features

- **🚀 Zero-Config Start**: One command (`open-researcher start`) does everything — init, analyze your project, confirm the plan, then run experiments autonomously.

- **🤖 Multi-Agent Support**: Works with Claude Code, Codex CLI, Aider, and OpenCode — auto-detects the first installed agent, or pick your own.

- **🔬 Scout → Review → Experiment Flow**: AI agent analyzes your codebase, searches related work, designs evaluation metrics, then runs experiments — keeping what works, discarding what doesn't.

- **📊 Rich 5-Tab TUI Dashboard**: Real-time stats, idea pool, metric trend charts, live agent logs with diff coloring, and auto-refreshing docs — all in your terminal.

- **🛡️ Safety First**: Every experiment is an isolated git commit. Failed experiments auto-rollback. Timeout watchdog, crash counter, and max-experiments limit keep things under control.

- **🔄 Dual-Agent Mode**: Separate Idea Agent (generates hypotheses) and Experiment Agent (implements & evaluates) for structured research workflows.

- **📡 Headless Mode**: Run without TUI — outputs structured JSON Lines to stdout, perfect for scripts, CI, or monitoring with external tools.

- **⚡ Parallel Workers**: Run experiments across multiple GPUs in isolated git worktrees — workers can't interfere with each other.

---

## 🚀 Quick Start

### Zero-Config Start (Recommended)

```bash
pip install open-researcher

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

> Try the interactive demo — no agent or API key needed: `open-researcher demo`

---

## 🔬 How It Works

Open Researcher generates a `.research/` directory in your repo with everything needed for autonomous research.

<details>
<summary><b>📂 .research/ Directory Structure</b></summary>
<br/>

| File | Purpose |
|:---|:---|
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

</details>

<details>
<summary><b>🔄 The Scout → Review → Experiment Flow</b></summary>
<br/>

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

</details>

---

## 🛡️ Safety & Runtime Controls

| Feature | Description |
|:---|:---|
| **Isolated git commits** | Every experiment is a separate commit — nothing is lost |
| **Auto-rollback** | Failed experiments are automatically rolled back via `git reset` |
| **Timeout watchdog** | Kills experiments exceeding the configured time limit |
| **Crash counter** | Auto-pauses after N consecutive crashes (default: 3) |
| **Max experiments** | Stops after N experiments (`--max-experiments` or `config.yaml`) |
| **Control plane** | Linearized pause / resume / skip commands via `control.json` |
| **Failure memory** | Persistent ledger of past failures, ranked by recovery success |
| **Phase gate** | In collaborative mode, pauses between phase transitions |
| **Parallel workers** | Run experiments across multiple GPUs in isolated worktrees |

---

## 🤖 Supported Agents

| Agent | Command | Status |
|:---|:---|:---|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `--agent claude-code` | Supported |
| [Codex CLI](https://github.com/openai/codex) | `--agent codex` | Supported |
| [Aider](https://github.com/paul-gauthier/aider) | `--agent aider` | Supported |
| [OpenCode](https://github.com/opencode-ai/opencode) | `--agent opencode` | Supported |

Auto-detection: If you don't specify `--agent`, Open Researcher finds the first installed one.

<details>
<summary><b>⚙️ Agent Configuration</b></summary>
<br/>

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

</details>

---

## 📊 Interactive TUI Dashboard

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

<details>
<summary><b>📑 5 Tabs & Keyboard Shortcuts</b></summary>
<br/>

**5 tabs**:

- **Overview** — Real-time stats, agent status with progress bar, recent results
- **Ideas** — Idea pool with status, priority, category, metric values
- **Charts** — Metric trend visualization with keep/discard/crash coloring
- **Logs** — Live agent output with diff highlighting and thinking/acting phases
- **Docs** — Auto-refreshing views of project understanding, literature, evaluation, ideas

**Keyboard shortcuts**: `1-5` switch tabs, `p` pause, `r` resume, `s` skip idea, `a` add idea, `g` GPU status, `q` quit.

</details>

---

## 📦 Installation

Open Researcher supports **Linux**, **macOS**, and **Windows**. Python 3.10+ required.

### Option A: pip install (recommended)

```bash
pip install open-researcher

# Try the demo first (no agent or API key needed)
open-researcher demo

# Then use it for real
cd your-project
open-researcher start
```

### Option B: From source (for development)

<details>
<summary><b>🐧 Linux / 🍎 macOS / 💻 Windows</b></summary>
<br/>

```bash
git clone https://github.com/open-researcher/open-researcher.git
cd open-researcher
make dev    # install with dev dependencies
make test   # run tests
make lint   # run linter
```

</details>

---

## 🖥️ CLI Reference

> All commands: `open-researcher <command>`

<details>
<summary>⚡ <b>Core Commands</b></summary>
<br/>

| Command | What It Does |
|:---|:---|
| `start` | Zero-config: Scout → Review → Experiment (TUI) |
| `start --multi` | Dual-agent mode (idea + experiment agents) |
| `start --headless --goal "..." --max-experiments N` | Headless JSON Lines mode |
| `init [--tag NAME]` | Initialize `.research/` directory |
| `run [--agent NAME]` | Launch AI agent with TUI dashboard |
| `run --multi` | Dual-agent mode (idea + experiment) |
| `demo` | Try the TUI with sample data (no agent needed) |

</details>

<details>
<summary>📈 <b>Monitoring & Results</b></summary>
<br/>

| Command | What It Does |
|:---|:---|
| `status [--sparkline]` | Show experiment progress |
| `results [--chart primary] [--json]` | Print results table or chart |
| `logs [--follow] [--errors]` | View agent logs |
| `export` | Export markdown report |

</details>

<details>
<summary>💡 <b>Idea Management</b></summary>
<br/>

| Command | What It Does |
|:---|:---|
| `ideas list` | List idea pool |
| `ideas add "description"` | Add idea manually |
| `ideas delete IDEA_ID` | Remove idea |
| `ideas prioritize` | Re-prioritize ideas |

</details>

<details>
<summary>🔧 <b>Utilities & Diagnostics</b></summary>
<br/>

| Command | What It Does |
|:---|:---|
| `config show` | View/validate configuration |
| `doctor` | Health check environment |

</details>

---

## ⚙️ Configuration

Edit `.research/config.yaml`:

<details>
<summary>🎛️ <b>Full Configuration Reference</b></summary>
<br/>

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

</details>

---

## 📁 Project Structure

<details>
<summary>🎯 <b>Core System</b></summary>
<br/>

| Module | Description |
|:---|:---|
| `cli.py` | CLI entry point, all commands (Typer) |
| `start_cmd.py` | Zero-config start flow (Scout → Review → Experiment) |
| `run_cmd.py` | Agent launch & TUI integration |
| `headless.py` | Headless mode (JSON Lines output) |
| `init_cmd.py` | Initialize `.research/` directory |
| `config.py` | Configuration parsing |

</details>

<details>
<summary>🤖 <b>Agent Adapters (<code>agents/</code>)</b></summary>
<br/>

| Module | Description |
|:---|:---|
| `base.py` | AgentAdapter abstract base class |
| `claude_code.py` | Claude Code adapter |
| `codex.py` | Codex CLI adapter |
| `aider.py` | Aider adapter |
| `opencode.py` | OpenCode adapter |

</details>

<details>
<summary>📊 <b>TUI Components (<code>tui/</code>)</b></summary>
<br/>

| Module | Description |
|:---|:---|
| `app.py` | Main Textual application, 5-tab layout |
| `widgets.py` | UI components (Stats, Ideas, Charts, Logs, Docs) |
| `review.py` | Post-Scout review TUI |
| `modals.py` | Modal dialogs (AddIdea, GPUStatus, Log) |
| `styles.css` | CSS styling |

</details>

<details>
<summary>⚙️ <b>Runtime Engine</b></summary>
<br/>

| Module | Description |
|:---|:---|
| `idea_pool.py` | Idea pool management (atomic reads/writes, file locking) |
| `control_plane.py` | Runtime control (pause/resume/skip) |
| `failure_memory.py` | Failure memory ledger (categorize, improve fixes) |
| `worker.py` | Parallel worker management (multi-GPU) |
| `worktree.py` | Git worktree management (worker isolation) |
| `gpu_manager.py` | GPU allocation (local/remote) |
| `watchdog.py` | Timeout watchdog (kill runaway experiments) |
| `crash_counter.py` | Crash counter (auto-pause after N failures) |
| `phase_gate.py` | Phase gate (collaborative mode confirmation) |
| `activity.py` | Activity monitor (real-time agent status) |

</details>

---

## 📚 Examples

See [`examples/`](examples/) for complete setups:

- **[nanoGPT](examples/nanogpt/)** — Reduce validation loss in character-level language model training
- **[Liger-Kernel](examples/liger-kernel/)** — Optimize Triton GPU kernels
- **[HF GLUE](examples/hf-glue/)** — Improve HuggingFace Transformers fine-tuning

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Open an [issue](https://github.com/open-researcher/open-researcher/issues) to discuss the proposed change
2. Fork the repository and create your feature branch
3. Submit a pull request with a clear description

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [CHANGELOG.md](CHANGELOG.md) for version history.

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

<p align="center">
  <a href="https://star-history.com/#open-researcher/open-researcher&Date">
    <img src="https://api.star-history.com/svg?repos=open-researcher/open-researcher&type=Date" width="600" alt="Star History" />
  </a>
</p>
