# Evaluation Design

## Primary Metric
- **Name:** eval_accuracy
- **Direction:** higher_is_better
- **How to measure:** Run fine-tuning script with `--do_eval`, extract `eval_accuracy` from trainer output

## Evaluation Command
```bash
python examples/pytorch/text-classification/run_glue.py \
  --model_name_or_path bert-base-uncased \
  --task_name sst2 \
  --do_train --do_eval \
  --max_seq_length 128 \
  --per_device_train_batch_size 32 \
  --learning_rate 2e-5 \
  --num_train_epochs 1 \
  --output_dir /tmp/sst2-eval 2>&1 | \
  grep "eval_accuracy" | tail -1

```

## Secondary Metrics
- `eval_loss` — Validation loss
- `train_runtime` — Training time in seconds
- `train_samples_per_second` — Training throughput
