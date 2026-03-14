# Crash Retry + Failure Memory 闭环设计

> 日期: 2026-03-15
> 状态: 已批准

## 问题

当前系统 `failure_memory` 基础设施已建好（FailureMemoryLedger 数据结构、worker prepare/record 调用、环境变量传递），但消费端完全断路：

1. Agent 模板（experiment_program.md.j2）零引用 failure_memory 环境变量
2. 无重试指令 — crash 直接标记 `skipped`，idea 进入死胡同
3. crash 的 frontier 无法进入 `needs_post_review` → Critic 看不到
4. Manager 无法从 crash 中学习 → 可能重复提出相同失败方案

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 重试层级 | Agent 模板层 | 最灵活，Agent 可根据 exit code 自主决策重试策略 |
| crash 反馈 | 写入 research_graph | 融入主流程，Critic 自然处理 |
| 实现范围 | 3 层完整闭环 | 模板+Worker+Critic/Manager 全部对接 |

---

## 第 1 层：Agent 模板 — 瞬态错误自重试

### 文件：`src/open_researcher/templates/experiment_program.md.j2`

### A. Failure Memory 上下文注入

在模板的实验执行 Phase 之前，新增段落：

```markdown
## Failure Recovery Context

Check these environment variables before running experiments:
- `OPEN_RESEARCHER_MEMORY_POLICY`: "rank_historical_success" or "disabled"
- `OPEN_RESEARCHER_FAILURE_CLASS`: classified failure type for this idea
- `OPEN_RESEARCHER_FIRST_FIX_ACTION`: recommended fix from history
- `OPEN_RESEARCHER_RANKED_FIXES`: top-3 historical fixes (comma-separated)

If MEMORY_POLICY is "rank_historical_success" and FIRST_FIX_ACTION is not
"generate_new_plan", apply the suggested fix strategy before running.
```

### B. 训练失败恢复指令

```markdown
## Training Failure Recovery

If training fails, diagnose the exit code:

| Exit Code | Diagnosis | Action |
|-----------|-----------|--------|
| 120 | NCCL/distributed init failure | Retry with different master_port (pick random 29501-29650) |
| 137 | OOM / killed | Reduce batch_size by 50%, retry once |
| 1 with "address already in use" | Port conflict | Pick new port, retry |
| 1 with "CUDA error" | GPU error | Wait 30s, retry once |
| Other | Code/config error | Do NOT retry, record crash |

Retry rules:
- Maximum 2 retries per experiment
- Wait 10-30 seconds between retries
- Log each retry attempt in the run script
- If all retries fail, record as crash with diagnostic info
```

### C. Crash 诊断记录

```markdown
When recording a crash, include diagnostic info in secondary_metrics:
- failure_stage: "train_failed" | "eval_failed" | "setup_failed"
- failure_exit_code: the actual exit code
- failure_diagnosis: "nccl_timeout" | "oom_killed" | "port_conflict" | "code_error" | "unknown"
- retry_count: number of retries attempted
- retry_outcomes: brief description of each retry result
```

---

## 第 2 层：Worker — crash 生成 evidence 写入 graph

### 文件：`src/open_researcher/worker.py`

### 当前行为

```
crash (run_code != 0)
  → idea 标记 "skipped"
  → 结束（死胡同）
```

### 新行为

```
crash (run_code != 0)
  ↓
1. 生成 crash evidence:
   {
     frontier_id, hypothesis_id, experiment_spec_id, execution_id,
     metric_value: null,
     reliability: "invalid",
     reason_code: "crash_<diagnosis>",
     resource_observation: {...}
   }
  ↓
2. 追加到 research_graph.evidence[]
  ↓
3. 更新 frontier:
   status: "approved" → "needs_post_review"
   claim_state: → "needs_review"
  ↓
4. idea 标记 "done", result.verdict = "crash"
  ↓
5. failure_memory.record() 记录
```

### 实现

新增方法 `_record_crash_evidence(self, idea, run_code, result_status, resource_obs)`：
- 从 idea 提取 frontier_id, hypothesis_id 等
- 从 results.tsv 最新行提取 crash 诊断信息（failure_diagnosis 等）
- 构造 evidence dict，写入 graph
- 更新 frontier 状态

修改 crash 分支（行 1298-1319）：调用 `_record_crash_evidence()` 后标记 idea 为 `"done"`（而非 `"skipped"`）。

---

## 第 3 层：Critic/Manager — crash 感知

### A. Critic 模板修改

文件：`src/open_researcher/templates/critic_program.md.j2`

新增段落：

```markdown
## Crash Evidence Review

When reviewing evidence with `reliability: "invalid"` and reason_code
starting with "crash_":

1. Read diagnostic info (failure_diagnosis, retry_count, retry_outcomes)
2. Classify:
   - **Transient** (nccl_timeout, port_conflict, oom_killed after retry):
     → transition: "needs_repro", reason_code: "transient_crash_retry"
   - **Systematic** (code_error, config_error, 2+ crashes on same frontier):
     → transition: "reject", reason_code: "systematic_crash"
3. Same frontier crashed 2+ times → always "reject"
```

### B. Manager 模板修改

文件：`src/open_researcher/templates/manager_program.md.j2`

新增段落：

```markdown
## Crash History Awareness

When reviewing frontier history:
- family_key with crash evidence → investigate before creating similar specs
- crash reason "oom_killed" → reduce resource_request in new specs
- crash reason "code_error" → revise change_plan approach
- Do NOT re-propose exact same spec that crashed
```

### C. memory_policy.py 修改

在 `retrieve_history()` 中统计 crash：

```python
crash_count = sum(1 for e in family_evidence
                  if "crash" in str(e.get("reason_code", "")))
```

新增 `policy_state = "crash_prone"`：family 有 2+ crash → 降低 runtime_priority。

---

## 影响文件清单

| 文件 | 改动 |
|------|------|
| `templates/experiment_program.md.j2` | 新增 Failure Recovery Context + Training Failure Recovery + Crash 诊断记录 |
| `worker.py` | 新增 `_record_crash_evidence()`，修改 crash 分支逻辑 |
| `templates/critic_program.md.j2` | 新增 Crash Evidence Review 段落 |
| `templates/manager_program.md.j2` | 新增 Crash History Awareness 段落 |
| `memory_policy.py` | `retrieve_history()` 增加 crash_count，新增 crash_prone 策略 |

## 测试

- `pytest tests/ -x -q` 全量通过
- 验证 crash evidence 写入 graph 的逻辑
- 验证 memory_policy crash_count 统计
