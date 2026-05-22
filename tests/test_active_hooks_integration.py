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
