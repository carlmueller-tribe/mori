"""4-stage retrieval pipeline for memory reads."""
from __future__ import annotations
import math
from datetime import datetime, timezone
from mori.memory.backends.base import MemoryBackend
from mori.memory.embedder import Embedder
from mori.types import MemoryFilters, MemoryLayer, MemoryRecord, MemoryRecordId, MemorySlice


def _recency_score(created_at: datetime) -> float:
    age = max(0.0, (datetime.now(timezone.utc) - created_at).total_seconds())
    return math.exp(-age / 86400.0)


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
    # Stage 1: Query Expansion
    expanded = f"{query} {task_context}".strip()

    # Stage 2: Multi-Layer Fan-Out
    embeddings = await embedder.embed([expanded])
    if not embeddings:
        return MemorySlice(
            records=[],
            total_tokens=0,
            query=query,
            layers_searched=layers or list(MemoryLayer),
            truncated=False,
        )

    search_layers = layers or list(MemoryLayer)
    all_results: list[tuple[MemoryRecord, float]] = []
    for layer in search_layers:
        results = await backend.search(embedding=embeddings[0], layer=layer, limit=20, filters=filters)
        all_results.extend(results)

    # Stage 3: Relevance Scoring
    scored = []
    for record, sim in all_results:
        recency = _recency_score(record.created_at)
        composite = (1.0 - recency_bias) * sim + recency_bias * recency
        scored.append((record, composite))
    scored.sort(key=lambda x: x[1], reverse=True)

    # Stage 4: Budget-Aware Truncation
    selected: list[MemoryRecord] = []
    total_tokens = 0
    truncated = False
    for record, _ in scored:
        tokens = len(record.content) // 4
        if total_tokens + tokens > max_tokens and selected:
            truncated = True
            break
        selected.append(record)
        total_tokens += tokens

    # Stage 5: Conflict Detection (stubbed)
    return MemorySlice(
        records=selected,
        total_tokens=total_tokens,
        query=query,
        layers_searched=search_layers,
        truncated=truncated,
        conflicts=[],
    )
