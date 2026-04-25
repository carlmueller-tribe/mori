"""Mori — top-level API and builder."""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable

from mori.model.anthropic import AnthropicAdapter
from mori.runtime.loop import AgentLoop, LoopConfig
from mori.runtime.result import RunResult
from mori.tools.registry import ToolRegistry
from mori.types import ThreadId


class MoriBuilder:
    """Fluent builder for constructing a Mori agent."""

    def __init__(self) -> None:
        self._model_adapter: Any = None
        self._tools: list[tuple[str, Callable[..., Any], str, dict[str, Any] | None]] = []
        self._loop_config: dict[str, Any] = {}

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
        """Configure the LLM provider."""
        if provider == "anthropic":
            self._model_adapter = AnthropicAdapter(
                model=model,
                api_key=api_key,
                max_tokens=max_tokens,
                base_url=base_url,
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
        """Register a Python function as a tool."""
        tool_name = name or fn.__name__
        self._tools.append((tool_name, fn, description, input_schema))
        return self

    def config(self, **kwargs: Any) -> MoriBuilder:
        """Set loop configuration options."""
        self._loop_config.update(kwargs)
        return self

    def build(self) -> Mori:
        """Build and return a configured Mori agent."""
        if self._model_adapter is None:
            raise ValueError("A model must be configured. Call .model() before .build()")

        registry = ToolRegistry()
        for tool_name, fn, desc, schema in self._tools:
            registry.register(tool_name, fn, description=desc, input_schema=schema)

        loop_config = LoopConfig(**self._loop_config) if self._loop_config else LoopConfig()

        loop = AgentLoop(
            model=self._model_adapter,
            tools=registry,
            config=loop_config,
        )

        return Mori(loop=loop, tools=registry)


class Mori:
    """Top-level Mori agent."""

    def __init__(self, loop: AgentLoop, tools: ToolRegistry) -> None:
        self._loop = loop
        self._tools = tools

    @staticmethod
    def builder() -> MoriBuilder:
        """Create a new MoriBuilder."""
        return MoriBuilder()

    async def run(
        self,
        task: str,
        thread_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        """Run the agent on a task."""
        tid = ThreadId(thread_id) if thread_id else None
        return await self._loop.run(task, thread_id=tid, context=context)

    @property
    def tools(self) -> ToolRegistry:
        """Access the tool registry."""
        return self._tools
