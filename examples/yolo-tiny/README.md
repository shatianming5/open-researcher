# Example: YOLO Tiny Object Detection

Maximize [Ultralytics YOLOv8](https://github.com/ultralytics/ultralytics) mAP50 on COCO8 with Open Researcher — from baseline ~50% to ~65%+ by tuning training and architecture.

## Prerequisites

- Python 3.10+
- PyTorch 2.0+ with GPU recommended
- One AI agent installed: `claude` (Claude Code), `codex`, `aider`, or `opencode`

## Setup

```bash
# 1. Create project directory
mkdir yolo-tiny && cd yolo-tiny
pip install ultralytics

# Write a baseline training script (train.py) that:
#   - Uses YOLOv8n with COCO8 dataset (auto-downloaded)
#   - Trains for 10 epochs
#   - Prints mAP50 at the end

# 2. Initialize Open Researcher
pip install open-researcher
open-researcher init --tag yolo

# 3. Launch autonomous research
open-researcher run --agent claude-code

# Or run headless with a specific goal
open-researcher start --mode headless \
  --goal "Maximize mAP50 on COCO8 object detection by tuning YOLOv8 training hyperparameters, augmentation strategies, and model architecture choices" \
  --max-experiments 20
```

## What the Agent Will Try

- Image size tuning (320, 640, 1280)
- Augmentation strategies (mosaic, mixup, copy-paste, HSV augmentation)
- Learning rate and optimizer selection (SGD vs AdamW, warmup)
- Backbone variants (YOLOv8n, YOLOv8s, custom width/depth multipliers)
- Multi-scale training
- Anchor-free detection head adjustments
- Training epochs and patience tuning

## Metrics

- **Primary:** `mAP50` (higher is better) — mean Average Precision at IoU=0.5
- **Evaluation:** Run training with COCO8, extract mAP50 from validation results
- **Typical baseline:** ~50% mAP50 (YOLOv8n, 10 epochs, COCO8)
- **Typical best after ~15 experiments:** ~65%+
