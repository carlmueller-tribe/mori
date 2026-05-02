import pytest
from unittest.mock import AsyncMock
from mori.hooks.registry import HookRegistry
from mori.model.base import ModelAdapter
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import Message, ModelResponse, TokenUsage, ToolCall

def _text(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="end_turn",
    )

def _tool_resp(tid, name, args):
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
async def test_run_start_and_end_hooks_fire(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()
    fired = []
    hooks.register("run.start", lambda p: fired.append("start"))
    hooks.register("run.end", lambda p: fired.append("end"))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("test")
    assert "start" in fired
    assert "end" in fired

@pytest.mark.asyncio
async def test_tool_before_hook_modifies_arguments(mock_model):
    calls = []
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "add", {"a": 1, "b": 2}),
        _text("result"),
    ])
    registry = ToolRegistry()
    def spy_add(a, b):
        calls.append({"a": a, "b": b})
        return a + b
    registry.register("add", spy_add, description="Add")
    hooks = HookRegistry()
    def modify_hook(tool_call):
        tool_call.arguments["a"] = 99
        return tool_call
    hooks.register("tool.invoke.before", modify_hook, priority=10)
    loop = AgentLoop(model=mock_model, tools=registry, hooks=hooks)
    await loop.run("add")
    assert calls[0]["a"] == 99

@pytest.mark.asyncio
async def test_tool_after_hook_fires(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "add", {"a": 1, "b": 2}),
        _text("result"),
    ])
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    hooks = HookRegistry()
    seen_tools = []
    hooks.register("tool.invoke.after", lambda r: seen_tools.append(r.tool_name))
    loop = AgentLoop(model=mock_model, tools=registry, hooks=hooks)
    await loop.run("add")
    assert "add" in seen_tools

@pytest.mark.asyncio
async def test_model_request_before_hook_fires(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()
    requests_seen = []
    hooks.register("model.request.before", lambda req: requests_seen.append(req) or req)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("test")
    assert len(requests_seen) >= 1

@pytest.mark.asyncio
async def test_model_response_after_hook_fires(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()
    responses_seen = []
    hooks.register("model.response.after", lambda resp: responses_seen.append(resp))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("test")
    assert len(responses_seen) >= 1

@pytest.mark.asyncio
async def test_loop_without_hooks_still_works(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    from mori.types import RunStatus
    loop = AgentLoop(model=mock_model, tools=ToolRegistry())
    result = await loop.run("test")
    assert result.status == RunStatus.COMPLETED
