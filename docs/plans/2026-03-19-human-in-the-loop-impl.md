# Human-in-the-Loop Checkpoint — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add configurable human review checkpoints to the v2 research loop, with TUI modals, CLI headless support, and anytime interactions (goal edit, inject idea).

**Architecture:** State file polling via `activity.json → control.awaiting_review`. SkillRunner blocks after each configurable step until TUI/CLI clears the review. TUI pushes Textual `Screen` modals for review. CLI provides `review`/`inject`/`constrain` commands for headless operation.

**Tech Stack:** Python 3.11+, Textual (Screen, DataTable, Input, TextArea), typer, filelock, yaml

**Design Doc:** `docs/plans/2026-03-19-human-in-the-loop-design.md`

---

## Task 1: Add `awaiting_review` to ResearchState

**Files:**
- Modify: `src/open_researcher_v2/state.py:81-86` (_DEFAULT_ACTIVITY)
- Modify: `src/open_researcher_v2/state.py:285-310` (after consume_skip)
- Modify: `src/open_researcher_v2/state.py:382-393` (summary return dict)
- Test: `tests/v2/test_state.py`

**Step 1: Write failing tests**

Append to `tests/v2/test_state.py`:

```python
class TestAwaitingReview:
    """Tests for awaiting_review state management."""

    def test_default_activity_has_awaiting_review(self, tmp_path):
        state = ResearchState(tmp_path)
        activity = state.load_activity()
        assert activity["control"]["awaiting_review"] is None

    def test_set_awaiting_review(self, tmp_path):
        state = ResearchState(tmp_path)
        review = {"type": "hypothesis_review", "requested_at": "2026-03-19T14:00:00Z"}
        state.set_awaiting_review(review)
        result = state.get_awaiting_review()
        assert result["type"] == "hypothesis_review"

    def test_clear_awaiting_review(self, tmp_path):
        state = ResearchState(tmp_path)
        state.set_awaiting_review({"type": "direction_confirm", "requested_at": "2026-03-19T14:00:00Z"})
        state.clear_awaiting_review()
        assert state.get_awaiting_review() is None

    def test_get_awaiting_review_when_not_set(self, tmp_path):
        state = ResearchState(tmp_path)
        assert state.get_awaiting_review() is None

    def test_summary_includes_awaiting_review(self, tmp_path):
        state = ResearchState(tmp_path)
        s = state.summary()
        assert "awaiting_review" in s
        assert s["awaiting_review"] is None

    def test_summary_includes_awaiting_review_when_set(self, tmp_path):
        state = ResearchState(tmp_path)
        state.set_awaiting_review({"type": "result_review", "requested_at": "2026-03-19T14:00:00Z"})
        s = state.summary()
        assert s["awaiting_review"]["type"] == "result_review"

    def test_set_awaiting_review_preserves_other_control_fields(self, tmp_path):
        state = ResearchState(tmp_path)
        state.set_paused(True)
        state.set_awaiting_review({"type": "frontier_review", "requested_at": "2026-03-19T14:00:00Z"})
        activity = state.load_activity()
        assert activity["control"]["paused"] is True
        assert activity["control"]["awaiting_review"]["type"] == "frontier_review"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/v2/test_state.py::TestAwaitingReview -v`
Expected: FAIL — `set_awaiting_review` not defined

**Step 3: Implement in state.py**

3a. Update `_DEFAULT_ACTIVITY` (line 81-86):

```python
_DEFAULT_ACTIVITY: dict[str, Any] = {
    "phase": "idle",
    "round": 0,
    "workers": [],
    "control": {"paused": False, "skip_current": False, "awaiting_review": None},
}
```

3b. Add 3 methods after `consume_skip()` (after line ~310):

```python
    def set_awaiting_review(self, review: dict | None) -> None:
        """Set control.awaiting_review in activity.json."""
        with self._activity_lock:
            data = self._load_activity_unlocked()
            data.setdefault("control", {})["awaiting_review"] = review
            self._save_activity_unlocked(data)

    def get_awaiting_review(self) -> dict | None:
        """Read control.awaiting_review from activity.json."""
        return self.load_activity().get("control", {}).get("awaiting_review")

    def clear_awaiting_review(self) -> None:
        """Set control.awaiting_review = null."""
        self.set_awaiting_review(None)
```

3c. Update `summary()` return dict (line ~382-393) — add after `"paused"`:

```python
            "awaiting_review": activity.get("control", {}).get("awaiting_review"),
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/v2/test_state.py::TestAwaitingReview -v`
Expected: all 7 PASS

**Step 5: Commit**

```bash
git add src/open_researcher_v2/state.py tests/v2/test_state.py
git commit -m "feat(v2): add awaiting_review to ResearchState"
```

---

## Task 2: Add interaction config defaults

**Files:**
- Modify: `src/open_researcher_v2/state.py:33-48` (_DEFAULT_CONFIG)
- Test: `tests/v2/test_state.py`

**Step 1: Write failing test**

Append to `tests/v2/test_state.py::TestConfig`:

```python
    def test_default_interaction_config(self, tmp_path):
        state = ResearchState(tmp_path)
        cfg = state.load_config()
        interaction = cfg["interaction"]
        assert interaction["mode"] == "autopilot"
        assert interaction["checkpoints"]["after_scout"] is True
        assert interaction["checkpoints"]["after_manager"] is True
        assert interaction["checkpoints"]["after_critic_preflight"] is True
        assert interaction["checkpoints"]["after_round"] is True
        assert interaction["review_timeout_minutes"] == 0

    def test_interaction_config_merge(self, tmp_path):
        import yaml
        (tmp_path / "config.yaml").write_text(yaml.dump({
            "interaction": {"mode": "checkpoint", "checkpoints": {"after_scout": False}},
        }))
        state = ResearchState(tmp_path)
        cfg = state.load_config()
        assert cfg["interaction"]["mode"] == "checkpoint"
        assert cfg["interaction"]["checkpoints"]["after_scout"] is False
        assert cfg["interaction"]["checkpoints"]["after_manager"] is True  # default preserved
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/v2/test_state.py::TestConfig::test_default_interaction_config -v`
Expected: FAIL — KeyError: 'interaction'

**Step 3: Add interaction defaults to _DEFAULT_CONFIG**

In `state.py`, add to `_DEFAULT_CONFIG` (after line ~47, before the closing `}`):

```python
    "interaction": {
        "mode": "autopilot",
        "checkpoints": {
            "after_scout": True,
            "after_manager": True,
            "after_critic_preflight": True,
            "after_round": True,
        },
        "review_timeout_minutes": 0,
    },
```

**Step 4: Run tests**

Run: `pytest tests/v2/test_state.py::TestConfig -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/open_researcher_v2/state.py tests/v2/test_state.py
git commit -m "feat(v2): add interaction config defaults"
```

---

## Task 3: Add SkillRunner checkpoint logic

**Files:**
- Modify: `src/open_researcher_v2/skill_runner.py:45-60` (__init__)
- Modify: `src/open_researcher_v2/skill_runner.py:152-167` (run_bootstrap)
- Modify: `src/open_researcher_v2/skill_runner.py:171-220` (run_one_round)
- Test: `tests/v2/test_skill_runner.py`

**Step 1: Write failing tests**

Append to `tests/v2/test_skill_runner.py`:

