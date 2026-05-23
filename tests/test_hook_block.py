"""HookBlock propagation through HookRegistry.dispatch_before."""

from __future__ import annotations

import pytest

from mori.hooks.exceptions import HookBlock
from mori.hooks.registry import HookRegistry
from mori.hooks.types import HookConfig


@pytest.mark.asyncio
async def test_dispatch_before_propagates_hook_block() -> None:
    reg = HookRegistry()

    async def blocker(payload: object) -> None:
        raise HookBlock("not allowed")

    reg.register("e", blocker)
    with pytest.raises(HookBlock) as exc:
        await reg.dispatch_before("e", {"x": 1})
    assert exc.value.reason == "not allowed"
    assert exc.value.hook_id is not None  # registry stamped it


@pytest.mark.asyncio
async def test_hook_block_short_circuits_chain() -> None:
    reg = HookRegistry()
    later_ran = False

    async def blocker(payload: object) -> None:
        raise HookBlock("stop")

    async def later(payload: object) -> object:
        nonlocal later_ran
        later_ran = True
        return payload

    reg.register("e", blocker, priority=50)
    reg.register("e", later, priority=100)
    with pytest.raises(HookBlock):
        await reg.dispatch_before("e", {})
    assert later_ran is False


@pytest.mark.asyncio
async def test_hook_block_not_swallowed_when_fail_open_true() -> None:
    reg = HookRegistry(config=HookConfig(fail_open=True))

    async def blocker(payload: object) -> None:
        raise HookBlock("never silenced")

    reg.register("e", blocker)
    with pytest.raises(HookBlock):
        await reg.dispatch_before("e", {})
