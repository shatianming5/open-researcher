# Project Understanding

## Project Goal
HuggingFace Transformers is the most popular library for NLP model training and inference. This research focuses on optimizing SST-2 (Stanford Sentiment Treebank) fine-tuning — a binary sentiment classification task.

## Code Structure
- `examples/pytorch/text-classification/run_glue.py` — Main GLUE fine-tuning script
- `src/transformers/models/` — Model implementations (BERT, RoBERTa, etc.)
- `src/transformers/trainer.py` — Training loop
- `src/transformers/optimization.py` — Learning rate schedules

## How to Run
```bash
python examples/pytorch/text-classification/run_glue.py \
  --model_name_or_path bert-base-uncased \
  --task_name sst2 \
  --do_train --do_eval \
  --max_seq_length 128 \
  --per_device_train_batch_size 32 \
  --learning_rate 2e-5 \
  --num_train_epochs 1 \
  --output_dir /tmp/sst2
```
