"""Tests for SkillRunner — skill loading and serial research loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from paperfarm.agent import Agent, AgentAdapter
from paperfarm.skill_runner import SkillRunner
from paperfarm.state import ResearchState


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
        from paperfarm import skill_runner

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
