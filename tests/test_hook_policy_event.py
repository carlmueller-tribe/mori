"""HookPolicyEvent — observability event for HookBlock/HookRetry."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from mori.hooks.exceptions import HookBlock, HookRetry
from mori.hooks.registry import HookRegistry
from mori.observability.engine import ObservabilityEngine
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


@pytest.mark.asyncio
async def test_dispatch_before_emits_hook_policy_event_on_block() -> None:
    """When dispatch_before catches a HookBlock, HookPolicyEvent must be emitted."""
    obs = AsyncMock(spec=ObservabilityEngine)
    registry = HookRegistry(observability=obs)

    @registry.hook("tool.invoke.before", priority=10, name="blocker")
    async def blocker(payload):
        raise HookBlock("denied for test")

    with pytest.raises(HookBlock):
        await registry.dispatch_before("tool.invoke.before", payload={"tool": "foo"})

    # Find the HookPolicyEvent in emitted events
    emit_calls = [c.args[0] for c in obs.emit.call_args_list]
    policy_events = [e for e in emit_calls if isinstance(e, HookPolicyEvent)]
    assert len(policy_events) == 1
    assert policy_events[0].signal == "HookBlock"
    assert policy_events[0].event_name == "tool.invoke.before"
    assert policy_events[0].handler_name == "blocker"
    assert policy_events[0].reason == "denied for test"


@pytest.mark.asyncio
async def test_dispatch_before_emits_hook_policy_event_on_retry() -> None:
    """When dispatch_before catches a HookRetry, HookPolicyEvent must be emitted."""
    obs = AsyncMock(spec=ObservabilityEngine)
    registry = HookRegistry(observability=obs)

    @registry.hook("model.request.before", priority=10, name="retrier")
    async def retrier(payload):
        raise HookRetry("retry feedback for test")

    with pytest.raises(HookRetry):
        await registry.dispatch_before("model.request.before", payload={"model": "gpt-4"})

    # Find the HookPolicyEvent in emitted events
    emit_calls = [c.args[0] for c in obs.emit.call_args_list]
    policy_events = [e for e in emit_calls if isinstance(e, HookPolicyEvent)]
    assert len(policy_events) == 1
    assert policy_events[0].signal == "HookRetry"
    assert policy_events[0].event_name == "model.request.before"
    assert policy_events[0].handler_name == "retrier"
    assert policy_events[0].reason == "retry feedback for test"


@pytest.mark.asyncio
async def test_set_current_run_id_propagates_to_policy_event() -> None:
    """set_current_run_id() value must appear in emitted HookPolicyEvent.run_id."""
    obs = AsyncMock(spec=ObservabilityEngine)
    registry = HookRegistry(observability=obs)

    @registry.hook("tool.invoke.before", priority=10, name="blocker_with_run_id")
    async def blocker(payload):
        raise HookBlock("blocked with run id")

    registry.set_current_run_id("run_test_abc123")

    with pytest.raises(HookBlock):
        await registry.dispatch_before("tool.invoke.before", payload={"tool": "foo"})

    emit_calls = [c.args[0] for c in obs.emit.call_args_list]
    policy_events = [e for e in emit_calls if isinstance(e, HookPolicyEvent)]
    assert len(policy_events) == 1
    assert policy_events[0].run_id == "run_test_abc123"


@pytest.mark.asyncio
async def test_set_current_run_id_none_falls_back_to_unknown() -> None:
    """When current_run_id is None and no run_id on signal, 'unknown' is used."""
    obs = AsyncMock(spec=ObservabilityEngine)
    registry = HookRegistry(observability=obs)

    @registry.hook("tool.invoke.before", priority=10, name="blocker_no_run_id")
    async def blocker(payload):
        raise HookBlock("blocked without run id")

    # current_run_id is None by default
    assert registry._current_run_id is None

    with pytest.raises(HookBlock):
        await registry.dispatch_before("tool.invoke.before", payload={"tool": "foo"})

    emit_calls = [c.args[0] for c in obs.emit.call_args_list]
    policy_events = [e for e in emit_calls if isinstance(e, HookPolicyEvent)]
    assert len(policy_events) == 1
    assert policy_events[0].run_id == "unknown"
