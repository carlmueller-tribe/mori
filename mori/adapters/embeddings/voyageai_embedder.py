"""VoyageAIEmbedder — embedding adapter for Voyage AI."""

from __future__ import annotations

from typing import cast


class VoyageAIEmbedder:
    """Embedding adapter using Voyage AI."""

    def __init__(self, api_key: str | None = None, model: str = "voyage-3") -> None:
        try:
            import voyageai
        except ImportError as e:
            raise ImportError(
                "VoyageAIEmbedder requires voyageai. Install with: pip install 'mori[voyageai]'"
            ) from e
        self._model = model
        self._client = voyageai.Client(api_key=api_key)
        self._dimensions = 1024

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result = self._client.embed(texts, model=self._model)
        return cast(list[list[float]], result.embeddings)

    @property
    def dimensions(self) -> int:
        return self._dimensions
