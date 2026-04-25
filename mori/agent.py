"""Mori — top-level API and builder."""

from __future__ import annotations

from typing import Any, Callable

from mori.control.bounds import ControlBounds, ControlConfig
from mori.model.anthropic import AnthropicAdapter
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import ObservabilityConfig
from mori.observability.sinks.jsonl import JsonlSink
from mori.observability.sinks.stdout import StdoutSink
from mori.runtime.loop import AgentLoop
from mori.runtime.result import RunResult
from mori.tools.registry import ToolRegistry
from mori.types import ThreadId


class MoriBuilder:
    """Fluent builder for constructing a Mori agent."""

    def __init__(self) -> None:
        self._model_adapter: Any = None
        self._tools: list[tuple[str, Callable[..., Any], str, dict[str, Any] | None]] = []
        self._cli_tools: list[dict[str, Any]] = []
        self._mcp_servers: list[dict[str, Any]] = []
        self._sinks: list[Any] = []
        self._config: dict[str, Any] = {}

    def model(
        self,
        provider: str,
        *,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        max_tokens: int = 4096,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> MoriBuilder:
        if provider == "anthropic":
            self._model_adapter = AnthropicAdapter(
                model=model, api_key=api_key, max_tokens=max_tokens, base_url=base_url,
            )
        else:
            raise ValueError(f"Unknown model provider: {provider}. Supported: anthropic")
        return self

    def tool(
        self,
        fn: Callable[..., Any],
        description: str,
        name: str | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> MoriBuilder:
        tool_name = name or fn.__name__
        self._tools.append((tool_name, fn, description, input_schema))
        return self

    def cli(
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
    ) -> MoriBuilder:
        self._cli_tools.append({
            "name": name, "command": command, "description": description,
            "args_format": args_format, "args_schema": args_schema,
            "shell": shell, "cwd": cwd, "env": env, "timeout_sec": timeout_sec,
            "tags": tags,
        })
        return self

    def mcp_server(
        self,
        name: str,
        url: str,
        transport: str = "sse",
        auth: Any = None,
    ) -> MoriBuilder:
        self._mcp_servers.append({"name": name, "url": url, "transport": transport, "auth": auth})
        return self

    def sink(self, sink_type: str, **kwargs: Any) -> MoriBuilder:
        if sink_type == "stdout":
            self._sinks.append(StdoutSink())
        elif sink_type == "jsonl":
            path = kwargs.get("path")
            if not path:
                raise ValueError("JsonlSink requires a 'path' argument")
            self._sinks.append(JsonlSink(path=path))
        else:
            raise ValueError(f"Unknown sink type: {sink_type}. Supported: stdout, jsonl")
        return self

    def config(self, **kwargs: Any) -> MoriBuilder:
        self._config.update(kwargs)
        return self

    def build(self) -> Mori:
        if self._model_adapter is None:
            raise ValueError("A model must be configured. Call .model() before .build()")

        # 1. Observability
        obs: ObservabilityEngine | None = None
        if self._sinks:
            obs = ObservabilityEngine(sinks=self._sinks, config=ObservabilityConfig())

        # 2. Control bounds
        control_fields = {k: v for k, v in self._config.items() if k in ControlConfig.model_fields}
        control = ControlBounds(config=ControlConfig(**control_fields))

        # 3. Tool registry
        registry = ToolRegistry()
        for tool_name, fn, desc, schema in self._tools:
            registry.register(tool_name, fn, description=desc, input_schema=schema)
        for cli in self._cli_tools:
            registry.register_cli(**cli)

        # 4. Agent loop
        loop = AgentLoop(model=self._model_adapter, tools=registry, observability=obs, control=control)

        return Mori(loop=loop, tools=registry, observability=obs, mcp_configs=self._mcp_servers)


class Mori:
    """Top-level Mori agent."""

    def __init__(
        self,
        loop: AgentLoop,
        tools: ToolRegistry,
        observability: ObservabilityEngine | None = None,
        mcp_configs: list[dict[str, Any]] | None = None,
    ) -> None:
        self._loop = loop
        self._tools = tools
        self._obs = observability
        self._mcp_configs = mcp_configs or []
        self._mcp_connected = False

    @staticmethod
    def builder() -> MoriBuilder:
        return MoriBuilder()

    async def run(
        self,
        task: str,
        thread_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        # Lazy MCP connection
        if self._mcp_configs and not self._mcp_connected:
            for cfg in self._mcp_configs:
                await self._tools.register_mcp_server(**cfg)
            self._mcp_connected = True

        tid = ThreadId(thread_id) if thread_id else None
        return await self._loop.run(task, thread_id=tid, context=context)

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    async def close(self) -> None:
        if self._obs:
            await self._obs.close()
