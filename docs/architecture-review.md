# 架构审查报告（GPT-5.4 + Claude Opus 4.6 联合分析）

> 分析日期：2026-03-10
> 分析工具：Codex CLI (gpt-5.4, read-only, reasoning effort: xhigh)

> 回填说明（2026-03-10，当日实现已落地）：下面第 1-7 节保留了原始审查判断；每节后增加“落地后状态”回填。文中的原始行号引用反映审查时快照，不等于当前代码行号。

---

## 核心结论

**项目的"研究流程模型"是简洁的，但"承载这个流程的运行平台"已经偏厚。**

核心循环确实是 `Scout → Idea → Experiment → Idea`，但外围包了较多运行时控制、并发、持久化和显示适配层。下一步最值得做的不是改 agent，而是把 orchestration、runtime、presentation 三层重新切开。

---

## 0. 实施回填（2026-03-10 当前代码状态）

**结论：报告里的 P0、P1、P2 已基本全部落地，且默认路径已经明显变薄。**

| 项目 | 状态 | 当前落地 |
|:---|:---|:---|
| `research_loop.py` 核心循环抽取 | **已完成** | `Scout`、单 agent、双 agent 默认循环统一收敛到 core engine |
| typed events + 双 renderer | **已完成** | TUI 与 Headless 共用 `research_events.py` + `event_journal.py` |
| CLI 收口 | **已完成（兼容保留旧入口）** | 主路径改为高层 `mode/workers`，旧 `--multi/--idea-agent/--exp-agent` 隐藏兼容 |
| `IdeaPool` 默认路径简化 | **已完成** | 拆成 `IdeaBacklog`（默认串行）与 `IdeaPool`（并行 claim/token 模式） |
| Worker/GPU/FailureMemory 插件化 | **已完成** | 通过 `worker_plugins.py` + `parallel_runtime.py` profile 收口为 advanced runtime |
| ControlPlane 合并到事件流 | **已完成** | `events.jsonl` 成为 canonical source，`control.json` 降为兼容快照 |

**当前剩余的主要问题不再是 P0/P1/P2 本身，而是：**

- `run_cmd.py` 虽已明显瘦身，但仍保留 TUI 入口适配和并行路径接线。
- `idea_program.md` / `experiment_program.md` 仍然存在；它们已经退化成内部实现文件，但概念还没有完全消失。
- 并行 worker 路径仍是一套“高级运行平台”，只是现在已经被清晰地隔离到了 advanced mode。

---

## 1. Agent 链路是否足够简洁

**结论：语义上接近，架构上不够简洁。**

- `Scout → Review → Idea/Experiment loop` 是明确存在的，入口现在集中在 `run_cmd.py` 和 `headless.py`。
- 真正的运行路径更像：

```
CLI → run orchestrator → Scout → TUI Review → IdeaPool
    → alternating/WorkerManager → Experiment Agent
    → ControlPlane/CrashCounter/PhaseGate/TimeoutWatchdog/GPUManager/FailureMemory
    → 回写 IdeaPool → Idea Agent
```

- **"三个 agent"是核心业务模型，但不是系统真实结构。系统真实结构已经演化成"agent loop + 一套运行平台"。**

### 1.1 落地后状态

**默认路径已经明显变成“三 agent 业务模型 + 一个薄 core engine”；厚 runtime 被压缩到并行高级模式。**

当前默认单机路径更接近：

```text
CLI / run / headless
    → ResearchLoop
    → typed events
    → TUIEventRenderer / HeadlessLogger
```

只有在 `workers > 1` 时才会切到：

```text
ResearchLoop / run adapter
    → parallel_runtime
    → WorkerManager
    → WorkerRuntimePlugins
    → IdeaPool (claim/token path)
```

也就是说，**“三个 agent + 一套运行平台”这个判断对并行高级模式仍成立，但对默认路径已经不再成立。**

---

## 2. 过度设计 / 冗余抽象 / 不必要复杂性

**结论：有，主要集中在 orchestration 和 runtime 层，不在 agent 抽象本身。**

| 问题 | 位置 | 说明 |
|:---|:---|:---|
| `run_cmd.py` 职责过重 | `run_cmd.py:120-415` | 接近 god module。同时承担 agent 启动、输出包装、watchdog、单双 agent 编排、并行 worker 协调、状态检查 |
| `start` bootstrap 逻辑曾经叠在 `run_cmd.py` 之外 | 现已收敛回 `run_cmd.py` | 历史问题已消除，保留为架构演进背景 |
| `IdeaPool` 设计偏重 | `idea_pool.py:16` | 不只是队列，而是带文件锁、claim token、状态迁移、优先级、实验归属的持久化状态机 |
| `WorkerManager` 平台化超前建设 | `worker.py:21-82` | 叠加了 GPU 管理、活动监控、失败记忆账本、worktree 隔离 |
| `ControlPlane` 引入第二套状态源 | `control_plane.py:14` | 单独维护 pause/resume/skip/phase 的线性化命令与文件锁 |
| `AgentAdapter` | `agents/base.py:13` | 这层抽象本身合理，是较好的最小抽象 |

