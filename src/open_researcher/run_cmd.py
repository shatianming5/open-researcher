"""Run command — launch the research-v1 runtime with interactive Textual TUI."""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path

from jinja2 import Environment, PackageLoader
from rich.console import Console

from open_researcher.agent_runtime import resolve_agent
from open_researcher.agents import detect_agent, get_agent
from open_researcher.bootstrap import (
    ensure_bootstrap_state,
    format_bootstrap_dry_run,
    run_bootstrap_prepare,
)
from open_researcher.config import load_config, require_supported_protocol
from open_researcher.graph_protocol import (
    initialize_graph_runtime_state,
    resolve_role_agent_name,
)
from open_researcher.parallel_runtime import run_parallel_experiment_batch
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
from open_researcher.role_programs import resolve_role_program_file
from open_researcher.tui_runner import (
    print_exit_summary,
    run_tui_session,
    start_daemon,
)
from open_researcher.workflow_options import apply_worker_override

console = Console()


def _resolve_agent(agent_name: str | None, agent_configs: dict | None = None):
    """Resolve agent by name or auto-detect, with per-agent config."""
    return resolve_agent(
        agent_name,
        agent_configs,
        detect_agent_fn=detect_agent,
        get_agent_fn=get_agent,
        console_obj=console,
    )


def _overall_exit_code(exit_codes: dict[str, int], *, crash_limited: bool = False) -> int:
    if crash_limited:
        return int(exit_codes.get("exp", 1) or 1)
    for key in ("prepare", "scout", "manager", "critic", "exp"):
        code = int(exit_codes.get(key, 0) or 0)
        if code != 0:
            return code
    return 0


def render_scout_program(research_dir: Path, tag: str, goal: str | None) -> None:
    """Render scout_program.md with optional goal."""
    env = Environment(loader=PackageLoader("open_researcher", "templates"))
    template = env.get_template("scout_program.md.j2")
    content = template.render(tag=tag, goal=goal or "")
    (research_dir / "scout_program.md").write_text(content)


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
    """Resolve manager/critic/experiment roles for research-v1."""
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


def _build_parallel_runner(
    *,
    repo_path: Path,
    research_dir: Path,
    cfg,
    exp_agent,
    renderer,
):
    if cfg.max_workers == 1:
        return None
    return lambda **kwargs: run_parallel_experiment_batch(
        repo_path,
        research_dir,
        cfg,
        exp_agent,
        renderer.make_output_callback("experimenting"),
        **kwargs,
    )


def _load_runtime_config(research: Path, *, workers: int | None, max_experiments: int = 0, token_budget: int = 0):
    cfg = apply_worker_override(load_config(research, strict=True), workers)
    require_supported_protocol(cfg)
    if max_experiments > 0:
        cfg.max_experiments = max_experiments
    if token_budget > 0:
        cfg.token_budget = token_budget
    return cfg


def _run_prepare_then_graph(
    *,
    app,
    loop: ResearchLoop,
    repo_path: Path,
    research: Path,
    cfg,
    exit_codes: dict[str, int],
    stop: threading.Event,
    manager_agent,
    critic_agent,
    exp_agent,
    parallel_runner,
    event_handler,
) -> None:
    prepare_code, _state = run_bootstrap_prepare(
        repo_path,
        research,
        cfg,
        on_prepare_event=event_handler,
    )
    exit_codes["prepare"] = prepare_code
    if prepare_code != 0:
        try:
            app.call_from_thread(
                app.notify,
                f"Prepare failed (code={prepare_code}). See .research/prepare.log.",
                severity="error",
            )
            app.call_from_thread(app.exit)
        except RuntimeError:
            pass
        return
    exit_codes.update(
        loop.run_graph_protocol(
            manager_agent,
            critic_agent,
            exp_agent,
            stop=stop,
            parallel_batch_runner=parallel_runner,
        )
    )


def do_start_init(repo_path: Path, tag: str | None = None) -> Path:
    """Auto-initialize .research/ if needed, return research dir path."""
    research = repo_path / ".research"
    if research.is_dir():
        console.print("[dim]Using existing .research/ directory.[/dim]")
        ensure_bootstrap_state(research / "bootstrap_state.json")
        return research

    from open_researcher.init_cmd import do_init

    if tag is None:
        tag = date.today().strftime("%b%d").lower()

    do_init(repo_path, tag=tag)
    ensure_bootstrap_state(research / "bootstrap_state.json")
    return research


