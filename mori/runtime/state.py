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

    # Counters
    step_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0

    # Timing
    started_at: datetime
    last_progress_at: datetime
