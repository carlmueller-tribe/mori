import pytest
from unittest.mock import AsyncMock
from mori.control.checkpoint import InMemoryCheckpoints
from mori.model.base import ModelAdapter
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import Message, ModelResponse, RunStatus, ThreadId, TokenUsage, ToolCall

def _text(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="end_turn",
    )

def _tool(tid, name, args):
    return ModelResponse(
        message=Message(role="assistant", content="", tool_calls=[ToolCall(id=tid, name=name, arguments=args)]),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="tool_use",
    )

@pytest.fixture
def mock_model():
    model = AsyncMock(spec=ModelAdapter)
    model.model_id = "test"
    model.supports_tool_use = True
    model.max_context_tokens = 100000
    return model

@pytest.mark.asyncio
async def test_loop_saves_checkpoint_on_completion(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    checkpointer = InMemoryCheckpoints()
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), checkpointer=checkpointer)
    result = await loop.run("test", thread_id=ThreadId("t1"))
    assert result.status == RunStatus.COMPLETED
    assert result.checkpoint_id is not None
    checkpoints = await checkpointer.list(ThreadId("t1"))
    assert len(checkpoints) >= 1

@pytest.mark.asyncio
async def test_loop_periodic_checkpoint_every_n_steps(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool("c1", "add", {"a": 1, "b": 2}),
        _tool("c2", "add", {"a": 3, "b": 4}),
        _text("done"),
    ])
    checkpointer = InMemoryCheckpoints()
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    loop = AgentLoop(model=mock_model, tools=registry, checkpointer=checkpointer, checkpoint_every_n_steps=2)
    result = await loop.run("test", thread_id=ThreadId("t1"))
    assert result.status == RunStatus.COMPLETED
    checkpoints = await checkpointer.list(ThreadId("t1"))
    assert len(checkpoints) >= 2  # at least 1 periodic + 1 final

@pytest.mark.asyncio
async def test_loop_without_checkpointer_still_works(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry())
    result = await loop.run("test")
    assert result.status == RunStatus.COMPLETED
    assert result.checkpoint_id is None
