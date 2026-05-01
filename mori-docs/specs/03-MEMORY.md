# 03: Memory Module

**Status:** Draft v3
**Module:** `mori.memory`
**Dependencies:** Spec 01

---

## 1. Purpose

Externalize the temporal burden of agency. Convert unbounded recall into bounded, curated retrieval across four functionally distinct memory layers. Each layer has distinct retention policies, update rates, and retrieval semantics.

## 2. Responsibilities

- Store and retrieve records across four memory layers (working, episodic, semantic, personalized)
- Apply retrieval strategies combining semantic similarity, recency, and relevance scoring
- Enforce retention policies (TTL, deduplication, conflict resolution)
- Support promotion of records across layers (episodic traces becoming semantic knowledge)
- Provide compression strategies for budget-constrained retrieval
- Expose a backend interface for pluggable storage implementations

## 3. Interface

```python
class MemoryModule:

    def __init__(self, backend: MemoryBackend, config: MemoryConfig, embedder: Embedder | None = None) -> None: ...

    # Read
    async def read(self, query: str, layers: list[MemoryLayer] | None = None, max_tokens: int = 2000, recency_bias: float = 0.3, filters: MemoryFilters | None = None) -> MemorySlice: ...
    async def read_by_ids(self, record_ids: list[MemoryRecordId]) -> list[MemoryRecord]: ...

    # Write
    async def write(self, records: list[MemoryRecord]) -> WriteReceipt: ...
    async def update(self, record_id: MemoryRecordId, content: str | None = None, metadata: dict | None = None, confidence: float | None = None) -> MemoryRecord: ...
    async def delete(self, record_ids: list[MemoryRecordId]) -> int: ...

    # Lifecycle
    async def promote(self, source_layer: MemoryLayer, target_layer: MemoryLayer, record_ids: list[MemoryRecordId], abstraction_fn: Callable | None = None) -> list[MemoryRecordId]: ...
    async def forget(self, policy: ForgetPolicy | None = None) -> ForgetReport: ...
    async def summarize_layer(self, layer: MemoryLayer, max_tokens: int = 500) -> str: ...

    # Diagnostics
    async def stats(self) -> MemoryStats: ...
    async def close(self) -> None: ...
```

## 4. Configuration

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
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    auto_forget_interval_sec: float = 300.0
```

## 5. Memory Filters

```python
class MemoryFilters(MoriModel):
    min_confidence: float | None = None
    max_age_seconds: int | None = None
    provenance: str | None = None
    metadata_match: dict | None = None
    exclude_ids: list[MemoryRecordId] = Field(default_factory=list)
```

## 6. Retrieval Pipeline

Five stages:

**Stage 1: Query Expansion.** Enrich the raw query with active plan context, recent action keywords, and current skill scope. Lightweight string operation, not a model call.

**Stage 2: Multi-Layer Fan-Out.** Issue parallel retrieval requests against all requested layers. Each layer query runs independently.

**Stage 3: Relevance Scoring.** Composite score per record:
```
score = (1 - recency_bias) * semantic_similarity + recency_bias * recency_score
```
Where `semantic_similarity` is cosine similarity (0.0 to 1.0) and `recency_score` is exponential decay (1 hour ago ~ 0.9, 7 days ago ~ 0.3).

**Stage 4: Budget-Aware Truncation.** Sort by composite score descending. Accumulate token counts until budget exhausted. Drop records that exceed budget.

**Stage 5: Conflict Detection.** Scan selected records for semantic contradictions (high similarity but opposing claims). Flag in MemorySlice.conflicts so the model can adjudicate.

## 7. Forget Policy

```python
class ForgetPolicy(MoriModel):
    expire_ttl: bool = True
    prune_below_confidence: float | None = 0.2
    deduplicate: bool = True
    resolve_contradictions: bool = True
    max_records_per_layer: dict[MemoryLayer, int] | None = None

class ForgetReport(MoriModel):
    expired: int
    pruned: int
    deduplicated: int
    contradictions_resolved: int
    total_deleted: int
```

## 8. Backend Interface

```python
class MemoryBackend(Protocol):
    async def insert(self, records: list[MemoryRecord]) -> list[MemoryRecordId]: ...
    async def get(self, record_ids: list[MemoryRecordId]) -> list[MemoryRecord]: ...
    async def update(self, record_id: MemoryRecordId, updates: dict) -> MemoryRecord: ...
    async def delete(self, record_ids: list[MemoryRecordId]) -> int: ...
    async def search(self, embedding: list[float], layer: MemoryLayer | None = None, limit: int = 20, filters: MemoryFilters | None = None) -> list[tuple[MemoryRecord, float]]: ...
    async def list_records(self, layer: MemoryLayer, limit: int = 100, offset: int = 0, order_by: Literal["created_at", "updated_at", "confidence"] = "created_at") -> list[MemoryRecord]: ...
    async def count(self, layer: MemoryLayer | None = None) -> int: ...
    async def close(self) -> None: ...
```

**Included backends:**

| Backend         | Dependencies       | Use Case              |
|-----------------|--------------------|-----------------------|
| InMemoryBackend | None               | Dev/test              |
| SQLiteBackend   | sqlite3, numpy     | Single-user local     |
| PostgresBackend | asyncpg, pgvector  | Multi-user production |

## 9. Embedder Interface

```python
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimensions(self) -> int: ...
```

## 10. Memory Stats

```python
class MemoryStats(MoriModel):
    total_records: int
    records_per_layer: dict[MemoryLayer, int]
    estimated_tokens_per_layer: dict[MemoryLayer, int]
    oldest_record_age_seconds: dict[MemoryLayer, float | None]
    newest_record_age_seconds: dict[MemoryLayer, float | None]
```

## 11. AIUC-1 Contracts

Per `12-AIUC1-COMPLIANCE.md` Section 2.2:
- Every `read()` and `write()` call MUST check the Permission Engine (Spec 06) for READ or WRITE on the target memory layer
- Memory backends MUST namespace records by thread_id for cross-customer isolation (A005)
- The `memory.write.before` hook point MUST be available for PIIGuard scanning (A006)
- All memory operations MUST emit observability events (E015)

## 12. Test Criteria

- [ ] Write followed by read returns the written record when query matches
- [ ] Records with expired TTL are not returned by read()
- [ ] Deduplication merges records above the similarity threshold
- [ ] Promote creates new records in the target layer and preserves source
- [ ] Promote with abstraction_fn produces a single summarized record
- [ ] Forget respects all policy parameters independently
- [ ] Retrieval respects max_tokens budget (never exceeds allocation)
- [ ] Recency bias 0.0 produces pure semantic ranking
- [ ] Recency bias 1.0 produces pure chronological ranking
- [ ] Conflict detection flags contradicting records in MemorySlice
- [ ] InMemoryBackend passes all integration tests
- [ ] SQLiteBackend passes all integration tests with vector search
- [ ] Concurrent writes to the same layer do not corrupt state
- [ ] summarize_layer output fits within the requested token budget
- [ ] Permission Engine is checked before read and write operations