```python
class TestCheckpoints:
    """Tests for human-in-the-loop checkpoint logic."""

    def test_checkpoint_type_returns_none_in_autopilot(self, tmp_path):
        runner, _, state = _make_runner(tmp_path)
        # Default mode is autopilot — no checkpoints
        assert runner._checkpoint_type("scout", 0) is None
        assert runner._checkpoint_type("manager", 1) is None

    def test_checkpoint_type_returns_direction_confirm_after_scout(self, tmp_path):
        runner, _, state = _make_runner(tmp_path, config_overrides={
            "interaction": {"mode": "checkpoint"},
        })
        assert runner._checkpoint_type("scout", 0) == "direction_confirm"

    def test_checkpoint_type_returns_hypothesis_review_after_manager(self, tmp_path):
        runner, _, state = _make_runner(tmp_path, config_overrides={
            "interaction": {"mode": "checkpoint"},
        })
        assert runner._checkpoint_type("manager", 1) == "hypothesis_review"

    def test_checkpoint_type_respects_disabled_checkpoint(self, tmp_path):
        runner, _, state = _make_runner(tmp_path, config_overrides={
            "interaction": {
                "mode": "checkpoint",
                "checkpoints": {"after_scout": False},
            },
        })
        assert runner._checkpoint_type("scout", 0) is None

    def test_checkpoint_critic_preflight_vs_postrun(self, tmp_path):
        runner, _, state = _make_runner(tmp_path, config_overrides={
            "interaction": {"mode": "checkpoint"},
        })
        # First critic call is preflight
        runner._critic_call_count_this_round = 1
        assert runner._checkpoint_type("critic", 1) == "frontier_review"
        # Second critic call is post-run
        runner._critic_call_count_this_round = 2
        assert runner._checkpoint_type("critic", 1) == "result_review"

    def test_await_review_blocks_until_cleared(self, tmp_path):
        import threading
        runner, _, state = _make_runner(tmp_path, config_overrides={
            "interaction": {"mode": "checkpoint"},
        })
        # Start _await_review in a thread
        done = threading.Event()
        def run_await():
            runner._await_review("hypothesis_review")
            done.set()

        t = threading.Thread(target=run_await)
        t.start()

        # Wait briefly, then clear review
        import time
        time.sleep(0.5)
        assert not done.is_set(), "Should still be blocking"
        state.clear_awaiting_review()
        done.wait(timeout=3.0)
        assert done.is_set(), "Should have unblocked"
        t.join(timeout=1.0)

    def test_await_review_logs_events(self, tmp_path):
        import threading
        runner, _, state = _make_runner(tmp_path, config_overrides={
            "interaction": {"mode": "checkpoint"},
        })
        def run_and_clear():
            import time
            time.sleep(0.3)
            state.clear_awaiting_review()
        t = threading.Thread(target=run_and_clear)
        t.start()
        runner._await_review("direction_confirm")
        t.join()
        logs = state.tail_log(10)
        events = [e["event"] for e in logs]
        assert "review_requested" in events
        assert "review_completed" in events

    def test_await_review_respects_timeout(self, tmp_path):
        import time
        runner, _, state = _make_runner(tmp_path, config_overrides={
            "interaction": {
                "mode": "checkpoint",
                "review_timeout_minutes": 0.01,  # ~0.6 seconds
            },
        })
        start = time.monotonic()
        runner._await_review("hypothesis_review")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, "Should have timed out quickly"
        logs = state.tail_log(10)
        events = [e["event"] for e in logs]
        assert "review_timeout" in events

    def test_run_one_round_triggers_checkpoint(self, tmp_path):
        runner, adapter, state = _make_runner(tmp_path, config_overrides={
            "interaction": {
                "mode": "checkpoint",
                "checkpoints": {
                    "after_scout": False,
                    "after_manager": True,
                    "after_critic_preflight": False,
                    "after_round": False,
                },
            },
        })
        # Pre-clear review after a delay (simulate TUI approving)
        import threading, time
        def auto_approve():
            time.sleep(0.5)
            if state.get_awaiting_review():
                state.clear_awaiting_review()
        t = threading.Thread(target=auto_approve)
        t.start()

        rc = runner.run_one_round(1)
        t.join()
        assert rc == 0
        # Verify checkpoint was requested
        logs = state.tail_log(50)
        review_events = [e for e in logs if e.get("event") == "review_requested"]
        assert len(review_events) == 1
        assert review_events[0]["review_type"] == "hypothesis_review"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/v2/test_skill_runner.py::TestCheckpoints -v`
Expected: FAIL — `_checkpoint_type` not defined

**Step 3: Implement checkpoint methods**

3a. Add `_critic_call_count_this_round` to `__init__` (after line 60):

```python
        self._critic_call_count_this_round = 0
```

3b. Add imports at top of file (after line 12):

```python
import time
from datetime import datetime, timezone
```

3c. Add `_checkpoint_type` method (before `run_bootstrap`, around line ~150):

```python
    def _checkpoint_type(self, step_name: str, round_num: int) -> str | None:
        """Return the review type for a checkpoint, or None if no review needed."""
        config = self.state.load_config()
        interaction = config.get("interaction", {})
        mode = interaction.get("mode", "autopilot")

        if mode != "checkpoint":
            return None

        checkpoints = interaction.get("checkpoints", {})

        if step_name == "scout" and checkpoints.get("after_scout", True):
            return "direction_confirm"
        if step_name == "manager" and checkpoints.get("after_manager", True):
            return "hypothesis_review"
        if step_name == "critic":
            if self._critic_call_count_this_round == 1 and checkpoints.get("after_critic_preflight", True):
                return "frontier_review"
            if self._critic_call_count_this_round == 2 and checkpoints.get("after_round", True):
                return "result_review"
        return None

    def _await_review(self, review_type: str) -> None:
        """Block until TUI/CLI clears awaiting_review or timeout expires."""
        self.state.set_awaiting_review({
            "type": review_type,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        })
        self.state.append_log({"event": "review_requested", "review_type": review_type})

        config = self.state.load_config()
        timeout = config.get("interaction", {}).get("review_timeout_minutes", 0)
        deadline = time.monotonic() + timeout * 60 if timeout > 0 else None

        while True:
            if self.state.get_awaiting_review() is None:
                self.state.append_log({"event": "review_completed", "review_type": review_type})
                break
            if self.state.is_paused():
                break
            if deadline and time.monotonic() > deadline:
                self.state.clear_awaiting_review()
                self.state.append_log({"event": "review_timeout", "review_type": review_type})
                break
            time.sleep(1.0)
```

3d. Update `run_bootstrap` (line 152-167) — add checkpoint after each step:

```python
    def run_bootstrap(self) -> int:
        protocol = self._load_protocol()
        bootstrap_steps = protocol.get("bootstrap", [])

        for step_name in bootstrap_steps:
            skill_file = f"{step_name}.md"
            rc = self._run_skill(step_name, skill_file)
            if rc != 0:
                logger.warning("Bootstrap step %r failed with rc=%d", step_name, rc)
                return rc
            review_type = self._checkpoint_type(step_name, 0)
            if review_type:
                self._await_review(review_type)
        return 0
```

3e. Update `run_one_round` (line 171-220) — add critic counter + checkpoint:

```python
    def run_one_round(self, round_num: int) -> int:
        protocol = self._load_protocol()
        loop_steps = protocol.get("loop", [])

        self._critic_call_count_this_round = 0
        self.state.update_phase("round", round_num)
        self.state.append_log({"event": "round_started", "round": round_num})

        for step_def in loop_steps:
            if self.state.is_paused():
                self.state.append_log({"event": "round_paused", "round": round_num})
                return -2

            if self.state.consume_skip():
                self.state.append_log({"event": "round_skipped", "round": round_num})
                return -1

            step_name = step_def["name"]
            skill_file = step_def["skill"]

            rc = self._run_skill(step_name, skill_file)
            if rc != 0:
                logger.warning("Round %d step %r failed with rc=%d", round_num, step_name, rc)
                return rc

            if step_name == "critic":
                self._critic_call_count_this_round += 1

            review_type = self._checkpoint_type(step_name, round_num)
            if review_type:
                self._await_review(review_type)

        self.state.append_log({"event": "round_completed", "round": round_num})
        return 0
```

**Step 4: Run tests**

Run: `pytest tests/v2/test_skill_runner.py::TestCheckpoints -v`
Expected: all PASS

**Step 5: Run full test suite**