def do_run(
    repo_path: Path,
    agent_name: str | None,
    dry_run: bool,
    workers: int | None = None,
    max_experiments: int = 0,
    token_budget: int = 0,
) -> int:
    """Continue an existing research-v1 workflow in the TUI."""
    research = repo_path / ".research"
    if not research.is_dir():
        console.print("[red]Error:[/red] .research/ not found. Run 'open-researcher init' first.")
        raise SystemExit(1)

    cfg = _load_runtime_config(research, workers=workers, max_experiments=max_experiments, token_budget=token_budget)
    initialize_graph_runtime_state(research, cfg)
    ensure_bootstrap_state(research / "bootstrap_state.json")
    manager_agent, critic_agent, exp_agent = _resolve_research_agents(
        cfg,
        primary_agent_name=agent_name,
    )

    if dry_run:
        console.print(f"[bold]Manager Agent:[/bold] {manager_agent.name}")
        console.print(f"[bold]Critic Agent:[/bold] {critic_agent.name}")
        console.print(f"[bold]Experiment Agent:[/bold] {exp_agent.name}")
        for line in format_bootstrap_dry_run(repo_path, research, cfg):
            console.print(line)
        exp_program = research / resolve_role_program_file(research, "experiment")
        console.print(
            f"[bold]Command:[/bold] {' '.join(exp_agent.build_command(exp_program, repo_path))}"
        )
        console.print(f"[bold]Working directory:[/bold] {repo_path}")
        console.print("\n[dim]Dry run -- no runtime launched.[/dim]")
        return 0

    stop = threading.Event()
    exit_codes: dict[str, int] = {}
    loop_ref: dict[str, ResearchLoop] = {}

    def setup(app, renderer):
        assert renderer is not None
        loop = ResearchLoop(
            repo_path,
            research,
            cfg,
            renderer.on_event,
            has_pending_ideas_fn=_has_pending_ideas,
            read_latest_status_fn=_read_latest_status,
            pause_fn=_set_paused,
        )
        loop_ref["loop"] = loop
        parallel_runner = _build_parallel_runner(
            repo_path=repo_path,
            research_dir=research,
            cfg=cfg,
            exp_agent=exp_agent,
            renderer=renderer,
        )
        start_daemon(
            lambda: _run_prepare_then_graph(
                app=app,
                loop=loop,
                repo_path=repo_path,
                research=research,
                cfg=cfg,
                exit_codes=exit_codes,
                stop=stop,
                manager_agent=manager_agent,
                critic_agent=critic_agent,
                exp_agent=exp_agent,
                parallel_runner=parallel_runner,
                event_handler=renderer.on_event,
            )
        )
        return [stop.set, manager_agent.terminate, critic_agent.terminate, exp_agent.terminate]

    run_tui_session(repo_path, research_dir=research, setup=setup)
    print_exit_summary(
        console,
        exit_codes,
        [
            ("prepare", "Prepare"),
            ("manager", "Research Manager"),
            ("critic", "Research Critic"),
            ("exp", "Experiment Agent"),
        ],
        show_missing=True,
    )

    from open_researcher.status_cmd import print_status

    print_status(repo_path)
    loop = loop_ref.get("loop")
    return _overall_exit_code(
        exit_codes,
        crash_limited=bool(loop and loop.last_stop_reason == "crash_limit"),
    )


