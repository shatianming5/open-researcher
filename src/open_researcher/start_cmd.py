"""Start command — zero-config launch with Scout analysis + TUI review."""

import threading
from datetime import date
from pathlib import Path

from jinja2 import Environment, PackageLoader
from rich.console import Console

from open_researcher.config import load_config
from open_researcher.run_cmd import _resolve_agent

console = Console()


def render_scout_program(research_dir: Path, tag: str, goal: str | None) -> None:
    """Render scout_program.md with optional goal."""
    env = Environment(loader=PackageLoader("open_researcher", "templates"))
    template = env.get_template("scout_program.md.j2")
    content = template.render(tag=tag, goal=goal or "")
    (research_dir / "scout_program.md").write_text(content)


def do_start_init(repo_path: Path, tag: str | None = None) -> Path:
    """Auto-initialize .research/ if needed, return research dir path."""
    research = repo_path / ".research"

    if research.is_dir():
        console.print("[dim]Using existing .research/ directory.[/dim]")
        return research

    # Run full init
    from open_researcher.init_cmd import do_init

    if tag is None:
        tag = date.today().strftime("%b%d").lower()

    do_init(repo_path, tag=tag)
    return research


def do_start(
    repo_path: Path,
    agent_name: str | None = None,
    tag: str | None = None,
    multi: bool = False,
    idea_agent_name: str | None = None,
    exp_agent_name: str | None = None,
) -> None:
    """Execute the start command: auto-init -> Scout -> Review -> Experiment."""
    from open_researcher.run_cmd import (
        _launch_agent_thread,
        _make_safe_output,
    )
    from open_researcher.tui.app import ResearchApp
    from open_researcher.tui.modals import GoalInputModal
    from open_researcher.tui.review import ReviewScreen
    from open_researcher.watchdog import TimeoutWatchdog

    # Phase 0: Bootstrap — auto init
    if tag is None:
        tag = date.today().strftime("%b%d").lower()
    research = do_start_init(repo_path, tag=tag)
    cfg = load_config(research)

    # Resolve agents
    scout_agent = _resolve_agent(agent_name, cfg.agent_config)
    if multi or idea_agent_name or exp_agent_name:
        idea_agent = _resolve_agent(idea_agent_name or agent_name, cfg.agent_config)
        exp_agent = _resolve_agent(exp_agent_name or agent_name, cfg.agent_config)
    else:
        idea_agent = None
        exp_agent = None

    # State
    stop = threading.Event()
    exit_codes: dict[str, int] = {}
    on_output_ref: list = []

    def _on_review_result(result: str | None) -> None:
        """Handle ReviewScreen dismissal."""
        if result == "confirm":
            app.app_phase = "experimenting"
            _start_experiment_agents()
        elif result == "reanalyze":
            app.app_phase = "scouting"
            _launch_scout()
        else:
            app.exit()

    def _show_review() -> None:
        """Push ReviewScreen onto the app."""
        app.push_screen(ReviewScreen(research), _on_review_result)

    def _launch_scout() -> None:
        """Launch Scout Agent and transition to ReviewScreen when done."""
        on_output = on_output_ref[0] if on_output_ref else _make_safe_output(app.append_log, research / "run.log")
        if not on_output_ref:
            on_output_ref.append(on_output)
        done_scout = threading.Event()

        def _after_scout():
            done_scout.wait()
            code = exit_codes.get("scout", -1)
            if code != 0:
                app.call_from_thread(
                    app.notify, f"Scout Agent failed (code={code}). Check logs.", severity="error"
                )
            app.app_phase = "reviewing"
            app.call_from_thread(_show_review)

        _launch_agent_thread(
            scout_agent, repo_path, on_output, done_scout, exit_codes, "scout",
            program_file="scout_program.md",
        )
        threading.Thread(target=_after_scout, daemon=True).start()

    def _on_goal_result(goal: str | None) -> None:
        """Called when user submits or skips the goal input."""
        render_scout_program(research, tag=tag, goal=goal)
        if goal:
            (research / "goal.md").write_text(f"# Research Goal\n\n{goal}\n")
        app.app_phase = "scouting"
        _launch_scout()

    def _start_experiment_agents():
        """Transition to experiment phase — launch idea + experiment agents."""
        from open_researcher.crash_counter import CrashCounter
        from open_researcher.phase_gate import PhaseGate
        from open_researcher.run_cmd import _has_pending_ideas, _read_latest_status, _set_paused

        on_output = on_output_ref[0] if on_output_ref else _make_safe_output(app.append_log, research / "run.log")

        if multi and idea_agent and exp_agent:
            # Dual-agent mode
            crash_counter = CrashCounter(cfg.max_crashes)
            phase_gate = PhaseGate(research, cfg.mode)
            watchdog = TimeoutWatchdog(cfg.timeout, on_timeout=lambda: exp_agent.terminate())

            def _alternating():
                cycle = 0
                while not stop.is_set():
                    cycle += 1
                    on_output(f"[system] === Cycle {cycle}: Starting Idea Agent ===")
                    try:
                        code = idea_agent.run(
                            repo_path, on_output=on_output, program_file="idea_program.md"
                        )
                    except Exception as exc:
                        on_output(f"[idea] Agent error: {exc}")
                        code = 1
                    exit_codes["idea"] = code

                    if not _has_pending_ideas(research):
                        on_output("[system] No pending ideas. Stopping.")
                        break

                    exp_run = 0
                    while not stop.is_set():
                        exp_run += 1
                        watchdog.reset()
                        try:
                            code = exp_agent.run(
                                repo_path, on_output=on_output, program_file="experiment_program.md"
                            )
                        except Exception as exc:
                            on_output(f"[exp] Agent error: {exc}")
                            code = 1
                        watchdog.stop()
                        exit_codes["exp"] = code

                        status = _read_latest_status(research)
                        if status and crash_counter.record(status):
                            on_output(f"[system] Crash limit reached. Pausing.")
                            _set_paused(research, f"Crash limit: {cfg.max_crashes}")
                            stop.set()
                            break

                        phase = phase_gate.check()
                        if phase:
                            on_output(f"[system] Phase transition to '{phase}'.")
                            _set_paused(research, f"Phase: {phase}")
                            break

                        if not _has_pending_ideas(research):
                            break
                        on_output("[exp] Pending ideas remain, restarting...")

                    if stop.is_set():
                        break

                watchdog.stop()
                on_output("[system] All cycles finished.")

            threading.Thread(target=_alternating, daemon=True).start()
        else:
            # Single-agent mode — use program.md
            agent = scout_agent  # Reuse the same agent
            watchdog = TimeoutWatchdog(cfg.timeout, on_timeout=lambda: agent.terminate())
            watchdog.start()
            done = threading.Event()
            _launch_agent_thread(agent, repo_path, on_output, done, exit_codes, "agent",
                                 program_file="program.md")

    def start_app():
        """Called on app mount (already on event loop thread)."""
        app.push_screen(GoalInputModal(), _on_goal_result)

    app = ResearchApp(repo_path, multi=bool(multi or idea_agent_name), on_ready=start_app, initial_phase="scouting")
    try:
        app.run()
    finally:
        stop.set()
        if on_output_ref and hasattr(on_output_ref[0], 'close'):
            on_output_ref[0].close()
        scout_agent.terminate()
        if idea_agent:
            idea_agent.terminate()
        if exp_agent:
            exp_agent.terminate()

    # Print summary
    for key, name in [("scout", "Scout"), ("idea", "Idea Agent"), ("exp", "Experiment Agent"), ("agent", "Agent")]:
        code = exit_codes.get(key)
        if code is not None:
            if code == 0:
                console.print(f"[green]{name} completed successfully.[/green]")
            else:
                console.print(f"[red]{name} exited with code {code}.[/red]")

    from open_researcher.status_cmd import print_status
    print_status(repo_path)
