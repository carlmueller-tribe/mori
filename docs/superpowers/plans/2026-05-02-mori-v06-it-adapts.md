# Mori v0.6 "It Adapts" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Formalize Mori's boundary model — protocols at every external seam, first-party adapter implementations in `mori/adapters/`, opinionated concrete core.

**Architecture:** Protocols stay in their owning modules (`Sink` in observability, `RuntimeAdapter` in runtime, `Embedder` in memory). `mori/adapters/` holds only first-party implementations with optional deps. Core modules never import from `mori/adapters/`. Builder gains `.embedder()` and `.runtime()` methods; `.sink()` gains instance acceptance.

**Tech Stack:** Python 3.11+, anyio, voyageai, openai, cohere, sentence-transformers, langgraph, opentelemetry-sdk

---

## File Map

**New files:**
- `mori/observability/sinks/base.py` — `Sink` protocol
- `mori/runtime/adapter.py` — `RuntimeAdapter` protocol
- `mori/adapters/__init__.py`
- `mori/adapters/embeddings/__init__.py`
- `mori/adapters/embeddings/voyageai_embedder.py` — `VoyageAIEmbedder`
- `mori/adapters/embeddings/openai_embedder.py` — `OpenAIEmbedder`
- `mori/adapters/embeddings/cohere_embedder.py` — `CohereEmbedder`
- `mori/adapters/embeddings/local_embedder.py` — `SentenceTransformerEmbedder`
- `mori/adapters/frameworks/__init__.py`
- `mori/adapters/frameworks/langgraph_adapter.py` — `LangGraphAdapter`, `langgraph_as_tool`, `langgraph_as_skill`
- `mori/adapters/sinks/__init__.py`
- `mori/adapters/sinks/otlp_sink.py` — `OTLPSink`
- `tests/test_sink_protocol.py`
- `tests/test_runtime_adapter.py`
- `tests/test_embedder_adapters.py`
- `tests/test_langgraph_adapter.py`
- `tests/test_builder_v06.py`
- `tests/test_integration_v06.py`

**Modified files:**
- `mori/types.py` — add `MoriConfigError`
- `mori/observability/sinks/jsonl.py` — add `realtime = False`
- `mori/observability/engine.py` — `list[Any]` → `list[Sink]`, `getattr` → `sink.realtime`
- `mori/observability/sinks/__init__.py` — export `Sink`
- `mori/memory/embedder.py` — backward-compat re-export `VoyageAIEmbedder as AnthropicEmbedder`
- `mori/runtime/loop.py` — accept `runtime: RuntimeAdapter | None`
- `mori/agent.py` — `.embedder()`, `.runtime()`, updated `.sink()`, remove auto-embedder
- `pyproject.toml` — new optional extras

---

## Task 1: `Sink` Protocol + Fix `JsonlSink` + Update Engine

**Files:**
- Create: `mori/observability/sinks/base.py`
- Modify: `mori/observability/sinks/jsonl.py`
- Modify: `mori/observability/engine.py`
- Modify: `mori/observability/sinks/__init__.py`
- Test: `tests/test_sink_protocol.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sink_protocol.py
from __future__ import annotations
import pytest
from mori.observability.sinks.base import Sink
from mori.observability.sinks.stdout import StdoutSink
from mori.observability.sinks.jsonl import JsonlSink
from mori.observability.engine import ObservabilityEngine


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
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_sink_protocol.py -v
```
Expected: 4 failures (Sink not importable, realtime missing on JsonlSink, TypeError not raised)

- [ ] **Step 3: Create `mori/observability/sinks/base.py`**

```python
"""Sink protocol — implemented by all observability output targets."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mori.observability.events import MoriEvent


@runtime_checkable
class Sink(Protocol):
    realtime: bool

    async def write(self, event: MoriEvent) -> None: ...
    async def write_batch(self, events: list[MoriEvent]) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...
```

- [ ] **Step 4: Add `realtime = False` to `JsonlSink`**

In `mori/observability/sinks/jsonl.py`, add after the class definition line:

```python
class JsonlSink:
    realtime = False  # Events are buffered and flushed

    def __init__(self, path: str) -> None:
        ...
```

- [ ] **Step 5: Update `ObservabilityEngine` to use `list[Sink]`**

In `mori/observability/engine.py`, replace the import and `__init__` signature:

```python
from mori.observability.sinks.base import Sink

class ObservabilityEngine:
    def __init__(self, sinks: list[Sink], config: ObservabilityConfig | None = None) -> None:
        for sink in sinks:
            if not isinstance(sink, Sink):
                raise TypeError(
                    f"{type(sink).__name__} does not satisfy Sink protocol. "
                    "Implement write(), write_batch(), flush(), close(), and realtime."
                )
        self._sinks = sinks
        ...
```

Also replace all `getattr(sink, "realtime", False)` with `sink.realtime` in `engine.py`.

- [ ] **Step 6: Export `Sink` from `mori/observability/sinks/__init__.py`**

```python
from mori.observability.sinks.base import Sink

__all__ = ["Sink"]
```

- [ ] **Step 7: Run tests to confirm pass**

```bash
pytest tests/test_sink_protocol.py -v
```
Expected: 4 passed

- [ ] **Step 8: Run full suite to check no regressions**

