"""Headless mode — structured JSON Lines logging for the research-v1 runtime."""

from __future__ import annotations

from pathlib import Path

from open_researcher.agent_runtime import resolve_agent
from open_researcher.bootstrap import ensure_bootstrap_state, run_bootstrap_prepare
from open_researcher.config import load_config, require_supported_protocol
from open_researcher.event_journal import EventJournal
from open_researcher.graph_protocol import (
    initialize_graph_runtime_state,
    resolve_role_agent_name,
)
from open_researcher.parallel_runtime import run_parallel_experiment_batch
from open_researcher.research_events import (
    RoleFailed,
    ReviewAutoConfirmed,
    SessionCompleted,
    SessionFailed,
    SessionStarted,
)
from open_researcher.research_loop import (
    ResearchLoop,
)
from open_researcher.research_loop import (
    has_pending_ideas as _has_pending_ideas,
)
from open_researcher.research_loop import (
    read_latest_status as _read_latest_status,
)
from open_researcher.research_loop import (
    set_paused as _set_paused,
)
from open_researcher.workflow_options import apply_worker_override

_resolve_agent = resolve_agent


class HeadlessLogger:
    """Emit structured JSON Lines events to a stream and optional log file."""

    def __init__(self, stream=None, log_path: Path | None = None):
        self._journal = EventJournal(log_path or Path("events.jsonl"), stream=stream)

    def emit(self, level: str, phase: str, event: str, **kwargs) -> None:
        self._journal.emit(level, phase, event, **kwargs)

    def make_output_callback(self, phase: str):
        """Return a callback compatible with agent.run(on_output=...)."""

        def on_output(line: str):
            self.emit("info", phase, "agent_output", detail=line)

        return on_output

    def on_event(self, event) -> None:
        """Render a typed research event as a JSONL record."""
        self._journal.emit_typed(event)

    def close(self):
        self._journal.close()


def _resolve_scout_agent(cfg, *, primary_agent_name: str | None):
    return _resolve_agent(
        resolve_role_agent_name(cfg, "scout_agent", primary_agent_name),
        cfg.agent_config,
    )


def _resolve_research_agents(
    cfg,
    *,
    primary_agent_name: str | None,
):
    manager_agent = _resolve_agent(
        resolve_role_agent_name(cfg, "manager_agent", primary_agent_name),
        cfg.agent_config,
    )
    critic_agent = _resolve_agent(
        resolve_role_agent_name(cfg, "critic_agent", primary_agent_name),
        cfg.agent_config,
    )
    exp_agent = _resolve_agent(
        resolve_role_agent_name(cfg, "experiment_agent", primary_agent_name),
        cfg.agent_config,
    )
    return manager_agent, critic_agent, exp_agent


def _read_goal_text(research: Path) -> str:
    goal_path = research / "goal.md"
    if not goal_path.exists():
        return ""
    try:
        return goal_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _build_parallel_runner(
    *,
    repo_path: Path,
    research_dir: Path,
    cfg,
    exp_agent,
    logger: HeadlessLogger,
):
    if cfg.max_workers == 1:
        return None
    return lambda **kwargs: run_parallel_experiment_batch(
        repo_path,
        research_dir,
        cfg,
        exp_agent,
        logger.make_output_callback("experimenting"),
        **kwargs,
    )


def _finalize_headless_session(
    logger: HeadlessLogger,
    loop: ResearchLoop,
    *,
    scout_code: int | None = None,
) -> int:
    if scout_code not in {None, 0}:
        logger.on_event(SessionFailed(failed_role="scout", exit_code=scout_code))
        return int(scout_code)

    failed_role = loop.last_failed_role
    if failed_role:
        failed_code = int(loop.last_exit_codes.get(failed_role, 1))
        logger.on_event(RoleFailed(role=failed_role, exit_code=failed_code))
        logger.on_event(SessionFailed(failed_role=failed_role, exit_code=failed_code))
        return failed_code or 1

    if loop.had_experiment_failure or loop.last_stop_reason == "crash_limit":
        failed_code = int(loop.last_experiment_failure_code or loop.last_exit_codes.get("exp", 1) or 1)
        logger.on_event(RoleFailed(role="experiment", exit_code=failed_code))
        logger.on_event(SessionFailed(failed_role="experiment", exit_code=failed_code))
        return failed_code

    logger.on_event(SessionCompleted())
    return 0


