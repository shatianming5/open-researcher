# Example: CartPole Reinforcement Learning

Maximize [CartPole-v1](https://gymnasium.farama.org/environments/classic_control/cart_pole/) average reward with Open Researcher — from baseline ~150 to the maximum score of 500.

## Prerequisites

- Python 3.10+
- PyTorch 2.0+
- gymnasium
- CPU is sufficient (no GPU needed)
- One AI agent installed: `claude` (Claude Code), `codex`, `aider`, or `opencode`

## Quick Start

```bash
# 1. Create project directory with a DQN training script
mkdir cartpole && cd cartpole
pip install torch gymnasium

# Write a baseline DQN script (train.py) that:
#   - Implements a simple DQN agent
#   - Trains on CartPole-v1
#   - Prints avg_reward at the end

# 2. Initialize Open Researcher
pip install open-researcher
open-researcher init --tag cartpole

# 3. Launch autonomous research
open-researcher run --agent claude-code

# Or run headless with a specific goal
open-researcher start --mode headless \
  --goal "Maximize average reward on CartPole-v1 by improving the RL algorithm, network architecture, reward shaping, and exploration strategy" \
  --max-experiments 20
```

## What the Agent Will Try

- Network architecture (layer count, hidden dimensions, activation functions)
- Algorithm improvements (DQN -> Double DQN -> Dueling DQN)
- Epsilon schedule (linear decay, exponential decay, adaptive)
- Replay buffer size and prioritized experience replay
- Reward shaping and clipping
- Target network update frequency (hard vs soft updates)
- Hyperparameters (learning rate, gamma, batch size)

## Metrics

- **Primary:** `avg_reward` (higher is better) — average episode reward over 100 evaluation episodes
- **Evaluation:** Run trained agent for 100 episodes, compute mean reward
- **Typical baseline:** ~150 avg_reward (simple DQN)
- **Typical best after ~10 experiments:** 500 (maximum possible score)