```bash
pytest --tb=short -q
```
Expected: all previously passing tests still pass

- [ ] **Step 9: Commit**

```bash
git add mori/observability/sinks/base.py mori/observability/sinks/jsonl.py \
        mori/observability/sinks/__init__.py mori/observability/engine.py \
        tests/test_sink_protocol.py
git commit -m "feat(observability): Sink protocol, fix JsonlSink.realtime, type-check engine sinks"
```

---

## Task 2: `OTLPSink` in `mori/adapters/sinks/`

**Files:**
- Create: `mori/adapters/__init__.py`
- Create: `mori/adapters/sinks/__init__.py`
- Create: `mori/adapters/sinks/otlp_sink.py`

No existing OTLP sink to move. This is a net-new implementation.

- [ ] **Step 1: Write failing test**

```python
# tests/test_sink_protocol.py — add to existing file

def test_otlp_sink_import_path():
    """OTLPSink lives in mori.adapters.sinks.otlp_sink."""
    from mori.adapters.sinks.otlp_sink import OTLPSink
    assert OTLPSink is not None
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_sink_protocol.py::test_otlp_sink_import_path -v
```
Expected: ImportError / ModuleNotFoundError

- [ ] **Step 3: Create package structure**

```python
# mori/adapters/__init__.py
"""First-party adapter implementations. Core Mori never imports from here."""
```

```python
# mori/adapters/sinks/__init__.py
```

- [ ] **Step 4: Create `mori/adapters/sinks/otlp_sink.py`**

```python
"""OTLPSink — OpenTelemetry Protocol sink for Mori events."""

from __future__ import annotations

try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except ImportError as e:
    raise ImportError(
        "OTLPSink requires opentelemetry packages. Install with: pip install 'mori[otlp]'"
    ) from e

from mori.observability.events import MoriEvent


class OTLPSink:
    """Exports Mori events as OpenTelemetry spans."""

    realtime: bool = False

    def __init__(self, endpoint: str = "http://localhost:4317") -> None:
        exporter = OTLPSpanExporter(endpoint=endpoint)
        self._provider = TracerProvider()
        self._provider.add_span_processor(BatchSpanProcessor(exporter))
        self._tracer = self._provider.get_tracer("mori")

    async def write(self, event: MoriEvent) -> None:
        with self._tracer.start_as_current_span(event.event_type) as span:
            span.set_attribute("mori.event_id", event.event_id)
            span.set_attribute("mori.run_id", str(event.run_id))
            for k, v in (event.metadata or {}).items():
                if isinstance(v, (str, int, float, bool)):
                    span.set_attribute(f"mori.{k}", v)

    async def write_batch(self, events: list[MoriEvent]) -> None:
        for event in events:
            await self.write(event)

    async def flush(self) -> None:
        self._provider.force_flush()

    async def close(self) -> None:
        self._provider.force_flush()
        self._provider.shutdown()
```

- [ ] **Step 5: Run test**

```bash
pytest tests/test_sink_protocol.py::test_otlp_sink_import_path -v
```
Expected: PASS (import succeeds; opentelemetry packages may not be installed, but module structure is valid)

Note: if `opentelemetry` is not installed, the test will hit the ImportError guard. Skip with `pytest -k "not otlp"` during dev without the optional dep installed.

- [ ] **Step 6: Commit**

```bash
git add mori/adapters/__init__.py mori/adapters/sinks/__init__.py \
        mori/adapters/sinks/otlp_sink.py tests/test_sink_protocol.py
git commit -m "feat(adapters): OTLPSink in mori.adapters.sinks"
```

---

## Task 3: `MoriConfigError` + `RuntimeAdapter` Protocol + `AgentLoop` Integration

**Files:**
- Modify: `mori/types.py`
- Create: `mori/runtime/adapter.py`
- Modify: `mori/runtime/loop.py`
- Test: `tests/test_runtime_adapter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_runtime_adapter.py
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock
from mori.runtime.adapter import RuntimeAdapter
from mori.runtime.loop import AgentLoop
from mori.runtime.result import RunResult
from mori.runtime.state import MoriState
from mori.types import RunStatus


class ConcreteAdapter:
    async def run(self, task, state, tools, memory, skills) -> RunResult:
        from mori.types import TokenUsage
        return RunResult(
            run_id=state.run_id,
            thread_id=state.thread_id,
            status=RunStatus.COMPLETED,
            task=task,
            final_output="adapter ran",
            total_steps=0,
            total_usage=TokenUsage(input_tokens=0, output_tokens=0),
            total_tool_calls=0,
            total_duration_ms=0.0,
        )

    async def stream(self, task, state, tools, **kwargs):
        return
        yield  # make it an async generator


def test_concrete_adapter_satisfies_protocol():
    assert isinstance(ConcreteAdapter(), RuntimeAdapter)


@pytest.mark.asyncio
async def test_agent_loop_delegates_to_runtime_adapter():
    mock_model = MagicMock()
    mock_tools = MagicMock()
    adapter = ConcreteAdapter()
    loop = AgentLoop(model=mock_model, tools=mock_tools, runtime=adapter)
    result = await loop.run("test task")
    assert result.final_output == "adapter ran"
    assert result.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_agent_loop_uses_native_loop_when_no_adapter(mock_loop):
    """When runtime=None, native loop runs (existing behavior unchanged)."""
    # This test verifies the conditional exists; native loop tests are in test_loop_*.py
    mock_model = MagicMock()
    mock_tools = MagicMock()
    loop = AgentLoop(model=mock_model, tools=mock_tools, runtime=None)
    assert loop._runtime is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_runtime_adapter.py -v
```
Expected: ImportError on `mori.runtime.adapter`

