"""Demo command — launch TUI with pre-populated sample data, no agent needed."""

import json
import shlex
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rich.console import Console

console = Console()

# ---------------------------------------------------------------------------
# Sample data generators
# ---------------------------------------------------------------------------

_EXPERIMENTS = [
    ("baseline", "keep", 0.412, "Baseline: standard training config"),
    ("lr-warmup", "keep", 0.389, "Add cosine learning rate warmup"),
    ("bigger-ctx", "discard", 0.425, "Increase context length 256→512"),
    ("dropout-0.2", "keep", 0.371, "Add dropout=0.2 to all layers"),
    ("layernorm", "discard", 0.395, "Switch to pre-LayerNorm"),
    ("gelu-act", "keep", 0.362, "Replace ReLU with GELU activation"),
    ("head-dim-up", "crash", None, "Double attention head dimension (OOM)"),
    ("weight-decay", "keep", 0.358, "Add weight decay 0.1"),
    ("grad-clip", "keep", 0.351, "Gradient clipping max_norm=1.0"),
    ("rope-embed", "discard", 0.367, "Switch to RoPE embeddings"),
    ("flash-attn", "keep", 0.343, "Enable FlashAttention-2"),
    ("batch-x2", "keep", 0.338, "Double batch size with grad accum"),
    ("mixup-aug", "discard", 0.355, "MixUp data augmentation"),
    ("kv-cache", "keep", 0.335, "KV-cache optimization for inference"),
    ("final-tune", "keep", 0.329, "Fine-tune with reduced LR 1e-5"),
]

_IDEAS = [
    {
        "description": "Try SwiGLU activation function",
        "status": "done",
        "priority": 2,
        "result": {"metric_value": 0.341, "verdict": "completed"},
    },
    {
        "description": "Implement grouped-query attention",
        "status": "done",
        "priority": 1,
        "result": {"metric_value": 0.337, "verdict": "completed"},
    },
    {"description": "Add sliding window attention", "status": "running", "priority": 3, "result": None},
    {"description": "Try Lion optimizer instead of AdamW", "status": "pending", "priority": 4, "result": None},
    {"description": "Implement speculative decoding", "status": "pending", "priority": 5, "result": None},
    {
        "description": "Add ALiBi positional encoding",
        "status": "skipped",
        "priority": 6,
        "result": {"metric_value": None, "verdict": "incompatible with current arch"},
    },
    {"description": "Knowledge distillation from larger model", "status": "pending", "priority": 7, "result": None},
    {"description": "Quantization-aware training (INT8)", "status": "pending", "priority": 8, "result": None},
]


def _build_results_tsv(base_time: datetime) -> str:
    """Generate results.tsv with realistic experiment data."""
    header = "timestamp\tcommit\tprimary_metric\tmetric_value\tsecondary_metrics\tstatus\tdescription"
    lines = [header]
    for i, (tag, status, val, desc) in enumerate(_EXPERIMENTS):
        ts = (base_time + timedelta(minutes=i * 45)).isoformat()
        commit = f"{i + 1:07x}"
        val_str = f"{val:.3f}" if val is not None else ""
        sec = json.dumps({"train_loss": round((val or 0.5) - 0.02, 3)}) if val else "{}"
        lines.append(f"{ts}\t{commit}\tval_loss\t{val_str}\t{sec}\t{status}\t{desc}")
    return "\n".join(lines) + "\n"


def _build_idea_pool() -> dict:
    """Generate idea_pool.json with sample ideas."""
    ideas = []
    now = datetime.now(timezone.utc)
    for i, idea_data in enumerate(_IDEAS):
        idea = {
            "id": f"idea-{i + 1:03d}",
            "description": idea_data["description"],
            "source": "ai" if i < 5 else "user",
            "category": "architecture" if i % 2 == 0 else "training",
            "priority": idea_data["priority"],
            "status": idea_data["status"],
            "gpu_hint": "auto",
            "result": idea_data["result"],
            "created_at": (now - timedelta(hours=10 - i)).isoformat(),
        }
        ideas.append(idea)
    return {"ideas": ideas}


def _build_activity() -> dict:
    """Generate activity.json showing an active experiment."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "experiment_agent": {
            "status": "experimenting",
            "detail": "Running: sliding window attention (idea-003)",
            "updated_at": now,
            "workers": [
                {"id": "worker-0", "status": "running", "idea": "sliding window attention", "updated_at": now},
            ],
        },
        "manager_agent": {
            "status": "idle",
            "detail": "Waiting for the next research cycle",
            "updated_at": now,
        },
    }


_PROJECT_UNDERSTANDING = """# Project Understanding

## Overview
This is a nanoGPT implementation — a minimal GPT-2 style language model for character-level text generation.
The model is trained on the Shakespeare dataset (~1MB of text).

## Key Files
- `train.py` — Main training loop with AdamW optimizer
- `model.py` — GPT model definition (Transformer blocks, attention, MLP)
- `config/` — Training configurations (learning rate, batch size, etc.)
- `data/shakespeare_char/` — Dataset preparation and tokenization

