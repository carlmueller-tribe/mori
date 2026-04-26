# Mori v0.3 "It Remembers" — Design Spec

**Goal:** Add four-layer memory with retrieval pipeline, pluggable backends, and runtime integration so the agent can persist and recall context across steps and runs.

**Depends on:** v0.2 complete (observability, control bounds, CLI/MCP tools, builder API)

**Reference specs:** 03-MEMORY

---

## 1. Components

| Component | What it does |
|-----------|-------------|
| Memory types | MemoryRecord, MemorySlice, WriteReceipt, ForgetPolicy, ForgetReport, MemoryStats, MemoryConfig, MemoryFilters |
| Embedder | Embedder protocol + AnthropicEmbedder |
| InMemoryBackend | Dict + numpy cosine similarity for dev/test |
| SQLiteBackend | SQLite with numpy vector search for local single-user |
| MemoryModule | Full interface: read (4-stage pipeline), write, promote, forget, summarize_layer |
| Runtime wiring | Retrieve phase reads memory, update phase writes working memory, run end writes episodic summary |
| Builder API | `.memory_backend("inmemory")` or `.memory_backend("sqlite", path="./memory.db")` |

---

## 2. File Structure

### New files

```
mori/
├── memory/
│   ├── __init__.py
│   ├── module.py             # MemoryModule — read, write, promote, forget, summarize
│   ├── retrieval.py          # 4-stage retrieval pipeline
│   ├── embedder.py           # Embedder protocol + AnthropicEmbedder
│   └── backends/
│       ├── __init__.py
│       ├── base.py            # MemoryBackend protocol
│       ├── inmemory.py        # InMemoryBackend (dict + numpy cosine)
│       └── sqlite.py          # SQLiteBackend (sqlite3 + numpy)
```

### Modified files

- `mori/types.py` — add/update memory types (MemoryRecord, MemorySlice, WriteReceipt, ForgetPolicy, ForgetReport, MemoryStats already partially defined)
- `mori/runtime/loop.py` — add retrieve phase and update phase when memory is configured
- `mori/runtime/state.py` — ensure `memory_slice: MemorySlice | None` field exists
- `mori/agent.py` — add `.memory_backend()` builder method, expose `agent.memory` property
- `mori/observability/events.py` — add MemoryReadEvent, MemoryWriteEvent

---

## 3. Memory Types

Types already defined in `mori/types.py` from v0.1 (MemoryRecord, MemorySlice, WriteReceipt). Additional types needed:

```python
class MemoryConfig(MoriModel):
    default_ttl_seconds: dict[MemoryLayer, int | None] = {
        MemoryLayer.WORKING: 3600,
        MemoryLayer.EPISODIC: None,
        MemoryLayer.SEMANTIC: None,
        MemoryLayer.PERSONALIZED: None,
    }
    max_records_per_layer: dict[MemoryLayer, int] = {
        MemoryLayer.WORKING: 200,
        MemoryLayer.EPISODIC: 10_000,
        MemoryLayer.SEMANTIC: 50_000,
        MemoryLayer.PERSONALIZED: 5_000,
    }
    deduplication_threshold: float = 0.95
    conflict_resolution: Literal["highest_confidence", "most_recent", "keep_all"] = "highest_confidence"
    embedding_dimensions: int = 1536
    auto_forget_interval_sec: float = 300.0

class MemoryFilters(MoriModel):
    min_confidence: float | None = None
    max_age_seconds: int | None = None
    provenance: str | None = None
    metadata_match: dict | None = None
    exclude_ids: list[MemoryRecordId] = Field(default_factory=list)

class ForgetPolicy(MoriModel):
    expire_ttl: bool = True
    prune_below_confidence: float | None = 0.2
    deduplicate: bool = True
    max_records_per_layer: dict[MemoryLayer, int] | None = None

class ForgetReport(MoriModel):
    expired: int
    pruned: int
    deduplicated: int
    total_deleted: int

class MemoryStats(MoriModel):
    total_records: int
    records_per_layer: dict[MemoryLayer, int]
    estimated_tokens_per_layer: dict[MemoryLayer, int]
    oldest_record_age_seconds: dict[MemoryLayer, float | None]
    newest_record_age_seconds: dict[MemoryLayer, float | None]
```

---

## 4. Embedder

### Protocol

```python
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]
    @property
    def dimensions(self) -> int
```

### AnthropicEmbedder

```python
class AnthropicEmbedder:
    def __init__(self, api_key: str | None = None, model: str = "voyage-3") -> None
    async def embed(self, texts: list[str]) -> list[list[float]]
    @property
    def dimensions(self) -> int  # 1024 for voyage-3
```

