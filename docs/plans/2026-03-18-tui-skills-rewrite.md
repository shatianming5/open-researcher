# TUI + Skills 极简重构实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 open-researcher 从 105 个文件 / 22,839 行重构为 7 个 Python 文件 / ~2,350 行的极简 "TUI + Skills" 架构。

**Architecture:** 三层分离 — SkillRunner（编排）、Agent（子进程执行）、TUI（展示+控制）。通信通过 .research/ 目录下 6 个状态文件完成，无内存共享。Skill 文件（.md）替代 Jinja2 模板，直接传给 agent 子进程作为 program.md。

**Tech Stack:** Python 3.10+, typer, rich, pyyaml, textual, filelock, plotext, textual-plotext

---

## 依赖关系

```
Task 1 (state.py) ← Task 2 (agent.py) ← Task 3 (skill_runner.py)
Task 1 ← Task 4 (parallel.py)
Task 3 + Task 4 ← Task 5 (cli.py)
Task 1 ← Task 6 (tui/widgets.py) ← Task 7 (tui/app.py)
```

Task 1 是所有后续任务的基础。Task 2/6 可与 Task 4 并行。

---

### Task 1: ResearchState — 状态文件读写层

**Files:**
- Create: `src/open_researcher_v2/state.py`
- Create: `src/open_researcher_v2/__init__.py`
- Test: `tests/v2/test_state.py`
- Test: `tests/v2/__init__.py`

> 注意：新代码放在 `open_researcher_v2` 包下，避免与现有代码冲突。最终验证通过后再替换。

**Step 1: 写失败测试 — config 读写**

```python
# tests/v2/__init__.py
# (empty)

# tests/v2/test_state.py
import pytest
from pathlib import Path
from open_researcher_v2.state import ResearchState


@pytest.fixture
def research_dir(tmp_path):
    d = tmp_path / ".research"
    d.mkdir()
    return d


@pytest.fixture
def state(research_dir):
    return ResearchState(research_dir)


class TestConfig:
    def test_load_default_config(self, state, research_dir):
        """No config.yaml => returns defaults."""
        cfg = state.load_config()
        assert cfg["protocol"] == "research-v1"
        assert cfg["metrics"]["primary"]["name"] == ""
        assert cfg["workers"]["max"] == 0

    def test_load_existing_config(self, state, research_dir):
        (research_dir / "config.yaml").write_text(
            "protocol: research-v1\nmetrics:\n  primary:\n    name: accuracy\n    direction: maximize\n"
        )
        cfg = state.load_config()
        assert cfg["metrics"]["primary"]["name"] == "accuracy"
        assert cfg["metrics"]["primary"]["direction"] == "maximize"
```

**Step 2: 运行测试确认失败**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_state.py::TestConfig -v`
Expected: FAIL — ModuleNotFoundError: No module named 'open_researcher_v2'

**Step 3: 实现 state.py 的 config 部分**

```python
# src/open_researcher_v2/__init__.py
# (empty)

# src/open_researcher_v2/state.py
"""Unified read/write layer for .research/ state files."""

from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from filelock import FileLock

_DEFAULT_CONFIG = {
    "protocol": "research-v1",
    "metrics": {
        "primary": {"name": "", "direction": "maximize"},
    },
    "bootstrap": {"steps": ["scout"]},
    "steps": [
        {"name": "manager", "skill": "manager.md"},
        {"name": "critic", "skill": "critic.md"},
        {"name": "experiment", "skill": "experiment.md"},
        {"name": "critic", "skill": "critic.md"},
    ],
    "workers": {"max": 0, "gpu_mem_per_worker_mb": 8192},
    "limits": {"max_rounds": 20, "timeout_minutes": 0},
    "agent": {"name": "claude-code", "config": {}},
}

_DEFAULT_GRAPH = {
    "repo_profile": {},
    "hypotheses": [],
    "experiment_specs": [],
    "evidence": [],
    "claim_updates": [],
    "branch_relations": [],
    "frontier": [],
    "counters": {"hypothesis": 0, "spec": 0, "frontier": 0, "evidence": 0, "claim": 0},
}

_RESULTS_HEADER = ["timestamp", "worker", "frontier_id", "status", "metric", "value", "description"]


