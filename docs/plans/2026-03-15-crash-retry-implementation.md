# Crash Retry + Failure Memory 闭环 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect the existing failure_memory infrastructure to Agent templates and fix the crash→skipped dead-end so crashes flow through Critic/Manager review.

**Architecture:** Three layers: (1) Add retry instructions to experiment_program.md.j2 template so agents can self-recover from transient failures, (2) Fix worker.py crash branch to mark ideas as "done" with verdict="crash" instead of "skipped" so absorb_experiment_outcomes() generates evidence and updates frontier to needs_post_review, (3) Add crash-aware sections to critic and manager templates + crash_count tracking in memory_policy.py.

**Tech Stack:** Python 3.12, Jinja2 templates, pytest, filelock

---

## Task 1: Fix Worker crash branch — idea "done" instead of "skipped"

**Files:**
- Modify: `src/open_researcher/worker.py:1298-1319`
- Test: `tests/test_worker.py`

**Context:** Currently when `run_code != 0` and no terminal result is present, the idea is marked "skipped" (line 1301-1319). This prevents `absorb_experiment_outcomes()` from finding the idea and generating evidence. The fix: mark as "done" with `result.verdict = "crash"` so the absorb pipeline creates evidence with `status=crash`.

**Step 1: Read worker.py crash branch**

Read lines 1290-1340 to understand the exact current code.

**Step 2: Modify crash branch**

Find the block at ~line 1299-1319 where `update_status("skipped")` is called when there's no terminal result. Change it to mark the idea as "done" with crash metadata:

```python
# OLD (line ~1301-1319):
else:
    if not self._terminal_result_present(current_state):
        applied = self.idea_pool.update_status(
            idea["id"],
            "skipped",
            claim_token=claim_token or None,
            resource_observation=self._resource_observation(...)
        )

# NEW:
else:
    if not self._terminal_result_present(current_state):
        # Mark as done with crash verdict so absorb_experiment_outcomes()
        # generates evidence and frontier enters needs_post_review
        crash_result = {
            "metric_value": None,
            "verdict": "crash",
            "failure_exit_code": run_code,
        }
        applied = self.idea_pool.update_status(
            idea["id"],
            "done",
            claim_token=claim_token or None,
            resource_observation=self._resource_observation(...),
            result=crash_result,
        )
```

Note: Check if `update_status` accepts a `result` parameter. If not, use `mark_done` or `mark_done_with_context` instead — read `idea_pool.py` to find the right API.

**Step 3: Run tests**

Run: `python3 -m pytest tests/ -x -q --timeout=60`
Expected: All tests PASS (or fix any tests that expected "skipped" for crash)

**Step 4: Commit**

```bash
git add src/open_researcher/worker.py tests/test_worker.py
git commit -m "fix(worker): mark crashed ideas as done/crash instead of skipped"
```

---

## Task 2: Add Failure Recovery instructions to experiment_program.md.j2

**Files:**
- Modify: `src/open_researcher/templates/experiment_program.md.j2:~136`

**Context:** The template currently has zero references to failure_memory environment variables. We need to add a section that tells the Agent how to diagnose and retry transient failures.

**Step 1: Read experiment_program.md.j2**

Read the full file to find the exact insertion point (around line 136, before "### 2d. Implement").

**Step 2: Insert Failure Recovery Context section**

Before the implementation phase, add:

```markdown
### 2c½. Failure Recovery Context

Before running training/evaluation commands, check these environment variables:
- `OPEN_RESEARCHER_MEMORY_POLICY`: if "rank_historical_success", historical fix data is available
- `OPEN_RESEARCHER_FAILURE_CLASS`: pre-classified failure type for this idea
- `OPEN_RESEARCHER_FIRST_FIX_ACTION`: recommended first remediation from history
- `OPEN_RESEARCHER_RANKED_FIXES`: comma-separated top-3 historical fixes

If `OPEN_RESEARCHER_FIRST_FIX_ACTION` is set and not "generate_new_plan", consider
applying the suggested fix proactively (e.g., picking a non-default master_port,
reducing batch size).
```

**Step 3: Insert Training Failure Recovery section**

After the evaluate/record phase, add retry instructions:

```markdown
### 2e½. Training Failure Recovery

If a training or evaluation command fails, diagnose and retry transient errors:

| Exit Code | Likely Cause | Recovery Action |
|-----------|-------------|-----------------|
| 120 | NCCL / distributed init | Pick a different `--master_port` (random in 29501-29650), retry |
| 137 | OOM / killed by OS | Halve `--samples-per-gpu` or `--batch-size`, retry once |
| 1 + "address already in use" in stderr | Port conflict | Pick new port, retry |
| 1 + "CUDA error" in stderr | Transient GPU fault | Wait 30 seconds, retry once |
| Any other | Code or config bug | Do **not** retry — record as crash |

**Retry rules:**
- Maximum **2 retries** per experiment.
- Sleep 10-30 seconds between retries.
- Each retry should be a fresh `torchrun` / training invocation.
- Log every retry attempt (exit code, stderr snippet, action taken).

**When recording a crash** (all retries exhausted or non-retriable error), include
in `secondary_metrics` passed to `record.py`:
- `failure_diagnosis`: one of `nccl_timeout`, `oom_killed`, `port_conflict`, `code_error`, `unknown`
- `retry_count`: how many retries were attempted
- `retry_outcomes`: short description of each retry result
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/ -x -q --timeout=60`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/open_researcher/templates/experiment_program.md.j2
git commit -m "feat(template): add failure recovery and retry instructions to experiment program"
```

---

## Task 3: Add Crash Evidence Review to critic_program.md.j2

**Files:**
- Modify: `src/open_researcher/templates/critic_program.md.j2:~156`

**Step 1: Read critic_program.md.j2**

Read the full file to find the Post-Run Review section and the exact insertion point.

**Step 2: Insert Crash Evidence Review section**

After the normal post-run reliability assessment, add:

```markdown
### Crash Evidence Assessment

