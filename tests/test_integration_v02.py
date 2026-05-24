"""v0.2 exit tests — CLI tools + observability integration."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mori import Mori
from mori.types import Message, ModelResponse, RunStatus, TokenUsage, ToolCall


def _tool_response(tool_id: str, name: str, args: dict) -> ModelResponse:
    return ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id=tool_id, name=name, arguments=args)],
        ),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="tool_use",
    )


def _text_response(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=80, output_tokens=30),
        stop_reason="end_turn",
    )


async def test_v02_exit_test_cli_and_observability(tmp_path):
    """v0.2 exit test: agent uses CLI tool and events appear in JSONL."""
    traces_path = str(tmp_path / "traces.jsonl")

    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(
            side_effect=[
                _tool_response("call_1", "echo_tool", {"0": "hello from CLI"}),
                _text_response("The CLI tool returned: hello from CLI"),
            ]
        )
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .cli("echo_tool", command="echo", description="Echo text", args_format="positional")
            .sink("jsonl", path=traces_path)
            .config(max_steps=10)
            .checkpointer("inmemory")
            .build()
        )
        result = await agent.run("Echo something")
        await agent.close()

        assert result.status == RunStatus.COMPLETED
        assert result.total_tool_calls >= 1

        lines = Path(traces_path).read_text().strip().split("\n")
        events = [json.loads(line) for line in lines]
        event_types = [e["event_type"] for e in events]

        assert "run.start" in event_types
        assert "run.end" in event_types
        assert "tool.invoke" in event_types
        assert "tool.result" in event_types


async def test_v02_mixed_native_and_cli_tools(tmp_path):
    """Native and CLI tools coexist in same registry."""
    traces_path = str(tmp_path / "traces.jsonl")

    def add(a: int, b: int) -> int:
        return a + b

    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(
            side_effect=[
                _tool_response("call_1", "add", {"a": 3, "b": 5}),
                _tool_response("call_2", "echo_tool", {"0": "result is 8"}),
                _text_response("Added 3+5=8 and echoed it"),
            ]
        )
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(add, description="Add two numbers")
            .cli("echo_tool", command="echo", description="Echo", args_format="positional")
            .sink("jsonl", path=traces_path)
            .config(max_steps=10)
            .checkpointer("inmemory")
            .build()
        )
        result = await agent.run("Add 3+5 then echo the result")
        await agent.close()

        assert result.status == RunStatus.COMPLETED
        assert result.total_tool_calls == 2


async def test_v02_step_limit_with_bound_violation_event(tmp_path):
    """ControlBounds emits violation events on step limit."""
    traces_path = str(tmp_path / "traces.jsonl")

    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(
            return_value=_tool_response("call_n", "echo_tool", {"0": "loop"})
        )
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .cli("echo_tool", command="echo", description="Echo", args_format="positional")
            .sink("jsonl", path=traces_path)
            .config(max_steps=3)
            .checkpointer("inmemory")
            .build()
        )
        result = await agent.run("loop forever")
        await agent.close()

        assert result.status == RunStatus.FAILED

        lines = Path(traces_path).read_text().strip().split("\n")
        events = [json.loads(line) for line in lines]
        event_types = [e["event_type"] for e in events]
        assert "control.bound_violation" in event_types
