"""PaperFarm Hub CLI commands."""

from __future__ import annotations

import os
import shlex
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import typer
from rich.console import Console

from open_researcher.hub import (
    HUB_REGISTRY_URL,
    apply_manifest_to_config_yaml,
    fetch_index,
    fetch_index_full,
    fetch_manifest,
    manifest_summary,
    manifest_to_bootstrap_overrides,
)

_ascii_mode = bool(os.environ.get("NO_COLOR", "").strip() or os.environ.get("TERM", "") == "dumb")

hub_app = typer.Typer(
    help=(
        "PaperFarm Hub — verified research environment registry.\n\n"
        "Typical workflow:\n"
        "  1. hub list                   Browse available papers\n"
        "  2. hub lookup <arxiv-id>      Inspect a paper's manifest\n"
        "  3. hub install <arxiv-id>     Clone and setup the repo\n"
        "  4. hub apply <arxiv-id>       Apply Hub config to .research/\n"
    ),
)
console = Console()


@hub_app.command()
def lookup(
    arxiv_id: str = typer.Argument(help="ArXiv ID (e.g. 2507.19457)"),
    registry: str = typer.Option(HUB_REGISTRY_URL, "--registry", help="Hub registry base URL"),
) -> None:
    """Show the Hub manifest for a paper."""
    try:
        manifest = fetch_manifest(arxiv_id, registry_url=registry)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]PaperFarm Hub — {arxiv_id}[/bold]")
    console.print(manifest_summary(manifest))

    overrides = manifest_to_bootstrap_overrides(manifest)
    if overrides:
        console.print("\n[dim]Bootstrap overrides (applied by `hub apply`):[/dim]")
        for k, v in overrides.items():
            console.print(f"  [cyan]{k}[/cyan] = {v}")


@hub_app.command(name="list")
def list_entries(
    area: str = typer.Option(None, "--area", help="Filter by area (e.g. nlp, cv, ml-systems, agents)"),
    award: str = typer.Option(None, "--award", help="Filter by award (best-paper, oral, spotlight)"),
    registry: str = typer.Option(HUB_REGISTRY_URL, "--registry", help="Hub registry base URL"),
) -> None:
    """List all entries in the Hub registry."""
    from rich.table import Table

    try:
        entries = fetch_index_full(registry_url=registry)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    if area:
        entries = [e for e in entries if e.get("area") == area]
    if award:
        entries = [e for e in entries if e.get("venue", {}).get("award") == award]

    table = Table(title=f"PaperFarm Hub — {len(entries)} entries")
    table.add_column("ArXiv ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Area")
    table.add_column("Venue")
    table.add_column("Award")
    table.add_column("GPU")
    table.add_column("OK" if _ascii_mode else "✓")

    if _ascii_mode:
        award_style = {"best-paper": "[gold1]*[/gold1]", "oral": "[green]o[/green]", "spotlight": "[blue]+[/blue]"}
    else:
        award_style = {"best-paper": "[gold1]★[/gold1]", "oral": "[green]●[/green]", "spotlight": "[blue]◆[/blue]"}

    for e in entries:
        venue = e.get("venue", {})
        env = e.get("env_summary", {})
        status = e.get("status", {})
        award_val = venue.get("award") or ""
        table.add_row(
            e.get("arxiv_id", ""),
            e.get("short_name", e.get("folder", "")),
            e.get("area", ""),
            f"{venue.get('name', '')} {venue.get('year', '')}",
            award_style.get(award_val, award_val),
            "yes" if env.get("gpu_required") else "no",
            str(status.get("verified_count", 0)),
        )

    console.print(table)