class ResearchState:
    """Single access point for all .research/ state files."""

    def __init__(self, research_dir: Path):
        self.dir = research_dir
        self._graph_lock = FileLock(self.dir / ".graph.lock", timeout=10)
        self._activity_lock = FileLock(self.dir / ".activity.lock", timeout=5)

    # ── config.yaml ──────────────────────────────────────────────
    def load_config(self) -> dict:
        p = self.dir / "config.yaml"
        if not p.exists():
            return dict(_DEFAULT_CONFIG)
        with open(p, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        merged = dict(_DEFAULT_CONFIG)
        _deep_merge(merged, raw)
        return merged

    # ── graph.json ───────────────────────────────────────────────
    def load_graph(self) -> dict:
        p = self.dir / "graph.json"
        with self._graph_lock:
            if not p.exists():
                return dict(_DEFAULT_GRAPH)
            return json.loads(p.read_text(encoding="utf-8"))

    def save_graph(self, graph: dict) -> None:
        p = self.dir / "graph.json"
        with self._graph_lock:
            _atomic_write(p, json.dumps(graph, indent=2, ensure_ascii=False))

    # ── results.tsv ──────────────────────────────────────────────
    def load_results(self) -> list[dict]:
        p = self.dir / "results.tsv"
        if not p.exists():
            return []
        rows = []
        with open(p, encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                rows.append(dict(row))
        return rows

    def append_result(self, row: dict) -> None:
        p = self.dir / "results.tsv"
        needs_header = not p.exists() or p.stat().st_size == 0
        with open(p, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=_RESULTS_HEADER, delimiter="\t", extrasaction="ignore")
            if needs_header:
                w.writeheader()
            if "timestamp" not in row:
                row["timestamp"] = datetime.now(timezone.utc).isoformat()
            w.writerow(row)

    # ── activity.json ────────────────────────────────────────────
    def load_activity(self) -> dict:
        p = self.dir / "activity.json"
        with self._activity_lock:
            if not p.exists():
                return {"phase": "idle", "round": 0, "workers": [], "control": {"paused": False, "skip_current": False}}
            return json.loads(p.read_text(encoding="utf-8"))

    def save_activity(self, activity: dict) -> None:
        p = self.dir / "activity.json"
        with self._activity_lock:
            _atomic_write(p, json.dumps(activity, indent=2, ensure_ascii=False))

    def update_phase(self, phase: str, round_num: int | None = None) -> None:
        act = self.load_activity()
        act["phase"] = phase
        if round_num is not None:
            act["round"] = round_num
        self.save_activity(act)

    def update_worker(self, worker_id: str, **fields) -> None:
        act = self.load_activity()
        workers = act.setdefault("workers", [])
        existing = next((w for w in workers if w.get("id") == worker_id), None)
        if existing is None:
            existing = {"id": worker_id}
            workers.append(existing)
        existing.update(fields)
        existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save_activity(act)

    def is_paused(self) -> bool:
        return self.load_activity().get("control", {}).get("paused", False)

    def set_paused(self, paused: bool) -> None:
        act = self.load_activity()
        act.setdefault("control", {})["paused"] = paused
        self.save_activity(act)

    def consume_skip(self) -> bool:
        act = self.load_activity()
        ctrl = act.get("control", {})
        if ctrl.get("skip_current", False):
            ctrl["skip_current"] = False
            self.save_activity(act)
            return True
        return False

    # ── log.jsonl ────────────────────────────────────────────────
    def append_log(self, event: dict) -> None:
        p = self.dir / "log.jsonl"
        if "ts" not in event:
            event["ts"] = datetime.now(timezone.utc).isoformat()
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def tail_log(self, n: int = 50) -> list[dict]:
        p = self.dir / "log.jsonl"
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        result = []
        for line in lines[-n:]:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result

    # ── summary (for TUI) ────────────────────────────────────────
    def summary(self) -> dict:
        graph = self.load_graph()
        results = self.load_results()
        activity = self.load_activity()
        frontier = graph.get("frontier", [])
        return {
            "phase": activity.get("phase", "idle"),
            "round": activity.get("round", 0),
            "hypotheses": len(graph.get("hypotheses", [])),
            "experiments_total": len(frontier),
            "experiments_done": sum(1 for f in frontier if f.get("status") in ("archived", "rejected")),
            "experiments_running": sum(1 for f in frontier if f.get("status") == "running"),
            "results_count": len(results),
            "best_value": _best_value(results),
            "workers": activity.get("workers", []),
            "paused": activity.get("control", {}).get("paused", False),
        }


def _deep_merge(base: dict, override: dict) -> None:
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _best_value(results: list[dict]) -> str:
    kept = [r for r in results if r.get("status") == "keep"]
    if not kept:
        return "—"
    try:
        return str(max(kept, key=lambda r: float(r.get("value", 0)))["value"])
    except (ValueError, KeyError):
        return "—"
```

**Step 4: 运行测试确认通过**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_state.py::TestConfig -v`
Expected: PASS

**Step 5: 写更多测试 — graph, results, activity, log**

```python
# 追加到 tests/v2/test_state.py

class TestGraph:
    def test_load_default_graph(self, state):
        g = state.load_graph()
        assert g["hypotheses"] == []
        assert g["frontier"] == []
        assert "counters" in g

    def test_save_and_load_graph(self, state):
        g = state.load_graph()
        g["hypotheses"].append({"id": "hyp-001", "summary": "test"})
        state.save_graph(g)
        g2 = state.load_graph()
        assert len(g2["hypotheses"]) == 1
        assert g2["hypotheses"][0]["id"] == "hyp-001"


class TestResults:
    def test_empty_results(self, state):
        assert state.load_results() == []

    def test_append_and_load(self, state):
        state.append_result({
            "worker": "w0", "frontier_id": "f-001",
            "status": "keep", "metric": "acc", "value": "0.95",
            "description": "test run",
        })
        rows = state.load_results()
        assert len(rows) == 1
        assert rows[0]["value"] == "0.95"
        assert rows[0]["worker"] == "w0"
        assert "timestamp" in rows[0]

    def test_append_multiple(self, state):
        for i in range(3):
            state.append_result({"status": "keep", "value": str(i)})
        assert len(state.load_results()) == 3


class TestActivity:
    def test_default_activity(self, state):
        act = state.load_activity()
        assert act["phase"] == "idle"
        assert act["control"]["paused"] is False

    def test_update_phase(self, state):
        state.update_phase("bootstrap", round_num=1)
        act = state.load_activity()
        assert act["phase"] == "bootstrap"
        assert act["round"] == 1

    def test_update_worker(self, state):
        state.update_worker("w0", status="running", frontier_id="f-001", gpu=0)
        act = state.load_activity()
        assert len(act["workers"]) == 1
        assert act["workers"][0]["id"] == "w0"
        assert act["workers"][0]["gpu"] == 0

    def test_pause_resume(self, state):
        assert not state.is_paused()
        state.set_paused(True)
        assert state.is_paused()
        state.set_paused(False)
        assert not state.is_paused()

    def test_consume_skip(self, state):
        assert not state.consume_skip()
        act = state.load_activity()
        act["control"]["skip_current"] = True
        state.save_activity(act)
        assert state.consume_skip()
        assert not state.consume_skip()  # consumed


class TestLog:
    def test_empty_log(self, state):
        assert state.tail_log() == []

    def test_append_and_tail(self, state):
        state.append_log({"type": "skill_started", "skill": "scout"})
        state.append_log({"type": "output", "text": "hello"})
        logs = state.tail_log(10)
        assert len(logs) == 2
        assert logs[0]["type"] == "skill_started"
        assert "ts" in logs[0]

    def test_tail_limit(self, state):
        for i in range(100):
            state.append_log({"type": "output", "i": i})
        logs = state.tail_log(5)
        assert len(logs) == 5
        assert logs[0]["i"] == 95


class TestSummary:
    def test_summary_empty(self, state):
        s = state.summary()
        assert s["phase"] == "idle"
        assert s["hypotheses"] == 0
        assert s["results_count"] == 0
        assert s["best_value"] == "—"
```

**Step 6: 运行全部 state 测试**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_state.py -v`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add src/open_researcher_v2/__init__.py src/open_researcher_v2/state.py tests/v2/__init__.py tests/v2/test_state.py
git commit -m "feat(v2): add ResearchState — unified .research/ file access layer"
```

---

### Task 2: Agent — 子进程封装

**Files:**
- Create: `src/open_researcher_v2/agent.py`
- Test: `tests/v2/test_agent.py`

**Step 1: 写失败测试**

```python
# tests/v2/test_agent.py
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from open_researcher_v2.agent import Agent, AgentAdapter, create_agent


class TestAgentAdapter:
    def test_create_claude_code(self):
        a = create_agent("claude-code")
        assert isinstance(a, AgentAdapter)
        assert a.name == "claude-code"

    def test_create_codex(self):
        a = create_agent("codex")
        assert a.name == "codex"

    def test_create_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown agent"):
            create_agent("nonexistent-agent")


class TestAgent:
    def test_agent_writes_program_and_calls_adapter(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()

        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.run.return_value = 0

        agent = Agent(mock_adapter)
        code = agent.run(
            workdir=tmp_path,
            program_content="# Test program\nDo something.",
            program_file="test_program.md",
        )
        assert code == 0
        mock_adapter.run.assert_called_once()
        # program file should have been written
        assert (research_dir / "test_program.md").read_text() == "# Test program\nDo something."

    def test_agent_passes_env(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()

        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.run.return_value = 0

        agent = Agent(mock_adapter)
        agent.run(
            workdir=tmp_path,
            program_content="test",
            env={"GPU_ID": "3"},
        )
        call_kwargs = mock_adapter.run.call_args
        assert call_kwargs.kwargs.get("env", {}).get("GPU_ID") == "3" or \
               call_kwargs[1].get("env", {}).get("GPU_ID") == "3"

    def test_agent_streams_output(self, tmp_path):
        research_dir = tmp_path / ".research"
        research_dir.mkdir()

        mock_adapter = MagicMock(spec=AgentAdapter)
        mock_adapter.run.return_value = 0

        lines = []
        agent = Agent(mock_adapter)
        agent.run(
            workdir=tmp_path,
            program_content="test",
            on_output=lines.append,
        )
        # on_output should have been forwarded
        call_kwargs = mock_adapter.run.call_args
        assert call_kwargs.kwargs.get("on_output") is not None or \
               call_kwargs[1].get("on_output") is not None
```

**Step 2: 运行测试确认失败**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_agent.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: 实现 agent.py**

```python
# src/open_researcher_v2/agent.py
"""Thin wrapper around agent CLI subprocesses.

Preserves the existing AgentAdapter pattern from open_researcher.agents.base
but keeps only the essential interface.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable


class AgentAdapter(ABC):
    """Minimal agent adapter interface."""

    name: str
    command: str

    def __init__(self, config: dict | None = None):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._config = config or {}

    def check_installed(self) -> bool:
        return shutil.which(self.command) is not None

    @abstractmethod
    def run(
        self,
        workdir: Path,
        on_output: Callable[[str], None] | None = None,
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
    ) -> int:
        """Launch agent subprocess, stream output, return exit code."""

    def terminate(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.send_signal(signal.SIGTERM)

    def _run_process(
        self,
        cmd: list[str],
        workdir: Path,
        on_output: Callable[[str], None] | None = None,
        stdin_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> int:
        run_env = {**os.environ, **(env or {})}
        with self._lock:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(workdir),
                stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=run_env,
                text=True,
            )
        proc = self._proc
        if stdin_text:
            proc.stdin.write(stdin_text)
            proc.stdin.close()
        for line in proc.stdout:
            line = line.rstrip("\n")
            if on_output:
                on_output(line)
        return proc.wait()


# ── Concrete adapters ────────────────────────────────────────────

class ClaudeCodeAdapter(AgentAdapter):
    name = "claude-code"
    command = "claude"

    def run(self, workdir, on_output=None, program_file="program.md", env=None):
        program_md = workdir / ".research" / program_file
        try:
            prompt = program_md.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            if on_output:
                on_output(f"[claude-code] failed to read {program_md}: {exc}")
            return 1
        flags = ["--print", "--output-format", "text", "--verbose"]
        model = self._config.get("model", "")
        if model:
            flags += ["--model", str(model)]
        cmd = [self.command, "-p", prompt, *flags]
        return self._run_process(cmd, workdir, on_output, env=env)


class CodexAdapter(AgentAdapter):
    name = "codex"
    command = "codex"

    def run(self, workdir, on_output=None, program_file="program.md", env=None):
        program_md = workdir / ".research" / program_file
        try:
            prompt = program_md.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            if on_output:
                on_output(f"[codex] failed to read {program_md}: {exc}")
            return 1
        sandbox = self._config.get("sandbox", "workspace-write")
        approval = self._config.get("approval_policy", "on-failure")
        cmd = [self.command, "exec", "-s", sandbox, "-a", approval, "-q"]
        model = self._config.get("model", "")
        if model:
            cmd += ["-m", model]
        cmd.append(prompt)
        return self._run_process(cmd, workdir, on_output, env=env)


class AiderAdapter(AgentAdapter):
    name = "aider"
    command = "aider"

    def run(self, workdir, on_output=None, program_file="program.md", env=None):
        program_md = workdir / ".research" / program_file
        if not program_md.exists():
            if on_output:
                on_output(f"[aider] program file not found: {program_md}")
            return 1
        cmd = [self.command, "--yes-always", "--no-git", "--message-file", str(program_md)]
        model = self._config.get("model", "")
        if model:
            cmd += ["--model", model]
        return self._run_process(cmd, workdir, on_output, env=env)


class GeminiAdapter(AgentAdapter):
    name = "gemini"
    command = "gemini"

    def run(self, workdir, on_output=None, program_file="program.md", env=None):
        program_md = workdir / ".research" / program_file
        try:
            prompt = program_md.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            if on_output:
                on_output(f"[gemini] failed to read {program_md}: {exc}")
            return 1
        cmd = [self.command, "-p", prompt]
        return self._run_process(cmd, workdir, on_output, env=env)


_ADAPTERS: dict[str, type[AgentAdapter]] = {
    "claude-code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "aider": AiderAdapter,
    "gemini": GeminiAdapter,
}


def create_agent(name: str, config: dict | None = None) -> AgentAdapter:
    cls = _ADAPTERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown agent: {name!r}. Available: {list(_ADAPTERS.keys())}")
    return cls(config)


class Agent:
    """High-level agent runner: writes program file, invokes adapter."""

    def __init__(self, adapter: AgentAdapter):
        self.adapter = adapter

    def run(
        self,
        workdir: Path,
        program_content: str,
        program_file: str = "program.md",
        env: dict[str, str] | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> int:
        # Write program.md to .research/
        program_path = workdir / ".research" / program_file
        program_path.parent.mkdir(parents=True, exist_ok=True)
        program_path.write_text(program_content, encoding="utf-8")
        return self.adapter.run(
            workdir=workdir,
            on_output=on_output,
            program_file=program_file,
            env=env,
        )

    def terminate(self) -> None:
        self.adapter.terminate()
```

**Step 4: 运行测试确认通过**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_agent.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/open_researcher_v2/agent.py tests/v2/test_agent.py
git commit -m "feat(v2): add Agent — thin subprocess wrapper with adapter pattern"
```

---

### Task 3: SkillRunner — 技能编排核心

**Files:**
- Create: `src/open_researcher_v2/skill_runner.py`
- Create: `src/open_researcher_v2/skills/protocol.yaml`
- Create: `src/open_researcher_v2/skills/scout.md`
- Create: `src/open_researcher_v2/skills/manager.md`
- Create: `src/open_researcher_v2/skills/critic.md`
- Create: `src/open_researcher_v2/skills/experiment.md`
- Test: `tests/v2/test_skill_runner.py`

**Step 1: 创建 skill 文件**

从现有模板迁移内容。Skill 文件是纯 Markdown，不需要 Jinja2 渲染。

```yaml
# src/open_researcher_v2/skills/protocol.yaml
# Default research protocol — defines the loop steps.
protocol: research-v1
bootstrap:
  - scout
loop:
  - name: manager
    skill: manager.md
    role: planning
  - name: critic
    skill: critic.md
    role: review
  - name: experiment
    skill: experiment.md
    role: execution
  - name: critic
    skill: critic.md
    role: review
```

Skill .md 文件直接复制自现有模板（去掉 Jinja2 标记）:
- `src/open_researcher_v2/skills/scout.md` ← 从 `templates/scout_program.md.j2` 复制，将 `{{ goal }}` / `{{ tag }}` 替换为占位文本 `[GOAL]` / `[TAG]`
- `src/open_researcher_v2/skills/manager.md` ← 从 `templates/manager_program.md.j2` 直接复制（无 Jinja2 变量）
- `src/open_researcher_v2/skills/critic.md` ← 从 `templates/critic_program.md.j2` 直接复制
- `src/open_researcher_v2/skills/experiment.md` ← 从 `templates/experiment_program.md.j2` 直接复制

**Step 2: 写失败测试**

```python
# tests/v2/test_skill_runner.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from open_researcher_v2.skill_runner import SkillRunner
from open_researcher_v2.state import ResearchState
from open_researcher_v2.agent import Agent, AgentAdapter


@pytest.fixture
def research_dir(tmp_path):
    d = tmp_path / ".research"
    d.mkdir()
    return d


@pytest.fixture
def state(research_dir):
    return ResearchState(research_dir)


@pytest.fixture
def mock_agent():
    adapter = MagicMock(spec=AgentAdapter)
    adapter.run.return_value = 0
    return Agent(adapter)


class TestSkillLoading:
    def test_load_default_protocol(self):
        runner = SkillRunner.__new__(SkillRunner)
        protocol = runner._load_protocol()
        assert len(protocol["loop"]) >= 3
        assert protocol["loop"][0]["name"] == "manager"

    def test_compose_program_returns_content(self):
        runner = SkillRunner.__new__(SkillRunner)
        content = runner._load_skill("manager.md")
        assert "Research Manager" in content
        assert len(content) > 100


class TestSkillRunnerSerial:
    def test_run_bootstrap(self, tmp_path, state, mock_agent):
        runner = SkillRunner(
            repo_path=tmp_path,
            state=state,
            agent=mock_agent,
            goal="Test research goal",
            tag="test-001",
        )
        runner.run_bootstrap()
        # Agent should have been called once for scout
        assert mock_agent.adapter.run.call_count == 1
        # Phase should be updated
        act = state.load_activity()
        assert act["phase"] != "idle"

    def test_run_one_round(self, tmp_path, state, mock_agent):
        runner = SkillRunner(
            repo_path=tmp_path,
            state=state,
            agent=mock_agent,
        )
        runner.run_one_round(round_num=1)
        # Should call agent for each loop step (manager, critic, experiment, critic)
        assert mock_agent.adapter.run.call_count == 4

    def test_run_serial_respects_max_rounds(self, tmp_path, state, mock_agent):
        # Set max_rounds = 1 in config
        import yaml
        (tmp_path / ".research" / "config.yaml").write_text(
            yaml.dump({"limits": {"max_rounds": 1}})
        )
        state = ResearchState(tmp_path / ".research")
        runner = SkillRunner(
            repo_path=tmp_path,
            state=state,
            agent=mock_agent,
        )
        runner.run_serial()
        # bootstrap (1 call) + 1 round (4 calls) = 5 total
        assert mock_agent.adapter.run.call_count == 5

    def test_pause_blocks_round(self, tmp_path, state, mock_agent):
        state.set_paused(True)
        runner = SkillRunner(
            repo_path=tmp_path,
            state=state,
            agent=mock_agent,
        )
        # run_one_round should return early when paused
        runner.run_one_round(round_num=1)
        assert mock_agent.adapter.run.call_count == 0
```

**Step 3: 运行测试确认失败**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_skill_runner.py -v`
Expected: FAIL

**Step 4: 实现 skill_runner.py**

```python
# src/open_researcher_v2/skill_runner.py
"""SkillRunner — loads skills, composes program.md, orchestrates agent rounds."""

from __future__ import annotations

import importlib.resources
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from open_researcher_v2.agent import Agent
from open_researcher_v2.state import ResearchState


class SkillRunner:
    """Core orchestrator: skill loading + agent dispatch."""

    def __init__(
        self,
        repo_path: Path,
        state: ResearchState,
        agent: Agent,
        goal: str = "",
        tag: str = "",
        on_output: Callable[[str], None] | None = None,
    ):
        self.repo_path = repo_path
        self.state = state
        self.agent = agent
        self.goal = goal
        self.tag = tag
        self.on_output = on_output or (lambda _: None)

    def _skills_dir(self) -> Path:
        """Return the directory containing built-in skill files."""
        return Path(__file__).parent / "skills"

    def _load_protocol(self) -> dict:
        """Load protocol.yaml from skills directory."""
        p = self._skills_dir() / "protocol.yaml"
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _load_skill(self, filename: str) -> str:
        """Load a skill .md file content."""
        p = self._skills_dir() / filename
        return p.read_text(encoding="utf-8")

    def _compose_program(self, skill_name: str) -> str:
        """Load skill content and apply variable substitution."""
        content = self._load_skill(skill_name)
        content = content.replace("[GOAL]", self.goal or "")
        content = content.replace("[TAG]", self.tag or "")
        return content

    def _run_skill(self, step_name: str, skill_file: str, env: dict | None = None) -> int:
        """Compose program from skill and run agent."""
        self.state.append_log({
            "type": "skill_started",
            "skill": step_name,
            "skill_file": skill_file,
        })
        self.state.update_phase(step_name)
        program_content = self._compose_program(skill_file)
        program_file_name = f"{step_name}_program.md"

        exit_code = self.agent.run(
            workdir=self.repo_path,
            program_content=program_content,
            program_file=program_file_name,
            env=env,
            on_output=self._make_output_callback(step_name),
        )

        self.state.append_log({
            "type": "skill_completed",
            "skill": step_name,
            "exit_code": exit_code,
        })
        return exit_code

    def _make_output_callback(self, phase: str) -> Callable[[str], None]:
        def callback(line: str):
            self.on_output(line)
            self.state.append_log({
                "type": "output",
                "phase": phase,
                "text": line[:500],
            })
        return callback

    # ── Public API ───────────────────────────────────────────────

    def run_bootstrap(self) -> int:
        """Run bootstrap steps (typically just scout)."""
        protocol = self._load_protocol()
        self.state.update_phase("bootstrap")
        for step_name in protocol.get("bootstrap", ["scout"]):
            skill_file = f"{step_name}.md"
            code = self._run_skill(step_name, skill_file)
            if code != 0:
                self.on_output(f"[bootstrap] {step_name} failed with exit code {code}")
                return code
        self.state.update_phase("ready")
        return 0

    def run_one_round(self, round_num: int) -> int:
        """Run one iteration of the research loop."""
        if self.state.is_paused():
            self.on_output("[runner] paused, skipping round")
            return 0

        protocol = self._load_protocol()
        self.state.update_phase("researching", round_num=round_num)

        for step in protocol.get("loop", []):
            if self.state.is_paused():
                self.on_output("[runner] paused mid-round")
                return 0
            if self.state.consume_skip():
                self.on_output("[runner] skip requested")
                return 0

            step_name = step["name"]
            skill_file = step["skill"]
            code = self._run_skill(step_name, skill_file)
            if code != 0:
                self.on_output(f"[runner] {step_name} failed (exit {code})")
                return code

        self.state.append_log({
            "type": "round_completed",
            "round": round_num,
        })
        return 0

    def run_serial(self) -> int:
        """Run full serial research loop: bootstrap + N rounds."""
        config = self.state.load_config()
        max_rounds = config.get("limits", {}).get("max_rounds", 20)

        # Bootstrap
        code = self.run_bootstrap()
        if code != 0:
            return code

        # Loop
        for r in range(1, max_rounds + 1):
            if self.state.is_paused():
                self.on_output("[runner] paused, waiting...")
                while self.state.is_paused():
                    time.sleep(5)

            code = self.run_one_round(r)
            if code != 0:
                return code

            # Check if all frontier items are done
            graph = self.state.load_graph()
            frontier = graph.get("frontier", [])
            active = [f for f in frontier if f.get("status") not in ("archived", "rejected")]
            if frontier and not active:
                self.on_output("[runner] all frontier items resolved")
                break

        self.state.update_phase("completed")
        return 0
```

**Step 5: 运行测试确认通过**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_skill_runner.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/open_researcher_v2/skill_runner.py src/open_researcher_v2/skills/ tests/v2/test_skill_runner.py
git commit -m "feat(v2): add SkillRunner — skill loading and serial research loop"
```

---

### Task 4: WorkerPool — 并行 GPU 实验执行

**Files:**
- Create: `src/open_researcher_v2/parallel.py`
- Test: `tests/v2/test_parallel.py`

**Step 1: 写失败测试**

```python
# tests/v2/test_parallel.py
import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from open_researcher_v2.parallel import WorkerPool, detect_gpus, create_worktree, cleanup_worktree
from open_researcher_v2.state import ResearchState
from open_researcher_v2.agent import Agent, AgentAdapter


@pytest.fixture
def research_dir(tmp_path):
    d = tmp_path / ".research"
    d.mkdir()
    return d


@pytest.fixture
def state(research_dir):
    return ResearchState(research_dir)


class TestGPUDetection:
    @patch("subprocess.run")
    def test_detect_gpus_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="index, memory.total [MiB], memory.free [MiB]\n0, 24576 MiB, 20000 MiB\n1, 24576 MiB, 19000 MiB\n",
        )
        gpus = detect_gpus()
        assert len(gpus) == 2
        assert gpus[0]["index"] == 0
        assert gpus[0]["memory_total_mb"] == 24576
        assert gpus[1]["index"] == 1

    @patch("subprocess.run")
    def test_detect_gpus_no_nvidia(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        gpus = detect_gpus()
        assert gpus == []


class TestFrontierClaiming:
    def test_claim_frontier_item(self, state):
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "f-001", "status": "approved", "priority": 1},
            {"id": "f-002", "status": "approved", "priority": 2},
            {"id": "f-003", "status": "running", "priority": 1},
        ]
        state.save_graph(graph)

        pool = WorkerPool.__new__(WorkerPool)
        pool.state = state
        claimed = pool.claim_frontier("w0")
        assert claimed is not None
        assert claimed["id"] == "f-001"

        # Verify it's now running with claimed_by
        g = state.load_graph()
        f = next(f for f in g["frontier"] if f["id"] == "f-001")
        assert f["status"] == "running"
        assert f["claimed_by"] == "w0"

    def test_claim_skips_already_claimed(self, state):
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "f-001", "status": "running", "claimed_by": "w0"},
            {"id": "f-002", "status": "approved", "priority": 1},
        ]
        state.save_graph(graph)

        pool = WorkerPool.__new__(WorkerPool)
        pool.state = state
        claimed = pool.claim_frontier("w1")
        assert claimed["id"] == "f-002"

    def test_claim_returns_none_when_empty(self, state):
        pool = WorkerPool.__new__(WorkerPool)
        pool.state = state
        assert pool.claim_frontier("w0") is None


