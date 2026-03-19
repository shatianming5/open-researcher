# Example: CIFAR-10 Speedrun

Maximize [CIFAR-10](https://www.cs.toronto.edu/~kriz/cifar.html) test accuracy with Open Researcher — from baseline ~88% to ~95%+ by optimizing a small ResNet.

## Prerequisites

- Python 3.10+
- PyTorch 2.0+ (GPU recommended but CPU works)
- One AI agent installed: `claude` (Claude Code), `codex`, `aider`, or `opencode`

## Quick Start

```bash
# 1. Create project directory with a simple CIFAR-10 training script
mkdir cifar10-speedrun && cd cifar10-speedrun

# Write a baseline ResNet-18 training script (train.py) that:
#   - Downloads CIFAR-10 automatically
#   - Trains a simple ResNet-18 with no augmentation
#   - Prints test_accuracy at the end

# 2. Initialize Open Researcher
pip install open-researcher
open-researcher init --tag cifar10

# 3. Launch autonomous research
open-researcher run --agent claude-code

# Or run headless with a specific goal
open-researcher run --mode headless \
  --goal "Improve CIFAR-10 test accuracy above 95% by optimizing model architecture, data augmentation, learning rate schedule, and training techniques" \
  --max-experiments 20
```

## What the Agent Will Try

- Data augmentation (CutOut, MixUp, AutoAugment, RandomCrop + HorizontalFlip)
- Model architecture improvements (wider ResNet, PreAct ResNet, squeeze-excitation blocks)
- Learning rate schedules (cosine annealing, warm restarts, OneCycleLR)
- Optimizer tuning (SGD with momentum, AdamW, learning rate warmup)
- Regularization (dropout, weight decay, label smoothing)
- Batch size and normalization strategies
- Training techniques (gradient clipping, EMA)

## Metrics

- **Primary:** `test_accuracy` (higher is better) — top-1 accuracy on CIFAR-10 test set
- **Evaluation:** Run training script, extract final test_accuracy from stdout
- **Typical baseline:** ~88% (simple ResNet-18, no augmentation)
- **Typical best after ~15 experiments:** ~95%+
