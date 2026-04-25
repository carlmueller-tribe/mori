"""Tests for v0.2 registry extensions — CLI and MCP tool registration."""

from unittest.mock import AsyncMock, patch

import pytest

from mori.protocols.cli.runner import CLIToolConfig
from mori.tools.registry import ToolRegistry
from mori.types import ToolSource


def test_register_cli():
    registry = ToolRegistry()
    tool_id = registry.register_cli(
        name="search_code",
        command="rg",
        description="Search with ripgrep",
        args_format="flags",
        args_schema={"pattern": {"type": "string"}, "path": {"type": "string", "default": "."}},
    )
    assert tool_id == "cli:search_code"
    spec = registry.get_spec("search_code")
    assert spec is not None
    assert spec.source == ToolSource.CLI


def test_register_cli_with_options():
    registry = ToolRegistry()
    registry.register_cli(name="git", command="git", description="Git", args_format="subcommand", cwd="/tmp", timeout_sec=30.0)
    assert registry.get_spec("git") is not None


@pytest.mark.anyio
async def test_invoke_cli_tool():
    registry = ToolRegistry()
    registry.register_cli(name="echo_test", command="echo", description="Echo", args_format="positional")
    result = await registry.invoke("echo_test", {"0": "hello"})
    assert result.success is True
    assert "hello" in result.content


@pytest.mark.anyio
async def test_invoke_cli_tool_tracks_metrics():
    registry = ToolRegistry()
    registry.register_cli(name="echo_test", command="echo", description="Echo", args_format="positional")
    await registry.invoke("echo_test", {"0": "hi"})
    metrics = registry.get_metrics("cli:echo_test")
    assert metrics is not None
    assert metrics.total_calls == 1


def test_list_specs_includes_cli():
    registry = ToolRegistry()
    registry.register("native_tool", lambda: "ok", description="Native")
    registry.register_cli("cli_tool", command="echo", description="CLI", args_format="flags")
    specs = registry.list_specs()
    assert len(specs) == 2
    sources = {s.source for s in specs}
    assert ToolSource.NATIVE in sources
    assert ToolSource.CLI in sources


@pytest.mark.anyio
async def test_register_mcp_server():
    registry = ToolRegistry()
    mock_client = AsyncMock()
    mock_client.name = "test_server"
    mock_client.discover_tools = AsyncMock(return_value=[])
    with patch("mori.tools.registry.MCPClient", return_value=mock_client):
        tool_ids = await registry.register_mcp_server(name="test_server", url="http://localhost:3000")
    mock_client.connect.assert_called_once()
    assert isinstance(tool_ids, list)
