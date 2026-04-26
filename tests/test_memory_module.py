"""Tests for MemoryModule."""
import math
from datetime import datetime, timezone, timedelta
import pytest
from mori.memory.backends.inmemory import InMemoryBackend
from mori.memory.module import MemoryModule
from mori.types import (ForgetPolicy, MemoryConfig, MemoryLayer, MemoryRecord, MemoryRecordId, MemorySlice, WriteReceipt)

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

def _make_record(record_id, layer=MemoryLayer.WORKING, content="test", confidence=1.0,
                 ttl_seconds=None, created_at=None):
    now = created_at or datetime.now(timezone.utc)
    return MemoryRecord(record_id=MemoryRecordId(record_id), layer=layer, content=content,
        created_at=now, updated_at=now, confidence=confidence, ttl_seconds=ttl_seconds)

@pytest.fixture
def module():
    return MemoryModule(backend=InMemoryBackend(), config=MemoryConfig(), embedder=FakeEmbedder())

async def test_write_and_read(module):
    receipt = await module.write([_make_record("rec_1", content="authentication uses JWT")])
    assert isinstance(receipt, WriteReceipt) and len(receipt.record_ids) == 1
    result = await module.read("authentication")
    assert isinstance(result, MemorySlice) and len(result.records) == 1

async def test_read_by_ids(module):
    await module.write([_make_record("rec_1", content="hello")])
    records = await module.read_by_ids([MemoryRecordId("rec_1")])
    assert len(records) == 1 and records[0].content == "hello"

async def test_update(module):
    await module.write([_make_record("rec_1", content="old")])
    updated = await module.update(MemoryRecordId("rec_1"), content="new")
    assert updated.content == "new"

async def test_delete(module):
    await module.write([_make_record("rec_1"), _make_record("rec_2")])
    assert await module.delete([MemoryRecordId("rec_1")]) == 1
    assert (await module.stats()).total_records == 1

async def test_promote(module):
    await module.write([_make_record("rec_1", layer=MemoryLayer.WORKING, content="fact")])
    new_ids = await module.promote(MemoryLayer.WORKING, MemoryLayer.SEMANTIC, [MemoryRecordId("rec_1")])
    assert len(new_ids) == 1
    stats = await module.stats()
    assert stats.records_per_layer[MemoryLayer.SEMANTIC] == 1
    assert stats.records_per_layer[MemoryLayer.WORKING] == 1  # source preserved

async def test_forget_expires_ttl(module):
    expired = _make_record("rec_old", ttl_seconds=1, created_at=datetime.now(timezone.utc) - timedelta(hours=1))
    await module.write([expired])
    report = await module.forget(ForgetPolicy(expire_ttl=True, prune_below_confidence=None, deduplicate=False))
    assert report.expired >= 1 and report.total_deleted >= 1

async def test_forget_prunes_low_confidence(module):
    await module.write([_make_record("rec_low", confidence=0.1), _make_record("rec_high", confidence=0.9)])
    report = await module.forget(ForgetPolicy(expire_ttl=False, prune_below_confidence=0.5, deduplicate=False))
    assert report.pruned >= 1
    assert (await module.stats()).total_records == 1

async def test_stats(module):
    await module.write([_make_record("r1", layer=MemoryLayer.WORKING), _make_record("r2", layer=MemoryLayer.EPISODIC),
        _make_record("r3", layer=MemoryLayer.WORKING)])
    stats = await module.stats()
    assert stats.total_records == 3
    assert stats.records_per_layer[MemoryLayer.WORKING] == 2

async def test_summarize_layer_fallback(module):
    await module.write([_make_record("r1", layer=MemoryLayer.WORKING, content="Auth uses JWT"),
        _make_record("r2", layer=MemoryLayer.WORKING, content="DB uses Postgres")])
    summary = await module.summarize_layer(MemoryLayer.WORKING, max_tokens=50)
    assert ("JWT" in summary or "Postgres" in summary) and len(summary) > 0

async def test_close(module):
    await module.close()
