"""Tests for v0.2 builder additions — .cli(), .mcp_server(), .sink()."""

from unittest.mock import AsyncMock, patch

import pytest

from mori import Mori
from mori.types import Message, ModelResponse, RunStatus, ToolCall, TokenUsage, ToolSource


def _text_response(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


def test_builder_cli():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .cli("search", command="rg", description="Search", args_format="flags")
            .build()
        )
        specs = agent.tools.list_specs()
        assert len(specs) == 1
        assert specs[0].name == "search"
        assert specs[0].source == ToolSource.CLI


def test_builder_multiple_cli():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .cli("rg", command="rg", description="Ripgrep", args_format="flags")
            .cli("git", command="git", description="Git", args_format="subcommand")
            .build()
        )
        assert len(agent.tools.list_specs()) == 2


def test_builder_sink_stdout():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .sink("stdout")
            .build()
        )
        assert agent._obs is not None


def test_builder_sink_jsonl(tmp_path):
    path = str(tmp_path / "traces.jsonl")
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .sink("jsonl", path=path)
            .build()
        )
        assert agent._obs is not None


def test_builder_config_feeds_control():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .config(max_steps=10, idle_timeout_sec=60)
            .build()
        )
        assert agent._loop._control._config.max_steps == 10
        assert agent._loop._control._config.idle_timeout_sec == 60


async def test_builder_full_run_with_cli():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(return_value=_text_response("done"))
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .cli("echo", command="echo", description="Echo", args_format="positional")
            .sink("stdout")
            .config(max_steps=5)
            .build()
        )
        result = await agent.run("say hello")
        assert result.status == RunStatus.COMPLETED