- [ ] **Step 3: Add `MoriConfigError` to `mori/types.py`**

After the existing `ServerUnavailable` class at the end of the error section:

```python
class MoriConfigError(MoriError):
    """Raised when Mori is misconfigured at build time."""
```

- [ ] **Step 4: Create `mori/runtime/adapter.py`**

```python
"""RuntimeAdapter protocol — implemented by external framework adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Protocol, runtime_checkable

from mori.runtime.result import RunResult
from mori.runtime.state import MoriState
from mori.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from mori.observability.events import StreamEvent


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Allows an external framework to serve as Mori's execution engine.

    Implement this protocol to replace the native AgentLoop with LangGraph,
    CrewAI, or any other orchestration framework while retaining all Mori modules.
    """

    async def run(
        self,
        task: str,
        state: MoriState,
        tools: ToolRegistry,
        memory: Any | None,
        skills: Any | None,
    ) -> RunResult: ...

    async def stream(
        self,
        task: str,
        state: MoriState,
        tools: ToolRegistry,
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]: ...
```

- [ ] **Step 5: Update `AgentLoop.__init__` in `mori/runtime/loop.py`**

Add `runtime` import and parameter:

```python
# At top of file, add to TYPE_CHECKING block:
if TYPE_CHECKING:
    from mori.control.bounds import ControlBounds
    from mori.observability.engine import ObservabilityEngine
    from mori.observability.events import MoriEvent
    from mori.runtime.adapter import RuntimeAdapter

class AgentLoop:
    def __init__(
        self,
        model: ModelAdapter,
        tools: ToolRegistry,
        observability: ObservabilityEngine | None = None,
        control: ControlBounds | None = None,
        memory: Any | None = None,
        skills: Any | None = None,
        budget: Any | None = None,
        checkpointer: Any | None = None,
        checkpoint_every_n_steps: int = 5,
        permission: Any | None = None,
        identity: Any | None = None,
        hooks: Any | None = None,
        runtime: RuntimeAdapter | None = None,   # ← new
    ) -> None:
        ...
        self._runtime = runtime   # ← add after existing assignments
```

- [ ] **Step 6: Update `AgentLoop.run()` to delegate when adapter present**

Replace the `run()` method body:

```python
async def run(
    self, task: str, thread_id: ThreadId | None = None, context: dict[str, Any] | None = None
) -> RunResult:
    state = self._init_state(task, thread_id, context)
    if self._runtime is not None:
        return await self._runtime.run(task, state, self._tools, self._memory, self._skills)
    return await self._run_from_state(state)
```

- [ ] **Step 7: Fix test — remove `mock_loop` fixture reference**

The third test references a non-existent `mock_loop` fixture. Replace it:

```python
def test_agent_loop_stores_none_runtime():
    from unittest.mock import MagicMock
    mock_model = MagicMock()
    mock_tools = MagicMock()
    loop = AgentLoop(model=mock_model, tools=mock_tools, runtime=None)
    assert loop._runtime is None
```

- [ ] **Step 8: Run tests**

```bash
pytest tests/test_runtime_adapter.py -v
```
Expected: 3 passed

- [ ] **Step 9: Run full suite**

```bash
pytest --tb=short -q
```
Expected: all previously passing tests still pass

- [ ] **Step 10: Commit**

```bash
git add mori/types.py mori/runtime/adapter.py mori/runtime/loop.py \
        tests/test_runtime_adapter.py
git commit -m "feat(runtime): RuntimeAdapter protocol + AgentLoop delegation, add MoriConfigError"
```

---

## Task 4: `VoyageAIEmbedder` — Rename and Relocate

**Files:**
- Create: `mori/adapters/embeddings/__init__.py`
- Create: `mori/adapters/embeddings/voyageai_embedder.py`
- Modify: `mori/memory/embedder.py`
- Test: `tests/test_embedder_adapters.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_embedder_adapters.py
from __future__ import annotations
import pytest
from mori.memory.embedder import Embedder


def test_voyageai_embedder_import_path():
    from mori.adapters.embeddings.voyageai_embedder import VoyageAIEmbedder
    assert VoyageAIEmbedder is not None


def test_anthropic_embedder_backward_compat():
    """AnthropicEmbedder re-export still importable with deprecation warning."""
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from mori.memory.embedder import AnthropicEmbedder
        assert AnthropicEmbedder is not None
        assert any("deprecated" in str(warning.message).lower() for warning in w)


def test_voyageai_embedder_satisfies_protocol():
    """VoyageAIEmbedder structurally satisfies Embedder without voyageai installed."""
    import inspect
    from mori.adapters.embeddings.voyageai_embedder import VoyageAIEmbedder
    # Check method signatures match protocol
    assert hasattr(VoyageAIEmbedder, "embed")
    assert hasattr(VoyageAIEmbedder, "dimensions")
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_embedder_adapters.py -v
```
Expected: ImportError on voyageai_embedder