Uses the Anthropic SDK's embedding endpoint (or Voyage AI via Anthropic's partnership). Batches texts in a single API call.

Note: Anthropic partners with Voyage AI for embeddings. The specific model (`voyage-3`, `voyage-3-lite`, etc.) may vary at implementation time. The `Embedder` protocol abstracts this — swapping providers requires no changes to the memory module or backends.

---

## 5. MemoryBackend Protocol

```python
class MemoryBackend(Protocol):
    async def insert(self, records: list[MemoryRecord]) -> list[MemoryRecordId]
    async def get(self, record_ids: list[MemoryRecordId]) -> list[MemoryRecord]
    async def update(self, record_id: MemoryRecordId, updates: dict) -> MemoryRecord
    async def delete(self, record_ids: list[MemoryRecordId]) -> int
    async def search(
        self, embedding: list[float], layer: MemoryLayer | None = None,
        limit: int = 20, filters: MemoryFilters | None = None,
    ) -> list[tuple[MemoryRecord, float]]
    async def list_records(
        self, layer: MemoryLayer, limit: int = 100, offset: int = 0,
        order_by: Literal["created_at", "updated_at", "confidence"] = "created_at",
    ) -> list[MemoryRecord]
    async def count(self, layer: MemoryLayer | None = None) -> int
    async def close(self) -> None
```

### InMemoryBackend

Dict-based storage. Search uses numpy cosine similarity against stored embeddings. Records stored as `dict[MemoryRecordId, MemoryRecord]`. No persistence — data lost on process exit. For dev/test.

### SQLiteBackend

Records stored as rows in a `memory_records` table. Embedding stored as BLOB (numpy `tobytes()`/`frombuffer()`). Search does a full table scan with numpy cosine similarity — no vector index. Fine for tens of thousands of records.

Schema:
```sql
CREATE TABLE memory_records (
    record_id TEXT PRIMARY KEY,
    layer TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,           -- JSON
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    ttl_seconds INTEGER,
    provenance TEXT,
    confidence REAL DEFAULT 1.0,
    embedding BLOB           -- numpy float32 array
);
CREATE INDEX idx_layer ON memory_records(layer);
CREATE INDEX idx_created ON memory_records(created_at);
```

---

## 6. MemoryModule

```python
class MemoryModule:
    def __init__(
        self, backend: MemoryBackend, config: MemoryConfig,
        embedder: Embedder | None = None, model: ModelAdapter | None = None,
    ) -> None

    # Read
    async def read(
        self, query: str, layers: list[MemoryLayer] | None = None,
        max_tokens: int = 2000, recency_bias: float = 0.3,
        filters: MemoryFilters | None = None,
    ) -> MemorySlice

    async def read_by_ids(self, record_ids: list[MemoryRecordId]) -> list[MemoryRecord]

    # Write
    async def write(self, records: list[MemoryRecord]) -> WriteReceipt
    async def update(
        self, record_id: MemoryRecordId, content: str | None = None,
        metadata: dict | None = None, confidence: float | None = None,
    ) -> MemoryRecord
    async def delete(self, record_ids: list[MemoryRecordId]) -> int

    # Lifecycle
    async def promote(
        self, source_layer: MemoryLayer, target_layer: MemoryLayer,
        record_ids: list[MemoryRecordId], abstraction_fn: Callable | None = None,
    ) -> list[MemoryRecordId]
    async def forget(self, policy: ForgetPolicy | None = None) -> ForgetReport
    async def summarize_layer(self, layer: MemoryLayer, max_tokens: int = 500) -> str

    # Diagnostics
    async def stats(self) -> MemoryStats
    async def close(self) -> None
```

`summarize_layer` uses a model call via the configured `ModelAdapter` — sends the layer's records as context and asks for a summary within the token budget. This is the one method that requires a model reference.

The `MemoryModule.__init__` accepts an optional `model` parameter for this purpose. If no model is provided and `summarize_layer` is called, it falls back to concatenate + truncate.

---

## 7. Retrieval Pipeline (`retrieval.py`)

Four stages, implemented as a standalone function:

```python
async def retrieve(
    query: str,
    task_context: str,
    backend: MemoryBackend,
    embedder: Embedder,
    layers: list[MemoryLayer] | None = None,
    max_tokens: int = 2000,
    recency_bias: float = 0.3,
    filters: MemoryFilters | None = None,
) -> MemorySlice
```

