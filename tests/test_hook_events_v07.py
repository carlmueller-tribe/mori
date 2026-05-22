"""Tests for HookEvents constants, TurnEndReason enum, and turn payloads."""

from __future__ import annotations

from datetime import UTC, datetime

from mori.hooks.events import HookEvents, TurnEndReason
from mori.hooks.payloads import TurnEndPayload, TurnStartPayload
from mori.runtime.state import MoriState
from mori.types import RunId, ThreadId


class TestHookEvents:
    def test_new_events_defined(self) -> None:
        assert HookEvents.TURN_START == "turn.start"
        assert HookEvents.TURN_END == "turn.end"

    def test_existing_events_preserved(self) -> None:
        assert HookEvents.MODEL_REQUEST_BEFORE == "model.request.before"
        assert HookEvents.MODEL_RESPONSE_AFTER == "model.response.after"
        assert HookEvents.PERMISSION_CHECK_AFTER == "permission.check.after"
        assert HookEvents.TOOL_INVOKE_BEFORE == "tool.invoke.before"
        assert HookEvents.TOOL_INVOKE_AFTER == "tool.invoke.after"
        assert HookEvents.RUN_START == "run.start"
        assert HookEvents.RUN_END == "run.end"


class TestTurnEndReason:
    def test_all_variants(self) -> None:
        assert TurnEndReason.COMPLETED == "completed"
        assert TurnEndReason.PAUSED_AWAIT_USER == "paused_await_user"
        assert TurnEndReason.PAUSED_ESCALATE == "paused_escalate"
        assert TurnEndReason.EXHAUSTED == "exhausted"
        assert TurnEndReason.ERRORED == "errored"
        assert TurnEndReason.BLOCKED == "blocked"


class TestTurnPayloads:
    def test_turn_start_payload(self) -> None:
        p = TurnStartPayload(input="hi", thread_id=ThreadId("t1"), is_resume=False)
        assert p.input == "hi"
        assert p.thread_id == "t1"
        assert p.is_resume is False

    def test_turn_end_payload(self) -> None:
        state = MoriState(
            run_id=RunId("r1"),
            thread_id=ThreadId("t1"),
            task="x",
            started_at=datetime.now(UTC),
            last_progress_at=datetime.now(UTC),
        )
        p = TurnEndPayload(state=state, reason=TurnEndReason.COMPLETED)
        assert p.state.run_id == "r1"
        assert p.reason == TurnEndReason.COMPLETED
