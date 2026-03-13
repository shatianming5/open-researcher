"""PaperFarm Hub CLI commands."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import typer
from rich.console import Console

from open_researcher.hub import (
    HUB_REGISTRY_URL,
    apply_manifest_to_config_yaml,
    fetch_index,
    fetch_manifest,
    manifest_summary,
    manifest_to_bootstrap_overrides,
)

hub_app = typer.Typer(help="PaperFarm Hub — verified research environment registry.")
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
    registry: str = typer.Option(HUB_REGISTRY_URL, "--registry", help="Hub registry base URL"),
) -> None:
    """List all entries in the Hub registry."""
    try:
        index = fetch_index(registry_url=registry)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    console.print(f"\n[bold]PaperFarm Hub — {len(index)} entries[/bold]\n")
    for arxiv_id, folder in sorted(index.items()):
        console.print(f"  [cyan]{arxiv_id}[/cyan]  {folder}")


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

    env_block = manifest.get("env", {})
    install_cmd = env_block.get("install_command", "")
    test_cmd = env_block.get("test_command", "")

    console.print(f"\n[bold]Hub install — {arxiv_id}[/bold]")
    console.print(manifest_summary(manifest))

    # Check hardware requirements
    resources = manifest.get("resources", {})
    gpu_req = resources.get("gpu", "none")
    min_vram = resources.get("min_vram_gb")
    if gpu_req == "required":
        try:
            import torch
            if not torch.cuda.is_available():
                console.print(f"\n[yellow][WARN] This paper requires a GPU but CUDA is not available.[/yellow]")
            elif min_vram:
                vram = torch.cuda.get_device_properties(0).total_memory / 1e9
                if vram < min_vram:
                    console.print(
                        f"\n[yellow][WARN] Min VRAM required: {min_vram}GB, "
                        f"available: {vram:.1f}GB.[/yellow]"
                    )
        except ImportError:
            if gpu_req == "required":
                console.print(f"\n[yellow][WARN] GPU required but torch not installed — cannot check VRAM.[/yellow]")

    # Step 1: install
    if not install_cmd:
        console.print("\n[yellow]No install_command in manifest — skipping install step.[/yellow]")
    else:
        console.print(f"\n[bold]Step 1/2: Install[/bold]")
        console.print(f"  $ {install_cmd}")
        result = subprocess.run(install_cmd, shell=True)
        if result.returncode != 0:
            console.print(f"[red]Install failed (exit {result.returncode}).[/red]")
            raise typer.Exit(code=result.returncode)
        console.print("[green]Install OK.[/green]")

    # Step 2: smoke test
    if skip_smoke or not test_cmd:
        if not skip_smoke and not test_cmd:
            console.print("[yellow]No test_command in manifest — skipping smoke test.[/yellow]")
        raise typer.Exit(code=0)

    console.print(f"\n[bold]Step 2/2: Smoke test[/bold]")

    # Fetch smoke_test.py from Hub into a temp file
    folder = _get_folder(arxiv_id, registry)
    smoke_url = f"{registry}/hub/{folder}/smoke_test.py"
    console.print(f"  Fetching smoke_test.py from Hub...")
    try:
        with urllib.request.urlopen(smoke_url, timeout=10) as resp:
            smoke_src = resp.read().decode("utf-8")
    except Exception as exc:
        console.print(f"[red]Failed to fetch smoke_test.py: {exc}[/red]")
        raise typer.Exit(code=1)

    with tempfile.NamedTemporaryFile(suffix="_smoke_test.py", mode="w", delete=False) as tmp:
        tmp.write(smoke_src)
        tmp_path = tmp.name

    smoke_argv = [sys.executable, tmp_path]
    if live:
        smoke_argv += ["--live", "--provider", provider]

    console.print(f"  $ {' '.join(smoke_argv[1:])}")
    result = subprocess.run(smoke_argv)
    if result.returncode != 0:
        console.print(f"[red]Smoke test failed (exit {result.returncode}).[/red]")
        raise typer.Exit(code=result.returncode)

    console.print(f"\n[green]✅  Hub install complete for {arxiv_id}.[/green]")
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

    try:
        written = apply_manifest_to_config_yaml(manifest, research_dir)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    if not written:
        console.print("[yellow]No bootstrap overrides to write (manifest has no install/test commands).[/yellow]")
        return

    console.print(f"\n[bold]Applied Hub manifest {arxiv_id} → .research/config.yaml[/bold]")
    for k, v in written.items():
        console.print(f"  [cyan]{k}[/cyan] = {v}")
    console.print("\n[dim]Run `open-researcher run` to start the workflow with Hub-verified settings.[/dim]")


def _get_folder(arxiv_id: str, registry: str) -> str:
    index = fetch_index(registry_url=registry)
    folder = index.get(arxiv_id)
    if not folder:
        raise ValueError(f"arxiv_id {arxiv_id!r} not found in Hub index")
    return folder
