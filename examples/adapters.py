"""v0.6 adapters demo — shows how to wire external providers via the adapter layer."""

from __future__ import annotations

import asyncio


async def demo_with_openai_embedder() -> None:
    """Agent with OpenAI embeddings for semantic memory search."""
    from mori import Mori
    from mori.adapters.embeddings.openai_embedder import OpenAIEmbedder

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .memory_backend("inmemory")
        .embedder(OpenAIEmbedder(model="text-embedding-3-small"))
        .sink("stdout")
        .build()
    )
    result = await agent.run("What do you remember about our previous conversations?")
    print(result.final_output)
    await agent.close()


async def demo_with_custom_sink() -> None:
    """Agent with a custom Sink implementation — no string key required."""
    from mori import Mori
    from mori.observability.events import MoriEvent

    class PrintSink:
        realtime = True

        async def write(self, event: MoriEvent) -> None:
            print(f"[custom] {event.event_type}")

        async def write_batch(self, events: list[MoriEvent]) -> None:
            for e in events:
                await self.write(e)

        async def flush(self) -> None:
            pass

        async def close(self) -> None:
            pass

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .sink(PrintSink())
        .build()
    )
    result = await agent.run("Say hello.")
    print(result.final_output)
    await agent.close()


async def demo_with_langgraph_runtime() -> None:
    """Agent with LangGraph as the execution runtime."""
    from mori import Mori
    from mori.adapters.frameworks.langgraph_adapter import LangGraphAdapter

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .runtime(LangGraphAdapter())
        .sink("stdout")
        .build()
    )
    result = await agent.run("Summarize the key points of the ports-and-adapters pattern.")
    print(result.final_output)
    await agent.close()


if __name__ == "__main__":
    asyncio.run(demo_with_custom_sink())
