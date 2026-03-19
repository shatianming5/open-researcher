"""Tests for TUI review modal screens."""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from open_researcher_v2.state import ResearchState


class TestReviewScreenBase:
    def test_import(self):
        from open_researcher_v2.tui.modals.base import ReviewScreen
        assert ReviewScreen is not None

    def test_construction(self, tmp_path):
        from open_researcher_v2.tui.modals.base import ReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        review_req = {"type": "test", "requested_at": "2026-03-19T14:00:00Z"}
        screen = ReviewScreen(state=state, review_request=review_req)
        assert screen.state is state
        assert screen.review_request == review_req

    def test_action_skip_clears_review(self, tmp_path):
        from open_researcher_v2.tui.modals.base import ReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review({"type": "test", "requested_at": "2026-03-19T14:00:00Z"})
        screen = ReviewScreen(state=state, review_request={"type": "test"})
        screen.dismiss = MagicMock()
        screen.action_skip()
        assert state.get_awaiting_review() is None
        screen.dismiss.assert_called_once_with(None)

    def test_action_skip_logs_event(self, tmp_path):
        from open_researcher_v2.tui.modals.base import ReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review({"type": "test_type", "requested_at": "2026-03-19T14:00:00Z"})
        screen = ReviewScreen(state=state, review_request={"type": "test_type"})
        screen.dismiss = MagicMock()
        screen.action_skip()
        logs = state.tail_log(10)
        skip_events = [e for e in logs if e.get("event") == "review_skipped"]
        assert len(skip_events) == 1
        assert skip_events[0]["review_type"] == "test_type"

    def test_action_confirm_clears_review(self, tmp_path):
        from open_researcher_v2.tui.modals.base import ReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review({"type": "test", "requested_at": "2026-03-19T14:00:00Z"})
        screen = ReviewScreen(state=state, review_request={"type": "test"})
        screen.dismiss = MagicMock()
        screen.action_confirm()
        assert state.get_awaiting_review() is None
        screen.dismiss.assert_called_once_with(True)

    def test_action_confirm_calls_apply_decisions(self, tmp_path):
        from open_researcher_v2.tui.modals.base import ReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review({"type": "test", "requested_at": "now"})
        screen = ReviewScreen(state=state, review_request={"type": "test"})
        screen.dismiss = MagicMock()
        screen._apply_decisions = MagicMock()
        screen.action_confirm()
        screen._apply_decisions.assert_called_once()

    def test_notify_safe_without_app(self, tmp_path):
        from open_researcher_v2.tui.modals.base import ReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = ReviewScreen(state=state, review_request={"type": "test"})
        # Should not raise even without app
        screen._notify("test message")


class TestDirectionConfirmScreen:
    def test_import(self):
        from open_researcher_v2.tui.modals.direction import DirectionConfirmScreen
        assert DirectionConfirmScreen is not None

    def test_is_review_screen_subclass(self):
        from open_researcher_v2.tui.modals.base import ReviewScreen
        from open_researcher_v2.tui.modals.direction import DirectionConfirmScreen
        assert issubclass(DirectionConfirmScreen, ReviewScreen)

    def test_confirm_writes_constraints(self, tmp_path):
        from open_researcher_v2.tui.modals.direction import DirectionConfirmScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.set_awaiting_review({"type": "direction_confirm", "requested_at": "2026-03-19T14:00:00Z"})
        screen = DirectionConfirmScreen(state=state, review_request={"type": "direction_confirm"})
        screen._user_constraints = "Focus on parser only"
        screen.dismiss = MagicMock()
        screen._apply_decisions()
        content = (research_dir / "user_constraints.md").read_text()
        assert "Focus on parser only" in content

    def test_empty_constraints_not_written(self, tmp_path):
        from open_researcher_v2.tui.modals.direction import DirectionConfirmScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = DirectionConfirmScreen(state=state, review_request={"type": "direction_confirm"})
        screen._user_constraints = "   "
        screen._apply_decisions()
        assert not (research_dir / "user_constraints.md").exists()

    def test_constraints_appended_to_existing(self, tmp_path):
        from open_researcher_v2.tui.modals.direction import DirectionConfirmScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        (research_dir / "user_constraints.md").write_text("- Existing\n")
        state = ResearchState(research_dir)
        screen = DirectionConfirmScreen(state=state, review_request={"type": "direction_confirm"})
        screen._user_constraints = "New constraint"
        screen._apply_decisions()
        content = (research_dir / "user_constraints.md").read_text()
        assert "Existing" in content
        assert "New constraint" in content

    def test_apply_logs_goal_updated(self, tmp_path):
        from open_researcher_v2.tui.modals.direction import DirectionConfirmScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = DirectionConfirmScreen(state=state, review_request={"type": "direction_confirm"})
        screen._user_constraints = "some constraint"
        screen._apply_decisions()
        logs = state.tail_log(10)
        assert any(e.get("event") == "goal_updated" for e in logs)


