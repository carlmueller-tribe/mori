"""AgentLoop — the core agent execution loop."""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from mori.model.base import ModelAdapter
from mori.runtime.result import RunResult
from mori.runtime.state import MoriState
from mori.tools.registry import ToolRegistry
from mori.types import (
    Message,
    ModelRequest,
    Phase,
    RunId,
    RunStatus,
    StepId,
    StepOutcome,
    ThreadId,
)

if TYPE_CHECKING:
    from mori.control.bounds import ControlBounds
    from mori.observability.engine import ObservabilityEngine
    from mori.observability.events import MoriEvent


def _uid() -> str:
    return secrets.token_hex(12)


class AgentLoop:
    """Agent loop: plan -> act -> evaluate, with observability and control bounds."""

    def __init__(
        self,
        model: ModelAdapter,
        tools: ToolRegistry,
        observability: ObservabilityEngine | None = None,
        control: ControlBounds | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._obs = observability
        if control is None:
            from mori.control.bounds import ControlBounds, ControlConfig
            control = ControlBounds(config=ControlConfig())
        self._control = control

    async def _emit(self, event: MoriEvent) -> None:
        if self._obs:
            await self._obs.emit(event)

    def _init_state(self, task: str, thread_id: ThreadId | None = None, context: dict[str, Any] | None = None) -> MoriState:
        now = datetime.now(timezone.utc)
        return MoriState(
            run_id=RunId(f"run_{_uid()}"),
            thread_id=thread_id or ThreadId(f"thread_{_uid()}"),
            task=task, context=context or {},
            messages=[Message(role="user", content=task)],
            status=RunStatus.RUNNING, started_at=now, last_progress_at=now,
        )

    def _assemble_request(self, state: MoriState) -> ModelRequest:
        tool_specs = self._tools.list_specs()
        return ModelRequest(messages=state.messages, tools=tool_specs if tool_specs else None)

    async def _phase_plan(self, state: MoriState) -> None:
        request = self._assemble_request(state)
        response = await self._model.invoke(request)
        state.messages.append(response.message)
        state.total_input_tokens += response.usage.input_tokens
        state.total_output_tokens += response.usage.output_tokens

    async def _phase_act(self, state: MoriState) -> None:
        last_msg = state.messages[-1]
        if not last_msg.tool_calls:
            return

        from mori.observability.events import ToolInvokeEvent, ToolResultEvent

        for call in last_msg.tool_calls:
            spec = self._tools.get_spec(call.name)
            source = spec.source if spec else "native"

            await self._emit(ToolInvokeEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id, tool_name=call.name, source=source,
                arguments=call.arguments,
            ))

            result = await self._tools.invoke(call.name, call.arguments)

            await self._emit(ToolResultEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id, tool_name=call.name, success=result.success,
                latency_ms=result.latency_ms, error=result.error,
                result_preview=str(result.content)[:200] if result.content else None,
            ))

            content = result.content if result.success else f"ERROR: {result.error}"
            state.messages.append(Message(role="tool", content=content, tool_call_id=call.id))
            state.total_tool_calls += 1

    def _phase_evaluate(self, state: MoriState) -> StepOutcome:
        last_msg = state.messages[-1]
        if last_msg.role == "tool":
            return StepOutcome.RETRY
        if last_msg.role == "assistant" and not last_msg.tool_calls:
            return StepOutcome.SUCCESS
        return StepOutcome.RETRY

    async def run(self, task: str, thread_id: ThreadId | None = None, context: dict[str, Any] | None = None) -> RunResult:
        from mori.observability.events import (
            BoundViolationEvent,
            RunEndEvent,
            RunStartEvent,
            StepEndEvent,
            StepStartEvent,
        )

        state = self._init_state(task, thread_id, context)
        start_time = time.monotonic()

        await self._emit(RunStartEvent(
            event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
            run_id=state.run_id, task=task,
            config={"max_steps": self._control._config.max_steps},
        ))

        while state.status == RunStatus.RUNNING:
            state.step_count += 1
            step_start = time.monotonic()
            step_id = StepId(f"step_{state.run_id}_{state.step_count:04d}")

            # Check bounds before executing
            bound_check = self._control.check_bounds(state)
            if not bound_check.ok:
                for bound in bound_check.violated_bounds:
                    await self._emit(BoundViolationEvent(
                        event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                        run_id=state.run_id, bound_name=bound,
                        current_value=bound_check.current_values.get("step_count", 0),
                        limit_value=float(getattr(self._control._config, bound, 0)),
                    ))
                state.status = RunStatus.FAILED
                break

            await self._emit(StepStartEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id, step_id=step_id, step_number=state.step_count, phase=Phase.PLAN,
            ))

            await self._phase_plan(state)
            await self._phase_act(state)
            outcome = self._phase_evaluate(state)

            step_elapsed = (time.monotonic() - step_start) * 1000
            await self._emit(StepEndEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id, step_id=step_id, step_number=state.step_count,
                outcome=outcome, input_tokens=0, output_tokens=0, duration_ms=step_elapsed,
            ))

            if outcome == StepOutcome.SUCCESS:
                state.status = RunStatus.COMPLETED
                break

            self._control.record_progress()
            state.last_progress_at = datetime.now(timezone.utc)

        elapsed_ms = (time.monotonic() - start_time) * 1000

        await self._emit(RunEndEvent(
            event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
            run_id=state.run_id, status=state.status, total_steps=state.step_count,
            total_input_tokens=state.total_input_tokens, total_output_tokens=state.total_output_tokens,
            duration_ms=elapsed_ms,
        ))

        if self._obs:
            await self._obs.flush()

        return RunResult.from_state(state, duration_ms=elapsed_ms)