class TestWorktree:
    def test_create_and_cleanup_worktree(self, tmp_path):
        """Requires git repo to test properly — skip if not in git."""
        # Initialize a git repo for testing
        import subprocess
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path, capture_output=True)

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        (research_dir / "config.yaml").write_text("test: true")

        wt_path = create_worktree(tmp_path, "w0")
        assert wt_path.exists()
        assert (wt_path / ".research").exists() or (wt_path / ".research").is_symlink()

        cleanup_worktree(tmp_path, "w0")
        assert not wt_path.exists()
```

**Step 2: 运行测试确认失败**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_parallel.py -v`
Expected: FAIL

**Step 3: 实现 parallel.py**

```python
# src/open_researcher_v2/parallel.py
"""WorkerPool — parallel experiment execution across GPUs."""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from open_researcher_v2.agent import Agent
from open_researcher_v2.state import ResearchState

logger = logging.getLogger(__name__)


def detect_gpus() -> list[dict]:
    """Detect available NVIDIA GPUs via nvidia-smi."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.total,memory.free", "--format=csv"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []

    gpus = []
    for line in r.stdout.strip().splitlines()[1:]:
        parts = [p.strip().replace(" MiB", "") for p in line.split(",")]
        if len(parts) >= 3:
            try:
                gpus.append({
                    "index": int(parts[0]),
                    "memory_total_mb": int(parts[1]),
                    "memory_free_mb": int(parts[2]),
                })
            except ValueError:
                continue
    return gpus


def create_worktree(repo_path: Path, worker_id: str) -> Path:
    """Create a git worktree for isolated experiment execution."""
    worktree_dir = repo_path / ".worktrees" / worker_id
    branch_name = f"research-worker-{worker_id}"

    if worktree_dir.exists():
        cleanup_worktree(repo_path, worker_id)

    subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(worktree_dir), "HEAD"],
        cwd=repo_path, capture_output=True, check=True,
    )

    # Symlink .research into worktree
    research_src = repo_path / ".research"
    research_dst = worktree_dir / ".research"
    if research_src.exists() and not research_dst.exists():
        research_dst.symlink_to(research_src.resolve())

    return worktree_dir


def cleanup_worktree(repo_path: Path, worker_id: str) -> None:
    """Remove a git worktree."""
    worktree_dir = repo_path / ".worktrees" / worker_id
    branch_name = f"research-worker-{worker_id}"

    # Remove symlink first
    research_link = worktree_dir / ".research"
    if research_link.is_symlink():
        research_link.unlink()

    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_dir)],
        cwd=repo_path, capture_output=True,
    )
    subprocess.run(
        ["git", "branch", "-D", branch_name],
        cwd=repo_path, capture_output=True,
    )


class WorkerPool:
    """Manage parallel experiment workers across GPUs."""

    def __init__(
        self,
        repo_path: Path,
        state: ResearchState,
        agent_factory: Callable[[], Agent],
        skill_content: str,
        max_workers: int = 0,
        gpu_mem_per_worker_mb: int = 8192,
        on_output: Callable[[str], None] | None = None,
    ):
        self.repo_path = repo_path
        self.state = state
        self.agent_factory = agent_factory
        self.skill_content = skill_content
        self.max_workers = max_workers
        self.gpu_mem_per_worker_mb = gpu_mem_per_worker_mb
        self.on_output = on_output or (lambda _: None)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def claim_frontier(self, worker_id: str) -> dict | None:
        """Atomically claim the highest-priority approved frontier item."""
        graph = self.state.load_graph()
        frontier = graph.get("frontier", [])

        candidates = [
            f for f in frontier
            if f.get("status") == "approved" and not f.get("claimed_by")
        ]
        if not candidates:
            return None

        candidates.sort(key=lambda f: f.get("priority", 999))
        chosen = candidates[0]
        chosen["status"] = "running"
        chosen["claimed_by"] = worker_id
        chosen["claimed_at"] = datetime.now(timezone.utc).isoformat()
        self.state.save_graph(graph)
        return chosen

    def finalize_experiment(self, worker_id: str, frontier_id: str, result: dict) -> None:
        """Mark a frontier item as needing review and record result."""
        graph = self.state.load_graph()
        frontier = graph.get("frontier", [])
        item = next((f for f in frontier if f["id"] == frontier_id), None)
        if item:
            item["status"] = "needs_post_review"
            item["claimed_by"] = None
        self.state.save_graph(graph)

        self.state.append_result({
            "worker": worker_id,
            "frontier_id": frontier_id,
            "status": result.get("status", "discard"),
            "metric": result.get("metric", ""),
            "value": str(result.get("value", "")),
            "description": result.get("description", ""),
        })

        self.state.update_worker(worker_id, status="idle", frontier_id="")
        self.state.append_log({
            "type": "experiment_result",
            "worker": worker_id,
            "frontier_id": frontier_id,
            "result": result,
        })

    def _resolve_gpu_assignments(self) -> list[dict]:
        """Determine how many workers to run and on which GPUs."""
        gpus = detect_gpus()
        if not gpus:
            # CPU-only: single worker
            if self.max_workers > 0:
                return [{"worker_id": "w0", "gpu_index": None}]
            return [{"worker_id": "w0", "gpu_index": None}]

        assignments = []
        worker_idx = 0
        for gpu in gpus:
            slots = gpu["memory_free_mb"] // self.gpu_mem_per_worker_mb
            for _ in range(slots):
                if self.max_workers > 0 and worker_idx >= self.max_workers:
                    break
                assignments.append({
                    "worker_id": f"w{worker_idx}",
                    "gpu_index": gpu["index"],
                })
                worker_idx += 1

        return assignments[:self.max_workers] if self.max_workers > 0 else assignments

    def _worker_loop(self, worker_id: str, gpu_index: int | None) -> None:
        """Single worker loop: claim → worktree → run → finalize → repeat."""
        self.state.update_worker(worker_id, status="starting", gpu=gpu_index)
        self.state.append_log({"type": "worker_started", "worker": worker_id, "gpu": gpu_index})

        agent = self.agent_factory()

        while not self._stop.is_set():
            if self.state.is_paused():
                self.state.update_worker(worker_id, status="paused")
                time.sleep(5)
                continue

            item = self.claim_frontier(worker_id)
            if item is None:
                self.state.update_worker(worker_id, status="idle")
                time.sleep(3)
                # Check again — maybe manager added new items
                if self.claim_frontier(worker_id) is None:
                    break
                continue

            frontier_id = item["id"]
            self.state.update_worker(worker_id, status="running", frontier_id=frontier_id)

            try:
                wt_path = create_worktree(self.repo_path, worker_id)
            except subprocess.CalledProcessError as e:
                self.on_output(f"[{worker_id}] worktree creation failed: {e}")
                self.state.append_log({"type": "worker_crashed", "worker": worker_id, "error": str(e)})
                break

            env = {}
            if gpu_index is not None:
                env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
            env["OPEN_RESEARCHER_FRONTIER_ID"] = frontier_id
            env["OPEN_RESEARCHER_WORKER_ID"] = worker_id

            try:
                exit_code = agent.run(
                    workdir=wt_path,
                    program_content=self.skill_content,
                    program_file="experiment_program.md",
                    env=env,
                    on_output=lambda line, w=worker_id: self.on_output(f"[{w}] {line}"),
                )
            except Exception as e:
                self.on_output(f"[{worker_id}] agent error: {e}")
                exit_code = 1

            cleanup_worktree(self.repo_path, worker_id)

            # Read result from results.tsv (the agent should have recorded it)
            results = self.state.load_results()
            matched = [r for r in results if r.get("frontier_id") == frontier_id]
            if matched:
                self.finalize_experiment(worker_id, frontier_id, matched[-1])
            else:
                self.finalize_experiment(worker_id, frontier_id, {
                    "status": "crash" if exit_code != 0 else "discard",
                    "description": f"exit_code={exit_code}",
                })

        self.state.update_worker(worker_id, status="stopped")
        self.state.append_log({"type": "worker_completed", "worker": worker_id})

    def run(self) -> None:
        """Start all workers in threads."""
        assignments = self._resolve_gpu_assignments()
        if not assignments:
            self.on_output("[pool] no GPU slots available")
            return

        self.on_output(f"[pool] starting {len(assignments)} workers")

        for a in assignments:
            t = threading.Thread(
                target=self._worker_loop,
                args=(a["worker_id"], a["gpu_index"]),
                daemon=True,
                name=f"worker-{a['worker_id']}",
            )
            self._threads.append(t)
            t.start()

    def wait(self, timeout: float | None = None) -> None:
        """Wait for all workers to finish."""
        for t in self._threads:
            t.join(timeout=timeout)

    def stop(self) -> None:
        """Signal all workers to stop."""
        self._stop.set()
```

