"""Tests for Mori builder and top-level API."""

from unittest.mock import AsyncMock, patch

import pytest

from mori import Mori
from mori.types import (
    Message,
    ModelResponse,
    RunStatus,
    TokenUsage,
    ToolCall,
)


def _text_response(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


def _tool_response(tool_id: str, tool_name: str, args: dict) -> ModelResponse:
    return ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id=tool_id, name=tool_name, arguments=args)],
        ),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="tool_use",
    )


def test_builder_returns_mori_instance():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-sonnet-4-20250514", api_key="test")
            .build()
        )
        assert isinstance(agent, Mori)


def test_builder_requires_model():
    with pytest.raises(ValueError, match="model"):
        Mori.builder().build()


def test_builder_registers_tool_function():
    def add(a: int, b: int) -> int:
        return a + b

    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(add, description="Add two numbers")
            .build()
        )
        specs = agent.tools.list_specs()
        assert len(specs) == 1
        assert specs[0].name == "add"


def test_builder_registers_tool_with_name():
    def my_func(x: int) -> int:
        return x

    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(my_func, description="Test", name="custom_name")
            .build()
        )
        specs = agent.tools.list_specs()
        assert specs[0].name == "custom_name"


def test_builder_config():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").config(max_steps=10).build()
        assert agent._loop._control._config.max_steps == 10


async def test_mori_run():
    """Full run through Mori.run()."""
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(
            side_effect=[
                _tool_response("call_1", "add", {"a": 3, "b": 5}),
                _text_response("3 + 5 = 8"),
            ]
        )
        MockAdapter.return_value = mock_adapter

        def add(a: int, b: int) -> int:
            return a + b

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(add, description="Add two numbers")
            .build()
        )
        result = await agent.run("What is 3 + 5?")

        assert result.status == RunStatus.COMPLETED
        assert "8" in (result.final_output or "")
        assert result.total_tool_calls == 1


def test_tools_property():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").build()
        assert agent.tools is not None
        assert agent.tools.list_specs() == []
