"""Embedder protocol and implementations."""

from __future__ import annotations

import warnings
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimensions(self) -> int: ...


def __getattr__(name: str) -> Any:
    if name == "AnthropicEmbedder":
        warnings.warn(
            "AnthropicEmbedder is deprecated. "
            "Use mori.adapters.embeddings.voyageai_embedder.VoyageAIEmbedder instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from mori.adapters.embeddings.voyageai_embedder import VoyageAIEmbedder

        return VoyageAIEmbedder
    raise AttributeError(f"module 'mori.memory.embedder' has no attribute {name!r}")
