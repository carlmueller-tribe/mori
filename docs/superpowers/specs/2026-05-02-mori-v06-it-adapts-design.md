# Mori v0.6 "It Adapts" — Design Spec

**Date:** 2026-05-02
**Branch:** v0.6/it-adapts
**Status:** Approved

---

## 1. Goal

Formalize Mori's boundary model: **ports at all external seams, opinionated concrete core**. Every place Mori touches something it doesn't own — a model provider, storage backend, embedding service, observability sink, external framework — has a protocol. Mori ships first-party adapters for common providers. The core runtime, budget, permission, and skill logic stays concrete and opinionated.

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .embedder(VoyageAIEmbedder(api_key="..."))
    .runtime(LangGraphAdapter())
    .sink(OTLPSink(endpoint="..."))
    .build()
)
```

---

## 2. Architectural Principle

Mori follows a **ports and adapters** model at its boundaries:

- **Ports** are protocols defined inside the module that owns the abstraction. `Embedder` lives in `mori/memory/`. `Sink` lives in `mori/observability/`. `RuntimeAdapter` lives in `mori/runtime/`. Protocols do not move to a central registry.
- **Adapters** are first-party implementations of those protocols for specific external providers. They live in `mori/adapters/`. They have optional dependencies and are never imported by core Mori modules.
- **Core** (runtime loop, budget, permissions, skills logic) is opinionated and concrete. It is not abstracted. Protocols are not added for things that will never have alternative implementations.

This becomes an explicit design principle (P7) alongside the existing five in the architecture docs:

> **P7: Ports at boundaries, concrete core.** Every external dependency is behind a protocol. The core runtime is opinionated — it is not abstracted away from itself.

---

## 3. Boundary Inventory

Complete audit of external ports and their status entering v0.6:

| Port | Protocol | Location | Status |
|---|---|---|---|
| Model provider | `ModelAdapter` | `mori/model/base.py` | ✓ Clean |
| Memory storage | `MemoryBackend` | `mori/memory/backends/base.py` | ✓ Clean |
| Checkpoint storage | `CheckpointStore` | `mori/control/checkpoint.py` | ✓ Clean |
| Skill registry | `SkillRegistry` | `mori/skills/registry.py` | ✓ Clean |
| Embedding provider | `Embedder` | `mori/memory/embedder.py` | Protocol clean; one misnamed impl |
| Observability sink | *(none)* | `mori/observability/engine.py` | Duck-typed `list[Any]` — needs protocol |
| Framework runtime | *(none)* | — | Missing — Spec 10b Part B |

v0.6 closes the three open rows.

---

## 4. Protocol Changes

### 4.1 `Sink` Protocol

**New file:** `mori/observability/sinks/base.py`

```python
class Sink(Protocol):
    realtime: bool
    async def write(self, event: MoriEvent) -> None: ...
    async def write_batch(self, events: list[MoriEvent]) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...
```

`ObservabilityEngine.__init__` changes from `sinks: list[Any]` to `sinks: list[Sink]`. `StdoutSink` and `JsonlSink` stay in `mori/observability/sinks/` — no external dependency, they are core.

### 4.2 `RuntimeAdapter` Protocol

**New file:** `mori/runtime/adapter.py`

```python
class RuntimeAdapter(Protocol):
    async def run(
        self,
        task: str,
        state: MoriState,
        tools: ToolRegistry,
        memory: MemoryModule | None,
        skills: SkillsModule | None,
        config: LoopConfig,
    ) -> RunResult: ...

    async def stream(
        self,
        task: str,
        state: MoriState,
        tools: ToolRegistry,
        **kwargs,
    ) -> AsyncIterator[StreamEvent]: ...
```

`AgentLoop` accepts an optional `runtime: RuntimeAdapter | None = None`. When provided, it delegates `run()` and `stream()` to the adapter instead of the native loop. When `None`, the native loop runs unchanged.

### 4.3 `Embedder` — Rename and Relocate

`AnthropicEmbedder` is renamed `VoyageAIEmbedder` and moves to `mori/adapters/embeddings/voyageai_embedder.py`. The name `AnthropicEmbedder` was incorrect — Voyage AI is a third-party provider, not an Anthropic product.

Backward-compat re-export in `mori/memory/embedder.py`:
```python
# Deprecated: import from mori.adapters.embeddings.voyageai_embedder
from mori.adapters.embeddings.voyageai_embedder import VoyageAIEmbedder as AnthropicEmbedder
```

---

## 5. `mori/adapters/` Package

Home for all first-party adapter implementations. Core Mori modules never import from here.

```
mori/adapters/
├── __init__.py
├── embeddings/
│   ├── __init__.py
│   ├── voyageai_embedder.py     # VoyageAIEmbedder  (mori[voyageai])
│   ├── openai_embedder.py       # OpenAIEmbedder     (mori[openai-embed])
│   ├── cohere_embedder.py       # CohereEmbedder     (mori[cohere])
│   └── local_embedder.py        # SentenceTransformerEmbedder (mori[local-embed])
├── frameworks/
│   ├── __init__.py
│   └── langgraph_adapter.py     # LangGraphAdapter   (mori[langgraph])
└── sinks/
    ├── __init__.py
    └── otlp_sink.py             # OTLPSink moves here from observability/sinks/ (mori[otlp])
