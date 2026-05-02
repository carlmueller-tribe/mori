import asyncio
import pytest
from mori.hooks.registry import HookRegistry
from mori.hooks.types import HookConfig


@pytest.mark.asyncio
async def test_before_hooks_fire_in_priority_order():
    registry = HookRegistry()
    order = []
    registry.register("test.event", lambda p: order.append(10) or p, priority=10)
    registry.register("test.event", lambda p: order.append(20) or p, priority=20)
    registry.register("test.event", lambda p: order.append(5) or p, priority=5)
    await registry.dispatch_before("test.event", "payload")
    assert order == [5, 10, 20]


@pytest.mark.asyncio
async def test_before_hook_modifies_payload():
    registry = HookRegistry()
    registry.register("test.event", lambda p: p + "_modified", priority=10)
    result = await registry.dispatch_before("test.event", "original")
    assert result == "original_modified"


@pytest.mark.asyncio
async def test_before_hook_none_passes_through():
    registry = HookRegistry()
    registry.register("test.event", lambda p: None, priority=10)
    result = await registry.dispatch_before("test.event", "original")
    assert result == "original"


@pytest.mark.asyncio
async def test_after_hook_ignores_return_value():
    registry = HookRegistry()
    received = []
    registry.register("test.after", lambda p: received.append(p) or "ignored")
    await registry.dispatch_after("test.after", "payload")
    assert received == ["payload"]


@pytest.mark.asyncio
async def test_async_handler():
    registry = HookRegistry()

    async def async_hook(p):
        await asyncio.sleep(0)
        return p + "_async"

    registry.register("test.event", async_hook, priority=10)
    result = await registry.dispatch_before("test.event", "data")
    assert result == "data_async"


@pytest.mark.asyncio
async def test_fail_open_swallows_hook_error():
    registry = HookRegistry(config=HookConfig(fail_open=True))

    def bad_hook(p):
        raise RuntimeError("hook failed")

    registry.register("test.event", bad_hook, priority=10)
    result = await registry.dispatch_before("test.event", "safe")
    assert result == "safe"


@pytest.mark.asyncio
async def test_fail_closed_propagates_hook_error():
    registry = HookRegistry(config=HookConfig(fail_open=False))

    def bad_hook(p):
        raise RuntimeError("hook failed")

    registry.register("test.event", bad_hook, priority=10)
    with pytest.raises(RuntimeError):
        await registry.dispatch_before("test.event", "safe")


def test_unregister_removes_hook():
    registry = HookRegistry()
    hid = registry.register("test.event", lambda p: p, priority=10)
    registry.unregister(hid)
    assert registry.list_hooks("test.event") == []


def test_decorator_registers_hook():
    registry = HookRegistry()

    @registry.hook("test.event", priority=5)
    def my_hook(p):
        return p

    hooks = registry.list_hooks("test.event")
    assert len(hooks) == 1
    assert hooks[0].handler_name == "my_hook"


def test_max_hooks_per_event():
    registry = HookRegistry(config=HookConfig(max_hooks_per_event=2))
    registry.register("test.event", lambda p: p, priority=10)
    registry.register("test.event", lambda p: p, priority=20)
    with pytest.raises(ValueError, match="Max hooks"):
        registry.register("test.event", lambda p: p, priority=30)


def test_clear_removes_all_hooks():
    registry = HookRegistry()
    registry.register("event.a", lambda p: p)
    registry.register("event.b", lambda p: p)
    count = registry.clear()
    assert count == 2
    assert registry.list_hooks() == []


def test_clear_event_name_removes_only_that_event():
    registry = HookRegistry()
    registry.register("event.a", lambda p: p)
    registry.register("event.b", lambda p: p)
    registry.clear("event.a")
    assert registry.list_hooks("event.a") == []
    assert len(registry.list_hooks("event.b")) == 1


@pytest.mark.asyncio
async def test_hook_timeout_fail_open():
    registry = HookRegistry(config=HookConfig(hook_timeout_sec=0.01, fail_open=True))

    async def slow_hook(p):
        await asyncio.sleep(10)
        return p

    registry.register("test.event", slow_hook, priority=10)
    result = await registry.dispatch_before("test.event", "original")
    assert result == "original"