**Step 4: 运行测试确认通过**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_parallel.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/open_researcher_v2/parallel.py tests/v2/test_parallel.py
git commit -m "feat(v2): add WorkerPool — parallel GPU experiment execution"
```

---

### Task 5: CLI — 命令行入口

**Files:**
- Create: `src/open_researcher_v2/cli.py`
- Test: `tests/v2/test_cli.py`

**Step 1: 写失败测试**

```python
# tests/v2/test_cli.py
import pytest
from pathlib import Path
from typer.testing import CliRunner
from unittest.mock import patch, MagicMock

runner = CliRunner()


class TestCLI:
    def test_import(self):
        from open_researcher_v2.cli import app
        assert app is not None

    def test_status_command(self, tmp_path):
        from open_researcher_v2.cli import app
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        result = runner.invoke(app, ["status", str(tmp_path)])
        assert result.exit_code == 0

    def test_results_command_empty(self, tmp_path):
        from open_researcher_v2.cli import app
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        result = runner.invoke(app, ["results", str(tmp_path)])
        assert result.exit_code == 0

    def test_run_requires_repo(self):
        from open_researcher_v2.cli import app
        result = runner.invoke(app, ["run", "/nonexistent/path"])
        assert result.exit_code != 0
```

**Step 2: 运行测试确认失败**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_cli.py -v`
Expected: FAIL

