# Example: Whisper Fine-tuning

Reduce [OpenAI Whisper](https://github.com/openai/whisper) word error rate (WER) with Open Researcher — from baseline ~35% to ~15% by optimizing fine-tuning on speech data.

## Prerequisites

- Python 3.10+
- PyTorch 2.0+ with 16GB+ GPU
- One AI agent installed: `claude` (Claude Code), `codex`, `aider`, or `opencode`

## Setup

```bash
# 1. Create project directory
mkdir whisper-finetune && cd whisper-finetune
pip install transformers datasets evaluate jiwer soundfile librosa accelerate

# Write a baseline fine-tuning script (train.py) that:
#   - Loads whisper-small from HuggingFace
#   - Fine-tunes on a Common Voice subset
#   - Prints WER at the end

# 2. Initialize Open Researcher
pip install open-researcher
open-researcher init --tag whisper

# 3. Launch autonomous research
open-researcher run --agent claude-code

# Or run headless with a specific goal
open-researcher start --mode headless \
  --goal "Reduce Whisper word error rate (WER) on speech recognition by optimizing fine-tuning hyperparameters, data preprocessing, and training strategies" \
  --max-experiments 20
```

## What the Agent Will Try

- Learning rate and warmup steps tuning
- SpecAugment parameters (frequency/time masking)
- Data augmentation (speed perturbation, noise injection)
- Beam search size and decoding strategies
- Gradient accumulation steps
- Training epochs and early stopping
- Feature extraction preprocessing
- Mixed precision training settings

## Metrics

- **Primary:** `wer` (lower is better) — Word Error Rate on validation set
- **Evaluation:** Run fine-tuning, decode validation set, compute WER with `jiwer`
- **Typical baseline:** ~35% WER (whisper-small, no fine-tuning)
- **Typical best after ~15 experiments:** ~15% WER