## Architecture
- 6 Transformer layers, 6 attention heads, embedding dim 384
- Character-level tokenizer (65 unique characters)
- ~10M parameters total

## Evaluation
Primary metric: **validation loss** (cross-entropy, lower is better).
Measured every 200 training iterations on held-out validation set.
"""

_LITERATURE = """# Related Work & Literature

## Relevant Techniques
1. **FlashAttention** (Dao et al., 2022) — IO-aware exact attention, 2-4x speedup
2. **RoPE** (Su et al., 2021) — Rotary position embeddings, better length generalization
3. **SwiGLU** (Shazeer, 2020) — Gated activation, used in LLaMA/PaLM
4. **Grouped-Query Attention** (Ainslie et al., 2023) — Reduces KV-cache memory
5. **Gradient Clipping** — Standard practice for training stability

## Baseline References
- Original nanoGPT: val_loss ~1.47 (char-level Shakespeare)
- With basic tuning: val_loss ~1.38-1.42
"""

_EVALUATION = """# Evaluation Design

## Primary Metric
- **val_loss** (validation cross-entropy loss)
- Direction: **lower is better**
- Measured every 200 iterations on the Shakespeare validation set

## Evaluation Command
```bash
python train.py --eval_only --ckpt_path=out/ckpt.pt
```

