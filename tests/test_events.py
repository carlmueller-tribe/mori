"""Tests for observability event types."""

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from mori.observability.events import (
    MoriEvent,
    RunStartEvent,
    RunEndEvent,
    StepStartEvent,
    StepEndEvent,
    ToolInvokeEvent,
    ToolResultEvent,
    BoundViolationEvent,
    SpanContext,
    EventSink,
    ObservabilityConfig,
    RunSummary,
)
from mori.types import RunId, RunStatus, StepId, StepOutcome, Phase, ToolSource, TraceId


def test_mori_event_base():
    e = MoriEvent(
        event_id="evt_1",
        event_type="test",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
    )
    assert e.event_type == "test"
    assert e.risk_flags == []
    assert e.metadata == {}
    assert e.step_id is None
    assert e.trace_id is None


def test_run_start_event():
    e = RunStartEvent(
        event_id="evt_1",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        task="test task",
        config={"max_steps": 50},
    )
    assert e.event_type == "run.start"
    assert e.task == "test task"


def test_run_end_event():
    e = RunEndEvent(
        event_id="evt_2",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        status=RunStatus.COMPLETED,
        total_steps=3,
        total_input_tokens=500,
        total_output_tokens=200,
        duration_ms=1500.0,
    )
    assert e.event_type == "run.end"
    assert e.status == RunStatus.COMPLETED


def test_step_start_event():
    e = StepStartEvent(
        event_id="evt_3",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        step_id=StepId("step_1"),
        step_number=1,
        phase=Phase.PLAN,
    )
    assert e.event_type == "step.start"
    assert e.step_number == 1


def test_step_end_event():
    e = StepEndEvent(
        event_id="evt_4",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        step_id=StepId("step_1"),
        step_number=1,
        outcome=StepOutcome.SUCCESS,
        input_tokens=100,
        output_tokens=50,
        duration_ms=300.0,
    )
    assert e.event_type == "step.end"
    assert e.phase_timings == {}


def test_tool_invoke_event():
    e = ToolInvokeEvent(
        event_id="evt_5",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        tool_name="add",
        source=ToolSource.NATIVE,
        arguments={"a": 1, "b": 2},
    )
    assert e.event_type == "tool.invoke"
    assert e.server_id is None


def test_tool_result_event():
    e = ToolResultEvent(
        event_id="evt_6",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        tool_name="add",
        success=True,
        latency_ms=5.0,
    )
    assert e.event_type == "tool.result"
    assert e.error is None


def test_bound_violation_event():
    e = BoundViolationEvent(
        event_id="evt_7",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        bound_name="max_steps",
        current_value=51.0,
        limit_value=50.0,
    )
    assert e.event_type == "control.bound_violation"


def test_span_context():
    s = SpanContext(
        trace_id=TraceId("trace_1"),
        span_id="span_1",
        name="plan_phase",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
    )
    assert s.duration_ms is not None
    assert abs(s.duration_ms - 1000.0) < 1.0


def test_span_context_no_end():
    s = SpanContext(
        trace_id=TraceId("trace_1"),
        span_id="span_1",
        name="ongoing",
        start_time=datetime.now(timezone.utc),
    )
    assert s.duration_ms is None


def test_event_json_roundtrip():
    e = ToolInvokeEvent(
        event_id="evt_1",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        tool_name="search",
        source=ToolSource.CLI,
        arguments={"pattern": "TODO"},
    )
    json_str = e.model_dump_json()
    restored = ToolInvokeEvent.model_validate_json(json_str)
    assert restored.tool_name == "search"
    assert restored.source == ToolSource.CLI


def test_event_sink_is_protocol():
    assert hasattr(EventSink, "__protocol_attrs__") or callable(getattr(EventSink, "_is_protocol", None)) or hasattr(EventSink, "_is_runtime_protocol")


def test_observability_config_defaults():
    c = ObservabilityConfig()
    assert c.buffer_size == 100
    assert c.flush_interval_sec == 5.0
    assert c.include_tool_args is True
    assert c.enabled_event_types is None


def test_run_summary():
    s = RunSummary(
        run_id=RunId("run_1"),
        status=RunStatus.COMPLETED,
        total_steps=3,
        total_input_tokens=500,
        total_output_tokens=200,
        total_tool_calls=2,
        total_tool_failures=0,
        total_duration_ms=1500.0,
        avg_step_duration_ms=500.0,
        tools_used=["add", "multiply"],
        error_summary=[],
    )
    assert s.total_tool_failures == 0