@hub_app.command()
def install(
    arxiv_id: str = typer.Argument(help="ArXiv ID (e.g. 2507.19457)"),
    registry: str = typer.Option(HUB_REGISTRY_URL, "--registry", help="Hub registry base URL"),
    live: bool = typer.Option(False, "--live", help="Pass --live to smoke_test.py (makes real API calls)"),
    provider: str = typer.Option("openai", "--provider", help="LLM provider for --live (openai/anthropic/ollama)"),
    skip_smoke: bool = typer.Option(False, "--skip-smoke", help="Run install_command but skip smoke_test.py"),
) -> None:
    """
    Fetch Hub manifest, run install_command and smoke_test.py.

    Equivalent to reading the paper's README and running the verified install steps.
    """
    try:
        manifest = fetch_manifest(arxiv_id, registry_url=registry)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    env_block = manifest.get("env") if isinstance(manifest.get("env"), dict) else {}
    install_cmd = str(env_block.get("install_command", "") or "").strip()
    test_cmd = str(env_block.get("test_command", "") or "").strip()

    console.print(f"\n[bold]Hub install — {arxiv_id}[/bold]")
    console.print(manifest_summary(manifest))

    # Security: show remote commands and require confirmation before execution
    commands_to_run: list[tuple[str, str]] = []
    if install_cmd:
        commands_to_run.append(("install_command", install_cmd))
    if test_cmd and not skip_smoke:
        commands_to_run.append(("test_command", test_cmd))
    if commands_to_run:
        console.print("\n[yellow]The following commands from the remote registry will be executed:[/yellow]")
        for label, cmd in commands_to_run:
            console.print(f"  [cyan]{label}[/cyan] = {cmd}")
        if not typer.confirm("Trust and run these commands?"):
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(code=0)

    # Check hardware requirements
    resources = manifest.get("resources") if isinstance(manifest.get("resources"), dict) else {}
    gpu_req = str(resources.get("gpu", "none") or "none").strip().lower()
    min_vram = resources.get("min_vram_gb")
    if gpu_req == "required":
        try:
            import torch
            if not torch.cuda.is_available():
                console.print("\n[yellow][WARN] This paper requires a GPU but CUDA is not available.[/yellow]")
            elif min_vram:
                vram = torch.cuda.get_device_properties(0).total_memory / 1e9
                if vram < min_vram:
                    console.print(
                        f"\n[yellow][WARN] Min VRAM required: {min_vram}GB, "
                        f"available: {vram:.1f}GB.[/yellow]"
                    )
        except ImportError:
            if gpu_req == "required":
                console.print("\n[yellow][WARN] GPU required but torch not installed — cannot check VRAM.[/yellow]")
        except Exception as exc:
            console.print(f"\n[yellow][WARN] GPU check failed: {exc}[/yellow]")

    # Step 1: install
    if not install_cmd:
        console.print("\n[yellow]No install_command in manifest — skipping install step.[/yellow]")
    else:
        console.print("\n[bold]Step 1/2: Install[/bold]")
        console.print(f"  $ {install_cmd}")
        try:
            argv = shlex.split(install_cmd)
        except ValueError:
            console.print("[red]Invalid install_command in manifest (cannot parse).[/red]")
            raise typer.Exit(code=1)
        # Security: run with scrubbed environment to avoid leaking API keys
        _scrubbed_env = _scrub_env(os.environ)
        result = subprocess.run(argv, timeout=600, env=_scrubbed_env)
        if result.returncode != 0:
            exit_code = max(result.returncode, 1)
            console.print(f"[red]Install failed (exit {result.returncode}).[/red]")
            raise typer.Exit(code=exit_code)
        console.print("[green]Install OK.[/green]")

    # Step 2: smoke test
    if skip_smoke or not test_cmd:
        if not skip_smoke and not test_cmd:
            console.print("[yellow]No test_command in manifest — skipping smoke test.[/yellow]")
        raise typer.Exit(code=0)

    console.print("\n[bold]Step 2/2: Smoke test[/bold]")

    # Fetch smoke_test.py from Hub into a temp file
    folder = _get_folder(arxiv_id, registry)
    from urllib.parse import quote
    smoke_url = f"{registry}/hub/{quote(folder, safe='')}/smoke_test.py"
    # Security: validate URL scheme
    if not smoke_url.startswith("https://"):
        console.print(f"[red]Refusing non-HTTPS smoke test URL: {smoke_url}[/red]")
        raise typer.Exit(code=1)

    console.print(f"  Fetching smoke_test.py from: {smoke_url}")
    try:
        with urllib.request.urlopen(smoke_url, timeout=10) as resp:
            smoke_src = resp.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError, socket.timeout, UnicodeDecodeError, OSError) as exc:
        console.print(f"[red]Failed to fetch smoke_test.py: {exc}[/red]")
        raise typer.Exit(code=1)

    # Security: show content hash so user can verify integrity
    import hashlib
    content_hash = hashlib.sha256(smoke_src.encode("utf-8")).hexdigest()[:16]
    console.print(f"  SHA256 (first 16 chars): [cyan]{content_hash}[/cyan]  ({len(smoke_src)} bytes)")
    if not typer.confirm("Trust and execute this remote script?"):
        console.print("[dim]Aborted.[/dim]")
        raise typer.Exit(code=0)

    with tempfile.NamedTemporaryFile(suffix="_smoke_test.py", mode="w", delete=False) as tmp:
        tmp.write(smoke_src)
        tmp_path = tmp.name

    try:
        smoke_argv = [sys.executable, tmp_path]
        if live:
            smoke_argv += ["--live", "--provider", provider]

        console.print(f"  $ {' '.join(smoke_argv[1:])}")
        # Security: run smoke test with scrubbed environment
        _scrubbed_smoke_env = _scrub_env(os.environ)
        result = subprocess.run(smoke_argv, timeout=300, env=_scrubbed_smoke_env)
        if result.returncode != 0:
            exit_code = max(result.returncode, 1)
            console.print(f"[red]Smoke test failed (exit {result.returncode}).[/red]")
            raise typer.Exit(code=exit_code)
    except subprocess.TimeoutExpired:
        console.print("[red]Smoke test timed out after 300s.[/red]")
        raise typer.Exit(code=124)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    _done = "OK" if _ascii_mode else "✅"
    console.print(f"\n[green]{_done}  Hub install complete for {arxiv_id}.[/green]")
    console.print(
        f"[dim]Run `open-researcher hub apply {arxiv_id}` to write these settings into .research/config.yaml[/dim]"
    )