## Success Criteria
- Any experiment that reduces val_loss below the current best is marked **keep**
- Experiments that increase val_loss are marked **discard**
- Experiments that crash (OOM, NaN, etc.) are marked **crash** and auto-rolled back
"""


def _populate_research(research_dir: Path) -> None:
    """Fill .research/ with realistic sample data."""
    base_time = datetime.now(timezone.utc) - timedelta(hours=12)

    (research_dir / "results.tsv").write_text(_build_results_tsv(base_time))
    (research_dir / "idea_pool.json").write_text(json.dumps(_build_idea_pool(), indent=2))
    (research_dir / "activity.json").write_text(json.dumps(_build_activity(), indent=2))
    (research_dir / "control.json").write_text(json.dumps({"paused": False, "skip_current": False}))
    (research_dir / "events.jsonl").write_text("")
    (research_dir / "experiment_progress.json").write_text(
        json.dumps({"phase": "experimenting", "experiment_count": 15})
    )
    (research_dir / "gpu_status.json").write_text(
        json.dumps(
            {
                "gpus": [
                    {
                        "host": "localhost",
                        "device": 0,
                        "name": "NVIDIA RTX 4090",
                        "memory_total": 24564,
                        "memory_used": 18200,
                        "memory_free": 6364,
                        "allocated_to": "worker-0",
                        "reservations": [
                            {
                                "reservation_id": "demo-001",
                                "tag": "worker-0",
                                "gpu_count": 1,
                                "memory_mb": 4096,
                                "started_at": "2026-03-08T10:00:00Z",
                                "kind": "experiment",
                            }
                        ],
                    },
                    {
                        "host": "localhost",
                        "device": 1,
                        "name": "NVIDIA RTX 4090",
                        "memory_total": 24564,
                        "memory_used": 2100,
                        "memory_free": 22464,
                        "allocated_to": None,
                        "reservations": [],
                    },
                ],
            }
        )
    )

    (research_dir / "config.yaml").write_text(
        "mode: autonomous\n"
        "experiment:\n"
        "  timeout: 600\n"
        "  max_consecutive_crashes: 3\n"
        "  max_parallel_workers: 2\n"
        "metrics:\n"
        "  primary:\n"
        "    name: val_loss\n"
        "    direction: lower_is_better\n"
        "research:\n"
        "  web_search: true\n"
        "  search_interval: 5\n"
        "gpu:\n"
        "  remote_hosts: []\n"
    )

    (research_dir / "project-understanding.md").write_text(_PROJECT_UNDERSTANDING)
    (research_dir / "literature.md").write_text(_LITERATURE)
    (research_dir / "evaluation.md").write_text(_EVALUATION)
    (research_dir / "ideas.md").write_text("# Ideas\n\nSee `idea_pool.json` for structured idea tracking.\n")
    (research_dir / "run.log").write_text("")

    scripts = research_dir / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "record.py").write_text("")
    (scripts / "rollback.sh").write_text("")

    (research_dir / "worktrees").mkdir(exist_ok=True)


_DEMO_LOG_LINES = [
    "[dim]───── 💭 Thinking ─────[/dim]",
    "[dim italic]Analyzing experiment results... val_loss improved from 0.335 to 0.329[/dim italic]",
    "[dim italic]The fine-tuning with reduced learning rate shows consistent improvement.[/dim italic]",
    "[dim italic]Next idea to try: sliding window attention (idea-003)[/dim italic]",
    "[bold]───── ✦ Acting ─────[/bold]",
    "[bold cyan]\\[exp] Starting experiment: sliding window attention[/bold cyan]",
    "[bold magenta]file update: model.py[/bold magenta]",
    "[bold white]diff --git a/model.py b/model.py[/bold white]",
    "[yellow]@@ -45,6 +45,12 @@[/yellow]",
    "[green]+    def sliding_window_attention(self, q, k, v, window_size=256):[/green]",
    '[green]+        """Apply sliding window attention pattern."""[/green]',
    "[green]+        seq_len = q.size(-2)[/green]",
    "[green]+        mask = torch.ones(seq_len, seq_len, device=q.device)[/green]",
    "[green]+        mask = torch.triu(mask, diagonal=-window_size)[/green]",
    "[green]+        return F.scaled_dot_product_attention(q, k, v, attn_mask=mask)[/green]",
    "[cyan]step 200: train loss 0.317, val loss 0.341, lr 3.00e-04[/cyan]",
    "[cyan]step 400: train loss 0.312, val loss 0.338, lr 2.85e-04[/cyan]",
    "[cyan]step 600: train loss 0.309, val loss 0.336, lr 2.55e-04[/cyan]",
    "[cyan]step 800: train loss 0.307, val loss 0.334, lr 2.15e-04[/cyan]",
    "[bold cyan]\\[exp] Experiment complete: val_loss=0.334 (improved from 0.335)[/bold cyan]",
    "[bold cyan]\\[exp] Recording result and committing...[/bold cyan]",
]


def _inject_logs(app, delay: float = 0.3) -> None:
    """Slowly inject demo log lines into the TUI."""
    time.sleep(1.5)  # wait for TUI to mount
    for line in _DEMO_LOG_LINES:
        try:
            app.call_from_thread(app._do_append_log, line)
        except Exception:
            pass
        time.sleep(delay)


def _setup_demo_repo(repo: Path) -> None:
    """Initialize a minimal git repo and populate .research/ with sample data."""
    subprocess.run(["git", "init", "--quiet"], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "demo@open-researcher.dev"],
        cwd=str(repo),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Demo"],
        cwd=str(repo),
        capture_output=True,
    )
    (repo / "train.py").write_text("# nanoGPT training script\n")
    (repo / "model.py").write_text("# GPT model definition\n")
    subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial", "--quiet"],
        cwd=str(repo),
        capture_output=True,
    )
    research = repo / ".research"
    research.mkdir()
    _populate_research(research)


def do_demo(serve: bool = False, port: int = 8000) -> None:
    """Launch the TUI with pre-populated sample data for a hands-on demo."""
    console.print("[bold green]Open Researcher Demo[/bold green]")

    if serve:
        try:
            from textual_serve.server import Server
        except ImportError:
            console.print(
                "[red]textual-serve is not installed.[/red]\n"
                "Install it with: [bold]pip install open-researcher[serve][/bold]"
            )
            return

        import atexit

        tmp_obj = tempfile.TemporaryDirectory(prefix="or-demo-")
        repo = Path(tmp_obj.name)
        atexit.register(tmp_obj.cleanup)

        _setup_demo_repo(repo)

        # Write a self-contained launcher script that textual-serve can execute
        python_exe = str(Path(__file__).parents[1] / ".." / ".." / ".venv" / "bin" / "python")
        # Resolve to absolute path; fall back to sys.executable if venv not found
        import sys as _sys

        python_exe = str(Path(python_exe).resolve()) if Path(python_exe).exists() else _sys.executable

        launcher = repo / "_serve_launcher.py"
        launcher.write_text(
            "import threading\n"
            "from pathlib import Path\n"
            "from open_researcher.tui.app import ResearchApp\n"
            "from open_researcher.demo_cmd import _inject_logs\n"
            f"repo_path = Path({str(repo)!r})\n"
            "app = ResearchApp(repo_path)\n"
            "def on_ready():\n"
            "    t = threading.Thread(target=_inject_logs, args=(app,), daemon=True)\n"
            "    t.start()\n"
            "app._on_ready = on_ready\n"
            "app.run()\n"
        )

        console.print(f"Launching TUI in browser at [bold]http://localhost:{port}[/bold]\n")
        console.print("[dim]Press Ctrl+C to stop the server.[/dim]\n")
        server = Server(f"{shlex.quote(python_exe)} {shlex.quote(str(launcher))}", port=port)
        server.serve()
        return

    console.print("Launching TUI with sample nanoGPT experiment data...\n")

    with tempfile.TemporaryDirectory(prefix="or-demo-") as tmp:
        repo = Path(tmp)
        _setup_demo_repo(repo)

        from open_researcher.tui.app import ResearchApp

        def on_ready():
            t = threading.Thread(target=_inject_logs, args=(app,), daemon=True)
            t.start()

        app = ResearchApp(repo, on_ready=on_ready)
        console.print("[dim]Press q to exit. Use 1-5 to switch tabs.[/dim]\n")
        app.run()

    console.print("\n[green]Demo complete![/green]")
    console.print(
        "To start with your own project:\n"
        "  [bold]cd your-project[/bold]\n"
        "  [bold]open-researcher init[/bold]\n"
        "  [bold]open-researcher run --agent claude-code[/bold]"
    )
