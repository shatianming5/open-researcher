"""Run command — launch AI agents with interactive Textual TUI."""

import json
import threading
import time
from pathlib import Path

from rich.console import Console

from open_researcher.agents import detect_agent, get_agent

console = Console()


def _launch_agent_thread(
    agent,
    workdir: Path,
    on_output,
    done_event: threading.Event,
    exit_codes: dict,
    key: str,
    program_file: str = "program.md",
):
    """Run an agent in a background thread."""

    def _run():
        try:
            code = agent.run(workdir, on_output=on_output, program_file=program_file)
        except Exception:
            code = 1
        exit_codes[key] = code
        done_event.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def _has_pending_ideas(research_dir: Path) -> bool:
    """Check if idea_pool.json has any pending ideas."""
    pool_path = research_dir / "idea_pool.json"
    if not pool_path.exists():
        return False
    try:
        data = json.loads(pool_path.read_text())
        return any(i["status"] == "pending" for i in data.get("ideas", []))
    except (json.JSONDecodeError, OSError):
        return False


def _launch_exp_with_wait(
    agent,
    workdir: Path,
    on_output,
    done_event: threading.Event,
    exit_codes: dict,
    stop_event: threading.Event,
):
    """Wait for ideas in the pool, then run experiment agent. Restart if more ideas remain."""
    research = workdir / ".research"

    def _run():
        on_output("[exp] Waiting for Idea Agent to generate ideas...")
        while not stop_event.is_set():
            if _has_pending_ideas(research):
                break
            time.sleep(5)
        if stop_event.is_set():
            exit_codes["exp"] = 0
            done_event.set()
            return

        # Run experiment agent, restart if there are still pending ideas
        run_count = 0
        while not stop_event.is_set():
            run_count += 1
            on_output(f"[exp] Starting experiment agent (run #{run_count})...")
            try:
                code = agent.run(workdir, on_output=on_output, program_file="experiment_program.md")
            except Exception:
                code = 1
            exit_codes["exp"] = code

            # Check if there are still pending ideas to process
            if not _has_pending_ideas(research):
                on_output("[exp] No more pending ideas. Waiting for new ideas...")
                while not stop_event.is_set():
                    if _has_pending_ideas(research):
                        break
                    time.sleep(10)
                if stop_event.is_set():
                    break
            else:
                on_output("[exp] More pending ideas found, restarting...")

        done_event.set()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


def _resolve_agent(agent_name: str | None):
    """Resolve agent by name or auto-detect."""
    if agent_name:
        try:
            return get_agent(agent_name)
        except KeyError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise SystemExit(1)
    agent = detect_agent()
    if agent is None:
        console.print(
            "[red]Error:[/red] No supported AI agent found.\n"
            "Install one of: claude (Claude Code), codex, aider, opencode\n"
            "Or specify with: --agent <name>"
        )
        raise SystemExit(1)
    console.print(f"[green]Auto-detected agent:[/green] {agent.name}")
    return agent


def do_run(repo_path: Path, agent_name: str | None, dry_run: bool) -> None:
    """Single-agent mode — backward compatible."""
    research = repo_path / ".research"
    if not research.is_dir():
        console.print("[red]Error:[/red] .research/ not found. Run 'open-researcher init' first.")
        raise SystemExit(1)

    program_md = research / "program.md"
    if not program_md.exists():
        console.print("[red]Error:[/red] .research/program.md not found.")
        raise SystemExit(1)

    agent = _resolve_agent(agent_name)

    if dry_run:
        console.print(f"[bold]Agent:[/bold] {agent.name}")
        console.print(f"[bold]Command:[/bold] {agent.name} -p <program.md>")
        console.print(f"[bold]Working directory:[/bold] {repo_path}")
        console.print("\n[dim]Dry run -- no agent launched.[/dim]")
        return

    # Launch with Textual TUI
    from open_researcher.tui.app import ResearchApp

    app = ResearchApp(repo_path, multi=False)
    done = threading.Event()
    exit_codes: dict[str, int] = {}

    def on_output(line: str):
        app.append_exp_log(line)
        log_path = research / "run.log"
        with open(log_path, "a") as f:
            f.write(line + "\n")

    _launch_agent_thread(agent, repo_path, on_output, done, exit_codes, "agent")
    app.run()

    # Cleanup: terminate agent subprocess when TUI exits
    agent.terminate()

    code = exit_codes.get("agent", -1)
    if code == 0:
        console.print(f"\n[green]Agent {agent.name} completed successfully.[/green]")
    else:
        console.print(f"\n[red]Agent {agent.name} exited with code {code}.[/red]")

    from open_researcher.status_cmd import print_status

    print_status(repo_path)


def do_run_multi(
    repo_path: Path,
    idea_agent_name: str | None,
    exp_agent_name: str | None,
    dry_run: bool,
) -> None:
    """Dual-agent mode — Idea Agent + Experiment Agent in parallel."""
    research = repo_path / ".research"
    if not research.is_dir():
        console.print("[red]Error:[/red] .research/ not found. Run 'open-researcher init' first.")
        raise SystemExit(1)

    idea_program = research / "idea_program.md"
    exp_program = research / "experiment_program.md"

    for p in [idea_program, exp_program]:
        if not p.exists():
            console.print(f"[red]Error:[/red] {p.name} not found. Re-run 'open-researcher init'.")
            raise SystemExit(1)

    idea_agent = _resolve_agent(idea_agent_name)
    exp_agent = _resolve_agent(exp_agent_name)

    if dry_run:
        console.print(f"[bold]Idea Agent:[/bold] {idea_agent.name}")
        console.print(f"[bold]Experiment Master Agent:[/bold] {exp_agent.name}")
        console.print(f"[bold]Working directory:[/bold] {repo_path}")
        console.print("\n[dim]Dry run -- no agents launched.[/dim]")
        return

    # Ensure worktrees directory exists for parallel experiments
    worktrees_dir = research / "worktrees"
    worktrees_dir.mkdir(exist_ok=True)

    # Launch with Textual TUI
    from open_researcher.tui.app import ResearchApp

    app = ResearchApp(repo_path, multi=True)
    done_idea = threading.Event()
    done_exp = threading.Event()
    stop_exp = threading.Event()
    exit_codes: dict[str, int] = {}

    def on_idea_output(line: str):
        app.append_idea_log(line)
        log_path = research / "idea_agent.log"
        with open(log_path, "a") as f:
            f.write(line + "\n")

    def on_exp_output(line: str):
        app.append_exp_log(line)
        log_path = research / "experiment_agent.log"
        with open(log_path, "a") as f:
            f.write(line + "\n")

    _launch_agent_thread(
        idea_agent,
        repo_path,
        on_idea_output,
        done_idea,
        exit_codes,
        "idea",
        program_file="idea_program.md",
    )
    _launch_exp_with_wait(
        exp_agent,
        repo_path,
        on_exp_output,
        done_exp,
        exit_codes,
        stop_exp,
    )

    app.run()

    # Cleanup: terminate agent subprocesses when TUI exits
    idea_agent.terminate()
    exp_agent.terminate()
    stop_exp.set()  # Signal experiment thread to stop when TUI exits

    for key, name in [("idea", "Idea Agent"), ("exp", "Experiment Master")]:
        code = exit_codes.get(key, -1)
        if code == 0:
            console.print(f"[green]{name} completed successfully.[/green]")
        else:
            console.print(f"[red]{name} exited with code {code}.[/red]")

    from open_researcher.status_cmd import print_status

    print_status(repo_path)