@hub_app.command()
def apply(
    arxiv_id: str = typer.Argument(help="ArXiv ID (e.g. 2507.19457)"),
    registry: str = typer.Option(HUB_REGISTRY_URL, "--registry", help="Hub registry base URL"),
    repo_path: str = typer.Option(".", "--path", help="Path to the research repo"),
) -> None:
    """
    Write Hub manifest bootstrap fields into .research/config.yaml.

    After running this, `open-researcher run` will use the Hub-verified
    install and smoke commands automatically.
    """
    research_dir = Path(repo_path) / ".research"

    try:
        manifest = fetch_manifest(arxiv_id, registry_url=registry)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    overrides = manifest_to_bootstrap_overrides(manifest)
    if not overrides:
        console.print("[yellow]No bootstrap overrides to write (manifest has no install/test commands).[/yellow]")
        return

    # Security: show commands from the remote manifest and require confirmation
    console.print(f"\n[bold]Hub manifest {arxiv_id} — commands to be written:[/bold]")
    for k, v in overrides.items():
        console.print(f"  [cyan]{k}[/cyan] = {v}")
    console.print(
        "\n[yellow]These commands come from a remote registry and will be executed "
        "during bootstrap. Review them carefully.[/yellow]"
    )
    if not typer.confirm("Trust and apply these commands?"):
        console.print("[dim]Aborted.[/dim]")
        raise typer.Exit(code=0)

    try:
        written = apply_manifest_to_config_yaml(
            manifest, research_dir, registry_url=registry, user_confirmed=True
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    _arrow = "->" if _ascii_mode else "\u2192"
    console.print(f"\n[bold]Applied Hub manifest {arxiv_id} {_arrow} .research/config.yaml[/bold]")
    for k, v in written.items():
        console.print(f"  [cyan]{k}[/cyan] = {v}")
    console.print("\n[dim]Run `open-researcher run` to start the workflow with Hub-verified settings.[/dim]")


_SENSITIVE_ENV_PREFIXES = (
    "API_KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL",
    "AWS_", "AZURE_", "GCP_", "GOOGLE_", "OPENAI_", "ANTHROPIC_",
    "HF_TOKEN", "HUGGING_FACE", "WANDB_API_KEY", "COMET_API_KEY",
    "GITHUB_TOKEN", "GH_TOKEN", "GITLAB_TOKEN", "NPM_TOKEN",
    "PRIVATE_KEY", "SSH_AUTH_SOCK",
    "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "NETRC",
    "NPM_CONFIG_", "DOCKER_CONFIG", "KUBECONFIG",
)


def _scrub_env(environ: dict[str, str]) -> dict[str, str]:
    """Return a copy of *environ* with sensitive variables removed.

    Used when running untrusted commands from the Hub registry so that
    API keys and cloud credentials are not leaked to arbitrary scripts.
    """
    scrubbed: dict[str, str] = {}
    for key, value in environ.items():
        upper = key.upper()
        if any(upper.startswith(prefix) or upper.endswith(prefix) for prefix in _SENSITIVE_ENV_PREFIXES):
            continue
        scrubbed[key] = value
    return scrubbed


def _get_folder(arxiv_id: str, registry: str) -> str:
    index = fetch_index(registry_url=registry)
    folder = index.get(arxiv_id)
    if not folder:
        raise ValueError(f"arxiv_id {arxiv_id!r} not found in Hub index")
    return folder