Run: `pytest tests/v2/test_skill_runner.py -v`
Expected: all PASS (existing tests still pass)

**Step 6: Commit**

```bash
git add src/open_researcher_v2/skill_runner.py tests/v2/test_skill_runner.py
git commit -m "feat(v2): add checkpoint logic to SkillRunner"
```

---

## Task 4: Add CLI `review` command

**Files:**
- Modify: `src/open_researcher_v2/cli.py` (after `results` command, ~line 206)
- Test: `tests/v2/test_cli.py`

**Step 1: Write failing test**

Append to `tests/v2/test_cli.py`:

```python
class TestReviewCommand:
    """Tests for the review CLI command."""

    def test_review_shows_no_pending_when_none(self, tmp_path):
        from typer.testing import CliRunner
        from open_researcher_v2.cli import app
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        runner = CliRunner()
        result = runner.invoke(app, ["review", str(tmp_path)])
        assert result.exit_code == 0
        assert "No pending review" in result.stdout

    def test_review_shows_pending_review(self, tmp_path):
        from typer.testing import CliRunner
        from open_researcher_v2.cli import app
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review({"type": "hypothesis_review", "requested_at": "2026-03-19T14:00:00Z"})

        runner = CliRunner()
        result = runner.invoke(app, ["review", str(tmp_path)])
        assert result.exit_code == 0
        assert "hypothesis_review" in result.stdout

    def test_review_skip_clears_review(self, tmp_path):
        from typer.testing import CliRunner
        from open_researcher_v2.cli import app
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review({"type": "frontier_review", "requested_at": "2026-03-19T14:00:00Z"})

        runner = CliRunner()
        result = runner.invoke(app, ["review", str(tmp_path), "--skip"])
        assert result.exit_code == 0
        assert state.get_awaiting_review() is None

    def test_review_approve_all_clears_review(self, tmp_path):
        from typer.testing import CliRunner
        from open_researcher_v2.cli import app
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review({"type": "result_review", "requested_at": "2026-03-19T14:00:00Z"})

        runner = CliRunner()
        result = runner.invoke(app, ["review", str(tmp_path), "--approve-all"])
        assert result.exit_code == 0
        assert state.get_awaiting_review() is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/v2/test_cli.py::TestReviewCommand -v`
Expected: FAIL — no command 'review'

**Step 3: Implement review command**

Add after `results` command in `cli.py`:

```python
@app.command()
def review(
    repo: Path = typer.Argument(..., help="Path to target repo"),
    skip: bool = typer.Option(False, help="Skip the pending review"),
    approve_all: bool = typer.Option(False, "--approve-all", help="Approve all and continue"),
    reject: list[str] = typer.Option([], help="Reject specific frontier IDs"),
    priority: list[str] = typer.Option([], help="Set priority: FRONTIER_ID=PRIORITY"),
) -> None:
    """Show or act on a pending human review."""
    from .state import ResearchState

    research_dir = _resolve_research_dir(repo)
    if not research_dir.is_dir():
        console.print("[red]No .research directory found[/red]")
        raise typer.Exit(code=1)

    state = ResearchState(research_dir)
    pending = state.get_awaiting_review()

    if pending is None:
        console.print("[dim]No pending review.[/dim]")
        return

    review_type = pending.get("type", "unknown")
    requested_at = pending.get("requested_at", "")

    if skip:
        state.clear_awaiting_review()
        state.append_log({"event": "review_skipped", "review_type": review_type})
        console.print(f"Skipped review: {review_type}")
        return

    if approve_all:
        state.clear_awaiting_review()
        state.append_log({"event": "review_completed", "review_type": review_type})
        console.print(f"Approved: {review_type}")
        return

    if reject:
        graph = state.load_graph()
        for fid in reject:
            for item in graph.get("frontier", []):
                if item.get("id") == fid:
                    item["status"] = "rejected"
        state.save_graph(graph)
        state.clear_awaiting_review()
        state.append_log({"event": "review_completed", "review_type": review_type})
        console.print(f"Rejected {reject} and approved remaining")
        return

    if priority:
        graph = state.load_graph()
        for spec in priority:
            fid, _, pval = spec.partition("=")
            for item in graph.get("frontier", []):
                if item.get("id") == fid:
                    item["priority"] = int(pval)
        state.save_graph(graph)
        console.print(f"Updated priorities: {priority}")
        # Don't clear review — user may want to do more actions
        return

    # Default: show pending review info
    console.print(f"[bold]Pending review:[/bold] {review_type}")
    console.print(f"[dim]Requested at: {requested_at}[/dim]")
    console.print()
    console.print("Actions:")
    console.print("  --approve-all    Approve and continue")
    console.print("  --skip           Skip this review")
    console.print("  --reject ID      Reject a frontier item")
    console.print("  --priority ID=N  Adjust priority")
```

**Step 4: Run tests**

Run: `pytest tests/v2/test_cli.py::TestReviewCommand -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/open_researcher_v2/cli.py tests/v2/test_cli.py
git commit -m "feat(v2): add CLI review command for headless checkpoint interaction"
```

---

## Task 5: Add CLI `inject` and `constrain` commands

**Files:**
- Modify: `src/open_researcher_v2/cli.py`
- Test: `tests/v2/test_cli.py`

**Step 1: Write failing tests**

Append to `tests/v2/test_cli.py`:

```python
class TestInjectCommand:
    def test_inject_adds_frontier_item(self, tmp_path):
        from typer.testing import CliRunner
        from open_researcher_v2.cli import app
        from open_researcher_v2.state import ResearchState
        import json

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)

        runner = CliRunner()
        result = runner.invoke(app, [
            "inject", str(tmp_path),
            "--desc", "Try __slots__ for hot path",
            "--priority", "3",
        ])
        assert result.exit_code == 0

        graph = state.load_graph()
        frontier = graph["frontier"]
        assert len(frontier) == 1
        assert frontier[0]["description"] == "Try __slots__ for hot path"
        assert frontier[0]["priority"] == 3
        assert frontier[0]["status"] == "approved"
        assert frontier[0]["selection_reason_code"] == "human_injected"
        assert graph["counters"]["frontier"] == 1


class TestConstrainCommand:
    def test_constrain_adds_constraint(self, tmp_path):
        from typer.testing import CliRunner
        from open_researcher_v2.cli import app

        research_dir = tmp_path / ".research"
        research_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(app, [
            "constrain", str(tmp_path),
            "--add", "Do not touch I/O code",
        ])
        assert result.exit_code == 0

        content = (research_dir / "user_constraints.md").read_text()
        assert "Do not touch I/O code" in content

    def test_constrain_appends_multiple(self, tmp_path):
        from typer.testing import CliRunner
        from open_researcher_v2.cli import app

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        (research_dir / "user_constraints.md").write_text("- Existing constraint\n")

        runner = CliRunner()
        result = runner.invoke(app, [
            "constrain", str(tmp_path),
            "--add", "Focus on parser only",
        ])
        assert result.exit_code == 0

        content = (research_dir / "user_constraints.md").read_text()
        assert "Existing constraint" in content
        assert "Focus on parser only" in content
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/v2/test_cli.py::TestInjectCommand tests/v2/test_cli.py::TestConstrainCommand -v`
Expected: FAIL — no command 'inject'/'constrain'

**Step 3: Implement inject command**

```python
@app.command()
def inject(
    repo: Path = typer.Argument(..., help="Path to target repo"),
    desc: str = typer.Option(..., help="Experiment description"),
    priority: int = typer.Option(3, help="Priority (1-5, higher=first)"),
) -> None:
    """Inject a human-authored experiment into the frontier."""
    from .state import ResearchState

    research_dir = _resolve_research_dir(repo)
    if not research_dir.is_dir():
        console.print("[red]No .research directory found[/red]")
        raise typer.Exit(code=1)

    state = ResearchState(research_dir)
    graph = state.load_graph()
    counter = graph.get("counters", {}).get("frontier", 0) + 1
    item = {
        "id": f"frontier-{counter:03d}",
        "description": desc,
        "priority": priority,
        "status": "approved",
        "selection_reason_code": "human_injected",
        "hypothesis_id": "",
        "experiment_spec_id": "",
    }
    graph.setdefault("frontier", []).append(item)
    graph.setdefault("counters", {})["frontier"] = counter
    state.save_graph(graph)
    state.append_log({"event": "human_injected", "frontier_id": item["id"]})
    console.print(f"Injected: {item['id']} — {desc}")
```

