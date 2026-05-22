"""Hook system invariants — properties that must hold across all events."""

from __future__ import annotations

from typing import Any

import pytest

from mori.hooks.events import HookEvents
from mori.hooks.exceptions import HookBlock
from mori.hooks.registry import HookRegistry

_BEFORE_EVENTS = [
    HookEvents.TURN_START,
    HookEvents.MODEL_REQUEST_BEFORE,
    HookEvents.TOOL_INVOKE_BEFORE,
    HookEvents.TURN_END,
]


@pytest.mark.asyncio
@pytest.mark.parametrize("event", _BEFORE_EVENTS)
async def test_noop_hook_observationally_identical(event: str) -> None:
    """A no-op hook (returns None) is observationally identical to no hook registered."""
    payload = {"key": "value"}

    reg_with = HookRegistry()

    async def noop(p: Any) -> None:
        return None

    reg_with.register(event, noop)
    result_with = await reg_with.dispatch_before(event, payload)

    reg_without = HookRegistry()
    result_without = await reg_without.dispatch_before(event, payload)

    assert result_with == result_without == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("event", _BEFORE_EVENTS)
async def test_hook_block_short_circuits_chain(event: str) -> None:
    """HookBlock always short-circuits — later hooks never observe the payload,
    on every block-capable event."""
    later_saw: list[Any] = []
    reg = HookRegistry()

    async def blocker(p: Any) -> None:
        raise HookBlock("stop", hook_id="b")

    async def later(p: Any) -> None:
        later_saw.append(p)

    reg.register(event, blocker, priority=50)
    reg.register(event, later, priority=100)
    with pytest.raises(HookBlock):
        await reg.dispatch_before(event, {"x": 1})
    assert later_saw == []
