# Example: HuggingFace GLUE Fine-tuning Research

This example shows how to use PaperFarm with HuggingFace Transformers to optimize GLUE benchmark fine-tuning (SST-2 sentiment classification).

## Setup

```bash
git clone https://github.com/huggingface/transformers.git
cd transformers
pip install -e ".[torch]"
pip install datasets evaluate accelerate

# Initialize PaperFarm
PaperFarm init --tag glue

# Launch research
PaperFarm run --agent claude-code
```

## What the Agent Will Try

- Hyperparameter search (learning rate, batch size, epochs)
- Learning rate schedules (linear warmup, cosine decay)
- Model selection (BERT vs RoBERTa vs DeBERTa)
- Data augmentation strategies
- Regularization techniques (dropout, weight decay, label smoothing)

## Metrics

- **Primary:** `eval_accuracy` (higher is better) on SST-2 validation set
- **Evaluation:** Run fine-tuning script with reduced epochs, extract eval_accuracy
