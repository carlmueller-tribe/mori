"""SentenceTransformerEmbedder — local embedding adapter using sentence-transformers."""

from __future__ import annotations

import asyncio


class SentenceTransformerEmbedder:
    """Local embedding adapter using sentence-transformers (no API key required)."""

    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "SentenceTransformerEmbedder requires sentence-transformers. "
                "Install with: pip install 'mori[local-embed]'"
            ) from e
        self._model_name = model
        self._model = SentenceTransformer(model)
        self._dimensions: int = self._model.get_sentence_embedding_dimension() or 384

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None, lambda: self._model.encode(texts, convert_to_numpy=True)
        )
        return [list(map(float, e)) for e in embeddings]

    @property
    def dimensions(self) -> int:
        return self._dimensions
