"""SQLiteBackend — sqlite3 + numpy cosine similarity."""
from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from typing import Any, Literal
import numpy as np
from mori.types import MemoryFilters, MemoryLayer, MemoryRecord, MemoryRecordId

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(dot / norm) if norm > 0 else 0.0

class SQLiteBackend:
    def __init__(self, path: str) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None

    async def initialize(self) -> None:
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("""CREATE TABLE IF NOT EXISTS memory_records (
            record_id TEXT PRIMARY KEY, layer TEXT NOT NULL, content TEXT NOT NULL,
            metadata TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            ttl_seconds INTEGER, provenance TEXT, confidence REAL DEFAULT 1.0, embedding BLOB)""")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_layer ON memory_records(layer)")
        self._conn.commit()

    def _to_row(self, r: MemoryRecord) -> tuple[Any, ...]:
        emb = np.array(r.embedding, dtype=np.float32).tobytes() if r.embedding else None
        return (r.record_id, r.layer.value, r.content, json.dumps(r.metadata) if r.metadata else None,
            r.created_at.isoformat(), r.updated_at.isoformat(), r.ttl_seconds, r.provenance, r.confidence, emb)

    def _from_row(self, row: tuple[Any, ...]) -> MemoryRecord:
        emb = np.frombuffer(row[9], dtype=np.float32).tolist() if row[9] else []
        return MemoryRecord(record_id=MemoryRecordId(row[0]), layer=MemoryLayer(row[1]), content=row[2],
            metadata=json.loads(row[3]) if row[3] else {}, created_at=datetime.fromisoformat(row[4]),
            updated_at=datetime.fromisoformat(row[5]), ttl_seconds=row[6], provenance=row[7],
            confidence=row[8], embedding=emb)

    async def insert(self, records: list[MemoryRecord]) -> list[MemoryRecordId]:
        assert self._conn
        ids = []
        for r in records:
            self._conn.execute("INSERT OR REPLACE INTO memory_records VALUES (?,?,?,?,?,?,?,?,?,?)", self._to_row(r))
            ids.append(r.record_id)
        self._conn.commit()
        return ids

    async def get(self, record_ids: list[MemoryRecordId]) -> list[MemoryRecord]:
        assert self._conn
        ph = ",".join("?" for _ in record_ids)
        rows = self._conn.execute(f"SELECT * FROM memory_records WHERE record_id IN ({ph})",
            [str(r) for r in record_ids]).fetchall()
        return [self._from_row(r) for r in rows]

    async def update(self, record_id: MemoryRecordId, updates: dict[str, Any]) -> MemoryRecord:
        assert self._conn
        records = await self.get([record_id])
        if not records: raise KeyError(f"Record {record_id} not found")
        data = records[0].model_dump()
        data.update(updates)
        data["updated_at"] = datetime.now(timezone.utc)
        updated = MemoryRecord(**data)
        self._conn.execute("INSERT OR REPLACE INTO memory_records VALUES (?,?,?,?,?,?,?,?,?,?)", self._to_row(updated))
        self._conn.commit()
        return updated

    async def delete(self, record_ids: list[MemoryRecordId]) -> int:
        assert self._conn
        count = 0
        for rid in record_ids:
            count += self._conn.execute("DELETE FROM memory_records WHERE record_id=?", (str(rid),)).rowcount
        self._conn.commit()
        return count

    async def search(self, embedding: list[float], layer: MemoryLayer | None = None,
        limit: int = 20, filters: MemoryFilters | None = None) -> list[tuple[MemoryRecord, float]]:
        assert self._conn
        q: str = "SELECT * FROM memory_records WHERE embedding IS NOT NULL"
        p: list[Any] = []
        if layer: q += " AND layer=?"; p.append(layer.value)
        if filters:
            if filters.min_confidence is not None: q += " AND confidence>=?"; p.append(filters.min_confidence)
            if filters.provenance is not None: q += " AND provenance=?"; p.append(filters.provenance)
        rows = self._conn.execute(q, p).fetchall()
        scored = []
        for row in rows:
            rec = self._from_row(row)
            if rec.embedding:
                scored.append((rec, _cosine_similarity(embedding, rec.embedding)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def list_records(self, layer: MemoryLayer, limit: int = 100, offset: int = 0,
        order_by: Literal["created_at", "updated_at", "confidence"] = "created_at") -> list[MemoryRecord]:
        assert self._conn
        direction = "DESC" if order_by == "confidence" else "ASC"
        rows = self._conn.execute(f"SELECT * FROM memory_records WHERE layer=? ORDER BY {order_by} {direction} LIMIT ? OFFSET ?",
            (layer.value, limit, offset)).fetchall()
        return [self._from_row(r) for r in rows]

    async def count(self, layer: MemoryLayer | None = None) -> int:
        assert self._conn
        if layer is None:
            return int(self._conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0])
        return int(self._conn.execute("SELECT COUNT(*) FROM memory_records WHERE layer=?", (layer.value,)).fetchone()[0])

    async def close(self) -> None:
        if self._conn: self._conn.close(); self._conn = None
