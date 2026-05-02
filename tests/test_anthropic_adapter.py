"""Tests for AnthropicAdapter — all model calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mori.model.anthropic import AnthropicAdapter
from mori.types import (
    Message,
    ModelRequest,
    ToolId,
    ToolSpec,
)


@pytest.fixture
def adapter():
    """Create an adapter with a mocked Anthropic client."""
    with patch("mori.model.anthropic.anthropic") as mock_mod:
        mock_client = MagicMock()
        mock_mod.AsyncAnthropic.return_value = mock_client
        a = AnthropicAdapter(model="claude-sonnet-4-20250514", api_key="test-key")
        a._client = mock_client
        yield a, mock_client


def test_adapter_properties(adapter):
    a, _ = adapter
    assert a.model_id == "claude-sonnet-4-20250514"
    assert a.supports_tool_use is True
    assert a.max_context_tokens > 0


def test_convert_tools_to_anthropic_format(adapter):
    a, _ = adapter
    specs = [
        ToolSpec(
            tool_id=ToolId("native:add"),
            name="add",
            description="Add two numbers",
            input_schema={
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
            },
        )
    ]
    converted = a._convert_tools(specs)
    assert len(converted) == 1
    assert converted[0]["name"] == "add"
    assert converted[0]["description"] == "Add two numbers"
    assert converted[0]["input_schema"]["type"] == "object"


def test_extract_system_message(adapter):
    a, _ = adapter
    messages = [
        Message(role="system", content="You are helpful."),
        Message(role="user", content="Hi"),
    ]
    system, remaining = a._extract_system(messages)
    assert system == "You are helpful."
    assert len(remaining) == 1
    assert remaining[0].role == "user"


def test_extract_system_message_when_none(adapter):
    a, _ = adapter
    messages = [Message(role="user", content="Hi")]
    system, remaining = a._extract_system(messages)
    assert system is None
    assert len(remaining) == 1


def test_convert_messages_to_anthropic(adapter):
    a, _ = adapter
    messages = [
        Message(role="user", content="Hello"),
        Message(role="assistant", content="Hi there"),
    ]
    converted = a._convert_messages(messages)
    assert converted[0]["role"] == "user"
    assert converted[0]["content"] == "Hello"
    assert converted[1]["role"] == "assistant"
    assert converted[1]["content"] == "Hi there"


def test_convert_tool_result_message(adapter):
    a, _ = adapter
    messages = [
        Message(role="tool", content="42", tool_call_id="toolu_123"),
    ]
    converted = a._convert_messages(messages)
    assert converted[0]["role"] == "user"
    assert converted[0]["content"][0]["type"] == "tool_result"
    assert converted[0]["content"][0]["tool_use_id"] == "toolu_123"
    assert converted[0]["content"][0]["content"] == "42"


def test_convert_consecutive_tool_results_merged(adapter):
    """Multiple tool results should merge into a single user message."""
    a, _ = adapter
    messages = [
        Message(role="tool", content="8", tool_call_id="toolu_1"),
        Message(role="tool", content="12", tool_call_id="toolu_2"),
    ]
    converted = a._convert_messages(messages)
    assert len(converted) == 1
    assert converted[0]["role"] == "user"
    assert len(converted[0]["content"]) == 2
    assert converted[0]["content"][0]["tool_use_id"] == "toolu_1"
    assert converted[0]["content"][1]["tool_use_id"] == "toolu_2"


async def test_invoke_text_response(adapter):
    a, mock_client = adapter

    mock_response = MagicMock()
    mock_response.content = [MagicMock(type="text", text="The answer is 42.")]
    mock_response.usage = MagicMock(input_tokens=50, output_tokens=10)
    mock_response.stop_reason = "end_turn"
    mock_response.model_dump.return_value = {}

    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    request = ModelRequest(messages=[Message(role="user", content="What is 6*7?")])
    response = await a.invoke(request)

    assert response.message.role == "assistant"
    assert response.message.content == "The answer is 42."
    assert response.stop_reason == "end_turn"
    assert response.usage.input_tokens == 50
    assert response.usage.output_tokens == 10


async def test_invoke_tool_use_response(adapter):
    a, mock_client = adapter

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "toolu_abc"
    tool_block.name = "add"
    tool_block.input = {"a": 3, "b": 5}

    mock_response = MagicMock()
    mock_response.content = [tool_block]
    mock_response.usage = MagicMock(input_tokens=60, output_tokens=20)
    mock_response.stop_reason = "tool_use"
    mock_response.model_dump.return_value = {}

    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    specs = [
        ToolSpec(
            tool_id=ToolId("native:add"),
            name="add",
            description="Add",
            input_schema={"type": "object"},
        )
    ]
    request = ModelRequest(
        messages=[Message(role="user", content="Add 3 and 5")],
        tools=specs,
    )
    response = await a.invoke(request)

    assert response.stop_reason == "tool_use"
    assert response.message.tool_calls is not None
    assert len(response.message.tool_calls) == 1
    assert response.message.tool_calls[0].id == "toolu_abc"
    assert response.message.tool_calls[0].name == "add"
    assert response.message.tool_calls[0].arguments == {"a": 3, "b": 5}


async def test_invoke_mixed_text_and_tool_use(adapter):
    a, mock_client = adapter

    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "I'll add those for you."

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = "toolu_xyz"
    tool_block.name = "add"
    tool_block.input = {"a": 1, "b": 2}

    mock_response = MagicMock()
    mock_response.content = [text_block, tool_block]
    mock_response.usage = MagicMock(input_tokens=40, output_tokens=30)
    mock_response.stop_reason = "tool_use"
    mock_response.model_dump.return_value = {}

    mock_client.messages = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    request = ModelRequest(messages=[Message(role="user", content="Add 1+2")])
    response = await a.invoke(request)

    assert response.message.content == "I'll add those for you."
    assert response.message.tool_calls is not None
    assert len(response.message.tool_calls) == 1
