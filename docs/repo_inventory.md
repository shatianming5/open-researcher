## Tree
- `src/open_researcher/`: 主代码
- `src/open_researcher/agents/`: agent adapter 实现
- `src/open_researcher/tui/`: Textual TUI
- `src/open_researcher/scripts/`: 运行期辅助脚本
- `tests/`: pytest 测试
- `docs/`: 文档与计划
- `examples/`: 示例目标仓库
- `analysis/`: 分析记录
- `.research/`: 运行期状态目录

## Entry Points
- `pyproject.toml`: 暴露 `open-researcher = open_researcher.cli:app`
- `src/open_researcher/cli.py`: 主 CLI，包含 `run/init/status/results/export/doctor/demo`
- `src/open_researcher/run_cmd.py`: interactive bootstrap/TUI 主路径
- `src/open_researcher/headless.py`: headless bootstrap/JSONL 主路径
- `src/open_researcher/init_cmd.py`: 初始化 `.research/` 模板与状态文件
- `src/open_researcher/config_cmd.py`: `open-researcher config show|validate`
- `src/open_researcher/ideas_cmd.py`: `open-researcher ideas list|add|delete|prioritize`
- `src/open_researcher/logs_cmd.py`: `open-researcher logs`

## Core Modules
- `src/open_researcher/workflow_options.py`: 统一 CLI 参数，归一化成 interactive/headless 与 worker 数。
- `src/open_researcher/agent_runtime.py`: agent 自动探测与显式解析。
- `src/open_researcher/research_loop.py`: 核心编排，统一执行 `Scout -> Manager -> Critic -> Experiment`。
- `src/open_researcher/research_events.py`: typed event 协议，映射到 `events.jsonl`。
- `src/open_researcher/event_journal.py`: JSONL 事件日志写入与读取。
- `src/open_researcher/graph_protocol.py`: `research-v1` 初始化与 role agent 解析。
- `src/open_researcher/research_graph.py`: canonical hypothesis/evidence/frontier graph 状态。
- `src/open_researcher/research_memory.py`: repo prior / ideation / experiment memory。
- `src/open_researcher/parallel_runtime.py`: 并行 experiment worker runtime。
- `src/open_researcher/tui/app.py`: 交互式监控 UI。
- `src/open_researcher/tui/events.py`: typed event -> TUI 日志渲染。
- `src/open_researcher/status_cmd.py`: 汇总 `.research/` 状态并显示进度。
- `src/open_researcher/results_cmd.py`: 读取/打印/图表化 `results.tsv`。

## Config & Data
- 配置文件：`.research/config.yaml`
- 关键配置：
  - `experiment.max_experiments`
  - `experiment.max_parallel_workers`
  - `metrics.primary.name`
  - `metrics.primary.direction`
  - `research.protocol = research-v1`
  - `research.manager_batch_size`
  - `research.critic_repro_policy`
  - `roles.scout_agent|manager_agent|critic_agent|experiment_agent`
  - `memory.ideation|experiment|repo_type_prior`
- 运行期状态：
  - `.research/scout_program.md`
  - `.research/.internal/role_programs/manager.md`
  - `.research/.internal/role_programs/critic.md`
  - `.research/.internal/role_programs/experiment.md`
  - `.research/idea_pool.json`
  - `.research/results.tsv`
  - `.research/events.jsonl`
  - `.research/research_graph.json`
  - `.research/research_memory.json`
  - `.research/activity.json`
  - `.research/control.json`
  - `.research/gpu_status.json`
- 外部前提：
  - 必须在 git repo 中运行
  - 至少安装一个支持的 agent CLI：`claude-code` / `codex` / `aider` / `opencode` / `kimi-cli` / `gemini-cli`
  - 并行 worker 场景默认假设本机或远端 GPU 可分配，但不是强制

## How To Run
```bash
open-researcher init
open-researcher run --agent codex
open-researcher run --mode headless --goal "improve latency"
open-researcher run --agent codex --workers 1
open-researcher run --agent codex --workers 4
open-researcher status
open-researcher results
open-researcher results --chart primary
open-researcher export
open-researcher config show
open-researcher ideas list
pytest -q
```

## Risks / Unknowns
- 当前“接口”主要是 CLI、配置文件、状态文件、typed events，不是 HTTP service。
- `research-v1` 已经是唯一执行协议，但并行 experiment worker 仍主要复用 `idea_pool.json` 兼容层。
- TUI 和 headless 都消费同一套 typed events，graph tracing 在 `research-v1` 下完整可见。
