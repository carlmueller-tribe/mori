"""Typed constants for known hook events. String registration stays valid."""

from __future__ import annotations

from enum import StrEnum


class HookEvents:
    """Constants for hook event names.

    Strings are intentional — they match the existing string-keyed
    registration API and stay valid for back-compat.
    """

    TURN_START = "turn.start"
    TURN_END = "turn.end"
    MODEL_REQUEST_BEFORE = "model.request.before"
    MODEL_RESPONSE_AFTER = "model.response.after"
    PERMISSION_CHECK_AFTER = "permission.check.after"
    TOOL_INVOKE_BEFORE = "tool.invoke.before"
    TOOL_INVOKE_AFTER = "tool.invoke.after"
    RUN_START = "run.start"
    RUN_END = "run.end"


class TurnEndReason(StrEnum):
    """Enum for the reasons a turn can end."""

    COMPLETED = "completed"
    PAUSED_AWAIT_USER = "paused_await_user"
    PAUSED_ESCALATE = "paused_escalate"
    EXHAUSTED = "exhausted"
    ERRORED = "errored"
    BLOCKED = "blocked"
