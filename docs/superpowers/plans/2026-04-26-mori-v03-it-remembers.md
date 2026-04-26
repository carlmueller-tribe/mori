# Mori v0.3 "It Remembers" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four-layer memory with a retrieval pipeline, pluggable backends (InMemory + SQLite), and runtime integration so the agent persists context across steps and runs.

**Architecture:** A `MemoryModule` orchestrates reads/writes through a `MemoryBackend` protocol (InMemory for tests, SQLite for persistence). An `Embedder` protocol (AnthropicEmbedder) generates vector embeddings for semantic search. A 4-stage retrieval pipeline (query expansion → fan-out → scoring → truncation) returns budget-aware `MemorySlice` results. The `AgentLoop` gains retrieve and update phases that fire when memory is configured.

**Tech Stack:** Python 3.11+, pydantic v2, numpy (cosine similarity), sqlite3, anthropic SDK (embeddings via Voyage), pytest + pytest-asyncio

---

## File Structure

### New files

```
mori/
├── memory/
│   ├── __init__.py
│   ├── module.py             # MemoryModule
│   ├── retrieval.py          # 4-stage retrieval pipeline
│   ├── embedder.py           # Embedder protocol + AnthropicEmbedder
│   └── backends/
│       ├── __init__.py
│       ├── base.py            # MemoryBackend protocol
│       ├── inmemory.py        # InMemoryBackend
│       └── sqlite.py          # SQLiteBackend
tests/
├── test_memory_types.py
├── test_embedder.py
├── test_inmemory_backend.py
├── test_sqlite_backend.py
├── test_retrieval.py
├── test_memory_module.py
├── test_loop_v03.py
├── test_builder_v03.py
└── test_integration_v03.py
```

### Modified files

- `mori/types.py` — add MemoryConfig, MemoryFilters, ForgetPolicy, ForgetReport, MemoryStats
- `mori/runtime/state.py` — add `memory_slice` field
- `mori/runtime/loop.py` — add retrieve/update phases, memory context in plan
- `mori/agent.py` — add `.memory_backend()`, expose `agent.memory`
- `mori/observability/events.py` — add MemoryReadEvent, MemoryWriteEvent

---

## Task 1: Memory Types

**Files:**
- Modify: `mori/types.py`
- Test: `tests/test_memory_types.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_memory_types.py`:

```python
"""Tests for v0.3 memory types."""

from datetime import datetime, timezone

from mori.types import (
    MemoryConfig,
    MemoryFilters,
    MemoryLayer,
    MemoryRecordId,
    MemoryStats,
    ForgetPolicy,
    ForgetReport,
)


def test_memory_config_defaults():
    c = MemoryConfig()
    assert c.default_ttl_seconds[MemoryLayer.WORKING] == 3600
    assert c.default_ttl_seconds[MemoryLayer.EPISODIC] is None
    assert c.max_records_per_layer[MemoryLayer.WORKING] == 200
    assert c.deduplication_threshold == 0.95
    assert c.embedding_dimensions == 1536


def test_memory_filters_defaults():
    f = MemoryFilters()
    assert f.min_confidence is None
    assert f.max_age_seconds is None
    assert f.exclude_ids == []


def test_memory_filters_with_values():
    f = MemoryFilters(
        min_confidence=0.5,
        max_age_seconds=3600,
        provenance="tool:search",
        metadata_match={"source": "docs"},
        exclude_ids=[MemoryRecordId("rec_1")],
    )
    assert f.min_confidence == 0.5
    assert len(f.exclude_ids) == 1


def test_forget_policy_defaults():
    p = ForgetPolicy()
    assert p.expire_ttl is True
    assert p.prune_below_confidence == 0.2
    assert p.deduplicate is True


def test_forget_report():
    r = ForgetReport(expired=5, pruned=3, deduplicated=2, total_deleted=10)
    assert r.total_deleted == 10


def test_memory_stats():
    s = MemoryStats(
        total_records=100,
        records_per_layer={
            MemoryLayer.WORKING: 50,
            MemoryLayer.EPISODIC: 30,
            MemoryLayer.SEMANTIC: 15,
            MemoryLayer.PERSONALIZED: 5,
        },
        estimated_tokens_per_layer={
            MemoryLayer.WORKING: 5000,
            MemoryLayer.EPISODIC: 3000,
            MemoryLayer.SEMANTIC: 1500,
            MemoryLayer.PERSONALIZED: 500,
        },
        oldest_record_age_seconds={
            MemoryLayer.WORKING: 3600.0,
            MemoryLayer.EPISODIC: 86400.0,
            MemoryLayer.SEMANTIC: None,
            MemoryLayer.PERSONALIZED: None,
        },
        newest_record_age_seconds={
            MemoryLayer.WORKING: 10.0,
            MemoryLayer.EPISODIC: 300.0,
            MemoryLayer.SEMANTIC: None,
            MemoryLayer.PERSONALIZED: None,
        },
    )
    assert s.total_records == 100
    assert s.records_per_layer[MemoryLayer.WORKING] == 50


def test_memory_config_json_roundtrip():
    c = MemoryConfig()
    json_str = c.model_dump_json()
    restored = MemoryConfig.model_validate_json(json_str)
    assert restored.deduplication_threshold == 0.95
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_types.py -v`
Expected: FAIL — `ImportError` (types don't exist yet)

- [ ] **Step 3: Add memory types to `mori/types.py`**

Read the current file first. Then append before the error hierarchy section (before `class MoriError`):

```python
# ── Memory Config & Lifecycle ────────────────────────────────

class MemoryConfig(MoriModel):
    default_ttl_seconds: dict[MemoryLayer, int | None] = Field(default_factory=lambda: {
        MemoryLayer.WORKING: 3600,
        MemoryLayer.EPISODIC: None,
        MemoryLayer.SEMANTIC: None,
        MemoryLayer.PERSONALIZED: None,
    })
    max_records_per_layer: dict[MemoryLayer, int] = Field(default_factory=lambda: {
        MemoryLayer.WORKING: 200,
        MemoryLayer.EPISODIC: 10_000,
        MemoryLayer.SEMANTIC: 50_000,
        MemoryLayer.PERSONALIZED: 5_000,
    })
    deduplication_threshold: float = 0.95
    conflict_resolution: Literal["highest_confidence", "most_recent", "keep_all"] = "highest_confidence"
    embedding_dimensions: int = 1536
    auto_forget_interval_sec: float = 300.0


class MemoryFilters(MoriModel):
    min_confidence: float | None = None
    max_age_seconds: int | None = None
    provenance: str | None = None
    metadata_match: dict[str, Any] | None = None
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

Note: `MemoryRecord`, `MemorySlice`, and `WriteReceipt` already exist in types.py from v0.1.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_types.py -v`
Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/types.py tests/test_memory_types.py
git commit -m "feat: memory types — MemoryConfig, MemoryFilters, ForgetPolicy, ForgetReport, MemoryStats"
```

---

## Task 2: Embedder Protocol + AnthropicEmbedder

**Files:**
- Create: `mori/memory/__init__.py`
- Create: `mori/memory/embedder.py`
- Test: `tests/test_embedder.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_embedder.py`:

```python
"""Tests for Embedder protocol and AnthropicEmbedder."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mori.memory.embedder import AnthropicEmbedder, Embedder


def test_embedder_is_protocol():
    """Embedder should be a runtime-checkable Protocol."""
    assert hasattr(Embedder, "__protocol_attrs__") or hasattr(Embedder, "_is_runtime_protocol")


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 10 for _ in texts]

    @property
    def dimensions(self) -> int:
        return 10


def test_fake_embedder_satisfies_protocol():
    e = FakeEmbedder()
    assert isinstance(e, Embedder)


async def test_anthropic_embedder_embed():
    with patch("mori.memory.embedder.voyageai") as mock_voyage:
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.embed = MagicMock(return_value=mock_result)
        mock_voyage.Client.return_value = mock_client

        embedder = AnthropicEmbedder(api_key="test-key")
        result = await embedder.embed(["hello", "world"])

        assert len(result) == 2
        assert len(result[0]) == 3
        mock_client.embed.assert_called_once()


def test_anthropic_embedder_dimensions():
    with patch("mori.memory.embedder.voyageai") as mock_voyage:
        mock_voyage.Client.return_value = MagicMock()
        embedder = AnthropicEmbedder(api_key="test-key")
        assert embedder.dimensions == 1024


async def test_anthropic_embedder_empty_input():
    with patch("mori.memory.embedder.voyageai") as mock_voyage:
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.embeddings = []
        mock_client.embed = MagicMock(return_value=mock_result)
        mock_voyage.Client.return_value = mock_client

        embedder = AnthropicEmbedder(api_key="test-key")
        result = await embedder.embed([])
        assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_embedder.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement Embedder**

Create `mori/memory/__init__.py`:

```python
"""Memory module — four-layer memory with retrieval pipeline."""
```

Create `mori/memory/embedder.py`:

```python
"""Embedder protocol and implementations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

try:
    import voyageai
except ImportError:
    voyageai = None  # type: ignore[assignment]


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimensions(self) -> int: ...


class AnthropicEmbedder:
    """Embedder using Voyage AI (Anthropic's embedding partner)."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "voyage-3",
    ) -> None:
        if voyageai is None:
            raise ImportError("Install voyageai: pip install voyageai")
        self._model = model
        self._client = voyageai.Client(api_key=api_key)
        self._dimensions = 1024  # voyage-3 default

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = self._client.embed(texts, model=self._model)
        return result.embeddings

    @property
    def dimensions(self) -> int:
        return self._dimensions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_embedder.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/memory/__init__.py mori/memory/embedder.py tests/test_embedder.py
git commit -m "feat: Embedder protocol + AnthropicEmbedder (Voyage AI)"
```

---

## Task 3: MemoryBackend Protocol + InMemoryBackend

**Files:**
- Create: `mori/memory/backends/__init__.py`
- Create: `mori/memory/backends/base.py`
- Create: `mori/memory/backends/inmemory.py`
- Test: `tests/test_inmemory_backend.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_inmemory_backend.py`:

```python
"""Tests for InMemoryBackend."""

import numpy as np
from datetime import datetime, timezone

import pytest

from mori.memory.backends.inmemory import InMemoryBackend
from mori.types import MemoryLayer, MemoryRecord, MemoryRecordId, MemoryFilters


def _make_record(
    record_id: str = "rec_1",
    layer: MemoryLayer = MemoryLayer.WORKING,
    content: str = "test content",
    embedding: list[float] | None = None,
    confidence: float = 1.0,
) -> MemoryRecord:
    now = datetime.now(timezone.utc)
    return MemoryRecord(
        record_id=MemoryRecordId(record_id),
        layer=layer,
        content=content,
        created_at=now,
        updated_at=now,
        confidence=confidence,
        embedding=embedding or [0.1] * 10,
    )


async def test_insert_and_get():
    backend = InMemoryBackend()
    records = [_make_record("rec_1"), _make_record("rec_2")]
    ids = await backend.insert(records)
    assert len(ids) == 2

    retrieved = await backend.get([MemoryRecordId("rec_1")])
    assert len(retrieved) == 1
    assert retrieved[0].content == "test content"


async def test_get_missing():
    backend = InMemoryBackend()
    retrieved = await backend.get([MemoryRecordId("nonexistent")])
    assert retrieved == []


async def test_update():
    backend = InMemoryBackend()
    await backend.insert([_make_record("rec_1")])
    updated = await backend.update(MemoryRecordId("rec_1"), {"content": "updated content"})
    assert updated.content == "updated content"

    retrieved = await backend.get([MemoryRecordId("rec_1")])
    assert retrieved[0].content == "updated content"


async def test_delete():
    backend = InMemoryBackend()
    await backend.insert([_make_record("rec_1"), _make_record("rec_2")])
    count = await backend.delete([MemoryRecordId("rec_1")])
    assert count == 1

    remaining = await backend.get([MemoryRecordId("rec_1"), MemoryRecordId("rec_2")])
    assert len(remaining) == 1
    assert remaining[0].record_id == "rec_2"


async def test_search_cosine_similarity():
    backend = InMemoryBackend()
    await backend.insert([
        _make_record("rec_1", embedding=[1.0, 0.0, 0.0]),
        _make_record("rec_2", embedding=[0.0, 1.0, 0.0]),
        _make_record("rec_3", embedding=[0.9, 0.1, 0.0]),
    ])

    results = await backend.search(embedding=[1.0, 0.0, 0.0], limit=2)
    assert len(results) == 2
    # rec_1 should be most similar (exact match), rec_3 second
    assert results[0][0].record_id == "rec_1"
    assert results[1][0].record_id == "rec_3"
    assert results[0][1] > results[1][1]  # scores descending


async def test_search_filter_by_layer():
    backend = InMemoryBackend()
    await backend.insert([
        _make_record("rec_1", layer=MemoryLayer.WORKING, embedding=[1.0, 0.0]),
        _make_record("rec_2", layer=MemoryLayer.EPISODIC, embedding=[1.0, 0.0]),
    ])

    results = await backend.search(
        embedding=[1.0, 0.0],
        layer=MemoryLayer.WORKING,
    )
    assert len(results) == 1
    assert results[0][0].record_id == "rec_1"


async def test_search_with_filters():
    backend = InMemoryBackend()
    await backend.insert([
        _make_record("rec_1", confidence=0.9, embedding=[1.0, 0.0]),
        _make_record("rec_2", confidence=0.3, embedding=[1.0, 0.0]),
    ])

    results = await backend.search(
        embedding=[1.0, 0.0],
        filters=MemoryFilters(min_confidence=0.5),
    )
    assert len(results) == 1
    assert results[0][0].record_id == "rec_1"


async def test_list_records():
    backend = InMemoryBackend()
    await backend.insert([
        _make_record("rec_1", layer=MemoryLayer.WORKING),
        _make_record("rec_2", layer=MemoryLayer.WORKING),
        _make_record("rec_3", layer=MemoryLayer.EPISODIC),
    ])

    records = await backend.list_records(MemoryLayer.WORKING)
    assert len(records) == 2


async def test_count():
    backend = InMemoryBackend()
    await backend.insert([
        _make_record("rec_1", layer=MemoryLayer.WORKING),
        _make_record("rec_2", layer=MemoryLayer.EPISODIC),
    ])

    assert await backend.count() == 2
    assert await backend.count(MemoryLayer.WORKING) == 1
    assert await backend.count(MemoryLayer.SEMANTIC) == 0


async def test_close():
    backend = InMemoryBackend()
    await backend.close()  # Should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_inmemory_backend.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement backend protocol and InMemoryBackend**

Create `mori/memory/backends/__init__.py`:

```python
"""Pluggable memory storage backends."""
```

Create `mori/memory/backends/base.py`:

```python
"""MemoryBackend protocol — interface for pluggable storage."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from mori.types import MemoryFilters, MemoryLayer, MemoryRecord, MemoryRecordId


@runtime_checkable
class MemoryBackend(Protocol):
    async def insert(self, records: list[MemoryRecord]) -> list[MemoryRecordId]: ...
    async def get(self, record_ids: list[MemoryRecordId]) -> list[MemoryRecord]: ...
    async def update(self, record_id: MemoryRecordId, updates: dict[str, Any]) -> MemoryRecord: ...
    async def delete(self, record_ids: list[MemoryRecordId]) -> int: ...
    async def search(
        self, embedding: list[float], layer: MemoryLayer | None = None,
        limit: int = 20, filters: MemoryFilters | None = None,
    ) -> list[tuple[MemoryRecord, float]]: ...
    async def list_records(
        self, layer: MemoryLayer, limit: int = 100, offset: int = 0,
        order_by: Literal["created_at", "updated_at", "confidence"] = "created_at",
    ) -> list[MemoryRecord]: ...
    async def count(self, layer: MemoryLayer | None = None) -> int: ...
    async def close(self) -> None: ...
```

Create `mori/memory/backends/inmemory.py`:

```python
"""InMemoryBackend — dict + numpy cosine similarity for dev/test."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np

from mori.types import MemoryFilters, MemoryLayer, MemoryRecord, MemoryRecordId


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(dot / norm)


class InMemoryBackend:
    """In-memory storage with numpy cosine similarity search."""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    async def insert(self, records: list[MemoryRecord]) -> list[MemoryRecordId]:
        ids: list[MemoryRecordId] = []
        for record in records:
            self._records[record.record_id] = record
            ids.append(record.record_id)
        return ids

    async def get(self, record_ids: list[MemoryRecordId]) -> list[MemoryRecord]:
        return [self._records[rid] for rid in record_ids if rid in self._records]

    async def update(self, record_id: MemoryRecordId, updates: dict[str, Any]) -> MemoryRecord:
        record = self._records[record_id]
        data = record.model_dump()
        data.update(updates)
        data["updated_at"] = datetime.now(timezone.utc)
        updated = MemoryRecord(**data)
        self._records[record_id] = updated
        return updated

    async def delete(self, record_ids: list[MemoryRecordId]) -> int:
        count = 0
        for rid in record_ids:
            if rid in self._records:
                del self._records[rid]
                count += 1
        return count

    async def search(
        self,
        embedding: list[float],
        layer: MemoryLayer | None = None,
        limit: int = 20,
        filters: MemoryFilters | None = None,
    ) -> list[tuple[MemoryRecord, float]]:
        candidates = list(self._records.values())

        if layer is not None:
            candidates = [r for r in candidates if r.layer == layer]

        if filters:
            if filters.min_confidence is not None:
                candidates = [r for r in candidates if r.confidence >= filters.min_confidence]
            if filters.max_age_seconds is not None:
                now = datetime.now(timezone.utc)
                candidates = [
                    r for r in candidates
                    if (now - r.created_at).total_seconds() <= filters.max_age_seconds
                ]
            if filters.exclude_ids:
                exclude_set = set(filters.exclude_ids)
                candidates = [r for r in candidates if r.record_id not in exclude_set]
            if filters.provenance is not None:
                candidates = [r for r in candidates if r.provenance == filters.provenance]

        scored: list[tuple[MemoryRecord, float]] = []
        for record in candidates:
            if record.embedding:
                sim = _cosine_similarity(embedding, record.embedding)
                scored.append((record, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def list_records(
        self,
        layer: MemoryLayer,
        limit: int = 100,
        offset: int = 0,
        order_by: Literal["created_at", "updated_at", "confidence"] = "created_at",
    ) -> list[MemoryRecord]:
        records = [r for r in self._records.values() if r.layer == layer]
        records.sort(key=lambda r: getattr(r, order_by), reverse=(order_by == "confidence"))
        return records[offset : offset + limit]

    async def count(self, layer: MemoryLayer | None = None) -> int:
        if layer is None:
            return len(self._records)
        return sum(1 for r in self._records.values() if r.layer == layer)

    async def close(self) -> None:
        self._records.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_inmemory_backend.py -v`
Expected: all 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/memory/backends/__init__.py mori/memory/backends/base.py mori/memory/backends/inmemory.py tests/test_inmemory_backend.py
git commit -m "feat: MemoryBackend protocol + InMemoryBackend with cosine search"
```

---

## Task 4: Retrieval Pipeline

**Files:**
- Create: `mori/memory/retrieval.py`
- Test: `tests/test_retrieval.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_retrieval.py`:

```python
"""Tests for the 4-stage retrieval pipeline."""

import math
from datetime import datetime, timezone, timedelta

import pytest

from mori.memory.backends.inmemory import InMemoryBackend
from mori.memory.embedder import Embedder
from mori.memory.retrieval import retrieve
from mori.types import MemoryLayer, MemoryRecord, MemoryRecordId, MemorySlice


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Simple deterministic embedding: hash-based
        results = []
        for text in texts:
            vec = [0.0] * 10
            for i, ch in enumerate(text[:10]):
                vec[i % 10] += ord(ch) / 1000.0
            # Normalize
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            results.append([v / norm for v in vec])
        return results

    @property
    def dimensions(self) -> int:
        return 10


async def _populated_backend() -> InMemoryBackend:
    embedder = FakeEmbedder()
    backend = InMemoryBackend()
    now = datetime.now(timezone.utc)

    records = [
        MemoryRecord(
            record_id=MemoryRecordId("rec_auth"),
            layer=MemoryLayer.WORKING,
            content="Authentication uses JWT tokens with 1-hour expiry",
            created_at=now - timedelta(minutes=5),
            updated_at=now,
            embedding=(await embedder.embed(["Authentication uses JWT tokens"]))[0],
        ),
        MemoryRecord(
            record_id=MemoryRecordId("rec_db"),
            layer=MemoryLayer.EPISODIC,
            content="Database migration completed for user table",
            created_at=now - timedelta(hours=2),
            updated_at=now,
            embedding=(await embedder.embed(["Database migration completed"]))[0],
        ),
        MemoryRecord(
            record_id=MemoryRecordId("rec_api"),
            layer=MemoryLayer.SEMANTIC,
            content="REST API follows OpenAPI 3.0 specification",
            created_at=now - timedelta(days=7),
            updated_at=now,
            embedding=(await embedder.embed(["REST API follows OpenAPI"]))[0],
        ),
    ]
    await backend.insert(records)
    return backend


async def test_retrieve_returns_memory_slice():
    backend = await _populated_backend()
    embedder = FakeEmbedder()

    result = await retrieve(
        query="authentication",
        task_context="research auth system",
        backend=backend,
        embedder=embedder,
    )

    assert isinstance(result, MemorySlice)
    assert len(result.records) > 0


async def test_retrieve_respects_max_tokens():
    backend = await _populated_backend()
    embedder = FakeEmbedder()

    result = await retrieve(
        query="test",
        task_context="",
        backend=backend,
        embedder=embedder,
        max_tokens=10,  # Very small budget
    )

    total_tokens = sum(len(r.content) // 4 for r in result.records)
    assert total_tokens <= 10 or len(result.records) <= 1  # At least one record allowed
    assert result.truncated is True or len(result.records) <= 1


async def test_retrieve_filter_by_layer():
    backend = await _populated_backend()
    embedder = FakeEmbedder()

    result = await retrieve(
        query="test",
        task_context="",
        backend=backend,
        embedder=embedder,
        layers=[MemoryLayer.WORKING],
    )

    for record in result.records:
        assert record.layer == MemoryLayer.WORKING


async def test_retrieve_recency_bias_zero_pure_semantic():
    backend = await _populated_backend()
    embedder = FakeEmbedder()

    result = await retrieve(
        query="authentication JWT",
        task_context="",
        backend=backend,
        embedder=embedder,
        recency_bias=0.0,
    )

    assert len(result.records) > 0
    # With 0 recency bias, ranking is pure semantic similarity


async def test_retrieve_recency_bias_one_pure_chronological():
    backend = await _populated_backend()
    embedder = FakeEmbedder()

    result = await retrieve(
        query="anything",
        task_context="",
        backend=backend,
        embedder=embedder,
        recency_bias=1.0,
    )

    if len(result.records) >= 2:
        # Most recent should be first
        assert result.records[0].created_at >= result.records[1].created_at


async def test_retrieve_conflicts_empty():
    """Conflict detection is stubbed — always returns empty list."""
    backend = await _populated_backend()
    embedder = FakeEmbedder()

    result = await retrieve(
        query="test",
        task_context="",
        backend=backend,
        embedder=embedder,
    )

    assert result.conflicts == []


async def test_retrieve_empty_backend():
    backend = InMemoryBackend()
    embedder = FakeEmbedder()

    result = await retrieve(
        query="test",
        task_context="",
        backend=backend,
        embedder=embedder,
    )

    assert result.records == []
    assert result.truncated is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_retrieval.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement retrieval pipeline**

Create `mori/memory/retrieval.py`:

```python
"""4-stage retrieval pipeline for memory reads."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from mori.memory.backends.base import MemoryBackend
from mori.memory.embedder import Embedder
from mori.types import (
    MemoryFilters,
    MemoryLayer,
    MemoryRecord,
    MemoryRecordId,
    MemorySlice,
)


def _recency_score(created_at: datetime) -> float:
    """Exponential decay: 1h ago ~ 0.96, 1d ago ~ 0.37, 7d ago ~ 0.001."""
    now = datetime.now(timezone.utc)
    age_seconds = max(0.0, (now - created_at).total_seconds())
    return math.exp(-age_seconds / 86400.0)


async def retrieve(
    query: str,
    task_context: str,
    backend: MemoryBackend,
    embedder: Embedder,
    layers: list[MemoryLayer] | None = None,
    max_tokens: int = 2000,
    recency_bias: float = 0.3,
    filters: MemoryFilters | None = None,
) -> MemorySlice:
    """Run the 4-stage retrieval pipeline."""

    # Stage 1: Query Expansion
    expanded_query = f"{query} {task_context}".strip()

    # Stage 2: Multi-Layer Fan-Out
    embeddings = await embedder.embed([expanded_query])
    if not embeddings:
        return MemorySlice(
            records=[], total_tokens=0, query=query,
            layers_searched=layers or list(MemoryLayer), truncated=False,
        )

    query_embedding = embeddings[0]
    search_layers = layers or list(MemoryLayer)

    all_results: list[tuple[MemoryRecord, float]] = []
    for layer in search_layers:
        results = await backend.search(
            embedding=query_embedding, layer=layer, limit=20, filters=filters,
        )
        all_results.extend(results)

    # Stage 3: Relevance Scoring
    scored: list[tuple[MemoryRecord, float]] = []
    for record, semantic_sim in all_results:
        recency = _recency_score(record.created_at)
        composite = (1.0 - recency_bias) * semantic_sim + recency_bias * recency
        scored.append((record, composite))

    scored.sort(key=lambda x: x[1], reverse=True)

    # Stage 4: Budget-Aware Truncation
    selected: list[MemoryRecord] = []
    total_tokens = 0
    truncated = False

    for record, score in scored:
        record_tokens = len(record.content) // 4
        if total_tokens + record_tokens > max_tokens and selected:
            truncated = True
            break
        selected.append(record)
        total_tokens += record_tokens

    # Stage 5: Conflict Detection (stubbed)
    conflicts: list[tuple[MemoryRecordId, MemoryRecordId]] = []

    return MemorySlice(
        records=selected,
        total_tokens=total_tokens,
        query=query,
        layers_searched=search_layers,
        truncated=truncated,
        conflicts=conflicts,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_retrieval.py -v`
Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/memory/retrieval.py tests/test_retrieval.py
git commit -m "feat: 4-stage retrieval pipeline — query expansion, fan-out, scoring, truncation"
```

---

## Task 5: MemoryModule

**Files:**
- Create: `mori/memory/module.py`
- Test: `tests/test_memory_module.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_memory_module.py`:

```python
"""Tests for MemoryModule — orchestrates backends and retrieval."""

import math
from datetime import datetime, timezone, timedelta

import pytest

from mori.memory.backends.inmemory import InMemoryBackend
from mori.memory.module import MemoryModule
from mori.types import (
    ForgetPolicy,
    MemoryConfig,
    MemoryLayer,
    MemoryRecord,
    MemoryRecordId,
    MemorySlice,
    WriteReceipt,
)


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            vec = [0.0] * 10
            for i, ch in enumerate(text[:10]):
                vec[i % 10] += ord(ch) / 1000.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            results.append([v / norm for v in vec])
        return results

    @property
    def dimensions(self) -> int:
        return 10


def _make_record(
    record_id: str,
    layer: MemoryLayer = MemoryLayer.WORKING,
    content: str = "test",
    confidence: float = 1.0,
    ttl_seconds: int | None = None,
    created_at: datetime | None = None,
) -> MemoryRecord:
    now = created_at or datetime.now(timezone.utc)
    return MemoryRecord(
        record_id=MemoryRecordId(record_id),
        layer=layer,
        content=content,
        created_at=now,
        updated_at=now,
        confidence=confidence,
        ttl_seconds=ttl_seconds,
    )


@pytest.fixture
def module():
    backend = InMemoryBackend()
    embedder = FakeEmbedder()
    return MemoryModule(backend=backend, config=MemoryConfig(), embedder=embedder)


async def test_write_and_read(module):
    records = [_make_record("rec_1", content="authentication uses JWT")]
    receipt = await module.write(records)
    assert isinstance(receipt, WriteReceipt)
    assert len(receipt.record_ids) == 1

    result = await module.read("authentication")
    assert isinstance(result, MemorySlice)
    assert len(result.records) == 1


async def test_read_by_ids(module):
    await module.write([_make_record("rec_1", content="hello")])
    records = await module.read_by_ids([MemoryRecordId("rec_1")])
    assert len(records) == 1
    assert records[0].content == "hello"


async def test_update(module):
    await module.write([_make_record("rec_1", content="old")])
    updated = await module.update(MemoryRecordId("rec_1"), content="new")
    assert updated.content == "new"


async def test_delete(module):
    await module.write([
        _make_record("rec_1"),
        _make_record("rec_2"),
    ])
    count = await module.delete([MemoryRecordId("rec_1")])
    assert count == 1

    stats = await module.stats()
    assert stats.total_records == 1


async def test_promote(module):
    await module.write([
        _make_record("rec_1", layer=MemoryLayer.WORKING, content="learned fact"),
    ])
    new_ids = await module.promote(
        source_layer=MemoryLayer.WORKING,
        target_layer=MemoryLayer.SEMANTIC,
        record_ids=[MemoryRecordId("rec_1")],
    )
    assert len(new_ids) == 1

    stats = await module.stats()
    assert stats.records_per_layer[MemoryLayer.SEMANTIC] == 1
    # Source record should still exist
    assert stats.records_per_layer[MemoryLayer.WORKING] == 1


async def test_forget_expires_ttl(module):
    expired_record = _make_record(
        "rec_old",
        ttl_seconds=1,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    await module.write([expired_record])

    report = await module.forget(ForgetPolicy(expire_ttl=True, prune_below_confidence=None, deduplicate=False))
    assert report.expired >= 1
    assert report.total_deleted >= 1


async def test_forget_prunes_low_confidence(module):
    await module.write([
        _make_record("rec_low", confidence=0.1),
        _make_record("rec_high", confidence=0.9),
    ])

    report = await module.forget(ForgetPolicy(expire_ttl=False, prune_below_confidence=0.5, deduplicate=False))
    assert report.pruned >= 1

    stats = await module.stats()
    assert stats.total_records == 1


async def test_stats(module):
    await module.write([
        _make_record("rec_1", layer=MemoryLayer.WORKING),
        _make_record("rec_2", layer=MemoryLayer.EPISODIC),
        _make_record("rec_3", layer=MemoryLayer.WORKING),
    ])

    stats = await module.stats()
    assert stats.total_records == 3
    assert stats.records_per_layer[MemoryLayer.WORKING] == 2
    assert stats.records_per_layer[MemoryLayer.EPISODIC] == 1


async def test_summarize_layer_fallback(module):
    """Without a model, summarize_layer falls back to concatenate + truncate."""
    await module.write([
        _make_record("rec_1", layer=MemoryLayer.WORKING, content="Auth uses JWT"),
        _make_record("rec_2", layer=MemoryLayer.WORKING, content="DB uses Postgres"),
    ])

    summary = await module.summarize_layer(MemoryLayer.WORKING, max_tokens=50)
    assert "JWT" in summary or "Postgres" in summary
    assert len(summary) > 0


async def test_close(module):
    await module.close()  # Should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_module.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement MemoryModule**

Create `mori/memory/module.py`:

```python
"""MemoryModule — orchestrates memory backends and retrieval."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Callable

from mori.memory.backends.base import MemoryBackend
from mori.memory.embedder import Embedder
from mori.memory.retrieval import retrieve
from mori.types import (
    ForgetPolicy,
    ForgetReport,
    MemoryConfig,
    MemoryFilters,
    MemoryLayer,
    MemoryRecord,
    MemoryRecordId,
    MemorySlice,
    MemoryStats,
    WriteReceipt,
)


class MemoryModule:
    """Orchestrates memory reads, writes, and lifecycle operations."""

    def __init__(
        self,
        backend: MemoryBackend,
        config: MemoryConfig,
        embedder: Embedder | None = None,
        model: Any = None,
    ) -> None:
        self._backend = backend
        self._config = config
        self._embedder = embedder
        self._model = model

    async def read(
        self,
        query: str,
        layers: list[MemoryLayer] | None = None,
        max_tokens: int = 2000,
        recency_bias: float = 0.3,
        filters: MemoryFilters | None = None,
        task_context: str = "",
    ) -> MemorySlice:
        if self._embedder is None:
            return MemorySlice(
                records=[], total_tokens=0, query=query,
                layers_searched=layers or list(MemoryLayer), truncated=False,
            )
        return await retrieve(
            query=query,
            task_context=task_context,
            backend=self._backend,
            embedder=self._embedder,
            layers=layers,
            max_tokens=max_tokens,
            recency_bias=recency_bias,
            filters=filters,
        )

    async def read_by_ids(self, record_ids: list[MemoryRecordId]) -> list[MemoryRecord]:
        return await self._backend.get(record_ids)

    async def write(self, records: list[MemoryRecord]) -> WriteReceipt:
        # Generate embeddings for records without them
        if self._embedder:
            texts_to_embed = []
            indices = []
            for i, record in enumerate(records):
                if not record.embedding:
                    texts_to_embed.append(record.content)
                    indices.append(i)

            if texts_to_embed:
                embeddings = await self._embedder.embed(texts_to_embed)
                for idx, embedding in zip(indices, embeddings):
                    records[idx].embedding = embedding

        ids = await self._backend.insert(records)
        layer = records[0].layer if records else MemoryLayer.WORKING
        return WriteReceipt(
            record_ids=ids,
            layer=layer,
            timestamp=datetime.now(timezone.utc),
        )

    async def update(
        self,
        record_id: MemoryRecordId,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        confidence: float | None = None,
    ) -> MemoryRecord:
        updates: dict[str, Any] = {}
        if content is not None:
            updates["content"] = content
            if self._embedder:
                embeddings = await self._embedder.embed([content])
                updates["embedding"] = embeddings[0]
        if metadata is not None:
            updates["metadata"] = metadata
        if confidence is not None:
            updates["confidence"] = confidence
        return await self._backend.update(record_id, updates)

    async def delete(self, record_ids: list[MemoryRecordId]) -> int:
        return await self._backend.delete(record_ids)

    async def promote(
        self,
        source_layer: MemoryLayer,
        target_layer: MemoryLayer,
        record_ids: list[MemoryRecordId],
        abstraction_fn: Callable[..., Any] | None = None,
    ) -> list[MemoryRecordId]:
        source_records = await self._backend.get(record_ids)
        new_records: list[MemoryRecord] = []
        now = datetime.now(timezone.utc)

        if abstraction_fn and source_records:
            # Combine into a single abstracted record
            combined_content = abstraction_fn([r.content for r in source_records])
            new_record = MemoryRecord(
                record_id=MemoryRecordId(f"mem_{secrets.token_hex(12)}"),
                layer=target_layer,
                content=combined_content,
                created_at=now,
                updated_at=now,
                provenance=f"promoted_from:{source_layer.value}",
            )
            new_records.append(new_record)
        else:
            for record in source_records:
                new_record = MemoryRecord(
                    record_id=MemoryRecordId(f"mem_{secrets.token_hex(12)}"),
                    layer=target_layer,
                    content=record.content,
                    metadata=record.metadata,
                    created_at=now,
                    updated_at=now,
                    confidence=record.confidence,
                    embedding=record.embedding,
                    provenance=f"promoted_from:{source_layer.value}",
                )
                new_records.append(new_record)

        return await self._backend.insert(new_records)

    async def forget(self, policy: ForgetPolicy | None = None) -> ForgetReport:
        if policy is None:
            policy = ForgetPolicy()

        expired = 0
        pruned = 0
        deduplicated = 0
        to_delete: list[MemoryRecordId] = []

        for layer in MemoryLayer:
            records = await self._backend.list_records(layer, limit=100_000)
            now = datetime.now(timezone.utc)

            for record in records:
                # TTL expiry
                if policy.expire_ttl and record.ttl_seconds is not None:
                    age = (now - record.created_at).total_seconds()
                    if age > record.ttl_seconds:
                        to_delete.append(record.record_id)
                        expired += 1
                        continue

                # Low confidence pruning
                if policy.prune_below_confidence is not None:
                    if record.confidence < policy.prune_below_confidence:
                        to_delete.append(record.record_id)
                        pruned += 1
                        continue

        if to_delete:
            await self._backend.delete(to_delete)

        total = expired + pruned + deduplicated
        return ForgetReport(
            expired=expired,
            pruned=pruned,
            deduplicated=deduplicated,
            total_deleted=total,
        )

    async def summarize_layer(self, layer: MemoryLayer, max_tokens: int = 500) -> str:
        records = await self._backend.list_records(layer, limit=100)
        if not records:
            return ""

        # Concatenate + truncate fallback (model-based summarization deferred to when model is available)
        parts = [r.content for r in records]
        combined = "\n".join(parts)
        max_chars = max_tokens * 4
        if len(combined) > max_chars:
            combined = combined[:max_chars]
        return combined

    async def stats(self) -> MemoryStats:
        total = await self._backend.count()
        records_per_layer: dict[MemoryLayer, int] = {}
        estimated_tokens: dict[MemoryLayer, int] = {}
        oldest: dict[MemoryLayer, float | None] = {}
        newest: dict[MemoryLayer, float | None] = {}
        now = datetime.now(timezone.utc)

        for layer in MemoryLayer:
            count = await self._backend.count(layer)
            records_per_layer[layer] = count

            records = await self._backend.list_records(layer, limit=1000)
            tokens = sum(len(r.content) // 4 for r in records)
            estimated_tokens[layer] = tokens

            if records:
                ages = [(now - r.created_at).total_seconds() for r in records]
                oldest[layer] = max(ages)
                newest[layer] = min(ages)
            else:
                oldest[layer] = None
                newest[layer] = None

        return MemoryStats(
            total_records=total,
            records_per_layer=records_per_layer,
            estimated_tokens_per_layer=estimated_tokens,
            oldest_record_age_seconds=oldest,
            newest_record_age_seconds=newest,
        )

    async def close(self) -> None:
        await self._backend.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_module.py -v`
Expected: all 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/memory/module.py tests/test_memory_module.py
git commit -m "feat: MemoryModule — read, write, promote, forget, summarize, stats"
```

---

## Task 6: SQLite Backend

**Files:**
- Create: `mori/memory/backends/sqlite.py`
- Test: `tests/test_sqlite_backend.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sqlite_backend.py`:

```python
"""Tests for SQLiteBackend — uses real sqlite3 database."""

import numpy as np
from datetime import datetime, timezone

import pytest

from mori.memory.backends.sqlite import SQLiteBackend
from mori.types import MemoryLayer, MemoryRecord, MemoryRecordId, MemoryFilters


def _make_record(
    record_id: str = "rec_1",
    layer: MemoryLayer = MemoryLayer.WORKING,
    content: str = "test content",
    embedding: list[float] | None = None,
    confidence: float = 1.0,
) -> MemoryRecord:
    now = datetime.now(timezone.utc)
    return MemoryRecord(
        record_id=MemoryRecordId(record_id),
        layer=layer,
        content=content,
        created_at=now,
        updated_at=now,
        confidence=confidence,
        embedding=embedding or [0.1] * 10,
    )


@pytest.fixture
async def backend(tmp_path):
    path = str(tmp_path / "test_memory.db")
    b = SQLiteBackend(path=path)
    await b.initialize()
    yield b
    await b.close()


async def test_insert_and_get(backend):
    ids = await backend.insert([_make_record("rec_1")])
    assert len(ids) == 1

    records = await backend.get([MemoryRecordId("rec_1")])
    assert len(records) == 1
    assert records[0].content == "test content"


async def test_update(backend):
    await backend.insert([_make_record("rec_1")])
    updated = await backend.update(MemoryRecordId("rec_1"), {"content": "new content"})
    assert updated.content == "new content"


async def test_delete(backend):
    await backend.insert([_make_record("rec_1"), _make_record("rec_2")])
    count = await backend.delete([MemoryRecordId("rec_1")])
    assert count == 1

    remaining = await backend.get([MemoryRecordId("rec_1"), MemoryRecordId("rec_2")])
    assert len(remaining) == 1


async def test_search(backend):
    await backend.insert([
        _make_record("rec_1", embedding=[1.0, 0.0, 0.0]),
        _make_record("rec_2", embedding=[0.0, 1.0, 0.0]),
        _make_record("rec_3", embedding=[0.9, 0.1, 0.0]),
    ])

    results = await backend.search(embedding=[1.0, 0.0, 0.0], limit=2)
    assert len(results) == 2
    assert results[0][0].record_id == "rec_1"


async def test_search_filter_by_layer(backend):
    await backend.insert([
        _make_record("rec_1", layer=MemoryLayer.WORKING, embedding=[1.0, 0.0]),
        _make_record("rec_2", layer=MemoryLayer.EPISODIC, embedding=[1.0, 0.0]),
    ])

    results = await backend.search(embedding=[1.0, 0.0], layer=MemoryLayer.WORKING)
    assert len(results) == 1


async def test_list_records(backend):
    await backend.insert([
        _make_record("rec_1", layer=MemoryLayer.WORKING),
        _make_record("rec_2", layer=MemoryLayer.WORKING),
        _make_record("rec_3", layer=MemoryLayer.EPISODIC),
    ])

    records = await backend.list_records(MemoryLayer.WORKING)
    assert len(records) == 2


async def test_count(backend):
    await backend.insert([
        _make_record("rec_1", layer=MemoryLayer.WORKING),
        _make_record("rec_2", layer=MemoryLayer.EPISODIC),
    ])

    assert await backend.count() == 2
    assert await backend.count(MemoryLayer.WORKING) == 1


async def test_persistence(tmp_path):
    """Data survives close and reopen."""
    path = str(tmp_path / "persist.db")

    b1 = SQLiteBackend(path=path)
    await b1.initialize()
    await b1.insert([_make_record("rec_1", content="persistent")])
    await b1.close()

    b2 = SQLiteBackend(path=path)
    await b2.initialize()
    records = await b2.get([MemoryRecordId("rec_1")])
    assert len(records) == 1
    assert records[0].content == "persistent"
    await b2.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sqlite_backend.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement SQLiteBackend**

Create `mori/memory/backends/sqlite.py`:

```python
"""SQLiteBackend — sqlite3 + numpy cosine similarity for local persistence."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np

from mori.types import MemoryFilters, MemoryLayer, MemoryRecord, MemoryRecordId


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(dot / norm)


class SQLiteBackend:
    """SQLite-based memory backend with numpy vector search."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None

    async def initialize(self) -> None:
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_records (
                record_id TEXT PRIMARY KEY,
                layer TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                ttl_seconds INTEGER,
                provenance TEXT,
                confidence REAL DEFAULT 1.0,
                embedding BLOB
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_layer ON memory_records(layer)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON memory_records(created_at)")
        self._conn.commit()

    def _record_to_row(self, record: MemoryRecord) -> tuple:
        embedding_blob = None
        if record.embedding:
            embedding_blob = np.array(record.embedding, dtype=np.float32).tobytes()
        return (
            record.record_id,
            record.layer.value,
            record.content,
            json.dumps(record.metadata) if record.metadata else None,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
            record.ttl_seconds,
            record.provenance,
            record.confidence,
            embedding_blob,
        )

    def _row_to_record(self, row: tuple) -> MemoryRecord:
        embedding = None
        if row[9]:
            embedding = np.frombuffer(row[9], dtype=np.float32).tolist()
        return MemoryRecord(
            record_id=MemoryRecordId(row[0]),
            layer=MemoryLayer(row[1]),
            content=row[2],
            metadata=json.loads(row[3]) if row[3] else {},
            created_at=datetime.fromisoformat(row[4]),
            updated_at=datetime.fromisoformat(row[5]),
            ttl_seconds=row[6],
            provenance=row[7],
            confidence=row[8],
            embedding=embedding,
        )

    async def insert(self, records: list[MemoryRecord]) -> list[MemoryRecordId]:
        assert self._conn is not None
        ids: list[MemoryRecordId] = []
        for record in records:
            row = self._record_to_row(record)
            self._conn.execute(
                "INSERT OR REPLACE INTO memory_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            ids.append(record.record_id)
        self._conn.commit()
        return ids

    async def get(self, record_ids: list[MemoryRecordId]) -> list[MemoryRecord]:
        assert self._conn is not None
        placeholders = ",".join("?" for _ in record_ids)
        cursor = self._conn.execute(
            f"SELECT * FROM memory_records WHERE record_id IN ({placeholders})",
            [str(rid) for rid in record_ids],
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    async def update(self, record_id: MemoryRecordId, updates: dict[str, Any]) -> MemoryRecord:
        assert self._conn is not None
        records = await self.get([record_id])
        if not records:
            raise KeyError(f"Record {record_id} not found")

        data = records[0].model_dump()
        data.update(updates)
        data["updated_at"] = datetime.now(timezone.utc)
        updated = MemoryRecord(**data)

        row = self._record_to_row(updated)
        self._conn.execute(
            "INSERT OR REPLACE INTO memory_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
        self._conn.commit()
        return updated

    async def delete(self, record_ids: list[MemoryRecordId]) -> int:
        assert self._conn is not None
        count = 0
        for rid in record_ids:
            cursor = self._conn.execute(
                "DELETE FROM memory_records WHERE record_id = ?", (str(rid),)
            )
            count += cursor.rowcount
        self._conn.commit()
        return count

    async def search(
        self,
        embedding: list[float],
        layer: MemoryLayer | None = None,
        limit: int = 20,
        filters: MemoryFilters | None = None,
    ) -> list[tuple[MemoryRecord, float]]:
        assert self._conn is not None
        query = "SELECT * FROM memory_records WHERE embedding IS NOT NULL"
        params: list[Any] = []

        if layer is not None:
            query += " AND layer = ?"
            params.append(layer.value)

        if filters:
            if filters.min_confidence is not None:
                query += " AND confidence >= ?"
                params.append(filters.min_confidence)
            if filters.provenance is not None:
                query += " AND provenance = ?"
                params.append(filters.provenance)

        cursor = self._conn.execute(query, params)
        rows = cursor.fetchall()

        scored: list[tuple[MemoryRecord, float]] = []
        for row in rows:
            record = self._row_to_record(row)
            if record.embedding:
                sim = _cosine_similarity(embedding, record.embedding)
                scored.append((record, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def list_records(
        self,
        layer: MemoryLayer,
        limit: int = 100,
        offset: int = 0,
        order_by: Literal["created_at", "updated_at", "confidence"] = "created_at",
    ) -> list[MemoryRecord]:
        assert self._conn is not None
        direction = "DESC" if order_by == "confidence" else "ASC"
        cursor = self._conn.execute(
            f"SELECT * FROM memory_records WHERE layer = ? ORDER BY {order_by} {direction} LIMIT ? OFFSET ?",
            (layer.value, limit, offset),
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    async def count(self, layer: MemoryLayer | None = None) -> int:
        assert self._conn is not None
        if layer is None:
            cursor = self._conn.execute("SELECT COUNT(*) FROM memory_records")
        else:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM memory_records WHERE layer = ?", (layer.value,)
            )
        return cursor.fetchone()[0]

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sqlite_backend.py -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/memory/backends/sqlite.py tests/test_sqlite_backend.py
git commit -m "feat: SQLiteBackend — persistent memory with numpy vector search"
```

---

## Task 7: Memory Observability Events

**Files:**
- Modify: `mori/observability/events.py`
- Test: `tests/test_memory_events.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_memory_events.py`:

```python
"""Tests for memory observability events."""

from datetime import datetime, timezone

from mori.observability.events import MemoryReadEvent, MemoryWriteEvent
from mori.types import MemoryLayer, RunId


def test_memory_read_event():
    e = MemoryReadEvent(
        event_id="evt_1",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        query="authentication",
        layers=[MemoryLayer.WORKING, MemoryLayer.EPISODIC],
        records_returned=5,
        tokens_consumed=500,
        duration_ms=15.0,
    )
    assert e.event_type == "memory.read"
    assert e.records_returned == 5


def test_memory_write_event():
    e = MemoryWriteEvent(
        event_id="evt_2",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        layer=MemoryLayer.WORKING,
        record_ids=["rec_1", "rec_2"],
        records_written=2,
    )
    assert e.event_type == "memory.write"
    assert e.records_written == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_memory_events.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Add events to `mori/observability/events.py`**

Read the file first. Then add after `BoundViolationEvent`, before `SpanContext`:

```python
# ── Memory Events ────────────────────────────────────────────

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

Also add `MemoryLayer` to the imports from `mori.types`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_memory_events.py -v`
Expected: all 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/observability/events.py tests/test_memory_events.py
git commit -m "feat: MemoryReadEvent and MemoryWriteEvent observability events"
```

---

## Task 8: MoriState memory_slice Field

**Files:**
- Modify: `mori/runtime/state.py`
- Test: `tests/test_state.py` (add test)

- [ ] **Step 1: Add test**

Append to `tests/test_state.py`:

```python
from mori.types import MemorySlice, MemoryLayer


def test_state_memory_slice_default_none():
    s = _make_state()
    assert s.memory_slice is None


def test_state_memory_slice_settable():
    s = _make_state()
    s.memory_slice = MemorySlice(
        records=[], total_tokens=0, query="test",
        layers_searched=[MemoryLayer.WORKING], truncated=False,
    )
    assert s.memory_slice is not None
    assert s.memory_slice.query == "test"
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_state.py -v`
Expected: FAIL on the new tests (memory_slice not a field)

- [ ] **Step 3: Add field to MoriState**

Read `mori/runtime/state.py`. Add to the MoriState class, after the `status` field:

```python
    # Memory
    memory_slice: MemorySlice | None = None
```

Also add `MemorySlice` to the imports from `mori.types`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_state.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/runtime/state.py tests/test_state.py
git commit -m "feat: add memory_slice field to MoriState"
```

---

## Task 9: Loop Integration — Retrieve and Update Phases

**Files:**
- Modify: `mori/runtime/loop.py`
- Test: `tests/test_loop_v03.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_loop_v03.py`:

```python
"""Tests for v0.3 loop — memory retrieve and update phases."""

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from mori.control.bounds import ControlBounds, ControlConfig
from mori.memory.backends.inmemory import InMemoryBackend
from mori.memory.module import MemoryModule
from mori.model.base import ModelAdapter
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import ObservabilityConfig
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import (
    MemoryConfig,
    MemoryLayer,
    MemoryRecord,
    MemoryRecordId,
    Message,
    ModelResponse,
    RunStatus,
    ToolCall,
    TokenUsage,
)


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            vec = [0.0] * 10
            for i, ch in enumerate(text[:10]):
                vec[i % 10] += ord(ch) / 1000.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            results.append([v / norm for v in vec])
        return results

    @property
    def dimensions(self) -> int:
        return 10


def _text_response(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="end_turn",
    )


def _tool_response(tool_id: str, name: str, args: dict) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content="",
            tool_calls=[ToolCall(id=tool_id, name=name, arguments=args)]),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="tool_use",
    )


@pytest.fixture
def mock_model():
    model = AsyncMock(spec=ModelAdapter)
    model.model_id = "test"
    model.supports_tool_use = True
    model.max_context_tokens = 100000
    return model


@pytest.fixture
def memory_module():
    backend = InMemoryBackend()
    embedder = FakeEmbedder()
    return MemoryModule(backend=backend, config=MemoryConfig(), embedder=embedder)


async def test_loop_writes_working_memory(mock_model, memory_module):
    """Loop should write working memory records during update phase."""
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_response("call_1", "add", {"a": 1, "b": 2}),
        _text_response("1 + 2 = 3"),
    ])

    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")

    loop = AgentLoop(model=mock_model, tools=registry, memory=memory_module)
    result = await loop.run("Add 1+2")

    assert result.status == RunStatus.COMPLETED
    stats = await memory_module.stats()
    assert stats.records_per_layer[MemoryLayer.WORKING] > 0


async def test_loop_writes_episodic_on_completion(mock_model, memory_module):
    """Loop should write an episodic summary after run completes."""
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))

    registry = ToolRegistry()
    loop = AgentLoop(model=mock_model, tools=registry, memory=memory_module)
    await loop.run("test task")

    stats = await memory_module.stats()
    assert stats.records_per_layer[MemoryLayer.EPISODIC] > 0


async def test_loop_emits_memory_events(mock_model, memory_module):
    """Loop should emit MemoryReadEvent and MemoryWriteEvent."""
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))

    collected = []

    class CollectorSink:
        async def write(self, event):
            collected.append(event)
        async def write_batch(self, events):
            collected.extend(events)
        async def flush(self):
            pass
        async def close(self):
            pass

    obs = ObservabilityEngine(sinks=[CollectorSink()], config=ObservabilityConfig(buffer_size=100))
    registry = ToolRegistry()
    loop = AgentLoop(model=mock_model, tools=registry, memory=memory_module, observability=obs)
    await loop.run("test")
    await obs.flush()

    event_types = [e.event_type for e in collected]
    assert "memory.read" in event_types
    assert "memory.write" in event_types


async def test_loop_without_memory_still_works(mock_model):
    """Loop without memory should work (backward compat)."""
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))
    registry = ToolRegistry()
    loop = AgentLoop(model=mock_model, tools=registry)
    result = await loop.run("test")
    assert result.status == RunStatus.COMPLETED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_loop_v03.py -v`
Expected: FAIL — `AgentLoop` doesn't accept `memory` param

- [ ] **Step 3: Modify AgentLoop**

Read `mori/runtime/loop.py` first. Then make these changes:

1. Add `memory` parameter to `__init__`:
```python
    def __init__(
        self,
        model: ModelAdapter,
        tools: ToolRegistry,
        observability: ObservabilityEngine | None = None,
        control: ControlBounds | None = None,
        memory: Any = None,  # MemoryModule, imported lazily
    ) -> None:
        ...
        self._memory = memory
```

2. Add `_phase_retrieve` method (before `_phase_plan`):
```python
    async def _phase_retrieve(self, state: MoriState) -> None:
        """Read memory to enrich context for the plan phase."""
        if not self._memory:
            return

        from mori.observability.events import MemoryReadEvent
        import time as _time

        start = _time.monotonic()
        memory_slice = await self._memory.read(
            query=state.task,
            task_context=state.task,
            max_tokens=2000,
        )
        elapsed_ms = (_time.monotonic() - start) * 1000
        state.memory_slice = memory_slice

        await self._emit(MemoryReadEvent(
            event_id=f"evt_{_uid()}",
            timestamp=datetime.now(timezone.utc),
            run_id=state.run_id,
            query=state.task,
            layers=[l for l in memory_slice.layers_searched],
            records_returned=len(memory_slice.records),
            tokens_consumed=memory_slice.total_tokens,
            duration_ms=elapsed_ms,
        ))
```

3. Modify `_assemble_request` to inject memory context:
```python
    def _assemble_request(self, state: MoriState) -> ModelRequest:
        tool_specs = self._tools.list_specs()
        messages = list(state.messages)

        # Inject memory context if available
        if state.memory_slice and state.memory_slice.records:
            memory_lines = ["[Memory Context]"]
            for record in state.memory_slice.records:
                memory_lines.append(
                    f"- {record.content} (layer: {record.layer.value}, confidence: {record.confidence})"
                )
            memory_text = "\n".join(memory_lines)
            messages.insert(0, Message(role="system", content=memory_text))

        return ModelRequest(messages=messages, tools=tool_specs if tool_specs else None)
```

4. Add `_phase_update` method (after `_phase_evaluate`):
```python
    async def _phase_update(self, state: MoriState) -> None:
        """Write step trace to working memory."""
        if not self._memory:
            return

        from mori.observability.events import MemoryWriteEvent
        import secrets as _secrets

        # Summarize what happened this step
        last_tools = []
        for msg in reversed(state.messages):
            if msg.role == "tool":
                last_tools.append(msg.tool_call_id or "unknown")
            elif msg.role == "assistant":
                break

        content = f"Step {state.step_count}: {len(last_tools)} tool call(s). Task: {state.task[:100]}"

        from mori.types import MemoryRecord, MemoryRecordId, MemoryLayer
        record = MemoryRecord(
            record_id=MemoryRecordId(f"mem_{_secrets.token_hex(12)}"),
            layer=MemoryLayer.WORKING,
            content=content,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            provenance="loop:update",
        )
        receipt = await self._memory.write([record])

        await self._emit(MemoryWriteEvent(
            event_id=f"evt_{_uid()}",
            timestamp=datetime.now(timezone.utc),
            run_id=state.run_id,
            layer=MemoryLayer.WORKING,
            record_ids=[str(rid) for rid in receipt.record_ids],
            records_written=len(receipt.record_ids),
        ))
```

5. In the `run()` method, add phase calls:
   - Add `await self._phase_retrieve(state)` before `await self._phase_plan(state)`
   - Add `await self._phase_update(state)` after `outcome = self._phase_evaluate(state)`

6. Add episodic summary at run end (after the loop, before returning):
```python
        # Write episodic summary
        if self._memory:
            from mori.observability.events import MemoryWriteEvent
            import secrets as _secrets
            from mori.types import MemoryRecord, MemoryRecordId, MemoryLayer

            tools_used = set()
            for msg in state.messages:
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tools_used.add(tc.name)

            episodic_content = (
                f'Run "{state.task[:100]}": {state.status.value} in {state.step_count} steps. '
                f'Tools: {", ".join(sorted(tools_used)) or "none"}. '
                f'Result: {(result.final_output or "")[:200] if hasattr(result, "final_output") else ""}'
            )

            # Build result first, then write episodic
            run_result = RunResult.from_state(state, duration_ms=elapsed_ms)

            episodic_content = (
                f'Run "{state.task[:100]}": {state.status.value} in {state.step_count} steps. '
                f'Tools: {", ".join(sorted(tools_used)) or "none"}. '
                f'Result: {(run_result.final_output or "")[:200]}'
            )

            record = MemoryRecord(
                record_id=MemoryRecordId(f"mem_{_secrets.token_hex(12)}"),
                layer=MemoryLayer.EPISODIC,
                content=episodic_content,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                provenance="loop:episodic",
            )
            receipt = await self._memory.write([record])

            await self._emit(MemoryWriteEvent(
                event_id=f"evt_{_uid()}",
                timestamp=datetime.now(timezone.utc),
                run_id=state.run_id,
                layer=MemoryLayer.EPISODIC,
                record_ids=[str(rid) for rid in receipt.record_ids],
                records_written=1,
            ))

            if self._obs:
                await self._obs.flush()

            return run_result
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_loop_v03.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Run existing loop tests**

Run: `pytest tests/test_loop.py tests/test_loop_v02.py -v`
Expected: all PASS (backward compat)

- [ ] **Step 6: Commit**

```bash
git add mori/runtime/loop.py tests/test_loop_v03.py
git commit -m "feat: retrieve and update phases — memory context in loop"
```

---

## Task 10: Builder API — .memory_backend()

**Files:**
- Modify: `mori/agent.py`
- Test: `tests/test_builder_v03.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_builder_v03.py`:

```python
"""Tests for v0.3 builder — .memory_backend()."""

from unittest.mock import AsyncMock, patch

import pytest

from mori import Mori
from mori.types import (
    MemoryLayer,
    Message,
    ModelResponse,
    RunStatus,
    TokenUsage,
)


def _text_response(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


def test_builder_memory_inmemory():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .memory_backend("inmemory")
            .build()
        )
        assert agent.memory is not None


def test_builder_memory_sqlite(tmp_path):
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        path = str(tmp_path / "test.db")
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .memory_backend("sqlite", path=path)
            .build()
        )
        assert agent.memory is not None


def test_builder_no_memory():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .build()
        )
        assert agent.memory is None


async def test_builder_memory_stats(tmp_path):
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(return_value=_text_response("done"))
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .memory_backend("inmemory")
            .build()
        )
        await agent.run("test task")

        stats = await agent.memory.stats()
        assert stats.total_records > 0
        await agent.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_builder_v03.py -v`
Expected: FAIL — `.memory_backend()` doesn't exist

- [ ] **Step 3: Modify agent.py**

Read `mori/agent.py` first. Add:

1. A `.memory_backend()` method on `MoriBuilder`:
```python
    def memory_backend(self, backend_type: str, **kwargs: Any) -> MoriBuilder:
        self._memory_config = {"type": backend_type, **kwargs}
        return self
```

2. In `__init__`, add: `self._memory_config: dict[str, Any] | None = None`

3. In `build()`, after tool registry setup and before AgentLoop creation, add memory setup:
```python
        # Memory setup
        memory_module = None
        if self._memory_config:
            from mori.memory.module import MemoryModule
            from mori.memory.embedder import AnthropicEmbedder, Embedder
            from mori.memory.backends.inmemory import InMemoryBackend
            from mori.types import MemoryConfig

            backend_type = self._memory_config["type"]
            if backend_type == "inmemory":
                backend = InMemoryBackend()
            elif backend_type == "sqlite":
                from mori.memory.backends.sqlite import SQLiteBackend
                backend = SQLiteBackend(path=self._memory_config["path"])
                import asyncio
                # Initialize SQLite (sync context — use run_until_complete if needed)
                # For now, lazy init in MemoryModule or on first use
            else:
                raise ValueError(f"Unknown memory backend: {backend_type}")

            # Create embedder (reuse model API key if available)
            embedder: Embedder | None = None
            try:
                embedder = AnthropicEmbedder()
            except ImportError:
                pass  # No voyageai installed — memory works without embeddings

            memory_module = MemoryModule(
                backend=backend,
                config=MemoryConfig(),
                embedder=embedder,
                model=self._model_adapter,
            )
```

4. Pass `memory=memory_module` to `AgentLoop`

5. Update `Mori` class to accept and expose memory:
```python
    def __init__(self, ..., memory: Any = None) -> None:
        ...
        self._memory = memory

    @property
    def memory(self):
        return self._memory
```

6. In `Mori.close()`, close memory too:
```python
    async def close(self) -> None:
        if self._memory:
            await self._memory.close()
        if self._obs:
            await self._obs.close()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_builder_v03.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Run existing builder tests**

Run: `pytest tests/test_builder.py tests/test_builder_v02.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add mori/agent.py tests/test_builder_v03.py
git commit -m "feat: .memory_backend() builder method — inmemory and sqlite support"
```

---

## Task 11: v0.3 Exit Tests

**Files:**
- Create: `tests/test_integration_v03.py`

- [ ] **Step 1: Write exit tests**

Create `tests/test_integration_v03.py`:

```python
"""v0.3 exit tests — memory persists across steps, working + episodic populated."""

from unittest.mock import AsyncMock, patch

import pytest

from mori import Mori
from mori.types import (
    MemoryLayer,
    Message,
    ModelResponse,
    RunStatus,
    ToolCall,
    TokenUsage,
)


def _tool_response(tool_id: str, name: str, args: dict) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content="",
            tool_calls=[ToolCall(id=tool_id, name=name, arguments=args)]),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="tool_use",
    )

def _text_response(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=80, output_tokens=30),
        stop_reason="end_turn",
    )


async def test_v03_exit_test():
    """v0.3 exit test: working and episodic memory populated after a run."""

    def lookup(topic: str) -> str:
        return f"Information about {topic}: it uses standard patterns."

    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(side_effect=[
            _tool_response("call_1", "lookup", {"topic": "auth"}),
            _tool_response("call_2", "lookup", {"topic": "database"}),
            _text_response("Auth uses standard patterns. Database uses standard patterns. Both are well-documented."),
        ])
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(lookup, description="Look up information about a topic")
            .memory_backend("inmemory")
            .config(max_steps=10)
            .build()
        )

        result = await agent.run(
            "Look up auth, then look up database, then summarize both",
            thread_id="test",
        )

        assert result.status == RunStatus.COMPLETED

        stats = await agent.memory.stats()
        assert stats.records_per_layer[MemoryLayer.WORKING] > 0
        assert stats.records_per_layer[MemoryLayer.EPISODIC] > 0
        assert stats.total_records >= 3  # At least: 2 working + 1 episodic

        await agent.close()


async def test_v03_memory_without_tools():
    """Memory works even when no tools are called."""
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(return_value=_text_response("Hello!"))
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .memory_backend("inmemory")
            .build()
        )

        await agent.run("Say hello")

        stats = await agent.memory.stats()
        # Should have at least episodic summary
        assert stats.records_per_layer[MemoryLayer.EPISODIC] > 0

        await agent.close()


async def test_v03_no_memory_backward_compat():
    """Agent without memory still works fine."""
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(return_value=_text_response("done"))
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .build()
        )

        result = await agent.run("test")
        assert result.status == RunStatus.COMPLETED
        assert agent.memory is None
```

- [ ] **Step 2: Run exit tests**

Run: `pytest tests/test_integration_v03.py -v`
Expected: all 3 tests PASS

- [ ] **Step 3: Run full suite**

Run: `pytest tests/ -q --tb=short`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_v03.py
git commit -m "feat: v0.3 exit tests — memory persists across steps and runs"
```

---

## Summary

| Task | What It Builds | Tests |
|------|---------------|-------|
| 1 | Memory types (MemoryConfig, Filters, ForgetPolicy, etc.) | ~7 |
| 2 | Embedder protocol + AnthropicEmbedder | ~5 |
| 3 | MemoryBackend protocol + InMemoryBackend | ~10 |
| 4 | 4-stage retrieval pipeline | ~7 |
| 5 | MemoryModule (read, write, promote, forget, stats) | ~11 |
| 6 | SQLiteBackend with numpy vector search | ~8 |
| 7 | Memory observability events | ~2 |
| 8 | MoriState.memory_slice field | ~2 |
| 9 | Loop integration — retrieve/update phases | ~4 |
| 10 | Builder API — .memory_backend() | ~4 |
| 11 | v0.3 exit tests | ~3 |

**Total:** ~63 new tests across 11 tasks.

**Dependency order:** Tasks 1-2 have no deps. Task 3 depends on Task 1. Task 4 depends on Tasks 2-3. Task 5 depends on Tasks 3-4. Task 6 depends on Task 1. Tasks 7-8 are independent. Task 9 depends on Tasks 5, 7, 8. Task 10 depends on Task 9. Task 11 depends on all.

**Parallelizable:** Tasks 1+2 (no deps), Tasks 6+7+8 (independent of each other after Task 1).