### 2.1 落地后状态

这部分已经发生实质变化：

- `run_cmd.py` 仍然不是完美的“纯 adapter”，但核心 loop、agent 解析、日志封装、并行 runtime 已被拆出去。
- `IdeaPool` 已拆分为：
  - `IdeaBacklog`：默认串行 backlog，不带 claim token / `assigned_experiment`
  - `IdeaPool`：仅用于并行 worker 的 claim/token 并发路径
- `WorkerManager` 不再硬编码 GPU / FailureMemory / worktree；这些能力已经通过插件 bundle 显式注入。
- `ControlPlane` 不再维护真正独立的第一状态源；现在以 `events.jsonl` 为准，`control.json` 只是兼容快照。

因此，**原本最重的两个点（`IdeaPool`、`ControlPlane`）都已经被按报告建议切开。**

---

## 3. TUI 和 Headless 是否干净分离

**结论：显示输出层基本分离，但"显示层"和"编排层"没有完全干净切开。**

- **好的一面**：TUI 在 `run_cmd.py` + `ResearchApp/ReviewScreen`，Headless 在 `headless.py` + `HeadlessLogger` 输出 JSON Lines，两者没有交叉依赖 TUI 组件。
- **不够干净的地方**：Headless 复用了 `run_cmd.py` 里的运行辅助函数（`_has_pending_ideas`、`_read_latest_status`、`_resolve_agent`、`_set_paused`），说明系统没有一个真正"无显示依赖的核心 loop API"。

**当前状态**：两个前端，共享一部分 orchestration 工具。
**理想状态**：一个 core engine，两个 renderer。

```
理想架构：
  Core Research Loop  →  typed events  →  TUI renderer
                                       →  JSONL renderer
```

### 3.1 落地后状态

这一条已经基本实现。

- TUI 现在订阅统一 typed events。
- Headless 现在也订阅同一套 typed events，并写入同一份 `events.jsonl`。
- Headless 不再复用 `run_cmd.py` 里的 orchestration helper；共享的是 `ResearchLoop`、`research_events`、`event_journal` 这套 core 层。

**当前更准确的描述已经是：一个 core engine，两个 renderer。**

---

## 4. 接口是否足够简洁

**结论：对高级用户还可以，对普通用户不够简洁，内部概念暴露偏多。**

暴露的内部概念：

| 暴露点 | 位置 | 说明 |
|:---|:---|:---|
| `--multi` / `--idea-agent` / `--exp-agent` | `cli.py:84` | 让用户必须理解 Idea/Experiment 的内部区分 |
| `idea_program.md` / `experiment_program.md` | `run_cmd.py:229-366` | 要求特定程序文件存在 |
| `--goal` 强制要求 | `cli.py:115` | `--headless` 时必须提供 `--goal` |
| `.research/events.jsonl` | `headless.py:74` | 暴露内部事件日志路径 |
| `.research/control.json` | `run_cmd.py:61` | 暴露控制文件 |

**更理想的接口**：只暴露 `goal`、`mode=interactive|headless`、`workers`、可选 `agent_profile`。Idea/Experiment 的拆分应尽量是内部实现。

### 4.1 落地后状态

这部分已完成大半：

- CLI 主路径已经收口到高层参数，`workers` 成为并行能力的主要开关。
- `--multi` / `--idea-agent` / `--exp-agent` 仍存在，但已经转为隐藏兼容入口，而不是主推荐接口。
- `goal`、`interactive/headless`、`workers` 已经成为更接近用户心智模型的接口。

仍未完全收口的部分：

- `idea_program.md` / `experiment_program.md` 还在内部实现里存在。
- `.research/events.jsonl` / `.research/control.json` 作为运行时文件仍然可见，只是前者已经明确为 canonical stream，后者仅为兼容快照。

---

## 5. 建议的简化方向

### 5.1 核心循环独立化

把核心循环收敛成一个单独模块（如 `research_loop.py`），只保留三个 phase：

```python
class ResearchLoop:
    def scout(self, agent, workdir) -> ScoutResult: ...
    def ideate(self, agent, workdir) -> list[Idea]: ...
    def experiment(self, agent, workdir, idea) -> ExperimentResult: ...
    def run(self, ...):  # Scout → Idea ↔ Experiment 循环
```

### 5.2 输入/输出适配分离

`cli.py`、`run_cmd.py`、`headless.py` 都只做"输入适配"和"输出适配"，不再持有业务编排。

### 5.3 事件驱动显示

TUI 和 Headless 都改成订阅同一套 typed events，不要让 `run_cmd.py` 同时懂 orchestration 和展示。

```python
# 事件类型
@dataclass
class ScoutStarted: ...
@dataclass
class IdeaGenerated: idea: Idea
@dataclass
class ExperimentCompleted: idea: Idea, result: ExperimentResult
@dataclass
class LoopFinished: ...

# 显示层只订阅事件
class TUIRenderer:
    def on_event(self, event): ...

class JSONLRenderer:
    def on_event(self, event): ...
```

### 5.4 运行时功能可插拔

