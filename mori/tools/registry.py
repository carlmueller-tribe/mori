"""Tool registry for native Python callables, CLI tools, and MCP servers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast

from mori.protocols.cli.runner import CLIRunner, CLIToolConfig
from mori.protocols.mcp.client import MCPClient
from mori.tools.schema import infer_schema
from mori.types import (
    MoriModel,
    RegisteredTool,
    ToolId,
    ToolInvocationError,
    ToolResult,
    ToolSource,
    ToolSpec,
)

# Approximate characters-per-token ratio for truncation
_CHARS_PER_TOKEN = 4


class ToolMetrics(MoriModel):
    tool_id: ToolId
    total_calls: int = 0
    total_errors: int = 0
    avg_latency_ms: float = 0.0
    last_error: str | None = None
    last_called: datetime | None = None
    _total_latency_ms: float = 0.0
    model_config = {"frozen": False, "extra": "forbid"}

    @property
    def error_rate(self) -> float:
        return self.total_errors / self.total_calls if self.total_calls > 0 else 0.0


class ToolRegistry:
    """Central registry for native Python tools."""

    def __init__(self, max_result_tokens: int = 4000) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._metrics: dict[str, ToolMetrics] = {}
        self._max_result_tokens = max_result_tokens
        self._cli_configs: dict[str, tuple[CLIRunner, CLIToolConfig]] = {}
        self._mcp_clients: dict[str, MCPClient] = {}

    def register(
        self,
        name: str,
        fn: Callable[..., Any],
        description: str,
        input_schema: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Register a Python function as a tool. Returns the tool ID."""
        tool_id = ToolId(f"native:{name}")

        if input_schema is None:
            input_schema = infer_schema(fn)

        spec = ToolSpec(
            tool_id=tool_id,
            name=name,
            description=description,
            input_schema=input_schema,
            source=ToolSource.NATIVE,
            tags=tags or [],
        )
        self._tools[name] = RegisteredTool(spec=spec, fn=fn)
        self._metrics[tool_id] = ToolMetrics(tool_id=tool_id)
        return tool_id

    def tool(
        self,
        description: str,
        name: str | None = None,
        tags: list[str] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator for registering tools."""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or fn.__name__
            self.register(tool_name, fn, description=description, tags=tags)
            return fn

        return decorator

    def list_specs(self) -> list[ToolSpec]:
        """List all registered tool specs."""
        return [rt.spec for rt in self._tools.values()]

    def get_spec(self, name: str) -> ToolSpec | None:
        """Get a tool spec by name."""
        rt = self._tools.get(name)
        return rt.spec if rt else None

    def register_cli(
        self,
        name: str,
        command: str,
        description: str,
        args_format: str = "flags",
        args_schema: dict[str, Any] | None = None,
        shell: bool = False,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: float = 60.0,
        tags: list[str] | None = None,
    ) -> str:
        """Register a CLI tool backed by CLIRunner. Returns the tool ID."""
        tool_id = ToolId(f"cli:{name}")
        config = CLIToolConfig(
            command=command,
            args_format=cast(Literal["positional", "flags", "subcommand", "raw"], args_format),
            shell=shell,
            cwd=cwd,
            env=env,
            timeout_sec=timeout_sec,
        )
        if args_schema is None:
            input_schema = {"type": "object", "properties": {}}
        elif args_schema.get("type") == "object":
            input_schema = args_schema
        else:
            # Treat bare dict as properties — wrap in object schema
            input_schema = {"type": "object", "properties": args_schema}
        spec = ToolSpec(
            tool_id=tool_id,
            name=name,
            description=description,
            input_schema=input_schema,
            source=ToolSource.CLI,
            tags=tags or [],
        )
        runner = CLIRunner()
        self._tools[name] = RegisteredTool(spec=spec, fn=None)
        self._cli_configs[name] = (runner, config)
        self._metrics[tool_id] = ToolMetrics(tool_id=tool_id)
        return tool_id

    async def register_mcp_server(
        self,
        name: str,
        url: str,
        transport: str = "sse",
        auth: Any = None,
    ) -> list[str]:
        """Connect to an MCP server, discover its tools, and register them."""
        client = MCPClient(name=name, url=url, transport=transport, auth=auth)
        await client.connect()
        specs = await client.discover_tools()
        self._mcp_clients[name] = client
        tool_ids: list[str] = []
        for spec in specs:
            self._tools[spec.name] = RegisteredTool(spec=spec, fn=None)
            self._metrics[spec.tool_id] = ToolMetrics(tool_id=spec.tool_id)
            tool_ids.append(spec.tool_id)
        return tool_ids

    def get_metrics(self, tool_id: str) -> ToolMetrics | None:
        """Get metrics for a tool by its full tool_id (e.g. 'native:add')."""
        return self._metrics.get(tool_id)

    def _truncate(self, content: str) -> str:
        """Truncate content to fit within max_result_tokens, appending a note."""
        max_chars = self._max_result_tokens * _CHARS_PER_TOKEN
        if len(content) <= max_chars:
            return content
        truncated = content[:max_chars]
        return f"{truncated} [TRUNCATED — original length: {len(content)} chars]"

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Invoke a tool by name with the given arguments, routing by source."""
        rt = self._tools.get(name)
        if rt is None:
            raise ToolInvocationError(f"Tool '{name}' not found")

        metrics = self._metrics.get(rt.spec.tool_id)
        start = time.monotonic()

        try:
            if rt.spec.source == ToolSource.CLI:
                cli_entry = self._cli_configs.get(name)
                if cli_entry is None:
                    raise ToolInvocationError(f"CLI tool '{name}' has no runner config")
                runner, config = cli_entry
                result = await runner.run(arguments=arguments, config=config)
                # CLIRunner sets tool_name to the command; override to the registered name
                result = ToolResult(
                    tool_name=name,
                    call_id=result.call_id,
                    success=result.success,
                    content=result.content,
                    error=result.error,
                    latency_ms=result.latency_ms,
                    metadata=result.metadata,
                )
            elif rt.spec.source == ToolSource.MCP:
                server_id = rt.spec.server_id
                if server_id is None or server_id not in self._mcp_clients:
                    raise ToolInvocationError(f"MCP tool '{name}' has no connected server")
                result = await self._mcp_clients[server_id].invoke(name, arguments)
            elif rt.fn is not None:
                if asyncio.iscoroutinefunction(rt.fn):
                    raw_result = await rt.fn(**arguments)
                else:
                    raw_result = rt.fn(**arguments)
                elapsed_ms = (time.monotonic() - start) * 1000
                content = str(raw_result) if not isinstance(raw_result, str) else raw_result
                result = ToolResult(
                    tool_name=name,
                    call_id="",
                    success=True,
                    content=content,
                    latency_ms=elapsed_ms,
                )
            else:
                raise ToolInvocationError(f"Tool '{name}' has no callable")

        except ToolInvocationError:
            raise
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            result = ToolResult(
                tool_name=name,
                call_id="",
                success=False,
                content="",
                error=str(exc),
                latency_ms=elapsed_ms,
            )

        # Truncate successful results
        if result.success and isinstance(result.content, str):
            result = ToolResult(
                tool_name=result.tool_name,
                call_id=result.call_id,
                success=result.success,
                content=self._truncate(result.content),
                error=result.error,
                latency_ms=result.latency_ms,
                metadata=result.metadata,
            )

        # Update metrics
        if metrics:
            metrics.total_calls += 1
            metrics._total_latency_ms += result.latency_ms
            metrics.avg_latency_ms = metrics._total_latency_ms / metrics.total_calls
            metrics.last_called = datetime.now(tz=UTC)
            if not result.success:
                metrics.total_errors += 1
                metrics.last_error = result.error

        return result
