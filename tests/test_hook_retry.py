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
