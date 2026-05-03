from __future__ import annotations


def test_voyageai_embedder_import_path():
    from mori.adapters.embeddings.voyageai_embedder import VoyageAIEmbedder

    assert VoyageAIEmbedder is not None


def test_anthropic_embedder_backward_compat():
    """AnthropicEmbedder re-export still importable with deprecation warning."""
    import warnings

    import mori.memory.embedder as _embedder_mod

    # Remove cached attribute so __getattr__ fires fresh, even if imported elsewhere
    _embedder_mod.__dict__.pop("AnthropicEmbedder", None)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from mori.memory.embedder import AnthropicEmbedder

        assert AnthropicEmbedder is not None
        assert any("deprecated" in str(warning.message).lower() for warning in w)


def test_voyageai_embedder_satisfies_protocol():
    """VoyageAIEmbedder structurally satisfies Embedder without voyageai installed."""
    from mori.adapters.embeddings.voyageai_embedder import VoyageAIEmbedder

    # Check method signatures match protocol
    assert hasattr(VoyageAIEmbedder, "embed")
    assert hasattr(VoyageAIEmbedder, "dimensions")