**Step 3: 实现 cli.py**

```python
# src/open_researcher_v2/cli.py
"""CLI entry point — typer commands for run, status, results."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from open_researcher_v2.agent import Agent, create_agent
from open_researcher_v2.state import ResearchState

app = typer.Typer(name="open-researcher", help="Let AI agents run experiments while you sleep.")
console = Console()


@app.command()
def run(
    repo: Path = typer.Argument(..., help="Path to the target repository"),
    goal: str = typer.Option("", help="Research goal description"),
    tag: str = typer.Option("", help="Session tag"),
    workers: int = typer.Option(0, help="Max parallel workers (0 = serial mode)"),
    headless: bool = typer.Option(False, help="Run without TUI"),
    agent_name: str = typer.Option("claude-code", help="Agent to use"),
) -> None:
    """Start a research session on a repository."""
    repo = repo.resolve()
    if not repo.is_dir():
        console.print(f"[red]Error: {repo} is not a directory[/red]")
        raise typer.Exit(1)

    research_dir = repo / ".research"
    research_dir.mkdir(exist_ok=True)

    state = ResearchState(research_dir)
    config = state.load_config()

    agent_config = config.get("agent", {}).get("config", {})
    adapter = create_agent(agent_name, agent_config)
    if not adapter.check_installed():
        console.print(f"[red]Agent '{agent_name}' not found on PATH[/red]")
        raise typer.Exit(1)

    agent = Agent(adapter)

    from open_researcher_v2.skill_runner import SkillRunner
    runner = SkillRunner(
        repo_path=repo,
        state=state,
        agent=agent,
        goal=goal,
        tag=tag or _auto_tag(),
        on_output=lambda line: console.print(f"  {line}") if headless else None,
    )

    if headless:
        if workers > 0:
            _run_parallel(repo, state, agent, runner, workers, config)
        else:
            exit_code = runner.run_serial()
            raise typer.Exit(exit_code)
    else:
        # Launch TUI
        try:
            from open_researcher_v2.tui.app import ResearchApp
            tui_app = ResearchApp(repo_path=repo, state=state, runner=runner)
            tui_app.run()
        except ImportError:
            console.print("[yellow]TUI not available, running headless[/yellow]")
            exit_code = runner.run_serial()
            raise typer.Exit(exit_code)


@app.command()
def status(
    repo: Path = typer.Argument(..., help="Path to the target repository"),
) -> None:
    """Show current research session status."""
    research_dir = repo.resolve() / ".research"
    if not research_dir.exists():
        console.print("[yellow]No .research directory found[/yellow]")
        raise typer.Exit(0)

    state = ResearchState(research_dir)
    s = state.summary()

    table = Table(title="Research Status")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Phase", s["phase"])
    table.add_row("Round", str(s["round"]))
    table.add_row("Hypotheses", str(s["hypotheses"]))
    table.add_row("Experiments (total)", str(s["experiments_total"]))
    table.add_row("Experiments (running)", str(s["experiments_running"]))
    table.add_row("Experiments (done)", str(s["experiments_done"]))
    table.add_row("Results", str(s["results_count"]))
    table.add_row("Best Value", s["best_value"])
    table.add_row("Paused", str(s["paused"]))
    console.print(table)

    if s["workers"]:
        wt = Table(title="Workers")
        wt.add_column("ID")
        wt.add_column("Status")
        wt.add_column("GPU")
        wt.add_column("Frontier")
        for w in s["workers"]:
            wt.add_row(w.get("id", "?"), w.get("status", "?"), str(w.get("gpu", "—")), w.get("frontier_id", "—"))
        console.print(wt)


@app.command()
def results(
    repo: Path = typer.Argument(..., help="Path to the target repository"),
) -> None:
    """Show experiment results."""
    research_dir = repo.resolve() / ".research"
    if not research_dir.exists():
        console.print("[yellow]No .research directory found[/yellow]")
        raise typer.Exit(0)

    state = ResearchState(research_dir)
    rows = state.load_results()
    if not rows:
        console.print("[dim]No results yet[/dim]")
        raise typer.Exit(0)

    table = Table(title="Results")
    for col in ["timestamp", "worker", "frontier_id", "status", "metric", "value", "description"]:
        table.add_column(col)
    for row in rows:
        table.add_row(*[row.get(c, "") for c in ["timestamp", "worker", "frontier_id", "status", "metric", "value", "description"]])
    console.print(table)


def _auto_tag() -> str:
    from datetime import datetime
    return datetime.now().strftime("r-%Y%m%d-%H%M%S")


def _run_parallel(repo, state, agent, runner, workers, config):
    from open_researcher_v2.parallel import WorkerPool

    # Bootstrap first
    runner.run_bootstrap()

    # Then run manager + critic
    runner.run_one_round(round_num=1)

    # Then parallel experiments
    skill_content = runner._compose_program("experiment.md")
    pool = WorkerPool(
        repo_path=repo,
        state=state,
        agent_factory=lambda: Agent(create_agent(
            config.get("agent", {}).get("name", "claude-code"),
            config.get("agent", {}).get("config", {}),
        )),
        skill_content=skill_content,
        max_workers=workers,
        gpu_mem_per_worker_mb=config.get("workers", {}).get("gpu_mem_per_worker_mb", 8192),
        on_output=lambda line: console.print(f"  {line}"),
    )
    pool.run()
    pool.wait()
```

