# Example: nanoGPT Research

Improve [karpathy/nanoGPT](https://github.com/karpathy/nanoGPT) validation loss with Open Researcher — from baseline ~0.41 to ~0.33 in an overnight run.

## Prerequisites

- Python 3.10+
- PyTorch with CUDA (1x GPU, any size — even 8GB works for char-level)
- One AI agent installed: `claude` (Claude Code), `codex`, `aider`, or `opencode`

## Quick Start (15 minutes)

```bash
# 1. Clone nanoGPT
git clone https://github.com/karpathy/nanoGPT.git
cd nanoGPT

# 2. Install Open Researcher
pip install open-researcher

# 3. Optional: inspect what bootstrap will do
open-researcher run --dry-run

# 4. Launch — Scout will fill bootstrap.*, then Open Researcher will
#    install deps, prepare Shakespeare data, run a smoke check, and
#    enter the research-v1 loop automatically
open-researcher run --agent claude-code

# 5. Check progress in the morning
open-researcher status --sparkline
open-researcher results --chart primary
open-researcher export --output report.md
```

## What Happens

| Phase | Time | What the system does |
|-------|------|----------------------|
| 1. Scout | ~2 min | Reads `train.py`, `model.py`, configs. Writes understanding, strategy, evaluation, and `bootstrap.*` hints |
| 2. Prepare | ~2 min | Installs `requirements.txt`, runs `data/shakespeare_char/prepare.py`, then smoke-checks the repo |
| 3. Review | ~1 min | Lets you inspect scout + prepare outputs in the TUI |
| 4. Baseline | ~5 min | Runs training, records baseline val_loss (~0.41) |
| 5. Experiment | ~5 min each | Manager/Critic/Experiment iterate on changes, tests, and evidence |

Each experiment is a git commit. Failed experiments are automatically rolled back.

## What the Agent Typically Tries

1. **Cosine LR warmup** → val_loss ~0.39 (keep)
2. **Dropout regularization** → val_loss ~0.37 (keep)
3. **GELU activation** → val_loss ~0.36 (keep)
4. **Weight decay tuning** → val_loss ~0.36 (keep)
5. **Gradient clipping** → val_loss ~0.35 (keep)
6. **FlashAttention** → val_loss ~0.34 (keep)
7. **Batch size doubling** → val_loss ~0.34 (keep)
8. **Final LR fine-tune** → val_loss ~0.33 (keep)

Results vary by agent and random seed. Typical improvement: **~20% reduction in val_loss**.

## Configuration

The default config works well. To customize, edit `.research/config.yaml`:

```yaml
experiment:
  timeout: 300              # 5 min per experiment (plenty for char-level nanoGPT)
  max_consecutive_crashes: 3
metrics:
  primary:
    name: val_loss
    direction: lower_is_better
```

## Bootstrap Overrides

If scout does not resolve the repo correctly on the first pass, edit `.research/config.yaml`:

```yaml
bootstrap:
  working_dir: "."
  install_command: "python -m pip install -r requirements.txt"
  data_command: "python data/shakespeare_char/prepare.py"
  smoke_command: "python train.py config/train_shakespeare_char.py --eval_only"
  expected_paths:
    - "data/shakespeare_char/train.bin"
    - "data/shakespeare_char/val.bin"
```

Then rerun:

```bash
open-researcher doctor
open-researcher run
```

## Metrics

- **Primary:** `val_loss` — validation cross-entropy loss (lower is better)
- **Evaluation:** `python train.py` with reduced iterations, extract final val_loss from stdout
- **Typical baseline:** ~0.41 (default nanoGPT config, Shakespeare char-level)
- **Typical best after ~15 experiments:** ~0.33
