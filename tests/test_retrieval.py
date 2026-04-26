"""Tests for the 4-stage retrieval pipeline."""
import math
from datetime import datetime, timezone, timedelta
import pytest
from mori.memory.backends.inmemory import InMemoryBackend
from mori.memory.retrieval import retrieve
from mori.types import MemoryLayer, MemoryRecord, MemoryRecordId, MemorySlice


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


async def _populated_backend() -> InMemoryBackend:
    embedder = FakeEmbedder()
    backend = InMemoryBackend()
    now = datetime.now(timezone.utc)
    records = [
        MemoryRecord(record_id=MemoryRecordId("rec_auth"), layer=MemoryLayer.WORKING,
            content="Authentication uses JWT tokens with 1-hour expiry",
            created_at=now - timedelta(minutes=5), updated_at=now,
            embedding=(await embedder.embed(["Authentication uses JWT tokens"]))[0]),
        MemoryRecord(record_id=MemoryRecordId("rec_db"), layer=MemoryLayer.EPISODIC,
            content="Database migration completed for user table",
            created_at=now - timedelta(hours=2), updated_at=now,
            embedding=(await embedder.embed(["Database migration completed"]))[0]),
        MemoryRecord(record_id=MemoryRecordId("rec_api"), layer=MemoryLayer.SEMANTIC,
            content="REST API follows OpenAPI 3.0 specification",
            created_at=now - timedelta(days=7), updated_at=now,
            embedding=(await embedder.embed(["REST API follows OpenAPI"]))[0]),
    ]
    await backend.insert(records)
    return backend


async def test_retrieve_returns_memory_slice():
    backend = await _populated_backend()
    result = await retrieve(query="authentication", task_context="research auth",
        backend=backend, embedder=FakeEmbedder())
    assert isinstance(result, MemorySlice)
    assert len(result.records) > 0


async def test_retrieve_respects_max_tokens():
    backend = await _populated_backend()
    result = await retrieve(query="test", task_context="", backend=backend,
        embedder=FakeEmbedder(), max_tokens=10)
    total = sum(len(r.content) // 4 for r in result.records)
    assert total <= 10 or len(result.records) <= 1


async def test_retrieve_filter_by_layer():
    backend = await _populated_backend()
    result = await retrieve(query="test", task_context="", backend=backend,
        embedder=FakeEmbedder(), layers=[MemoryLayer.WORKING])
    for r in result.records:
        assert r.layer == MemoryLayer.WORKING


async def test_retrieve_recency_bias_zero():
    backend = await _populated_backend()
    result = await retrieve(query="authentication JWT", task_context="", backend=backend,
        embedder=FakeEmbedder(), recency_bias=0.0)
    assert len(result.records) > 0


async def test_retrieve_recency_bias_one():
    backend = await _populated_backend()
    result = await retrieve(query="anything", task_context="", backend=backend,
        embedder=FakeEmbedder(), recency_bias=1.0)
    if len(result.records) >= 2:
        assert result.records[0].created_at >= result.records[1].created_at


async def test_retrieve_conflicts_empty():
    backend = await _populated_backend()
    result = await retrieve(query="test", task_context="", backend=backend, embedder=FakeEmbedder())
    assert result.conflicts == []


async def test_retrieve_empty_backend():
    result = await retrieve(query="test", task_context="", backend=InMemoryBackend(), embedder=FakeEmbedder())
    assert result.records == []
    assert result.truncated is False
