"""v0.1 exit test — proves the whole thing works end-to-end.

Uses a mocked model to avoid API calls in CI. For a real integration
test with Claude, set ANTHROPIC_API_KEY and run:
    pytest tests/test_integration.py -k real --run-real
"""

from unittest.mock import AsyncMock, patch

from mori import Mori
from mori.types import (
    Message,
    ModelResponse,
    RunStatus,
    TokenUsage,
    ToolCall,
)


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


async def test_v01_exit_test():
    """v0.1 exit test: agent uses two tools and produces a correct answer.

    Scenario: "What is (3 + 5) * 12?"
    Expected: model calls add(3, 5) → 8, then multiply(8, 12) → 96, then answers "96".
    """

    def add(a: int, b: int) -> int:
        return a + b

    def multiply(a: int, b: int) -> int:
        return a * b

    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(
            side_effect=[
                _tool_response("call_1", "add", {"a": 3, "b": 5}),
                _tool_response("call_2", "multiply", {"a": 8, "b": 12}),
                _text_response("(3 + 5) * 12 = 96"),
            ]
        )
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", model="claude-sonnet-4-20250514", api_key="test")
            .tool(add, description="Add two numbers")
            .tool(multiply, description="Multiply two numbers")
            .build()
        )
        result = await agent.run("What is (3 + 5) * 12?")

        assert result.status == RunStatus.COMPLETED
        assert "96" in result.final_output
        assert result.total_tool_calls == 2
        assert result.total_steps == 3


async def test_v01_simple_no_tools():
    """Agent answers a question without needing tools."""
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(return_value=_text_response("Hello! How can I help?"))
        MockAdapter.return_value = mock_adapter

        agent = Mori.builder().model("anthropic", api_key="test").build()
        result = await agent.run("Hello")

        assert result.status == RunStatus.COMPLETED
        assert result.final_output == "Hello! How can I help?"
        assert result.total_steps == 1
        assert result.total_tool_calls == 0


async def test_v01_step_limit_enforced():
    """Agent stops when step limit is reached."""
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(return_value=_tool_response("call_n", "noop", {}))
        MockAdapter.return_value = mock_adapter

        def noop() -> str:
            return "ok"

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(noop, description="Does nothing")
            .config(max_steps=5)
            .build()
        )
        result = await agent.run("Loop forever")

        assert result.status == RunStatus.FAILED
        assert result.total_steps == 5
