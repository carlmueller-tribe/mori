"""Tool registry for native Python callables."""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Callable

from mori.tools.schema import infer_schema
from mori.types import (
    RegisteredTool,
    ToolId,
    ToolInvocationError,
    ToolResult,
    ToolSource,
    ToolSpec,
)


class ToolRegistry:
    """Central registry for native Python tools."""

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

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

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Invoke a tool by name with the given arguments."""
        rt = self._tools.get(name)
        if rt is None:
            raise ToolInvocationError(f"Tool '{name}' not found")

        if rt.fn is None:
            raise ToolInvocationError(f"Tool '{name}' has no callable")

        start = time.monotonic()
        try:
            if asyncio.iscoroutinefunction(rt.fn):
                raw_result = await rt.fn(**arguments)
            else:
                raw_result = rt.fn(**arguments)

            elapsed_ms = (time.monotonic() - start) * 1000
            content = str(raw_result) if not isinstance(raw_result, str) else raw_result

            return ToolResult(
                tool_name=name,
                call_id="",
                success=True,
                content=content,
                latency_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=name,
                call_id="",
                success=False,
                content="",
                error=str(exc),
                latency_ms=elapsed_ms,
            )
