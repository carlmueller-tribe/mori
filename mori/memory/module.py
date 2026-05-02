"""MemoryModule — orchestrates memory backends and retrieval."""
from __future__ import annotations
import secrets
from datetime import datetime, timezone
from typing import Any, Callable
from mori.memory.backends.base import MemoryBackend
from mori.memory.embedder import Embedder
from mori.memory.retrieval import retrieve
from mori.types import (ForgetPolicy, ForgetReport, MemoryConfig, MemoryFilters, MemoryLayer,
    MemoryRecord, MemoryRecordId, MemorySlice, MemoryStats, WriteReceipt)

class MemoryModule:
    def __init__(self, backend: MemoryBackend, config: MemoryConfig,
                 embedder: Embedder | None = None, model: Any = None) -> None:
        self._backend = backend
        self._config = config
        self._embedder = embedder
        self._model = model

    async def read(self, query: str, layers: list[MemoryLayer] | None = None,
        max_tokens: int = 2000, recency_bias: float = 0.3,
        filters: MemoryFilters | None = None, task_context: str = "") -> MemorySlice:
        if not self._embedder:
            return MemorySlice(records=[], total_tokens=0, query=query,
                layers_searched=layers or list(MemoryLayer), truncated=False)
        return await retrieve(query=query, task_context=task_context, backend=self._backend,
            embedder=self._embedder, layers=layers, max_tokens=max_tokens,
            recency_bias=recency_bias, filters=filters)

    async def read_by_ids(self, record_ids: list[MemoryRecordId]) -> list[MemoryRecord]:
        return await self._backend.get(record_ids)

    async def write(self, records: list[MemoryRecord]) -> WriteReceipt:
        if self._embedder:
            texts, indices = [], []
            for i, r in enumerate(records):
                if not r.embedding:
                    texts.append(r.content)
                    indices.append(i)
            if texts:
                embeddings = await self._embedder.embed(texts)
                for idx, emb in zip(indices, embeddings):
                    records[idx].embedding = emb
        ids = await self._backend.insert(records)
        layer = records[0].layer if records else MemoryLayer.WORKING
        return WriteReceipt(record_ids=ids, layer=layer, timestamp=datetime.now(timezone.utc))

    async def update(self, record_id: MemoryRecordId, content: str | None = None,
        metadata: dict[str, Any] | None = None, confidence: float | None = None) -> MemoryRecord:
        updates: dict[str, Any] = {}
        if content is not None:
            updates["content"] = content
            if self._embedder:
                updates["embedding"] = (await self._embedder.embed([content]))[0]
        if metadata is not None:
            updates["metadata"] = metadata
        if confidence is not None:
            updates["confidence"] = confidence
        return await self._backend.update(record_id, updates)

    async def delete(self, record_ids: list[MemoryRecordId]) -> int:
        return await self._backend.delete(record_ids)

    async def promote(self, source_layer: MemoryLayer, target_layer: MemoryLayer,
        record_ids: list[MemoryRecordId], abstraction_fn: Callable[..., Any] | None = None) -> list[MemoryRecordId]:
        source_records = await self._backend.get(record_ids)
        now = datetime.now(timezone.utc)
        new_records = []
        if abstraction_fn and source_records:
            combined = abstraction_fn([r.content for r in source_records])
            new_records.append(MemoryRecord(record_id=MemoryRecordId(f"mem_{secrets.token_hex(12)}"),
                layer=target_layer, content=combined, created_at=now, updated_at=now,
                provenance=f"promoted_from:{source_layer.value}"))
        else:
            for r in source_records:
                new_records.append(MemoryRecord(record_id=MemoryRecordId(f"mem_{secrets.token_hex(12)}"),
                    layer=target_layer, content=r.content, metadata=r.metadata, created_at=now,
                    updated_at=now, confidence=r.confidence, embedding=r.embedding,
                    provenance=f"promoted_from:{source_layer.value}"))
        return await self._backend.insert(new_records)

    async def forget(self, policy: ForgetPolicy | None = None) -> ForgetReport:
        if policy is None:
            policy = ForgetPolicy()
        expired, pruned, deduped = 0, 0, 0
        to_delete: list[MemoryRecordId] = []
        now = datetime.now(timezone.utc)
        for layer in MemoryLayer:
            records = await self._backend.list_records(layer, limit=100_000)
            for r in records:
                if policy.expire_ttl and r.ttl_seconds is not None:
                    if (now - r.created_at).total_seconds() > r.ttl_seconds:
                        to_delete.append(r.record_id)
                        expired += 1
                        continue
                if policy.prune_below_confidence is not None:
                    if r.confidence < policy.prune_below_confidence:
                        to_delete.append(r.record_id)
                        pruned += 1
                        continue
        if to_delete:
            await self._backend.delete(to_delete)
        return ForgetReport(expired=expired, pruned=pruned, deduplicated=deduped,
            total_deleted=expired + pruned + deduped)

    async def summarize_layer(self, layer: MemoryLayer, max_tokens: int = 500) -> str:
        records = await self._backend.list_records(layer, limit=100)
        if not records:
            return ""
        combined = "\n".join(r.content for r in records)
        max_chars = max_tokens * 4
        return combined[:max_chars] if len(combined) > max_chars else combined

    async def stats(self) -> MemoryStats:
        total = await self._backend.count()
        per_layer: dict[MemoryLayer, int] = {}
        tokens: dict[MemoryLayer, int] = {}
        oldest: dict[MemoryLayer, float | None] = {}
        newest: dict[MemoryLayer, float | None] = {}
        now = datetime.now(timezone.utc)
        for layer in MemoryLayer:
            count = await self._backend.count(layer)
            per_layer[layer] = count
            records = await self._backend.list_records(layer, limit=1000)
            tokens[layer] = sum(len(r.content) // 4 for r in records)
            if records:
                ages = [(now - r.created_at).total_seconds() for r in records]
                oldest[layer], newest[layer] = max(ages), min(ages)
            else:
                oldest[layer], newest[layer] = None, None
        return MemoryStats(total_records=total, records_per_layer=per_layer,
            estimated_tokens_per_layer=tokens, oldest_record_age_seconds=oldest,
            newest_record_age_seconds=newest)

    async def close(self) -> None:
        await self._backend.close()
