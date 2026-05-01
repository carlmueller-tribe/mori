"""Event taxonomy, sink protocol, and trace context for Mori observability."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from mori.budget.types import BudgetSlot, StageResult
from mori.types import (
    DisclosureLevel,
    MemoryLayer,
    MoriModel,
    Phase,
    RunId,
    RunStatus,
    StepId,
    StepOutcome,
    ToolSource,
    TraceId,
)


# ── Base Event ───────────────────────────────────────────────

class MoriEvent(MoriModel):
    event_id: str
    event_type: str
    timestamp: datetime
    run_id: RunId
    step_id: StepId | None = None
    trace_id: TraceId | None = None
    span_id: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Loop Events ──────────────────────────────────────────────

class RunStartEvent(MoriEvent):
    event_type: str = "run.start"
    task: str
    config: dict[str, Any] = Field(default_factory=dict)


class RunEndEvent(MoriEvent):
    event_type: str = "run.end"
    status: RunStatus
    total_steps: int
    total_input_tokens: int
    total_output_tokens: int
    duration_ms: float


class StepStartEvent(MoriEvent):
    event_type: str = "step.start"
    step_number: int
    phase: Phase


class StepEndEvent(MoriEvent):
    event_type: str = "step.end"
    step_number: int
    outcome: StepOutcome
    input_tokens: int
    output_tokens: int
    duration_ms: float
    phase_timings: dict[str, float] = Field(default_factory=dict)


# ── Tool Events ──────────────────────────────────────────────

class ToolInvokeEvent(MoriEvent):
    event_type: str = "tool.invoke"
    tool_name: str
    source: ToolSource
    server_id: str | None = None
    arguments: dict[str, Any] | None = None


class ToolResultEvent(MoriEvent):
    event_type: str = "tool.result"
    tool_name: str
    success: bool
    latency_ms: float
    error: str | None = None
    result_preview: str | None = None


# ── Control Events ───────────────────────────────────────────

class BoundViolationEvent(MoriEvent):
    event_type: str = "control.bound_violation"
    bound_name: str
    current_value: float
    limit_value: float


# ── Memory Events ────────────────────────────────────────────

class MemoryReadEvent(MoriEvent):
    event_type: str = "memory.read"
    query: str
    layers: list[MemoryLayer]
    records_returned: int
    tokens_consumed: int
    duration_ms: float

class MemoryWriteEvent(MoriEvent):
    event_type: str = "memory.write"
    layer: MemoryLayer
    record_ids: list[str]
    records_written: int


# ── Skills Events ────────────────────────────────────────────

class SkillDiscoverEvent(MoriEvent):
    event_type: str = "skill.discover"
    task_preview: str
    candidates_found: int
    top_match_name: str | None = None
    top_match_score: float | None = None
    duration_ms: float


class SkillLoadEvent(MoriEvent):
    event_type: str = "skill.load"
    skill_id: str
    disclosure_level: DisclosureLevel
    token_estimate: int
    duration_ms: float


# ── Budget Events ────────────────────────────────────────────

class BudgetRebalanceEvent(MoriEvent):
    event_type: str = "budget.rebalance"
    phase: str
    allocations: dict[BudgetSlot, int]
    total_consumed: int
    utilization: float


class CompactionEvent(MoriEvent):
    event_type: str = "budget.compaction"
    stages_run: list[StageResult]
    total_tokens_reclaimed: int
    final_utilization: float


# ── Permission Events ────────────────────────────────────────

class PermissionCheckEvent(MoriEvent):
    event_type: str = "permission.check"
    identity_id: str
    resource_id: str
    permission: str       # "r", "w", or "x"
    decision: str         # "allow", "deny", or "escalate"
    rule_id: str | None = None
    explanation: str = ""


# ── Trace Context ────────────────────────────────────────────

class SpanContext(MoriModel):
    trace_id: TraceId
    span_id: str
    parent_span_id: str | None = None
    name: str
    start_time: datetime
    end_time: datetime | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds() * 1000


# ── Sink Protocol ────────────────────────────────────────────

@runtime_checkable
class EventSink(Protocol):
    async def write(self, event: MoriEvent) -> None: ...
    async def write_batch(self, events: list[MoriEvent]) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...


# ── Config ───────────────────────────────────────────────────

class ObservabilityConfig(MoriModel):
    buffer_size: int = 100
    flush_interval_sec: float = 5.0
    include_model_io: bool = False
    include_tool_args: bool = True
    include_tool_results: bool = True
    max_content_length: int = 10_000
    enabled_event_types: list[str] | None = None


# ── Run Summary ──────────────────────────────────────────────

class RunSummary(MoriModel):
    run_id: RunId
    status: RunStatus
    total_steps: int
    total_input_tokens: int
    total_output_tokens: int
    total_tool_calls: int
    total_tool_failures: int
    total_duration_ms: float
    avg_step_duration_ms: float
    tools_used: list[str] = Field(default_factory=list)
    error_summary: list[str] = Field(default_factory=list)
