"""Pytest fixtures for live-model integration tests.

These tests require ANTHROPIC_API_KEY in the environment (e.g., via .env or via
the shell). When the key is absent, all tests in this directory are skipped.

If ANTHROPIC_API_KEY is a 1Password CLI reference (`op://...`), the conftest
calls `op read` once at session start to resolve it. If `op` is missing or the
read fails, tests skip rather than fail.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from mori.model.anthropic import AnthropicAdapter


def _resolve_op_reference() -> bool:
    """If ANTHROPIC_API_KEY is an op:// reference, resolve via `op read`.

    Returns True if a usable key is in os.environ after this call, False otherwise.
    """
    raw = os.getenv("ANTHROPIC_API_KEY", "")
    if not raw:
        return False
    if not raw.startswith("op://"):
        return True  # already a literal key

    if shutil.which("op") is None:
        return False

    try:
        result = subprocess.run(
            ["op", "read", raw],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False

    resolved = result.stdout.strip()
    if not resolved:
        return False
    os.environ["ANTHROPIC_API_KEY"] = resolved
    return True


def pytest_collection_modifyitems(config, items):
    """Skip every test in tests/integration/ if ANTHROPIC_API_KEY is unusable."""
    if _resolve_op_reference():
        return
    skip_marker = pytest.mark.skip(
        reason="ANTHROPIC_API_KEY not set (or op:// reference could not be resolved)"
    )
    for item in items:
        if "tests/integration/" in str(item.fspath):
            item.add_marker(skip_marker)


@pytest.fixture
def anthropic_model():
    """A real AnthropicAdapter using claude-haiku for cost-efficient live tests."""
    return AnthropicAdapter(model="claude-haiku-4-5-20251001")