class TestFrontierReviewScreen:
    def test_import(self):
        from open_researcher_v2.tui.modals.frontier import FrontierReviewScreen
        assert FrontierReviewScreen is not None

    def test_is_hypothesis_review_subclass(self):
        from open_researcher_v2.tui.modals.hypothesis import HypothesisReviewScreen
        from open_researcher_v2.tui.modals.frontier import FrontierReviewScreen
        assert issubclass(FrontierReviewScreen, HypothesisReviewScreen)

    def test_inherits_apply_decisions(self, tmp_path):
        """FrontierReviewScreen should use HypothesisReviewScreen._apply_decisions."""
        from open_researcher_v2.tui.modals.frontier import FrontierReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "frontier-001", "status": "approved"},
        ]
        state.save_graph(graph)
        screen = FrontierReviewScreen(state=state, review_request={"type": "frontier_review"})
        screen._decisions = {"frontier-001": "rejected"}
        screen._apply_decisions()
        updated = state.load_graph()
        assert updated["frontier"][0]["status"] == "rejected"


class TestHypothesisReviewScreen:
    def test_apply_rejects_item(self, tmp_path):
        from open_researcher_v2.tui.modals.hypothesis import HypothesisReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "frontier-001", "priority": 3, "status": "approved", "description": "Test A"},
            {"id": "frontier-002", "priority": 2, "status": "approved", "description": "Test B"},
        ]
        state.save_graph(graph)
        screen = HypothesisReviewScreen(state=state, review_request={"type": "hypothesis_review"})
        screen._decisions = {"frontier-002": "rejected"}
        screen.dismiss = MagicMock()
        screen._apply_decisions()
        graph = state.load_graph()
        statuses = {f["id"]: f["status"] for f in graph["frontier"]}
        assert statuses["frontier-001"] == "approved"
        assert statuses["frontier-002"] == "rejected"

    def test_apply_multiple_decisions(self, tmp_path):
        from open_researcher_v2.tui.modals.hypothesis import HypothesisReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        graph = state.load_graph()
        graph["frontier"] = [
            {"id": "f-1", "status": "approved"},
            {"id": "f-2", "status": "approved"},
            {"id": "f-3", "status": "approved"},
        ]
        state.save_graph(graph)
        screen = HypothesisReviewScreen(state=state, review_request={"type": "hypothesis_review"})
        screen._decisions = {"f-1": "rejected", "f-3": "rejected"}
        screen._apply_decisions()
        updated = state.load_graph()
        statuses = {f["id"]: f["status"] for f in updated["frontier"]}
        assert statuses == {"f-1": "rejected", "f-2": "approved", "f-3": "rejected"}

    def test_empty_decisions_no_change(self, tmp_path):
        from open_researcher_v2.tui.modals.hypothesis import HypothesisReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        graph = state.load_graph()
        graph["frontier"] = [{"id": "f-1", "status": "approved"}]
        state.save_graph(graph)
        screen = HypothesisReviewScreen(state=state, review_request={"type": "hypothesis_review"})
        screen._decisions = {}
        screen._apply_decisions()
        updated = state.load_graph()
        assert updated["frontier"][0]["status"] == "approved"

    def test_status_colors_defined(self):
        from open_researcher_v2.tui.modals.hypothesis import _STATUS_COLORS
        assert "approved" in _STATUS_COLORS
        assert "rejected" in _STATUS_COLORS
        assert "running" in _STATUS_COLORS
        assert "needs_post_review" in _STATUS_COLORS


