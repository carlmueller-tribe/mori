from __future__ import annotations


def test_openai_embedder_import_path() -> None:
    from mori.adapters.embeddings.openai_embedder import OpenAIEmbedder

    assert OpenAIEmbedder is not None


def test_openai_embedder_satisfies_protocol() -> None:
    from mori.adapters.embeddings.openai_embedder import OpenAIEmbedder

    assert hasattr(OpenAIEmbedder, "embed")
    assert hasattr(OpenAIEmbedder, "dimensions")
