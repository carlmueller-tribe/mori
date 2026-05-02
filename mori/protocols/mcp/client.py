"""MCPClient — native MCP client speaking JSON-RPC 2.0."""

from __future__ import annotations

import secrets
import time
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

from mori.protocols.mcp.schema_cache import SchemaCache
from mori.types import (
    AuthConfig,
    HealthStatus,
    ServerUnavailable,
    ToolId,
    ToolResult,
    ToolSource,
    ToolSpec,
)


class MCPClient:
    def __init__(
        self, name: str, url: str, transport: str = "sse", auth: AuthConfig | None = None
    ) -> None:  # noqa: E501
        self.name = name
        self._url = url
        self._transport = transport
        self._auth = auth
        self._connected = False
        self._cache = SchemaCache()
        self._client: Any = None

    async def connect(self) -> None:
        if httpx is None:
            raise ImportError("httpx is required for MCP client")
        headers: dict[str, str] = {}
        if self._auth and self._auth.token:
            headers[self._auth.header_name] = f"Bearer {self._auth.token}"
        self._client = httpx.AsyncClient(base_url=self._url, headers=headers, timeout=30.0)
        self._connected = True

    async def discover_tools(self) -> list[ToolSpec]:
        cached = self._cache.get(self.name)
        if cached is not None and not self._cache.is_stale(self.name):
            return cached
        result = await self._send_rpc("tools/list", {})
        tools_data = result.get("tools", [])
        specs = [
            ToolSpec(
                tool_id=ToolId(f"mcp:{self.name}:{t['name']}"),
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {"type": "object"}),
                source=ToolSource.MCP,
                server_id=self.name,
            )
            for t in tools_data
        ]
        self._cache.put(self.name, specs)
        return specs

    async def invoke(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        start = time.monotonic()
        try:
            result = await self._send_rpc("tools/call", {"name": tool_name, "arguments": arguments})
            elapsed_ms = (time.monotonic() - start) * 1000
            content_blocks = result.get("content", [])
            text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
            content = "\n".join(text_parts) if text_parts else str(result)
            return ToolResult(
                tool_name=tool_name,
                call_id="",
                success=True,
                content=content,
                latency_ms=elapsed_ms,
                metadata={"server": self.name},
            )  # noqa: E501
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=tool_name,
                call_id="",
                success=False,
                content="",
                error=str(exc),
                latency_ms=elapsed_ms,
                metadata={"server": self.name},
            )  # noqa: E501

    async def health_check(self) -> HealthStatus:
        start = time.monotonic()
        try:
            await self._send_rpc("ping", {})
            return HealthStatus(
                healthy=True,
                component=self.name,
                message="ok",
                latency_ms=(time.monotonic() - start) * 1000,
            )  # noqa: E501
        except Exception as exc:
            return HealthStatus(
                healthy=False,
                component=self.name,
                message=str(exc),
                latency_ms=(time.monotonic() - start) * 1000,
            )  # noqa: E501

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
        self._connected = False

    async def _send_rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            raise ServerUnavailable(f"Not connected to {self.name}")
        payload = {"jsonrpc": "2.0", "id": secrets.token_hex(8), "method": method, "params": params}
        response = await self._client.post("/", json=payload)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise ServerUnavailable(
                f"MCP error: {data['error'].get('message', 'unknown')}", details=data["error"]
            )  # noqa: E501
        result: dict[str, Any] = data.get("result", {})
        return result
