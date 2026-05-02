from datetime import datetime, timezone

import pytest

from mori.control.checkpoint import (
    Checkpoint, FileCheckpoints, InMemoryCheckpoints, SQLiteCheckpoints,
)
from mori.runtime.state import MoriState
from mori.types import RunId, RunStatus, ThreadId


def _state(thread_id: str = "t1") -> MoriState:
    now = datetime.now(timezone.utc)
    return MoriState(
        run_id=RunId("run_test"), thread_id=ThreadId(thread_id),
        task="test task", status=RunStatus.RUNNING,
        started_at=now, last_progress_at=now,
    )


@pytest.mark.asyncio
async def test_inmemory_save_and_load():
    store = InMemoryCheckpoints()
    state = _state()
    cid = await store.save(state)
    cp = await store.load(cid)
    assert cp is not None
    assert cp.checkpoint_id == cid


@pytest.mark.asyncio
async def test_inmemory_load_latest():
    store = InMemoryCheckpoints()
    state = _state("t1")
    await store.save(state)
    cid2 = await store.save(state)
    cp = await store.load_latest(ThreadId("t1"))
    assert cp is not None
    assert cp.checkpoint_id == cid2


@pytest.mark.asyncio
async def test_inmemory_load_latest_unknown_thread_returns_none():
    store = InMemoryCheckpoints()
    cp = await store.load_latest(ThreadId("unknown"))
    assert cp is None


@pytest.mark.asyncio
async def test_checkpoint_restore_round_trips_state():
    store = InMemoryCheckpoints()
    state = _state()
    state.step_count = 3
    state.total_tool_calls = 5
    cid = await store.save(state)
    cp = await store.load(cid)
    restored = cp.restore()
    assert restored.step_count == 3
    assert restored.total_tool_calls == 5
    assert restored.task == "test task"


@pytest.mark.asyncio
async def test_inmemory_list():
    store = InMemoryCheckpoints()
    state = _state("t1")
    await store.save(state)
    await store.save(state)
    checkpoints = await store.list(ThreadId("t1"))
    assert len(checkpoints) == 2


@pytest.mark.asyncio
async def test_inmemory_delete():
    store = InMemoryCheckpoints()
    state = _state()
    cid = await store.save(state)
    await store.delete(cid)
    assert await store.load(cid) is None


@pytest.mark.asyncio
async def test_file_checkpoints_save_and_restore(tmp_path):
    store = FileCheckpoints(str(tmp_path))
    state = _state("t1")
    state.step_count = 7
    cid = await store.save(state)
    cp = await store.load(cid)
    assert cp is not None
    restored = cp.restore()
    assert restored.step_count == 7
    assert restored.task == "test task"


@pytest.mark.asyncio
async def test_file_checkpoints_load_latest(tmp_path):
    store = FileCheckpoints(str(tmp_path))
    state = _state("t1")
    await store.save(state)
    cid2 = await store.save(state)
    cp = await store.load_latest(ThreadId("t1"))
    assert cp is not None


@pytest.mark.asyncio
async def test_file_checkpoints_list(tmp_path):
    store = FileCheckpoints(str(tmp_path))
    state = _state("t1")
    await store.save(state)
    await store.save(state)
    checkpoints = await store.list(ThreadId("t1"))
    assert len(checkpoints) == 2


@pytest.mark.asyncio
async def test_sqlite_checkpoints_save_and_restore(tmp_path):
    store = SQLiteCheckpoints(str(tmp_path / "ckpts.db"))
    state = _state("t1")
    state.step_count = 4
    cid = await store.save(state)
    cp = await store.load(cid)
    assert cp is not None
    restored = cp.restore()
    assert restored.step_count == 4


@pytest.mark.asyncio
async def test_sqlite_checkpoints_load_latest(tmp_path):
    store = SQLiteCheckpoints(str(tmp_path / "ckpts.db"))
    state = _state("t1")
    await store.save(state)
    await store.save(state)
    cp = await store.load_latest(ThreadId("t1"))
    assert cp is not None


@pytest.mark.asyncio
async def test_sqlite_checkpoints_list(tmp_path):
    store = SQLiteCheckpoints(str(tmp_path / "ckpts.db"))
    state = _state("t1")
    await store.save(state)
    await store.save(state)
    checkpoints = await store.list(ThreadId("t1"))
    assert len(checkpoints) == 2


@pytest.mark.asyncio
async def test_sqlite_checkpoints_delete(tmp_path):
    store = SQLiteCheckpoints(str(tmp_path / "ckpts.db"))
    state = _state()
    cid = await store.save(state)
    await store.delete(cid)
    assert await store.load(cid) is None