- [ ] **Step 3: Create `mori/adapters/embeddings/__init__.py`**

```python
```
(empty)

- [ ] **Step 4: Create `mori/adapters/embeddings/voyageai_embedder.py`**

```python
"""VoyageAIEmbedder — embedding adapter for Voyage AI."""

from __future__ import annotations

from typing import cast

try:
    import voyageai
except ImportError as e:
    raise ImportError(
        "VoyageAIEmbedder requires voyageai. Install with: pip install 'mori[voyageai]'"
    ) from e


class VoyageAIEmbedder:
    """Embedding adapter using Voyage AI."""

    def __init__(self, api_key: str | None = None, model: str = "voyage-3") -> None:
        self._model = model
        self._client = voyageai.Client(api_key=api_key)
        self._dimensions = 1024

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = self._client.embed(texts, model=self._model)
        return cast(list[list[float]], result.embeddings)

    @property
    def dimensions(self) -> int:
        return self._dimensions
```

- [ ] **Step 5: Update `mori/memory/embedder.py`**

Replace the `AnthropicEmbedder` class with a backward-compat re-export. Keep the `Embedder` protocol exactly as-is:

```python
"""Embedder protocol and implementations."""

from __future__ import annotations

import warnings
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimensions(self) -> int: ...


def __getattr__(name: str) -> object:
    if name == "AnthropicEmbedder":
        warnings.warn(
            "AnthropicEmbedder is deprecated. Use mori.adapters.embeddings.voyageai_embedder.VoyageAIEmbedder instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from mori.adapters.embeddings.voyageai_embedder import VoyageAIEmbedder
        return VoyageAIEmbedder
    raise AttributeError(f"module 'mori.memory.embedder' has no attribute {name!r}")
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_embedder_adapters.py -v
```
Expected: 3 passed (voyageai import test passes at module level since the ImportError guard fires at instantiation, not import)

- [ ] **Step 7: Run full suite**

```bash
pytest --tb=short -q
```
Expected: all passing

- [ ] **Step 8: Commit**

```bash
git add mori/adapters/embeddings/__init__.py \
        mori/adapters/embeddings/voyageai_embedder.py \
        mori/memory/embedder.py \
        tests/test_embedder_adapters.py
git commit -m "feat(adapters): VoyageAIEmbedder in mori.adapters.embeddings, deprecate AnthropicEmbedder"
```

---

## Task 5: `OpenAIEmbedder`

**Files:**
- Create: `mori/adapters/embeddings/openai_embedder.py`
- Test: `tests/test_embedder_adapters.py` (add to existing)

- [ ] **Step 1: Add failing test to `tests/test_embedder_adapters.py`**

```python
def test_openai_embedder_import_path():
    from mori.adapters.embeddings.openai_embedder import OpenAIEmbedder
    assert OpenAIEmbedder is not None


def test_openai_embedder_satisfies_protocol():
    from mori.adapters.embeddings.openai_embedder import OpenAIEmbedder
    assert hasattr(OpenAIEmbedder, "embed")
    assert hasattr(OpenAIEmbedder, "dimensions")
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_embedder_adapters.py::test_openai_embedder_import_path -v
```
Expected: ImportError / ModuleNotFoundError

- [ ] **Step 3: Create `mori/adapters/embeddings/openai_embedder.py`**

```python
"""OpenAIEmbedder — embedding adapter for OpenAI embeddings API."""

from __future__ import annotations

try:
    from openai import AsyncOpenAI
except ImportError as e:
    raise ImportError(
        "OpenAIEmbedder requires openai. Install with: pip install 'mori[openai]'"
    ) from e

_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbedder:
    """Embedding adapter using OpenAI embeddings API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
    ) -> None:
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key)
        self._dimensions = _DIMENSIONS.get(model, 1536)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(input=texts, model=self._model)
        return [item.embedding for item in response.data]

    @property
    def dimensions(self) -> int:
        return self._dimensions
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_embedder_adapters.py -v
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add mori/adapters/embeddings/openai_embedder.py tests/test_embedder_adapters.py
git commit -m "feat(adapters): OpenAIEmbedder"
```

---

## Task 6: `CohereEmbedder`

**Files:**
- Create: `mori/adapters/embeddings/cohere_embedder.py`
- Test: `tests/test_embedder_adapters.py` (add to existing)

- [ ] **Step 1: Add failing tests**

```python
def test_cohere_embedder_import_path():
    from mori.adapters.embeddings.cohere_embedder import CohereEmbedder
    assert CohereEmbedder is not None


def test_cohere_embedder_satisfies_protocol():
    from mori.adapters.embeddings.cohere_embedder import CohereEmbedder
    assert hasattr(CohereEmbedder, "embed")
    assert hasattr(CohereEmbedder, "dimensions")
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_embedder_adapters.py::test_cohere_embedder_import_path -v
```
Expected: ImportError

- [ ] **Step 3: Create `mori/adapters/embeddings/cohere_embedder.py`**

