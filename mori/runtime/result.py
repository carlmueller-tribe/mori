"""RunResult and StepResult — outputs from the agent loop."""

from __future__ import annotations

from pydantic import Field

from mori.runtime.state import MoriState
from mori.types import (
    CheckpointId,
    Message,
    ModelResponse,
    MoriModel,
    RunId,
    RunStatus,
    StepId,
    StepOutcome,
    ThreadId,
    TokenUsage,
    ToolResult,
)


class StepResult(MoriModel):
    step_id: StepId
    step_number: int
    outcome: StepOutcome
    response: ModelResponse | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    usage: TokenUsage
    duration_ms: float


class RunResult(MoriModel):
    run_id: RunId
    thread_id: ThreadId
    status: RunStatus
    task: str
    final_output: str | None = None
    messages: list[Message] = Field(default_factory=list)
    total_steps: int = 0
    total_usage: TokenUsage = TokenUsage(input_tokens=0, output_tokens=0)
    total_tool_calls: int = 0
    total_duration_ms: float = 0.0
    checkpoint_id: CheckpointId | None = None
    block_reason: str | None = None
    block_hook_id: str | None = None
    paused_prompt: str | None = None

    @staticmethod
    def from_state(
        state: MoriState, duration_ms: float, checkpoint_id: CheckpointId | None = None
    ) -> RunResult:  # noqa: E501
        """Build a RunResult from the final MoriState."""
        final_output: str | None = None
        for msg in reversed(state.messages):
            if msg.role == "assistant" and isinstance(msg.content, str) and msg.content:
                final_output = msg.content
                break

        return RunResult(
            run_id=state.run_id,
            thread_id=state.thread_id,
            status=state.status,
            task=state.task,
            final_output=final_output,
            messages=state.messages,
            total_steps=state.step_count,
            total_usage=TokenUsage(
                input_tokens=state.total_input_tokens,
                output_tokens=state.total_output_tokens,
            ),
            total_tool_calls=state.total_tool_calls,
            total_duration_ms=duration_ms,
            checkpoint_id=checkpoint_id,
            paused_prompt=state.paused_prompt,
        )
