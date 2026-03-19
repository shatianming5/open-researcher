"""Repository and environment detection for bootstrapping."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RepoInfo:
    """Detected repository information."""
    path: Path
    has_git: bool = False
    has_python: bool = False
    has_requirements: bool = False
    has_setup_py: bool = False
    has_pyproject: bool = False
    languages: list[str] = field(default_factory=list)
    python_version: str | None = None


def detect_repo(path: Path) -> RepoInfo:
    """Detect repository type and available tooling at the given path.

    Checks for git, Python environment markers, and common project files.
    """
    info = RepoInfo(path=path)

    info.has_git = (path / ".git").exists()
    info.has_requirements = (path / "requirements.txt").exists()
    info.has_setup_py = (path / "setup.py").exists()
    info.has_pyproject = (path / "pyproject.toml").exists()

    # Detect Python
    if info.has_requirements or info.has_setup_py or info.has_pyproject:
        info.has_python = True
        info.languages.append("python")

    # Check for other language markers
    if (path / "package.json").exists():
        info.languages.append("javascript")
    if (path / "Cargo.toml").exists():
        info.languages.append("rust")
    if (path / "go.mod").exists():
        info.languages.append("go")

    return info


def detect_python_env(path: Path) -> str | None:
    """Detect the Python executable to use for this repository.

    Checks for virtual environments and system Python in order of preference.
    """
    # Check for venv/virtualenv
    import sys
    if sys.platform == "win32":
        _venv_bin = "Scripts"
        _python_name = "python.exe"
    else:
        _venv_bin = "bin"
        _python_name = "python"
    for venv_dir in [".venv", "venv", "env"]:
        python = path / venv_dir / _venv_bin / _python_name
        if python.exists():
            logger.debug("Detected Python via venv: %s", python)
            return str(python)

    # Check for conda env
    conda_python = path / "conda_env" / _venv_bin / _python_name
    if conda_python.exists():
        logger.debug("Detected Python via conda env: %s", conda_python)
        return str(conda_python)

    # Fall back to system python
    if shutil.which("python3"):
        logger.debug("Falling back to system python3")
        return "python3"
    if shutil.which("python"):
        logger.debug("Falling back to system python")
        return "python"

    logger.debug("No Python executable detected")
    return None


@dataclass
class CommandInfo:
    """A detected or configured command to run during bootstrap."""
    name: str
    command: list[str]
    description: str = ""
    optional: bool = False
    env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.command:
            raise ValueError("CommandInfo.command must be non-empty")