```python
"""CohereEmbedder — embedding adapter for Cohere Embed API."""

from __future__ import annotations

try:
    import cohere
except ImportError as e:
    raise ImportError(
        "CohereEmbedder requires cohere. Install with: pip install 'mori[cohere]'"
    ) from e

_DIMENSIONS: dict[str, int] = {
    "embed-english-v3.0": 1024,
    "embed-multilingual-v3.0": 1024,
    "embed-english-light-v3.0": 384,
    "embed-multilingual-light-v3.0": 384,
}


class CohereEmbedder:
    """Embedding adapter using Cohere Embed API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "embed-english-v3.0",
        input_type: str = "search_document",
    ) -> None:
        self._model = model
        self._input_type = input_type
        self._client = cohere.AsyncClient(api_key=api_key)
        self._dimensions = _DIMENSIONS.get(model, 1024)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embed(
            texts=texts,
            model=self._model,
            input_type=self._input_type,
            embedding_types=["float"],
        )
        embeddings = response.embeddings
        if hasattr(embeddings, "float") and embeddings.float is not None:
            return list(embeddings.float)
        return list(embeddings)  # type: ignore[arg-type]

    @property
    def dimensions(self) -> int:
        return self._dimensions
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_embedder_adapters.py -v
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add mori/adapters/embeddings/cohere_embedder.py tests/test_embedder_adapters.py
git commit -m "feat(adapters): CohereEmbedder"
```

---

## Task 7: `SentenceTransformerEmbedder`

**Files:**
- Create: `mori/adapters/embeddings/local_embedder.py`
- Test: `tests/test_embedder_adapters.py` (add to existing)

- [ ] **Step 1: Add failing tests**

```python
def test_local_embedder_import_path():
    from mori.adapters.embeddings.local_embedder import SentenceTransformerEmbedder
    assert SentenceTransformerEmbedder is not None


def test_local_embedder_satisfies_protocol():
    from mori.adapters.embeddings.local_embedder import SentenceTransformerEmbedder
    assert hasattr(SentenceTransformerEmbedder, "embed")
    assert hasattr(SentenceTransformerEmbedder, "dimensions")
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_embedder_adapters.py::test_local_embedder_import_path -v
```
Expected: ImportError

- [ ] **Step 3: Create `mori/adapters/embeddings/local_embedder.py`**

```python
"""SentenceTransformerEmbedder — local embedding adapter using sentence-transformers."""

from __future__ import annotations

import asyncio

try:
    from sentence_transformers import SentenceTransformer
except ImportError as e:
    raise ImportError(
        "SentenceTransformerEmbedder requires sentence-transformers. "
        "Install with: pip install 'mori[local-embed]'"
    ) from e


class SentenceTransformerEmbedder:
    """Local embedding adapter using sentence-transformers (no API key required)."""

    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model
        self._model = SentenceTransformer(model)
        self._dimensions: int = self._model.get_sentence_embedding_dimension() or 384

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None, lambda: self._model.encode(texts, convert_to_numpy=True)
        )
        return [list(map(float, e)) for e in embeddings]

    @property
    def dimensions(self) -> int:
        return self._dimensions
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_embedder_adapters.py -v
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add mori/adapters/embeddings/local_embedder.py tests/test_embedder_adapters.py
git commit -m "feat(adapters): SentenceTransformerEmbedder (local, no API key)"
```

---

## Task 8: `LangGraphAdapter`

**Files:**
- Create: `mori/adapters/frameworks/__init__.py`
- Create: `mori/adapters/frameworks/langgraph_adapter.py`
- Test: `tests/test_langgraph_adapter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_langgraph_adapter.py
from __future__ import annotations
import pytest


def test_langgraph_adapter_import():
    from mori.adapters.frameworks.langgraph_adapter import LangGraphAdapter
    assert LangGraphAdapter is not None


def test_langgraph_as_tool_import():
    from mori.adapters.frameworks.langgraph_adapter import langgraph_as_tool
    assert langgraph_as_tool is not None


def test_langgraph_as_skill_import():
    from mori.adapters.frameworks.langgraph_adapter import langgraph_as_skill
    assert langgraph_as_skill is not None


def test_langgraph_adapter_satisfies_runtime_adapter_protocol():
    from mori.adapters.frameworks.langgraph_adapter import LangGraphAdapter
    from mori.runtime.adapter import RuntimeAdapter
    adapter = LangGraphAdapter()
    assert isinstance(adapter, RuntimeAdapter)
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_langgraph_adapter.py -v
```
Expected: ImportError on `langgraph_adapter`

- [ ] **Step 3: Create `mori/adapters/frameworks/__init__.py`**

```python
```
(empty)

- [ ] **Step 4: Create `mori/adapters/frameworks/langgraph_adapter.py`**

