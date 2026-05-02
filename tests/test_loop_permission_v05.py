"""Loop permission integration tests — Task 7 of v0.5 "It's Governed"."""
import pytest
from unittest.mock import AsyncMock
from mori.control.checkpoint import InMemoryCheckpoints
from mori.model.base import ModelAdapter
from mori.permission.engine import PermissionEngine
from mori.permission.types import (
    Identity, IdentityPattern, IdentityType, Permission, PermissionConfig,
    PermissionRule, Resource, ResourcePattern, ResourceType,
)
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import Message, ModelResponse, RunStatus, ThreadId, TokenUsage, ToolCall


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


def _allow_engine() -> PermissionEngine:
    config = PermissionConfig(rules=[PermissionRule(
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="*"),
        identity=IdentityPattern(match="any", value="*"),
        permissions="r-x", effect="allow",
    )])
    return PermissionEngine(config)


def _deny_engine(pattern: str) -> PermissionEngine:
    config = PermissionConfig(rules=[
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="*"),
            identity=IdentityPattern(match="any", value="*"),
            permissions="r-x", effect="allow", priority=100,
        ),
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern=pattern),
            identity=IdentityPattern(match="any", value="*"),
            permissions="--x", effect="deny", priority=5,
        ),
    ])
    return PermissionEngine(config)


def _escalate_engine(pattern: str) -> PermissionEngine:
    config = PermissionConfig(rules=[PermissionRule(
        resource=ResourcePattern(type=ResourceType.TOOL, pattern=pattern),
        identity=IdentityPattern(match="any", value="*"),
        permissions="--x", effect="escalate", priority=10,
    )])
    return PermissionEngine(config)


@pytest.mark.asyncio
async def test_allowed_tool_completes(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "add", {"a": 1, "b": 2}),
        _text("3"),
    ])
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    identity = Identity(id="user:carl", name="carl", type=IdentityType.USER)
    loop = AgentLoop(model=mock_model, tools=registry, permission=_allow_engine(), identity=identity)
    result = await loop.run("add 1+2")
    assert result.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_denied_tool_returns_error_result_and_continues(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "deploy_prod", {"version": "1.2.3"}),
        _text("cannot deploy, permission denied"),
    ])
    registry = ToolRegistry()
    registry.register("deploy_prod", lambda version: "deployed", description="Deploy")
    identity = Identity(id="agent:bot", name="bot", type=IdentityType.AGENT)
    loop = AgentLoop(model=mock_model, tools=registry, permission=_deny_engine("deploy_prod"), identity=identity)
    result = await loop.run("deploy 1.2.3")
    assert result.status == RunStatus.COMPLETED
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert any("Permission denied" in str(m.content) for m in tool_msgs)


@pytest.mark.asyncio
async def test_escalate_pauses_run(mock_model):
    mock_model.invoke = AsyncMock(return_value=_tool_resp("c1", "deploy_prod", {"version": "1.2.3"}))
    registry = ToolRegistry()
    registry.register("deploy_prod", lambda version: "deployed", description="Deploy")
    identity = Identity(id="agent:bot", name="bot", type=IdentityType.AGENT)
    checkpointer = InMemoryCheckpoints()
    loop = AgentLoop(
        model=mock_model, tools=registry,
        permission=_escalate_engine("deploy_prod"), identity=identity,
        checkpointer=checkpointer,
    )
    result = await loop.run("deploy 1.2.3", thread_id=ThreadId("t_esc"))
    assert result.status == RunStatus.PAUSED
    assert result.checkpoint_id is not None


@pytest.mark.asyncio
async def test_resume_after_escalate_completes(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "deploy_prod", {"version": "1.2.3"}),
        _tool_resp("c2", "deploy_prod", {"version": "1.2.3"}),
        _text("deployed successfully"),
    ])
    registry = ToolRegistry()
    registry.register("deploy_prod", lambda version: f"deployed {version}", description="Deploy")
    identity = Identity(id="agent:bot", name="bot", type=IdentityType.AGENT)
    checkpointer = InMemoryCheckpoints()
    loop = AgentLoop(
        model=mock_model, tools=registry,
        permission=_escalate_engine("deploy_prod"), identity=identity,
        checkpointer=checkpointer,
    )
    tid = ThreadId("t_resume")
    result = await loop.run("deploy 1.2.3", thread_id=tid)
    assert result.status == RunStatus.PAUSED
    loop._permission = _allow_engine()
    result2 = await loop.resume(thread_id=tid, input={"approved": True})
    assert result2.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_loop_without_permission_still_works(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "add", {"a": 1, "b": 2}),
        _text("3"),
    ])
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    loop = AgentLoop(model=mock_model, tools=registry)
    result = await loop.run("add 1+2")
    assert result.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_permission_check_event_emitted(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "add", {"a": 1, "b": 2}),
        _text("3"),
    ])
    from mori.observability.engine import ObservabilityEngine
    from mori.observability.events import ObservabilityConfig
    collected = []

    class Sink:
        realtime = True

        async def write(self, e): collected.append(e)

        async def write_batch(self, es): collected.extend(es)

        async def flush(self): pass

        async def close(self): pass

    obs = ObservabilityEngine(sinks=[Sink()], config=ObservabilityConfig(buffer_size=100))
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    identity = Identity(id="user:carl", name="carl", type=IdentityType.USER)
    loop = AgentLoop(model=mock_model, tools=registry, observability=obs, permission=_allow_engine(), identity=identity)
    await loop.run("add 1+2")
    await obs.flush()
    event_types = [e.event_type for e in collected]
    assert "permission.check" in event_types
