#!/usr/bin/env bash
set -Eeuo pipefail

# ═══════════════════════════════════════════════════════════
#  Open Researcher 端到端真实 Demo
#
#  在 macOS 上用 nanoGPT (Shakespeare char-level) 演示
#  双 Agent 多轮实验自动化研究系统
#
#  用法: chmod +x run_demo.sh && ./run_demo.sh
# ═══════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEMO_DIR="${SCRIPT_DIR}/_demo_workspace"
NANOGPT_DIR="${DEMO_DIR}/nanoGPT"
VENV_DIR="${SCRIPT_DIR}/.venv"

echo ""
echo "════════════════════════════════════════════════════════"
echo "  Open Researcher — nanoGPT 真实 Demo"
echo "════════════════════════════════════════════════════════"
echo ""

# ── 0. 检查 Python ──────────────────────────────────────────

if ! command -v python3 &>/dev/null; then
    echo "[ERROR] 需要 python3，请先安装"
    exit 1
fi

# ── 1. 确保 open-researcher venv 可用 ───────────────────────

echo ">>> Step 1: 准备 open-researcher 虚拟环境"
if [ ! -d "${VENV_DIR}" ]; then
    echo "  创建 .venv ..."
    python3 -m venv "${VENV_DIR}"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
pip install -q -e "${SCRIPT_DIR}[dev]" 2>/dev/null
echo "  open-researcher 已安装"
echo ""

# ── 2. 克隆 nanoGPT ─────────────────────────────────────────

echo ">>> Step 2: 克隆 nanoGPT"
mkdir -p "${DEMO_DIR}"
if [ -d "${NANOGPT_DIR}" ]; then
    echo "  已存在，跳过克隆"
else
    git clone --depth 1 https://github.com/karpathy/nanoGPT.git "${NANOGPT_DIR}"
fi
echo ""

# ── 3. 安装 nanoGPT 依赖 ────────────────────────────────────

echo ">>> Step 3: 安装 nanoGPT 依赖"
pip install -q torch numpy transformers datasets tiktoken tqdm 2>/dev/null
echo "  依赖已安装"
echo ""

# ── 4. 准备 Shakespeare 数据集 ──────────────────────────────

echo ">>> Step 4: 准备 Shakespeare 数据集"
if [ -f "${NANOGPT_DIR}/data/shakespeare_char/train.bin" ]; then
    echo "  数据已存在，跳过"
else
    echo "  下载并处理数据..."
    python3 "${NANOGPT_DIR}/data/shakespeare_char/prepare.py"
fi
echo ""

# ── 5. 快速验证 nanoGPT 可以跑通 ────────────────────────────

echo ">>> Step 5: 快速验证 nanoGPT 能正常训练 (50 iters)"
cd "${NANOGPT_DIR}"
python3 train.py config/train_shakespeare_char.py \
    --device=cpu --compile=False \
    --eval_iters=5 --log_interval=10 \
    --block_size=64 --batch_size=8 --n_layer=4 --n_head=4 --n_embd=128 \
    --max_iters=50 --lr_decay_iters=50 --dropout=0.0 2>&1 | tail -5
echo ""
echo "  nanoGPT 训练验证通过!"
echo ""

# ── 6. 初始化 open-researcher ────────────────────────────────

echo ">>> Step 6: 初始化 open-researcher (.research/)"
cd "${NANOGPT_DIR}"

# 清理旧的 .research (如果有)
rm -rf .research

open-researcher init --tag demo
echo ""

# ── 7. 写入适合 macOS CPU 的配置 ─────────────────────────────

echo ">>> Step 7: 配置 macOS CPU 优化参数"

cat > .research/config.yaml << 'YAML'
mode: autonomous
experiment:
  timeout: 300
  max_consecutive_crashes: 3
  max_parallel_workers: 0       # 0 = auto (one per available GPU), 1 = serial
  worker_agent: ""              # sub-worker agent (default: same as master)
metrics:
  primary:
    name: val_loss
    direction: lower_is_better
environment: |
  macOS, CPU-only, Python 3.10+, PyTorch
  训练命令 (CPU 小模型, ~2 min):
    python train.py config/train_shakespeare_char.py \
      --device=cpu --compile=False --eval_iters=20 --log_interval=50 \
      --block_size=64 --batch_size=12 --n_layer=4 --n_head=4 --n_embd=128 \
      --max_iters=500 --lr_decay_iters=500 --dropout=0.0
  评估: 从 stdout 提取 "val loss X.XXXX" 的最后一行
research:
  web_search: true
  search_interval: 3
gpu:
  remote_hosts: []
YAML

echo "  config.yaml 已写入"

# 写入评估文档
cat > .research/evaluation.md << 'MD'
# Evaluation Design

## Primary Metric
- **Name:** val_loss
- **Direction:** lower_is_better
- **Why:** Validation loss directly measures generalization on held-out Shakespeare text.

## Evaluation Command
```bash
python train.py config/train_shakespeare_char.py \
  --device=cpu --compile=False --eval_iters=20 --log_interval=50 \
  --block_size=64 --batch_size=12 --n_layer=4 --n_head=4 --n_embd=128 \
  --max_iters=500 --lr_decay_iters=500 --dropout=0.0 2>&1 | \
  grep "val loss" | tail -1 | awk '{print $NF}'
```

## How to Extract
The training script prints lines like:
```
step 500: train loss 1.7234, val loss 1.8821
```
Extract the last "val loss" value.

## Secondary Metrics
- `train_loss` — Training loss at eval time
MD

echo "  evaluation.md 已写入"
echo ""

# ── 8. 显示最终状态 ──────────────────────────────────────────

echo ">>> Step 8: idea pool 为空，启动后由 Idea Agent 自动生成"
echo ""

echo ">>> Step 9: 项目状态"
echo ""
open-researcher status
echo ""

# ── 10. 提示启动 ─────────────────────────────────────────────

echo "════════════════════════════════════════════════════════"
echo "  准备就绪！"
echo ""
echo "  工作目录: ${NANOGPT_DIR}"
echo ""
echo "  先执行:"
echo "    cd ${NANOGPT_DIR}"
echo "    source ${VENV_DIR}/bin/activate"
echo ""
echo "  ──── Claude Code ────"
echo "  open-researcher run --agent claude-code"
echo "  open-researcher run --multi --agent claude-code"
echo ""
echo "  ──── Codex CLI ────"
echo "  open-researcher run --agent codex"
echo "  open-researcher run --multi --agent codex"
echo ""
echo "  ──── 混合模式 (idea=codex, exp=claude) ────"
echo "  open-researcher run --idea-agent codex --exp-agent claude-code"
echo ""
echo "  ──── 并发实验模式 (多GPU) ────"
echo "  open-researcher run --multi --agent claude-code"
echo "  # Master Agent 自动检测 GPU 并分配 worker"
echo ""
echo "  ──── Dry run (只看命令) ────"
echo "  open-researcher run --agent codex --dry-run"
echo ""
echo "  ──── 查看结果 ────"
echo "  open-researcher results"
echo "  open-researcher status"
echo "════════════════════════════════════════════════════════"
echo ""
