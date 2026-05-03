from __future__ import annotations


def test_cohere_embedder_import_path():
    from mori.adapters.embeddings.cohere_embedder import CohereEmbedder

    assert CohereEmbedder is not None


def test_cohere_embedder_satisfies_protocol():
    from mori.adapters.embeddings.cohere_embedder import CohereEmbedder

    assert hasattr(CohereEmbedder, "embed")
    assert hasattr(CohereEmbedder, "dimensions")
