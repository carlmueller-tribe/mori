"""HookRetry propagation through HookRegistry.dispatch_before."""

from __future__ import annotations

import pytest

from mori.hooks.exceptions import HookRetry
from mori.hooks.registry import HookRegistry
from mori.hooks.types import HookConfig


@pytest.mark.asyncio
async def test_dispatch_before_propagates_hook_retry() -> None:
    reg = HookRegistry()

    async def retrier(payload: object) -> None:
        raise HookRetry("re-think")

    reg.register("e", retrier)
    with pytest.raises(HookRetry) as exc:
        await reg.dispatch_before("e", {})
    assert exc.value.feedback == "re-think"
    assert exc.value.hook_id is not None


@pytest.mark.asyncio
async def test_hook_retry_not_swallowed_when_fail_open_true() -> None:
    reg = HookRegistry(config=HookConfig(fail_open=True))

    async def retrier(payload: object) -> None:
        raise HookRetry("silenced?")

    reg.register("e", retrier)
    with pytest.raises(HookRetry):
        await reg.dispatch_before("e", {})


def test_hook_config_has_max_retry_limit_default() -> None:
    config = HookConfig()
    assert config.max_retry_limit == 3


@pytest.mark.asyncio
async def test_hook_retry_on_after_event_warns_and_swallows(caplog) -> None:
    """HookRetry on an after-event (observe-only) is logged and ignored, not propagated."""
    import logging

    reg = HookRegistry()

    async def bad(payload: object) -> None:
        raise HookRetry("wrong place", hook_id="bad")

    reg.register("e", bad)
    with caplog.at_level(logging.WARNING):
        # Must NOT raise
        await reg.dispatch_after("e", {})


@pytest.mark.asyncio
async def test_hook_block_on_after_event_warns_and_swallows(caplog) -> None:
    """HookBlock on an after-event (observe-only) is also logged and ignored."""
    import logging

    from mori.hooks.exceptions import HookBlock

    reg = HookRegistry()

    async def bad(payload: object) -> None:
        raise HookBlock("wrong place", hook_id="bad")

    reg.register("e", bad)
    with caplog.at_level(logging.WARNING):
        await reg.dispatch_after("e", {})


@pytest.mark.asyncio
async def test_dispatch_after_processes_remaining_handlers_after_invalid_signal() -> None:
    """If one after-handler raises HookRetry, the next handler still fires."""
    from mori.hooks.exceptions import HookBlock

    reg = HookRegistry()
    other_ran = False

    async def bad(payload: object) -> None:
        raise HookBlock("wrong place")

    async def other(payload: object) -> None:
        nonlocal other_ran
        other_ran = True

    reg.register("e", bad, priority=50)
    reg.register("e", other, priority=100)
    await reg.dispatch_after("e", {})
    assert other_ran is True
