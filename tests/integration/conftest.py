"""Pytest fixtures for live-model integration tests.

These tests require ANTHROPIC_API_KEY in the environment (e.g., via .env).
When the key is absent, all tests in this directory are skipped.
"""

from __future__ import annotations

import os

import pytest

from mori.model.anthropic import AnthropicAdapter


def pytest_collection_modifyitems(config, items):
    """Skip every test in tests/integration/ if ANTHROPIC_API_KEY is unset."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return
    skip_marker = pytest.mark.skip(reason="ANTHROPIC_API_KEY not set")
    for item in items:
        if "tests/integration/" in str(item.fspath):
            item.add_marker(skip_marker)


@pytest.fixture
def anthropic_model():
    """A real AnthropicAdapter using claude-haiku for cost-efficient live tests."""
    return AnthropicAdapter(model="claude-haiku-4-5-20251001")
