"""RuntimeAdapter protocol — implemented by external framework adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from mori.runtime.result import RunResult
from mori.runtime.state import MoriState
from mori.tools.registry import ToolRegistry


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Allows an external framework to serve as Mori's execution engine.

    Implement this protocol to replace the native AgentLoop with LangGraph,
    CrewAI, or any other orchestration framework while retaining all Mori modules.
    """

    async def run(
        self,
        task: str,
        state: MoriState,
        tools: ToolRegistry,
        memory: Any | None,
        skills: Any | None,
    ) -> RunResult: ...

    async def stream(
        self,
        task: str,
        state: MoriState,
        tools: ToolRegistry,
        **kwargs: Any,
    ) -> AsyncIterator[Any]: ...

    # TODO: tighten to AsyncIterator[StreamEvent] once StreamEvent is defined
    #       in mori.observability.events
