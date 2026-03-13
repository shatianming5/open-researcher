"""PaperFarm Hub — manifest fetching and bootstrap config integration."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HUB_REGISTRY_URL = "https://raw.githubusercontent.com/XuanmiaoG/PaperFarm-Hub/main"


def _fetch_json(url: str, timeout: int = 10) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"HTTP {exc.code}: {url}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Network error fetching {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON at {url}: {exc}") from exc


def fetch_index(registry_url: str = HUB_REGISTRY_URL) -> dict[str, str]:
    """Return mapping of arxiv_id -> folder name from the Hub index."""
    index = _fetch_json(f"{registry_url}/index.json")
    entries = index.get("entries", {})
    if not isinstance(entries, dict):
        raise ValueError("Hub index.json has unexpected format")
    return entries


def fetch_manifest(arxiv_id: str, registry_url: str = HUB_REGISTRY_URL) -> dict[str, Any]:
    """Fetch paperfarm.json for the given arxiv_id from the Hub registry."""
    index = fetch_index(registry_url)
    folder = index.get(arxiv_id)
    if not folder:
        raise ValueError(
            f"arxiv_id {arxiv_id!r} not found in Hub index. "
            f"Available: {', '.join(sorted(index.keys()))}"
        )
    url = f"{registry_url}/hub/{folder}/paperfarm.json"
    return _fetch_json(url)


def manifest_to_bootstrap_overrides(manifest: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a paperfarm.json manifest into bootstrap config.yaml overrides.
    Only sets fields that are non-empty in the manifest.
    """
    overrides: dict[str, Any] = {}

    env = manifest.get("env", {})
    if env.get("install_command"):
        overrides["install_command"] = env["install_command"]
    if env.get("test_command"):
        overrides["smoke_command"] = env["test_command"]
    if env.get("python"):
        overrides["python"] = env["python"]

    resources = manifest.get("resources", {})
    if resources.get("gpu") == "required":
        overrides["requires_gpu"] = True

    return overrides


def manifest_summary(manifest: dict[str, Any]) -> str:
    """Return a short human-readable summary of a manifest."""
    paper = manifest.get("paper", {})
    env = manifest.get("env", {})
    resources = manifest.get("resources", {})
    status = manifest.get("status", {})
    agent = manifest.get("agent", {})

    lines = [
        f"  Title   : {paper.get('title', '?')}",
        f"  ArXiv   : {paper.get('arxiv_id', '?')}",
        f"  Repo    : {manifest.get('source', {}).get('git_repo', '?')}",
        f"  Manager : {env.get('manager', '?')}  Python {env.get('python', '?')}",
        f"  Install : {env.get('install_command', '?')}",
        f"  Test    : {env.get('test_command', '?')}",
        f"  GPU     : {resources.get('gpu', '?')}",
    ]

    if resources.get("min_vram_gb"):
        lines.append(f"  VRAM    : {resources['min_vram_gb']} GB min")

    if agent:
        providers = agent.get("providers", [])
        if providers:
            names = [p["name"] for p in providers if p.get("name")]
            lines.append(f"  LLM     : {', '.join(names)}")

    verified = status.get("verified", False)
    count = status.get("verified_count", 0)
    lines.append(f"  Verified: {'yes' if verified else 'no'} ({count} report(s))")

    issues = status.get("known_issues", [])
    if issues:
        lines.append(f"  Issues  : {issues[0]}")
        for issue in issues[1:]:
            lines.append(f"            {issue}")

    return "\n".join(lines)


def apply_manifest_to_config_yaml(
    manifest: dict[str, Any],
    research_dir: Path,
) -> dict[str, Any]:
    """
    Merge manifest bootstrap overrides into .research/config.yaml.
    Returns the dict of fields that were written.
    """
    import yaml

    config_path = research_dir / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"{config_path} not found — run `open-researcher init` first")

    try:
        raw = yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Failed to parse config.yaml: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("config.yaml must be a YAML mapping")

    overrides = manifest_to_bootstrap_overrides(manifest)
    if not overrides:
        return {}

    bootstrap = raw.setdefault("bootstrap", {})
    for key, value in overrides.items():
        bootstrap[key] = value

    # Record the Hub manifest source for audit trail
    bootstrap["hub_arxiv_id"] = manifest.get("paper", {}).get("arxiv_id", "")
    bootstrap["hub_manifest_source"] = (
        f"{HUB_REGISTRY_URL}/hub/"
        f"{manifest.get('_folder', '')}/paperfarm.json"
    )

    config_path.write_text(yaml.dump(raw, default_flow_style=False, allow_unicode=True))
    return overrides
