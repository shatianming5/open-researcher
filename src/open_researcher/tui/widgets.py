"""Custom Textual widgets for Open Researcher TUI."""

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class StatsBar(Static):
    """Top status bar showing experiment summary."""

    stats = reactive("")

    def render(self) -> str:
        return self.stats or "Open Researcher — starting..."

    def update_stats(self, state: dict) -> None:
        total = state.get("total", 0)
        keep = state.get("keep", 0)
        discard = state.get("discard", 0)
        crash = state.get("crash", 0)
        best = state.get("best_value")
        pm = state.get("primary_metric", "")

        parts = ["Open Researcher"]
        if total > 0:
            parts.append(f"{total} exp")
            parts.append(f"{keep} kept {discard} disc {crash} crash")
            if best is not None:
                parts.append(f"best {pm}={best:.4f}")
        else:
            parts.append("waiting for experiments...")

        self.stats = " | ".join(parts)


class IdeaPoolPanel(Widget):
    """Scrollable panel showing all ideas in the pool."""

    ideas_text = reactive("")

    def render(self) -> str:
        return self.ideas_text or "No ideas yet — Idea Agent is starting..."

    def update_ideas(self, ideas: list[dict], summary: dict, workers: list[dict] | None = None) -> None:
        pending = summary.get("pending", 0)
        total = summary.get("total", 0)
        lines = [f"Idea Pool ({pending} pending / {total} total)"]
        lines.append("-" * 60)

        # Build worker lookup: idea_id -> gpu list
        worker_gpu_map: dict[str, list[int]] = {}
        if workers:
            for w in workers:
                idea = w.get("idea", "")
                gpus = w.get("gpus", [])
                worker_gpu_map[idea] = gpus

        status_order = {"running": 0, "pending": 1, "done": 2, "skipped": 3}
        sorted_ideas = sorted(ideas, key=lambda i: (status_order.get(i["status"], 9), i.get("priority", 99)))

        for idea in sorted_ideas:
            sid = idea["status"]
            desc = idea["description"][:45]
            iid = idea["id"].replace("idea-", "#")

            if sid == "running":
                gpus = worker_gpu_map.get(idea["id"], [])
                gpu_str = f" GPU:{','.join(str(g) for g in gpus)}" if gpus else ""
                hint = idea.get("gpu_hint", "auto")
                ddp = " DDP" if isinstance(hint, int) and hint > 1 else ""
                lines.append(f">> {iid} {desc:<45} [RUNNING{gpu_str}{ddp}]")
            elif sid == "pending":
                pri = idea.get("priority", "?")
                lines.append(f"   {iid} {desc:<45} [pending]  pri:{pri}")
            elif sid == "done":
                result = idea.get("result", {})
                verdict = result.get("verdict", "?") if result else "?"
                val = result.get("metric_value", 0) if result else 0
                marker = "--" if verdict == "kept" else "xx"
                lines.append(f"{marker} {iid} {desc:<45} [{verdict} {val:.4f}]")
            elif sid == "skipped":
                lines.append(f"~~ {iid} {desc:<45} [skipped]")

        self.ideas_text = "\n".join(lines)


class AgentPanel(Widget):
    """Panel showing a single agent's status and recent output."""

    agent_text = reactive("")

    def render(self) -> str:
        return self.agent_text or "[idle]"

    def update_from_activity(self, activity: dict | None, agent_name: str, log_lines: list[str] | None = None) -> None:
        lines = [f"{agent_name}"]
        lines.append("-" * 30)

        if activity:
            status = activity.get("status", "idle")
            lines.append(f"[{status}]")

            detail = activity.get("detail", "")
            if detail:
                lines.append(detail)

            idea = activity.get("idea", "")
            if idea:
                lines.append(f"Idea: {idea}")

            gpu = activity.get("gpu")
            if gpu:
                lines.append(f"GPU: {gpu.get('host', '?')}:{gpu.get('device', '?')}")

            branch = activity.get("branch", "")
            if branch:
                lines.append(f"Branch: {branch}")

            started = activity.get("started_at", "")
            if started:
                lines.append(f"Started: {started[:19]}")
        else:
            lines.append("[idle] waiting to start...")

        if log_lines:
            lines.append("")
            for line in log_lines[-5:]:
                lines.append(f"> {line[:70]}")

        self.agent_text = "\n".join(lines)


class AgentStatusWidget(Widget):
    """Prominent display of agent's current phase and action."""

    status_text = reactive("")

    def render(self) -> str:
        return self.status_text or "[dim]waiting to start...[/dim]"

    def update_status(self, activity: dict | None) -> None:
        if not activity:
            self.status_text = "[dim]waiting to start...[/dim]"
            return

        status = activity.get("status", "idle")
        detail = activity.get("detail", "")
        idea = activity.get("idea", "")
        updated = activity.get("updated_at", "")[:19]

        # Status icon mapping (text symbols, no emoji)
        status_icons = {
            "analyzing": ">>",
            "generating": "**",
            "searching": "..",
            "idle": "--",
            "coding": "<>",
            "evaluating": "##",
            "scheduling": "::",
            "detecting_gpus": "||",
            "establishing_baseline": "==",
            "monitoring": "()",
            "paused": "--",
            "cpu_serial_mode": "[]",
        }
        icon = status_icons.get(status, " *")

        lines = [f"  {icon} [{status.upper()}]"]
        if detail:
            lines.append(f"  {detail}")
        if idea:
            lines.append(f"  Idea: {idea}")
        if updated:
            lines.append(f"  Updated: {updated}")

        self.status_text = "\n".join(lines)


class WorkerStatusPanel(Widget):
    """Panel showing experiment workers and their GPU assignments."""

    workers_text = reactive("")

    def render(self) -> str:
        return self.workers_text or "Experiment Master — idle"

    def update_workers(self, workers: list[dict], gpu_total: int = 0) -> None:
        if not workers:
            active_gpus = 0
        else:
            active_gpus = sum(len(w.get("gpus", [])) for w in workers)
        lines = [f"Experiment Master | Workers: {len(workers)} | GPU: {active_gpus}/{gpu_total} active"]
        lines.append("-" * 60)
        if not workers:
            lines.append("No workers running — waiting for ideas...")
        for w in workers:
            wid = w.get("id", "?")
            idea = w.get("idea", "?")
            gpus = w.get("gpus", [])
            gpu_str = ",".join(str(g) for g in gpus)
            status = w.get("status", "?")
            lines.append(f"  {wid}: {idea} [GPU:{gpu_str}] [{status}]")
        self.workers_text = "\n".join(lines)


class HotkeyBar(Static):
    """Bottom bar showing available keyboard shortcuts."""

    def render(self) -> str:
        return "[p]ause [r]esume [s]kip [a]dd idea [e]dit [g]pu [l]og [q]uit"
