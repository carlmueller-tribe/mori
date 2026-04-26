"""Observability example — structured event traces.

Shows how to capture every phase of agent execution as structured
events, written to both the console and a JSONL file for analysis.

Requires: ANTHROPIC_API_KEY

Usage:
    python examples/observability.py
    # Then inspect: cat traces.jsonl | python -m json.tool
"""

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from mori import Mori


def add(a: int, b: int) -> int:
    return a + b


def multiply(a: int, b: int) -> int:
    return a * b


TRACES_PATH = "traces.jsonl"


async def main():
    # Clean up previous traces
    Path(TRACES_PATH).unlink(missing_ok=True)

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .tool(add, description="Add two numbers")
        .tool(multiply, description="Multiply two numbers")
        # Both sinks active — console output AND file traces
        .sink("stdout")
        .sink("jsonl", path=TRACES_PATH)
        .config(max_steps=10)
        .build()
    )

    result = await agent.run("What is (7 + 3) * (2 + 8)?")
    await agent.close()

    # ── Analyze the traces ───────────────────────────────────
    print(f"\n{'━' * 70}")
    print("  Trace Analysis")
    print(f"{'━' * 70}")

    lines = Path(TRACES_PATH).read_text().strip().split("\n")
    events = [json.loads(line) for line in lines]

    print(f"\n  Total events captured: {len(events)}")
    print(f"  Event types:")
    for event in events:
        ts = event["timestamp"][:19]
        etype = event["event_type"]
        extra = ""
        if etype == "tool.invoke":
            extra = f" → {event['tool_name']}({event.get('arguments', {})})"
        elif etype == "tool.result":
            status = "✓" if event["success"] else "✗"
            extra = f" → {status} {event['tool_name']} ({event['latency_ms']:.0f}ms)"
        elif etype == "run.end":
            extra = f" → {event['status']} in {event['total_steps']} steps"
        print(f"    {ts}  {etype}{extra}")

    print(f"\n  Trace file: {TRACES_PATH}")
    print(f"  Run: cat {TRACES_PATH} | python -m json.tool")


if __name__ == "__main__":
    asyncio.run(main())
