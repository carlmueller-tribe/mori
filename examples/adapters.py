"""
Mori v0.6 "It Adapts" — adapter examples.

Demonstrates how to wire external providers through the adapter layer:
  - Embedding adapters  (VoyageAI, OpenAI, Cohere, local sentence-transformers)
  - Custom Sink         (bring your own observability target)
  - Custom RuntimeAdapter (replace the native loop with any framework)
  - OTLP sink           (export spans to an OpenTelemetry collector)

Run any demo directly:

    uv run examples/adapters.py

Prerequisites vary by section — see each function's docstring.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mori import Mori
from mori.observability.events import MoriEvent

# ---------------------------------------------------------------------------
# Embedding adapters
# ---------------------------------------------------------------------------


async def demo_voyageai_embedder() -> None:
    """Semantic memory search powered by Voyage AI.

    Requires: pip install 'mori[voyageai]'
    Env:      VOYAGE_API_KEY
    """
    from mori.adapters.embeddings.voyageai_embedder import VoyageAIEmbedder

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .memory_backend("inmemory")
        .embedder(VoyageAIEmbedder(model="voyage-3"))
        .sink("stdout")
        .build()
    )
    result = await agent.run("What were the key decisions from our last architecture review?")
    print(result.final_output)
    await agent.close()


async def demo_openai_embedder() -> None:
    """Semantic memory search powered by OpenAI embeddings.

    Requires: pip install 'mori[openai-embed]'
    Env:      OPENAI_API_KEY
    """
    from mori.adapters.embeddings.openai_embedder import OpenAIEmbedder

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .memory_backend("inmemory")
        .embedder(OpenAIEmbedder(model="text-embedding-3-small"))
        .sink("stdout")
        .build()
    )
    result = await agent.run("Summarize what I've asked you about before.")
    print(result.final_output)
    await agent.close()


async def demo_cohere_embedder() -> None:
    """Semantic memory search powered by Cohere Embed.

    Requires: pip install 'mori[cohere]'
    Env:      COHERE_API_KEY
    """
    from mori.adapters.embeddings.cohere_embedder import CohereEmbedder

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .memory_backend("sqlite", path="/tmp/mori_cohere.db")
        .embedder(CohereEmbedder(model="embed-english-v3.0"))
        .sink("stdout")
        .build()
    )
    result = await agent.run("Find notes related to the Q1 project timeline.")
    print(result.final_output)
    await agent.close()


async def demo_local_embedder() -> None:
    """Semantic memory with no API key — runs entirely on-device.

    Requires: pip install 'mori[local-embed]'
    No API key needed.
    """
    from mori.adapters.embeddings.local_embedder import SentenceTransformerEmbedder

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .memory_backend("inmemory")
        .embedder(SentenceTransformerEmbedder(model="all-MiniLM-L6-v2"))
        .sink("stdout")
        .build()
    )
    result = await agent.run("What topics have come up most often in our conversations?")
    print(result.final_output)
    await agent.close()


# ---------------------------------------------------------------------------
# Custom Sink
# ---------------------------------------------------------------------------


async def demo_custom_sink() -> None:
    """Pass any object that satisfies the Sink protocol — no string key required.

    Useful for routing events to Slack, a database, a custom metrics system, etc.

    No credentials needed — uses a stub RuntimeAdapter so you can see the full
    event flow without a live model.
    """
    import datetime

    from mori.agent import MoriBuilder
    from mori.runtime.result import RunResult
    from mori.types import RunStatus, TokenUsage

    # --- Stub adapter: returns a fixed response, no model call ---
    class StubAdapter:
        async def run(
            self, task: str, state: Any, tools: Any, memory: Any, skills: Any
        ) -> RunResult:
            return RunResult(
                run_id=state.run_id,
                thread_id=state.thread_id,
                status=RunStatus.COMPLETED,
                task=task,
                final_output=(
                    "Engineering update (stub):\n"
                    "- Mori v0.6 shipped — ports-and-adapters at every boundary\n"
                    "- New adapters: VoyageAI, OpenAI, Cohere, local embeddings, LangGraph, OTLP\n"
                    "- 469 tests passing"
                ),
                total_steps=1,
                total_usage=TokenUsage(input_tokens=0, output_tokens=0),
                total_tool_calls=0,
                total_duration_ms=1.0,
            )

        async def stream(self, task: str, state: Any, tools: Any, **kwargs: Any):
            return
            yield

    # --- Custom Sink: print a timestamped line for every event ---
    class ConsoleSink:
        realtime = True

        async def write(self, event: MoriEvent) -> None:
            ts = datetime.datetime.now(datetime.UTC).strftime("%H:%M:%S")
            print(f"  [{ts}] {event.event_type}")

        async def write_batch(self, events: list[MoriEvent]) -> None:
            for e in events:
                await self.write(e)

        async def flush(self) -> None:
            pass

        async def close(self) -> None:
            pass

    builder = MoriBuilder()
    builder._model_adapter = object()  # not reached — StubAdapter handles run()
    builder._runtime_adapter = StubAdapter()
    agent = builder.sink(ConsoleSink()).build()

    print("── events ────────────────────────")
    result = await agent.run("Draft a short status update for the engineering team.")
    print("── output ────────────────────────")
    print(result.final_output)
    await agent.close()


# ---------------------------------------------------------------------------
# OTLP sink (OpenTelemetry)
# ---------------------------------------------------------------------------


async def demo_otlp_sink() -> None:
    """Export Mori events as OpenTelemetry spans to a local Collector.

    Requires: pip install 'mori[otlp]'
    Assumes an OTLP-compatible collector on localhost:4317.
    """
    from mori.adapters.sinks.otlp_sink import OTLPSink

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .sink(OTLPSink(endpoint="http://localhost:4317"))
        .sink("stdout")
        .build()
    )
    result = await agent.run("List the open action items from last week.")
    print(result.final_output)
    await agent.close()


# ---------------------------------------------------------------------------
# Custom RuntimeAdapter
# ---------------------------------------------------------------------------


class AuditingAdapter:
    """Example RuntimeAdapter that logs every run to a local audit log.

    Wraps an inner adapter and records start/end/error to a file. In production
    the inner adapter could be a LangGraph graph, a CrewAI crew, a live model, etc.
    """

    def __init__(self, inner: Any, audit_path: str = "/tmp/mori_audit.log") -> None:
        self._inner = inner
        self._audit_path = audit_path

    async def run(self, task: str, state: Any, tools: Any, memory: Any, skills: Any) -> Any:
        import time

        started_at = time.time()
        self._log(f"START run_id={state.run_id} task={task!r}")
        try:
            result = await self._inner.run(task, state, tools, memory, skills)
        except Exception as exc:
            self._log(f"ERROR run_id={state.run_id} error={exc!r}")
            raise
        elapsed = (time.time() - started_at) * 1000
        self._log(
            f"END run_id={state.run_id} status={result.status} "
            f"steps={result.total_steps} duration_ms={elapsed:.0f}"
        )
        return result

    async def stream(self, task: str, state: Any, tools: Any, **kwargs: Any):
        self._log(f"STREAM run_id={state.run_id} task={task!r}")
        async for chunk in self._inner.stream(task, state, tools, **kwargs):
            yield chunk

    def _log(self, message: str) -> None:
        import datetime

        ts = datetime.datetime.now(datetime.UTC).isoformat()
        with open(self._audit_path, "a") as f:
            f.write(f"{ts}  {message}\n")
        print(f"  [audit] {message}")


async def demo_custom_runtime_adapter() -> None:
    """RuntimeAdapter that wraps every run with audit log entries.

    No credentials needed — the inner adapter is a stub.
    """
    from mori.agent import MoriBuilder
    from mori.runtime.result import RunResult
    from mori.types import RunStatus, TokenUsage

    class StubAdapter:
        async def run(
            self, task: str, state: Any, tools: Any, memory: Any, skills: Any
        ) -> RunResult:
            return RunResult(
                run_id=state.run_id,
                thread_id=state.thread_id,
                status=RunStatus.COMPLETED,
                task=task,
                final_output=f"stub response to: {task}",
                total_steps=2,
                total_usage=TokenUsage(input_tokens=120, output_tokens=48),
                total_tool_calls=0,
                total_duration_ms=42.0,
            )

        async def stream(self, task: str, state: Any, tools: Any, **kwargs: Any):
            return
            yield

    audit_path = "/tmp/mori_audit.log"
    builder = MoriBuilder()
    builder._model_adapter = object()  # not reached — AuditingAdapter handles run()
    builder._runtime_adapter = AuditingAdapter(StubAdapter(), audit_path=audit_path)
    agent = builder.build()

    result = await agent.run("Draft the weekly engineering update.")
    print(f"\noutput: {result.final_output}")
    print(f"audit written to: {audit_path}")
    await agent.close()


async def demo_langgraph_runtime() -> None:
    """Use LangGraph as the execution engine behind a Mori agent.

    Requires: pip install 'mori[langgraph]'
    """
    from typing import TypedDict

    from langgraph.graph import StateGraph

    from mori import Mori
    from mori.adapters.frameworks.langgraph_adapter import LangGraphAdapter

    class State(TypedDict):
        task: str
        messages: list[Any]
        context: dict[str, Any]
        output: str
        step_count: int
        total_input_tokens: int
        total_output_tokens: int
        total_tool_calls: int

    async def planner(state: State) -> State:
        return {**state, "output": f"[LangGraph] planned: {state['task']}", "step_count": 1}

    async def executor(state: State) -> State:
        return {**state, "output": f"[LangGraph] executed: {state['task']}"}

    def build_graph(**kwargs: Any) -> Any:
        g: StateGraph = StateGraph(State)
        g.add_node("planner", planner)
        g.add_node("executor", executor)
        g.add_edge("planner", "executor")
        g.set_entry_point("planner")
        g.set_finish_point("executor")
        return g.compile()

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .runtime(LangGraphAdapter(graph_builder=build_graph))
        .sink("stdout")
        .build()
    )
    result = await agent.run("Outline a two-week sprint plan for adding OAuth support.")
    print(result.final_output)
    await agent.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

DEMOS = {
    "custom-sink": demo_custom_sink,
    "custom-runtime": demo_custom_runtime_adapter,
    "voyageai": demo_voyageai_embedder,
    "openai": demo_openai_embedder,
    "cohere": demo_cohere_embedder,
    "local": demo_local_embedder,
    "otlp": demo_otlp_sink,
    "langgraph": demo_langgraph_runtime,
}

if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "custom-sink"
    if name not in DEMOS:
        print(f"Available demos: {', '.join(DEMOS)}")
        sys.exit(1)
    asyncio.run(DEMOS[name]())
