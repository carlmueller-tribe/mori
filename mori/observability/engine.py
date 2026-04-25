"""ObservabilityEngine — buffered event dispatch with trace context."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from mori.observability.events import (
    EventSink,
    MoriEvent,
    ObservabilityConfig,
    RunEndEvent,
    RunSummary,
    SpanContext,
    ToolResultEvent,
)
from mori.types import RunId, RunStatus, TraceId


class ObservabilityEngine:
    """Buffered event dispatch to pluggable sinks."""

    def __init__(self, sinks: list[Any], config: ObservabilityConfig | None = None) -> None:
        self._sinks = sinks
        self._config = config or ObservabilityConfig()
        self._buffer: list[MoriEvent] = []
        self._all_events: list[MoriEvent] = []

    async def emit(self, event: MoriEvent) -> None:
        if self._config.enabled_event_types is not None:
            if event.event_type not in self._config.enabled_event_types:
                return
        self._buffer.append(event)
        self._all_events.append(event)
        if len(self._buffer) >= self._config.buffer_size:
            await self._flush_buffer()

    async def emit_batch(self, events: list[MoriEvent]) -> None:
        for event in events:
            await self.emit(event)

    def start_trace(self, run_id: RunId) -> TraceId:
        return TraceId(f"trace_{secrets.token_hex(12)}")

    def start_span(self, trace_id: TraceId, name: str, parent_span_id: str | None = None) -> SpanContext:
        return SpanContext(
            trace_id=trace_id, span_id=f"span_{secrets.token_hex(8)}",
            parent_span_id=parent_span_id, name=name,
            start_time=datetime.now(timezone.utc),
        )

    def end_span(self, span: SpanContext) -> None:
        span.end_time = datetime.now(timezone.utc)

    def get_run_summary(self, run_id: RunId) -> RunSummary:
        run_events = [e for e in self._all_events if e.run_id == run_id]
        status = RunStatus.RUNNING
        total_steps = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_tool_calls = 0
        total_tool_failures = 0
        total_duration_ms = 0.0
        tools_used: set[str] = set()
        errors: list[str] = []

        for event in run_events:
            if isinstance(event, RunEndEvent):
                status = event.status
                total_steps = event.total_steps
                total_input_tokens = event.total_input_tokens
                total_output_tokens = event.total_output_tokens
                total_duration_ms = event.duration_ms
            elif isinstance(event, ToolResultEvent):
                total_tool_calls += 1
                tools_used.add(event.tool_name)
                if not event.success:
                    total_tool_failures += 1
                    if event.error:
                        errors.append(event.error)

        avg_step_ms = total_duration_ms / total_steps if total_steps > 0 else 0.0
        return RunSummary(
            run_id=run_id, status=status, total_steps=total_steps,
            total_input_tokens=total_input_tokens, total_output_tokens=total_output_tokens,
            total_tool_calls=total_tool_calls, total_tool_failures=total_tool_failures,
            total_duration_ms=total_duration_ms, avg_step_duration_ms=avg_step_ms,
            tools_used=sorted(tools_used), error_summary=errors,
        )

    async def flush(self) -> None:
        await self._flush_buffer()
        for sink in self._sinks:
            await sink.flush()

    async def close(self) -> None:
        await self._flush_buffer()
        for sink in self._sinks:
            await sink.flush()
            await sink.close()

    async def _flush_buffer(self) -> None:
        if not self._buffer:
            return
        events = list(self._buffer)
        self._buffer.clear()
        for sink in self._sinks:
            await sink.write_batch(events)
