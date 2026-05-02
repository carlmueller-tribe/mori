"""Tests for StdoutSink and JsonlSink."""

import json
from datetime import UTC, datetime

from mori.observability.events import (
    MoriEvent,
    RunStartEvent,
)
from mori.observability.sinks.jsonl import JsonlSink
from mori.observability.sinks.stdout import StdoutSink
from mori.types import RunId


def _make_event(**overrides) -> MoriEvent:
    defaults = {
        "event_id": "evt_1",
        "event_type": "test",
        "timestamp": datetime.now(UTC),
        "run_id": RunId("run_1"),
    }
    defaults.update(overrides)
    return MoriEvent(**defaults)


async def test_stdout_sink_write(capsys):
    sink = StdoutSink()
    event = RunStartEvent(
        event_id="evt_1",
        timestamp=datetime.now(UTC),
        run_id=RunId("run_1"),
        task="test task",
    )
    await sink.write(event)
    captured = capsys.readouterr()
    assert "run.start" in captured.out
    assert "test task" in captured.out


async def test_stdout_sink_flush_noop():
    sink = StdoutSink()
    await sink.flush()


async def test_stdout_sink_close_noop():
    sink = StdoutSink()
    await sink.close()


async def test_jsonl_sink_write(tmp_path):
    path = tmp_path / "traces.jsonl"
    sink = JsonlSink(path=str(path))
    event = _make_event(event_type="test.event")
    await sink.write(event)
    await sink.flush()

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_type"] == "test.event"
    assert parsed["run_id"] == "run_1"
    await sink.close()


async def test_jsonl_sink_write_batch(tmp_path):
    path = tmp_path / "traces.jsonl"
    sink = JsonlSink(path=str(path))
    events = [_make_event(event_id=f"evt_{i}", event_type="batch") for i in range(5)]
    await sink.write_batch(events)
    await sink.flush()
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 5
    await sink.close()


async def test_jsonl_sink_multiple_writes(tmp_path):
    path = tmp_path / "traces.jsonl"
    sink = JsonlSink(path=str(path))
    await sink.write(_make_event(event_id="evt_1"))
    await sink.write(_make_event(event_id="evt_2"))
    await sink.flush()
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2
    await sink.close()


async def test_jsonl_sink_close_flushes(tmp_path):
    path = tmp_path / "traces.jsonl"
    sink = JsonlSink(path=str(path))
    await sink.write(_make_event())
    await sink.close()
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 1


async def test_stdout_sink_write_batch(capsys):
    sink = StdoutSink()
    events = [_make_event(event_type="first"), _make_event(event_type="second")]
    await sink.write_batch(events)
    captured = capsys.readouterr()
    assert "first" in captured.out
    assert "second" in captured.out