**Step 4: 运行测试确认通过**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_cli.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/open_researcher_v2/cli.py tests/v2/test_cli.py
git commit -m "feat(v2): add CLI — typer commands for run/status/results"
```

---

### Task 6: TUI Widgets — 可视化组件

**Files:**
- Create: `src/open_researcher_v2/tui/__init__.py`
- Create: `src/open_researcher_v2/tui/widgets.py`
- Create: `src/open_researcher_v2/tui/styles.css`
- Test: `tests/v2/test_tui_widgets.py`

**Step 1: 写失败测试**

```python
# tests/v2/test_tui_widgets.py
import pytest
from open_researcher_v2.tui.widgets import (
    StatsBar,
    PhaseStripBar,
    FrontierPanel,
    WorkerPanel,
    LogPanel,
)


class TestWidgetInstantiation:
    """Verify all widgets can be instantiated without errors."""

    def test_stats_bar(self):
        w = StatsBar()
        assert w is not None

    def test_phase_strip_bar(self):
        w = PhaseStripBar()
        assert w is not None

    def test_frontier_panel(self):
        w = FrontierPanel()
        assert w is not None

    def test_worker_panel(self):
        w = WorkerPanel()
        assert w is not None

    def test_log_panel(self):
        w = LogPanel()
        assert w is not None


class TestWidgetUpdate:
    def test_stats_bar_update(self):
        w = StatsBar()
        w.update_data({
            "phase": "researching",
            "round": 3,
            "hypotheses": 5,
            "experiments_total": 10,
            "experiments_done": 4,
            "experiments_running": 2,
            "results_count": 4,
            "best_value": "0.95",
            "paused": False,
        })

    def test_phase_strip_update(self):
        w = PhaseStripBar()
        w.update_phase("manager")

    def test_frontier_panel_update(self):
        w = FrontierPanel()
        w.update_data([
            {"id": "f-001", "status": "running", "description": "test exp", "priority": 1},
            {"id": "f-002", "status": "approved", "description": "next exp", "priority": 2},
        ])

    def test_worker_panel_update(self):
        w = WorkerPanel()
        w.update_data([
            {"id": "w0", "status": "running", "gpu": 0, "frontier_id": "f-001"},
            {"id": "w1", "status": "idle", "gpu": 1, "frontier_id": ""},
        ])

    def test_log_panel_update(self):
        w = LogPanel()
        w.update_data([
            {"ts": "2026-03-18T10:00:00Z", "type": "output", "text": "hello"},
            {"ts": "2026-03-18T10:00:01Z", "type": "skill_started", "skill": "manager"},
        ])
```

**Step 2: 运行测试确认失败**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_tui_widgets.py -v`
Expected: FAIL

**Step 3: 创建 CSS 样式**

```css
/* src/open_researcher_v2/tui/styles.css */
Screen {
    layout: grid;
    grid-size: 2 3;
    grid-rows: 3 1fr 1fr;
    grid-columns: 1fr 1fr;
}

StatsBar {
    column-span: 2;
    height: 3;
    background: $surface;
    padding: 0 1;
}

PhaseStripBar {
    column-span: 2;
    height: 1;
    background: $primary-background;
}

FrontierPanel {
    height: 100%;
}

WorkerPanel {
    height: 100%;
}

LogPanel {
    column-span: 2;
    height: 100%;
}

.panel-title {
    text-style: bold;
    color: $text;
}

.status-running {
    color: $success;
}

.status-idle {
    color: $text-muted;
}

.status-paused {
    color: $warning;
}
```