When reviewing evidence where the result row has `status: "crash"`:

1. **Read diagnostic info** from `secondary_metrics`:
   - `failure_diagnosis`, `retry_count`, `retry_outcomes`, `failure_exit_code`

2. **Classify the crash type:**
   - **Transient** (`nccl_timeout`, `port_conflict`, `oom_killed` with retries exhausted):
     - Set `reliability: "invalid"`, `reason_code: "transient_crash"`
     - Set `transition: "needs_repro"` — the frontier deserves another attempt
   - **Systematic** (`code_error`, `unknown`, or same frontier crashed 2+ times):
     - Set `reliability: "invalid"`, `reason_code: "systematic_crash"`
     - Set `transition: "reject"` — the hypothesis/spec has fundamental issues

3. **Repeated crash rule:** If the same frontier_id appears in 2 or more crash
   evidence rows, always use `transition: "reject"` regardless of diagnosis.
```

**Step 3: Run tests**

Run: `python3 -m pytest tests/ -x -q --timeout=60`

**Step 4: Commit**

```bash
git add src/open_researcher/templates/critic_program.md.j2
git commit -m "feat(template): add crash evidence assessment to critic program"
```

---

## Task 4: Add Crash History Awareness to manager_program.md.j2

**Files:**
- Modify: `src/open_researcher/templates/manager_program.md.j2:~163`

**Step 1: Read manager_program.md.j2**

Read the full file to find the Manager Policy section.

**Step 2: Insert Crash History Awareness section**

In the Manager Policy section, add:

```markdown
### Crash History Awareness

Before proposing new frontier rows, review crash patterns:

- If a `family_key` has **crash evidence** in the graph → investigate the crash
  `reason_code` before creating similar experiment specs.
- If crash reason was `oom_killed` → reduce `resource_request` (smaller batch,
  fewer GPUs) in new specs for this family.
- If crash reason was `code_error` → the `change_plan` approach likely has a bug;
  revise the implementation strategy or reject the hypothesis.
- **Do NOT** re-propose the exact same `experiment_spec` that produced a crash.
  Check `evidence` rows for `reason_code` containing "crash" before approving
  similar specs.
- If a family has 2+ crash evidence rows → set `priority` to lowest and consider
  archiving the hypothesis.
```

**Step 3: Add failure_memory_ledger.json to Manager's read list**

In the Files section (around line 5-16), add:

```markdown
- **Read** (optional): `.research/failure_memory_ledger.json` — historical crash recovery outcomes
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/ -x -q --timeout=60`

**Step 5: Commit**

```bash
git add src/open_researcher/templates/manager_program.md.j2
git commit -m "feat(template): add crash history awareness to manager program"
```

---

## Task 5: Add crash_count tracking to memory_policy.py

**Files:**
- Modify: `src/open_researcher/memory_policy.py:68-165` (retrieve_history)
- Modify: `src/open_researcher/memory_policy.py:196-210` (apply_history_policy)

**Step 1: Read memory_policy.py**

Read the full file, especially `retrieve_history()` and `apply_history_policy()`.

**Step 2: Add crash_count to retrieve_history()**

In `retrieve_history()`, after counting strong_positive_count, negative_count, open_repro_count, add crash counting:

```python
# Add to the history dict initialization:
history = {
    "strong_positive_count": 0,
    "negative_count": 0,
    "open_repro_count": 0,
    "crash_count": 0,        # NEW
    "recent_matches": [],
}

# In the evidence/claim scanning loop, count crash evidence:
reason_code = str(item.get("reason_code", ""))
if "crash" in reason_code:
    history["crash_count"] += 1
```

**Step 3: Add crash_prone policy state to apply_history_policy()**

In `apply_history_policy()`, after the existing policy state assignments, add:

```python
# After existing policy_state assignments:
if history.get("crash_count", 0) >= 2 and history.get("strong_positive_count", 0) == 0:
    row["policy_state"] = "crash_prone"
    row["runtime_priority"] = row.get("runtime_priority", 0) + 4  # deprioritize
```

**Step 4: Run tests**

Run: `python3 -m pytest tests/ -x -q --timeout=60`

**Step 5: Commit**

```bash
git add src/open_researcher/memory_policy.py
git commit -m "feat(policy): add crash_count tracking and crash_prone policy state"
```

---

## Task 6: Final integration test and commit

**Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -x -q --timeout=60`
Expected: All 761+ tests PASS

**Step 2: Verify the complete crash flow**

Manually trace the flow to confirm:
1. Worker crash → idea marked "done" with verdict="crash" ✓
2. `absorb_experiment_outcomes()` picks up crash result → generates evidence ✓
3. Frontier status → "needs_post_review" ✓
4. Critic template has crash evidence instructions ✓
5. Manager template has crash history awareness ✓
6. `memory_policy.py` tracks crash_count and applies crash_prone ✓
7. `experiment_program.md.j2` has retry instructions ✓

**Step 3: Single integration commit if needed**

If individual commits were made per task, no additional commit needed.
Otherwise:

```bash
git add -A
git commit -m "feat: complete crash retry + failure_memory closed loop"
```

---

## Deployment

After all tasks complete:

```bash
# SCP to remote runners
for runner in open-researcher open-researcher-runner-20260312 open-researcher-runner-c2a5ab9 open-researcher-runner-3a29c1b open-researcher-runner-025412c; do
    scp -r src/open_researcher/ zechuan@222.200.185.183:/mnt/SSD1_8TB/zechuan/$runner/src/open_researcher/
done
```
