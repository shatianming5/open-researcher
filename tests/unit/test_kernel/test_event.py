"""Tests for the core Event dataclass."""
import time


def test_event_creation():
    from open_researcher.kernel.event import Event

    e = Event(type="experiment.started", payload={"id": 1})
    assert e.type == "experiment.started"
    assert e.payload == {"id": 1}
    assert isinstance(e.ts, float)
    assert e.source == ""
    assert e.correlation_id == ""


def test_event_is_frozen():
    from open_researcher.kernel.event import Event

    e = Event(type="test", payload={})
    try:
        e.type = "other"
        assert False, "Should raise"
    except AttributeError:
        pass


def test_event_with_source_and_correlation():
    from open_researcher.kernel.event import Event

    e = Event(
        type="scout.completed",
        payload={"ideas": 3},
        source="orchestrator",
        correlation_id="abc-123",
    )
    assert e.source == "orchestrator"
    assert e.correlation_id == "abc-123"


def test_event_matches_exact():
    from open_researcher.kernel.event import Event, event_matches

    e = Event(type="experiment.started", payload={})
    assert event_matches(e, "experiment.started") is True
    assert event_matches(e, "experiment.completed") is False


def test_event_matches_wildcard():
    from open_researcher.kernel.event import Event, event_matches

    e = Event(type="experiment.started", payload={})
    assert event_matches(e, "experiment.*") is True
    assert event_matches(e, "scout.*") is False
    assert event_matches(e, "*") is True