**Step 4: 实现 widgets.py**

```python
# src/open_researcher_v2/tui/__init__.py
# (empty)

# src/open_researcher_v2/tui/widgets.py
"""TUI widgets — Textual components for research monitoring."""

from __future__ import annotations

from textual.widget import Widget
from textual.widgets import Static, DataTable, RichLog
from textual.containers import Vertical, Horizontal
from rich.text import Text


class StatsBar(Static):
    """Top bar showing key metrics."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._data: dict = {}

    def update_data(self, summary: dict) -> None:
        self._data = summary
        self._refresh_display()

    def _refresh_display(self) -> None:
        d = self._data
        if not d:
            self.update("Loading...")
            return
        phase = d.get("phase", "idle")
        paused = " [PAUSED]" if d.get("paused") else ""
        text = (
            f"Phase: {phase}{paused}  |  "
            f"Round: {d.get('round', 0)}  |  "
            f"Hyps: {d.get('hypotheses', 0)}  |  "
            f"Exps: {d.get('experiments_done', 0)}/{d.get('experiments_total', 0)} "
            f"({d.get('experiments_running', 0)} running)  |  "
            f"Best: {d.get('best_value', '—')}"
        )
        self.update(text)


PHASE_ORDER = ["scout", "manager", "critic", "experiment"]


class PhaseStripBar(Static):
    """Horizontal phase indicator strip."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._current = ""

    def update_phase(self, phase: str) -> None:
        self._current = phase
        parts = []
        for p in PHASE_ORDER:
            if p == phase:
                parts.append(f"[bold green]▶ {p.upper()}[/]")
            else:
                parts.append(f"[dim]{p}[/]")
        self.update("  →  ".join(parts))


class FrontierPanel(Vertical):
    """Display frontier items with status."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._table = DataTable()
        self._table.add_columns("ID", "Priority", "Status", "Description")
        self._initialized = False

    def compose(self):
        yield Static("[b]Frontier[/b]", classes="panel-title")
        yield self._table

    def update_data(self, frontier: list[dict]) -> None:
        self._table.clear()
        for item in sorted(frontier, key=lambda f: f.get("priority", 999)):
            self._table.add_row(
                item.get("id", ""),
                str(item.get("priority", "")),
                item.get("status", ""),
                (item.get("description", "") or "")[:50],
            )


class WorkerPanel(Vertical):
    """Display worker status grid."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._table = DataTable()
        self._table.add_columns("Worker", "Status", "GPU", "Frontier")

    def compose(self):
        yield Static("[b]Workers[/b]", classes="panel-title")
        yield self._table

    def update_data(self, workers: list[dict]) -> None:
        self._table.clear()
        for w in workers:
            self._table.add_row(
                w.get("id", "?"),
                w.get("status", "?"),
                str(w.get("gpu", "—")),
                w.get("frontier_id", "—") or "—",
            )


class LogPanel(Vertical):
    """Scrolling log display."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._log = RichLog(highlight=True, markup=True, max_lines=200)

    def compose(self):
        yield Static("[b]Log[/b]", classes="panel-title")
        yield self._log

    def update_data(self, events: list[dict]) -> None:
        self._log.clear()
        for ev in events:
            ts = ev.get("ts", "")[:19]
            ev_type = ev.get("type", "?")
            if ev_type == "output":
                text = ev.get("text", "")
                self._log.write(f"[dim]{ts}[/] {text}")
            elif ev_type == "skill_started":
                skill = ev.get("skill", "?")
                self._log.write(f"[dim]{ts}[/] [bold green]▶ {skill}[/]")
            elif ev_type == "skill_completed":
                skill = ev.get("skill", "?")
                code = ev.get("exit_code", "?")
                color = "green" if code == 0 else "red"
                self._log.write(f"[dim]{ts}[/] [{color}]✓ {skill} (exit {code})[/]")
            elif ev_type in ("worker_started", "worker_completed", "worker_crashed"):
                worker = ev.get("worker", "?")
                self._log.write(f"[dim]{ts}[/] [cyan]{ev_type}: {worker}[/]")
            elif ev_type == "experiment_result":
                worker = ev.get("worker", "?")
                result = ev.get("result", {})
                self._log.write(f"[dim]{ts}[/] [yellow]result: {worker} → {result.get('status', '?')}[/]")
            else:
                self._log.write(f"[dim]{ts}[/] {ev_type}")


class MetricChart(Static):
    """Simple metric trend chart using plotext."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def update_data(self, results: list[dict]) -> None:
        kept = [r for r in results if r.get("status") == "keep"]
        if len(kept) < 2:
            self.update("[dim]Need 2+ results for chart[/dim]")
            return
        try:
            import plotext as plt
            values = [float(r["value"]) for r in kept]
            plt.clf()
            plt.plot(list(range(len(values))), values, marker="braille")
            plt.title("Metric Trend")
            plt.theme("dark")
            self.update(plt.build())
        except (ImportError, ValueError):
            self.update("[dim]Chart unavailable[/dim]")
```

**Step 5: 运行测试确认通过**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_tui_widgets.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/open_researcher_v2/tui/__init__.py src/open_researcher_v2/tui/widgets.py src/open_researcher_v2/tui/styles.css tests/v2/test_tui_widgets.py
git commit -m "feat(v2): add TUI widgets — StatsBar, FrontierPanel, WorkerPanel, LogPanel"
```

---

### Task 7: TUI App — 主应用

**Files:**
- Create: `src/open_researcher_v2/tui/app.py`
- Test: `tests/v2/test_tui_app.py`

**Step 1: 写失败测试**

```python
# tests/v2/test_tui_app.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock


class TestTUIAppImport:
    def test_import(self):
        from open_researcher_v2.tui.app import ResearchApp
        assert ResearchApp is not None

    def test_instantiation(self, tmp_path):
        from open_researcher_v2.tui.app import ResearchApp
        from open_researcher_v2.state import ResearchState

        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        runner = MagicMock()

        app = ResearchApp(repo_path=tmp_path, state=state, runner=runner)
        assert app is not None
```

**Step 2: 运行测试确认失败**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_tui_app.py -v`
Expected: FAIL

**Step 3: 实现 tui/app.py**

```python
# src/open_researcher_v2/tui/app.py
"""ResearchApp — Textual TUI for monitoring research sessions."""

from __future__ import annotations

import threading
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.widgets import Header, Footer, TabbedContent, TabPane

from open_researcher_v2.state import ResearchState
from open_researcher_v2.tui.widgets import (
    StatsBar,
    PhaseStripBar,
    FrontierPanel,
    WorkerPanel,
    LogPanel,
    MetricChart,
)


class ResearchApp(App):
    """Interactive TUI for monitoring and controlling research sessions."""

    CSS_PATH = "styles.css"
    TITLE = "Open Researcher"

    BINDINGS = [
        Binding("p", "pause", "Pause", show=True),
        Binding("r", "resume", "Resume", show=True),
        Binding("s", "skip", "Skip", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(
        self,
        repo_path: Path,
        state: ResearchState,
        runner=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.repo_path = repo_path
        self.state = state
        self.runner = runner
        self._runner_thread: threading.Thread | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatsBar(id="stats")
        yield PhaseStripBar(id="phase-strip")
        with TabbedContent():
            with TabPane("Execution", id="tab-exec"):
                with Horizontal():
                    yield FrontierPanel(id="frontier")
                    yield WorkerPanel(id="workers")
            with TabPane("Metrics", id="tab-metrics"):
                yield MetricChart(id="chart")
            with TabPane("Logs", id="tab-logs"):
                yield LogPanel(id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(1.0, self._poll_state)
        if self.runner:
            self._runner_thread = threading.Thread(
                target=self._run_research, daemon=True, name="research-runner"
            )
            self._runner_thread.start()

    def _run_research(self) -> None:
        if self.runner:
            self.runner.on_output = lambda line: self.call_from_thread(
                self._on_runner_output, line
            )
            self.runner.run_serial()

    def _on_runner_output(self, line: str) -> None:
        pass  # Output goes to log.jsonl, polled by _poll_state

    def _poll_state(self) -> None:
        try:
            summary = self.state.summary()
            self.query_one("#stats", StatsBar).update_data(summary)
            self.query_one("#phase-strip", PhaseStripBar).update_phase(summary["phase"])
            self.query_one("#workers", WorkerPanel).update_data(summary.get("workers", []))

            graph = self.state.load_graph()
            self.query_one("#frontier", FrontierPanel).update_data(graph.get("frontier", []))

            results = self.state.load_results()
            self.query_one("#chart", MetricChart).update_data(results)

            logs = self.state.tail_log(100)
            self.query_one("#log", LogPanel).update_data(logs)
        except Exception:
            pass  # Polling should never crash the TUI

    def action_pause(self) -> None:
        self.state.set_paused(True)
        self.notify("Research paused")

    def action_resume(self) -> None:
        self.state.set_paused(False)
        self.notify("Research resumed")

    def action_skip(self) -> None:
        act = self.state.load_activity()
        act.setdefault("control", {})["skip_current"] = True
        self.state.save_activity(act)
        self.notify("Skip requested")
```