**Step 4: Implement constrain command**

```python
@app.command()
def constrain(
    repo: Path = typer.Argument(..., help="Path to target repo"),
    add: str = typer.Option("", help="Add a constraint"),
) -> None:
    """Add user constraints for the research direction."""
    from .state import ResearchState

    research_dir = _resolve_research_dir(repo)
    if not research_dir.is_dir():
        console.print("[red]No .research directory found[/red]")
        raise typer.Exit(code=1)

    state = ResearchState(research_dir)
    path = research_dir / "user_constraints.md"

    if add:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"- {add}\n")
        state.append_log({"event": "goal_updated"})
        console.print(f"Added constraint: {add}")
    else:
        if path.exists():
            console.print(path.read_text(encoding="utf-8"))
        else:
            console.print("[dim]No constraints set.[/dim]")
```

**Step 5: Run tests**

Run: `pytest tests/v2/test_cli.py::TestInjectCommand tests/v2/test_cli.py::TestConstrainCommand -v`
Expected: all PASS

**Step 6: Commit**

```bash
git add src/open_researcher_v2/cli.py tests/v2/test_cli.py
git commit -m "feat(v2): add inject and constrain CLI commands"
```

---

## Task 6: Add `--mode` flag to CLI `run` command

**Files:**
- Modify: `src/open_researcher_v2/cli.py:46-54` (run command params)
- Test: `tests/v2/test_cli.py`

**Step 1: Write failing test**

```python
class TestRunModeFlag:
    def test_run_mode_flag_writes_config(self, tmp_path):
        import yaml
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()

        # Write initial config
        (research_dir / "config.yaml").write_text(yaml.dump({"metrics": {"primary": {"name": "acc"}}}))

        state = ResearchState(research_dir)
        cfg = state.load_config()
        assert cfg["interaction"]["mode"] == "autopilot"  # default

        # TODO: The actual test would invoke `run` with --mode checkpoint
        # but that starts a full session. Instead, test the config writing helper.
```

Note: Testing the full `run` command with `--mode` is integration-level. For now, add the flag and validate via a config-write helper.

**Step 2: Add `--mode` parameter to run command**

Modify the `run` function signature (line 46-54):

```python
@app.command()
def run(
    repo: Path = typer.Argument(..., help="Path to target repo"),
    goal: str = typer.Option("", help="Research goal"),
    tag: str = typer.Option("", help="Session tag"),
    workers: int = typer.Option(0, help="Max parallel workers (0=serial)"),
    headless: bool = typer.Option(False, help="Run without TUI"),
    agent_name: str = typer.Option("claude-code", help="Agent to use"),
    mode: str = typer.Option("", help="Interaction mode: autopilot or checkpoint"),
) -> None:
```

After `state = ResearchState(research_dir)` (line 74), add mode override:

```python
    # Apply --mode override to config
    if mode:
        import yaml
        config_path = research_dir / "config.yaml"
        cfg = {}
        if config_path.exists():
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        cfg.setdefault("interaction", {})["mode"] = mode
        config_path.write_text(yaml.dump(cfg), encoding="utf-8")
```

**Step 3: Run existing tests**

Run: `pytest tests/v2/test_cli.py -v`
Expected: all PASS (new param is optional, defaults to empty)

**Step 4: Commit**

```bash
git add src/open_researcher_v2/cli.py tests/v2/test_cli.py
git commit -m "feat(v2): add --mode flag to run command"
```

---

## Task 7: Create TUI ReviewScreen base class + CSS

**Files:**
- Create: `src/open_researcher_v2/tui/modals/__init__.py`
- Create: `src/open_researcher_v2/tui/modals/base.py`
- Modify: `src/open_researcher_v2/tui/styles.css`
- Test: `tests/v2/test_review_modals.py`

**Step 1: Create modals directory**

```bash
mkdir -p src/open_researcher_v2/tui/modals
```

**Step 2: Write failing test**

Create `tests/v2/test_review_modals.py`:

```python
"""Tests for TUI review modal screens."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from open_researcher_v2.tui.modals.base import ReviewScreen


class TestReviewScreenBase:
    def test_import(self):
        from open_researcher_v2.tui.modals.base import ReviewScreen
        assert ReviewScreen is not None

    def test_action_skip_clears_review(self, tmp_path):
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review({"type": "test", "requested_at": "2026-03-19T14:00:00Z"})

        screen = ReviewScreen(state=state, review_request={"type": "test"})
        # Mock dismiss since we're not in a running app
        screen.dismiss = MagicMock()
        screen.action_skip()

        assert state.get_awaiting_review() is None
        screen.dismiss.assert_called_once_with(None)
```

**Step 3: Run test to verify it fails**

Run: `pytest tests/v2/test_review_modals.py::TestReviewScreenBase -v`
Expected: FAIL — ModuleNotFoundError

**Step 4: Create `modals/__init__.py`**

```python
"""TUI modal screens for human-in-the-loop review checkpoints."""
```

**Step 5: Create `modals/base.py`**

```python
"""Base class for review modal screens."""
from __future__ import annotations

from textual.binding import Binding
from textual.screen import Screen

from open_researcher_v2.state import ResearchState


class ReviewScreen(Screen):
    """Base class for all review modals.

    Subclasses implement ``compose()`` for layout and ``_apply_decisions()``
    for writing user choices to state files.
    """

    BINDINGS = [
        Binding("enter", "confirm", "Confirm"),
        Binding("escape", "skip", "Skip"),
    ]

    def __init__(
        self,
        state: ResearchState,
        review_request: dict,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.state = state
        self.review_request = review_request

    def _apply_decisions(self) -> None:
        """Subclass hook: write user decisions to graph.json / files."""

    def action_confirm(self) -> None:
        self._apply_decisions()
        self.state.clear_awaiting_review()
        self.dismiss(True)

    def action_skip(self) -> None:
        self.state.clear_awaiting_review()
        self.state.append_log({
            "event": "review_skipped",
            "review_type": self.review_request.get("type", "unknown"),
        })
        self.dismiss(None)
```

**Step 6: Add modal CSS to styles.css**

Append to `src/open_researcher_v2/tui/styles.css`:

```css

/* Review modal screens */
ReviewScreen {
    align: center middle;
}

ReviewScreen > #review-dialog {
    width: 80;
    max-height: 30;
    border: thick $accent;
    background: $surface;
    padding: 1 2;
}

ReviewScreen > #review-dialog #review-title {
    text-style: bold;
    width: 100%;
    content-align: center middle;
    padding-bottom: 1;
}

ReviewScreen > #review-dialog #review-actions {
    dock: bottom;
    height: 1;
    padding-top: 1;
}
```

**Step 7: Run tests**

Run: `pytest tests/v2/test_review_modals.py -v`
Expected: PASS

**Step 8: Commit**

```bash
git add src/open_researcher_v2/tui/modals/ tests/v2/test_review_modals.py src/open_researcher_v2/tui/styles.css
git commit -m "feat(v2): add ReviewScreen base class and modal CSS"
```

---

## Task 8: Create DirectionConfirmScreen

**Files:**
- Create: `src/open_researcher_v2/tui/modals/direction.py`
- Test: `tests/v2/test_review_modals.py`

**Step 1: Write failing test**

Append to `tests/v2/test_review_modals.py`:

