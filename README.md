<div align="center">

# 🧑‍🌾 PaperFarm: Planting GPUs & APIs 🌱, Harvesting Papers & SOTAs 🌾

<p>
  <a href="https://pypi.org/project/PaperFarm/"><img alt="PyPI" src="https://img.shields.io/pypi/v/PaperFarm?style=flat-square&logo=pypi&logoColor=white" /></a>
  <a href="https://pepy.tech/projects/PaperFarm"><img alt="Downloads" src="https://img.shields.io/pepy/dt/PaperFarm?style=flat-square&logo=python&logoColor=white" /></a>
  <a href="https://www.python.org/downloads/"><img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" /></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green?style=flat-square" /></a>
  <a href="https://github.com/shatianming5/PaperFarm"><img alt="GitHub stars" src="https://img.shields.io/github/stars/shatianming5/PaperFarm?style=flat-square&logo=github" /></a>
</p>

<h3>🔬 Point it at any repo — sow ideas, run experiments, and harvest better code autonomously</h3>

<p><em>🌱 Sow ideas. 🚜 Run experiments. 🌾 Harvest evidence. 📄</em></p>

[**Quick Start**](#-quick-start) · [**How It Works**](#-how-it-works) · [**Agents**](#-supported-agents) · [**TUI Dashboard**](#-interactive-tui-dashboard) · [**CLI Reference**](#%EF%B8%8F-cli-reference) · [**Examples**](#-examples)

</div>

---

## 🌾 Key Features

- **🚀 One `run` Command**: `paperfarm run .` bootstraps a scout analysis, then enters the research loop — plan, review, experiment, repeat.

- **🤖 Multi-Agent Support**: Works with Claude Code, Codex CLI, Aider, and Gemini CLI — pick your favorite.

- **🔬 Skill-Based Loop**: Scout → Manager → Critic → Experiment — each phase is a markdown "skill" that an agent executes faithfully.

- **🖥️ Research TUI**: Live dashboard with frontier status, metric charts, and structured log viewer. Keyboard controls for pause/resume/skip.

- **🛡️ Safety First**: Every experiment is a git commit. Failed experiments auto-rollback via `rollback.sh`. Results logged to `results.tsv` with FileLock concurrency safety.

- **📡 Headless Mode**: `--headless` for CI, scripts, or remote servers — no TUI needed.

- **⚡ Parallel Workers**: Run experiments across multiple GPUs in isolated git worktrees — workers can't interfere with each other.

---

## 🌱 Quick Start

```bash
pip install PaperFarm

cd your-project
paperfarm run .
```

This launches a research session:

1. **🌱 Scout** — survey the field: analyze your codebase, search related work, design evaluation metrics
2. **🚜 Manager** — plan the crop: propose hypotheses, design experiments, maintain the frontier backlog
3. **🔍 Critic** — inspect the plan: review experiment specs before execution, review evidence after
4. **🌾 Experiment** — plant, test, harvest: implement one change, evaluate, record to `results.tsv`
5. **🔄 Repeat** — until all frontier items are done or `max_rounds` is reached

### Headless Mode

```bash
paperfarm run . --headless \
  --goal "Reduce val_loss below 0.3" \
  --agent-name codex
```

### Parallel Workers

```bash
paperfarm run . --headless --workers 4 --agent-name codex
```

---

## 🚜 How It Works

PaperFarm creates a `.research/` directory in your repo with everything needed for autonomous research.

<details>
<summary><b>📂 .research/ Directory Structure</b></summary>
<br/>

| File | Purpose |
|:---|:---|
| `config.yaml` | Research configuration (metrics, limits, agent settings) |
| `graph.json` | Hypothesis → experiment spec → frontier → evidence graph |
| `results.tsv` | Experiment results ledger (timestamp, frontier_id, status, metric, value) |
| `activity.json` | Live phase/worker status for TUI polling |
| `log.jsonl` | Append-only structured event log |
| `evaluation.md` | How to measure the primary metric (written by scout) |
| `project-understanding.md` | Project analysis (written by scout) |
| `research-strategy.md` | Research direction and focus areas (written by scout) |
| `literature.md` | Related work and prior art (written by scout) |
| `scripts/record.py` | Helper script agents call to append results (FileLock-safe) |
| `scripts/rollback.sh` | Helper script to revert failed experiments |

</details>

<details>
<summary><b>🔄 The Research Loop</b></summary>
<br/>

```
Bootstrap
  └─ Scout — analyze codebase, define strategy and evaluation

Research Loop (repeats until done)
  ├─ Manager  — propose hypotheses, design experiments, maintain frontier
  ├─ Critic   — preflight review: approve or reject experiment specs
  ├─ Experiment — claim frontier item, implement change, evaluate, record
  └─ Critic   — post-run review: assess evidence, update claims
```

Each phase is a markdown skill template (`skills/*.md`) loaded by `SkillRunner`, variable-substituted with `[GOAL]` and `[TAG]`, then passed to the agent as a prompt. The agent reads/writes `.research/` state files directly.

</details>

<details>
<summary><b>🧰 Skill Templates</b></summary>
<br/>

| Skill | Role | What It Does |
|:---|:---|:---|
| `scout.md` | Bootstrap | Analyze project, search related work, define strategy and evaluation |
| `manager.md` | Planning | Propose hypotheses, design experiment specs, populate frontier |
| `critic.md` | Review | Pre-approve experiments (preflight), post-review evidence (post-run) |
| `experiment.md` | Execution | Claim frontier item, implement, evaluate, record via `record.py` |

Skills reference these `.research/` files directly. The experiment agent calls `python .research/scripts/record.py --frontier-id F-1 --status keep --value 0.87` to record results, and `bash .research/scripts/rollback.sh` to revert failed changes.

</details>

---

## 🛡️ Field Safety

| Feature | Description |
|:---|:---|
| **Isolated git commits** | Every experiment is a separate commit — nothing is lost |
| **Auto-rollback** | Failed experiments are reverted via `rollback.sh` |
| **FileLock results** | `record.py` uses FileLock for concurrent-safe writes to `results.tsv` |
| **Max rounds** | Stops after N rounds (`config.yaml: limits.max_rounds`) |
| **Pause / Resume / Skip** | TUI keyboard controls or `activity.json` control flags |
| **Parallel isolation** | Workers run in separate git worktrees — no interference |

---

## 🤖 Supported Agents

| Agent | Flag | How It's Invoked |
|:---|:---|:---|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `--agent-name claude-code` | `claude -p <prompt> --verbose` |
| [Codex CLI](https://github.com/openai/codex) | `--agent-name codex` | `codex exec --full-auto <prompt>` |
| [Aider](https://github.com/paul-gauthier/aider) | `--agent-name aider` | `aider --yes-always --no-git --message-file <file>` |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `--agent-name gemini` | `gemini -p <prompt>` |

Default is `claude-code`. All agents receive the same skill prompt and work against the same `.research/` state files.

---

## 📊 Interactive TUI Dashboard

Launch with TUI (default, no `--headless`):

```bash
paperfarm run . --agent-name claude-code
```

<p align="center">
  <img src="imgs/overview.png" alt="PaperFarm overview dashboard" width="100%" />
</p>

```
┌──────────────────────── PaperFarm ────────────────────────┐
│ Phase: experiment | Round: 3 | Hyps: 5 | Exps: 4/7 | Best: 1.92 │
│ scout  ‣  manager  ‣  critic  ‣  EXPERIMENT               │
├──[Execution]──[Metrics]──[Logs]────────────────────────────┤
│                                                             │
│  Frontier Panel              │  Worker Panel                │
│  frontier-001  keep   2.62   │  (idle)                      │
│  frontier-002  keep   2.40   │                              │
│  frontier-003  keep   2.31   │                              │
│  frontier-006  keep   1.92   │                              │
│                              │                              │
├─────────────────────────────────────────────────────────────┤
│ p Pause   r Resume   s Skip   q Quit             ^p palette│
└─────────────────────────────────────────────────────────────┘
```

<details>
<summary><b>📑 3 Tabs & Keyboard Shortcuts</b></summary>
<br/>

**3 tabs**:

- **Execution** — Frontier items with status/priority, worker activity panel
- **Metrics** — Experiment results chart over time
- **Logs** — Structured event log from `log.jsonl`

**Keyboard shortcuts**: `p` pause, `r` resume, `s` skip current experiment, `q` quit.

Polls `.research/` state files every second — attach to a running session anytime to monitor progress.

</details>

---

## 🚜 Installation

Python 3.10+ required. Supports **Linux**, **macOS**, and **Windows**.

### pip install (recommended)

```bash
pip install PaperFarm

cd your-project
paperfarm run .
```

### From source (for development)

```bash
git clone https://github.com/shatianming5/PaperFarm.git
cd PaperFarm
pip install -e ".[dev]"
pytest
```

---

## 🖥️ CLI Reference

```
paperfarm run REPO [OPTIONS]    Launch or resume a research session
paperfarm status REPO           Show current research state
paperfarm results REPO          Display experiment results table
```

### `run` Options

| Option | Default | Description |
|:---|:---|:---|
| `--goal TEXT` | `""` | Research goal (injected into skill templates as `[GOAL]`) |
| `--tag TEXT` | auto | Session tag (injected as `[TAG]`) |
| `--workers N` | `0` | Parallel workers (0 = serial) |
| `--headless` | off | Run without TUI |
| `--agent-name TEXT` | `claude-code` | Which agent CLI to use |

---

## ⚙️ Configuration

The scout agent fills `.research/config.yaml` during bootstrap. You can also edit it manually:

```yaml
protocol: research-v1

metrics:
  primary:
    name: val_loss           # or test_accuracy, ops_per_sec, etc.
    direction: minimize      # minimize | maximize

limits:
  max_rounds: 20             # max research loop iterations
  timeout_minutes: 0         # 0 = no timeout

workers:
  max: 0                     # 0 = serial
  gpu_mem_per_worker_mb: 8192

agent:
  name: claude-code
  config: {}                 # passed to agent adapter
```

---

## 🏡 Project Structure

```
src/paperfarm/
├── cli.py              # Typer CLI (run / status / results)
├── agent.py            # Agent adapters (ClaudeCode, Codex, Aider, Gemini)
├── skill_runner.py     # Loads skills, substitutes [GOAL]/[TAG], drives the loop
├── state.py            # .research/ state file access layer
├── parallel.py         # WorkerPool for multi-GPU parallel experiments
├── skills/
│   ├── protocol.yaml   # Bootstrap + loop step order
│   ├── scout.md        # 🌱 Scout skill template
│   ├── manager.md      # 🚜 Manager skill template
│   ├── critic.md       # 🔍 Critic skill template
│   ├── experiment.md   # 🌾 Experiment skill template
│   └── scripts/
│       ├── record.py   # CLI tool for recording results (FileLock-safe)
│       └── rollback.sh # Revert failed experiments
└── tui/
    ├── app.py          # Textual TUI app (polling-based)
    ├── widgets.py      # StatsBar, PhaseStrip, FrontierPanel, etc.
    └── styles.css      # TUI styling
```

---

## 🌽 Examples

See [`examples/`](examples/) for ready-to-run setups:

| Example | Task | Metric | Result |
|:---|:---|:---|:---|
| [🎮 CartPole RL](examples/cartpole/) | Maximize DQN reward on CartPole-v1 | avg_reward | 266.7 |
| [⚡ Code Perf](examples/code-perf/) | Optimize JSON parser throughput | ops/sec | 45K → 545K |
| [🧠 nanoGPT](examples/nanogpt/) | Reduce Shakespeare char-level val_loss | val_loss | 2.62 → 1.92 (-27%) |
| [🖼️ CIFAR-10](examples/cifar10-speedrun/) | Maximize CIFAR-10 test accuracy | test_accuracy | 67.7% (WIP) |
| [📦 YOLO Tiny](examples/yolo-tiny/) | Maximize YOLOv8 mAP50 on COCO8 | mAP50 | 0.875 |
| [📝 HF GLUE](examples/hf-glue/) | Optimize SST-2 fine-tuning | eval_accuracy | (needs GPU) |
| [🎙️ Whisper](examples/whisper-finetune/) | Reduce Whisper word error rate | WER | (needs GPU) |
| [🔥 Liger-Kernel](examples/liger-kernel/) | Optimize Triton GPU kernels | throughput | (needs GPU) |

### Running an Example

```bash
cd examples/cartpole
paperfarm run . --agent-name codex --headless \
  --goal "Maximize CartPole-v1 average reward to 500"
```

---

## 🧑‍🌾 Contributing

Contributions are welcome! Please:

1. Open an [issue](https://github.com/shatianming5/PaperFarm/issues) to discuss the proposed change
2. Fork the repository and create your feature branch
3. Submit a pull request with a clear description

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

## Star History

[![Star History Chart](https://api.star-history.com/image?repos=shatianming5/PaperFarm&type=date&legend=top-left)](https://www.star-history.com/?repos=shatianming5%2FPaperFarm&type=date&legend=top-left)
