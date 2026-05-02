"""Embedder protocol and implementations."""

from __future__ import annotations

from typing import Protocol, cast, runtime_checkable

try:
    import voyageai
except ImportError:
    voyageai = None


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimensions(self) -> int: ...


class AnthropicEmbedder:
    """Embedder using Voyage AI (Anthropic's embedding partner)."""

    def __init__(self, api_key: str | None = None, model: str = "voyage-3") -> None:
        if voyageai is None:
            raise ImportError("Install voyageai: pip install voyageai")
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