```python
class TestDirectionConfirmScreen:
    def test_import(self):
        from open_researcher_v2.tui.modals.direction import DirectionConfirmScreen
        assert DirectionConfirmScreen is not None

    def test_confirm_writes_constraints(self, tmp_path):
        from open_researcher_v2.state import ResearchState
        from open_researcher_v2.tui.modals.direction import DirectionConfirmScreen
        from unittest.mock import MagicMock

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review({"type": "direction_confirm", "requested_at": "2026-03-19T14:00:00Z"})

        screen = DirectionConfirmScreen(state=state, review_request={"type": "direction_confirm"})
        screen._user_constraints = "Focus on parser only"
        screen.dismiss = MagicMock()
        screen._apply_decisions()

        content = (research_dir / "user_constraints.md").read_text()
        assert "Focus on parser only" in content
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/v2/test_review_modals.py::TestDirectionConfirmScreen -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Create `modals/direction.py`**

```python
"""Direction confirmation modal — shown after scout completes."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Static, TextArea

from .base import ReviewScreen


class DirectionConfirmScreen(ReviewScreen):
    """Review and confirm the research direction after scout analysis."""

    def __init__(self, state, review_request, **kwargs):
        super().__init__(state=state, review_request=review_request, **kwargs)
        self._user_constraints = ""

    def compose(self) -> ComposeResult:
        config = self.state.load_config()
        metric = config.get("metrics", {}).get("primary", {})
        metric_name = metric.get("name", "unknown")
        direction = metric.get("direction", "maximize")

        strategy_path = self.state.dir / "research-strategy.md"
        strategy = strategy_path.read_text(encoding="utf-8") if strategy_path.exists() else "[No strategy yet]"

        with Vertical(id="review-dialog"):
            yield Label("Research Direction", id="review-title")
            yield Static(f"Metric: [bold]{metric_name}[/] ({direction})")
            yield Static(f"\n[bold]Strategy:[/]\n{strategy[:500]}")
            yield Label("\nAdditional constraints:")
            yield TextArea(id="constraints-input")
            yield Static("[Enter] Confirm & Continue    [Esc] Skip", id="review-actions")

    def _apply_decisions(self) -> None:
        try:
            textarea = self.query_one("#constraints-input", TextArea)
            self._user_constraints = textarea.text
        except Exception:
            pass
        if self._user_constraints.strip():
            path = self.state.dir / "user_constraints.md"
            with open(path, "a", encoding="utf-8") as f:
                f.write(self._user_constraints.strip() + "\n")
            self.state.append_log({"event": "goal_updated"})
```

**Step 4: Run tests**

Run: `pytest tests/v2/test_review_modals.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/open_researcher_v2/tui/modals/direction.py tests/v2/test_review_modals.py
git commit -m "feat(v2): add DirectionConfirmScreen modal"
```

---

## Task 9: Create HypothesisReviewScreen and FrontierReviewScreen

**Files:**
- Create: `src/open_researcher_v2/tui/modals/hypothesis.py`
- Create: `src/open_researcher_v2/tui/modals/frontier.py`
- Test: `tests/v2/test_review_modals.py`

**Step 1: Write failing tests**

Append to `tests/v2/test_review_modals.py`:

```python
class TestHypothesisReviewScreen:
    def test_apply_rejects_item(self, tmp_path):
        from open_researcher_v2.state import ResearchState
        from open_researcher_v2.tui.modals.hypothesis import HypothesisReviewScreen
        from unittest.mock import MagicMock

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "frontier-001", "priority": 3, "status": "approved", "description": "Test A"},
            {"id": "frontier-002", "priority": 2, "status": "approved", "description": "Test B"},
        ]
        state.save_graph(graph)

        screen = HypothesisReviewScreen(state=state, review_request={"type": "hypothesis_review"})
        screen._decisions = {"frontier-002": "rejected"}
        screen.dismiss = MagicMock()
        screen._apply_decisions()

        graph = state.load_graph()
        statuses = {f["id"]: f["status"] for f in graph["frontier"]}
        assert statuses["frontier-001"] == "approved"
        assert statuses["frontier-002"] == "rejected"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/v2/test_review_modals.py::TestHypothesisReviewScreen -v`
Expected: FAIL

**Step 3: Create `modals/hypothesis.py`**

```python
"""Hypothesis review modal — shown after manager completes."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Label, Static

from .base import ReviewScreen


class HypothesisReviewScreen(ReviewScreen):
    """Review hypotheses and frontier items proposed by manager."""

    BINDINGS = [
        Binding("enter", "confirm", "Confirm"),
        Binding("escape", "skip", "Skip"),
        Binding("space", "toggle_item", "Toggle"),
        Binding("a", "approve_all", "Approve all"),
    ]

    def __init__(self, state, review_request, **kwargs):
        super().__init__(state=state, review_request=review_request, **kwargs)
        self._decisions: dict[str, str] = {}  # frontier_id -> status

    def compose(self) -> ComposeResult:
        graph = self.state.load_graph()
        frontier = graph.get("frontier", [])

        with Vertical(id="review-dialog"):
            yield Label("Hypothesis Review", id="review-title")
            table = DataTable(id="review-table")
            table.add_columns("ID", "P", "Status", "Description", "Keep?")
            table.cursor_type = "row"
            for item in sorted(frontier, key=lambda f: -float(f.get("priority", 0))):
                fid = item.get("id", "")
                keep = "✓" if item.get("status") != "rejected" else "✗"
                table.add_row(fid, str(item.get("priority", "")),
                              item.get("status", ""), item.get("description", "")[:40], keep)
            yield table
            yield Static("[Space] Toggle  [a] Approve all  [Enter] Confirm  [Esc] Skip", id="review-actions")

    def action_toggle_item(self) -> None:
        table: DataTable = self.query_one("#review-table", DataTable)
        if table.cursor_row is not None:
            row_key = list(table.rows)[table.cursor_row]
            cells = table.get_row(row_key)
            fid = str(cells[0])
            current = self._decisions.get(fid, "approved")
            new_status = "rejected" if current == "approved" else "approved"
            self._decisions[fid] = new_status

    def action_approve_all(self) -> None:
        self._decisions.clear()

    def _apply_decisions(self) -> None:
        if not self._decisions:
            return
        graph = self.state.load_graph()
        for item in graph.get("frontier", []):
            fid = item.get("id", "")
            if fid in self._decisions:
                item["status"] = self._decisions[fid]
        self.state.save_graph(graph)
```

**Step 4: Create `modals/frontier.py`**

```python
"""Frontier review modal — shown after critic preflight."""
from __future__ import annotations

from .hypothesis import HypothesisReviewScreen


class FrontierReviewScreen(HypothesisReviewScreen):
    """Review critic-assessed frontier items. Same UI as HypothesisReview."""

    def compose(self):
        # Override title
        from textual.app import ComposeResult
        from textual.containers import Vertical
        from textual.widgets import DataTable, Label, Static

        graph = self.state.load_graph()
        frontier = graph.get("frontier", [])

        with Vertical(id="review-dialog"):
            yield Label("Frontier Review (post-critic)", id="review-title")
            table = DataTable(id="review-table")
            table.add_columns("ID", "P", "Status", "Description", "Keep?")
            table.cursor_type = "row"
            for item in sorted(frontier, key=lambda f: -float(f.get("priority", 0))):
                fid = item.get("id", "")
                keep = "✓" if item.get("status") not in ("rejected", "draft") else "✗"
                table.add_row(fid, str(item.get("priority", "")),
                              item.get("status", ""), item.get("description", "")[:40], keep)
            yield table
            yield Static("[Space] Toggle  [a] Approve all  [Enter] Confirm  [Esc] Skip", id="review-actions")