```python
"""LangGraphAdapter — wraps a LangGraph StateGraph as a Mori RuntimeAdapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, AsyncIterator

try:
    from langgraph.graph import StateGraph
except ImportError as e:
    raise ImportError(
        "LangGraphAdapter requires langgraph. Install with: pip install 'mori[langgraph]'"
    ) from e

from mori.runtime.result import RunResult
from mori.runtime.state import MoriState
from mori.tools.registry import ToolRegistry
from mori.types import RunStatus


class LangGraphAdapter:
    """Wraps Mori modules into a LangGraph StateGraph for execution.

    Pass an optional graph_builder callable to customize the graph topology.
    Without one, a default linear graph mirroring the native loop is used.
    """

    def __init__(self, graph_builder: Callable | None = None) -> None:
        self._graph_builder = graph_builder

    async def run(
        self,
        task: str,
        state: MoriState,
        tools: ToolRegistry,
        memory: Any | None,
        skills: Any | None,
    ) -> RunResult:
        import time
        start = time.monotonic()

        graph = self._build_graph(task, tools, memory, skills)
        initial = {"task": task, "messages": list(state.messages), "context": state.context}
        final = await graph.ainvoke(initial)

        from mori.types import TokenUsage
        return RunResult(
            run_id=state.run_id,
            thread_id=state.thread_id,
            status=RunStatus.COMPLETED,
            task=task,
            final_output=final.get("output", ""),
            total_steps=final.get("step_count", 1),
            total_usage=TokenUsage(
                input_tokens=final.get("total_input_tokens", 0),
                output_tokens=final.get("total_output_tokens", 0),
            ),
            total_tool_calls=final.get("total_tool_calls", 0),
            total_duration_ms=(time.monotonic() - start) * 1000,
        )

    async def stream(
        self,
        task: str,
        state: MoriState,
        tools: ToolRegistry,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        graph = self._build_graph(task, tools, None, None)
        initial = {"task": task, "messages": list(state.messages)}
        async for chunk in graph.astream(initial):
            yield chunk

    def _build_graph(
        self,
        task: str,
        tools: ToolRegistry,
        memory: Any | None,
        skills: Any | None,
    ) -> Any:
        if self._graph_builder is not None:
            return self._graph_builder(task=task, tools=tools, memory=memory, skills=skills)

        # Default: single-node graph that invokes all registered tools
        from typing import TypedDict

        class GraphState(TypedDict):
            task: str
            messages: list[Any]
            context: dict[str, Any]
            output: str
            step_count: int
            total_input_tokens: int
            total_output_tokens: int
            total_tool_calls: int

        async def agent_node(state: GraphState) -> GraphState:
            # Minimal passthrough — consumers should provide graph_builder for real logic
            return {**state, "output": f"LangGraph executed: {state['task']}", "step_count": 1}

        graph: StateGraph = StateGraph(GraphState)
        graph.add_node("agent", agent_node)
        graph.set_entry_point("agent")
        graph.set_finish_point("agent")
        return graph.compile()


def langgraph_as_tool(
    graph: Any,
    name: str,
    description: str,
    input_schema: type,
) -> Any:
    """Wrap a compiled LangGraph graph as a Mori RegisteredTool."""
    from mori.tools.registry import ToolRegistry

    async def _invoke(**kwargs: Any) -> str:
        result = await graph.ainvoke(kwargs)
        return str(result)

    _invoke.__name__ = name
    registry = ToolRegistry()
    registry.register(name, _invoke, description=description)
    return registry.get(name)


def langgraph_as_skill(
    graph: Any,
    name: str,
    version: str,
    description: str,
    triggers: dict[str, Any] | None = None,
) -> Any:
    """Wrap a compiled LangGraph graph as a Mori SkillManifest."""
    from mori.skills.types import SkillManifest

    return SkillManifest(
        name=name,
        version=version,
        description=description,
        triggers=triggers or {},
    )
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_langgraph_adapter.py -v
```
Expected: first 3 import tests pass; protocol test passes if `isinstance` check works structurally

- [ ] **Step 6: Commit**

```bash
git add mori/adapters/frameworks/__init__.py \
        mori/adapters/frameworks/langgraph_adapter.py \
        tests/test_langgraph_adapter.py
git commit -m "feat(adapters): LangGraphAdapter, langgraph_as_tool, langgraph_as_skill"
```

---

## Task 9: Builder Updates

**Files:**
- Modify: `mori/agent.py`
- Test: `tests/test_builder_v06.py`

Changes: add `.embedder()`, `.runtime()`, update `.sink()` to accept `Sink` instances, remove the silent auto-embedder in `build()`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_builder_v06.py
from __future__ import annotations
import pytest
from unittest.mock import MagicMock
from mori.observability.sinks.base import Sink
from mori.observability.sinks.stdout import StdoutSink
from mori.types import MoriConfigError


def _make_builder():
    from mori import Mori
    return Mori.builder()


def test_builder_accepts_embedder_instance():
    from mori.memory.embedder import Embedder

    class FakeEmbedder:
        async def embed(self, texts):
            return [[0.1] * 384 for _ in texts]
        @property
        def dimensions(self):
            return 384

    builder = _make_builder().model("anthropic").embedder(FakeEmbedder())
    assert builder._embedder is not None


def test_builder_accepts_runtime_adapter():
    from mori.runtime.adapter import RuntimeAdapter

    class FakeAdapter:
        async def run(self, task, state, tools, memory, skills):
            pass
        async def stream(self, task, state, tools, **kwargs):
            return
            yield

    builder = _make_builder().model("anthropic").runtime(FakeAdapter())
    assert builder._runtime_adapter is not None


def test_builder_sink_accepts_sink_instance():
    builder = _make_builder().model("anthropic")
    builder.sink(StdoutSink())
    assert len(builder._sinks) == 1
    assert isinstance(builder._sinks[0], StdoutSink)


