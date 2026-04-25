"""AgentLoop — the core agent execution loop."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from pydantic import Field

from mori.model.base import ModelAdapter
from mori.runtime.result import RunResult
from mori.runtime.state import MoriState
from mori.tools.registry import ToolRegistry
from mori.types import (
    Message,
    ModelRequest,
    MoriModel,
    RunId,
    RunStatus,
    StepOutcome,
    ThreadId,
    ToolCall,
)


def _ulid_like() -> str:
    """Generate a simple unique-ish ID. Not a real ULID — good enough for v0.1."""
    import secrets

    return secrets.token_hex(12)


class LoopConfig(MoriModel):
    max_steps: int = 50
    max_total_tokens: int = 2_000_000
    step_timeout_sec: float = 120.0
    run_timeout_sec: float = 3600.0


class AgentLoop:
    """Minimal agent loop: plan → act → evaluate."""

    def __init__(
        self,
        model: ModelAdapter,
        tools: ToolRegistry,
        config: LoopConfig | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._config = config or LoopConfig()

    def _init_state(
        self,
        task: str,
        thread_id: ThreadId | None = None,
        context: dict[str, Any] | None = None,
    ) -> MoriState:
        now = datetime.now(timezone.utc)
        return MoriState(
            run_id=RunId(f"run_{_ulid_like()}"),
            thread_id=thread_id or ThreadId(f"thread_{_ulid_like()}"),
            task=task,
            context=context or {},
            messages=[Message(role="user", content=task)],
            status=RunStatus.RUNNING,
            started_at=now,
            last_progress_at=now,
        )

    def _assemble_request(self, state: MoriState) -> ModelRequest:
        """Build a ModelRequest from current state."""
        tool_specs = self._tools.list_specs()
        return ModelRequest(
            messages=state.messages,
            tools=tool_specs if tool_specs else None,
        )

    async def _phase_plan(self, state: MoriState) -> None:
        """Call the model with the current conversation + tool schemas."""
        request = self._assemble_request(state)
        response = await self._model.invoke(request)

        state.messages.append(response.message)
        state.total_input_tokens += response.usage.input_tokens
        state.total_output_tokens += response.usage.output_tokens

    async def _phase_act(self, state: MoriState) -> None:
        """Execute any tool calls from the latest assistant message."""
        last_msg = state.messages[-1]
        if not last_msg.tool_calls:
            return

        for call in last_msg.tool_calls:
            result = await self._tools.invoke(call.name, call.arguments)

            content = result.content if result.success else f"ERROR: {result.error}"
            state.messages.append(
                Message(
                    role="tool",
                    content=content,
                    tool_call_id=call.id,
                )
            )
            state.total_tool_calls += 1

    def _phase_evaluate(self, state: MoriState) -> StepOutcome:
        """Decide whether to continue, complete, or fail."""
        last_msg = state.messages[-1]

        # If last message is from tool, we need another model call
        if last_msg.role == "tool":
            return StepOutcome.RETRY

        # If assistant message has no tool calls, it's a final answer
        if last_msg.role == "assistant" and not last_msg.tool_calls:
            return StepOutcome.SUCCESS

        # If assistant message has tool calls, we already handled them above
        # so this shouldn't normally be reached, but just in case:
        return StepOutcome.RETRY

    def _should_terminate(self, state: MoriState, outcome: StepOutcome) -> bool:
        """Check if the loop should stop."""
        if outcome == StepOutcome.SUCCESS:
            state.status = RunStatus.COMPLETED
            return True

        if state.step_count >= self._config.max_steps:
            state.status = RunStatus.FAILED
            return True

        total_tokens = state.total_input_tokens + state.total_output_tokens
        if total_tokens >= self._config.max_total_tokens:
            state.status = RunStatus.FAILED
            return True

        return False

    async def run(
        self,
        task: str,
        thread_id: ThreadId | None = None,
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        """Execute the agent loop until completion or termination."""
        state = self._init_state(task, thread_id, context)
        start_time = time.monotonic()

        while state.status == RunStatus.RUNNING:
            state.step_count += 1

            # Plan: call the model
            await self._phase_plan(state)

            # Act: execute tool calls (if any)
            await self._phase_act(state)

            # Evaluate: should we continue?
            outcome = self._phase_evaluate(state)

            if self._should_terminate(state, outcome):
                break

            state.last_progress_at = datetime.now(timezone.utc)

        elapsed_ms = (time.monotonic() - start_time) * 1000
        return RunResult.from_state(state, duration_ms=elapsed_ms)
