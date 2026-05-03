"""LangGraphAdapter — wraps a LangGraph StateGraph as a Mori RuntimeAdapter."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from mori.runtime.result import RunResult
from mori.runtime.state import MoriState
from mori.tools.registry import ToolRegistry
from mori.types import RunStatus, TokenUsage


class LangGraphAdapter:
    """Wraps Mori modules into a LangGraph StateGraph for execution.

    Pass an optional graph_builder callable to customize the graph topology.
    Without one, a default linear graph mirroring the native loop is used.
    """

    def __init__(self, graph_builder: Callable[..., Any] | None = None) -> None:
        try:
            import langgraph  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "LangGraphAdapter requires langgraph. Install with: pip install 'mori[langgraph]'"
            ) from e
        self._graph_builder = graph_builder

    async def run(
        self,
        task: str,
        state: MoriState,
        tools: ToolRegistry,
        memory: Any | None,
        skills: Any | None,
    ) -> RunResult:
        import time

        start = time.monotonic()

        graph = self._build_graph(task, tools, memory, skills)
        initial = {"task": task, "messages": list(state.messages), "context": state.context}
        final = await graph.ainvoke(initial)

        return RunResult(
            run_id=state.run_id,
            thread_id=state.thread_id,
            status=RunStatus.COMPLETED,
            task=task,
            final_output=final.get("output", ""),
            total_steps=final.get("step_count", 1),
            total_usage=TokenUsage(
                input_tokens=final.get("total_input_tokens", 0),
                output_tokens=final.get("total_output_tokens", 0),
            ),
            total_tool_calls=final.get("total_tool_calls", 0),
            total_duration_ms=(time.monotonic() - start) * 1000,
        )

    async def stream(
        self,
        task: str,
        state: MoriState,
        tools: ToolRegistry,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        graph = self._build_graph(task, tools, None, None)
        initial = {"task": task, "messages": list(state.messages)}
        async for chunk in graph.astream(initial):
            yield chunk

    def _build_graph(
        self,
        task: str,
        tools: ToolRegistry,
        memory: Any | None,
        skills: Any | None,
    ) -> Any:
        if self._graph_builder is not None:
            return self._graph_builder(task=task, tools=tools, memory=memory, skills=skills)

        from typing import TypedDict

        from langgraph.graph import StateGraph

        class GraphState(TypedDict):
            task: str
            messages: list[Any]
            context: dict[str, Any]
            output: str
            step_count: int
            total_input_tokens: int
            total_output_tokens: int
            total_tool_calls: int

        async def agent_node(state: GraphState) -> GraphState:
            return {**state, "output": f"LangGraph executed: {state['task']}", "step_count": 1}

        graph: StateGraph = StateGraph(GraphState)
        graph.add_node("agent", agent_node)
        graph.set_entry_point("agent")
        graph.set_finish_point("agent")
        return graph.compile()


def langgraph_as_tool(
    graph: Any,
    name: str,
    description: str,
    input_schema: type,
) -> Any:
    """Wrap a compiled LangGraph graph as a Mori RegisteredTool."""
    from mori.tools.registry import ToolRegistry

    async def _invoke(**kwargs: Any) -> str:
        result = await graph.ainvoke(kwargs)
        return str(result)

    _invoke.__name__ = name
    registry = ToolRegistry()
    registry.register(name, _invoke, description=description)
    return registry.get_spec(name)


def langgraph_as_skill(
    graph: Any,
    name: str,
    version: str,
    description: str,
    triggers: dict[str, Any] | None = None,
) -> Any:
    """Wrap a compiled LangGraph graph as a Mori SkillManifest."""
    from mori.skills.types import SkillManifest

    return SkillManifest(
        name=name,
        version=version,
        description=description,
        triggers=triggers or {},
    )