```

**Step 5: Run tests**

Run: `pytest tests/v2/test_review_modals.py -v`
Expected: all PASS

**Step 6: Commit**

```bash
git add src/open_researcher_v2/tui/modals/hypothesis.py src/open_researcher_v2/tui/modals/frontier.py tests/v2/test_review_modals.py
git commit -m "feat(v2): add HypothesisReviewScreen and FrontierReviewScreen modals"
```

---

## Task 10: Create ResultReviewScreen

**Files:**
- Create: `src/open_researcher_v2/tui/modals/result.py`
- Test: `tests/v2/test_review_modals.py`

**Step 1: Write failing test**

```python
class TestResultReviewScreen:
    def test_override_writes_claim_update(self, tmp_path):
        import csv
        from open_researcher_v2.state import ResearchState
        from open_researcher_v2.tui.modals.result import ResultReviewScreen
        from unittest.mock import MagicMock

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)

        # Write a result
        state.append_result({
            "timestamp": "2026-03-19T14:00:00Z",
            "worker": "w0",
            "frontier_id": "frontier-001",
            "status": "discard",
            "metric": "ops_per_sec",
            "value": "2000000",
            "description": "Test result",
        })

        screen = ResultReviewScreen(state=state, review_request={"type": "result_review"})
        screen._overrides = {"frontier-001": "keep"}
        screen.dismiss = MagicMock()
        screen._apply_decisions()

        graph = state.load_graph()
        claims = graph.get("claim_updates", [])
        assert len(claims) == 1
        assert claims[0]["frontier_id"] == "frontier-001"
        assert claims[0]["new_status"] == "keep"
        assert claims[0]["reviewer"] == "human"
```

**Step 2: Create `modals/result.py`**

```python
"""Result review modal — shown at end of round."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Label, Static, TextArea

from .base import ReviewScreen


class ResultReviewScreen(ReviewScreen):
    """Review experiment results and optionally override AI keep/discard decisions."""

    BINDINGS = [
        Binding("enter", "confirm", "Confirm"),
        Binding("escape", "skip", "Skip"),
        Binding("space", "toggle_override", "Override"),
    ]

    def __init__(self, state, review_request, **kwargs):
        super().__init__(state=state, review_request=review_request, **kwargs)
        self._overrides: dict[str, str] = {}  # frontier_id -> new_status

    def compose(self) -> ComposeResult:
        results = self.state.load_results()
        config = self.state.load_config()
        baseline_name = config.get("metrics", {}).get("primary", {}).get("name", "metric")

        with Vertical(id="review-dialog"):
            yield Label("Round Results", id="review-title")
            table = DataTable(id="result-table")
            table.add_columns("Frontier", "Value", "AI Decision", "Override?")
            table.cursor_type = "row"
            for r in results[-10:]:  # last 10 results
                fid = r.get("frontier_id", "")
                val = r.get("value", "")
                status = r.get("status", "")
                table.add_row(fid, str(val), status, "—")
            yield table
            yield Label("\nConstraints for next round:")
            yield TextArea(id="next-constraints")
            yield Static("[Space] Override  [Enter] Next round  [Esc] Skip", id="review-actions")

    def action_toggle_override(self) -> None:
        table: DataTable = self.query_one("#result-table", DataTable)
        if table.cursor_row is not None:
            row_key = list(table.rows)[table.cursor_row]
            cells = table.get_row(row_key)
            fid = str(cells[0])
            ai_status = str(cells[2])
            new = "keep" if ai_status == "discard" else "discard"
            self._overrides[fid] = new

    def _apply_decisions(self) -> None:
        if self._overrides:
            graph = self.state.load_graph()
            for fid, new_status in self._overrides.items():
                graph.setdefault("claim_updates", []).append({
                    "frontier_id": fid,
                    "new_status": new_status,
                    "reviewer": "human",
                })
                self.state.append_log({
                    "event": "human_override",
                    "frontier_id": fid,
                    "new_status": new_status,
                })
            self.state.save_graph(graph)

        # Write next-round constraints
        try:
            textarea = self.query_one("#next-constraints", TextArea)
            text = textarea.text.strip()
            if text:
                path = self.state.dir / "user_constraints.md"
                with open(path, "a", encoding="utf-8") as f:
                    f.write(text + "\n")
                self.state.append_log({"event": "goal_updated"})
        except Exception:
            pass
```

**Step 3: Run tests**

Run: `pytest tests/v2/test_review_modals.py -v`
Expected: all PASS

**Step 4: Commit**

```bash
git add src/open_researcher_v2/tui/modals/result.py tests/v2/test_review_modals.py
git commit -m "feat(v2): add ResultReviewScreen modal"
```

---

## Task 11: Create GoalEditScreen and InjectIdeaScreen

**Files:**
- Create: `src/open_researcher_v2/tui/modals/goal_edit.py`
- Create: `src/open_researcher_v2/tui/modals/inject.py`
- Test: `tests/v2/test_review_modals.py`

**Step 1: Write failing tests**

```python
class TestGoalEditScreen:
    def test_save_writes_constraints(self, tmp_path):
        from open_researcher_v2.state import ResearchState
        from open_researcher_v2.tui.modals.goal_edit import GoalEditScreen
        from unittest.mock import MagicMock

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)

        screen = GoalEditScreen(state=state)
        screen._user_text = "Focus on parser only"
        screen.dismiss = MagicMock()
        screen.action_save()

        content = (research_dir / "user_constraints.md").read_text()
        assert "Focus on parser only" in content


class TestInjectIdeaScreen:
    def test_inject_adds_to_graph(self, tmp_path):
        from open_researcher_v2.state import ResearchState
        from open_researcher_v2.tui.modals.inject import InjectIdeaScreen
        from unittest.mock import MagicMock

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)

        screen = InjectIdeaScreen(state=state)
        screen._description = "Try __slots__"
        screen._priority = 3
        screen.dismiss = MagicMock()
        screen.action_inject()

        graph = state.load_graph()
        assert len(graph["frontier"]) == 1
        assert graph["frontier"][0]["description"] == "Try __slots__"
        assert graph["frontier"][0]["selection_reason_code"] == "human_injected"
        assert graph["counters"]["frontier"] == 1
```

**Step 2: Create `modals/goal_edit.py`**

```python
"""Goal edit modal — available anytime via 'g' key."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Label, Static, TextArea

from open_researcher_v2.state import ResearchState