**Stage 1: Query Expansion.** Concatenate: `f"{query} {task_context}"`. No model call.

**Stage 2: Multi-Layer Fan-Out.** Embed the expanded query. Search all requested layers (default: all four) via `backend.search()`. Each returns up to 20 records with similarity scores.

**Stage 3: Relevance Scoring.** Composite score per record:
```
score = (1 - recency_bias) * semantic_similarity + recency_bias * recency_score
```
Recency score: `exp(-age_seconds / 86400)` — 1 hour ago ~ 0.96, 1 day ago ~ 0.37, 7 days ago ~ 0.001.

**Stage 4: Budget-Aware Truncation.** Sort by composite score descending. Walk records, accumulate estimated token counts (`len(content) // 4`). Stop when `max_tokens` would be exceeded. Return as `MemorySlice` with `truncated=True` if records were dropped.

**Stage 5: Conflict Detection.** Stubbed — returns empty `conflicts` list.

---

## 8. Runtime Integration

### Loop Changes

`AgentLoop.__init__` gains optional `memory: MemoryModule` param.

**Retrieve phase** (new, before plan phase):
- Only runs if `self._memory` is configured
- Calls `memory.read(query=state.task, max_tokens=2000)`
- Stores result on `state.memory_slice`
- Emits `MemoryReadEvent`

**Plan phase** (modified):
- If `state.memory_slice` has records, inject them into the model request as a system/context message:
  ```
  [Memory Context]
  - {record.content} (layer: {record.layer}, confidence: {record.confidence})
  ...
  ```

**Update phase** (new, after evaluate):
- Only runs if `self._memory` is configured
- Writes a working memory record summarizing this step:
  ```
  Step {n}: Called {tool_names}. Results: {brief_results}. Outcome: {outcome}.
  ```
- Template-based, no model call
- Emits `MemoryWriteEvent`

**Run finalize** (after loop exits, before returning RunResult):
- Writes one episodic memory record:
  ```
  Run "{task}": {status} in {steps} steps. Tools: {tool_list}. Result: {final_output[:200]}
  ```
- Template-based from RunResult data
- Emits `MemoryWriteEvent`

### State Changes

`MoriState.memory_slice` already exists in the spec (defined in v0.1 types). Verify it's on the model, set to `None` by default.

### Observability Events

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

---

## 9. Builder API Changes

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(search_docs, description="Search docs")
    .memory_backend("sqlite", path="./memory.db")
    # or: .memory_backend("inmemory")
    .sink("stdout")
    .build()
)

# Memory persists across runs via thread_id
result = await agent.run("Research auth", thread_id="research-1")
stats = await agent.memory.stats()
```

### `build()` wiring:

1. If `.memory_backend()` was called, create the backend
2. Create `AnthropicEmbedder` (reuses the model adapter's API key)
3. Create `MemoryModule(backend, config, embedder, model_adapter)`
4. Pass to `AgentLoop(memory=memory_module)`
5. Expose via `Mori.memory` property

### Embedder API key:

The `AnthropicEmbedder` reuses the API key from the model adapter. No separate config needed — if you configured `.model("anthropic", api_key="...")`, the embedder uses the same key.

---

## 10. v0.3 Exit Test

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(search_docs, description="Search docs")
    .memory_backend("sqlite", path="./memory.db")
    .sink("stdout")
    .build()
)

result = await agent.run("Look up X, then look up Y, then summarize both", thread_id="test")
assert result.status == RunStatus.COMPLETED

stats = await agent.memory.stats()
assert stats.records_per_layer[MemoryLayer.WORKING] > 0
assert stats.records_per_layer[MemoryLayer.EPISODIC] > 0
```

---

## 11. What's Deferred

| Item | Deferred to |
|------|-------------|
| Conflict detection (retrieval stage 5) | When needed |
| PostgresBackend | v0.7 |
| Permission checks on read/write | v0.5 |
| PIIGuard hook on memory.write | v0.6 |
| Budget Manager integration for summarize_layer | v0.4 |
| OpenAI embedder | When needed |

---

## 12. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Embedding provider | Anthropic (via AnthropicEmbedder) | Single provider for v0.3, OpenAI added later |
| Conflict detection | Stubbed (empty list) | Hard to test without large contradicting corpus |
| Episodic summary | Template-based from RunResult | No extra model call for internal bookkeeping |
| summarize_layer | Model call | Needed for natural language compression; Budget Manager (v0.4) will own when to trigger it |
| SQLite vector search | Full scan + numpy cosine | Fine for <50k records; pgvector in v0.7 for scale |
