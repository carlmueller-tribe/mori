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
    mock_model.invoke = AsyncMock(
        return_value=ModelResponse(
            message=Message(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(id="c1", name="ask_user", arguments={"question": "which db?"})
                ],
            ),
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            stop_reason="tool_use",
        )
    )

    tools = ToolRegistry()
    tools.register("ask_user", ask_user, description="ask the user")

    checkpointer = InMemoryCheckpoints()

    loop = AgentLoop(model=mock_model, tools=tools, checkpointer=checkpointer)
    result = await loop.run("migrate the user table")

    assert result.status == RunStatus.PAUSED
    assert result.paused_prompt == "which db?"
    assert result.checkpoint_id is not None


@pytest.mark.asyncio
async def test_resume_after_ask_user_injects_input_as_tool_result() -> None:
    """After ask_user pause, resume(thread_id, user_text) appends a tool
    result message with the user's response and continues the run."""
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

    ask_response = ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="ask_user", arguments={"question": "which db?"})],
        ),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="tool_use",
    )
    done_response = ModelResponse(
        message=Message(role="assistant", content="done"),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )
    mock_model.invoke = AsyncMock(side_effect=[ask_response, done_response])

    tools = ToolRegistry()
    tools.register("ask_user", ask_user, description="ask the user")

    checkpointer = InMemoryCheckpoints()

    loop = AgentLoop(model=mock_model, tools=tools, checkpointer=checkpointer)
    paused = await loop.run("migrate the user table")
    assert paused.status == RunStatus.PAUSED

    resumed = await loop.resume(paused.thread_id, "production_db")
    # The resumed conversation contains the user's text as a tool message with the paused call's id
    user_tool_msgs = [
        m for m in resumed.messages if m.role == "tool" and m.content == "production_db"
    ]
    assert len(user_tool_msgs) == 1
    # The agent should have completed (the second model response was no-tool-call)
    assert resumed.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_resume_dict_input_with_response_key() -> None:
    """If resume() is called with a dict {'response': ...}, the value is used as user_text."""
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
    ask_response = ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="ask_user", arguments={"question": "x?"})],
        ),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="tool_use",
    )
    done_response = ModelResponse(
        message=Message(role="assistant", content="ok"),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )
    mock_model.invoke = AsyncMock(side_effect=[ask_response, done_response])

    tools = ToolRegistry()
    tools.register("ask_user", ask_user, description="ask the user")
    checkpointer = InMemoryCheckpoints()
    loop = AgentLoop(model=mock_model, tools=tools, checkpointer=checkpointer)
    paused = await loop.run("hi")
    assert paused.status == RunStatus.PAUSED

    resumed = await loop.resume(paused.thread_id, {"response": "yes"})
    user_tool_msgs = [m for m in resumed.messages if m.role == "tool" and m.content == "yes"]
    assert len(user_tool_msgs) == 1