def do_start(
    repo_path: Path,
    agent_name: str | None = None,
    tag: str | None = None,
    workers: int | None = None,
    goal: str | None = None,
    max_experiments: int = 0,
    token_budget: int = 0,
) -> int:
    """Bootstrap a research-v1 workflow: init -> Scout -> Review -> runtime."""
    from open_researcher.tui.modals import GoalInputModal
    from open_researcher.tui.review import ReviewScreen

    if tag is None:
        tag = date.today().strftime("%b%d").lower()
    research = do_start_init(repo_path, tag=tag)
    cfg = _load_runtime_config(research, workers=workers, max_experiments=max_experiments, token_budget=token_budget)
    initialize_graph_runtime_state(research, cfg)
    ensure_bootstrap_state(research / "bootstrap_state.json")

    scout_agent = _resolve_scout_agent(cfg, primary_agent_name=agent_name)
    manager_agent, critic_agent, exp_agent = _resolve_research_agents(
        cfg,
        primary_agent_name=agent_name,
    )

    stop = threading.Event()
    exit_codes: dict[str, int] = {}
    loop_ref: dict[str, ResearchLoop] = {}
    cfg_ref = {"cfg": cfg}

    def setup(app, renderer):
        assert renderer is not None
        loop = ResearchLoop(repo_path, research, cfg_ref["cfg"], renderer.on_event)
        loop_ref["loop"] = loop

        def _show_review() -> None:
            app.push_screen(ReviewScreen(research), _on_review_result)

        def _launch_scout() -> None:
            def _run_scout():
                exit_codes["scout"] = loop.run_scout(scout_agent)
                if stop.is_set():
                    return
                code = exit_codes.get("scout", -1)
                if code != 0:
                    try:
                        app.call_from_thread(
                            app.notify,
                            f"Scout Agent failed (code={code}). Check logs.",
                            severity="error",
                        )
                    except RuntimeError:
                        pass
                    return
                refreshed_cfg = _load_runtime_config(
                    research, workers=workers, max_experiments=max_experiments, token_budget=token_budget
                )
                initialize_graph_runtime_state(research, refreshed_cfg)
                ensure_bootstrap_state(research / "bootstrap_state.json")
                cfg_ref["cfg"] = refreshed_cfg
                loop.cfg = refreshed_cfg
                prepare_code, _ = run_bootstrap_prepare(
                    repo_path,
                    research,
                    refreshed_cfg,
                    on_prepare_event=renderer.on_event,
                )
                exit_codes["prepare"] = prepare_code
                if prepare_code != 0:
                    try:
                        app.call_from_thread(
                            app.notify,
                            f"Prepare failed (code={prepare_code}). See .research/prepare.log.",
                            severity="error",
                        )
                        app.call_from_thread(app.exit)
                    except RuntimeError:
                        pass
                    return
                try:
                    app.call_from_thread(setattr, app, "app_phase", "reviewing")
                    app.call_from_thread(_show_review)
                except RuntimeError:
                    pass

            start_daemon(_run_scout)

        def _start_runtime() -> None:
            parallel_runner = _build_parallel_runner(
                repo_path=repo_path,
                research_dir=research,
                cfg=cfg_ref["cfg"],
                exp_agent=exp_agent,
                renderer=renderer,
            )
            start_daemon(
                lambda: exit_codes.update(
                    loop.run_graph_protocol(
                        manager_agent,
                        critic_agent,
                        exp_agent,
                        stop=stop,
                        parallel_batch_runner=parallel_runner,
                    )
                )
            )

        def _on_review_result(result: str | None) -> None:
            if result == "confirm":
                app.app_phase = "experimenting"
                _start_runtime()
            elif result == "reanalyze":
                app.app_phase = "scouting"
                _launch_scout()
            else:
                app.exit()

        def _on_goal_result(goal: str | None) -> None:
            render_scout_program(research, tag=tag, goal=goal)
            if goal:
                (research / "goal.md").write_text(f"# Research Goal\n\n{goal}\n")
            app.app_phase = "scouting"
            _launch_scout()

        if goal is not None:
            _on_goal_result(goal)
        else:
            app.push_screen(GoalInputModal(), _on_goal_result)
        return [
            stop.set,
            scout_agent.terminate,
            manager_agent.terminate,
            critic_agent.terminate,
            exp_agent.terminate,
        ]

    run_tui_session(
        repo_path,
        research_dir=research,
        initial_phase="scouting",
        setup=setup,
    )
    print_exit_summary(
        console,
        exit_codes,
        [
            ("scout", "Scout"),
            ("prepare", "Prepare"),
            ("manager", "Research Manager"),
            ("critic", "Research Critic"),
            ("exp", "Experiment Agent"),
        ],
    )

    from open_researcher.status_cmd import print_status

    print_status(repo_path)
    loop = loop_ref.get("loop")
    return _overall_exit_code(
        exit_codes,
        crash_limited=bool(loop and loop.last_stop_reason == "crash_limit"),
    )
