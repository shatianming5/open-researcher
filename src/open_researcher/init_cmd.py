"""Implementation of the 'init' command."""

import os
import shutil
import stat
import sys
from datetime import date
from pathlib import Path

from jinja2 import Environment, PackageLoader


def do_init(repo_path: Path, tag: str | None = None) -> None:
    """Initialize .research/ directory in the given repo."""
    research_dir = repo_path / ".research"

    if research_dir.exists():
        print(f"[ERROR] .research/ already exists at {research_dir}", file=sys.stderr)
        raise SystemExit(1)

    # Generate tag from date if not provided
    if tag is None:
        today = date.today()
        tag = today.strftime("%b%d").lower()  # e.g. "mar08"

    # Render templates
    env = Environment(loader=PackageLoader("open_researcher", "templates"))
    context = {"tag": tag}

    research_dir.mkdir()

    # Render each template
    for template_name, output_name in [
        ("program.md.j2", "program.md"),
        ("config.yaml.j2", "config.yaml"),
        ("project-understanding.md.j2", "project-understanding.md"),
        ("evaluation.md.j2", "evaluation.md"),
    ]:
        template = env.get_template(template_name)
        content = template.render(context)
        (research_dir / output_name).write_text(content)

    # Create results.tsv with header
    header = "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription\n"
    (research_dir / "results.tsv").write_text(header)

    # Copy helper scripts
    scripts_dir = research_dir / "scripts"
    scripts_dir.mkdir()

    scripts_src = Path(__file__).parent / "scripts"
    for script_name in ["record.py", "rollback.sh"]:
        src = scripts_src / script_name
        dst = scripts_dir / script_name
        shutil.copy2(src, dst)

    # Make shell scripts executable
    rollback = scripts_dir / "rollback.sh"
    rollback.chmod(rollback.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    print(f"[OK] Initialized .research/ with tag '{tag}'")
    print(f"     Branch: research/{tag}")
    print(f"     Next: point your AI agent at .research/program.md")
