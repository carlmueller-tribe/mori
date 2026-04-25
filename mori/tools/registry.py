"""Tool registry for native Python callables."""

from __future__ import annotations

import asyncio
import inspect
import time
from datetime import datetime, timezone
from typing import Any, Callable

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
        """Invoke a tool by name with the given arguments."""
        rt = self._tools.get(name)
        if rt is None:
            raise ToolInvocationError(f"Tool '{name}' not found")

        if rt.fn is None:
            raise ToolInvocationError(f"Tool '{name}' has no callable")

        tool_id = ToolId(f"native:{name}")
        m = self._metrics.get(tool_id)

        start = time.monotonic()
        try:
            if asyncio.iscoroutinefunction(rt.fn):
                raw_result = await rt.fn(**arguments)
            else:
                raw_result = rt.fn(**arguments)

            elapsed_ms = (time.monotonic() - start) * 1000
            content = str(raw_result) if not isinstance(raw_result, str) else raw_result
            content = self._truncate(content)

            if m is not None:
                m.total_calls += 1
                m._total_latency_ms += elapsed_ms
                m.avg_latency_ms = m._total_latency_ms / m.total_calls
                m.last_called = datetime.now(tz=timezone.utc)

            return ToolResult(
                tool_name=name,
                call_id="",
                success=True,
                content=content,
                latency_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000

            if m is not None:
                m.total_calls += 1
                m.total_errors += 1
                m._total_latency_ms += elapsed_ms
                m.avg_latency_ms = m._total_latency_ms / m.total_calls
                m.last_called = datetime.now(tz=timezone.utc)
                m.last_error = str(exc)

            return ToolResult(
                tool_name=name,
                call_id="",
                success=False,
                content="",
                error=str(exc),
                latency_ms=elapsed_ms,
            )
