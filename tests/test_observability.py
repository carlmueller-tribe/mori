"""Tests for ObservabilityEngine — buffered event dispatch."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from mori.observability.engine import ObservabilityEngine
from mori.observability.events import (
    MoriEvent,
    ObservabilityConfig,
    RunStartEvent,
    RunEndEvent,
    ToolResultEvent,
)
from mori.types import RunId, RunStatus, TraceId


def _make_event(event_type: str = "test", **overrides) -> MoriEvent:
    defaults = {
        "event_id": "evt_1",
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc),
        "run_id": RunId("run_1"),
    }
    defaults.update(overrides)
    return MoriEvent(**defaults)


@pytest.fixture
def mock_sink():
    sink = AsyncMock()
    sink.write = AsyncMock()
    sink.write_batch = AsyncMock()
    sink.flush = AsyncMock()
    sink.close = AsyncMock()
    return sink


async def test_emit_dispatches_to_sink(mock_sink):
    engine = ObservabilityEngine(sinks=[mock_sink], config=ObservabilityConfig(buffer_size=1))
    await engine.emit(_make_event())
    await engine.flush()
    mock_sink.write_batch.assert_called()
    await engine.close()


async def test_emit_buffers_until_threshold(mock_sink):
    engine = ObservabilityEngine(
        sinks=[mock_sink],
        config=ObservabilityConfig(buffer_size=5, flush_interval_sec=999),
    )
    for i in range(3):
        await engine.emit(_make_event(event_id=f"evt_{i}"))
    mock_sink.write_batch.assert_not_called()

    for i in range(3, 5):
        await engine.emit(_make_event(event_id=f"evt_{i}"))
    mock_sink.write_batch.assert_called_once()
    events = mock_sink.write_batch.call_args[0][0]
    assert len(events) == 5
    await engine.close()


async def test_flush_drains_buffer(mock_sink):
    engine = ObservabilityEngine(sinks=[mock_sink], config=ObservabilityConfig(buffer_size=100))
    await engine.emit(_make_event())
    await engine.emit(_make_event())
    await engine.flush()
    mock_sink.write_batch.assert_called_once()
    events = mock_sink.write_batch.call_args[0][0]
    assert len(events) == 2
    await engine.close()


async def test_close_flushes_remaining(mock_sink):
    engine = ObservabilityEngine(sinks=[mock_sink], config=ObservabilityConfig(buffer_size=100))
    await engine.emit(_make_event())
    await engine.close()
    mock_sink.write_batch.assert_called_once()
    mock_sink.close.assert_called_once()


async def test_multiple_sinks():
    sink1 = AsyncMock()
    sink2 = AsyncMock()
    engine = ObservabilityEngine(sinks=[sink1, sink2], config=ObservabilityConfig(buffer_size=1))
    await engine.emit(_make_event())
    await engine.flush()
    sink1.write_batch.assert_called()
    sink2.write_batch.assert_called()
    await engine.close()


async def test_start_trace():
    engine = ObservabilityEngine(sinks=[], config=ObservabilityConfig())
    trace_id = engine.start_trace(RunId("run_1"))
    assert trace_id.startswith("trace_")
    await engine.close()


async def test_start_and_end_span():
    engine = ObservabilityEngine(sinks=[], config=ObservabilityConfig())
    trace_id = engine.start_trace(RunId("run_1"))
    span = engine.start_span(trace_id, "test_span")
    assert span.trace_id == trace_id
    assert span.end_time is None
    engine.end_span(span)
    assert span.end_time is not None
    assert span.duration_ms is not None
    assert span.duration_ms >= 0
    await engine.close()


async def test_enabled_event_types_filter(mock_sink):
    engine = ObservabilityEngine(
        sinks=[mock_sink],
        config=ObservabilityConfig(buffer_size=1, enabled_event_types=["run.start"]),
    )
    await engine.emit(RunStartEvent(
        event_id="evt_1", timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"), task="test",
    ))
    await engine.emit(_make_event(event_type="other.type"))
    await engine.flush()

    if mock_sink.write_batch.called:
        events = mock_sink.write_batch.call_args[0][0]
        event_types = [e.event_type for e in events]
        assert "other.type" not in event_types
    await engine.close()


async def test_get_run_summary():
    engine = ObservabilityEngine(sinks=[], config=ObservabilityConfig())
    await engine.emit(RunStartEvent(
        event_id="evt_1", timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"), task="test",
    ))
    await engine.emit(ToolResultEvent(
        event_id="evt_2", timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"), tool_name="add", success=True, latency_ms=5.0,
    ))
    await engine.emit(ToolResultEvent(
        event_id="evt_3", timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"), tool_name="fail", success=False, latency_ms=10.0, error="broke",
    ))
    await engine.emit(RunEndEvent(
        event_id="evt_4", timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"), status=RunStatus.COMPLETED,
        total_steps=2, total_input_tokens=300, total_output_tokens=100, duration_ms=1000.0,
    ))
    summary = engine.get_run_summary(RunId("run_1"))
    assert summary.total_tool_calls == 2
    assert summary.total_tool_failures == 1
    assert summary.status == RunStatus.COMPLETED
    assert "add" in summary.tools_used
    assert "fail" in summary.tools_used
    await engine.close()
