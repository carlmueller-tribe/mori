"""ask_user tool yields via YieldToUser exception."""

from __future__ import annotations

import pytest

from mori.hooks.exceptions import YieldToUser
from mori.tools.native.ask_user import ask_user


@pytest.mark.asyncio
async def test_ask_user_raises_yield_to_user() -> None:
    with pytest.raises(YieldToUser) as exc:
        await ask_user("which db?")
    assert exc.value.question == "which db?"


@pytest.mark.asyncio
async def test_ask_user_question_is_required() -> None:
    with pytest.raises(TypeError):
        await ask_user()  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_tool_registry_re_raises_yield_to_user() -> None:
    """When ask_user raises YieldToUser, ToolRegistry.invoke must re-raise."""
    from mori.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register("ask_user", ask_user, description="ask the user")
    with pytest.raises(YieldToUser) as exc:
        await registry.invoke("ask_user", {"question": "which db?"})
    assert exc.value.question == "which db?"


@pytest.mark.asyncio
async def test_tool_registry_re_raises_hook_block() -> None:
    """If a tool raises HookBlock, the registry must re-raise."""
    from mori.hooks.exceptions import HookBlock
    from mori.tools.registry import ToolRegistry

    async def blocker() -> None:
        raise HookBlock("stop")

    registry = ToolRegistry()
    registry.register("blocker", blocker, description="x")
    with pytest.raises(HookBlock):
        await registry.invoke("blocker", {})


@pytest.mark.asyncio
async def test_tool_registry_re_raises_hook_retry() -> None:
    from mori.hooks.exceptions import HookRetry
    from mori.tools.registry import ToolRegistry

    async def retrier() -> None:
        raise HookRetry("again")

    registry = ToolRegistry()
    registry.register("retrier", retrier, description="x")
    with pytest.raises(HookRetry):
        await registry.invoke("retrier", {})


@pytest.mark.asyncio
async def test_loop_pauses_on_ask_user_yield() -> None:
    """When the model calls ask_user, the loop pauses with
    paused_reason='await_user_input' and paused_prompt set."""
    from unittest.mock import AsyncMock

    from mori.control.checkpoint import InMemoryCheckpoints
    from mori.model.base import ModelAdapter
    from mori.runtime.loop import AgentLoop
    from mori.tools.registry import ToolRegistry
    from mori.types import (
        Message,
        ModelResponse,
        RunStatus,
        TokenUsage,
        ToolCall,
    )

    mock_model = AsyncMock(spec=ModelAdapter)
    mock_model.model_id = "test"
    mock_model.supports_tool_use = True
    mock_model.max_context_tokens = 100000
    # The model asks ask_user on first call. No second call (we pause).
    mock_model.invoke = AsyncMock(return_value=ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="ask_user", arguments={"question": "which db?"})],
        ),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="tool_use",
    ))

    tools = ToolRegistry()
    tools.register("ask_user", ask_user, description="ask the user")

    checkpointer = InMemoryCheckpoints()

    loop = AgentLoop(model=mock_model, tools=tools, checkpointer=checkpointer)
    result = await loop.run("migrate the user table")

    assert result.status == RunStatus.PAUSED
    assert result.paused_prompt == "which db?"
    assert result.checkpoint_id is not None
