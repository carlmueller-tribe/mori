"""Metrics and limits example — resource control and tool tracking.

Shows how ControlBounds enforces step limits and how per-tool
metrics track call counts, error rates, and latency.

Requires: ANTHROPIC_API_KEY

Usage:
    python examples/metrics_and_limits.py
"""

import asyncio
import random

from dotenv import load_dotenv

load_dotenv()

from mori import Mori

# ── Tools (one is unreliable) ────────────────────────────────


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def flaky_lookup(query: str) -> str:
    """Look up data — but sometimes fails."""
    if random.random() < 0.4:
        raise ConnectionError("Service temporarily unavailable")
    return f"Result for '{query}': 42"


async def main():
    # ── Example 1: Step limit enforcement ────────────────────
    print("━" * 70)
    print("  Example 1: Step Limit Enforcement")
    print("━" * 70)

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .tool(add, description="Add two numbers")
        .sink("stdout")
        .config(max_steps=3)
        .build()
    )

    result = await agent.run(
        "Add 1+1, then add 2+2, then add 3+3, then add 4+4, then add 5+5. " "Report all results."
    )

    print(f"\n  Status: {result.status}")
    print(f"  Steps used: {result.total_steps} / 3 max")
    print(f"  Tool calls completed: {result.total_tool_calls}")

    # Check metrics
    metrics = agent.tools.get_metrics("native:add")
    if metrics:
        print("\n  Tool 'add' metrics:")
        print(f"    Calls: {metrics.total_calls}")
        print(f"    Errors: {metrics.total_errors}")
        print(f"    Avg latency: {metrics.avg_latency_ms:.2f}ms")

    await agent.close()

    # ── Example 2: Error tracking with flaky tools ───────────
    print(f"\n{'━' * 70}")
    print("  Example 2: Error Rate Tracking")
    print("━" * 70)

    agent2 = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .tool(add, description="Add two numbers")
        .tool(flaky_lookup, description="Look up data (may fail temporarily)")
        .sink("stdout")
        .config(max_steps=8)
        .build()
    )

    result2 = await agent2.run(
        "Look up 'sales Q3' and 'sales Q4', then add the results together. "
        "Keep trying if a lookup fails."
    )

    print(f"\n  Status: {result2.status}")

    for tool_name, tool_id in [("add", "native:add"), ("flaky_lookup", "native:flaky_lookup")]:
        m = agent2.tools.get_metrics(tool_id)
        if m and m.total_calls > 0:
            print(f"\n  Tool '{tool_name}' metrics:")
            print(f"    Calls: {m.total_calls}")
            print(f"    Errors: {m.total_errors}")
            print(f"    Error rate: {m.error_rate:.0%}")
            print(f"    Avg latency: {m.avg_latency_ms:.2f}ms")
            if m.last_error:
                print(f"    Last error: {m.last_error}")

    await agent2.close()


if __name__ == "__main__":
    asyncio.run(main())
