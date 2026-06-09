"""ask_user is auto-registered; disable_native_tool removes it."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mori import Mori


def test_ask_user_auto_registered() -> None:
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-sonnet-4-20250514", api_key="test-key")
            .checkpointer("inmemory")
            .build()
        )
    specs = agent.tools.list_specs()
    assert any(s.name == "ask_user" for s in specs)


def test_disable_native_tool_removes_ask_user() -> None:
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-sonnet-4-20250514", api_key="test-key")
            .disable_native_tool("ask_user")
            .build()
        )
    specs = agent.tools.list_specs()
    assert not any(s.name == "ask_user" for s in specs)


def test_disable_unknown_native_tool_raises() -> None:
    with pytest.raises(ValueError, match="not a native tool"):
        Mori.builder().disable_native_tool("not_a_tool")


def test_build_without_checkpointer_with_ask_user_raises() -> None:
    """ask_user is auto-registered by default. Calling .build() without
    .checkpointer(...) must raise — the spec promises a clear build-time
    error, not a deferred resume-time failure.
    """
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        builder = Mori.builder().model("anthropic", model="claude-sonnet-4-20250514")
        # No .checkpointer() called and ask_user is NOT disabled — expect failure
        with pytest.raises(Exception) as exc:
            builder.build()
    msg = str(exc.value).lower()
    assert "checkpointer" in msg
    assert "ask_user" in msg or "ask user" in msg
    # Should mention the escape hatch
    assert "disable_native_tool" in msg or "disable" in msg


def test_build_without_checkpointer_with_ask_user_disabled_ok() -> None:
    """The opt-out path: .disable_native_tool('ask_user') makes .build() valid
    without a checkpointer.
    """
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-sonnet-4-20250514")
            .disable_native_tool("ask_user")
            .build()
        )
    assert agent is not None


def test_build_with_checkpointer_and_ask_user_ok() -> None:
    """The default path: ask_user enabled + checkpointer configured is fine."""
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-sonnet-4-20250514")
            .checkpointer("inmemory")
            .build()
        )
    assert agent is not None
