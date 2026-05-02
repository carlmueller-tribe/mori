"""Tests for PermissionCheckEvent and MoriState paused fields."""

from datetime import UTC, datetime

from mori.observability.events import PermissionCheckEvent
from mori.runtime.state import MoriState
from mori.types import RunId, ThreadId, ToolCall

# ── Helpers ──────────────────────────────────────────────────


def make_event(**kwargs):
    defaults = dict(
        event_id="ev1",
        event_type="permission.check",
        timestamp=datetime.now(UTC),
        run_id=RunId("r1"),
        identity_id="user:alice",
        resource_id="file:/secrets",
        permission="r",
        decision="allow",
    )
    defaults.update(kwargs)
    return PermissionCheckEvent(**defaults)


def make_state(**kwargs):
    defaults = dict(
        run_id=RunId("r1"),
        thread_id=ThreadId("t1"),
        task="test task",
        started_at=datetime.now(UTC),
        last_progress_at=datetime.now(UTC),
    )
    defaults.update(kwargs)
    return MoriState(**defaults)


# ── PermissionCheckEvent tests ────────────────────────────────


def test_permission_check_event_fields():
    event = make_event(
        identity_id="user:alice",
        resource_id="file:/secrets",
        permission="r",
        decision="allow",
    )
    assert event.event_type == "permission.check"
    assert event.identity_id == "user:alice"
    assert event.decision == "allow"


def test_permission_check_event_defaults():
    event = make_event()
    assert event.rule_id is None
    assert event.explanation == ""


# ── MoriState paused fields tests ─────────────────────────────


def test_moristate_paused_reason_default():
    state = make_state()
    assert state.paused_reason is None


def test_moristate_paused_tool_call_default():
    state = make_state()
    assert state.paused_tool_call is None


def test_moristate_paused_fields_settable():
    state = make_state(
        paused_reason="tool blocked",
        paused_tool_call=ToolCall(id="tc1", name="delete_file", arguments={}),
    )
    assert state.paused_reason == "tool blocked"
    assert state.paused_tool_call == ToolCall(id="tc1", name="delete_file", arguments={})
