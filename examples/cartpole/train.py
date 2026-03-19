#!/usr/bin/env python3
"""Baseline DQN agent for CartPole-v1.

Trains a simple Deep Q-Network and evaluates over 100 episodes.
Prints ``avg_reward <value>`` so Open Researcher can parse the metric.
"""

import random
from collections import deque

import gymnasium as gym
import torch
import torch.nn as nn
import torch.optim as optim

# ---------------------------------------------------------------------------
# Hyperparameters (the agent will modify these across experiments)
# ---------------------------------------------------------------------------
HIDDEN_DIM = 128
LR = 1e-3
GAMMA = 0.99
EPSILON_START = 1.0
EPSILON_END = 0.01
EPSILON_DECAY = 500
BUFFER_SIZE = 10_000
BATCH_SIZE = 64
TARGET_UPDATE_FREQ = 10
NUM_TRAIN_EPISODES = 300
EVAL_EPISODES = 100


# ---------------------------------------------------------------------------
# Q-Network
# ---------------------------------------------------------------------------
class QNetwork(nn.Module):
    def __init__(self, state_dim: int, action_dim: int, hidden: int = HIDDEN_DIM):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden),
            nn.ReLU(),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, action_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ---------------------------------------------------------------------------
# Replay Buffer
# ---------------------------------------------------------------------------
class ReplayBuffer:
    def __init__(self, capacity: int = BUFFER_SIZE):
        self.buffer: deque = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        self.buffer.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int):
        import numpy as np

        batch = random.sample(self.buffer, batch_size)
        states, actions, rewards, next_states, dones = zip(*batch)
        return (
            torch.from_numpy(np.array(states, dtype=np.float32)),
            torch.tensor(actions, dtype=torch.long),
            torch.tensor(rewards, dtype=torch.float32),
            torch.from_numpy(np.array(next_states, dtype=np.float32)),
            torch.tensor(dones, dtype=torch.float32),
        )

    def __len__(self):
        return len(self.buffer)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
def train():
    env = gym.make("CartPole-v1")
    state_dim = env.observation_space.shape[0]
    action_dim = env.action_space.n

    policy_net = QNetwork(state_dim, action_dim)
    target_net = QNetwork(state_dim, action_dim)
    target_net.load_state_dict(policy_net.state_dict())
    target_net.eval()

    optimizer = optim.Adam(policy_net.parameters(), lr=LR)
    buffer = ReplayBuffer()

    steps_done = 0

    for episode in range(NUM_TRAIN_EPISODES):
        state, _ = env.reset()
        total_reward = 0.0

        while True:
            # Epsilon-greedy action selection
            eps = EPSILON_END + (EPSILON_START - EPSILON_END) * max(
                0.0, 1.0 - steps_done / EPSILON_DECAY
            )
            if random.random() < eps:
                action = env.action_space.sample()
            else:
                with torch.no_grad():
                    q_values = policy_net(torch.tensor(state, dtype=torch.float32))
                    action = q_values.argmax().item()

            next_state, reward, terminated, truncated, _ = env.step(action)
            done = terminated or truncated
            buffer.push(state, action, reward, next_state, done)
            state = next_state
            total_reward += reward
            steps_done += 1

            # Learn
            if len(buffer) >= BATCH_SIZE:
                s, a, r, ns, d = buffer.sample(BATCH_SIZE)
                q_vals = policy_net(s).gather(1, a.unsqueeze(1)).squeeze(1)
                with torch.no_grad():
                    next_q = target_net(ns).max(1).values
                    target = r + GAMMA * next_q * (1.0 - d)
                loss = nn.functional.mse_loss(q_vals, target)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            if done:
                break

        # Update target network
        if (episode + 1) % TARGET_UPDATE_FREQ == 0:
            target_net.load_state_dict(policy_net.state_dict())

        if (episode + 1) % 50 == 0:
            print(f"Episode {episode + 1}/{NUM_TRAIN_EPISODES}  reward={total_reward:.0f}  eps={eps:.3f}")

    env.close()
    return policy_net


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def evaluate(policy_net: QNetwork) -> float:
    env = gym.make("CartPole-v1")
    total = 0.0
    for _ in range(EVAL_EPISODES):
        state, _ = env.reset()
        ep_reward = 0.0
        while True:
            with torch.no_grad():
                action = policy_net(torch.tensor(state, dtype=torch.float32)).argmax().item()
            state, reward, terminated, truncated, _ = env.step(action)
            ep_reward += reward
            if terminated or truncated:
                break
        total += ep_reward
    env.close()
    return total / EVAL_EPISODES


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    policy = train()
    avg = evaluate(policy)
    print(f"avg_reward {avg:.1f}")
