"""Tests for InMemoryBackend."""
from datetime import datetime, timezone
import pytest
from mori.memory.backends.inmemory import InMemoryBackend
from mori.types import MemoryLayer, MemoryRecord, MemoryRecordId, MemoryFilters

def _make_record(record_id="rec_1", layer=MemoryLayer.WORKING, content="test content",
                 embedding=None, confidence=1.0):
    now = datetime.now(timezone.utc)
    return MemoryRecord(record_id=MemoryRecordId(record_id), layer=layer, content=content,
        created_at=now, updated_at=now, confidence=confidence, embedding=embedding or [0.1]*10)

async def test_insert_and_get():
    backend = InMemoryBackend()
    ids = await backend.insert([_make_record("rec_1"), _make_record("rec_2")])
    assert len(ids) == 2
    retrieved = await backend.get([MemoryRecordId("rec_1")])
    assert len(retrieved) == 1
    assert retrieved[0].content == "test content"

async def test_get_missing():
    backend = InMemoryBackend()
    assert await backend.get([MemoryRecordId("nonexistent")]) == []

async def test_update():
    backend = InMemoryBackend()
    await backend.insert([_make_record("rec_1")])
    updated = await backend.update(MemoryRecordId("rec_1"), {"content": "updated"})
    assert updated.content == "updated"

async def test_delete():
    backend = InMemoryBackend()
    await backend.insert([_make_record("rec_1"), _make_record("rec_2")])
    assert await backend.delete([MemoryRecordId("rec_1")]) == 1
    remaining = await backend.get([MemoryRecordId("rec_1"), MemoryRecordId("rec_2")])
    assert len(remaining) == 1

async def test_search_cosine_similarity():
    backend = InMemoryBackend()
    await backend.insert([
        _make_record("rec_1", embedding=[1.0, 0.0, 0.0]),
        _make_record("rec_2", embedding=[0.0, 1.0, 0.0]),
        _make_record("rec_3", embedding=[0.9, 0.1, 0.0]),
    ])
    results = await backend.search(embedding=[1.0, 0.0, 0.0], limit=2)
    assert len(results) == 2
    assert results[0][0].record_id == "rec_1"
    assert results[1][0].record_id == "rec_3"
    assert results[0][1] > results[1][1]

async def test_search_filter_by_layer():
    backend = InMemoryBackend()
    await backend.insert([
        _make_record("rec_1", layer=MemoryLayer.WORKING, embedding=[1.0, 0.0]),
        _make_record("rec_2", layer=MemoryLayer.EPISODIC, embedding=[1.0, 0.0]),
    ])
    results = await backend.search(embedding=[1.0, 0.0], layer=MemoryLayer.WORKING)
    assert len(results) == 1
    assert results[0][0].record_id == "rec_1"

async def test_search_with_filters():
    backend = InMemoryBackend()
    await backend.insert([
        _make_record("rec_1", confidence=0.9, embedding=[1.0, 0.0]),
        _make_record("rec_2", confidence=0.3, embedding=[1.0, 0.0]),
    ])
    results = await backend.search(embedding=[1.0, 0.0], filters=MemoryFilters(min_confidence=0.5))
    assert len(results) == 1
    assert results[0][0].record_id == "rec_1"

async def test_list_records():
    backend = InMemoryBackend()
    await backend.insert([
        _make_record("rec_1", layer=MemoryLayer.WORKING),
        _make_record("rec_2", layer=MemoryLayer.WORKING),
        _make_record("rec_3", layer=MemoryLayer.EPISODIC),
    ])
    assert len(await backend.list_records(MemoryLayer.WORKING)) == 2

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
    await backend.close()
