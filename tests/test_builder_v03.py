"""Tests for v0.3 builder — .memory_backend()."""
from unittest.mock import AsyncMock, patch
import pytest
from mori import Mori
from mori.types import MemoryLayer, Message, ModelResponse, RunStatus, TokenUsage

def _text_response(text):
    return ModelResponse(message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="end_turn")

def test_builder_memory_inmemory():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").memory_backend("inmemory").build()
        assert agent.memory is not None

def test_builder_no_memory():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").build()
        assert agent.memory is None

@pytest.mark.asyncio
async def test_builder_memory_stats():
    with patch("mori.agent.AnthropicAdapter") as M:
        mock = AsyncMock()
        mock.invoke = AsyncMock(return_value=_text_response("done"))
        M.return_value = mock
        agent = Mori.builder().model("anthropic", api_key="test").memory_backend("inmemory").build()
        await agent.run("test")
        stats = await agent.memory.stats()
        assert stats.total_records > 0
        await agent.close()
