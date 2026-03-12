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

[**Quick Start**](#-quick-start) · [**How It Works**](#-how-it-works) · [**Agents**](#-supported-agents) · [**TUI Dashboard**](#-interactive-tui-dashboard) · [**CLI Reference**](#%EF%B8%8F-cli-reference) · [**Configuration**](#%EF%B8%8F-configuration) · [**Examples**](#-examples)

</div>

---

## 🌾 Key Features

- **🚀 One `run` Command**: `PaperFarm run` bootstraps a new workflow when `.research/` is missing, or resumes an existing workflow when it already exists.

- **🤖 Multi-Agent Support**: Works with Claude Code, Codex CLI, Aider, OpenCode, Kimi CLI, and Gemini CLI — auto-detects the first installed agent, or pick your own.

- **🔬 Scout → Prepare → Review → Experiment Flow**: AI agent analyzes your codebase, resolves install/data/smoke bootstrap steps, then runs the `research-v1` loop — keeping what works, discarding what doesn't.

- **🖥️ Research Command Center TUI**: A 4-tab `Command / Execution / Logs / Docs` dashboard with frontier focus, collapsible detail drawer, hypothesis lineage, trace-aware logs, and searchable docs navigation.

- **🛡️ Safety First**: Every experiment is an isolated git commit. Failed experiments auto-rollback. Timeout watchdog, crash counter, and max-experiments limit keep things under control.

- **🧭 Research-v1 Runtime**: A single `Scout -> Manager -> Critic -> Experiment` loop keeps research state explicit and reviewable.

- **📡 Headless Mode**: Run without TUI — outputs structured JSON Lines to stdout, perfect for scripts, CI, or monitoring with external tools.

- **⚡ Parallel Workers**: Run experiments across multiple GPUs in isolated git worktrees — workers can't interfere with each other.

---

## 🌱 Quick Start

### One-Command Workflow (Recommended)

```bash
pip install PaperFarm

cd your-project
PaperFarm run
```

This launches a **4-phase flow**:

Plant the first seed with `PaperFarm run`, then let the field work:

1. **Scout** — survey the field: analyze your codebase, search related work, and design evaluation metrics
2. **Prepare** — prepare the soil: resolve a local Python env, install command, data/setup step, and a readiness smoke check
3. **Review** — inspect the crop plan: review the analysis and prepare results in an interactive TUI, then confirm or edit the plan
4. **Experiment** — plant, test, and harvest: `Manager -> Critic -> Experiment` runs the research loop autonomously, keeping what improves metrics

If you want to inspect exactly what `run` will use before it touches the repo, use:

```bash
PaperFarm run --dry-run
PaperFarm doctor
```

### Headless Mode

Run without TUI — perfect for scripts, CI, or monitoring with external tools:

```bash
PaperFarm run --mode headless --goal "reduce val_loss below 0.3" --max-experiments 20
```

Outputs structured **JSON Lines** to stdout, one event per line:

```json
{"ts": "2026-03-10T12:34:56Z", "level": "info", "phase": "scouting", "event": "scout_started"}
{"ts": "2026-03-10T12:40:00Z", "level": "info", "phase": "preparing", "event": "prepare_step_completed", "step": "smoke", "status": "completed"}
{"ts": "2026-03-10T12:45:00Z", "level": "info", "phase": "experimenting", "event": "experiment_completed", "idea": "idea-001", "metric_value": 0.95, "experiment_num": 3, "max_experiments": 20}
{"ts": "2026-03-10T12:50:00Z", "level": "info", "phase": "done", "event": "limit_reached", "detail": "Max experiments (20) reached"}
```

Also writes to `.research/events.jsonl` for persistent logging. Interactive mode now writes the same canonical event stream, so TUI and headless share one runtime log.

### Manual Step-by-Step

```bash
pip install PaperFarm

cd your-project
PaperFarm init                      # Initialize .research/ directory
PaperFarm run --agent claude-code   # Launch with TUI dashboard
# Go to sleep. Check results in the morning:
PaperFarm status --sparkline
PaperFarm results --chart primary
```

> Try the interactive demo — no agent or API key needed:
> ```bash
> PaperFarm demo              # run in terminal
> PaperFarm demo --serve      # open in browser at http://localhost:8000
> PaperFarm demo --serve --port 9000
> ```

---

## 🚜 How It Works

Open Researcher generates a `.research/` directory in your repo with everything needed for autonomous research.

<details>
<summary><b>📂 .research/ Directory Structure</b></summary>
<br/>

| File | Purpose |
|:---|:---|
| `scout_program.md` | Scout agent instructions — project analysis phase |
| `.internal/role_programs/*.md` | Internal runtime role prompts (manager / critic / experiment), auto-managed |
| `config.yaml` | Mode, metrics, timeout, experiment limits, agent settings, and `bootstrap.*` overrides |
| `project-understanding.md` | Agent fills: what the project does |
| `research-strategy.md` | Agent fills: research direction and focus areas |
| `literature.md` | Agent fills: related work and prior art |
| `evaluation.md` | Agent fills: how to measure improvement |
| `bootstrap_state.json` | Canonical install/data/smoke state for repo readiness |
| `prepare.log` | Raw logs from env install, data prep, and smoke execution |
| `idea_pool.json` | Projected experiment backlog with priority, status, and worker claim metadata |
| `results.tsv` | Experiment log (timestamp, commit, metrics, status) |
| `events.jsonl` | Canonical runtime event stream for research + control |
| `research_graph.json` | Canonical hypothesis / experiment / evidence graph |
| `research_memory.json` | Repo prior, ideation, and experiment memory |
| `control.json` | Compatibility snapshot of pause/resume/skip state |
| `activity.json` | Real-time agent status for TUI display |

</details>

<details>
<summary><b>🔄 The Scout → Prepare → Review → Experiment Flow</b></summary>
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
  └─ Design evaluation + bootstrap hints → evaluation.md + config.yaml

Phase 3: Repository Prepare
  ├─ Resolve local Python env
  ├─ Resolve install_command / data_command / smoke_command
  ├─ Run install/data/smoke with logs in .research/prepare.log
  └─ Persist readiness state in .research/bootstrap_state.json

Phase 4: Human Review (TUI only, auto-confirmed in headless)
  ├─ Review all Scout outputs
  ├─ Review bootstrap resolution and readiness
  └─ Confirm, edit, or re-analyze

Phase 5: Research-v1 Loop
  ├─ Manager proposes/refines hypotheses and frontier rows
  ├─ Critic reviews experiment specs before execution
  ├─ Experiment agent implements, tests, and evaluates → results.tsv
  ├─ Critic records evidence and claim updates into research_graph.json
  └─ Repeat until no runnable frontier remains or --max-experiments reached
```

Each experiment is a git commit. Successful experiments stay; failed ones are rolled back. Everything is logged in `results.tsv`.

</details>

<details>
<summary><b>🧰 Auto-Prepare Resolution Rules</b></summary>
<br/>

`PaperFarm run` now tries to make a local Python repo runnable before the research loop starts.

- **Python env priority**: explicit `bootstrap.python` → active virtualenv → repo `.venv` → auto-create `.venv`
- **Install priority**: explicit `bootstrap.install_command` → `uv sync` → `poetry install` → `python -m pip install -r requirements.txt` → `python -m pip install -e .`
- **Data/setup priority**: explicit `bootstrap.data_command` → `make setup|prepare|data|download-data` → `scripts/prepare*.py` / `scripts/download*.py` / `data/*/prepare.py`
- **Smoke priority**: explicit `bootstrap.smoke_command` → first runnable command block from `.research/evaluation.md` → `pytest -q` → `make test`

If a command cannot be resolved safely, `run` stops before the review/runtime stage and records the failure in `.research/bootstrap_state.json`.

</details>

---

## 🛡️ Field Safety & Runtime Controls

| Feature | Description |
|:---|:---|
| **Isolated git commits** | Every experiment is a separate commit — nothing is lost |
| **Auto-rollback** | Failed experiments are automatically rolled back via `git reset` |
| **Timeout watchdog** | Kills experiments exceeding the configured time limit |
| **Crash counter** | Auto-pauses after N consecutive crashes (default: 3) |
| **Max experiments** | Stops after N experiments (`--max-experiments` or `config.yaml`) |
| **Control plane** | Pause / resume / skip commands are event-backed in `events.jsonl`, with `control.json` kept as a compatibility snapshot |
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
| [Kimi CLI](https://moonshotai.github.io/kimi-cli/en/reference/kimi-command.html) | `--agent kimi-cli` | Supported |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | `--agent gemini-cli` | Supported |

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
    sandbox: "workspace-write"            # workspace-write | read-only | danger-full-access | full-auto
  aider:
    model: "gpt-4o"
    extra_flags: ["--no-git"]
  opencode:
    model: "openai/gpt-5"
    agent: "builder"
    extra_flags: ["--share"]
  kimi-cli:
    model: ""                       # optional model override
    agent: "okabe"                  # optional built-in agent profile
    agent_file: ""                  # custom agent file path (optional)
    extra_flags: ["--thinking"]
  gemini-cli:
    model: "gemini-3.1-pro"          # override default model
    sandbox: ""                       # optional sandbox mode
    extra_flags: []
```

</details>

---

## 📊 Interactive TUI Dashboard

The interactive UI is now a **research-v1 command center**, not a generic tabbed monitor. It is built around the real runtime objects in `.research/`: frontier rows, hypotheses, evidence, claims, control state, and the shared event stream.

### Screenshots

<p align="center">
  <img src="imgs/overview.png" alt="Open Researcher overview dashboard" width="100%" />
</p>
<p align="center"><em>Field Overview</em>: research command center with frontier focus, lineage, and live role activity.</p>

<p align="center">
  <img src="imgs/execution.png" alt="Open Researcher execution dashboard" width="100%" />
</p>
<p align="center"><em>Harvest In Progress</em>: metric trend, run summary, and recent experiment results.</p>

<p align="center">
  <img src="imgs/docs.png" alt="Open Researcher docs dashboard" width="100%" />
</p>
<p align="center"><em>Docs</em>: searchable research documents with grouped navigation and live preview.</p>

```
┌─ OPEN RESEARCHER ─ research-v1 ────────────────────────────────────────┐
│ Research  branch main  frontier 3  best=0.3290                        │
├─ Command ─ Execution ─ Logs ─ Docs ────────────────────────────────────┤
│ Role Activity      │ Frontier Focus          │ Frontier Detail         │
│ Research Manager   │ frontier-001 / exec-014 │ status / priority /     │
│ Research Critic    │ hypothesis + spec       │ claim chips             │
│ Experiment Agent   │ select a frontier       │ collapsible hypothesis  │
│                    │ to inspect               │ spec / evidence / claim │
│────────────────────┼─────────────────────────┼─────────────────────────│
│ Research Graph     │ Lineage & Timeline      │ Docs sidebar + search   │
│ hypotheses/specs   │ hypothesis tree         │ grouped by type         │
│ evidence/claims    │ recent manager / critic │ recent docs + preview   │
└────────────────────────────────────────────────────────────────────────┘
```

<details>
<summary><b>📑 4 Tabs & Keyboard Shortcuts</b></summary>
<br/>

**4 tabs**:

- **Command** — Session chrome, role activity, frontier focus, collapsible frontier detail drawer, graph summary, hypothesis lineage, recent timeline
- **Execution** — Metric trend, baseline/current/best summary, recent results, execution focus
- **Logs** — Trace-aware runtime log with `frontier_id / execution_id / reason_code`
- **Docs** — Searchable docs workbench with grouped navigation, recent history, preview, and live document viewer

**Keyboard shortcuts**: `1-4` switch tabs, `p` pause, `r` resume, `s` skip frontier, `g` GPU status, `l` open run log, `q` quit.

</details>

<details>
<summary><b>🔎 Command Page Highlights</b></summary>
<br/>

- **Frontier Focus** shows the top projected frontier rows ordered by runtime priority, not a separate editable idea pool.
- **Frontier Detail Drawer** is selection-driven and includes collapsible sections for hypothesis, experiment spec, metric/evidence comparison, and claim updates.
- **Metric & Evidence Compare** shows latest observed metric, best observed metric, baseline/current/global best references, and evidence reliability counts.
- **Lineage & Timeline** combines branch relations from `research_graph.json` with the latest typed events from `events.jsonl`.

</details>

<details>
<summary><b>📚 Docs Workbench Highlights</b></summary>
<br/>

- Documents are grouped by type: **Research State**, **Research Notes**, and **Role Programs**.
- Search highlights matching text in titles, filenames, and previews.
- Recent documents are tracked in-session so you can jump back to the last files you inspected.
- Dynamic docs such as `research_graph.md`, `research_memory.md`, and `projected_backlog.md` are generated from canonical JSON state.

</details>

---

## 🚜 Installation

Open Researcher supports **Linux**, **macOS**, and **Windows**. Python 3.10+ required.

### Option A: pip install (recommended)

```bash
pip install PaperFarm

# Try the demo first (no agent or API key needed)
PaperFarm demo                   # run in terminal
PaperFarm demo --serve           # open in browser at http://localhost:8000

# Install browser support (optional)
pip install "PaperFarm[serve]"

# Then use it for real
cd your-project
PaperFarm run
```

### Option B: From source (for development)

<details>
<summary><b>🐧 Linux / 🍎 macOS / 💻 Windows</b></summary>
<br/>

```bash
git clone https://github.com/shatianming5/PaperFarm.git
cd PaperFarm
make dev    # install with dev dependencies
make test   # run tests
make test-cov      # run tests with coverage gate (>=75%)
make lint   # run linter
make package-check # build wheel + install + CLI smoke test
make ci     # full local CI: lint + test + coverage + package smoke
```

</details>

---

## 🖥️ CLI Reference

> All commands: `PaperFarm <command>`

<details>
<summary>⚡ <b>Core Commands</b></summary>
<br/>

| Command | What It Does |
|:---|:---|
| `run` | Primary command: bootstrap if needed, otherwise run the existing workflow |
| `run --mode headless --goal "..." --max-experiments N` | Headless JSON Lines mode |
| `run --workers N` | Set experiment worker count for serial or parallel execution |
| `start` | Legacy alias for bootstrap mode |
| `init [--tag NAME]` | Initialize `.research/` directory |
| `demo` | Try the TUI with sample data (no agent needed) |
| `demo --serve [--port N]` | Serve the demo TUI in a browser (requires `PaperFarm[serve]`) |

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
| `ideas list` | Inspect the projected backlog currently derived from `research_graph.json` |
| `ideas add "description"` | Compatibility command that now refuses mutation under `research-v1` |
| `ideas delete IDEA_ID` | Compatibility command that now refuses mutation under `research-v1` |
| `ideas prioritize` | Compatibility command that now refuses mutation under `research-v1` |

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
  # Free-form notes for agents. Runtime execution uses bootstrap.* below.

bootstrap:
  auto_prepare: true          # run install/data/smoke before review/runtime
  working_dir: "."            # relative to repo root
  python: ""                  # explicit python path if needed
  install_command: ""         # explicit dependency install command
  data_command: ""            # explicit dataset/setup command
  smoke_command: ""           # explicit readiness check command
  expected_paths: []          # files/dirs that data/setup must materialize
  requires_gpu: false         # fail prepare if GPU is required but unavailable

research:
  protocol: research-v1
  manager_batch_size: 3
  critic_repro_policy: best_or_surprising

memory:
  ideation: true
  experiment: true
  repo_type_prior: true

roles:
  scout_agent: ""             # optional override
  manager_agent: ""           # optional override
  critic_agent: ""            # optional override
  experiment_agent: ""        # optional override

gpu:
  remote_hosts: []            # optional remote GPU allocation hosts

agents:                       # per-agent overrides (optional)
  claude-code:
    model: ""
    allowed_tools: "Edit,Write,Bash,Read,Glob,Grep"
```

</details>

---

## 🏡 Project Structure

<details>
<summary>🎯 <b>Core System</b></summary>
<br/>

| Module | Description |
|:---|:---|
| `cli.py` | CLI entry point, all commands (Typer) |
| `run_cmd.py` | Unified workflow entrypoint: bootstrap flow + existing-workflow runner |
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
| `kimi.py` | Kimi CLI adapter |
| `gemini.py` | Gemini CLI adapter |

</details>

<details>
<summary>📊 <b>TUI Components (<code>tui/</code>)</b></summary>
<br/>

| Module | Description |
|:---|:---|
| `app.py` | Main Textual application for the 4-tab research command center |
| `widgets.py` | Command, execution, logs, docs, lineage, frontier, and detail drawer widgets |
| `view_model.py` | TUI-specific aggregation layer from graph / memory / results / events into renderable state |
| `review.py` | Post-Scout review TUI |
| `modals.py` | Modal dialogs (AddIdea, GPUStatus, Log) |
| `tui_runner.py` | Shared Textual session lifecycle for bootstrap and existing-workflow entrypoints |
| `styles.css` | CSS styling |

</details>

<details>
<summary>⚙️ <b>Runtime Engine</b></summary>
<br/>

| Module | Description |
|:---|:---|
| `idea_pool.py` | Serial idea backlog plus parallel claim handling for workers |
| `research_loop.py` | Shared Scout → Manager → Critic → Experiment core loop |
| `research_events.py` | Typed event contract shared by TUI and headless |
| `event_journal.py` | Shared JSONL journal for runtime and control events |
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

## 🌽 Examples

See [`examples/`](examples/) for complete setups:

- **[nanoGPT](examples/nanogpt/)** — Reduce validation loss in character-level language model training
- **[Liger-Kernel](examples/liger-kernel/)** — Optimize Triton GPU kernels
- **[HF GLUE](examples/hf-glue/)** — Improve HuggingFace Transformers fine-tuning
- **[CIFAR-10 Speedrun](examples/cifar10-speedrun/)** — Maximize CIFAR-10 image classification accuracy
- **[YOLO Tiny](examples/yolo-tiny/)** — Optimize YOLOv8 object detection on COCO8
- **[Whisper Fine-tune](examples/whisper-finetune/)** — Reduce Whisper speech recognition word error rate
- **[CartPole RL](examples/cartpole/)** — Maximize CartPole-v1 reinforcement learning reward
- **[Code Perf](examples/code-perf/)** — Optimize Python JSON parser throughput (non-ML)

---

## 🧑‍🌾 Contributing

Contributions are welcome! Please follow these steps:

1. Open an [issue](https://github.com/shatianming5/PaperFarm/issues) to discuss the proposed change
2. Fork the repository and create your feature branch
3. Submit a pull request with a clear description

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [CHANGELOG.md](CHANGELOG.md) for version history.

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

## Star History

[![Star History Chart](https://api.star-history.com/image?repos=shatianming5/PaperFarm&type=date&legend=top-left)](https://www.star-history.com/?repos=shatianming5%2FPaperFarm&type=date&legend=top-left)
