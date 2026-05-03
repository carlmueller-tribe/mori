from __future__ import annotations


def test_local_embedder_import_path():
    from mori.adapters.embeddings.local_embedder import SentenceTransformerEmbedder

    assert SentenceTransformerEmbedder is not None


def test_local_embedder_satisfies_protocol():
    from mori.adapters.embeddings.local_embedder import SentenceTransformerEmbedder

    assert hasattr(SentenceTransformerEmbedder, "embed")
    assert hasattr(SentenceTransformerEmbedder, "dimensions")