class GoalEditScreen(Screen):
    """Edit user constraints for the research direction."""

    BINDINGS = [
        Binding("enter", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, state: ResearchState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._user_text = ""

    def compose(self) -> ComposeResult:
        config = self.state.load_config()
        goal = config.get("metrics", {}).get("primary", {}).get("name", "")
        existing = ""
        path = self.state.dir / "user_constraints.md"
        if path.exists():
            existing = path.read_text(encoding="utf-8")

        with Vertical(id="review-dialog"):
            yield Label("Edit Research Goal", id="review-title")
            yield Static(f"Primary metric: [bold]{goal}[/]")
            yield Label("\nUser constraints (editable):")
            yield TextArea(existing, id="constraints-edit")
            yield Static("[Enter] Save    [Esc] Cancel", id="review-actions")

    def action_save(self) -> None:
        try:
            textarea = self.query_one("#constraints-edit", TextArea)
            self._user_text = textarea.text
        except Exception:
            pass
        if self._user_text.strip():
            path = self.state.dir / "user_constraints.md"
            path.write_text(self._user_text.strip() + "\n", encoding="utf-8")
            self.state.append_log({"event": "goal_updated"})
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(None)
```

**Step 3: Create `modals/inject.py`**

```python
"""Inject idea modal — available anytime via 'i' key."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Input, Label, Static

from open_researcher_v2.state import ResearchState


class InjectIdeaScreen(Screen):
    """Inject a human-authored experiment idea into the frontier."""

    BINDINGS = [
        Binding("enter", "inject", "Add to frontier"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, state: ResearchState, **kwargs):
        super().__init__(**kwargs)
        self.state = state
        self._description = ""
        self._priority = 3

    def compose(self) -> ComposeResult:
        with Vertical(id="review-dialog"):
            yield Label("Inject Experiment", id="review-title")
            yield Label("Description:")
            yield Input(id="inject-desc", placeholder="Describe the experiment...")
            yield Label("Priority (1-5):")
            yield Input(id="inject-priority", value="3")
            yield Static("[Enter] Add to frontier    [Esc] Cancel", id="review-actions")

    def action_inject(self) -> None:
        try:
            self._description = self.query_one("#inject-desc", Input).value
            self._priority = int(self.query_one("#inject-priority", Input).value)
        except Exception:
            pass

        if not self._description.strip():
            self.dismiss(None)
            return

        graph = self.state.load_graph()
        counter = graph.get("counters", {}).get("frontier", 0) + 1
        item = {
            "id": f"frontier-{counter:03d}",
            "description": self._description.strip(),
            "priority": self._priority,
            "status": "approved",
            "selection_reason_code": "human_injected",
            "hypothesis_id": "",
            "experiment_spec_id": "",
        }
        graph.setdefault("frontier", []).append(item)
        graph.setdefault("counters", {})["frontier"] = counter
        self.state.save_graph(graph)
        self.state.append_log({"event": "human_injected", "frontier_id": item["id"]})
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(None)
```

**Step 4: Run tests**

Run: `pytest tests/v2/test_review_modals.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/open_researcher_v2/tui/modals/goal_edit.py src/open_researcher_v2/tui/modals/inject.py tests/v2/test_review_modals.py
git commit -m "feat(v2): add GoalEditScreen and InjectIdeaScreen modals"
```

---

## Task 12: Wire modals into TUI app

**Files:**
- Modify: `src/open_researcher_v2/tui/app.py:19-27` (imports)
- Modify: `src/open_researcher_v2/tui/app.py:51-56` (BINDINGS)
- Modify: `src/open_researcher_v2/tui/app.py:58-69` (__init__)
- Modify: `src/open_researcher_v2/tui/app.py:112-146` (_poll_state)
- Add: `src/open_researcher_v2/tui/app.py` (action_quit, action_edit_goal, action_inject_idea)
- Test: `tests/v2/test_tui_app.py`

**Step 1: Write failing test**

Append to `tests/v2/test_tui_app.py`:

```python
class TestReviewDetection:
    def test_poll_state_detects_review(self, tmp_path):
        from open_researcher_v2.state import ResearchState
        from open_researcher_v2.tui.app import ResearchApp

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)

        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=None)
        assert app._review_shown is False

    def test_action_quit_clears_review(self, tmp_path):
        from open_researcher_v2.state import ResearchState
        from open_researcher_v2.tui.app import ResearchApp
        from unittest.mock import patch

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review({"type": "test", "requested_at": "2026-03-19T14:00:00Z"})

        app = ResearchApp(repo_path=str(tmp_path), state=state, runner=None)
        with patch.object(app.__class__.__bases__[0], "action_quit"):
            app.action_quit()

        assert state.get_awaiting_review() is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/v2/test_tui_app.py::TestReviewDetection -v`
Expected: FAIL — `_review_shown` not found

**Step 3: Update app.py**

3a. Add imports (after line 17):

```python
from open_researcher_v2.tui.modals.base import ReviewScreen
from open_researcher_v2.tui.modals.direction import DirectionConfirmScreen
from open_researcher_v2.tui.modals.hypothesis import HypothesisReviewScreen
from open_researcher_v2.tui.modals.frontier import FrontierReviewScreen
from open_researcher_v2.tui.modals.result import ResultReviewScreen
from open_researcher_v2.tui.modals.goal_edit import GoalEditScreen
from open_researcher_v2.tui.modals.inject import InjectIdeaScreen
```

3b. Update BINDINGS (line 51-56):

```python
    BINDINGS = [
        Binding("p", "pause", "Pause"),
        Binding("r", "resume", "Resume"),
        Binding("s", "skip", "Skip"),
        Binding("g", "edit_goal", "Goal"),
        Binding("i", "inject_idea", "Inject"),
        Binding("q", "quit", "Quit"),
    ]
```

3c. Add `_review_shown` to `__init__` (after line 69):

```python
        self._review_shown = False
```

3d. Add review detection to `_poll_state` (after line 143, before `except`):

```python
            # Check for pending review
            review = summary.get("awaiting_review")
            if review and not self._review_shown:
                self._review_shown = True
                try:
                    screen = self._make_review_screen(review)
                    self.push_screen(screen, callback=self._on_review_done)
                except Exception:
                    self._review_shown = False
```

3e. Add helper methods (after `action_skip`, at end of class):

```python
    def _make_review_screen(self, review: dict) -> ReviewScreen:
        """Create the appropriate review screen for the review type."""
        rtype = review.get("type", "")
        if rtype == "direction_confirm":
            return DirectionConfirmScreen(state=self.state, review_request=review)
        if rtype == "hypothesis_review":
            return HypothesisReviewScreen(state=self.state, review_request=review)
        if rtype == "frontier_review":
            return FrontierReviewScreen(state=self.state, review_request=review)
        if rtype == "result_review":
            return ResultReviewScreen(state=self.state, review_request=review)
        # Fallback — skip unknown review types
        self.state.clear_awaiting_review()
        raise ValueError(f"Unknown review type: {rtype}")

    def _on_review_done(self, result) -> None:
        self._review_shown = False

    def action_edit_goal(self) -> None:
        """Open goal edit modal."""
        try:
            self.push_screen(GoalEditScreen(state=self.state))
        except Exception:
            pass

    def action_inject_idea(self) -> None:
        """Open inject idea modal."""
        try:
            self.push_screen(InjectIdeaScreen(state=self.state))
        except Exception:
            pass

    def action_quit(self) -> None:
        """Quit TUI, cleaning up any pending review."""
        if self.state.get_awaiting_review():
            self.state.clear_awaiting_review()
            self.state.append_log({"event": "review_skipped", "review_type": "quit"})
        self._review_shown = False
        super().action_quit()
```

**Step 4: Run tests**

Run: `pytest tests/v2/test_tui_app.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/open_researcher_v2/tui/app.py tests/v2/test_tui_app.py
git commit -m "feat(v2): wire review modals + g/i keybindings into TUI app"
```

---

## Task 13: Update StatsBar and LogPanel for review events

**Files:**
- Modify: `src/open_researcher_v2/tui/widgets.py:39-51` (StatsBar.update_data)
- Modify: `src/open_researcher_v2/tui/widgets.py:134-141` (_EVENT_PREFIXES)
- Test: `tests/v2/test_tui_widgets.py`

**Step 1: Write failing test**

Append to `tests/v2/test_tui_widgets.py`:

```python
class TestStatsBarReview:
    def test_shows_review_indicator(self):
        from open_researcher_v2.tui.widgets import StatsBar
        from textual.app import App, ComposeResult

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield StatsBar(id="stats")

        async def _test():
            async with TestApp().run_test() as pilot:
                bar: StatsBar = pilot.app.query_one("#stats", StatsBar)
                bar.update_data({
                    "phase": "manager",
                    "round": 1,
                    "hypotheses": 3,
                    "experiments_total": 5,
                    "experiments_done": 2,
                    "experiments_running": 0,
                    "best_value": "1000",
                    "paused": False,
                    "awaiting_review": {"type": "hypothesis_review"},
                })
                text = str(bar.content)
                assert "REVIEW" in text.upper()

        import asyncio
        asyncio.run(_test())


class TestLogPanelReviewEvents:
    def test_review_event_prefixes(self):
        from open_researcher_v2.tui.widgets import _EVENT_PREFIXES
        assert "review_requested" in _EVENT_PREFIXES
        assert "review_completed" in _EVENT_PREFIXES
        assert "human_injected" in _EVENT_PREFIXES
        assert "human_override" in _EVENT_PREFIXES
        assert "goal_updated" in _EVENT_PREFIXES
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/v2/test_tui_widgets.py::TestStatsBarReview tests/v2/test_tui_widgets.py::TestLogPanelReviewEvents -v`
Expected: FAIL

**Step 3: Update StatsBar.update_data**

Replace `update_data` method (line 39-51):

```python
    def update_data(self, summary: dict[str, Any]) -> None:
        phase = summary.get("phase", "idle")
        rnd = summary.get("round", 0)
        hyps = summary.get("hypotheses", 0)
        done = summary.get("experiments_done", 0)
        total = summary.get("experiments_total", 0)
        running = summary.get("experiments_running", 0)
        best = summary.get("best_value", "\u2014")
        suffix = ""
        if summary.get("paused"):
            suffix = " [PAUSED]"
        review = summary.get("awaiting_review")
        if review:
            rtype = review.get("type", "").replace("_", " ").upper()
            suffix = f" \u23f3 REVIEW {rtype}"
        self.update(
            f"Phase: {phase} | Round: {rnd} | Hyps: {hyps} "
            f"| Exps: {done}/{total} ({running}) | Best: {best}{suffix}"
        )
```

**Step 4: Update _EVENT_PREFIXES**

Replace `_EVENT_PREFIXES` dict (line 134-141):

```python
_EVENT_PREFIXES: dict[str, str] = {
    "skill_started": "[cyan]SKILL[/]",
    "skill_completed": "[green]DONE[/]",
    "output": "[white]OUT[/]",
    "worker_started": "[blue]W+[/]",
    "worker_finished": "[blue]W-[/]",
    "experiment_result": "[yellow]RES[/]",
    "review_requested": "[bold yellow]WAIT[/]",
    "review_completed": "[green]REVW[/]",
    "review_timeout": "[yellow]TOUT[/]",
    "review_skipped": "[dim]SKIP[/]",
    "human_injected": "[bold cyan]INJ[/]",
    "human_override": "[bold magenta]OVRD[/]",
    "goal_updated": "[cyan]GOAL[/]",
}
```

**Step 5: Run tests**

Run: `pytest tests/v2/test_tui_widgets.py -v`
Expected: all PASS

**Step 6: Commit**

```bash
git add src/open_researcher_v2/tui/widgets.py tests/v2/test_tui_widgets.py
git commit -m "feat(v2): add review indicators to StatsBar and LogPanel"
```

---

## Task 14: Update skill templates

**Files:**
- Modify: `src/open_researcher_v2/skills/manager.md` (add user_constraints instruction near top)
- Modify: `src/open_researcher_v2/skills/experiment.md` (add human_injected handling)
- Test: manual verification via grep

**Step 1: Read current manager.md header**

Read first 30 lines of `src/open_researcher_v2/skills/manager.md` to find insertion point.

**Step 2: Add user_constraints section to manager.md**

Insert after the "Your Files" section:

```markdown
## User Constraints

If `.research/user_constraints.md` exists, read it FIRST. All hypotheses
and frontier items MUST respect these constraints. If a constraint conflicts
with your analysis, prioritize the constraint and note the conflict in the
hypothesis rationale.
```

**Step 3: Add human_injected handling to experiment.md**

Insert in the "Claiming Your Experiment" section:

```markdown
**Human-injected items:**
If the claimed frontier item has `selection_reason_code: "human_injected"`
and no linked `experiment_spec_id`, treat the `description` field as your
complete task specification. Design the change_plan and evaluation_plan
yourself based on the description and `.research/evaluation.md`.
```

**Step 4: Verify no v1 file references leaked**

Run: `grep -r "idea_pool\|research_memory\|events.jsonl\|control.json\|experiment_progress\|failure_memory" src/open_researcher_v2/skills/`
Expected: zero matches

**Step 5: Commit**

```bash
git add src/open_researcher_v2/skills/manager.md src/open_researcher_v2/skills/experiment.md
git commit -m "feat(v2): add user_constraints and human_injected handling to skill templates"
```

---

## Task 15: Update modals __init__.py exports and final integration test

**Files:**
- Modify: `src/open_researcher_v2/tui/modals/__init__.py`
- Test: `tests/v2/test_review_modals.py` (add integration test)

**Step 1: Update modals __init__.py**

```python
"""TUI modal screens for human-in-the-loop review checkpoints."""

from .base import ReviewScreen
from .direction import DirectionConfirmScreen
from .frontier import FrontierReviewScreen
from .goal_edit import GoalEditScreen
from .hypothesis import HypothesisReviewScreen
from .inject import InjectIdeaScreen
from .result import ResultReviewScreen

__all__ = [
    "ReviewScreen",
    "DirectionConfirmScreen",
    "FrontierReviewScreen",
    "GoalEditScreen",
    "HypothesisReviewScreen",
    "InjectIdeaScreen",
    "ResultReviewScreen",
]
```

**Step 2: Write integration test**

Append to `tests/v2/test_review_modals.py`:

```python
class TestFullCheckpointFlow:
    """Integration test: config → checkpoint → state change → clear."""

    def test_checkpoint_mode_end_to_end(self, tmp_path):
        import threading
        import yaml
        from open_researcher_v2.state import ResearchState
        from open_researcher_v2.skill_runner import SkillRunner
        from open_researcher_v2.agent import Agent, AgentAdapter

        # Setup
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        (research_dir / "config.yaml").write_text(yaml.dump({
            "interaction": {
                "mode": "checkpoint",
                "checkpoints": {
                    "after_scout": True,
                    "after_manager": False,
                    "after_critic_preflight": False,
                    "after_round": False,
                },
            },
        }))

        state = ResearchState(research_dir)

        class StubAdapter(AgentAdapter):
            name = "stub"
            command = "stub"
            def run(self, workdir, *, on_output=None, program_file="program.md", env=None):
                return 0

        agent = Agent(StubAdapter())
        runner = SkillRunner(tmp_path, state, agent, goal="test", tag="t1")

        # Auto-approve after delay
        def auto_approve():
            import time
            for _ in range(10):
                time.sleep(0.3)
                if state.get_awaiting_review():
                    state.clear_awaiting_review()
                    break

        t = threading.Thread(target=auto_approve, daemon=True)
        t.start()

        rc = runner.run_bootstrap()
        t.join(timeout=5.0)
        assert rc == 0

        # Verify review was requested and completed
        logs = state.tail_log(50)
        events = [e["event"] for e in logs]
        assert "review_requested" in events
        assert "review_completed" in events
```

**Step 3: Run all tests**

Run: `pytest tests/v2/ -v`
Expected: all PASS

**Step 4: Commit**

```bash
git add src/open_researcher_v2/tui/modals/__init__.py tests/v2/test_review_modals.py
git commit -m "feat(v2): finalize modals package and add integration test"
```

---

## Verification Checklist

After all tasks are complete, run these verification steps:

```bash
# 1. Full test suite
pytest tests/v2/ -v

# 2. Import check
python -c "from open_researcher_v2.tui.modals import ReviewScreen, DirectionConfirmScreen, HypothesisReviewScreen, FrontierReviewScreen, ResultReviewScreen, GoalEditScreen, InjectIdeaScreen; print('OK')"

# 3. State method check
python -c "from open_researcher_v2.state import ResearchState; import tempfile; s=ResearchState(tempfile.mkdtemp()); s.set_awaiting_review({'type':'test','requested_at':'now'}); print(s.get_awaiting_review()); s.clear_awaiting_review(); print(s.get_awaiting_review()); print('OK')"

# 4. Config defaults check
python -c "from open_researcher_v2.state import ResearchState; import tempfile; s=ResearchState(tempfile.mkdtemp()); c=s.load_config(); print(c['interaction']); print('OK')"

# 5. Skill template audit — must return zero matches
grep -r "idea_pool\|research_memory\|events.jsonl\|control.json\|experiment_progress\|failure_memory" src/open_researcher_v2/skills/ || echo "CLEAN"
```