class TestResultReviewScreen:
    def test_override_writes_claim_update(self, tmp_path):
        from open_researcher_v2.tui.modals.result import ResultReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        state.append_result({
            "timestamp": "2026-03-19T14:00:00Z",
            "worker": "w0",
            "frontier_id": "frontier-001",
            "status": "discard",
            "metric": "ops_per_sec",
            "value": "2000000",
            "description": "Test result",
        })
        screen = ResultReviewScreen(state=state, review_request={"type": "result_review"})
        screen._overrides = {"frontier-001": "keep"}
        screen.dismiss = MagicMock()
        screen._apply_decisions()
        graph = state.load_graph()
        claims = graph.get("claim_updates", [])
        assert len(claims) == 1
        assert claims[0]["frontier_id"] == "frontier-001"
        assert claims[0]["new_status"] == "keep"
        assert claims[0]["reviewer"] == "human"

    def test_no_overrides_no_change(self, tmp_path):
        from open_researcher_v2.tui.modals.result import ResultReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = ResultReviewScreen(state=state, review_request={"type": "result_review"})
        screen._overrides = {}
        screen._apply_decisions()
        graph = state.load_graph()
        assert len(graph.get("claim_updates", [])) == 0

    def test_override_logs_human_override(self, tmp_path):
        from open_researcher_v2.tui.modals.result import ResultReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = ResultReviewScreen(state=state, review_request={"type": "result_review"})
        screen._overrides = {"f-1": "discard"}
        screen._apply_decisions()
        logs = state.tail_log(10)
        override_events = [e for e in logs if e.get("event") == "human_override"]
        assert len(override_events) == 1
        assert override_events[0]["frontier_id"] == "f-1"
        assert override_events[0]["new_status"] == "discard"

    def test_multiple_overrides(self, tmp_path):
        from open_researcher_v2.tui.modals.result import ResultReviewScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = ResultReviewScreen(state=state, review_request={"type": "result_review"})
        screen._overrides = {"f-1": "keep", "f-2": "discard"}
        screen._apply_decisions()
        graph = state.load_graph()
        claims = graph.get("claim_updates", [])
        assert len(claims) == 2
        fids = {c["frontier_id"] for c in claims}
        assert fids == {"f-1", "f-2"}


class TestGoalEditScreen:
    def test_save_writes_constraints(self, tmp_path):
        from open_researcher_v2.tui.modals.goal_edit import GoalEditScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = GoalEditScreen(state=state)
        screen._user_text = "Focus on parser only"
        screen.dismiss = MagicMock()
        screen.action_save()
        content = (research_dir / "user_constraints.md").read_text()
        assert "Focus on parser only" in content

    def test_save_empty_text_dismisses(self, tmp_path):
        from open_researcher_v2.tui.modals.goal_edit import GoalEditScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = GoalEditScreen(state=state)
        screen._user_text = "  "
        screen.dismiss = MagicMock()
        screen.action_save()
        screen.dismiss.assert_called_once_with(True)
        assert not (research_dir / "user_constraints.md").exists()

    def test_save_logs_goal_updated(self, tmp_path):
        from open_researcher_v2.tui.modals.goal_edit import GoalEditScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = GoalEditScreen(state=state)
        screen._user_text = "new goal"
        screen.dismiss = MagicMock()
        screen.action_save()
        logs = state.tail_log(10)
        assert any(e.get("event") == "goal_updated" for e in logs)

    def test_cancel_dismisses_with_none(self, tmp_path):
        from open_researcher_v2.tui.modals.goal_edit import GoalEditScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = GoalEditScreen(state=state)
        screen.dismiss = MagicMock()
        screen.action_cancel()
        screen.dismiss.assert_called_once_with(None)

    def test_is_not_review_screen_subclass(self):
        """GoalEditScreen extends Screen, not ReviewScreen."""
        from open_researcher_v2.tui.modals.goal_edit import GoalEditScreen
        from open_researcher_v2.tui.modals.base import ReviewScreen
        assert not issubclass(GoalEditScreen, ReviewScreen)


