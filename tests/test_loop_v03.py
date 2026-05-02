"""Tests for v0.3 loop — memory retrieve and update phases."""

import math
from unittest.mock import AsyncMock

import pytest

from mori.memory.backends.inmemory import InMemoryBackend
from mori.memory.module import MemoryModule
from mori.model.base import ModelAdapter
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import ObservabilityConfig
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import (
    MemoryConfig,
    MemoryLayer,
    Message,
    ModelResponse,
    RunStatus,
    TokenUsage,
    ToolCall,
)


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            vec = [0.0] * 10
            for i, ch in enumerate(text[:10]):
                vec[i % 10] += ord(ch) / 1000.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            results.append([v / norm for v in vec])
        return results

    @property
    def dimensions(self) -> int:
        return 10


def _text_response(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="end_turn",
    )


def _tool_response(tid, name, args):
    return ModelResponse(
        message=Message(
            role="assistant", content="", tool_calls=[ToolCall(id=tid, name=name, arguments=args)]
        ),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="tool_use",
    )


@pytest.fixture
def mock_model():
    model = AsyncMock(spec=ModelAdapter)
    model.model_id = "test"
    model.supports_tool_use = True
    model.max_context_tokens = 100000
    return model


@pytest.fixture
def memory_module():
    return MemoryModule(backend=InMemoryBackend(), config=MemoryConfig(), embedder=FakeEmbedder())


async def test_loop_writes_working_memory(mock_model, memory_module):
    mock_model.invoke = AsyncMock(
        side_effect=[_tool_response("c1", "add", {"a": 1, "b": 2}), _text_response("3")]
    )
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    loop = AgentLoop(model=mock_model, tools=registry, memory=memory_module)
    result = await loop.run("Add 1+2")
    assert result.status == RunStatus.COMPLETED
    stats = await memory_module.stats()
    assert stats.records_per_layer[MemoryLayer.WORKING] > 0


async def test_loop_writes_episodic_on_completion(mock_model, memory_module):
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), memory=memory_module)
    await loop.run("test task")
    stats = await memory_module.stats()
    assert stats.records_per_layer[MemoryLayer.EPISODIC] > 0


async def test_loop_emits_memory_events(mock_model, memory_module):
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))
    collected = []

    class Sink:
        realtime = True

        async def write(self, e):
            collected.append(e)

        async def write_batch(self, es):
            collected.extend(es)

        async def flush(self):
            pass

        async def close(self):
            pass

    obs = ObservabilityEngine(sinks=[Sink()], config=ObservabilityConfig(buffer_size=100))
    loop = AgentLoop(
        model=mock_model, tools=ToolRegistry(), memory=memory_module, observability=obs
    )
    await loop.run("test")
    await obs.flush()
    types = [e.event_type for e in collected]
    assert "memory.read" in types
    assert "memory.write" in types


async def test_loop_without_memory_still_works(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry())
    result = await loop.run("test")
    assert result.status == RunStatus.COMPLETED
