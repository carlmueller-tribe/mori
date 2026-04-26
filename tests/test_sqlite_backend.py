"""Tests for SQLiteBackend."""
from datetime import datetime, timezone
import pytest
from mori.memory.backends.sqlite import SQLiteBackend
from mori.types import MemoryLayer, MemoryRecord, MemoryRecordId, MemoryFilters

def _make_record(record_id="rec_1", layer=MemoryLayer.WORKING, content="test content",
                 embedding=None, confidence=1.0):
    now = datetime.now(timezone.utc)
    return MemoryRecord(record_id=MemoryRecordId(record_id), layer=layer, content=content,
        created_at=now, updated_at=now, confidence=confidence, embedding=embedding or [0.1]*10)

@pytest.fixture
async def backend(tmp_path):
    b = SQLiteBackend(path=str(tmp_path / "test.db"))
    await b.initialize()
    yield b
    await b.close()

async def test_insert_and_get(backend):
    ids = await backend.insert([_make_record("rec_1")])
    assert len(ids) == 1
    records = await backend.get([MemoryRecordId("rec_1")])
    assert len(records) == 1 and records[0].content == "test content"

async def test_update(backend):
    await backend.insert([_make_record("rec_1")])
    updated = await backend.update(MemoryRecordId("rec_1"), {"content": "new"})
    assert updated.content == "new"

async def test_delete(backend):
    await backend.insert([_make_record("rec_1"), _make_record("rec_2")])
    assert await backend.delete([MemoryRecordId("rec_1")]) == 1
    assert len(await backend.get([MemoryRecordId("rec_1"), MemoryRecordId("rec_2")])) == 1

async def test_search(backend):
    await backend.insert([
        _make_record("rec_1", embedding=[1.0, 0.0, 0.0]),
        _make_record("rec_2", embedding=[0.0, 1.0, 0.0]),
        _make_record("rec_3", embedding=[0.9, 0.1, 0.0]),
    ])
    results = await backend.search(embedding=[1.0, 0.0, 0.0], limit=2)
    assert len(results) == 2 and results[0][0].record_id == "rec_1"

async def test_search_filter_by_layer(backend):
    await backend.insert([
        _make_record("rec_1", layer=MemoryLayer.WORKING, embedding=[1.0, 0.0]),
        _make_record("rec_2", layer=MemoryLayer.EPISODIC, embedding=[1.0, 0.0]),
    ])
    results = await backend.search(embedding=[1.0, 0.0], layer=MemoryLayer.WORKING)
    assert len(results) == 1

async def test_list_records(backend):
    await backend.insert([_make_record("r1", layer=MemoryLayer.WORKING),
        _make_record("r2", layer=MemoryLayer.WORKING), _make_record("r3", layer=MemoryLayer.EPISODIC)])
    assert len(await backend.list_records(MemoryLayer.WORKING)) == 2

async def test_count(backend):
    await backend.insert([_make_record("r1", layer=MemoryLayer.WORKING),
        _make_record("r2", layer=MemoryLayer.EPISODIC)])
    assert await backend.count() == 2
    assert await backend.count(MemoryLayer.WORKING) == 1

async def test_persistence(tmp_path):
    path = str(tmp_path / "persist.db")
    b1 = SQLiteBackend(path=path)
    await b1.initialize()
    await b1.insert([_make_record("rec_1", content="persistent")])
    await b1.close()
    b2 = SQLiteBackend(path=path)
    await b2.initialize()
    records = await b2.get([MemoryRecordId("rec_1")])
    assert len(records) == 1 and records[0].content == "persistent"
    await b2.close()
