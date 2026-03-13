#!/usr/bin/env python3
"""
Open Researcher Demo — 演示多 Agent 系统的核心功能。

用法: source .venv/bin/activate && python demo.py

演示内容:
  1. 初始化 .research/ 目录
  2. IdeaPool 增删改查
  3. ActivityMonitor 状态追踪
  4. GPUManager 模拟分配
  5. 控制文件读写 (pause/skip)
  6. 启动 Textual TUI（交互式界面）
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from open_researcher.activity import ActivityMonitor
from open_researcher.gpu_manager import GPUManager
from open_researcher.idea_pool import IdeaPool
from open_researcher.init_cmd import do_init
from open_researcher.status_cmd import PHASE_NAMES, parse_research_state
from open_researcher.tui.app import ResearchApp

# ── 准备临时项目目录 ──────────────────────────────────────────────

DEMO_DIR = Path(tempfile.mkdtemp(prefix="open-researcher-demo-"))
print(f"\n{'=' * 60}")
print("  Open Researcher Demo")
print(f"  临时目录: {DEMO_DIR}")
print(f"{'=' * 60}\n")


# ── Step 1: 初始化 .research/ ─────────────────────────────────────

print(">>> Step 1: 初始化 .research/ 目录\n")

# git init is required before do_init
subprocess.run(["git", "init", "--quiet"], cwd=DEMO_DIR, capture_output=True, check=True)
subprocess.run(["git", "config", "user.email", "demo@open-researcher.dev"], cwd=DEMO_DIR, capture_output=True)
subprocess.run(["git", "config", "user.name", "Demo"], cwd=DEMO_DIR, capture_output=True)
(DEMO_DIR / "README.md").write_text("# Demo\n")
subprocess.run(["git", "add", "."], cwd=DEMO_DIR, capture_output=True)
subprocess.run(["git", "commit", "-m", "init", "--quiet"], cwd=DEMO_DIR, capture_output=True)

do_init(repo_path=DEMO_DIR, tag="demo")

research = DEMO_DIR / ".research"
print("\n生成的文件:")
for f in sorted(research.iterdir()):
    if f.is_file():
        size = f.stat().st_size
        print(f"  {f.name:<30} {size:>6} bytes")
    elif f.is_dir():
        print(f"  {f.name}/")
        for sub in sorted(f.iterdir()):
            print(f"    {sub.name:<28} {sub.stat().st_size:>6} bytes")

print()


# ── Step 2: IdeaPool 操作 ─────────────────────────────────────────

print(">>> Step 2: IdeaPool — Idea 生命周期演示\n")

pool = IdeaPool(research / "idea_pool.json")

# 添加 idea
ideas_data = [
    ("cosine LR + warmup 500 steps", "literature", "training", 1),
    ("gradient clipping 1.0", "original", "training", 2),
    ("AdamW + lr=3e-4", "literature", "training", 3),
    ("dropout 0.3 on FC layers", "original", "regularization", 4),
    ("data augmentation: mixup", "literature", "data", 5),
]

for desc, source, cat, pri in ideas_data:
    idea = pool.add(desc, source=source, category=cat, priority=pri)
    print(f"  + {idea['id']}: {desc} (pri={pri}, source={source})")

print(f"\n  Summary: {pool.summary()}")

# 选取最高优先级 idea 并标记 running
pending = pool.list_by_status("pending")
top = pending[0]
pool.update_status(top["id"], "running", experiment=1)
print(f"\n  >> 选取 {top['id']}: {top['description']} -> RUNNING (experiment #1)")

# 标记完成
pool.mark_done(top["id"], metric_value=0.873, verdict="kept")
print(f"  -- {top['id']}: done, kept (metric=0.873)")

# 跳过一个
second = pending[1]
pool.update_status(second["id"], "skipped")
print(f"  ~~ {second['id']}: {second['description']} -> SKIPPED")

# 手动添加用户 idea
user_idea = pool.add("try LAMB optimizer", source="user", category="training", priority=2)
print(f"  + {user_idea['id']}: {user_idea['description']} (user-added)")

print(f"\n  Final summary: {pool.summary()}")
print()


# ── Step 3: ActivityMonitor ───────────────────────────────────────

print(">>> Step 3: ActivityMonitor — Agent 状态追踪\n")

activity = ActivityMonitor(research)

activity.update("idea_agent", status="analyzing", detail="reviewing experiment #1 result")
activity.update(
    "experiment_agent",
    status="evaluating",
    idea="gradient clipping 1.0",
    experiment=2,
    gpu={"host": "local", "device": 0},
    branch="exp/grad-clip",
)

all_act = activity.get_all()
for agent_key, act in all_act.items():
    print(f"  {agent_key}:")
    for k, v in act.items():
        print(f"    {k}: {v}")
    print()


# ── Step 4: GPUManager 模拟 ──────────────────────────────────────

print(">>> Step 4: GPUManager — GPU 分配模拟\n")

FAKE_NVIDIA_SMI = """\
index, memory.total [MiB], memory.used [MiB], memory.free [MiB], utilization.gpu [%]
0, 24576 MiB, 2048 MiB, 22528 MiB, 10 %
1, 24576 MiB, 12000 MiB, 12576 MiB, 55 %
2, 81920 MiB, 0 MiB, 81920 MiB, 0 %
3, 81920 MiB, 40000 MiB, 41920 MiB, 60 %
"""

gpu_mgr = GPUManager(research / "gpu_status.json")

with patch("subprocess.run") as mock_run:
    mock_run.return_value = MagicMock(returncode=0, stdout=FAKE_NVIDIA_SMI)

    # 分配一个 GPU
    result = gpu_mgr.allocate(tag="exp-001")
    print(f"  分配 exp-001: host={result[0]}, device={result[1]}")

    # 再分配一个
    result2 = gpu_mgr.allocate(tag="exp-002")
    print(f"  分配 exp-002: host={result2[0]}, device={result2[1]}")

print("\n  GPU 状态:")
for g in gpu_mgr.status():
    alloc = g.get("allocated_to") or "free"
    print(f"    GPU:{g['device']}  {g['memory_used']}/{g['memory_total']} MiB  free={g['memory_free']}  [{alloc}]")

# 释放
gpu_mgr.release(result[0], result[1])
print(f"\n  释放 GPU:{result[1]} -> free")
print()


# ── Step 5: 控制文件 ─────────────────────────────────────────────

print(">>> Step 5: Control 文件 — 暂停/跳过控制\n")

ctrl_path = research / "control.json"
ctrl = json.loads(ctrl_path.read_text())
print(f"  当前: {ctrl}")

ctrl["paused"] = True
ctrl_path.write_text(json.dumps(ctrl, indent=2))
print(f"  设置 paused=True: {json.loads(ctrl_path.read_text())}")

ctrl["paused"] = False
ctrl["skip_current"] = True
ctrl_path.write_text(json.dumps(ctrl, indent=2))
print(f"  设置 skip_current=True: {json.loads(ctrl_path.read_text())}")

ctrl["skip_current"] = False
ctrl_path.write_text(json.dumps(ctrl, indent=2))
print(f"  复位: {json.loads(ctrl_path.read_text())}")
print()


# ── Step 6: 模拟 results.tsv ─────────────────────────────────────

print(">>> Step 6: 写入模拟实验结果到 results.tsv\n")

results_path = research / "results.tsv"
rows = [
    "2026-03-09T10:00:00\tabc1234\taccuracy\t0.820000\t{}\tkeep\tbaseline",
    "2026-03-09T10:30:00\tdef5678\taccuracy\t0.873000\t{}\tkeep\tcosine LR + warmup",
    "2026-03-09T11:00:00\tghi9012\taccuracy\t0.810000\t{}\tdiscard\tgradient clipping",
    "2026-03-09T11:30:00\tjkl3456\taccuracy\t0.000000\t{}\tcrash\tdropout too high",
    "2026-03-09T12:00:00\tmno7890\taccuracy\t0.891000\t{}\tkeep\tAdamW + lr=3e-4",
]
with open(results_path, "a") as f:
    for row in rows:
        f.write(row + "\n")
        parts = row.split("\t")
        print(f"  [{parts[5]}] {parts[6]:<25} {parts[2]}={parts[3]}")

print()


# ── Step 7: Status 命令 ──────────────────────────────────────────

print(">>> Step 7: 解析研究状态\n")

# 写入一些内容让 phase 检测工作
(research / "project-understanding.md").write_text("# Project\nThis is a demo project.\nIt does cool things.\n")
(research / "literature.md").write_text("# Literature\nPaper A is relevant.\nMethod B works well.\n")
(research / "evaluation.md").write_text("# Evaluation\nUse accuracy as primary metric.\nRun test suite.\n")

# 切换到 research 分支 (git 已在 Step 1 初始化)
subprocess.run(["git", "checkout", "-b", "research/demo"], cwd=DEMO_DIR, capture_output=True)

state = parse_research_state(DEMO_DIR)
print(f"  Phase: {PHASE_NAMES.get(state['phase'], '?')}")
print(f"  Branch: {state['branch']}")
print(f"  Mode: {state['mode']}")
print(
    f"  Experiments: {state['total']} total, {state['keep']} kept, {state['discard']} discard, {state['crash']} crash"
)
if state["baseline_value"] is not None:
    print(f"  Baseline: {state['baseline_value']:.4f}")
    print(f"  Current:  {state['current_value']:.4f}")
    print(f"  Best:     {state['best_value']:.4f}")
print()


# ── Step 8: 启动 TUI ─────────────────────────────────────────────

print(">>> Step 8: 启动 Textual TUI 交互界面\n")
print("  快捷键:")
print("    [p] 暂停    [r] 恢复    [s] 跳过当前 idea")
print("    [a] 添加 idea    [g] GPU 状态    [l] 日志查看器")
print("    [q] 退出")
print()

try:
    answer = input("  是否启动 TUI？(y/n): ").strip().lower()
except EOFError:
    answer = "n"
if answer == "y":
    app = ResearchApp(DEMO_DIR, multi=True)
    app.run()
    print("\n  TUI 已退出。")
else:
    print("  跳过 TUI。")

print()


# ── 清理 ──────────────────────────────────────────────────────────

try:
    answer = input(f"  是否删除临时目录 {DEMO_DIR}？(y/n): ").strip().lower()
except EOFError:
    answer = "n"
if answer == "y":
    shutil.rmtree(DEMO_DIR)
    print("  已清理。")
else:
    print(f"  保留在: {DEMO_DIR}")

print(f"\n{'=' * 60}")
print("  Demo 完成！")
print(f"{'=' * 60}\n")
