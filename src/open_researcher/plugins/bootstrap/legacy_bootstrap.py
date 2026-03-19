"""Bootstrap resolution and auto-prepare helpers for local research-v1 runs.

Migrated from ``open_researcher.bootstrap``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from open_researcher.config import ResearchConfig
from open_researcher.event_journal import now_iso

logger = logging.getLogger(__name__)

BOOTSTRAP_STATE_VERSION = "research-v1"
PREPARE_LOG_NAME = "prepare.log"
SMOKE_PREFLIGHT_ATTEMPTS = 2


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
        "warnings": [],
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
        logger.warning("Corrupt bootstrap state file %s — resetting to defaults", path)
        payload = default_bootstrap_state(path.parent)
    if not isinstance(payload, dict):
        payload = default_bootstrap_state(path.parent)
    merged = default_bootstrap_state(path.parent)
    _nested_keys = {"repo_profile", "python_env", "install", "data", "smoke"}
    merged.update({k: v for k, v in payload.items() if k in merged and k not in _nested_keys})
    for key in _nested_keys:
        value = payload.get(key, {})
        if isinstance(value, dict):
            merged[key].update({k: v for k, v in value.items() if k in merged[key]})
    if isinstance(payload.get("expected_path_status"), list):
        merged["expected_path_status"] = [item for item in payload["expected_path_status"] if isinstance(item, dict)]
    if isinstance(payload.get("expected_paths"), list):
        merged["expected_paths"] = [str(item) for item in payload["expected_paths"]]
    if isinstance(payload.get("errors"), list):
        merged["errors"] = [str(item) for item in payload["errors"]]
    if isinstance(payload.get("warnings"), list):
        merged["warnings"] = [str(item) for item in payload["warnings"]]
    if isinstance(payload.get("unresolved"), list):
        merged["unresolved"] = [str(item) for item in payload["unresolved"]]
    return merged


def _redact_state_secrets(payload: dict) -> dict:
    """Redact secret-bearing strings in the bootstrap state before persistence.

    Works on a deep copy so the in-memory state used for execution is unaffected.
    """
    import copy
    sanitized = copy.deepcopy(payload)
    for step_key in ("install", "data", "smoke"):
        step = sanitized.get(step_key, {})
        if isinstance(step.get("command"), str) and step["command"]:
            step["command"] = _redact_secrets(step["command"])
        if isinstance(step.get("detail"), str) and step["detail"]:
            step["detail"] = _redact_secrets(step["detail"])
    return sanitized


def write_bootstrap_state(path: Path, state: dict) -> None:
    payload = default_bootstrap_state(path.parent)
    payload.update({k: v for k, v in state.items() if k in payload})
    for key in ("repo_profile", "python_env", "install", "data", "smoke"):
        if isinstance(state.get(key), dict):
            payload[key].update(state[key])
    payload["updated_at"] = now_iso()
    # Security: redact secrets before writing to disk
    payload = _redact_state_secrets(payload)
    import tempfile
    content = json.dumps(payload, indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
    blocks = re.findall(r"```(?:bash|sh)?\n(.*?)```", content, flags=re.DOTALL)
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip() and not line.strip().startswith("#")]
        command = "\n".join(lines).strip()
        if command and not _looks_like_placeholder(command):
            return command
    return ""


def _detect_install_command(
    repo_path: Path, workdir: Path, python_executable: str, cfg: ResearchConfig
) -> tuple[str, str]:
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
        if head and re.match(r"^[a-zA-Z0-9_-]+$", head):
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
    repo_root = repo_path.resolve()
    for raw in expected_paths:
        value = str(raw).strip()
        if not value:
            continue
        path = (repo_path / value).resolve()
        # Security: only probe paths within the repo root
        try:
            path.relative_to(repo_root)
        except ValueError:
            logger.warning("Skipping expected_path outside repo root: %s", value)
            continue
        items.append({"path": value, "exists": path.exists()})
    return items


def _append_warning(state: dict, detail: str) -> None:
    message = str(detail or "").strip()
    if not message:
        return
    warnings = state.setdefault("warnings", [])
    if message not in warnings:
        warnings.append(message)


def _set_step_resolution(
    step: dict,
    *,
    command: str,
    source: str,
    status: str,
    detail: str,
) -> None:
    step.update(
        {
            "command": command,
            "source": source,
            "status": status,
            "started_at": "",
            "finished_at": "",
            "detail": detail,
        }
    )


def _dry_run_step_preview(step: dict) -> str:
    command = str(step.get("command", "")).strip()
    if command:
        return command
    status = str(step.get("status", "")).strip()
    if status == "skipped":
        return "<not required>"
    if status == "disabled":
        return "<disabled>"
    return "<unresolved>"


def _is_explicit_bootstrap_source(source: str) -> bool:
    return str(source or "").strip().startswith("config.bootstrap.")


def _has_explicit_prepare_fallback(state: dict) -> bool:
    for step_name in ("install", "data"):
        step = state.get(step_name, {})
        if str(step.get("command", "")).strip() and _is_explicit_bootstrap_source(str(step.get("source", "")).strip()):
            return True
    return False


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
    warnings: list[str] = []
    unresolved: list[str] = []
    # Security: reject working_dir that escapes the repo root
    repo_root = repo_path.resolve()
    try:
        working_dir.relative_to(repo_root)
    except ValueError:
        errors.append(
            f"Working directory escapes the repo root: {working_dir_value} "
            f"(resolves to {working_dir}, repo root is {repo_root})"
        )
    if not working_dir.exists():
        errors.append(f"Working directory does not exist: {working_dir_value}")
    # Security: verify Hub command digest if commands came from Hub
    if cfg.hub_arxiv_id:
        if not cfg.hub_commands_reviewed or not cfg.hub_commands_digest:
            # Fail closed: Hub-origin commands without review metadata require re-review
            errors.append(
                f"Hub commands for {cfg.hub_arxiv_id} lack review metadata. "
                "Re-run `hub apply` to review and approve the commands."
            )
        else:
            import hashlib
            # Reconstruct the same canonical override set as hub.py's apply function
            hub_overrides: dict[str, str] = {}
            if cfg.bootstrap_install_command:
                hub_overrides["install_command"] = cfg.bootstrap_install_command
            if cfg.bootstrap_smoke_command:
                hub_overrides["smoke_command"] = cfg.bootstrap_smoke_command
            if cfg.bootstrap_python:
                hub_overrides["python"] = cfg.bootstrap_python
            if cfg.bootstrap_requires_gpu:
                hub_overrides["requires_gpu"] = str(True)
            if hub_overrides:
                command_text = "|".join(f"{k}={v}" for k, v in sorted(hub_overrides.items()))
                actual_digest = hashlib.sha256(command_text.encode()).hexdigest()
                if actual_digest != cfg.hub_commands_digest:
                    errors.append(
                        "Hub command digest mismatch: bootstrap commands have been modified since "
                        f"user review (hub_arxiv_id={cfg.hub_arxiv_id}). "
                        "Re-run `hub apply` to re-review the commands."
                    )
    if repo_profile["kind"] != "python" and not (
        cfg.bootstrap_install_command or cfg.bootstrap_data_command or cfg.bootstrap_smoke_command
    ):
        unresolved.append("Could not infer a safe auto-prepare path for a non-Python repo.")
    if not smoke_command:
        unresolved.append("Smoke command is unresolved. Fill bootstrap.smoke_command or evaluation.md.")
    # Note: smoke status is set below by _set_step_resolution; no early assignment needed.
    if missing_expected_paths and not data_command:
        detail = "Expected paths are missing but no data command was resolved: " + ", ".join(missing_expected_paths)
        if smoke_command:
            warnings.append(detail + ". A successful smoke check will be treated as authoritative readiness.")
        else:
            unresolved.append(detail)
    if cfg.bootstrap_requires_gpu and not shutil.which("nvidia-smi"):
        errors.append("bootstrap.requires_gpu=true but nvidia-smi is not available.")

    install_status = "pending" if install_command else "skipped"
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
            "warnings": warnings,
            "unresolved": unresolved,
        }
    )
    _set_step_resolution(
        state["install"],
        command=install_command,
        source=install_source,
        status=install_status,
        detail="Dependency installation step" if install_command else "No install step required",
    )
    _set_step_resolution(
        state["data"],
        command=data_command,
        source=data_source,
        status="pending" if data_command else "skipped",
        detail="Dataset/setup step" if data_command else "No data step required for readiness",
    )
    _set_step_resolution(
        state["smoke"],
        command=smoke_command,
        source=smoke_source,
        status="pending" if smoke_command else "unresolved",
        detail="Readiness smoke step" if smoke_command else "No smoke command resolved",
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
    return str(state.get("smoke", {}).get("status", "")).strip() == "completed"


def _venv_root_from_python(python_executable: str) -> Path | None:
    path = Path(python_executable)
    if not path.exists():
        return None
    parent = path.parent
    root = parent.parent
    pyvenv_cfg = root / "pyvenv.cfg"
    return root if pyvenv_cfg.exists() else None


def _conda_exe_name() -> str:
    return "conda.exe" if os.name == "nt" else "conda"


def _conda_bin_dir(root: Path) -> Path:
    return root / ("Scripts" if os.name == "nt" else "bin")


def _conda_layout_from_python(python_executable: str) -> tuple[Path | None, Path | None, Path | None]:
    path = Path(python_executable)
    if not path.exists():
        return None, None, None
    if path.parent.name not in {"bin", "Scripts"}:
        return None, None, None

    prefix = path.parent.parent
    if not (prefix / "conda-meta").is_dir():
        return None, None, None

    candidate_roots: list[Path] = []
    env_conda_exe = str(os.environ.get("CONDA_EXE", "")).strip()
    if env_conda_exe:
        env_path = Path(env_conda_exe)
        if env_path.exists():
            candidate_roots.append(env_path.parent.parent)
    if prefix.parent.name == "envs":
        candidate_roots.append(prefix.parent.parent)
    candidate_roots.append(prefix)

    seen: set[Path] = set()
    for root in candidate_roots:
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        conda_exe = _conda_bin_dir(root) / _conda_exe_name()
        if conda_exe.exists():
            return prefix, root, conda_exe
    return prefix, None, None


def _prepend_path(path_value: str, entries: list[Path]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        raw = str(entry)
        if not raw or raw in seen:
            continue
        seen.add(raw)
        parts.append(raw)
    for raw in str(path_value or "").split(os.pathsep):
        if not raw or raw in seen:
            continue
        seen.add(raw)
        parts.append(raw)
    return os.pathsep.join(parts)


_SENSITIVE_ENV_PREFIXES = (
    "API_KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL",
    "AWS_", "AZURE_", "GCP_", "GOOGLE_", "OPENAI_", "ANTHROPIC_",
    "HF_TOKEN", "HUGGING_FACE", "WANDB_API_KEY", "COMET_API_KEY",
    "GITHUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN", "NPM_TOKEN",
    "PRIVATE_KEY", "SSH_AUTH_SOCK",
    "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "NETRC",
    "NPM_CONFIG_", "DOCKER_CONFIG", "KUBECONFIG",
)


def _scrub_sensitive_env(env: dict[str, str]) -> dict[str, str]:
    """Remove sensitive variables (API keys, cloud credentials) from the env dict.

    Bootstrap commands are derived from config or auto-detected from repo files,
    so they should not have access to ambient secrets.
    """
    return {
        k: v for k, v in env.items()
        if not any(k.upper().startswith(p) or k.upper().endswith(p) for p in _SENSITIVE_ENV_PREFIXES)
    }


def command_env_for_python(python_executable: str, *, base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base_env) if base_env is not None else dict(os.environ)
    path_entries: list[Path] = []
    venv_root = _venv_root_from_python(python_executable)
    if venv_root is not None:
        path_entries.append(_venv_bin_dir(venv_root))
        env["VIRTUAL_ENV"] = str(venv_root)
    conda_prefix, conda_root, conda_exe = _conda_layout_from_python(python_executable)
    if conda_prefix is not None:
        path_entries.append(_venv_bin_dir(conda_prefix))
        env["CONDA_PREFIX"] = str(conda_prefix)
        env.setdefault("CONDA_DEFAULT_ENV", conda_prefix.name or "base")
    if conda_root is not None:
        path_entries.append(_conda_bin_dir(conda_root))
    if conda_exe is not None:
        env["CONDA_EXE"] = str(conda_exe)
    if path_entries:
        env["PATH"] = _prepend_path(env.get("PATH", ""), path_entries)
    return env


def _command_env(python_executable: str) -> dict[str, str]:
    return _scrub_sensitive_env(command_env_for_python(python_executable))


def _ambient_command_env(python_executable: str) -> dict[str, str]:
    env = _scrub_sensitive_env(dict(os.environ))
    venv_root = _venv_root_from_python(python_executable)
    if venv_root is None:
        return env

    bin_dir = _venv_bin_dir(venv_root).resolve()
    path_entries = []
    for entry in env.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            if Path(entry).resolve() == bin_dir:
                continue
        except OSError:
            if entry == str(bin_dir):
                continue
        path_entries.append(entry)
    env["PATH"] = os.pathsep.join(path_entries)

    active_venv = env.get("VIRTUAL_ENV", "").strip()
    if active_venv:
        try:
            if Path(active_venv).resolve() == venv_root.resolve():
                env.pop("VIRTUAL_ENV", None)
        except OSError:
            if active_venv == str(venv_root):
                env.pop("VIRTUAL_ENV", None)
    return env


_SECRET_PATTERNS = [
    # key=value and key: value forms
    re.compile(
        r"(?i)"
        r"(?:api[_-]?key|secret|token|password|credential|private[_-]?key)"
        r"\s*[:=]\s*\S+"
    ),
    # Bearer/Basic auth headers
    re.compile(r"(?i)(?:Bearer|Basic)\s+[A-Za-z0-9+/=_-]{8,}"),
    # URL-embedded credentials (user:pass@host)
    re.compile(r"://[^@\s]+:[^@\s]+@"),
]


def _redact_secrets(text: str) -> str:
    """Redact text that looks like it contains secrets."""
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def _append_prepare_log(
    log_path: Path,
    step: str,
    command: str,
    result: subprocess.CompletedProcess[str],
    *,
    env_mode: str | None = None,
) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n== {now_iso()} :: {step} ==\n")
            handle.write(f"$ {_redact_secrets(command)}\n")
            if env_mode:
                handle.write(f"[env_mode={env_mode}]\n")
            if result.stdout:
                handle.write(_redact_secrets(result.stdout))
                if not result.stdout.endswith("\n"):
                    handle.write("\n")
            if result.stderr:
                handle.write(_redact_secrets(result.stderr))
                if not result.stderr.endswith("\n"):
                    handle.write("\n")
            handle.write(f"[exit_code={result.returncode}]\n")
    except OSError:
        logger.warning("Failed to write prepare log to %s", log_path, exc_info=True)


_PREPARE_COMMAND_TIMEOUT = 600  # seconds


_SHELL_METACHARACTERS = frozenset("&|;<>()$`\\\"'*?#~=!{}[]")


def _needs_shell(command: str) -> bool:
    """Return True if the command contains shell metacharacters that require bash -c."""
    return any(ch in _SHELL_METACHARACTERS for ch in command)


def _run_prepare_command(
    step_name: str,
    command: str,
    *,
    working_dir: Path,
    env: dict[str, str],
    log_path: Path,
    env_mode: str = "project",
    timeout: int = _PREPARE_COMMAND_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    import shlex

    if _needs_shell(command):
        # Security: log that we're using shell mode so it's auditable.
        # Commands with shell metacharacters are wrapped in bash -c.
        logger.info(
            "Bootstrap step %s uses shell mode (command contains metacharacters): %s",
            step_name, _redact_secrets(command),
        )
        argv = ["bash", "-c", command]
    else:
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = ["bash", "-c", command]
    try:
        result = subprocess.run(
            argv,
            shell=False,
            cwd=str(working_dir),
            text=True,
            capture_output=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        result = subprocess.CompletedProcess(
            args=command, returncode=124,
            stdout="", stderr=f"Command timed out after {timeout}s",
        )
    except FileNotFoundError as exc:
        result = subprocess.CompletedProcess(
            args=command, returncode=127,
            stdout="", stderr=f"Command not found: {exc}",
        )
    except OSError as exc:
        result = subprocess.CompletedProcess(
            args=command, returncode=126,
            stdout="", stderr=f"OS error running command: {exc}",
        )
    _append_prepare_log(log_path, step_name, command, result, env_mode=env_mode)
    return result


def _try_smoke_preflight(
    repo_path: Path,
    state: dict,
    *,
    working_dir: Path,
    project_env: dict[str, str],
    ambient_env: dict[str, str],
    log_path: Path,
    state_path: Path,
    on_prepare_event=None,
) -> tuple[bool, bool, dict]:
    step = state.setdefault("smoke", {})
    command = str(step.get("command", "")).strip()
    if not command:
        return False, False, state

    explicit_smoke = _is_explicit_bootstrap_source(str(step.get("source", "")).strip())
    attempts: list[tuple[str, dict[str, str]]] = []
    if explicit_smoke:
        attempts = [("project", project_env), ("ambient", ambient_env)]
    else:
        attempts = [("project", project_env) for _ in range(SMOKE_PREFLIGHT_ATTEMPTS)]

    attempt_count = 0
    success_env_mode = ""
    first_started_at = ""
    result: subprocess.CompletedProcess[str] | None = None
    for attempt, (env_mode, env) in enumerate(attempts, start=1):
        step_name = "smoke_preflight" if attempt == 1 else f"smoke_preflight_retry_{attempt}"
        if not first_started_at:
            first_started_at = now_iso()
        result = _run_prepare_command(
            step_name,
            command,
            working_dir=working_dir,
            env=env,
            log_path=log_path,
            env_mode=env_mode,
        )
        attempt_count = attempt
        if result.returncode == 0:
            success_env_mode = env_mode
            break
    if result is None or result.returncode != 0:
        if explicit_smoke and not _has_explicit_prepare_fallback(state):
            failure_detail = (
                "Explicit smoke command failed in both project and ambient environments; "
                "install fallback suppressed. See prepare.log for the failing attempts."
            )
            step["status"] = "failed"
            step["detail"] = failure_detail
            step["started_at"] = first_started_at or now_iso()
            step["finished_at"] = now_iso()
            state["status"] = "failed"
            state["errors"] = [failure_detail]
            state["unresolved"] = []
            for step_name in ("install", "data"):
                current = state.get(step_name, {})
                current["status"] = "skipped"
                current["detail"] = "Suppressed because the explicit smoke command failed before fallback steps."
                current["started_at"] = ""
                current["finished_at"] = ""
            return False, True, state
        return False, False, state

    timestamp = now_iso()
    ready_detail = "Smoke passed before install/data; reusing the current workspace as-is."
    if attempt_count > 1:
        ready_detail += f" The readiness probe passed on retry {attempt_count}/{len(attempts)}."
        if success_env_mode == "ambient":
            ready_detail += " The successful retry ran in the ambient environment without repo .venv injection."
            _append_warning(
                state,
                "Smoke preflight passed on retry in the ambient environment after the project-env attempt failed.",
            )
        else:
            _append_warning(
                state,
                "Smoke preflight passed on retry after an earlier failure; see prepare.log for the initial failure.",
            )
    expected_paths = _expected_paths_status(repo_path, state.get("expected_paths", []))
    state["expected_path_status"] = expected_paths
    missing = [item["path"] for item in expected_paths if not item.get("exists")]
    if missing:
        _append_warning(
            state,
            "Smoke passed even though these expected paths were absent: "
            + ", ".join(missing)
            + ". Treating smoke success as the stronger readiness signal.",
        )

    for step_name in ("install", "data"):
        current = state.get(step_name, {})
        current["status"] = "skipped"
        current["detail"] = "Skipped because smoke preflight already proved the workspace is ready"
        current["started_at"] = ""
        current["finished_at"] = ""

    step["status"] = "completed"
    step["detail"] = ready_detail
    step["started_at"] = first_started_at or timestamp
    step["finished_at"] = timestamp
    state["status"] = "completed"
    state["errors"] = []
    state["unresolved"] = []
    write_bootstrap_state(state_path, state)

    if on_prepare_event is not None:
        from open_researcher.kernel.events import PrepareStepCompleted, PrepareStepStarted

        on_prepare_event(
            PrepareStepStarted(
                step="smoke",
                command=command,
                source=str(step.get("source", "")).strip(),
            )
        )
        on_prepare_event(
            PrepareStepCompleted(
                step="smoke",
                status="completed",
                log_path=str(log_path),
                detail=ready_detail,
            )
        )
    return True, False, state


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
    venv_cmd = f"{sys.executable} -m venv {venv_dir}"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            cwd=str(repo_path),
            text=True,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"Failed to create venv: {exc}"
    _append_prepare_log(log_path, "python_env", venv_cmd, result)
    if result.returncode != 0:
        return result.returncode, "Failed to create .venv"
    return 0, ""


def _safe_prepare_event(on_prepare_event, event):
    """Invoke the prepare event callback, swallowing exceptions to prevent propagation."""
    if on_prepare_event is None:
        return
    try:
        on_prepare_event(event)
    except Exception:
        logger.debug("on_prepare_event callback raised; ignoring", exc_info=True)


def run_bootstrap_prepare(
    repo_path: Path,
    research_dir: Path,
    cfg: ResearchConfig,
    *,
    on_prepare_event=None,
) -> tuple[int, dict]:
    if on_prepare_event is not None:
        _raw_event_cb = on_prepare_event

        def _wrapped_prepare_event(event):
            return _safe_prepare_event(_raw_event_cb, event)

        on_prepare_event = _wrapped_prepare_event
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
            from open_researcher.kernel.events import PrepareCompleted

            on_prepare_event(PrepareCompleted(status="disabled", unresolved=0))
        return 0, state

    if is_prepare_ready(state, repo_path):
        if on_prepare_event is not None:
            from open_researcher.kernel.events import PrepareCompleted

            on_prepare_event(PrepareCompleted(status="cached", unresolved=0))
        return 0, state

    if on_prepare_event is not None:
        from open_researcher.kernel.events import PrepareStarted

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
            from open_researcher.kernel.events import PrepareFailed

            on_prepare_event(PrepareFailed(step="resolve", detail=" ; ".join(str(item) for item in state["errors"])))
        return 1, state
    if state.get("unresolved"):
        state["status"] = "failed"
        state["errors"] = list(state.get("unresolved", []))
        write_bootstrap_state(state_path, state)
        if on_prepare_event is not None:
            from open_researcher.kernel.events import PrepareFailed

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
            from open_researcher.kernel.events import PrepareFailed

            on_prepare_event(PrepareFailed(step="python_env", detail=detail))
        return code, state

    working_dir = (repo_path / str(state.get("working_dir", ".") or ".")).resolve()
    python_executable = str(state.get("python_env", {}).get("executable", ""))
    project_env = _command_env(python_executable)
    ambient_env = _ambient_command_env(python_executable)

    ready, fail_fast, state = _try_smoke_preflight(
        repo_path,
        state,
        working_dir=working_dir,
        project_env=project_env,
        ambient_env=ambient_env,
        log_path=log_path,
        state_path=state_path,
        on_prepare_event=on_prepare_event,
    )
    if ready:
        if on_prepare_event is not None:
            from open_researcher.kernel.events import PrepareCompleted

            on_prepare_event(PrepareCompleted(status="completed", unresolved=0))
        return 0, state
    if fail_fast:
        write_bootstrap_state(state_path, state)
        if on_prepare_event is not None:
            from open_researcher.kernel.events import PrepareFailed

            on_prepare_event(PrepareFailed(step="smoke", detail=str(state.get("smoke", {}).get("detail", "")).strip()))
        return 1, state

    for step_name in _step_names():
        step = state.setdefault(step_name, {})
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
            from open_researcher.kernel.events import PrepareStepStarted

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
        try:
            result = _run_prepare_command(
                step_name,
                command,
                working_dir=working_dir,
                env=project_env,
                log_path=log_path,
                env_mode="project",
            )
        except Exception as exc:
            step["status"] = "failed"
            step["finished_at"] = now_iso()
            step["detail"] = f"Unexpected error: {exc}"
            state["status"] = "failed"
            state["errors"] = [step["detail"]]
            write_bootstrap_state(state_path, state)
            raise
        step["finished_at"] = now_iso()
        if result.returncode != 0:
            step["status"] = "failed"
            step["detail"] = f"Command failed with exit code {result.returncode}"
            state["status"] = "failed"
            state["errors"] = [step["detail"]]
            write_bootstrap_state(state_path, state)
            if on_prepare_event is not None:
                from open_researcher.kernel.events import PrepareFailed

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
                    from open_researcher.kernel.events import PrepareFailed

                    on_prepare_event(PrepareFailed(step=step_name, detail=step["detail"]))
                return 1, state
        step["status"] = "completed"
        step["detail"] = "Completed successfully"
        write_bootstrap_state(state_path, state)
        if on_prepare_event is not None:
            from open_researcher.kernel.events import PrepareStepCompleted

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
        if str(state.get("smoke", {}).get("status", "")).strip() == "completed":
            _append_warning(
                state,
                "Expected paths were still missing after prepare, but smoke succeeded: " + ", ".join(missing),
            )
        else:
            state["status"] = "failed"
            state["errors"] = [f"Expected paths missing after prepare: {', '.join(missing)}"]
            write_bootstrap_state(state_path, state)
            if on_prepare_event is not None:
                from open_researcher.kernel.events import PrepareFailed

                on_prepare_event(PrepareFailed(step="expected_paths", detail=state["errors"][0]))
            return 1, state

    state["status"] = "completed"
    state["errors"] = []
    write_bootstrap_state(state_path, state)
    if on_prepare_event is not None:
        from open_researcher.kernel.events import PrepareCompleted

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
        command = _dry_run_step_preview(step)
        source = str(step.get("source", "")).strip() or "none"
        lines.append(f"[bold]{step_name.title()}:[/bold] {command}")
        lines.append(f"[dim]  source: {source}[/dim]")
        lines.append(f"[dim]  status: {step.get('status', 'pending')}[/dim]")
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
    if state.get("warnings"):
        lines.append("[bold yellow]Warnings:[/bold yellow]")
        for item in state["warnings"]:
            lines.append(f"[yellow]- {item}[/yellow]")
    if not state.get("errors") and not state.get("unresolved"):
        lines.append("[green]Bootstrap resolution is ready.[/green]")
    return lines
