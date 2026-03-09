# TUI Simplification & Experiment Agent Redesign

Date: 2026-03-09

## Problem

1. Idea Pool panel doesn't show full idea descriptions, has no scrolling, truncates at 45 chars
2. Master+Worker experiment architecture is over-engineered for current use (CPU-only, single machine)
3. Dual-panel TUI layout wastes space when there's only one experiment agent

## Design

### TUI Layout — Single Panel

```
┌──────────────────────────────────────────────────────┐
│ Open Researcher | 4 exp | 2 kept 2 disc | best=1.62 │ StatsBar
├──────────────────────────────────────────────────────┤
│ ID  │ Description              │ Status │ Pri │ Val  │ DataTable
│ #01 │ Scale width n_embd=320.. │ pending│  1  │      │ (scrollable)
│ #02 │ Train longer 5000 iters  │ running│  4  │      │
│ #03 │ Reduce weight decay..    │ done   │  2  │1.621 │
├──────────────────────────────────────────────────────┤
│ >> [RUNNING] idea-002: Train longer...               │ AgentStatus
│    Experiment Agent (codex) | Updated: 16:25:08      │
├──────────────────────────────────────────────────────┤
│ [idea] Analyzing experiment results...               │ RichLog
│ [exp] Modifying train.py for max_iters=5000          │ (single stream)
│ [exp] Running evaluation...                          │
│ [exp] val loss 1.6180 — better than baseline         │
├──────────────────────────────────────────────────────┤
│ [p]ause [r]esume [s]kip [a]dd [g]pu [l]og [q]uit    │ HotkeyBar
└──────────────────────────────────────────────────────┘
```

Changes:
- Remove left/right dual-panel layout → single vertical stack
- IdeaPoolPanel → Textual DataTable (scrollable, full descriptions, columns: ID, Desc, Status, Priority, Result)
- Remove WorkerStatusPanel → replace with single AgentStatusWidget for experiment agent
- Single RichLog for both agents (prefixed [idea] / [exp])

### Experiment Agent — Serial Simplification

Remove:
- Master+Worker architecture, worktree creation, sub-agent spawning from experiment_program.md.j2
- worker_prompt.md.j2 template
- WorkerStatusPanel widget
- Complex restart logic in _launch_exp_with_wait

Simplified experiment_program.md.j2:
```
Phase 1: Detect environment (GPU/CPU)
Phase 2: Establish baseline (if no results yet)
Phase 3: Loop {
  Poll idea_pool.json for highest-priority pending idea
  Mark as running, update activity.json
  Implement the idea (edit code directly)
  Run evaluation
  Record result via scripts/record.py
  If better → keep, git commit
  If worse → discard, rollback
  Mark idea as done
  Repeat
}
```

### run_cmd.py Changes

- do_run_multi: both agents output to same RichLog with prefixes
- _launch_exp_with_wait: simplified wait-for-ideas + run-agent loop
- Single output callback writes to unified log file

### Preserved

- idea_pool.py, activity.py — data layer unchanged
- idea_program.md.j2 — idea agent logic unchanged
- File locking, atomic operations — recent fixes kept
- init_cmd.py — still generates all coordination files