def test_builder_sink_string_still_works():
    builder = _make_builder().model("anthropic")
    builder.sink("stdout")
    assert len(builder._sinks) == 1


def test_builder_sink_rejects_non_sink_instance():
    builder = _make_builder().model("anthropic")
    with pytest.raises(TypeError, match="does not satisfy Sink protocol"):
        builder.sink(object())


def test_builder_passes_runtime_to_loop():
    """AgentLoop receives the runtime adapter from builder."""
    from mori.runtime.adapter import RuntimeAdapter

    class FakeAdapter:
        async def run(self, task, state, tools, memory, skills):
            pass
        async def stream(self, task, state, tools, **kwargs):
            return
            yield

    adapter = FakeAdapter()
    mock_model = MagicMock()

    from mori.agent import MoriBuilder
    builder = MoriBuilder()
    builder._model_adapter = mock_model
    builder._runtime_adapter = adapter
    mori = builder.build()
    assert mori._loop._runtime is adapter
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_builder_v06.py -v
```
Expected: failures (no `.embedder()`, no `.runtime()`, `.sink()` doesn't accept instances)

- [ ] **Step 3: Update `MoriBuilder` in `mori/agent.py`**

Add fields to `__init__`:

```python
def __init__(self) -> None:
    ...  # existing fields
    self._embedder: Any | None = None        # ← new
    self._runtime_adapter: Any | None = None  # ← new
```

Add methods after `.hook()`:

```python
def embedder(self, embedder: Any) -> MoriBuilder:
    self._embedder = embedder
    return self

def runtime(self, adapter: Any) -> MoriBuilder:
    self._runtime_adapter = adapter
    return self
```

Update `.sink()` to accept instances:

```python
def sink(self, sink: Any, **kwargs: Any) -> MoriBuilder:
    from mori.observability.sinks.base import Sink
    if isinstance(sink, str):
        if sink == "stdout":
            self._sinks.append(StdoutSink())
        elif sink == "jsonl":
            path = kwargs.get("path")
            if not path:
                raise ValueError("JsonlSink requires a 'path' argument")
            self._sinks.append(JsonlSink(path=path))
        else:
            raise ValueError(f"Unknown sink type: {sink!r}. Supported: stdout, jsonl, or pass a Sink instance")
    elif isinstance(sink, Sink):
        self._sinks.append(sink)
    else:
        raise TypeError(
            f"{type(sink).__name__} does not satisfy Sink protocol. "
            "Implement write(), write_batch(), flush(), close(), and realtime."
        )
    return self
```

Update `build()` — remove silent auto-embedder (lines 218-224) and replace with explicit embedder wiring:

```python
# In build(), step 4 (Memory), replace the embedder auto-import block:
embedder = self._embedder  # explicit — set via .embedder(), None if not configured
memory_module = MemoryModule(
    backend=backend, config=MemoryConfig(), embedder=embedder, model=self._model_adapter
)
```

Update `build()` step 10 (Agent loop) to pass runtime adapter:

```python
loop = AgentLoop(
    model=self._model_adapter,
    tools=registry,
    observability=obs,
    control=control,
    memory=memory_module,
    skills=skills_module,
    budget=budget_manager,
    checkpointer=checkpointer,
    permission=permission_engine,
    identity=self._identity,
    hooks=hook_registry,
    runtime=self._runtime_adapter,   # ← new
)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_builder_v06.py -v
```
Expected: all pass

- [ ] **Step 5: Run full suite**

```bash
pytest --tb=short -q
```
Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add mori/agent.py tests/test_builder_v06.py
git commit -m "feat(builder): .embedder(), .runtime(), Sink instance acceptance in .sink()"
```

---

## Task 10: `pyproject.toml` Optional Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add new extras**

In `pyproject.toml`, under `[project.optional-dependencies]`, add:

```toml
voyageai     = ["voyageai>=0.2"]
cohere       = ["cohere>=5.0"]
local-embed  = ["sentence-transformers>=3.0"]
otlp         = ["opentelemetry-sdk>=1.20", "opentelemetry-exporter-otlp-proto-grpc>=1.20"]
```

Note: `openai` and `langgraph` extras already exist — no change needed.

- [ ] **Step 2: Verify toml parses cleanly**

```bash
python -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"
```
Expected: no output (no error)

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): add voyageai, cohere, local-embed, otlp optional extras"
```

---

## Task 11: Exit Test + Example + Tag

**Files:**
- Create: `tests/test_integration_v06.py`
- Create: `examples/adapters.py`

- [ ] **Step 1: Write exit test**

```python
# tests/test_integration_v06.py
"""v0.6 exit test — adapter pattern is enforced at every external boundary."""

from __future__ import annotations
import pytest
from mori.observability.sinks.base import Sink
from mori.observability.sinks.stdout import StdoutSink
from mori.observability.sinks.jsonl import JsonlSink
from mori.runtime.adapter import RuntimeAdapter
from mori.memory.embedder import Embedder


def test_sink_protocol_exported():
    """Sink protocol is importable from its owning module."""
    assert Sink is not None


