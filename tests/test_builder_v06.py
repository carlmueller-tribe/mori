"""Tests for v0.6 builder additions: .embedder(), .runtime(), Sink instance acceptance."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mori.agent import MoriBuilder
from mori.observability.sinks.stdout import StdoutSink
from mori.types import MoriConfigError  # noqa: F401 — ensure it's importable


def _builder() -> MoriBuilder:
    b = MoriBuilder()
    b._model_adapter = MagicMock()
    return b


def test_builder_accepts_embedder_instance():
    class FakeEmbedder:
        async def embed(self, texts):
            return [[0.1] * 384 for _ in texts]

        @property
        def dimensions(self):
            return 384

    builder = _builder().embedder(FakeEmbedder())
    assert builder._embedder is not None


def test_builder_accepts_runtime_adapter():
    class FakeAdapter:
        async def run(self, task, state, tools, memory, skills):
            pass

        async def stream(self, task, state, tools, **kwargs):
            return
            yield

    builder = _builder().runtime(FakeAdapter())
    assert builder._runtime_adapter is not None


def test_builder_sink_accepts_sink_instance():
    builder = _builder()
    builder.sink(StdoutSink())
    assert len(builder._sinks) == 1
    assert isinstance(builder._sinks[0], StdoutSink)


def test_builder_sink_string_still_works():
    builder = _builder()
    builder.sink("stdout")
    assert len(builder._sinks) == 1


def test_builder_sink_rejects_non_sink_instance():
    builder = _builder()
    with pytest.raises(TypeError, match="does not satisfy Sink protocol"):
        builder.sink(object())


def test_builder_passes_runtime_to_loop():
    """AgentLoop receives the runtime adapter from builder."""

    class FakeAdapter:
        async def run(self, task, state, tools, memory, skills):
            pass

        async def stream(self, task, state, tools, **kwargs):
            return
            yield

    adapter = FakeAdapter()
    builder = _builder()
    builder._runtime_adapter = adapter
    builder._disabled_native_tools = {"ask_user"}
    mori = builder.build()
    assert mori._loop._runtime is adapter


def test_builder_embedder_wired_to_loop():
    """Embedder passed to .embedder() ends up in the memory module."""

    class FakeEmbedder:
        async def embed(self, texts):
            return [[0.0] * 64 for _ in texts]

        @property
        def dimensions(self):
            return 64

    embedder = FakeEmbedder()
    builder = _builder()
    builder._embedder = embedder
    builder._memory_config = {"type": "inmemory"}
    builder._disabled_native_tools = {"ask_user"}
    mori = builder.build()
    assert mori._memory._embedder is embedder


def test_builder_embedder_none_by_default():
    builder = _builder()
    assert builder._embedder is None


def test_builder_runtime_none_by_default():
    builder = _builder()
    assert builder._runtime_adapter is None
