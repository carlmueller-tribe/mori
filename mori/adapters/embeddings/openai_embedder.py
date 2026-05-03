"""OpenAIEmbedder — embedding adapter for OpenAI embeddings API."""

from __future__ import annotations

_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbedder:
    """Embedding adapter using OpenAI embeddings API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
    ) -> None:
        try:
            from openai import AsyncOpenAI
        except ImportError as e:
            raise ImportError(
                "OpenAIEmbedder requires openai. Install with: pip install 'mori[openai]'"
            ) from e
        self._model = model
        self._client = AsyncOpenAI(api_key=api_key)
        self._dimensions = _DIMENSIONS.get(model, 1536)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(input=texts, model=self._model)
        return [item.embedding for item in response.data]

    @property
    def dimensions(self) -> int:
        return self._dimensions
