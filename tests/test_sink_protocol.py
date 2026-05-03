from __future__ import annotations

import pytest

from mori.observability.engine import ObservabilityEngine
from mori.observability.sinks.base import Sink
from mori.observability.sinks.jsonl import JsonlSink
from mori.observability.sinks.stdout import StdoutSink


def test_stdout_sink_satisfies_protocol():
    assert isinstance(StdoutSink(), Sink)


def test_jsonl_sink_satisfies_protocol(tmp_path):
    sink = JsonlSink(path=str(tmp_path / "test.jsonl"))
    assert isinstance(sink, Sink)
    assert sink.realtime is False


def test_observability_engine_accepts_sink_list():
    # Should not raise
    ObservabilityEngine(sinks=[StdoutSink()])


def test_observability_engine_rejects_non_sink():
    with pytest.raises(TypeError, match="does not satisfy Sink protocol"):
        ObservabilityEngine(sinks=[object()])
