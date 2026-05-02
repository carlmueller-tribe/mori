"""Checkpoint store — protocol + InMemory / File / SQLite backends."""
from __future__ import annotations

import contextlib
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mori.runtime.state import MoriState

from mori.types import CheckpointId, MoriModel, ThreadId


class Checkpoint(MoriModel):
    checkpoint_id: CheckpointId
    thread_id: ThreadId
    state_json: str
    created_at: datetime

    def restore(self) -> "MoriState":
        from mori.runtime.state import MoriState
        return MoriState.model_validate_json(self.state_json)


def _new_cid() -> CheckpointId:
    return CheckpointId(f"ckpt_{secrets.token_hex(8)}")


@runtime_checkable
class CheckpointStore(Protocol):
    async def save(self, state: Any) -> CheckpointId: ...
    async def load_latest(self, thread_id: ThreadId) -> Checkpoint | None: ...
    async def load(self, checkpoint_id: CheckpointId) -> Checkpoint | None: ...
    async def list(self, thread_id: ThreadId) -> list[Checkpoint]: ...
    async def delete(self, checkpoint_id: CheckpointId) -> None: ...


class InMemoryCheckpoints:
    def __init__(self) -> None:
        self._store: dict[CheckpointId, Checkpoint] = {}
        self._order: dict[ThreadId, list[CheckpointId]] = {}

    async def save(self, state: Any) -> CheckpointId:
        cid = _new_cid()
        cp = Checkpoint(
            checkpoint_id=cid, thread_id=state.thread_id,
            state_json=state.model_dump_json(), created_at=datetime.now(timezone.utc),
        )
        self._store[cid] = cp
        self._order.setdefault(state.thread_id, []).append(cid)
        return cid

    async def load_latest(self, thread_id: ThreadId) -> Checkpoint | None:
        cids = self._order.get(thread_id, [])
        return self._store.get(cids[-1]) if cids else None

    async def load(self, checkpoint_id: CheckpointId) -> Checkpoint | None:
        return self._store.get(checkpoint_id)

    async def list(self, thread_id: ThreadId) -> list[Checkpoint]:
        return [self._store[c] for c in self._order.get(thread_id, []) if c in self._store]

    async def delete(self, checkpoint_id: CheckpointId) -> None:
        if checkpoint_id in self._store:
            cp = self._store.pop(checkpoint_id)
            self._order[cp.thread_id] = [c for c in self._order.get(cp.thread_id, []) if c != checkpoint_id]


class FileCheckpoints:
    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, cid: CheckpointId) -> Path:
        return self._dir / f"{cid}.json"

    async def save(self, state: Any) -> CheckpointId:
        cid = _new_cid()
        cp = Checkpoint(
            checkpoint_id=cid, thread_id=state.thread_id,
            state_json=state.model_dump_json(), created_at=datetime.now(timezone.utc),
        )
        self._path(cid).write_text(cp.model_dump_json())
        return cid

    async def load_latest(self, thread_id: ThreadId) -> Checkpoint | None:
        checkpoints = await self.list(thread_id)
        return max(checkpoints, key=lambda c: c.created_at) if checkpoints else None

    async def load(self, checkpoint_id: CheckpointId) -> Checkpoint | None:
        p = self._path(checkpoint_id)
        return Checkpoint.model_validate_json(p.read_text()) if p.exists() else None

    async def list(self, thread_id: ThreadId) -> list[Checkpoint]:
        result = []
        for f in self._dir.glob("ckpt_*.json"):
            cp = Checkpoint.model_validate_json(f.read_text())
            if cp.thread_id == thread_id:
                result.append(cp)
        return sorted(result, key=lambda c: c.created_at)

    async def delete(self, checkpoint_id: CheckpointId) -> None:
        p = self._path(checkpoint_id)
        if p.exists():
            p.unlink()


class SQLiteCheckpoints:
    def __init__(self, path: str) -> None:
        self._path = path
        with contextlib.closing(sqlite3.connect(path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cp_thread ON checkpoints(thread_id)")
            conn.commit()

    def _row_to_checkpoint(self, row: tuple[Any, ...]) -> Checkpoint:
        return Checkpoint(
            checkpoint_id=CheckpointId(row[0]), thread_id=ThreadId(row[1]),
            state_json=row[2], created_at=datetime.fromisoformat(row[3]),
        )

    async def save(self, state: Any) -> CheckpointId:
        cid = _new_cid()
        with contextlib.closing(sqlite3.connect(self._path)) as conn:
            conn.execute(
                "INSERT INTO checkpoints VALUES (?, ?, ?, ?)",
                (cid, state.thread_id, state.model_dump_json(), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        return cid

    async def load_latest(self, thread_id: ThreadId) -> Checkpoint | None:
        with contextlib.closing(sqlite3.connect(self._path)) as conn:
            row = conn.execute(
                "SELECT checkpoint_id, thread_id, state_json, created_at FROM checkpoints "
                "WHERE thread_id = ? ORDER BY created_at DESC LIMIT 1", (thread_id,)
            ).fetchone()
        return self._row_to_checkpoint(row) if row else None

    async def load(self, checkpoint_id: CheckpointId) -> Checkpoint | None:
        with contextlib.closing(sqlite3.connect(self._path)) as conn:
            row = conn.execute(
                "SELECT checkpoint_id, thread_id, state_json, created_at FROM checkpoints "
                "WHERE checkpoint_id = ?", (checkpoint_id,)
            ).fetchone()
        return self._row_to_checkpoint(row) if row else None

    async def list(self, thread_id: ThreadId) -> list[Checkpoint]:
        with contextlib.closing(sqlite3.connect(self._path)) as conn:
            rows = conn.execute(
                "SELECT checkpoint_id, thread_id, state_json, created_at FROM checkpoints "
                "WHERE thread_id = ? ORDER BY created_at ASC", (thread_id,)
            ).fetchall()
        return [self._row_to_checkpoint(r) for r in rows]

    async def delete(self, checkpoint_id: CheckpointId) -> None:
        with contextlib.closing(sqlite3.connect(self._path)) as conn:
            conn.execute("DELETE FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,))
            conn.commit()
