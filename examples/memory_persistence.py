"""Memory persistence example — SQLite backend across multiple runs.

Shows that episodic memory survives between agent instantiations.
Each run writes one episodic record to the database. A third agent
instance (read-only) opens the same file and prints the accumulated
history.

Requires: ANTHROPIC_API_KEY

Usage:
    cd ~/Projects/Mori
    python examples/memory_persistence.py

The demo creates examples/memory_sessions.db and deletes it on exit.
"""

import ast
import asyncio
import operator
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from mori import Mori
from mori.types import MemoryLayer

DB_PATH = str(Path(__file__).parent / "memory_sessions.db")


# ── Tools ────────────────────────────────────────────────────

def lookup(topic: str) -> str:
    """Look up a simple fact about a topic."""
    facts = {
        "paris":     "Paris is the capital of France, population ~2.1 million.",
        "london":    "London is the capital of the United Kingdom, population ~9 million.",
        "berlin":    "Berlin is the capital of Germany, population ~3.7 million.",
        "tokyo":     "Tokyo is the capital of Japan and the world's most populous metro area.",
        "fibonacci": "The Fibonacci sequence: 1, 1, 2, 3, 5, 8, 13, 21, 34, 55 ...",
    }
    key = topic.lower().strip()
    return facts.get(key, f"No fact found for '{topic}'.")


def compute(a: float, b: float, op: str) -> str:
    """Perform a arithmetic operation on two numbers.

    op: one of 'add', 'subtract', 'multiply', 'divide'
    """
    ops = {
        "add":      operator.add,
        "subtract": operator.sub,
        "multiply": operator.mul,
        "divide":   operator.truediv,
    }
    if op not in ops:
        return f"Error: unknown op '{op}'. Use: add, subtract, multiply, divide"
    if op == "divide" and b == 0:
        return "Error: division by zero"
    return str(ops[op](a, b))


# ── Helper ───────────────────────────────────────────────────

def build_agent() -> Mori:
    return (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .tool(lookup, description="Look up a fact about a topic (paris, london, berlin, tokyo, fibonacci)")
        .tool(compute, description="Perform arithmetic: compute(a, b, op) where op is add/subtract/multiply/divide")
        .memory_backend("sqlite", path=DB_PATH)
        .config(max_steps=8)
        .build()
    )


def section(label: str) -> None:
    print(f"\n{'━' * 70}")
    print(f"  {label}")
    print(f"{'━' * 70}")


# ── Main ─────────────────────────────────────────────────────

async def main() -> None:
    # Remove any leftover DB from a previous run
    Path(DB_PATH).unlink(missing_ok=True)

    # ── Run 1 ─────────────────────────────────────────────────
    section("Session 1 — capitals of France and the UK")

    agent1 = build_agent()
    result1 = await agent1.run(
        "What are the capitals of France and the UK? Look them both up.",
        thread_id="demo-thread",
    )
    print(f"\n  Answer: {result1.final_output}")
    print(f"  [{result1.total_steps} steps]")

    stats1 = await agent1.memory.stats()
    print(f"\n  Memory after run 1:")
    print(f"    Working  : {stats1.records_per_layer[MemoryLayer.WORKING]}")
    print(f"    Episodic : {stats1.records_per_layer[MemoryLayer.EPISODIC]}")
    await agent1.close()

    # ── Run 2 — new agent instance, same DB ───────────────────
    section("Session 2 — Fibonacci and 99 × 99  (new agent, same DB)")

    agent2 = build_agent()
    result2 = await agent2.run(
        "Look up the Fibonacci sequence and then calculate 99 multiplied by 99.",
        thread_id="demo-thread",
    )
    print(f"\n  Answer: {result2.final_output}")
    print(f"  [{result2.total_steps} steps]")

    stats2 = await agent2.memory.stats()
    print(f"\n  Memory after run 2  (cumulative across both sessions):")
    print(f"    Working  : {stats2.records_per_layer[MemoryLayer.WORKING]}")
    print(f"    Episodic : {stats2.records_per_layer[MemoryLayer.EPISODIC]}"
          f"  ← 2 runs = 2 episodic records")
    await agent2.close()

    # ── Run 3 — read accumulated history ──────────────────────
    section("Session 3 — read accumulated episodic history  (no task run)")

    agent3 = build_agent()
    backend = agent3.memory._backend  # type: ignore[attr-defined]
    episodes = await backend.list_records(MemoryLayer.EPISODIC, order_by="created_at")

    print(f"\n  {len(episodes)} episodic record(s) in {Path(DB_PATH).name}:\n")
    for i, ep in enumerate(episodes, 1):
        print(f"  [{i}] {ep.content[:120]}")
        print(f"       written: {ep.created_at.strftime('%H:%M:%S')} UTC  "
              f"provenance: {ep.provenance}")
        print()

    await agent3.close()

    # ── Tidy up ───────────────────────────────────────────────
    Path(DB_PATH).unlink(missing_ok=True)
    print(f"  Cleaned up {Path(DB_PATH).name}")


if __name__ == "__main__":
    asyncio.run(main())
