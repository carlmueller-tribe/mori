"""Payload types for turn.start and turn.end hook events."""

from __future__ import annotations

from mori.hooks.events import TurnEndReason
from mori.runtime.state import MoriState
from mori.types import MoriModel, ThreadId


class TurnStartPayload(MoriModel):
    """Payload for turn.start hook event."""

    input: str
    thread_id: ThreadId
    is_resume: bool


class TurnEndPayload(MoriModel):
    """Payload for turn.end hook event."""

    state: MoriState
    reason: TurnEndReason
