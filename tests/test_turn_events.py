"""turn.start and turn.end fire on run() and resume()."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from mori.hooks.events import HookEvents, TurnEndReason
from mori.hooks.registry import HookRegistry
from mori.model.base import ModelAdapter
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import Message, ModelResponse, TokenUsage


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
async def test_turn_start_fires_on_run(mock_model) -> None:
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    seen: list[Any] = []
    hooks = HookRegistry()

    async def capture(payload: Any) -> None:
        seen.append(payload)
        return None

    hooks.register(HookEvents.TURN_START, capture)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("hello")
    assert len(seen) == 1
    assert seen[0].input == "hello"
    assert seen[0].is_resume is False


@pytest.mark.asyncio
async def test_turn_end_fires_on_run(mock_model) -> None:
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    seen: list[Any] = []
    hooks = HookRegistry()

    async def capture(payload: Any) -> None:
        seen.append(payload)
        return None

    hooks.register(HookEvents.TURN_END, capture)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("hello")
    assert len(seen) == 1
    assert seen[0].reason in {TurnEndReason.COMPLETED, TurnEndReason.EXHAUSTED}
