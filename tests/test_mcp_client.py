"""Tests for MCPClient — uses mocked HTTP."""

from unittest.mock import AsyncMock, patch

from mori.protocols.mcp.client import MCPClient
from mori.types import ToolSource


async def test_client_init():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    assert client.name == "test"
    assert client._connected is False


async def test_client_discover_tools_returns_specs():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    mock_result = {
        "tools": [
            {
                "name": "read_file",
                "description": "Read a file",
                "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
            {
                "name": "write_file",
                "description": "Write a file",
                "inputSchema": {"type": "object"},
            },
        ]
    }
    with patch.object(client, "_send_rpc", new_callable=AsyncMock, return_value=mock_result):
        specs = await client.discover_tools()
    assert len(specs) == 2
    assert specs[0].name == "read_file"
    assert specs[0].source == ToolSource.MCP


async def test_client_invoke_routes_through_rpc():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    client._connected = True
    mock_result = {"content": [{"type": "text", "text": "file contents here"}]}
    with patch.object(client, "_send_rpc", new_callable=AsyncMock, return_value=mock_result):
        result = await client.invoke("read_file", {"path": "test.txt"})
    assert result.success is True
    assert "file contents" in result.content


async def test_client_invoke_handles_error():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    client._connected = True
    with patch.object(
        client, "_send_rpc", new_callable=AsyncMock, side_effect=Exception("connection lost")
    ):
        result = await client.invoke("read_file", {"path": "test.txt"})
    assert result.success is False
    assert "connection lost" in (result.error or "")


async def test_client_health_check_healthy():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    client._connected = True
    with patch.object(client, "_send_rpc", new_callable=AsyncMock, return_value={}):
        health = await client.health_check()
    assert health.healthy is True


async def test_client_health_check_unhealthy():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    client._connected = True
    with patch.object(client, "_send_rpc", new_callable=AsyncMock, side_effect=Exception("down")):
        health = await client.health_check()
    assert health.healthy is False


async def test_client_uses_schema_cache():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    mock_result = {
        "tools": [{"name": "tool1", "description": "Tool 1", "inputSchema": {"type": "object"}}]
    }
    with patch.object(
        client, "_send_rpc", new_callable=AsyncMock, return_value=mock_result
    ) as mock_rpc:
        specs1 = await client.discover_tools()
        specs2 = await client.discover_tools()
    assert mock_rpc.call_count == 1  # Second call uses cache