```

### Embedding adapters

All implement `mori.memory.embedder.Embedder`. Constructor takes `api_key` and `model` with sensible defaults. `dimensions` property reflects the chosen model's output size.

```python
# All follow the same interface
class VoyageAIEmbedder:
    def __init__(self, api_key: str | None = None, model: str = "voyage-3") -> None: ...

class OpenAIEmbedder:
    def __init__(self, api_key: str | None = None, model: str = "text-embedding-3-small") -> None: ...

class CohereEmbedder:
    def __init__(self, api_key: str | None = None, model: str = "embed-english-v3.0") -> None: ...

class SentenceTransformerEmbedder:
    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None: ...
```

### LangGraph adapter

Implements `mori.runtime.adapter.RuntimeAdapter`. Wraps Mori modules into a LangGraph `StateGraph`. Also ships two helpers:

```python
def langgraph_as_tool(graph, name: str, description: str, input_schema: type) -> RegisteredTool: ...
def langgraph_as_skill(graph, name: str, version: str, description: str, triggers: list[str]) -> SkillManifest: ...
```

### OTLP sink

Moves from `mori/observability/sinks/otlp.py` to `mori/adapters/sinks/otlp_sink.py`. Depends on `opentelemetry-*`. Implements the `Sink` protocol. The old path (`mori.observability.sinks.otlp`) is replaced with a stub that raises `ImportError` with a migration message pointing to the new location.

---

## 6. Builder API

Two new additive methods — no breaking changes:

```python
.embedder(embedder: Embedder) -> MoriBuilder
.runtime(adapter: RuntimeAdapter) -> MoriBuilder
```

**`.embedder()`** — if not called, semantic memory search is disabled. Attempting vector search without an embedder raises `MoriConfigError` with a clear message pointing to `mori/adapters/embeddings/`.

**`.runtime()`** — if not called, the native `AgentLoop` runs as today.

`.sink()` now type-checks against the `Sink` protocol at builder time rather than at flush time.

---

## 7. Optional Dependencies

```toml
[project.optional-dependencies]
anthropic    = ["anthropic"]          # unchanged
voyageai     = ["voyageai"]
openai-embed = ["openai"]
cohere       = ["cohere"]
local-embed  = ["sentence-transformers"]
langgraph    = ["langgraph"]
otlp         = ["opentelemetry-sdk", "opentelemetry-exporter-otlp-proto-grpc"]
```

---

## 8. What Does Not Change

- `ModelAdapter` and `mori/model/` — already clean, no move
- `MemoryBackend`, `CheckpointStore`, `SkillRegistry` — already clean, no change
- `StdoutSink`, `JsonlSink` — no external dependency, stay in `mori/observability/sinks/`
- Native `AgentLoop` — unchanged when no `RuntimeAdapter` is provided
- All existing builder methods — no breaking changes

---

## 9. Test Criteria

- [ ] `Sink` protocol is satisfied by `StdoutSink`, `JsonlSink`, and `OTLPSink`
- [ ] `ObservabilityEngine` rejects objects that don't satisfy `Sink` at construction
- [ ] `RuntimeAdapter` protocol is implementable by a third party without importing Mori internals
- [ ] `LangGraphAdapter` produces a `RunResult` equivalent to the native loop for a simple task
- [ ] `langgraph_as_tool` wraps a graph as a callable `RegisteredTool`
- [ ] `langgraph_as_skill` produces a valid `SkillManifest`
- [ ] All four embedding adapters satisfy the `Embedder` protocol
- [ ] `AnthropicEmbedder` re-export works with a deprecation warning
- [ ] `.embedder()` on builder wires the embedder into the memory module
- [ ] Omitting `.embedder()` disables semantic search with a clear `MoriConfigError`
- [ ] `.runtime()` on builder routes `run()` and `stream()` through the adapter
- [ ] Omitting `.runtime()` runs the native loop unchanged
- [ ] `OTLPSink` moved path is importable; old path raises `ImportError` with migration message
- [ ] `mori[voyageai]`, `mori[openai-embed]`, `mori[cohere]`, `mori[local-embed]`, `mori[langgraph]`, `mori[otlp]` extras install cleanly
- [ ] Core Mori modules (`runtime`, `memory`, `observability`) have zero imports from `mori.adapters`
