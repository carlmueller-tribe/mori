"""End-to-end integration tests for Active Hooks v0.7."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from mori.hooks.events import HookEvents
from mori.hooks.exceptions import HookBlock
from mori.hooks.registry import HookRegistry
from mori.model.base import ModelAdapter
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import Message, ModelResponse, RunStatus, TokenUsage


def _text(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


@pytest.fixture
def mock_model():
    model = AsyncMock(spec=ModelAdapter)
    model.model_id = "test"
    model.supports_tool_use = True
    model.max_context_tokens = 100000
    return model


@pytest.mark.asyncio
async def test_turn_start_block_yields_blocked_result(mock_model) -> None:
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()

    async def blocker(payload: Any) -> None:
        raise HookBlock("forbidden task", hook_id="my_hook")

    hooks.register(HookEvents.TURN_START, blocker)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    result = await loop.run("anything")
    assert result.status == RunStatus.BLOCKED
    assert result.block_reason == "forbidden task"
    assert result.block_hook_id is not None


@pytest.mark.asyncio
async def test_turn_start_block_does_not_invoke_model(mock_model) -> None:
    """When turn.start blocks, the model is never invoked."""
    mock_model.invoke = AsyncMock(return_value=_text("should not run"))
    hooks = HookRegistry()

    async def blocker(payload: Any) -> None:
        raise HookBlock("nope")

    hooks.register(HookEvents.TURN_START, blocker)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("anything")
    mock_model.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_turn_start_block_fires_turn_end_with_blocked_reason(mock_model) -> None:
    """turn.end still fires (with reason=BLOCKED) when turn.start blocks."""
    from mori.hooks.events import TurnEndReason

    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()
    end_payloads: list[Any] = []

    async def blocker(payload: Any) -> None:
        raise HookBlock("nope")

    async def capture_end(payload: Any) -> None:
        end_payloads.append(payload)
        return None

    hooks.register(HookEvents.TURN_START, blocker)
    hooks.register(HookEvents.TURN_END, capture_end)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("anything")
    assert len(end_payloads) == 1
    assert end_payloads[0].reason == TurnEndReason.BLOCKED


@pytest.mark.asyncio
async def test_tool_invoke_block_appends_synthetic_message(mock_model) -> None:
    """When a tool.invoke.before hook blocks, the tool call gets a synthetic
    blocked result message and the loop continues (no actual tool invocation)."""
    from mori.types import ToolCall

    # First model response: assistant requests apply_migration with env=prod
    first_response = ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="apply_migration", arguments={"env": "prod"})],
        ),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="tool_use",
    )
    # Second response: assistant declares done (no tool calls → loop exits)
    second_response = _text("done")
    mock_model.invoke = AsyncMock(side_effect=[first_response, second_response])

    registry = ToolRegistry()
    invoked = []

    def apply_migration(env: str) -> str:
        invoked.append(env)
        return "applied"

    registry.register("apply_migration", apply_migration, description="apply a migration")

    hooks = HookRegistry()

    async def block_prod(call: Any) -> None:
        if call.arguments.get("env") == "prod":
            raise HookBlock("no prod tools", hook_id="prod_gate")
        return None

    hooks.register(HookEvents.TOOL_INVOKE_BEFORE, block_prod)

    loop = AgentLoop(model=mock_model, tools=registry, hooks=hooks)
    result = await loop.run("do the thing")

    # The tool was NOT actually invoked
    assert invoked == []

    # A synthetic blocked message appears in the conversation
    blocked_msgs = [
        m for m in result.messages
        if m.role == "tool" and isinstance(m.content, str) and "BLOCKED" in m.content
    ]
    assert len(blocked_msgs) == 1
    assert "no prod tools" in blocked_msgs[0].content
    assert "prod_gate" in blocked_msgs[0].content
    assert blocked_msgs[0].tool_call_id == "c1"

    # Status is NOT BLOCKED — the run continued
    assert result.status != RunStatus.BLOCKED


@pytest.mark.asyncio
async def test_model_request_block_returns_blocked_result(mock_model) -> None:
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()

    async def blocker(req: Any) -> None:
        raise HookBlock("request gate", hook_id="req_gate")

    hooks.register(HookEvents.MODEL_REQUEST_BEFORE, blocker)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    result = await loop.run("anything")
    assert result.status == RunStatus.BLOCKED
    assert result.block_reason == "request gate"
    assert result.block_hook_id == "req_gate"


@pytest.mark.asyncio
async def test_model_request_retry_appends_feedback_and_retries(mock_model) -> None:
    """First call to model.request.before hook raises HookRetry; second call passes through."""
    from mori.hooks.exceptions import HookRetry

    mock_model.invoke = AsyncMock(return_value=_text("hello"))

    call_count = 0
    hooks = HookRegistry()

    async def retry_once(req: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise HookRetry("think harder", hook_id="r")
        return None

    hooks.register(HookEvents.MODEL_REQUEST_BEFORE, retry_once)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    result = await loop.run("hello")

    # The feedback should appear as a system message in the state
    system_msgs = [
        m for m in result.messages
        if m.role == "system" and "think harder" in (m.content or "")
    ]
    assert len(system_msgs) >= 1
    assert result.status != RunStatus.BLOCKED
    # The hook ran twice (once retry, once allowed)
    assert call_count == 2
    # The model was invoked exactly once (after the retry passed)
    assert mock_model.invoke.call_count == 1
