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
