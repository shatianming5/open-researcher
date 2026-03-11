"""Bootstrap resolution and auto-prepare helpers for local research-v1 runs."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from open_researcher.config import ResearchConfig
from open_researcher.event_journal import now_iso


BOOTSTRAP_STATE_VERSION = "research-v1"
PREPARE_LOG_NAME = "prepare.log"


def _default_step(*, log_path: str) -> dict:
    return {
        "command": "",
        "source": "",
        "status": "pending",
        "started_at": "",
        "finished_at": "",
        "log_path": log_path,
        "detail": "",
    }


def default_bootstrap_state(research_dir: Path) -> dict:
    log_path = str(research_dir / PREPARE_LOG_NAME)
    return {
        "version": BOOTSTRAP_STATE_VERSION,
        "status": "pending",
        "repo_profile": {
            "kind": "unknown",
            "python_project": False,
            "manifests": [],
        },
        "working_dir": ".",
        "python_env": {"executable": "", "source": ""},
        "expected_paths": [],
        "requires_gpu": False,
        "expected_path_status": [],
        "install": _default_step(log_path=log_path),
        "data": _default_step(log_path=log_path),
        "smoke": _default_step(log_path=log_path),
        "errors": [],
        "unresolved": [],
        "updated_at": "",
    }


def ensure_bootstrap_state(path: Path) -> None:
    if path.exists():
        return
    payload = default_bootstrap_state(path.parent)
    payload["updated_at"] = now_iso()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_bootstrap_state(path: Path) -> dict:
    if not path.exists():
        return default_bootstrap_state(path.parent)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        payload = default_bootstrap_state(path.parent)
    if not isinstance(payload, dict):
        payload = default_bootstrap_state(path.parent)
    merged = default_bootstrap_state(path.parent)
    merged.update({k: v for k, v in payload.items() if k in merged})
    for key in ("repo_profile", "python_env", "install", "data", "smoke"):
        value = payload.get(key, {})
        if isinstance(value, dict):
            merged[key].update(value)
    if isinstance(payload.get("expected_path_status"), list):
        merged["expected_path_status"] = [
            item for item in payload["expected_path_status"] if isinstance(item, dict)
        ]
    if isinstance(payload.get("expected_paths"), list):
        merged["expected_paths"] = [str(item) for item in payload["expected_paths"]]
    if isinstance(payload.get("errors"), list):
        merged["errors"] = [str(item) for item in payload["errors"]]
    if isinstance(payload.get("unresolved"), list):
        merged["unresolved"] = [str(item) for item in payload["unresolved"]]
    return merged


def write_bootstrap_state(path: Path, state: dict) -> None:
    payload = default_bootstrap_state(path.parent)
    payload.update({k: v for k, v in state.items() if k in payload})
    for key in ("repo_profile", "python_env", "install", "data", "smoke"):
        if isinstance(state.get(key), dict):
            payload[key].update(state[key])
    payload["updated_at"] = now_iso()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def detect_repo_profile(repo_path: Path) -> dict:
    manifests: list[str] = []
    for name in ("uv.lock", "poetry.lock", "requirements.txt", "pyproject.toml"):
        if (repo_path / name).exists():
            manifests.append(name)
    python_project = bool(manifests) or any((repo_path / name).exists() for name in ("setup.py", "tox.ini"))
    return {
        "kind": "python" if python_project else "unknown",
        "python_project": python_project,
        "manifests": manifests,
    }


def _venv_python_path(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_bin_dir(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts"
    return venv_dir / "bin"


def _explicit_python_candidate(raw: str, *, workdir: Path) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (workdir / candidate).resolve()
    return candidate


def resolve_python_environment(repo_path: Path, workdir: Path, cfg: ResearchConfig) -> tuple[str, str]:
    if cfg.bootstrap_python:
        return str(_explicit_python_candidate(cfg.bootstrap_python, workdir=workdir)), "config.bootstrap.python"

    current_venv = os.environ.get("VIRTUAL_ENV")
    if current_venv:
        candidate = _venv_python_path(Path(current_venv))
        if candidate.exists():
            return str(candidate), "active virtualenv"

    repo_venv = repo_path / ".venv"
    candidate = _venv_python_path(repo_venv)
    if candidate.exists():
        return str(candidate), "repo .venv"

    return str(candidate), "auto-create .venv"


def _looks_like_placeholder(command: str) -> bool:
    text = str(command or "").strip()
    if not text:
        return True
    return text.startswith("#") or "<!--" in text


def _extract_evaluation_command(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    blocks = re.findall(r"```(?:bash)?\n(.*?)```", content, flags=re.DOTALL)
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip() and not line.strip().startswith("#")]
        command = "\n".join(lines).strip()
        if command and not _looks_like_placeholder(command):
            return command
    return ""


def _detect_install_command(repo_path: Path, workdir: Path, python_executable: str, cfg: ResearchConfig) -> tuple[str, str]:
    if cfg.bootstrap_install_command:
        return cfg.bootstrap_install_command.strip(), "config.bootstrap.install_command"
    if (workdir / "uv.lock").exists() and shutil.which("uv"):
        return "uv sync", "uv.lock"
    if (workdir / "poetry.lock").exists() and shutil.which("poetry"):
        return "poetry install", "poetry.lock"
    if (workdir / "requirements.txt").exists():
        return f"{shlex.quote(python_executable)} -m pip install -r requirements.txt", "requirements.txt"
    if (workdir / "pyproject.toml").exists():
        return f"{shlex.quote(python_executable)} -m pip install -e .", "pyproject.toml"
    return "", "none"


def _makefile_targets(workdir: Path) -> set[str]:
    path = workdir / "Makefile"
    if not path.exists():
        return set()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    targets: set[str] = set()
    for line in text.splitlines():
        if not line or line.startswith("\t") or ":" not in line:
            continue
        head = line.split(":", 1)[0].strip()
        if head and " " not in head and not head.startswith("."):
            targets.add(head)
    return targets


def _detect_data_command(workdir: Path, python_executable: str, cfg: ResearchConfig) -> tuple[str, str]:
    if cfg.bootstrap_data_command:
        return cfg.bootstrap_data_command.strip(), "config.bootstrap.data_command"

    targets = _makefile_targets(workdir)
    for target in ("setup", "prepare", "data", "download-data"):
        if target in targets:
            return f"make {target}", f"Makefile:{target}"

    for pattern in ("scripts/prepare*.py", "scripts/download*.py", "data/*/prepare.py"):
        matches = sorted(workdir.glob(pattern))
        if len(matches) == 1 and matches[0].is_file():
            rel = matches[0].relative_to(workdir)
            return f"{shlex.quote(python_executable)} {shlex.quote(str(rel))}", pattern
    return "", "none"


def _detect_smoke_command(repo_path: Path, research_dir: Path, workdir: Path, cfg: ResearchConfig) -> tuple[str, str]:
    if cfg.bootstrap_smoke_command:
        return cfg.bootstrap_smoke_command.strip(), "config.bootstrap.smoke_command"

    evaluation_command = _extract_evaluation_command(research_dir / "evaluation.md")
    if evaluation_command:
        return evaluation_command, "evaluation.md"

    if (workdir / "tests").is_dir() or (workdir / "pytest.ini").exists():
        return "pytest -q", "pytest"

    targets = _makefile_targets(workdir)
    if "test" in targets:
        return "make test", "Makefile:test"

    return "", "none"


def _expected_paths_status(repo_path: Path, expected_paths: list[str]) -> list[dict]:
    items: list[dict] = []
    for raw in expected_paths:
        value = str(raw).strip()
        if not value:
            continue
        path = (repo_path / value).resolve()
        items.append({"path": value, "exists": path.exists()})
    return items


def resolve_bootstrap_plan(repo_path: Path, research_dir: Path, cfg: ResearchConfig) -> dict:
    state = read_bootstrap_state(research_dir / "bootstrap_state.json")
    repo_profile = detect_repo_profile(repo_path)
    working_dir_value = cfg.bootstrap_working_dir or "."
    working_dir = (repo_path / working_dir_value).resolve()
    python_executable, python_source = resolve_python_environment(repo_path, working_dir, cfg)
    install_command, install_source = _detect_install_command(repo_path, working_dir, python_executable, cfg)
    data_command, data_source = _detect_data_command(working_dir, python_executable, cfg)
    smoke_command, smoke_source = _detect_smoke_command(repo_path, research_dir, working_dir, cfg)
    expected_paths = [str(item).strip() for item in cfg.bootstrap_expected_paths if str(item).strip()]
    expected_paths_state = _expected_paths_status(repo_path, expected_paths)
    missing_expected_paths = [item["path"] for item in expected_paths_state if not item.get("exists")]

    errors: list[str] = []
    unresolved: list[str] = []
    if not working_dir.exists():
        errors.append(f"Working directory does not exist: {working_dir_value}")
    if repo_profile["kind"] != "python" and not (
        cfg.bootstrap_install_command or cfg.bootstrap_data_command or cfg.bootstrap_smoke_command
    ):
        unresolved.append("Could not infer a safe auto-prepare path for a non-Python repo.")
    if not smoke_command:
        unresolved.append("Smoke command is unresolved. Fill bootstrap.smoke_command or evaluation.md.")
    if missing_expected_paths and not data_command:
        unresolved.append(
            "Expected paths are missing but no data command was resolved: "
            + ", ".join(missing_expected_paths)
        )
    if cfg.bootstrap_requires_gpu and not shutil.which("nvidia-smi"):
        errors.append("bootstrap.requires_gpu=true but nvidia-smi is not available.")

    install_status = "pending" if install_command else "skipped"
    if unresolved and not smoke_command:
        state["smoke"]["status"] = "unresolved"
    state.update(
        {
            "status": "resolved" if not errors and not unresolved else "unresolved",
            "repo_profile": repo_profile,
            "working_dir": working_dir_value,
            "python_env": {"executable": python_executable, "source": python_source},
            "expected_paths": expected_paths,
            "requires_gpu": bool(cfg.bootstrap_requires_gpu),
            "expected_path_status": expected_paths_state,
            "errors": errors,
            "unresolved": unresolved,
        }
    )
    state["install"].update(
        {
            "command": install_command,
            "source": install_source,
            "status": install_status,
            "detail": "Dependency installation step",
        }
    )
    state["data"].update(
        {
            "command": data_command,
            "source": data_source,
            "status": "pending" if data_command else "skipped",
            "detail": "Dataset/setup step" if data_command else "No data step detected",
        }
    )
    state["smoke"].update(
        {
            "command": smoke_command,
            "source": smoke_source,
            "status": "pending" if smoke_command else "unresolved",
            "detail": "Readiness smoke step" if smoke_command else "No smoke command resolved",
        }
    )
    if not cfg.bootstrap_auto_prepare:
        state["status"] = "disabled"
        state["errors"] = []
        state["unresolved"] = []
        for step_name in _step_names():
            state[step_name]["status"] = "disabled"
            state[step_name]["detail"] = "Auto-prepare disabled"
    state["expected_path_status"] = expected_paths_state
    return state


def _step_names() -> tuple[str, ...]:
    return ("install", "data", "smoke")


def is_prepare_ready(state: dict, repo_path: Path) -> bool:
    if str(state.get("status", "")).strip() != "completed":
        return False
    expected = state.get("expected_paths", [])
    if isinstance(expected, list):
        for raw in expected:
            value = str(raw).strip()
            if value and not (repo_path / value).exists():
                return False
    return str(state.get("smoke", {}).get("status", "")).strip() == "completed"


def _venv_root_from_python(python_executable: str) -> Path | None:
    path = Path(python_executable)
    if not path.exists():
        return None
    parent = path.parent
    root = parent.parent
    pyvenv_cfg = root / "pyvenv.cfg"
    return root if pyvenv_cfg.exists() else None


def _command_env(python_executable: str) -> dict[str, str]:
    env = dict(os.environ)
    venv_root = _venv_root_from_python(python_executable)
    if venv_root is not None:
        bin_dir = _venv_bin_dir(venv_root)
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(venv_root)
    return env


def _append_prepare_log(log_path: Path, step: str, command: str, result: subprocess.CompletedProcess[str]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n== {now_iso()} :: {step} ==\n")
        handle.write(f"$ {command}\n")
        if result.stdout:
            handle.write(result.stdout)
            if not result.stdout.endswith("\n"):
                handle.write("\n")
        if result.stderr:
            handle.write(result.stderr)
            if not result.stderr.endswith("\n"):
                handle.write("\n")
        handle.write(f"[exit_code={result.returncode}]\n")


def _ensure_python_environment(repo_path: Path, state: dict, log_path: Path) -> tuple[int, str]:
    python_executable = str(state.get("python_env", {}).get("executable", "")).strip()
    if not python_executable:
        return 1, "No Python executable resolved."
    path = Path(python_executable)
    if path.exists():
        return 0, ""
    if str(state.get("python_env", {}).get("source", "")).strip() != "auto-create .venv":
        return 1, f"Resolved Python executable does not exist: {python_executable}"

    venv_dir = repo_path / ".venv"
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        cwd=str(repo_path),
        text=True,
        capture_output=True,
    )
    _append_prepare_log(log_path, "python_env", f"{sys.executable} -m venv {venv_dir}", result)
    if result.returncode != 0:
        return result.returncode, "Failed to create .venv"
    return 0, ""


def run_bootstrap_prepare(
    repo_path: Path,
    research_dir: Path,
    cfg: ResearchConfig,
    *,
    on_prepare_event=None,
) -> tuple[int, dict]:
    state_path = research_dir / "bootstrap_state.json"
    ensure_bootstrap_state(state_path)
    state = resolve_bootstrap_plan(repo_path, research_dir, cfg)
    log_path = research_dir / PREPARE_LOG_NAME
    state["install"]["log_path"] = str(log_path)
    state["data"]["log_path"] = str(log_path)
    state["smoke"]["log_path"] = str(log_path)
    write_bootstrap_state(state_path, state)

    if not cfg.bootstrap_auto_prepare:
        state["status"] = "disabled"
        state["errors"] = []
        write_bootstrap_state(state_path, state)
        if on_prepare_event is not None:
            from open_researcher.research_events import PrepareCompleted

            on_prepare_event(PrepareCompleted(status="disabled", unresolved=0))
        return 0, state

    if is_prepare_ready(state, repo_path):
        if on_prepare_event is not None:
            from open_researcher.research_events import PrepareCompleted

            on_prepare_event(PrepareCompleted(status="cached", unresolved=0))
        return 0, state

    if on_prepare_event is not None:
        from open_researcher.research_events import PrepareStarted

        on_prepare_event(
            PrepareStarted(
                repo_profile=str(state.get("repo_profile", {}).get("kind", "")).strip() or "unknown",
                working_dir=str(state.get("working_dir", ".") or "."),
                python_executable=str(state.get("python_env", {}).get("executable", "")).strip(),
            )
        )

    if state.get("errors"):
        state["status"] = "failed"
        write_bootstrap_state(state_path, state)
        if on_prepare_event is not None:
            from open_researcher.research_events import PrepareFailed

            on_prepare_event(
                PrepareFailed(step="resolve", detail=" ; ".join(str(item) for item in state["errors"]))
            )
        return 1, state
    if state.get("unresolved"):
        state["status"] = "failed"
        state["errors"] = list(state.get("unresolved", []))
        write_bootstrap_state(state_path, state)
        if on_prepare_event is not None:
            from open_researcher.research_events import PrepareFailed

            on_prepare_event(
                PrepareFailed(step="resolve", detail=" ; ".join(str(item) for item in state["unresolved"]))
            )
        return 1, state

    code, detail = _ensure_python_environment(repo_path, state, log_path)
    if code != 0:
        state["status"] = "failed"
        state["errors"] = [detail]
        write_bootstrap_state(state_path, state)
        if on_prepare_event is not None:
            from open_researcher.research_events import PrepareFailed

            on_prepare_event(PrepareFailed(step="python_env", detail=detail))
        return code, state

    working_dir = (repo_path / str(state.get("working_dir", ".") or ".")).resolve()
    env = _command_env(str(state.get("python_env", {}).get("executable", "")))

    for step_name in _step_names():
        step = state.get(step_name, {})
        command = str(step.get("command", "")).strip()
        if not command:
            step["status"] = "skipped"
            continue
        if step_name == "data":
            expected_paths = _expected_paths_status(repo_path, state.get("expected_paths", []))
            state["expected_path_status"] = expected_paths
            if expected_paths and all(item.get("exists") for item in expected_paths):
                step["status"] = "skipped"
                step["detail"] = "Expected paths already exist"
                write_bootstrap_state(state_path, state)
                continue
        if on_prepare_event is not None:
            from open_researcher.research_events import PrepareStepStarted

            on_prepare_event(
                PrepareStepStarted(
                    step=step_name,
                    command=command,
                    source=str(step.get("source", "")).strip(),
                )
            )
        step["status"] = "running"
        step["started_at"] = now_iso()
        write_bootstrap_state(state_path, state)
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(working_dir),
            text=True,
            capture_output=True,
            env=env,
        )
        _append_prepare_log(log_path, step_name, command, result)
        step["finished_at"] = now_iso()
        if result.returncode != 0:
            step["status"] = "failed"
            step["detail"] = f"Command failed with exit code {result.returncode}"
            state["status"] = "failed"
            state["errors"] = [step["detail"]]
            write_bootstrap_state(state_path, state)
            if on_prepare_event is not None:
                from open_researcher.research_events import PrepareFailed

                on_prepare_event(PrepareFailed(step=step_name, detail=step["detail"]))
            return result.returncode or 1, state
        if step_name == "data":
            expected_paths = _expected_paths_status(repo_path, state.get("expected_paths", []))
            state["expected_path_status"] = expected_paths
            missing = [item["path"] for item in expected_paths if not item.get("exists")]
            if missing:
                step["status"] = "failed"
                step["detail"] = f"Expected paths missing after data step: {', '.join(missing)}"
                state["status"] = "failed"
                state["errors"] = [step["detail"]]
                write_bootstrap_state(state_path, state)
                if on_prepare_event is not None:
                    from open_researcher.research_events import PrepareFailed

                    on_prepare_event(PrepareFailed(step=step_name, detail=step["detail"]))
                return 1, state
        step["status"] = "completed"
        step["detail"] = "Completed successfully"
        write_bootstrap_state(state_path, state)
        if on_prepare_event is not None:
            from open_researcher.research_events import PrepareStepCompleted

            on_prepare_event(
                PrepareStepCompleted(
                    step=step_name,
                    status="completed",
                    log_path=str(log_path),
                    detail=step["detail"],
                )
            )

    expected_paths = _expected_paths_status(repo_path, state.get("expected_paths", []))
    state["expected_path_status"] = expected_paths
    missing = [item["path"] for item in expected_paths if not item.get("exists")]
    if missing:
        state["status"] = "failed"
        state["errors"] = [f"Expected paths missing after prepare: {', '.join(missing)}"]
        write_bootstrap_state(state_path, state)
        if on_prepare_event is not None:
            from open_researcher.research_events import PrepareFailed

            on_prepare_event(PrepareFailed(step="expected_paths", detail=state["errors"][0]))
        return 1, state

    state["status"] = "completed"
    state["errors"] = []
    write_bootstrap_state(state_path, state)
    if on_prepare_event is not None:
        from open_researcher.research_events import PrepareCompleted

        on_prepare_event(PrepareCompleted(status="completed", unresolved=0))
    return 0, state


def format_bootstrap_dry_run(repo_path: Path, research_dir: Path, cfg: ResearchConfig) -> list[str]:
    state = resolve_bootstrap_plan(repo_path, research_dir, cfg)
    lines = [
        f"[bold]Bootstrap auto-prepare:[/bold] {'enabled' if cfg.bootstrap_auto_prepare else 'disabled'}",
        f"[bold]Repo profile:[/bold] {state['repo_profile'].get('kind', 'unknown')}",
        f"[bold]Working directory:[/bold] {(repo_path / state.get('working_dir', '.')).resolve()}",
        f"[bold]Python:[/bold] {state['python_env'].get('executable', '')} [{state['python_env'].get('source', '')}]",
    ]
    for step_name in _step_names():
        step = state.get(step_name, {})
        command = str(step.get("command", "")).strip() or "<unresolved>"
        source = str(step.get("source", "")).strip() or "none"
        lines.append(f"[bold]{step_name.title()}:[/bold] {command}")
        lines.append(f"[dim]  source: {source}[/dim]")
    expected = state.get("expected_paths", [])
    if expected:
        lines.append(f"[bold]Expected paths:[/bold] {', '.join(expected)}")
    if state.get("errors"):
        lines.append("[bold red]Errors:[/bold red]")
        for item in state["errors"]:
            lines.append(f"[red]- {item}[/red]")
    if state.get("unresolved"):
        lines.append("[bold yellow]Unresolved:[/bold yellow]")
        for item in state["unresolved"]:
            lines.append(f"[yellow]- {item}[/yellow]")
    if not state.get("errors") and not state.get("unresolved"):
        lines.append("[green]Bootstrap resolution is ready.[/green]")
    return lines