`IdeaPool + ControlPlane + FailureMemory` 视为可插拔 runtime feature，默认路径先走最小实现。

### 5.5 高级模式分层

并行 worker、GPU 调度、失败记忆账本改成高级模式；默认单机单 worker 路径应尽量接近三 agent 理想模型。

### 5.6 CLI 收口

隐藏 `idea/exp/program file/control file` 这些内部概念，收口成少量高层参数。

### 5.7 落地情况总结

按这份报告定义的简化方向，当前完成度可以概括为：

- **5.1 已完成**：`research_loop.py` 已抽出。
- **5.2 已完成**：`cli.py` / `run_cmd.py` / `headless.py` 已明显退化为输入输出适配层。
- **5.3 已完成**：typed events + TUI/JSONL renderer 已统一。
- **5.4 已完成**：运行时功能已变成可插拔插件和可切换 profile。
- **5.5 已完成**：并行 worker / GPU / failure memory 已被隔离为高级模式。
- **5.6 大体完成**：CLI 已收口，但内部 program file 仍作为实现细节存在。

---

## 6. 理想 vs 当前架构对比

### 理想架构（你描述的简洁模型）

```
用户 → PaperFarm run [--mode interactive|headless]
                │
                ▼
        ┌─── Analysis Agent (Scout) ───┐
        │   分析代码、搜索文献、设计评估   │
        └──────────┬───────────────────┘
                   ▼
        ┌─── Idea Agent ◄─────────────┐
        │   生成实验假设                 │
        └──────────┬───────────────────┘
                   ▼                   │
        ┌─── Experiment Agent ─────────┘
        │   实现、测试、评估 → 回到 Idea
        └──────────────────────────────┘

显示层：TUI（交互式）或 Headless（JSON Lines）
```

### 当前实际架构

```
用户 → cli.py → run_cmd.py
                    │
                    ├── 缺少 `.research/` → bootstrap
                    │       → init_cmd → render templates
                    │       → Scout Agent (scout_program.md)
                    │       → TUI Review / auto-confirm
                    │
                    └── 已有 `.research/` → 直接运行研究循环
                                        │
                                        ▼
    ┌─── ResearchLoop ───────────── 或 ─── parallel_runtime ──┐
    │                                                          │
    │   IdeaBacklog / IdeaPool                                 │
    │       ▼                                                  │
    │   Experiment Agent                                       │
    │       ▼                                                  │
    │   CrashCounter + PhaseGate + TimeoutWatchdog            │
    │   + WorkerRuntimePlugins + event-backed ControlPlane    │
    │       ▼                                                  │
    │   回写 backlog / pool → 回到 Idea Agent                 │
    └──────────────────────────────────────────────────────────┘
```

### 当前实际架构（落地后修正版）

```text
用户 → cli.py
       → run_cmd.py / headless.py                  # 输入输出适配
       → ResearchLoop                              # core engine
       → ResearchEvents                            # typed events
       → TUIEventRenderer / HeadlessLogger         # presentation

默认单机/单 worker：
  不经过 WorkerManager
  不经过 IdeaPool claim/token 状态机
  只使用轻量 IdeaBacklog

并行高级模式（workers > 1）：
  parallel_runtime
    → WorkerManager
    → WorkerRuntimePlugins
       → GPUAllocatorPlugin
       → FailureMemoryPlugin
       → WorktreeIsolationPlugin
    → IdeaPool (claim/token / assigned_experiment)

控制面：
  events.jsonl   # canonical source
  control.json   # compatibility snapshot
```

---

## 7. 优先级排序

| 优先级 | 改动 | 影响 | 状态 |
|:---|:---|:---|:---|
| **P0** | 抽取 `research_loop.py` 核心循环 | 解决 run_cmd god module + 编排逻辑分散 | **已完成** |
| **P0** | 事件驱动：TUI/Headless 订阅统一事件流 | 干净切开显示层和编排层 | **已完成** |
| **P1** | CLI 接口简化：隐藏 `--multi`/`--idea-agent`/`--exp-agent` | 降低用户认知成本 | **已完成（兼容入口仍保留）** |
| **P1** | IdeaPool 简化：默认路径不需要 claim token | 减少单机场景复杂度 | **已完成** |
| **P2** | WorkerManager/GPU/FailureMemory 改为可选插件 | 减少默认路径代码量 | **已完成** |
| **P2** | ControlPlane 简化或合并到事件流 | 减少状态源数量 | **已完成** |

### 7.1 新的后续优先级

P0/P1/P2 已经完成后，新的合理优先级应变成：

| 新优先级 | 改动 | 影响 |
|:---|:---|:---|
| **R1** | 继续压薄 `run_cmd.py` 的入口适配代码 | 进一步收口 orchestration 边界 |
| **R1** | 把 `idea_program.md` / `experiment_program.md` 更彻底地下沉为内部实现细节 | 继续减少对外暴露的内部概念 |
| **R2** | 为 advanced runtime 建立更明确的 profile 文档和可观测性边界 | 防止默认路径再次被高级模式污染 |
| **R2** | 清理历史设计文档与旧 JSON 示例 | 降低后续回退到旧心智模型的概率 |
