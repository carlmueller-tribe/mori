"""End-to-end integration tests for Active Hooks v0.7."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from mori.hooks.events import HookEvents, TurnEndReason
from mori.hooks.exceptions import HookBlock
from mori.hooks.registry import HookRegistry
from mori.model.base import ModelAdapter
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import Message, ModelResponse, RunStatus, TokenUsage


def _text(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


@pytest.fixture
def mock_model():
    model = AsyncMock(spec=ModelAdapter)
    model.model_id = "test"
    model.supports_tool_use = True
    model.max_context_tokens = 100000
    return model


@pytest.mark.asyncio
async def test_turn_start_block_yields_blocked_result(mock_model) -> None:
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()

    async def blocker(payload: Any) -> None:
        raise HookBlock("forbidden task", hook_id="my_hook")

    hooks.register(HookEvents.TURN_START, blocker)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    result = await loop.run("anything")
    assert result.status == RunStatus.BLOCKED
    assert result.block_reason == "forbidden task"
    assert result.block_hook_id is not None


@pytest.mark.asyncio
async def test_turn_start_block_does_not_invoke_model(mock_model) -> None:
    """When turn.start blocks, the model is never invoked."""
    mock_model.invoke = AsyncMock(return_value=_text("should not run"))
    hooks = HookRegistry()

    async def blocker(payload: Any) -> None:
        raise HookBlock("nope")

    hooks.register(HookEvents.TURN_START, blocker)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("anything")
    mock_model.invoke.assert_not_called()


@pytest.mark.asyncio
async def test_turn_start_block_fires_turn_end_with_blocked_reason(mock_model) -> None:
    """turn.end still fires (with reason=BLOCKED) when turn.start blocks."""
    from mori.hooks.events import TurnEndReason

    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()
    end_payloads: list[Any] = []

    async def blocker(payload: Any) -> None:
        raise HookBlock("nope")

    async def capture_end(payload: Any) -> None:
        end_payloads.append(payload)
        return None

    hooks.register(HookEvents.TURN_START, blocker)
    hooks.register(HookEvents.TURN_END, capture_end)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("anything")
    assert len(end_payloads) == 1
    assert end_payloads[0].reason == TurnEndReason.BLOCKED


@pytest.mark.asyncio
async def test_tool_invoke_block_appends_synthetic_message(mock_model) -> None:
    """When a tool.invoke.before hook blocks, the tool call gets a synthetic
    blocked result message and the loop continues (no actual tool invocation)."""
    from mori.types import ToolCall

    # First model response: assistant requests apply_migration with env=prod
    first_response = ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="apply_migration", arguments={"env": "prod"})],
        ),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="tool_use",
    )
    # Second response: assistant declares done (no tool calls → loop exits)
    second_response = _text("done")
    mock_model.invoke = AsyncMock(side_effect=[first_response, second_response])

    registry = ToolRegistry()
    invoked = []

    def apply_migration(env: str) -> str:
        invoked.append(env)
        return "applied"

    registry.register("apply_migration", apply_migration, description="apply a migration")

    hooks = HookRegistry()

    async def block_prod(call: Any) -> None:
        if call.arguments.get("env") == "prod":
            raise HookBlock("no prod tools", hook_id="prod_gate")
        return None

    hooks.register(HookEvents.TOOL_INVOKE_BEFORE, block_prod)

    loop = AgentLoop(model=mock_model, tools=registry, hooks=hooks)
    result = await loop.run("do the thing")

    # The tool was NOT actually invoked
    assert invoked == []

    # A synthetic blocked message appears in the conversation
    blocked_msgs = [
        m
        for m in result.messages
        if m.role == "tool" and isinstance(m.content, str) and "BLOCKED" in m.content
    ]
    assert len(blocked_msgs) == 1
    assert "no prod tools" in blocked_msgs[0].content
    assert "prod_gate" in blocked_msgs[0].content
    assert blocked_msgs[0].tool_call_id == "c1"

    # Status is NOT BLOCKED — the run continued
    assert result.status != RunStatus.BLOCKED


@pytest.mark.asyncio
async def test_model_request_block_returns_blocked_result(mock_model) -> None:
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()

    async def blocker(req: Any) -> None:
        raise HookBlock("request gate", hook_id="req_gate")

    hooks.register(HookEvents.MODEL_REQUEST_BEFORE, blocker)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    result = await loop.run("anything")
    assert result.status == RunStatus.BLOCKED
    assert result.block_reason == "request gate"
    assert result.block_hook_id == "req_gate"


@pytest.mark.asyncio
async def test_model_request_retry_appends_feedback_and_retries(mock_model) -> None:
    """First call to model.request.before hook raises HookRetry; second call passes through."""
    from mori.hooks.exceptions import HookRetry

    mock_model.invoke = AsyncMock(return_value=_text("hello"))

    call_count = 0
    hooks = HookRegistry()

    async def retry_once(req: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise HookRetry("think harder", hook_id="r")
        return None

    hooks.register(HookEvents.MODEL_REQUEST_BEFORE, retry_once)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    result = await loop.run("hello")

    # The feedback should appear as a system message in the state
    system_msgs = [
        m for m in result.messages if m.role == "system" and "think harder" in (m.content or "")
    ]
    assert len(system_msgs) >= 1
    assert result.status != RunStatus.BLOCKED
    # The hook ran twice (once retry, once allowed)
    assert call_count == 2
    # The model was invoked exactly once (after the retry passed)
    assert mock_model.invoke.call_count == 1


@pytest.mark.asyncio
async def test_turn_end_retry_continues_loop(mock_model) -> None:
    """First completion raises HookRetry; the loop continues for another iteration."""
    from mori.hooks.exceptions import HookRetry

    # Both model responses are no-tool-call (loop wants to complete after each)
    mock_model.invoke = AsyncMock(side_effect=[_text("first"), _text("second")])

    call_count = 0
    hooks = HookRegistry()

    async def retry_once(payload: Any) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise HookRetry("not done yet", hook_id="finisher")
        return None

    hooks.register(HookEvents.TURN_END, retry_once)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    result = await loop.run("hi")

    # turn.end was dispatched twice: once retried, once allowed
    assert call_count == 2
    # The "not done yet" feedback appears as a system message
    feedback_msgs = [
        m for m in result.messages if m.role == "system" and "not done yet" in (m.content or "")
    ]
    assert len(feedback_msgs) >= 1
    # The model was invoked twice (once per iteration)
    assert mock_model.invoke.call_count == 2


@pytest.mark.asyncio
async def test_turn_end_retry_bounded_by_max_retry_limit(mock_model) -> None:
    """If turn.end keeps raising HookRetry, exhaustion sets FAILED."""
    from mori.hooks.exceptions import HookRetry
    from mori.hooks.types import HookConfig

    # Mock returns a no-tool-call response on every invocation (always wants to end)
    mock_model.invoke = AsyncMock(return_value=_text("done"))

    hooks = HookRegistry(config=HookConfig(max_retry_limit=2))

    async def always_retry(payload: Any) -> None:
        raise HookRetry("never done", hook_id="r")

    hooks.register(HookEvents.TURN_END, always_retry)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    result = await loop.run("hi")

    # On exhaustion, status is FAILED (NOT BLOCKED)
    assert result.status == RunStatus.FAILED


@pytest.mark.asyncio
async def test_e2e_chat_loop() -> None:
    """Full chat-loop integration: agent calls ask_user, yields, caller
    resumes with a response, agent completes."""
    from mori.control.checkpoint import InMemoryCheckpoints
    from mori.tools.native.ask_user import ask_user
    from mori.types import ToolCall

    ask_response = ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="ask_user", arguments={"question": "which db?"})],
        ),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="tool_use",
    )
    done_response = _text("done")

    mock = AsyncMock(spec=ModelAdapter)
    mock.model_id = "test"
    mock.supports_tool_use = True
    mock.max_context_tokens = 100000
    mock.invoke = AsyncMock(side_effect=[ask_response, done_response])

    tools = ToolRegistry()
    tools.register("ask_user", ask_user, description="ask the user")
    checkpointer = InMemoryCheckpoints()
    loop = AgentLoop(model=mock, tools=tools, checkpointer=checkpointer)

    paused = await loop.run("migrate the user table")
    assert paused.status == RunStatus.PAUSED
    assert paused.paused_prompt == "which db?"

    final = await loop.resume(paused.thread_id, "production_db")
    assert final.status == RunStatus.COMPLETED
    assert any(m.role == "tool" and m.content == "production_db" for m in final.messages)


@pytest.mark.asyncio
async def test_turn_end_hook_block_is_logged_not_propagated(mock_model) -> None:
    """HookBlock raised on turn.end (which uses dispatch_before) must NOT
    propagate; turn.end can't actually block a run that's already ending."""
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()

    async def block_at_end(payload: Any) -> None:
        raise HookBlock("late block", hook_id="late")

    hooks.register(HookEvents.TURN_END, block_at_end)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    # Must NOT raise
    result = await loop.run("hi")
    # Run completed normally; turn.end's HookBlock was swallowed
    assert result.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_fire_turn_end_swallows_retry_on_early_exit_path(mock_model) -> None:
    """When turn.start blocks AND a turn.end hook raises HookRetry,
    the HookRetry from turn.end must not propagate to the caller."""
    from mori.hooks.exceptions import HookRetry

    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()

    async def block_at_start(payload: Any) -> None:
        raise HookBlock("forbid", hook_id="gate")

    async def retry_at_end(payload: Any) -> None:
        raise HookRetry("retry me", hook_id="r")

    hooks.register(HookEvents.TURN_START, block_at_start)
    hooks.register(HookEvents.TURN_END, retry_at_end)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    # Must NOT raise — HookRetry from turn.end during early-exit is swallowed
    result = await loop.run("anything")
    # Run is BLOCKED (because turn.start blocked), not affected by the swallowed retry
    assert result.status == RunStatus.BLOCKED


@pytest.mark.asyncio
async def test_unhandled_exception_in_phase_still_fires_turn_end(mock_model) -> None:
    """If a phase raises an unhandled exception, turn.end still fires
    (with a FAILED reason) so observers see the run's closing boundary."""
    mock_model.invoke = AsyncMock(side_effect=RuntimeError("boom"))
    hooks = HookRegistry()
    fired: list[Any] = []

    async def capture_end(payload: Any) -> None:
        fired.append(payload)
        return None

    hooks.register(HookEvents.TURN_END, capture_end)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    result = await loop.run("hi")

    assert len(fired) == 1
    assert fired[0].reason == TurnEndReason.ERRORED
    assert result.status == RunStatus.FAILED
