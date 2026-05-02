"""MoriState — mutable state carried across the agent loop."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from mori.types import (
    MemorySlice,
    Message,
    MoriModel,
    RunId,
    RunStatus,
    ThreadId,
    ToolCall,
)


class MoriState(MoriModel):
    """Mutable state carried across the loop."""

    run_id: RunId
    thread_id: ThreadId
    task: str
    context: dict[str, Any] = Field(default_factory=dict)
    messages: list[Message] = Field(default_factory=list)
    status: RunStatus = RunStatus.RUNNING

    # Memory
    memory_slice: MemorySlice | None = None

    # Skills
    active_skill_payload: Any | None = None

    # Pause context (set when status == RunStatus.PAUSED after ESCALATE decision)
    paused_reason: str | None = None
    paused_tool_call: ToolCall | None = None

    # Counters
    step_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0

    # Timing
    started_at: datetime
    last_progress_at: datetime