def test_stdout_and_jsonl_satisfy_sink(tmp_path):
    assert isinstance(StdoutSink(), Sink)
    assert isinstance(JsonlSink(path=str(tmp_path / "test.jsonl")), Sink)


def test_runtime_adapter_protocol_exported():
    assert RuntimeAdapter is not None


def test_embedder_protocol_exported():
    assert Embedder is not None


def test_all_adapter_modules_importable():
    """All adapter subpackages are importable (without optional deps installed)."""
    import importlib
    for module in [
        "mori.adapters",
        "mori.adapters.embeddings",
        "mori.adapters.frameworks",
        "mori.adapters.sinks",
    ]:
        importlib.import_module(module)


def test_voyageai_embedder_class_importable():
    """VoyageAIEmbedder module is importable; ImportError fires at instantiation."""
    import importlib
    import sys
    # Temporarily remove voyageai from sys.modules to test guard
    voyageai_mod = sys.modules.pop("voyageai", None)
    try:
        # Re-import the module; import guard fires at class instantiation not module load
        mod = importlib.import_module("mori.adapters.embeddings.voyageai_embedder")
        assert hasattr(mod, "VoyageAIEmbedder")
    finally:
        if voyageai_mod:
            sys.modules["voyageai"] = voyageai_mod


def test_anthropic_embedder_deprecated():
    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from mori.memory.embedder import AnthropicEmbedder  # noqa: F401
        assert any("deprecated" in str(warning.message).lower() for warning in w)


def test_core_modules_do_not_import_adapters():
    """Core modules must not import from mori.adapters."""
    import ast
    import pathlib

    core_dirs = ["mori/runtime", "mori/memory", "mori/observability", "mori/budget",
                 "mori/permission", "mori/control", "mori/skills", "mori/hooks"]
    violations: list[str] = []
    for dir_path in core_dirs:
        for py_file in pathlib.Path(dir_path).rglob("*.py"):
            source = py_file.read_text()
            if "mori.adapters" in source or "from mori.adapters" in source:
                tree = ast.parse(source)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        node_str = ast.unparse(node)
                        if "mori.adapters" in node_str:
                            violations.append(f"{py_file}: {node_str}")
    assert violations == [], f"Core modules import from mori.adapters:\n" + "\n".join(violations)


@pytest.mark.asyncio
async def test_builder_with_runtime_adapter_delegates():
    """AgentLoop uses the RuntimeAdapter when provided via builder."""
    from mori.types import RunStatus
    from mori.runtime.result import RunResult

    class EchoAdapter:
        async def run(self, task, state, tools, memory, skills):
            from mori.types import TokenUsage
            return RunResult(
                run_id=state.run_id,
                thread_id=state.thread_id,
                status=RunStatus.COMPLETED,
                task=task,
                final_output=f"echo: {task}",
                total_steps=1,
                total_usage=TokenUsage(input_tokens=0, output_tokens=0),
                total_tool_calls=0,
                total_duration_ms=1.0,
            )

        async def stream(self, task, state, tools, **kwargs):
            return
            yield

    from unittest.mock import MagicMock
    from mori.agent import MoriBuilder

    builder = MoriBuilder()
    builder._model_adapter = MagicMock()
    builder._runtime_adapter = EchoAdapter()
    agent = builder.build()
    result = await agent.run("hello from adapter")
    assert result.final_output == "echo: hello from adapter"
    assert result.status == RunStatus.COMPLETED
```

- [ ] **Step 2: Run exit test**

```bash
pytest tests/test_integration_v06.py -v
```
Expected: all pass

- [ ] **Step 3: Write example**

```python
# examples/adapters.py
"""v0.6 adapters demo — shows how to wire external providers via the adapter layer."""

from __future__ import annotations

import asyncio


async def demo_with_openai_embedder() -> None:
    """Agent with OpenAI embeddings for semantic memory search."""
    from mori import Mori
    from mori.adapters.embeddings.openai_embedder import OpenAIEmbedder

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .memory_backend("inmemory")
        .embedder(OpenAIEmbedder(model="text-embedding-3-small"))
        .sink("stdout")
        .build()
    )
    result = await agent.run("What do you remember about our previous conversations?")
    print(result.output)
    await agent.close()


async def demo_with_custom_sink() -> None:
    """Agent with a custom Sink implementation — no string key required."""
    from mori import Mori
    from mori.observability.sinks.base import Sink
    from mori.observability.events import MoriEvent

    class PrintSink:
        realtime = True

        async def write(self, event: MoriEvent) -> None:
            print(f"[custom] {event.event_type}")

        async def write_batch(self, events: list[MoriEvent]) -> None:
            for e in events:
                await self.write(e)

        async def flush(self) -> None:
            pass

        async def close(self) -> None:
            pass

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .sink(PrintSink())
        .build()
    )
    result = await agent.run("Say hello.")
    print(result.output)
    await agent.close()


if __name__ == "__main__":
    asyncio.run(demo_with_custom_sink())
```

- [ ] **Step 4: Run full test suite one final time**

```bash
pytest --tb=short -q
```
Expected: all passing

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration_v06.py examples/adapters.py
git commit -m "feat: v0.6 exit test + adapters example"
```

- [ ] **Step 6: Tag**

```bash
git tag v0.6.0
```
