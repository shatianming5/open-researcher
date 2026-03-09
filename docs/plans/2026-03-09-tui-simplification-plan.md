# TUI Simplification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Simplify TUI to single-panel layout with scrollable DataTable for ideas, remove Master+Worker experiment architecture in favor of serial experiment agent.

**Architecture:** Replace dual-panel TUI with vertical stack (StatsBar → DataTable → AgentStatus → RichLog → HotkeyBar). Simplify experiment_program.md.j2 to serial claim-implement-evaluate loop. Both agents output to single RichLog with prefixes.

**Tech Stack:** Textual (DataTable widget), Jinja2 templates, Python threading

---

### Task 1: Replace IdeaPoolPanel with DataTable

**Files:**
- Modify: `src/open_researcher/tui/widgets.py:36-84` (replace IdeaPoolPanel class)
- Modify: `src/open_researcher/tui/app.py:49-59` (compose method)
- Modify: `src/open_researcher/tui/app.py:77-85` (_refresh_data idea pool section)
- Modify: `src/open_researcher/tui/styles.css:13-18` (#idea-pool rules)
- Modify: `tests/test_tui.py:21-38,86-104` (IdeaPoolPanel tests)

**Step 1: Update IdeaPoolPanel widget to use DataTable**

Replace the IdeaPoolPanel class in `widgets.py` with:

```python
from textual.widgets import DataTable, Static

class IdeaPoolTable(Static):
    """Scrollable DataTable showing all ideas in the pool."""

    def compose(self):
        yield DataTable(id="idea-table")

    def on_mount(self):
        table = self.query_one("#idea-table", DataTable)
        table.add_columns("ID", "Description", "Status", "Pri", "Result")
        table.cursor_type = "row"

    def update_ideas(self, ideas: list[dict], summary: dict) -> None:
        table = self.query_one("#idea-table", DataTable)
        table.clear()
        status_order = {"running": 0, "pending": 1, "done": 2, "skipped": 3}
        sorted_ideas = sorted(ideas, key=lambda i: (status_order.get(i["status"], 9), i.get("priority", 99)))
        for idea in sorted_ideas:
            sid = idea["status"]
            iid = idea["id"].replace("idea-", "#")
            desc = idea["description"][:80]
            pri = str(idea.get("priority", ""))
            result = idea.get("result")
            if result and result.get("metric_value"):
                val = f"{result['metric_value']:.4f}"
            else:
                val = ""
            status_display = sid.upper() if sid == "running" else sid
            table.add_row(iid, desc, status_display, pri, val)
```

**Step 2: Update app.py compose() — single panel layout**

Replace compose method:

```python
def compose(self) -> ComposeResult:
    yield StatsBar(id="stats-bar")
    yield IdeaPoolTable(id="idea-pool")
    yield AgentStatusWidget(id="agent-status")
    yield RichLog(id="agent-log", wrap=True, markup=False)
    yield HotkeyBar(id="hotkey-bar")
```

**Step 3: Update _refresh_data() for new widget IDs**

Simplify idea pool refresh (no workers parameter):
```python
# Refresh idea pool
try:
    ideas = self.pool.all_ideas()
    summary = self.pool.summary()
    self.query_one("#idea-pool", IdeaPoolTable).update_ideas(ideas, summary)
except (json.JSONDecodeError, OSError, KeyError, NoMatches):
    pass
```

Merge agent status refresh into one (show experiment agent status when running, else idea agent):
```python
# Refresh agent status
try:
    exp_act = self.activity.get("experiment_master")
    idea_act = self.activity.get("idea_agent")
    # Show whichever agent is actively doing something
    active = exp_act if exp_act and exp_act.get("status") not in (None, "idle") else idea_act
    self.query_one("#agent-status", AgentStatusWidget).update_status(active)
except (json.JSONDecodeError, OSError, KeyError, NoMatches):
    pass
```

Remove the worker status panel refresh block entirely.

**Step 4: Update CSS for vertical stack layout**

Replace `#idea-pool`, `#agent-panels`, `#idea-agent-section`, `#exp-agent-section`, `#idea-status`, `#worker-status`, `#idea-log`, `#exp-log` rules with:

```css
#idea-pool {
    height: auto;
    max-height: 12;
    border: solid $primary;
}

#agent-status {
    min-height: 2;
    height: auto;
    max-height: 5;
    border-bottom: solid $accent;
    padding: 0 1;
}

#agent-log {
    height: 1fr;
    border: solid $primary;
}
```

Remove all `#agent-panels`, `#idea-agent-section`, `#exp-agent-section`, `#idea-status`, `#worker-status`, `#idea-log`, `#exp-log` rules.

**Step 5: Update tests**

Replace IdeaPoolPanel tests with IdeaPoolTable tests (can't test DataTable without Textual app, so test the class exists and basic creation):

```python
def test_idea_pool_table_exists():
    from open_researcher.tui.widgets import IdeaPoolTable
    panel = IdeaPoolTable()
    assert panel is not None
```

Remove `test_idea_pool_shows_gpu_info` and `test_worker_status_panel_*` tests.

**Step 6: Run tests**

Run: `python3 -m pytest tests/ -x -q`
Expected: All pass

**Step 7: Commit**

```bash
git add src/open_researcher/tui/ tests/test_tui.py
git commit -m "feat: replace IdeaPoolPanel with scrollable DataTable, single-panel layout"
```

---

### Task 2: Simplify experiment_program.md.j2

**Files:**
- Modify: `src/open_researcher/templates/experiment_program.md.j2` (full rewrite)
- Delete: `src/open_researcher/templates/worker_prompt.md.j2`

**Step 1: Rewrite experiment_program.md.j2**

Replace entire file with simplified serial version:

```markdown
# Experiment Agent — Serial Experiment Runner

You are the **Experiment Agent**. You pick ideas from the pool and run experiments one at a time.

## Your Files

- **Read/Write**: `.research/idea_pool.json` — claim ideas, update results
- **Read/Write**: `.research/activity.json` — update `experiment_master` key with status
- **Write**: `.research/results.tsv` — record results via `.research/scripts/record.py`
- **Read**: `.research/config.yaml` — experiment settings
- **Read**: `.research/evaluation.md` — how to evaluate experiments
- **Read**: `.research/control.json` — pause/skip signals

## Status Updates

Before each action, update `.research/activity.json`:
```json
{"experiment_master": {"status": "<phase>", "detail": "<what you're doing>", "idea": "<current idea>", "updated_at": "<ISO timestamp>"}}
```

Valid statuses: `detecting_environment`, `establishing_baseline`, `running`, `evaluating`, `idle`, `paused`

## Phase 1: Detect Environment

1. Check for GPUs:
   ```bash
   nvidia-smi --query-gpu=index,memory.total,memory.free --format=csv 2>/dev/null
   ```
2. If GPUs available: note which device to use (pick the one with most free memory)
3. If no GPUs: you will run on CPU. Set `CUDA_VISIBLE_DEVICES=` (empty) for all training commands

## Phase 2: Establish Baseline (First Run Only)

If `.research/results.tsv` has no data rows (only header):
1. Create branch: `git checkout -b research/{{ tag }}`
2. Read `.research/evaluation.md` for the exact command to run
3. Run the evaluation command as-is (no modifications)
4. Extract the primary metric from output
5. Record: `python .research/scripts/record.py --metric <name> --value <val> --status keep --desc "baseline"`
6. Git commit: `git add -A && git commit -m "baseline: <metric>=<value>"`

## Phase 3: Experiment Loop

Repeat until no pending ideas remain:

### 3a. Check Control
- Read `.research/control.json`
- If `paused: true`: update status to `paused`, sleep 10s, recheck
- If `skip_current: true`: skip to next idea, reset flag

### 3b. Pick Next Idea
- Read `.research/idea_pool.json`
- Find the highest-priority idea with `status: "pending"`
- If none: update status to `idle`, exit (Python will restart you if new ideas arrive)
- Claim it: set `status: "running"` in the idea pool
- Update activity with the idea you're working on

### 3c. Implement
- Read the idea description carefully
- Make the code changes needed to implement it
- Keep changes minimal and focused on the idea
- Git commit your changes: `git add -A && git commit -m "exp: <idea description short>"`

### 3d. Evaluate
- Run the evaluation command from `.research/evaluation.md`
- Extract the primary metric value from output
- Update status to `evaluating`

### 3e. Record & Decide
- Read current best value from `.research/results.tsv`
- If result is better than best:
  - `python .research/scripts/record.py --metric <m> --value <v> --status keep --desc "<idea>"`
  - Git commit
- If result is worse:
  - `python .research/scripts/record.py --metric <m> --value <v> --status discard --desc "<idea>"`
  - Rollback code: `bash .research/scripts/rollback.sh`
- Update idea in `idea_pool.json`: set `status: "done"`, add `result: {"metric_value": <v>, "verdict": "kept"|"discarded"}`

### 3f. Loop
- Go back to 3a

## Rules

- **Never** generate or modify ideas — that is the Idea Agent's job
- **Always** update `activity.json` before each action
- **Always** check `control.json` at the start of each loop iteration
- **One experiment at a time** — finish current before starting next
- Keep code changes small and reversible
```

**Step 2: Delete worker_prompt.md.j2**

```bash
rm src/open_researcher/templates/worker_prompt.md.j2
```

**Step 3: Commit**

```bash
git add src/open_researcher/templates/
git commit -m "feat: simplify experiment_program to serial runner, remove worker_prompt"
```

---

### Task 3: Simplify run_cmd.py — merge output streams

**Files:**
- Modify: `src/open_researcher/run_cmd.py:233-314` (do_run_multi function)
- Modify: `src/open_researcher/tui/app.py` (merge log methods)

**Step 1: Simplify app.py log methods**

Replace `append_idea_log` and `append_exp_log` with single `append_log`:

```python
def append_log(self, line: str) -> None:
    """Thread-safe: append a line to the unified log panel."""
    self.call_from_thread(self._do_append_log, line)

def _do_append_log(self, line: str) -> None:
    try:
        self.query_one("#agent-log", RichLog).write(line)
    except NoMatches:
        pass
```

Keep the old methods as aliases for backward compat in single mode:
```python
append_idea_log = append_log
append_exp_log = append_log
```

**Step 2: Update do_run_multi — unified output**

In `start_threads()`, both callbacks write to the same log file and same TUI panel:

```python
def start_threads():
    on_idea_output = _make_safe_output(app.append_log, research / "run.log")
    on_exp_output = _make_safe_output(app.append_log, research / "run.log")

    _launch_agent_thread(
        idea_agent, repo_path, on_idea_output, done_idea, exit_codes,
        "idea", program_file="idea_program.md",
    )
    _launch_exp_with_wait(
        exp_agent, repo_path, on_exp_output, done_exp, exit_codes, stop_exp,
    )
```

**Step 3: Update do_run for single mode**

Single mode already uses one log — just update to use `append_log`:

```python
def start_threads():
    nonlocal on_output
    on_output = _make_safe_output(app.append_log, research / "run.log")
    _launch_agent_thread(agent, repo_path, on_output, done, exit_codes, "agent")
```

**Step 4: Update action_view_log**

Always open `run.log` now (both modes write to same file):

```python
def action_view_log(self) -> None:
    log_path = str(self.research_dir / "run.log")
    self.push_screen(LogScreen(log_path))
```

**Step 5: Run tests**

Run: `python3 -m pytest tests/ -x -q`
Expected: All pass

**Step 6: Commit**

```bash
git add src/open_researcher/tui/app.py src/open_researcher/run_cmd.py
git commit -m "feat: merge dual agent outputs into single log stream"
```

---

### Task 4: Clean up dead code

**Files:**
- Modify: `src/open_researcher/tui/widgets.py` (remove WorkerStatusPanel, AgentPanel)
- Modify: `src/open_researcher/tui/app.py` (remove unused imports)
- Modify: `tests/test_tui.py` (remove dead tests)
- Modify: `src/open_researcher/tui/styles.css` (remove dead rules)

**Step 1: Remove dead widget classes**

From `widgets.py`, remove:
- `AgentPanel` class (lines 87-130)
- `WorkerStatusPanel` class (lines 179-203)

**Step 2: Remove dead imports from app.py**

Remove `WorkerStatusPanel` from imports. Remove `Horizontal` from textual imports (no longer needed).

**Step 3: Remove dead CSS rules**

Remove all rules for: `#agent-panels`, `#idea-agent-section`, `#exp-agent-section`, `#idea-status`, `#worker-status`, `#idea-log`, `#exp-log`, `.panel-title`

**Step 4: Remove dead tests**

Remove from `test_tui.py`:
- `test_worker_status_panel_update`
- `test_worker_status_panel_empty`
- `test_idea_pool_shows_gpu_info`
- `test_agent_panel_update`
- `test_agent_panel_no_activity`

Update import line to remove `AgentPanel`, `IdeaPoolPanel`.

**Step 5: Run lint + tests**

Run: `python3 -m ruff check src/ tests/ && python3 -m pytest tests/ -x -q`
Expected: All pass, no lint errors

**Step 6: Commit**

```bash
git add src/open_researcher/tui/ tests/test_tui.py
git commit -m "chore: remove dead WorkerStatusPanel, AgentPanel, and related code"
```

---

### Task 5: Final integration test + push

**Files:** None (verification only)

**Step 1: Full test suite**

Run: `python3 -m pytest tests/ -x -v`
Expected: All pass

**Step 2: Lint**

Run: `python3 -m ruff check src/ tests/`
Expected: All checks passed

**Step 3: Push**

```bash
git push
```