class TestInjectIdeaScreen:
    def test_inject_adds_to_graph(self, tmp_path):
        from open_researcher_v2.tui.modals.inject import InjectIdeaScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = InjectIdeaScreen(state=state)
        screen._description = "Try __slots__"
        screen._priority = 3
        screen.dismiss = MagicMock()
        screen.action_inject()
        graph = state.load_graph()
        assert len(graph["frontier"]) == 1
        assert graph["frontier"][0]["description"] == "Try __slots__"
        assert graph["frontier"][0]["selection_reason_code"] == "human_injected"
        assert graph["counters"]["frontier"] == 1

    def test_inject_logs_event(self, tmp_path):
        from open_researcher_v2.tui.modals.inject import InjectIdeaScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = InjectIdeaScreen(state=state)
        screen._description = "Test idea"
        screen._priority = 2
        screen.dismiss = MagicMock()
        screen.action_inject()
        logs = state.tail_log(10)
        assert any(e.get("event") == "human_injected" for e in logs)

    def test_inject_dismisses_on_success(self, tmp_path):
        from open_researcher_v2.tui.modals.inject import InjectIdeaScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = InjectIdeaScreen(state=state)
        screen._description = "Test"
        screen._priority = 3
        screen.dismiss = MagicMock()
        screen.action_inject()
        screen.dismiss.assert_called_once_with(True)

    def test_inject_empty_description_rejected(self, tmp_path):
        from open_researcher_v2.tui.modals.inject import InjectIdeaScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = InjectIdeaScreen(state=state)
        screen._description = "   "
        screen._priority = 3
        screen.dismiss = MagicMock()
        screen.action_inject()
        # Should not dismiss or add to graph
        screen.dismiss.assert_not_called()
        graph = state.load_graph()
        assert len(graph.get("frontier", [])) == 0

    def test_inject_invalid_priority_rejected(self, tmp_path):
        from open_researcher_v2.tui.modals.inject import InjectIdeaScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = InjectIdeaScreen(state=state)
        screen._description = "Test"
        screen._priority = 0  # Out of range
        screen.dismiss = MagicMock()
        screen.action_inject()
        screen.dismiss.assert_not_called()

    def test_inject_increments_counter(self, tmp_path):
        from open_researcher_v2.tui.modals.inject import InjectIdeaScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        # First inject
        s1 = InjectIdeaScreen(state=state)
        s1._description = "First"
        s1._priority = 3
        s1.dismiss = MagicMock()
        s1.action_inject()
        # Second inject
        s2 = InjectIdeaScreen(state=state)
        s2._description = "Second"
        s2._priority = 2
        s2.dismiss = MagicMock()
        s2.action_inject()
        graph = state.load_graph()
        assert len(graph["frontier"]) == 2
        assert graph["frontier"][0]["id"] == "frontier-001"
        assert graph["frontier"][1]["id"] == "frontier-002"

    def test_cancel_dismisses(self, tmp_path):
        from open_researcher_v2.tui.modals.inject import InjectIdeaScreen
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        state = ResearchState(research_dir)
        screen = InjectIdeaScreen(state=state)
        screen.dismiss = MagicMock()
        screen.action_cancel()
        screen.dismiss.assert_called_once_with(None)


class TestModalsPackageImport:
    def test_all_exports(self):
        from open_researcher_v2.tui.modals import (
            ReviewScreen,
            DirectionConfirmScreen,
            FrontierReviewScreen,
            GoalEditScreen,
            HypothesisReviewScreen,
            InjectIdeaScreen,
            ResultReviewScreen,
        )
        assert all(cls is not None for cls in [
            ReviewScreen, DirectionConfirmScreen, FrontierReviewScreen,
            GoalEditScreen, HypothesisReviewScreen, InjectIdeaScreen,
            ResultReviewScreen,
        ])


class TestFullCheckpointFlow:
    """Integration test: config -> checkpoint -> state change -> clear."""

    def test_checkpoint_mode_end_to_end(self, tmp_path):
        import threading
        import yaml
        from open_researcher_v2.state import ResearchState
        from open_researcher_v2.skill_runner import SkillRunner
        from open_researcher_v2.agent import Agent, AgentAdapter

        # Setup
        research_dir = tmp_path / ".research"
        research_dir.mkdir()
        (research_dir / "config.yaml").write_text(yaml.dump({
            "interaction": {
                "mode": "checkpoint",
                "checkpoints": {
                    "after_scout": True,
                    "after_manager": False,
                    "after_critic_preflight": False,
                    "after_round": False,
                },
            },
        }))

        state = ResearchState(research_dir)

        class StubAdapter(AgentAdapter):
            name = "stub"
            command = "stub"
            def run(self, workdir, *, on_output=None, program_file="program.md", env=None):
                # Create the program file that Agent.run() expects to write
                return 0

        agent = Agent(StubAdapter())
        runner = SkillRunner(tmp_path, state, agent, goal="test", tag="t1")

        # Auto-approve after delay
        def auto_approve():
            import time
            for _ in range(10):
                time.sleep(0.3)
                if state.get_awaiting_review():
                    state.clear_awaiting_review()
                    break

        t = threading.Thread(target=auto_approve, daemon=True)
        t.start()

        rc = runner.run_bootstrap()
        t.join(timeout=5.0)
        assert rc == 0

        # Verify review was requested and completed
        logs = state.tail_log(50)
        events = [e["event"] for e in logs]
        assert "review_requested" in events
        assert "review_completed" in events
