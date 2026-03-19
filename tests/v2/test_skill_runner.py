"""Tests for SkillRunner — skill loading and serial research loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from open_researcher_v2.agent import Agent, AgentAdapter
from open_researcher_v2.skill_runner import SkillRunner
from open_researcher_v2.state import ResearchState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubAdapter(AgentAdapter):
    """Adapter that always returns a fixed exit code without spawning a process."""

    name = "stub"
    command = "stub"

    def __init__(self, rc: int = 0) -> None:
        super().__init__()
        self.rc = rc
        self.calls: list[dict[str, Any]] = []

    def run(self, workdir, *, on_output=None, program_file="program.md", env=None):
        # Read the program content that Agent.run() wrote so tests can inspect it.
        content = (workdir / ".research" / program_file).read_text(encoding="utf-8")
        self.calls.append({
            "workdir": workdir,
            "program_file": program_file,
            "content": content,
            "env": env,
        })
        # Optionally send some output lines back.
        if on_output is not None:
            on_output("stub output line\n")
        return self.rc


def _make_runner(
    tmp_path: Path,
    *,
    adapter_rc: int = 0,
    goal: str = "improve accuracy",
    tag: str = "test-run",
    config_overrides: dict | None = None,
    on_output=None,
) -> tuple[SkillRunner, _StubAdapter, ResearchState]:
    """Create a SkillRunner backed by a stub adapter + a temp research dir."""
    research_dir = tmp_path / ".research"
    research_dir.mkdir(parents=True, exist_ok=True)

    # Write config if overrides provided.
    if config_overrides:
        import yaml
        (research_dir / "config.yaml").write_text(
            yaml.dump(config_overrides), encoding="utf-8",
        )

    state = ResearchState(research_dir)
    adapter = _StubAdapter(rc=adapter_rc)
    agent = Agent(adapter)
    runner = SkillRunner(
        tmp_path,
        state,
        agent,
        goal=goal,
        tag=tag,
        on_output=on_output,
    )
    return runner, adapter, state


# ---------------------------------------------------------------------------
# TestSkillLoading
# ---------------------------------------------------------------------------


class TestSkillLoading:
    """Test protocol and skill file loading."""

    def test_skills_dir_exists(self):
        """The skills directory should exist relative to skill_runner.py."""
        from open_researcher_v2 import skill_runner

        skills_dir = Path(skill_runner.__file__).parent / "skills"
        assert skills_dir.is_dir()

    def test_load_protocol(self, tmp_path):
        runner, _, _ = _make_runner(tmp_path)
        protocol = runner._load_protocol()

        assert protocol["protocol"] == "research-v1"
        assert isinstance(protocol["bootstrap"], list)
        assert "scout" in protocol["bootstrap"]
        assert isinstance(protocol["loop"], list)
        assert len(protocol["loop"]) > 0

    def test_load_protocol_has_loop_structure(self, tmp_path):
        runner, _, _ = _make_runner(tmp_path)
        protocol = runner._load_protocol()

        for step in protocol["loop"]:
            assert "name" in step
            assert "skill" in step

    def test_load_skill_scout(self, tmp_path):
        runner, _, _ = _make_runner(tmp_path)
        content = runner._load_skill("scout.md")
        assert "Scout" in content
        assert "[GOAL]" in content

    def test_load_skill_manager(self, tmp_path):
        runner, _, _ = _make_runner(tmp_path)
        content = runner._load_skill("manager.md")
        assert "Manager" in content

    def test_load_skill_missing_raises(self, tmp_path):
        runner, _, _ = _make_runner(tmp_path)
        with pytest.raises(FileNotFoundError):
            runner._load_skill("nonexistent.md")

    def test_compose_program_substitutes_goal_and_tag(self, tmp_path):
        runner, _, _ = _make_runner(tmp_path, goal="beat SOTA", tag="exp-42")
        content = runner._compose_program("scout")

        assert "[GOAL]" not in content
        assert "[TAG]" not in content
        assert "beat SOTA" in content
        # TAG may or may not appear in scout.md — check if it was substituted
        # The key assertion is that template vars are gone.

    def test_compose_program_no_goal(self, tmp_path):
        """When goal is empty, [GOAL] is replaced with empty string."""
        runner, _, _ = _make_runner(tmp_path, goal="", tag="")
        content = runner._compose_program("scout")
        assert "[GOAL]" not in content
        assert "[TAG]" not in content


# ---------------------------------------------------------------------------
# TestSkillRunnerSerial
# ---------------------------------------------------------------------------


class TestSkillRunnerSerial:
    """Test bootstrap, single round, and serial loop execution."""

    def test_run_bootstrap_success(self, tmp_path):
        runner, adapter, state = _make_runner(tmp_path)
        rc = runner.run_bootstrap()

        assert rc == 0
        # Adapter should have been called once (scout).
        assert len(adapter.calls) == 1
        assert "scout" in adapter.calls[0]["program_file"]

    def test_run_bootstrap_failure(self, tmp_path):
        runner, adapter, state = _make_runner(tmp_path, adapter_rc=1)
        rc = runner.run_bootstrap()

        assert rc == 1
        # Only one call — failed on the first bootstrap step.
        assert len(adapter.calls) == 1

    def test_run_bootstrap_logs_events(self, tmp_path):
        runner, _, state = _make_runner(tmp_path)
        runner.run_bootstrap()

        log = state.tail_log(100)
        events = [e["event"] for e in log if "event" in e]
        assert "skill_started" in events
        assert "skill_completed" in events

    def test_run_bootstrap_substitutes_variables(self, tmp_path):
        runner, adapter, _ = _make_runner(tmp_path, goal="test goal", tag="v1")
        runner.run_bootstrap()

        content = adapter.calls[0]["content"]
        assert "test goal" in content
        assert "[GOAL]" not in content

    def test_run_one_round_success(self, tmp_path):
        runner, adapter, state = _make_runner(tmp_path)
        rc = runner.run_one_round(1)

        assert rc == 0
        # Protocol has 4 loop steps: manager, critic, experiment, critic
        assert len(adapter.calls) == 4

    def test_run_one_round_step_failure(self, tmp_path):
        """If any step fails, the round returns that exit code."""
        runner, adapter, state = _make_runner(tmp_path, adapter_rc=2)
        rc = runner.run_one_round(1)

        assert rc == 2
        # Should have stopped at the first failing step.
        assert len(adapter.calls) == 1

    def test_run_one_round_logs_round_events(self, tmp_path):
        runner, _, state = _make_runner(tmp_path)
        runner.run_one_round(3)

        log = state.tail_log(200)
        round_events = [e for e in log if e.get("event") in ("round_started", "round_completed")]
        assert any(e["event"] == "round_started" and e["round"] == 3 for e in round_events)
        assert any(e["event"] == "round_completed" and e["round"] == 3 for e in round_events)

    def test_run_one_round_paused(self, tmp_path):
        runner, adapter, state = _make_runner(tmp_path)
        # Set paused before the round.
        state.set_paused(True)

        rc = runner.run_one_round(1)

        assert rc == -2
        assert len(adapter.calls) == 0

    def test_run_one_round_skip(self, tmp_path):
        runner, adapter, state = _make_runner(tmp_path)
        # Set skip_current before the round.
        state.set_skip_current(True)

        rc = runner.run_one_round(1)

        assert rc == -1
        assert len(adapter.calls) == 0
        # Skip should have been consumed.
        assert not state.consume_skip()

    def test_run_serial_bootstrap_then_rounds(self, tmp_path):
        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 2}},
        )
        rc = runner.run_serial()

        assert rc == 0
        # 1 bootstrap call (scout) + 2 rounds * 4 steps = 9 total calls.
        assert len(adapter.calls) == 9

    def test_run_serial_respects_max_rounds(self, tmp_path):
        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 1}},
        )
        rc = runner.run_serial()

        assert rc == 0
        # 1 bootstrap + 1 round * 4 steps = 5 total.
        assert len(adapter.calls) == 5

    def test_run_serial_bootstrap_failure_stops(self, tmp_path):
        runner, adapter, state = _make_runner(tmp_path, adapter_rc=1)
        rc = runner.run_serial()

        assert rc == 1
        # Only one call — the failed bootstrap step.
        assert len(adapter.calls) == 1

    def test_run_serial_pause_stops_loop(self, tmp_path):
        """Pausing before the loop starts should prevent any rounds."""
        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 5}},
        )
        # Pause after bootstrap by hooking into the agent calls.
        original_run = adapter.run

        call_count = 0

        def _pausing_run(workdir, *, on_output=None, program_file="program.md", env=None):
            nonlocal call_count
            result = original_run(workdir, on_output=on_output, program_file=program_file, env=env)
            call_count += 1
            # After bootstrap (1st call), set paused.
            if call_count == 1:
                state.set_paused(True)
            return result

        adapter.run = _pausing_run

        rc = runner.run_serial()
        assert rc == 0
        # Bootstrap (1 call), then pause kicks in before round 1 loop steps execute.
        # The scout call happens, then is_paused() == True, so the loop breaks.
        assert call_count == 1

    def test_run_serial_frontier_complete_stops(self, tmp_path):
        """If all frontier items are terminal, stop early."""
        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 10}},
        )
        # Pre-populate graph with a fully-done frontier.
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "f-1", "status": "archived"},
            {"id": "f-2", "status": "rejected"},
        ]
        state.save_graph(graph)

        rc = runner.run_serial()
        assert rc == 0
        # 1 bootstrap + 1 round (4 steps) = 5 calls, then frontier check stops it.
        assert len(adapter.calls) == 5

    def test_run_serial_empty_frontier_continues(self, tmp_path):
        """An empty frontier should not be treated as 'all done'."""
        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 2}},
        )

        rc = runner.run_serial()
        assert rc == 0
        # Should run all rounds: 1 + 2*4 = 9.
        assert len(adapter.calls) == 9

    def test_on_output_callback_receives_lines(self, tmp_path):
        received: list[str] = []
        runner, adapter, state = _make_runner(
            tmp_path,
            on_output=received.append,
        )
        runner.run_bootstrap()

        # The stub adapter sends one line of output.
        assert len(received) > 0
        assert any("stub output" in line for line in received)

    def test_run_serial_updates_phase_to_idle(self, tmp_path):
        runner, _, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 1}},
        )
        runner.run_serial()

        activity = state.load_activity()
        assert activity["phase"] == "idle"

    def test_run_one_round_updates_phase(self, tmp_path):
        runner, _, state = _make_runner(tmp_path)
        runner.run_one_round(5)

        # During the round, update_phase is called with step names.
        # After all steps complete, the last phase set should be from the last step.
        # We just verify the log records correct round info.
        log = state.tail_log(200)
        assert any(e.get("round") == 5 for e in log)


# ---------------------------------------------------------------------------
# TestCheckpoints
# ---------------------------------------------------------------------------


class TestCheckpoints:
    """Tests for human-in-the-loop checkpoint logic."""

    def test_checkpoint_type_returns_none_in_autopilot(self, tmp_path):
        runner, _, state = _make_runner(tmp_path)
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
        runner._critic_call_count_this_round = 1
        assert runner._checkpoint_type("critic", 1) == "frontier_review"
        runner._critic_call_count_this_round = 2
        assert runner._checkpoint_type("critic", 1) == "result_review"

    def test_await_review_blocks_until_cleared(self, tmp_path):
        import threading, time
        runner, _, state = _make_runner(tmp_path, config_overrides={
            "interaction": {"mode": "checkpoint"},
        })
        done = threading.Event()
        def run_await():
            runner._await_review("hypothesis_review")
            done.set()
        t = threading.Thread(target=run_await)
        t.start()
        time.sleep(0.5)
        assert not done.is_set(), "Should still be blocking"
        state.clear_awaiting_review()
        done.wait(timeout=3.0)
        assert done.is_set(), "Should have unblocked"
        t.join(timeout=1.0)

    def test_await_review_logs_events(self, tmp_path):
        import threading, time
        runner, _, state = _make_runner(tmp_path, config_overrides={
            "interaction": {"mode": "checkpoint"},
        })
        def run_and_clear():
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
        import threading, time
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
        def auto_approve():
            time.sleep(0.5)
            if state.get_awaiting_review():
                state.clear_awaiting_review()
        t = threading.Thread(target=auto_approve)
        t.start()
        rc = runner.run_one_round(1)
        t.join()
        assert rc == 0
        logs = state.tail_log(50)
        review_events = [e for e in logs if e.get("event") == "review_requested"]
        assert len(review_events) == 1
        assert review_events[0]["review_type"] == "hypothesis_review"

    def test_await_review_clears_on_pause(self, tmp_path):
        """When paused during a review, awaiting_review should be cleared."""
        import threading, time
        runner, _, state = _make_runner(tmp_path, config_overrides={
            "interaction": {"mode": "checkpoint"},
        })
        def pause_after_delay():
            time.sleep(0.3)
            state.set_paused(True)
        t = threading.Thread(target=pause_after_delay)
        t.start()
        runner._await_review("hypothesis_review")
        t.join()
        # Review should be cleared (not left stale)
        assert state.get_awaiting_review() is None
        logs = state.tail_log(10)
        events = [e["event"] for e in logs]
        assert "review_skipped" in events


# ---------------------------------------------------------------------------
# TestRunParallel
# ---------------------------------------------------------------------------


class _MockPool:
    """A lightweight mock for WorkerPool with run/wait/stop methods."""

    def __init__(self):
        self.run_called = False
        self.wait_called = False

    def run(self):
        self.run_called = True

    def wait(self, timeout=None):
        self.wait_called = True

    def stop(self):
        pass


class TestRunParallel:
    """Tests for SkillRunner.run_parallel orchestration."""

    def test_parallel_runs_correct_step_order(self, tmp_path):
        """run_parallel should call: scout → manager → critic → workers → critic per round."""
        pools = []

        def pool_factory():
            p = _MockPool()
            pools.append(p)
            return p

        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 1}},
        )
        rc = runner.run_parallel(pool_factory)
        assert rc == 0

        # Step names from adapter calls:
        # bootstrap: scout (1 call)
        # round 1: manager, critic, critic (3 agent calls + 1 pool)
        step_names = [c["program_file"] for c in adapter.calls]
        assert step_names == ["scout.md", "manager.md", "critic.md", "critic.md"]

        # Pool should have been created and used
        assert len(pools) == 1
        assert pools[0].run_called
        assert pools[0].wait_called

    def test_parallel_runs_multiple_rounds(self, tmp_path):
        """run_parallel runs correct number of rounds."""
        pools = []

        def pool_factory():
            p = _MockPool()
            pools.append(p)
            return p

        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 3}},
        )
        rc = runner.run_parallel(pool_factory)
        assert rc == 0

        # 1 bootstrap + 3 rounds * 3 agent calls = 10 total agent calls
        assert len(adapter.calls) == 10
        # 3 pools (one per round)
        assert len(pools) == 3

    def test_parallel_respects_max_rounds(self, tmp_path):
        """run_parallel stops after max_rounds."""
        pools = []

        def pool_factory():
            p = _MockPool()
            pools.append(p)
            return p

        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 2}},
        )
        rc = runner.run_parallel(pool_factory)
        assert rc == 0
        assert len(pools) == 2

    def test_parallel_bootstrap_failure_stops(self, tmp_path):
        """If bootstrap fails, run_parallel returns the error code."""
        runner, adapter, state = _make_runner(tmp_path, adapter_rc=1)
        rc = runner.run_parallel(lambda: _MockPool())
        assert rc == 1
        assert len(adapter.calls) == 1  # only scout attempted

    def test_parallel_manager_failure_stops(self, tmp_path):
        """If manager fails, run_parallel returns the error code."""
        call_count = [0]
        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 2}},
        )
        original_run = adapter.run

        def _fail_on_manager(workdir, *, on_output=None, program_file="program.md", env=None):
            result = original_run(workdir, on_output=on_output, program_file=program_file, env=env)
            call_count[0] += 1
            # Fail on manager (2nd call, after scout)
            if call_count[0] == 2:
                return 3
            return result

        adapter.run = _fail_on_manager
        rc = runner.run_parallel(lambda: _MockPool())
        assert rc == 3

    def test_parallel_pause_stops_loop(self, tmp_path):
        """Pausing before a round starts should prevent that round."""
        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 5}},
        )
        original_run = adapter.run
        call_count = [0]

        def _pausing_run(workdir, *, on_output=None, program_file="program.md", env=None):
            result = original_run(workdir, on_output=on_output, program_file=program_file, env=env)
            call_count[0] += 1
            # After bootstrap (1st call), set paused
            if call_count[0] == 1:
                state.set_paused(True)
            return result

        adapter.run = _pausing_run
        rc = runner.run_parallel(lambda: _MockPool())
        assert rc == 0
        # Only bootstrap ran (1 call), then pause stopped the loop
        assert call_count[0] == 1

    def test_parallel_frontier_complete_stops(self, tmp_path):
        """If all frontier items are terminal, stop early."""
        pools = []

        def pool_factory():
            p = _MockPool()
            pools.append(p)
            return p

        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 10}},
        )
        # Pre-populate graph with a fully-done frontier
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "f-1", "status": "archived"},
            {"id": "f-2", "status": "rejected"},
        ]
        state.save_graph(graph)

        rc = runner.run_parallel(pool_factory)
        assert rc == 0
        # Should stop after round 1: 1 bootstrap + 3 agent calls + 1 pool = done
        assert len(pools) == 1
        logs = state.tail_log(100)
        assert any(e.get("event") == "frontier_complete" for e in logs)

    def test_parallel_logs_worker_events(self, tmp_path):
        """run_parallel logs parallel_workers_started and parallel_workers_finished."""
        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 1}},
        )
        rc = runner.run_parallel(lambda: _MockPool())
        assert rc == 0

        logs = state.tail_log(100)
        events = [e["event"] for e in logs if "event" in e]
        assert "parallel_workers_started" in events
        assert "parallel_workers_finished" in events

    def test_parallel_updates_phase_to_idle(self, tmp_path):
        """After run_parallel completes, phase should be idle."""
        runner, _, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 1}},
        )
        runner.run_parallel(lambda: _MockPool())

        activity = state.load_activity()
        assert activity["phase"] == "idle"

    def test_parallel_sets_experiment_phase_during_workers(self, tmp_path):
        """During worker execution, phase should be set to 'experiment'."""
        phases_seen = []

        class _PhaseCapturingPool:
            def __init__(self, state):
                self._state = state

            def run(self):
                activity = self._state.load_activity()
                phases_seen.append(activity.get("phase"))

            def wait(self, timeout=None):
                pass

            def stop(self):
                pass

        runner, adapter, state = _make_runner(
            tmp_path,
            config_overrides={"limits": {"max_rounds": 1}},
        )
        runner.run_parallel(lambda: _PhaseCapturingPool(state))

        assert "experiment" in phases_seen

    def test_parallel_passes_timeout_to_pool(self, tmp_path):
        """run_parallel reads timeout_minutes and passes it to pool.wait()."""
        wait_args = []

        class _TimeoutCapturingPool:
            def run(self):
                pass

            def wait(self, timeout=None):
                wait_args.append(timeout)

            def stop(self):
                pass

        runner, _, state = _make_runner(
            tmp_path,
            config_overrides={
                "limits": {"max_rounds": 1, "timeout_minutes": 5},
            },
        )
        runner.run_parallel(lambda: _TimeoutCapturingPool())
        assert len(wait_args) == 1
        assert wait_args[0] == 300.0  # 5 min * 60

    def test_parallel_no_timeout_when_zero(self, tmp_path):
        """When timeout_minutes is 0, pool.wait() gets None (no timeout)."""
        wait_args = []

        class _TimeoutCapturingPool:
            def run(self):
                pass

            def wait(self, timeout=None):
                wait_args.append(timeout)

            def stop(self):
                pass

        runner, _, state = _make_runner(
            tmp_path,
            config_overrides={
                "limits": {"max_rounds": 1, "timeout_minutes": 0},
            },
        )
        runner.run_parallel(lambda: _TimeoutCapturingPool())
        assert wait_args[0] is None
