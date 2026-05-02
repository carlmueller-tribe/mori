"""Tests for AgentLoop — model calls are mocked."""

from unittest.mock import AsyncMock

import pytest

from mori.control.bounds import ControlBounds, ControlConfig
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


def _text_response(text: str, input_tokens: int = 50, output_tokens: int = 20) -> ModelResponse:
    """Create a ModelResponse with just text (no tool calls)."""
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="end_turn",
    )


def _tool_response(
    tool_id: str, tool_name: str, arguments: dict, input_tokens: int = 50, output_tokens: int = 20
) -> ModelResponse:
    """Create a ModelResponse with a tool call."""
    return ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id=tool_id, name=tool_name, arguments=arguments)],
        ),
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="tool_use",
    )


@pytest.fixture
def mock_model():
    model = AsyncMock(spec=ModelAdapter)
    model.model_id = "test-model"
    model.supports_tool_use = True
    model.max_context_tokens = 100000
    return model


@pytest.fixture
def registry_with_add():
    registry = ToolRegistry()

    def add(a: int, b: int) -> int:
        return a + b

    registry.register("add", add, description="Add two numbers")
    return registry


async def test_simple_text_response(mock_model, registry_with_add):
    """Model answers directly without tool calls — loop completes in one step."""
    mock_model.invoke = AsyncMock(return_value=_text_response("The answer is 42."))

    loop = AgentLoop(model=mock_model, tools=registry_with_add)
    result = await loop.run("What is the meaning of life?")

    assert result.status == RunStatus.COMPLETED
    assert result.final_output == "The answer is 42."
    assert result.total_steps == 1
    assert result.total_tool_calls == 0


async def test_single_tool_call(mock_model, registry_with_add):
    """Model calls a tool, gets the result, then answers."""
    mock_model.invoke = AsyncMock(
        side_effect=[
            _tool_response("call_1", "add", {"a": 3, "b": 5}),
            _text_response("3 + 5 = 8"),
        ]
    )

    loop = AgentLoop(model=mock_model, tools=registry_with_add)
    result = await loop.run("What is 3 + 5?")

    assert result.status == RunStatus.COMPLETED
    assert result.final_output == "3 + 5 = 8"
    assert result.total_steps == 2
    assert result.total_tool_calls == 1


async def test_multiple_tool_calls(mock_model, registry_with_add):
    """Model calls tools multiple times before answering."""
    mock_model.invoke = AsyncMock(
        side_effect=[
            _tool_response("call_1", "add", {"a": 3, "b": 5}),
            _tool_response("call_2", "add", {"a": 8, "b": 12}),
            _text_response("(3+5) + 12 = 20"),
        ]
    )

    loop = AgentLoop(model=mock_model, tools=registry_with_add)
    result = await loop.run("Add 3+5, then add 12")

    assert result.status == RunStatus.COMPLETED
    assert result.total_steps == 3
    assert result.total_tool_calls == 2


async def test_step_limit(mock_model, registry_with_add):
    """Loop terminates when step limit is hit."""
    mock_model.invoke = AsyncMock(return_value=_tool_response("call_n", "add", {"a": 1, "b": 1}))

    control = ControlBounds(config=ControlConfig(max_steps=3))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, control=control)
    result = await loop.run("infinite loop task")

    assert result.status == RunStatus.FAILED
    assert result.total_steps == 3


async def test_token_tracking(mock_model, registry_with_add):
    """Token usage is accumulated across steps."""
    mock_model.invoke = AsyncMock(
        side_effect=[
            _tool_response("call_1", "add", {"a": 1, "b": 2}, input_tokens=100, output_tokens=30),
            _text_response("done", input_tokens=150, output_tokens=20),
        ]
    )

    loop = AgentLoop(model=mock_model, tools=registry_with_add)
    result = await loop.run("test")

    assert result.total_usage.input_tokens == 250
    assert result.total_usage.output_tokens == 50


async def test_tool_failure_reported_to_model(mock_model):
    """When a tool raises, the error is sent back to the model."""
    registry = ToolRegistry()

    def fail(x: int) -> int:
        raise ValueError("something broke")

    registry.register("fail", fail, description="Always fails")

    mock_model.invoke = AsyncMock(
        side_effect=[
            _tool_response("call_1", "fail", {"x": 1}),
            _text_response("The tool failed, sorry."),
        ]
    )

    loop = AgentLoop(model=mock_model, tools=registry)
    result = await loop.run("try the failing tool")

    assert result.status == RunStatus.COMPLETED
    # The error message was injected into conversation
    tool_messages = [m for m in result.messages if m.role == "tool"]
    assert len(tool_messages) == 1
    assert "something broke" in str(tool_messages[0].content)


async def test_messages_include_full_conversation(mock_model, registry_with_add):
    """RunResult.messages contains the full conversation history."""
    mock_model.invoke = AsyncMock(
        side_effect=[
            _tool_response("call_1", "add", {"a": 1, "b": 2}),
            _text_response("Result is 3"),
        ]
    )

    loop = AgentLoop(model=mock_model, tools=registry_with_add)
    result = await loop.run("Add 1+2")

    roles = [m.role for m in result.messages]
    assert roles[0] == "user"  # Initial task
    assert roles[1] == "assistant"  # Tool call
    assert roles[2] == "tool"  # Tool result
    assert roles[3] == "assistant"  # Final answer


async def test_run_returns_duration(mock_model, registry_with_add):
    """RunResult includes total duration."""
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))

    loop = AgentLoop(model=mock_model, tools=registry_with_add)
    result = await loop.run("quick task")

    assert result.total_duration_ms > 0


async def test_token_limit_terminates(mock_model, registry_with_add):
    """Loop terminates when token limit is hit."""
    mock_model.invoke = AsyncMock(
        return_value=_tool_response(
            "call_n", "add", {"a": 1, "b": 1}, input_tokens=600_000, output_tokens=400_000
        )
    )

    control = ControlBounds(config=ControlConfig(max_total_tokens=2_000_000))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, control=control)
    result = await loop.run("token heavy task")

    assert result.status == RunStatus.FAILED
    assert result.total_usage.input_tokens + result.total_usage.output_tokens >= 2_000_000


async def test_multiple_tool_calls_in_single_message(mock_model):
    """Model returns two tool calls in one message — both are executed."""
    registry = ToolRegistry()

    def add(a: int, b: int) -> int:
        return a + b

    def multiply(a: int, b: int) -> int:
        return a * b

    registry.register("add", add, description="Add")
    registry.register("multiply", multiply, description="Multiply")

    multi_tool_response = ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="call_1", name="add", arguments={"a": 3, "b": 5}),
                ToolCall(id="call_2", name="multiply", arguments={"a": 2, "b": 4}),
            ],
        ),
        usage=TokenUsage(input_tokens=50, output_tokens=30),
        stop_reason="tool_use",
    )

    mock_model.invoke = AsyncMock(
        side_effect=[
            multi_tool_response,
            _text_response("3+5=8 and 2*4=8"),
        ]
    )

    loop = AgentLoop(model=mock_model, tools=registry)
    result = await loop.run("Add 3+5 and multiply 2*4")

    assert result.status == RunStatus.COMPLETED
    assert result.total_tool_calls == 2
    tool_messages = [m for m in result.messages if m.role == "tool"]
    assert len(tool_messages) == 2
