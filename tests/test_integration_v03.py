"""v0.3 exit tests — memory persists, working + episodic populated."""

from unittest.mock import AsyncMock, patch

import pytest

from mori import Mori
from mori.types import MemoryLayer, Message, ModelResponse, RunStatus, TokenUsage, ToolCall


def _tool_response(tid, name, args):
    return ModelResponse(
        message=Message(
            role="assistant", content="", tool_calls=[ToolCall(id=tid, name=name, arguments=args)]
        ),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="tool_use",
    )


def _text_response(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=80, output_tokens=30),
        stop_reason="end_turn",
    )


@pytest.mark.asyncio
async def test_v03_exit_test():
    def lookup(topic: str) -> str:
        return f"Info about {topic}: uses standard patterns."

    with patch("mori.agent.AnthropicAdapter") as M:
        mock = AsyncMock()
        mock.invoke = AsyncMock(
            side_effect=[
                _tool_response("c1", "lookup", {"topic": "auth"}),
                _tool_response("c2", "lookup", {"topic": "database"}),
                _text_response("Auth and DB both use standard patterns."),
            ]
        )
        M.return_value = mock
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(lookup, description="Look up a topic")
            .memory_backend("inmemory")
            .config(max_steps=10)
            .build()
        )
        result = await agent.run("Look up auth and database, summarize both", thread_id="test")
        assert result.status == RunStatus.COMPLETED
        stats = await agent.memory.stats()
        assert stats.records_per_layer[MemoryLayer.WORKING] > 0
        assert stats.records_per_layer[MemoryLayer.EPISODIC] > 0
        assert stats.total_records >= 3
        await agent.close()


@pytest.mark.asyncio
async def test_v03_no_memory_backward_compat():
    with patch("mori.agent.AnthropicAdapter") as M:
        mock = AsyncMock()
        mock.invoke = AsyncMock(return_value=_text_response("done"))
        M.return_value = mock
        agent = Mori.builder().model("anthropic", api_key="test").build()
        result = await agent.run("test")
        assert result.status == RunStatus.COMPLETED
        assert agent.memory is None
