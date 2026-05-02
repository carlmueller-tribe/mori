"""Memory basic example — agent with in-memory backend.

Shows how memory accumulates automatically during a run:
- Working memory: one record written per step by the loop
- Episodic memory: one record written at run end summarising the task

Retrieval (injecting past context into the prompt) requires voyageai:
    pip install voyageai
Without it, reads return empty but writes still happen, as shown here.

Requires: ANTHROPIC_API_KEY

Usage:
    cd ~/Projects/Mori
    python examples/memory_basic.py
"""

import asyncio

from dotenv import load_dotenv

load_dotenv()

from mori import Mori
from mori.types import MemoryLayer

# ── Tools ────────────────────────────────────────────────────


def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


def power(base: float, exponent: float) -> float:
    """Raise base to exponent."""
    return base**exponent


def round_decimal(value: float, places: int = 2) -> float:
    """Round a float to a given number of decimal places."""
    return round(value, places)


# ── Agent ────────────────────────────────────────────────────


async def main() -> None:
    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .tool(add, description="Add two numbers")
        .tool(multiply, description="Multiply two numbers")
        .tool(power, description="Raise base to an exponent")
        .tool(round_decimal, description="Round a float to N decimal places")
        .memory_backend("inmemory")
        .sink("stdout")
        .config(max_steps=10)
        .build()
    )

    task = (
        "Calculate the future value of $1,000 invested at 5% annual interest, "
        "compounded annually, for 10 years. Show the result rounded to 2 decimal places. "
        "Formula: FV = PV * (1 + r)^n"
    )

    print(f"{'━' * 70}")
    print(f"  Task: {task}")
    print(f"{'━' * 70}\n")

    result = await agent.run(task)

    print(f"\n{'━' * 70}")
    print(f"  Answer: {result.final_output}")
    print(
        f"  [{result.total_steps} steps, {result.total_tool_calls} tool calls, "
        f"{result.total_usage.total} tokens]"
    )
    print(f"{'━' * 70}\n")

    # ── Memory stats ──────────────────────────────────────────
    stats = await agent.memory.stats()

    print("Memory after run:")
    print(f"  Total records : {stats.total_records}")
    for layer in MemoryLayer:
        count = stats.records_per_layer[layer]
        tokens = stats.estimated_tokens_per_layer[layer]
        if count > 0:
            print(f"  {layer.value:14s}: {count} record(s), ~{tokens} tokens")

    print()
    print("  Working  records = one per loop step (task + tool-call summary)")
    print("  Episodic records = one per run (status, steps, tools, final output)")
    print()

    # ── Peek at episodic record ───────────────────────────────
    from mori.memory.backends.inmemory import InMemoryBackend

    backend = agent.memory._backend  # type: ignore[attr-defined]
    if isinstance(backend, InMemoryBackend):
        episodic = await backend.list_records(MemoryLayer.EPISODIC)
        if episodic:
            print("  Episodic record content:")
            print(f"    {episodic[0].content}")

    await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
