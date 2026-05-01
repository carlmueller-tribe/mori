# 08: Observability Engine

**Status:** Draft v3
**Module:** `mori.observability`
**Dependencies:** Spec 01

---

## 1. Purpose

Make every decision inspectable without requiring a paid service. Mori produces structured events at every phase boundary and dispatches them to pluggable sinks.

## 2. Interface

```python
class ObservabilityEngine:

    def __init__(self, sinks: list[EventSink], config: ObservabilityConfig) -> None: ...

    # Event emission
    async def emit(self, event: MoriEvent) -> None: ...
    async def emit_batch(self, events: list[MoriEvent]) -> None: ...

    # Trace context
    def start_trace(self, run_id: RunId) -> TraceId: ...
    def start_span(self, trace_id: TraceId, name: str, parent_span_id: str | None = None) -> SpanContext: ...
    def end_span(self, span: SpanContext) -> None: ...

    # Aggregates
    def get_run_summary(self, run_id: RunId) -> RunSummary: ...

    # Lifecycle
    async def flush(self) -> None: ...
    async def close(self) -> None: ...
```

## 3. Configuration

```python
class ObservabilityConfig(MoriModel):
    buffer_size: int = 100
    flush_interval_sec: float = 5.0
    include_model_io: bool = False
    include_tool_args: bool = True
    include_tool_results: bool = True
    max_content_length: int = 10_000
    enabled_event_types: list[str] | None = None
```

## 4. Event Taxonomy

All events inherit from:

```python
class MoriEvent(MoriModel):
    event_id: str
    event_type: str
    timestamp: datetime
    run_id: RunId
    step_id: StepId | None = None
    trace_id: TraceId | None = None
    span_id: str | None = None
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
```

### 4.1 Loop Events

```python
class RunStartEvent(MoriEvent):
    event_type: str = "run.start"
    task: str
    config: dict

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
```

### 4.2 Memory Events

```python
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
```

### 4.3 Skill Events

```python
class SkillDiscoverEvent(MoriEvent):
    event_type: str = "skill.discover"
    query: str
    candidates_returned: int
    top_match: str | None = None
    top_score: float | None = None

class SkillLoadEvent(MoriEvent):
    event_type: str = "skill.load"
    skill_id: str
    disclosure_level: DisclosureLevel
    tokens_consumed: int

class SkillOutcomeEvent(MoriEvent):
    event_type: str = "skill.outcome"
    skill_id: str
    success: bool
    failure_reason: str | None = None
```

### 4.4 Tool Events

```python
class ToolInvokeEvent(MoriEvent):
    event_type: str = "tool.invoke"
    tool_name: str
    source: ToolSource
    server_id: str | None = None
    arguments: dict | None = None

class ToolResultEvent(MoriEvent):
    event_type: str = "tool.result"
    tool_name: str
    success: bool
    latency_ms: float
    error: str | None = None
    result_preview: str | None = None
```

### 4.5 Permission Events

```python
class PermissionCheckEvent(MoriEvent):
    event_type: str = "permission.check"
    identity: str
    resource_type: str
    resource_id: str
    permission_requested: str
    decision: PermissionDecision
    reason: str

class ApprovalRequestEvent(MoriEvent):
    event_type: str = "approval.request"
    action_description: str
    risk_level: str

class ApprovalResponseEvent(MoriEvent):
    event_type: str = "approval.response"
    approved: bool
    responder: str | None = None
    latency_ms: float
```

### 4.6 Control Events

```python
class BoundViolationEvent(MoriEvent):
    event_type: str = "control.bound_violation"
    bound_name: str
    current_value: float
    limit_value: float

class CheckpointEvent(MoriEvent):
    event_type: str = "control.checkpoint"
    checkpoint_id: str
    step_count: int
```

## 5. Span Context

```python
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
```

## 6. Event Sink Interface

```python
class EventSink(Protocol):
    async def write(self, event: MoriEvent) -> None: ...
    async def write_batch(self, events: list[MoriEvent]) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...
```

**Included sinks:**

| Sink         | Output               | Dependencies        |
|--------------|----------------------|---------------------|
| StdoutSink   | Formatted console    | None                |
| JsonlSink    | JSONL file           | None                |
| CallbackSink | Arbitrary callback   | None                |
| OtlpSink     | OpenTelemetry export | opentelemetry-*     |

## 7. Run Summary

```python
class RunSummary(MoriModel):
    run_id: RunId
    status: RunStatus
    total_steps: int
    total_input_tokens: int
    total_output_tokens: int
    total_tool_calls: int
    total_tool_failures: int
    total_permission_denials: int
    total_duration_ms: float
    avg_step_duration_ms: float
    skills_used: list[str]
    tools_used: list[str]
    error_summary: list[str]
```

## 8. AIUC-1 Contracts

Per `12-AIUC1-COMPLIANCE.md` Section 2.7:
- Every MoriEvent MUST support a `risk_flags: list[RiskFlag]` field
- Sinks MUST NOT silently drop events
- The engine MUST support flush-on-shutdown to prevent data loss
- The runtime MUST emit events at every phase boundary (no silent phases)

## 9. Test Criteria

- [ ] emit() dispatches to all registered sinks
- [ ] Events are buffered and flushed according to buffer_size and flush_interval
- [ ] Trace context correctly links parent and child spans
- [ ] Span duration is computed correctly
- [ ] include_model_io=False suppresses model I/O from events
- [ ] max_content_length truncates long content fields
- [ ] enabled_event_types filters events by type
- [ ] get_run_summary computes correct aggregates
- [ ] StdoutSink produces human-readable output
- [ ] JsonlSink produces valid JSONL with one event per line
- [ ] flush() drains the buffer completely
- [ ] close() flushes and releases resources for all sinks
- [ ] risk_flags field is present on all events