def do_run_headless(
    repo_path: Path,
    *,
    max_experiments: int = 0,
    agent_name: str | None = None,
    workers: int | None = None,
    stream=None,
) -> int:
    """Continue an existing research-v1 workflow in headless mode."""
    research = repo_path / ".research"
    if not research.is_dir():
        raise SystemExit(1)

    cfg = apply_worker_override(load_config(research, strict=True), workers)
    require_supported_protocol(cfg)
    initialize_graph_runtime_state(research, cfg)
    ensure_bootstrap_state(research / "bootstrap_state.json")
    if max_experiments > 0:
        cfg.max_experiments = max_experiments
    effective_max = cfg.max_experiments

    logger = HeadlessLogger(stream=stream, log_path=research / "events.jsonl")
    manager_agent, critic_agent, exp_agent = _resolve_research_agents(
        cfg,
        primary_agent_name=agent_name,
    )

    try:
        logger.on_event(
            SessionStarted(
                goal=_read_goal_text(research),
                max_experiments=effective_max,
                repo=str(repo_path),
            )
        )
        loop = ResearchLoop(
            repo_path,
            research,
            cfg,
            logger.on_event,
            has_pending_ideas_fn=_has_pending_ideas,
            read_latest_status_fn=_read_latest_status,
            pause_fn=_set_paused,
        )
        parallel_runner = _build_parallel_runner(
            repo_path=repo_path,
            research_dir=research,
            cfg=cfg,
            exp_agent=exp_agent,
            logger=logger,
        )
        prepare_code, _state = run_bootstrap_prepare(
            repo_path,
            research,
            cfg,
            on_prepare_event=logger.on_event,
        )
        if prepare_code != 0:
            logger.on_event(RoleFailed(role="prepare", exit_code=prepare_code))
            logger.on_event(SessionFailed(failed_role="prepare", exit_code=prepare_code))
            return prepare_code
        loop.run_graph_protocol(
            manager_agent,
            critic_agent,
            exp_agent,
            max_experiments=effective_max,
            parallel_batch_runner=parallel_runner,
        )
        return _finalize_headless_session(logger, loop)
    finally:
        manager_agent.terminate()
        critic_agent.terminate()
        exp_agent.terminate()
        logger.close()


def do_start_headless(
    repo_path: Path,
    goal: str,
    max_experiments: int = 0,
    agent_name: str | None = None,
    tag: str | None = None,
    workers: int | None = None,
    stream=None,
) -> int:
    """Run the full bootstrap flow without TUI — structured JSON Lines to stdout."""
    from datetime import date

    from open_researcher.run_cmd import do_start_init, render_scout_program

    if tag is None:
        tag = date.today().strftime("%b%d").lower()

    research = do_start_init(repo_path, tag=tag)
    cfg = apply_worker_override(load_config(research, strict=True), workers)
    require_supported_protocol(cfg)
    initialize_graph_runtime_state(research, cfg)
    ensure_bootstrap_state(research / "bootstrap_state.json")

    if max_experiments > 0:
        cfg.max_experiments = max_experiments
    effective_max = cfg.max_experiments

    logger = HeadlessLogger(stream=stream, log_path=research / "events.jsonl")
    logger.on_event(
        SessionStarted(
            goal=goal,
            max_experiments=effective_max,
            repo=str(repo_path),
        )
    )

    scout_agent = _resolve_scout_agent(cfg, primary_agent_name=agent_name)
    manager_agent, critic_agent, exp_agent = _resolve_research_agents(
        cfg,
        primary_agent_name=agent_name,
    )

    try:
        render_scout_program(research, tag=tag, goal=goal)
        (research / "goal.md").write_text(f"# Research Goal\n\n{goal}\n")

        loop = ResearchLoop(
            repo_path,
            research,
            cfg,
            logger.on_event,
            has_pending_ideas_fn=_has_pending_ideas,
            read_latest_status_fn=_read_latest_status,
            pause_fn=_set_paused,
        )

        code = loop.run_scout(scout_agent)
        if code != 0:
            _finalize_headless_session(logger, loop, scout_code=code)
            return code

        cfg = apply_worker_override(load_config(research, strict=True), workers)
        require_supported_protocol(cfg)
        if max_experiments > 0:
            cfg.max_experiments = max_experiments
        initialize_graph_runtime_state(research, cfg)
        prepare_code, _state = run_bootstrap_prepare(
            repo_path,
            research,
            cfg,
            on_prepare_event=logger.on_event,
        )
        if prepare_code != 0:
            logger.on_event(RoleFailed(role="prepare", exit_code=prepare_code))
            logger.on_event(SessionFailed(failed_role="prepare", exit_code=prepare_code))
            return prepare_code

        logger.on_event(ReviewAutoConfirmed())

        parallel_runner = _build_parallel_runner(
            repo_path=repo_path,
            research_dir=research,
            cfg=cfg,
            exp_agent=exp_agent,
            logger=logger,
        )

        loop.run_graph_protocol(
            manager_agent,
            critic_agent,
            exp_agent,
            max_experiments=effective_max,
            parallel_batch_runner=parallel_runner,
        )

        return _finalize_headless_session(logger, loop)
    finally:
        scout_agent.terminate()
        manager_agent.terminate()
        critic_agent.terminate()
        exp_agent.terminate()
        logger.close()
