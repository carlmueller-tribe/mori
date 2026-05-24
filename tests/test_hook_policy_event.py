"""HookPolicyEvent — observability event for HookBlock/HookRetry."""

from __future__ import annotations

from datetime import datetime

import pytest

from mori.observability.events import HookPolicyEvent
from mori.types import RunId


def test_hook_policy_event_block() -> None:
    event = HookPolicyEvent(
        event_id="evt_1",
        timestamp=datetime.now(),
        run_id=RunId("run_1"),
        signal="HookBlock",
        event_name="tool.invoke.before",
        hook_id="hook_abc123",
        handler_name="block_prod_writes",
        reason="production migrations must go through CI",
    )
    assert event.event_type == "hook.policy"
    assert event.signal == "HookBlock"
    assert event.event_name == "tool.invoke.before"
    assert event.reason == "production migrations must go through CI"


def test_hook_policy_event_retry() -> None:
    event = HookPolicyEvent(
        event_id="evt_2",
        timestamp=datetime.now(),
        run_id=RunId("run_2"),
        signal="HookRetry",
        event_name="turn.end",
        hook_id="hook_xyz789",
        handler_name="no_speculate",
        reason="response contains speculation; revise",
    )
    assert event.signal == "HookRetry"


def test_hook_policy_event_signal_is_constrained() -> None:
    """signal field must be 'HookBlock' or 'HookRetry' — pydantic Literal."""
    with pytest.raises(Exception):  # ValidationError
        HookPolicyEvent(
            event_id="evt_3",
            timestamp=datetime.now(),
            run_id=RunId("run_3"),
            signal="NotASignal",  # invalid
            event_name="turn.end",
            hook_id="hook_1",
            handler_name="h",
            reason="r",
        )
