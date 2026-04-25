"""Tests for v0.2 loop — observability events and control bounds."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from mori.control.bounds import ControlBounds, ControlConfig
from mori.model.base import ModelAdapter
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import ObservabilityConfig
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import Message, ModelResponse, RunStatus, ToolCall, TokenUsage


def _text_response(text: str, input_tokens: int = 50, output_tokens: int = 20) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="end_turn",
    )

def _tool_response(tool_id: str, tool_name: str, arguments: dict) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content="", tool_calls=[ToolCall(id=tool_id, name=tool_name, arguments=arguments)]),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
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
    registry.register("add", lambda a, b: a + b, description="Add")
    return registry

class CollectorSink:
    def __init__(self):
        self.events = []
    async def write(self, event):
        self.events.append(event)
    async def write_batch(self, events):
        self.events.extend(events)
    async def flush(self):
        pass
    async def close(self):
        pass

async def test_loop_emits_run_events(mock_model, registry_with_add):
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))
    sink = CollectorSink()
    obs = ObservabilityEngine(sinks=[sink], config=ObservabilityConfig(buffer_size=100))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, observability=obs)
    await loop.run("test")
    await obs.flush()
    event_types = [e.event_type for e in sink.events]
    assert "run.start" in event_types
    assert "run.end" in event_types

async def test_loop_emits_step_events(mock_model, registry_with_add):
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))
    sink = CollectorSink()
    obs = ObservabilityEngine(sinks=[sink], config=ObservabilityConfig(buffer_size=100))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, observability=obs)
    await loop.run("test")
    await obs.flush()
    event_types = [e.event_type for e in sink.events]
    assert "step.start" in event_types
    assert "step.end" in event_types

async def test_loop_emits_tool_events(mock_model, registry_with_add):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_response("call_1", "add", {"a": 1, "b": 2}),
        _text_response("3"),
    ])
    sink = CollectorSink()
    obs = ObservabilityEngine(sinks=[sink], config=ObservabilityConfig(buffer_size=100))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, observability=obs)
    await loop.run("add 1+2")
    await obs.flush()
    event_types = [e.event_type for e in sink.events]
    assert "tool.invoke" in event_types
    assert "tool.result" in event_types

async def test_loop_uses_control_bounds(mock_model, registry_with_add):
    mock_model.invoke = AsyncMock(return_value=_tool_response("call_n", "add", {"a": 1, "b": 1}))
    control = ControlBounds(config=ControlConfig(max_steps=3))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, control=control)
    result = await loop.run("loop forever")
    assert result.status == RunStatus.FAILED
    assert result.total_steps == 3

async def test_loop_emits_bound_violation(mock_model, registry_with_add):
    mock_model.invoke = AsyncMock(return_value=_tool_response("call_n", "add", {"a": 1, "b": 1}))
    sink = CollectorSink()
    obs = ObservabilityEngine(sinks=[sink], config=ObservabilityConfig(buffer_size=100))
    control = ControlBounds(config=ControlConfig(max_steps=2))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, observability=obs, control=control)
    await loop.run("loop")
    await obs.flush()
    event_types = [e.event_type for e in sink.events]
    assert "control.bound_violation" in event_types

async def test_loop_without_observability_still_works(mock_model, registry_with_add):
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))
    loop = AgentLoop(model=mock_model, tools=registry_with_add)
    result = await loop.run("test")
    assert result.status == RunStatus.COMPLETED

async def test_loop_without_control_uses_default(mock_model, registry_with_add):
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))
    loop = AgentLoop(model=mock_model, tools=registry_with_add)
    result = await loop.run("test")
    assert result.status == RunStatus.COMPLETED
