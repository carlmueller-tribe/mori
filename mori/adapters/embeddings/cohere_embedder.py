"""CohereEmbedder — embedding adapter for Cohere Embed API."""

from __future__ import annotations

_DIMENSIONS: dict[str, int] = {
    "embed-english-v3.0": 1024,
    "embed-multilingual-v3.0": 1024,
    "embed-english-light-v3.0": 384,
    "embed-multilingual-light-v3.0": 384,
}


class CohereEmbedder:
    """Embedding adapter using Cohere Embed API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "embed-english-v3.0",
        input_type: str = "search_document",
    ) -> None:
        try:
            import cohere
        except ImportError as e:
            raise ImportError(
                "CohereEmbedder requires cohere. Install with: pip install 'mori[cohere]'"
            ) from e
        self._model = model
        self._input_type = input_type
        self._client = cohere.AsyncClient(api_key=api_key)
        self._dimensions = _DIMENSIONS.get(model, 1024)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embed(
            texts=texts,
            model=self._model,
            input_type=self._input_type,
            embedding_types=["float"],
        )
        embeddings = response.embeddings
        if hasattr(embeddings, "float") and embeddings.float is not None:
            return list(embeddings.float)
        return list(embeddings)

    @property
    def dimensions(self) -> int:
        return self._dimensions
