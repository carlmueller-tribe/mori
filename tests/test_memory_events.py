"""Tests for memory observability events."""

from datetime import UTC, datetime

from mori.observability.events import MemoryReadEvent, MemoryWriteEvent
from mori.types import MemoryLayer, RunId


def test_memory_read_event():
    e = MemoryReadEvent(
        event_id="evt_1",
        timestamp=datetime.now(UTC),
        run_id=RunId("run_1"),
        query="auth",
        layers=[MemoryLayer.WORKING, MemoryLayer.EPISODIC],
        records_returned=5,
        tokens_consumed=500,
        duration_ms=15.0,
    )
    assert e.event_type == "memory.read" and e.records_returned == 5


def test_memory_write_event():
    e = MemoryWriteEvent(
        event_id="evt_2",
        timestamp=datetime.now(UTC),
        run_id=RunId("run_1"),
        layer=MemoryLayer.WORKING,
        record_ids=["rec_1", "rec_2"],
        records_written=2,
    )
    assert e.event_type == "memory.write" and e.records_written == 2