**Step 4: 运行测试确认通过**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_tui_app.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/open_researcher_v2/tui/app.py tests/v2/test_tui_app.py
git commit -m "feat(v2): add ResearchApp TUI — polling-based monitoring with controls"
```

---

### Task 8: 集成测试 + pyproject.toml 更新

**Files:**
- Create: `tests/v2/test_integration.py`
- Modify: `pyproject.toml` — 添加 v2 入口

**Step 1: 写集成测试**

```python
# tests/v2/test_integration.py
"""End-to-end integration test: full serial flow with mock agent."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from open_researcher_v2.state import ResearchState
from open_researcher_v2.agent import Agent, AgentAdapter
from open_researcher_v2.skill_runner import SkillRunner


@pytest.fixture
def repo(tmp_path):
    """Set up a fake repo with .research directory."""
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=tmp_path, capture_output=True)
    research = tmp_path / ".research"
    research.mkdir()
    return tmp_path


@pytest.fixture
def mock_adapter():
    adapter = MagicMock(spec=AgentAdapter)
    adapter.run.return_value = 0
    return adapter


class TestFullSerialFlow:
    def test_bootstrap_then_one_round(self, repo, mock_adapter):
        state = ResearchState(repo / ".research")
        agent = Agent(mock_adapter)
        runner = SkillRunner(
            repo_path=repo, state=state, agent=agent,
            goal="Test goal", tag="test-001",
        )
        # Bootstrap
        code = runner.run_bootstrap()
        assert code == 0
        # Should have called scout
        assert mock_adapter.run.call_count == 1
        assert state.load_activity()["phase"] == "ready"

        # One round
        code = runner.run_one_round(round_num=1)
        assert code == 0
        # 4 steps: manager, critic, experiment, critic
        assert mock_adapter.run.call_count == 5  # 1 bootstrap + 4 loop

        # Verify log
        logs = state.tail_log(100)
        skill_events = [e for e in logs if e["type"] in ("skill_started", "skill_completed")]
        assert len(skill_events) == 10  # 5 starts + 5 completes

    def test_full_serial_with_limit(self, repo, mock_adapter):
        import yaml
        (repo / ".research" / "config.yaml").write_text(
            yaml.dump({"limits": {"max_rounds": 2}})
        )
        state = ResearchState(repo / ".research")
        agent = Agent(mock_adapter)
        runner = SkillRunner(
            repo_path=repo, state=state, agent=agent,
        )
        code = runner.run_serial()
        assert code == 0
        # 1 bootstrap + 2 rounds * 4 steps = 9
        assert mock_adapter.run.call_count == 9
        assert state.load_activity()["phase"] == "completed"

    def test_pause_stops_progress(self, repo, mock_adapter):
        state = ResearchState(repo / ".research")
        state.set_paused(True)
        agent = Agent(mock_adapter)
        runner = SkillRunner(repo_path=repo, state=state, agent=agent)
        runner.run_one_round(round_num=1)
        assert mock_adapter.run.call_count == 0


class TestParallelClaiming:
    def test_two_workers_claim_different_items(self, repo):
        state = ResearchState(repo / ".research")
        from open_researcher_v2.parallel import WorkerPool

        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "f-001", "status": "approved", "priority": 1, "description": "exp 1"},
            {"id": "f-002", "status": "approved", "priority": 2, "description": "exp 2"},
        ]
        state.save_graph(graph)

        pool = WorkerPool.__new__(WorkerPool)
        pool.state = state

        c1 = pool.claim_frontier("w0")
        c2 = pool.claim_frontier("w1")

        assert c1["id"] == "f-001"
        assert c2["id"] == "f-002"

        # Both should be running in graph
        g = state.load_graph()
        statuses = {f["id"]: f["status"] for f in g["frontier"]}
        assert statuses["f-001"] == "running"
        assert statuses["f-002"] == "running"
```

**Step 2: 运行集成测试**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/test_integration.py -v`
Expected: ALL PASS

**Step 3: 更新 pyproject.toml 添加 v2 入口**

在 `[project.scripts]` 中添加:

```toml
open-researcher-v2 = "open_researcher_v2.cli:app"
```

确保 `src/open_researcher_v2` 包含在 hatch 构建路径中。

**Step 4: 运行全部 v2 测试**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -m pytest tests/v2/ -v --tb=short`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add tests/v2/test_integration.py pyproject.toml
git commit -m "feat(v2): add integration tests and v2 CLI entry point"
```

---

### Task 9: Skill 文件迁移

**Files:**
- Create: `src/open_researcher_v2/skills/scout.md`
- Create: `src/open_researcher_v2/skills/manager.md`
- Create: `src/open_researcher_v2/skills/critic.md`
- Create: `src/open_researcher_v2/skills/experiment.md`

**Step 1: 复制并清理模板内容**

从现有 Jinja2 模板复制内容，移除 Jinja2 语法：

- `scout.md`: 从 `templates/scout_program.md.j2` 复制。将 `{{ goal }}` 替换为 `[GOAL]`，`{{ tag }}` 替换为 `[TAG]`。
- `manager.md`: 从 `templates/manager_program.md.j2` 直接复制（无 Jinja2 变量）。
- `critic.md`: 从 `templates/critic_program.md.j2` 直接复制。
- `experiment.md`: 从 `templates/experiment_program.md.j2` 直接复制。

**Step 2: 验证 skill 文件可被 SkillRunner 加载**

Run: `cd /Users/shatianming/Downloads/open-researcher && python -c "from open_researcher_v2.skill_runner import SkillRunner; r = SkillRunner.__new__(SkillRunner); print(len(r._load_skill('manager.md')), 'chars')"`
Expected: 打印 manager.md 的字符数

**Step 3: Commit**

```bash
git add src/open_researcher_v2/skills/
git commit -m "feat(v2): migrate skill files from Jinja2 templates to plain Markdown"
```

---

## 文件清单总览

| 文件 | 行数估计 | 职责 |
|------|---------|------|
| `src/open_researcher_v2/__init__.py` | 0 | 包标记 |
| `src/open_researcher_v2/state.py` | ~200 | 6 个状态文件的统一读写 |
| `src/open_researcher_v2/agent.py` | ~150 | Agent 子进程封装 + 5 个适配器 |
| `src/open_researcher_v2/skill_runner.py` | ~180 | 技能加载 + 串行研究循环 |
| `src/open_researcher_v2/parallel.py` | ~250 | GPU 检测 + worktree + WorkerPool |
| `src/open_researcher_v2/cli.py` | ~130 | typer 命令入口 |
| `src/open_researcher_v2/tui/widgets.py` | ~200 | 5 个 Textual 组件 |
| `src/open_researcher_v2/tui/app.py` | ~120 | TUI 主应用 |
| `src/open_researcher_v2/tui/styles.css` | ~50 | 样式 |
| `src/open_researcher_v2/skills/protocol.yaml` | ~15 | 协议定义 |
| `src/open_researcher_v2/skills/*.md` | ~800 | 4 个 skill 文件 |
| **合计 Python** | **~1,230** | （不含 skill .md 文件） |

## 状态文件接口

| 文件 | 写入者 | 读取者 |
|------|--------|--------|
| `config.yaml` | 用户/bootstrap | SkillRunner, TUI |
| `graph.json` | Manager/Critic agent | SkillRunner (claiming), TUI |
| `results.tsv` | Experiment agent (record.py) | TUI, SkillRunner |
| `activity.json` | SkillRunner, WorkerPool | TUI |
| `log.jsonl` | SkillRunner, WorkerPool | TUI |
| `*.md` | Scout/Manager agent | TUI (docs tab) |
