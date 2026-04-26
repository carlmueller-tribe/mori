"""InMemoryBackend — dict + numpy cosine similarity."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Literal
import numpy as np
from mori.types import MemoryFilters, MemoryLayer, MemoryRecord, MemoryRecordId

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    dot = np.dot(va, vb)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(dot / norm) if norm > 0 else 0.0

class InMemoryBackend:
    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    async def insert(self, records: list[MemoryRecord]) -> list[MemoryRecordId]:
        ids = []
        for r in records:
            self._records[r.record_id] = r
            ids.append(r.record_id)
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

    async def search(self, embedding: list[float], layer: MemoryLayer | None = None,
        limit: int = 20, filters: MemoryFilters | None = None) -> list[tuple[MemoryRecord, float]]:
        candidates = list(self._records.values())
        if layer is not None:
            candidates = [r for r in candidates if r.layer == layer]
        if filters:
            if filters.min_confidence is not None:
                candidates = [r for r in candidates if r.confidence >= filters.min_confidence]
            if filters.max_age_seconds is not None:
                now = datetime.now(timezone.utc)
                candidates = [r for r in candidates if (now - r.created_at).total_seconds() <= filters.max_age_seconds]
            if filters.exclude_ids:
                exclude = set(filters.exclude_ids)
                candidates = [r for r in candidates if r.record_id not in exclude]
            if filters.provenance is not None:
                candidates = [r for r in candidates if r.provenance == filters.provenance]
        scored = [(r, _cosine_similarity(embedding, r.embedding)) for r in candidates if r.embedding]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    async def list_records(self, layer: MemoryLayer, limit: int = 100, offset: int = 0,
        order_by: Literal["created_at", "updated_at", "confidence"] = "created_at") -> list[MemoryRecord]:
        records = [r for r in self._records.values() if r.layer == layer]
        records.sort(key=lambda r: getattr(r, order_by), reverse=(order_by == "confidence"))
        return records[offset:offset + limit]

    async def count(self, layer: MemoryLayer | None = None) -> int:
        if layer is None:
            return len(self._records)
        return sum(1 for r in self._records.values() if r.layer == layer)

    async def close(self) -> None:
        self._records.clear()
