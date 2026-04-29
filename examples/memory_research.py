"""Memory research example — multi-step research with working memory.

An agent researches multiple topics across several tool calls. After the
run we inspect the working-memory records written per step, then promote
the most relevant ones to the semantic layer for future retrieval.

Memory layers after this example:
  working    — one record per step, logging which tools were called
  episodic   — one record summarising the whole run
  semantic   — records promoted manually from working layer

Retrieval (semantic search to inject past context) requires voyageai:
    pip install voyageai
Without it, the retrieve phase returns empty but all writes still work.

Requires: ANTHROPIC_API_KEY

Usage:
    cd ~/Projects/Mori
    python examples/memory_research.py
"""

import asyncio
import secrets
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from mori import Mori
from mori.types import MemoryLayer, MemoryRecord, MemoryRecordId


# ── Simulated knowledge base ─────────────────────────────────

_ARTICLES: dict[str, str] = {
    "python": (
        "Python is a high-level, interpreted programming language created by Guido van Rossum "
        "in 1991. It emphasises readability and simplicity, making it popular for data science, "
        "web development, and automation."
    ),
    "rust": (
        "Rust is a systems programming language focused on safety, speed, and concurrency. "
        "It achieves memory safety without a garbage collector through its ownership model. "
        "Released by Mozilla in 2015, it has grown rapidly in the systems and WebAssembly space."
    ),
    "typescript": (
        "TypeScript is a strongly typed superset of JavaScript developed by Microsoft. "
        "It adds optional static types and compiles to plain JavaScript, making large codebases "
        "easier to maintain. Introduced in 2012."
    ),
    "go": (
        "Go (Golang) is a statically typed, compiled language designed at Google. "
        "It prioritises simplicity, fast compilation, and built-in concurrency via goroutines. "
        "Released in 2009 and widely used for cloud infrastructure and CLI tools."
    ),
}


def search_language(language: str) -> str:
    """Search the knowledge base for information about a programming language."""
    key = language.lower().strip()
    return _ARTICLES.get(key, f"No article found for '{language}'.")


def compare_languages(a: str, b: str) -> str:
    """Retrieve articles for two languages so they can be compared side-by-side."""
    art_a = _ARTICLES.get(a.lower().strip(), f"No article for '{a}'.")
    art_b = _ARTICLES.get(b.lower().strip(), f"No article for '{b}'.")
    return f"=== {a} ===\n{art_a}\n\n=== {b} ===\n{art_b}"


def get_languages() -> str:
    """List all available languages in the knowledge base."""
    return ", ".join(sorted(_ARTICLES.keys()))


# ── Agent ────────────────────────────────────────────────────

async def main() -> None:
    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .tool(get_languages, description="List available languages in the knowledge base")
        .tool(search_language, description="Search for information about a programming language")
        .tool(compare_languages, description="Compare two programming languages side-by-side")
        .memory_backend("inmemory")
        .sink("stdout")
        .config(max_steps=12)
        .build()
    )

    task = (
        "Research Python and Rust from the knowledge base, then compare them. "
        "Finish with a one-paragraph summary of key differences."
    )

    print(f"{'━' * 70}")
    print(f"  Task: {task}")
    print(f"{'━' * 70}\n")

    result = await agent.run(task)

    print(f"\n{'━' * 70}")
    print(f"  Answer:\n")
    for line in result.final_output.splitlines():
        print(f"  {line}")
    print(f"\n  [{result.total_steps} steps, {result.total_tool_calls} tool calls, "
          f"{result.total_usage.total} tokens]")
    print(f"{'━' * 70}\n")

    # ── Inspect working memory ────────────────────────────────
    print("Working-memory records (one per loop step):\n")
    backend = agent.memory._backend  # type: ignore[attr-defined]
    working = await backend.list_records(MemoryLayer.WORKING, order_by="created_at")
    for i, r in enumerate(working, 1):
        print(f"  [step {i}] {r.content}")

    # ── Inspect episodic memory ───────────────────────────────
    print(f"\nEpisodic-memory records (one per run):\n")
    episodic = await backend.list_records(MemoryLayer.EPISODIC)
    for ep in episodic:
        print(f"  {ep.content[:200]}")

    # ── Promote working → semantic ────────────────────────────
    print(f"\nPromoting all working records to semantic layer...\n")
    working_ids = [r.record_id for r in working]
    if working_ids:
        new_ids = await agent.memory.promote(
            source_layer=MemoryLayer.WORKING,
            target_layer=MemoryLayer.SEMANTIC,
            record_ids=working_ids,
        )
        print(f"  Promoted {len(new_ids)} record(s) to semantic layer.")

    # Also promote the episodic record to semantic
    episodic_ids = [r.record_id for r in episodic]
    if episodic_ids:
        ep_semantic = await agent.memory.promote(
            source_layer=MemoryLayer.EPISODIC,
            target_layer=MemoryLayer.SEMANTIC,
            record_ids=episodic_ids,
        )
        print(f"  Promoted {len(ep_semantic)} episodic record(s) to semantic layer.")

    # ── Final stats ───────────────────────────────────────────
    stats = await agent.memory.stats()
    print(f"\nFinal memory stats:\n")
    for layer in MemoryLayer:
        count = stats.records_per_layer[layer]
        tokens = stats.estimated_tokens_per_layer[layer]
        mark = " ← promoted copies" if layer == MemoryLayer.SEMANTIC and count > 0 else ""
        print(f"  {layer.value:14s}: {count:3d} record(s), ~{tokens:4d} tokens{mark}")

    print(f"\n  Total: {stats.total_records} records")
    print()
    print("  Note: semantic-layer records are retrievable in future runs once")
    print("  voyageai is installed  (pip install voyageai).")

    await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
