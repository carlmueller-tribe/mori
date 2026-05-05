"""Tests for Embedder protocol and AnthropicEmbedder."""

import sys
from unittest.mock import MagicMock, patch

from mori.memory.embedder import AnthropicEmbedder, Embedder


def test_embedder_is_protocol():
    assert hasattr(Embedder, "__protocol_attrs__") or hasattr(Embedder, "_is_runtime_protocol")


class FakeEmbedder:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 10 for _ in texts]

    @property
    def dimensions(self) -> int:
        return 10


def test_fake_embedder_satisfies_protocol():
    assert isinstance(FakeEmbedder(), Embedder)


async def test_anthropic_embedder_embed():
    mock_voyage = MagicMock()
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    mock_client.embed = MagicMock(return_value=mock_result)
    mock_voyage.Client.return_value = mock_client
    with patch.dict(sys.modules, {"voyageai": mock_voyage}):
        embedder = AnthropicEmbedder(api_key="test-key")
        result = await embedder.embed(["hello", "world"])
        assert len(result) == 2
        assert len(result[0]) == 3


def test_anthropic_embedder_dimensions():
    mock_voyage = MagicMock()
    mock_voyage.Client.return_value = MagicMock()
    with patch.dict(sys.modules, {"voyageai": mock_voyage}):
        assert AnthropicEmbedder(api_key="test-key").dimensions == 1024


async def test_anthropic_embedder_empty_input():
    mock_voyage = MagicMock()
    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.embeddings = []
    mock_client.embed = MagicMock(return_value=mock_result)
    mock_voyage.Client.return_value = mock_client
    with patch.dict(sys.modules, {"voyageai": mock_voyage}):
        result = await AnthropicEmbedder(api_key="test-key").embed([])
        assert result == []
