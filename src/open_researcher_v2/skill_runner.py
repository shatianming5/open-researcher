"""SkillRunner — core skill orchestrator for the research-v1 protocol.

Loads skill definitions from ``skills/protocol.yaml``, performs variable
substitution (``[GOAL]``, ``[TAG]``), and drives the serial research loop:
bootstrap (scout) followed by N rounds of manager/critic/experiment steps.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from .agent import Agent
from .state import ResearchState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SkillRunner
# ---------------------------------------------------------------------------


class SkillRunner:
    """Orchestrates skill execution according to ``protocol.yaml``.

    Parameters
    ----------
    repo_path:
        Root of the research repository (the agent's working directory).
    state:
        A ``ResearchState`` instance for the ``.research/`` directory.
    agent:
        An ``Agent`` wrapping a concrete agent adapter.
    goal:
        Free-text research goal injected into skill templates as ``[GOAL]``.
    tag:
        Short identifier for this research session, injected as ``[TAG]``.
    on_output:
        Optional callback invoked with every line of agent output.
    """

    def __init__(
        self,
        repo_path: Path,
        state: ResearchState,
        agent: Agent,
        *,
        goal: str = "",
        tag: str = "",
        on_output: Callable[[str], None] | None = None,
    ) -> None:
        self.repo_path = repo_path
        self.state = state
        self.agent = agent
        self.goal = goal
        self.tag = tag
        self.on_output = on_output
        self._critic_call_count_this_round = 0

    # -- paths & loading ----------------------------------------------------

    def _skills_dir(self) -> Path:
        """Return the directory containing bundled skill files."""
        return Path(__file__).parent / "skills"

    def _load_protocol(self) -> dict[str, Any]:
        """Load and return ``skills/protocol.yaml``."""
        path = self._skills_dir() / "protocol.yaml"
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def _load_skill(self, filename: str) -> str:
        """Read a skill markdown file from the skills directory."""
        path = self._skills_dir() / filename
        return path.read_text(encoding="utf-8")

    def _compose_program(self, skill_name: str) -> str:
        """Load a skill file and perform ``[GOAL]``/``[TAG]`` substitution."""
        # skill_name may or may not end with .md
        filename = skill_name if skill_name.endswith(".md") else f"{skill_name}.md"
        content = self._load_skill(filename)
        content = content.replace("[GOAL]", self.goal)
        content = content.replace("[TAG]", self.tag)
        return content

    # -- execution ----------------------------------------------------------

    def _make_output_callback(self, phase: str) -> Callable[[str], None]:
        """Return a callback that forwards output and logs it."""

        def _cb(line: str) -> None:
            if self.on_output is not None:
                self.on_output(line)
            # Log a trimmed version to the structured log (avoid huge entries).
            trimmed = line.rstrip("\n")[:500]
            if trimmed:
                self.state.append_log({
                    "event": "agent_output",
                    "phase": phase,
                    "line": trimmed,
                })

        return _cb

    def _run_skill(
        self,
        step_name: str,
        skill_file: str,
        *,
        env: dict[str, str] | None = None,
    ) -> int:
        """Execute a single skill step.

        1. Log ``skill_started``
        2. Update phase in activity
        3. Compose the program content (variable substitution)
        4. Run agent
        5. Log ``skill_completed``

        Returns the agent exit code.
        """
        self.state.append_log({
            "event": "skill_started",
            "step": step_name,
            "skill": skill_file,
        })
        self.state.update_phase(step_name)

        program = self._compose_program(skill_file)
        callback = self._make_output_callback(step_name)

        program_file = f"{step_name}.md"
        rc = self.agent.run(
            self.repo_path,
            program_content=program,
            program_file=program_file,
            env=env,
            on_output=callback,
        )

        self.state.append_log({
            "event": "skill_completed",
            "step": step_name,
            "skill": skill_file,
            "exit_code": rc,
        })
        return rc

    # -- checkpoints -------------------------------------------------------

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
                self.state.clear_awaiting_review()
                self.state.append_log({"event": "review_skipped", "review_type": review_type, "reason": "paused"})
                break
            if deadline and time.monotonic() > deadline:
                self.state.clear_awaiting_review()
                self.state.append_log({"event": "review_timeout", "review_type": review_type})
                break
            time.sleep(1.0)

    # -- bootstrap ----------------------------------------------------------

    def run_bootstrap(self) -> int:
        """Run all bootstrap steps defined in ``protocol.yaml``.

        Returns 0 if every step succeeds, or the first non-zero exit code.
        """
        protocol = self._load_protocol()
        bootstrap_steps = protocol.get("bootstrap", [])

        for step_name in bootstrap_steps:
            # Bootstrap steps reference skill files by name (e.g. "scout" -> "scout.md")
            skill_file = f"{step_name}.md"
            rc = self._run_skill(step_name, skill_file)
            if rc != 0:
                logger.warning("Bootstrap step %r failed with rc=%d", step_name, rc)
                return rc
            review_type = self._checkpoint_type(step_name, 0)
            if review_type:
                self._await_review(review_type)
        return 0

    # -- single round -------------------------------------------------------

    def run_one_round(self, round_num: int) -> int:
        """Run one iteration of the research loop.

        Checks for pause and skip before executing each step.

        Returns 0 on success, non-zero on failure.  Returns -1 if
        the round was skipped.
        """
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

    # -- serial loop --------------------------------------------------------

    def _frontier_all_done(self) -> bool:
        """Return True if every frontier item is archived or rejected."""
        graph = self.state.load_graph()
        frontier = graph.get("frontier", [])
        if not frontier:
            return False  # empty frontier is not "all done"
        return all(
            item.get("status") in ("archived", "rejected")
            for item in frontier
        )

    def run_parallel(
        self,
        pool_factory: "Callable[[], Any]",
    ) -> int:
        """Run the parallel research loop: bootstrap → (manager → critic → workers → critic) × N.

        Parameters
        ----------
        pool_factory:
            Callable returning a fresh ``WorkerPool`` instance.
            Called each round so workers get fresh skill content.

        Returns 0 on clean completion, non-zero on failure.
        """
        # -- bootstrap --
        rc = self.run_bootstrap()
        if rc != 0:
            return rc

        config = self.state.load_config()
        max_rounds = config.get("limits", {}).get("max_rounds", 20)

        for round_num in range(1, max_rounds + 1):
            if self.state.is_paused():
                self.state.append_log({"event": "loop_paused", "round": round_num})
                self.state.update_phase("paused", round_num)
                break

            self._critic_call_count_this_round = 0
            self.state.update_phase("round", round_num)
            self.state.append_log({"event": "round_started", "round": round_num})

            # Step 1: Manager — proposes hypotheses & frontier items
            rc = self._run_skill("manager", "manager.md")
            if rc != 0:
                return rc
            self._critic_call_count_this_round = 0
            review_type = self._checkpoint_type("manager", round_num)
            if review_type:
                self._await_review(review_type)

            # Step 2: Critic preflight — approve/reject draft frontier items
            rc = self._run_skill("critic", "critic.md")
            if rc != 0:
                return rc
            self._critic_call_count_this_round += 1
            review_type = self._checkpoint_type("critic", round_num)
            if review_type:
                self._await_review(review_type)

            # Step 3: Parallel workers — run approved experiments
            self.state.update_phase("experiment")
            self.state.append_log({"event": "parallel_workers_started", "round": round_num})

            pool = pool_factory()
            pool.run()
            timeout_min = config.get("limits", {}).get("timeout_minutes", 0)
            pool_timeout = timeout_min * 60 if timeout_min > 0 else None
            pool.wait(timeout=pool_timeout)
            if pool_timeout is not None:
                pool.stop()  # signal remaining workers to finish

            self.state.append_log({"event": "parallel_workers_finished", "round": round_num})

            # Step 4: Critic post-review — evaluate results
            rc = self._run_skill("critic", "critic.md")
            if rc != 0:
                return rc
            self._critic_call_count_this_round += 1
            review_type = self._checkpoint_type("critic", round_num)
            if review_type:
                self._await_review(review_type)

            self.state.append_log({"event": "round_completed", "round": round_num})

            if self._frontier_all_done():
                self.state.append_log({"event": "frontier_complete", "round": round_num})
                break

        self.state.update_phase("idle")
        return 0

    def run_serial(self) -> int:
        """Run the full serial research loop: bootstrap then N rounds.

        Respects ``limits.max_rounds`` from config, pause control, and
        stops early if all frontier items are terminal.

        Returns 0 on clean completion, or a non-zero exit code on failure.
        """
        # -- bootstrap --
        rc = self.run_bootstrap()
        if rc != 0:
            return rc

        # -- loop rounds --
        config = self.state.load_config()
        max_rounds = config.get("limits", {}).get("max_rounds", 20)

        for round_num in range(1, max_rounds + 1):
            # Check pause before starting a round
            if self.state.is_paused():
                self.state.append_log({"event": "loop_paused", "round": round_num})
                self.state.update_phase("paused", round_num)
                break

            rc = self.run_one_round(round_num)
            if rc == -2:
                # Paused during round — stop the loop
                break
            if rc == -1:
                # Skipped — continue to next round
                continue
            if rc != 0:
                return rc

            # Check if all frontier items are terminal
            if self._frontier_all_done():
                self.state.append_log({
                    "event": "frontier_complete",
                    "round": round_num,
                })
                break

        self.state.update_phase("idle")
        return 0
