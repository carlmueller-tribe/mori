"""Skills and budget example — v0.4 "It Learns".

Demonstrates:
  - .skill_registry() — discovers the three built-in skills
  - .budget()         — tracks context allocation per slot
  - skill.discover event showing top match for the task
  - budget.rebalance event showing per-slot allocation

No ANTHROPIC_API_KEY required — uses a mock model adapter.

Usage:
    cd ~/Projects/Mori
    python examples/skills_and_budget.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from mori import Mori
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import ObservabilityConfig
from mori.types import Message, ModelResponse, TokenUsage


def _mock_adapter() -> object:
    adapter = AsyncMock()
    adapter.model_id = "mock"
    adapter.supports_tool_use = True
    adapter.max_context_tokens = 200_000
    adapter.invoke = AsyncMock(
        return_value=ModelResponse(
            message=Message(
                role="assistant", content="I traced the error and applied a minimal fix."
            ),
            usage=TokenUsage(input_tokens=300, output_tokens=80),
            stop_reason="end_turn",
        )
    )
    return adapter


async def main() -> None:
    skills_root = str(Path(__file__).parent.parent / "skills")

    traces: list[dict] = []

    class TraceSink:
        realtime = True

        async def write(self, e):
            traces.append(e.model_dump())

        async def write_batch(self, es):
            traces.extend(e.model_dump() for e in es)

        async def flush(self):
            pass

        async def close(self):
            pass

    import mori.agent as agent_mod

    original = agent_mod.AnthropicAdapter
    agent_mod.AnthropicAdapter = MagicMock(return_value=_mock_adapter())

    try:
        agent = (
            Mori.builder()
            .model("anthropic", api_key="demo")
            .skill_registry(skills_root)
            .budget(total_context_tokens=200_000)
            .build()
        )
        agent._obs = ObservabilityEngine(sinks=[TraceSink()], config=ObservabilityConfig())
        agent._loop._obs = agent._obs

        print(f"\n{'━' * 60}")
        print("  Task: Fix the failing test in tests/test_auth.py")
        print(f"{'━' * 60}\n")

        result = await agent.run("Fix the failing test in tests/test_auth.py")
        await agent._obs.flush()

        print(f"  Status : {result.status.value}")
        print(f"  Steps  : {result.total_steps}")

        skill_events = [e for e in traces if e["event_type"] == "skill.discover"]
        budget_events = [e for e in traces if e["event_type"] == "budget.rebalance"]
        compaction_events = [e for e in traces if e["event_type"] == "budget.compaction"]

        print(f"\n{'─' * 60}")
        print("  Skill Discovery")
        print(f"{'─' * 60}")
        for e in skill_events:
            print(f"  candidates : {e['candidates_found']}")
            print(f"  top match  : {e['top_match_name']}  (score={e['top_match_score']})")

        print(f"\n{'─' * 60}")
        print("  Budget Rebalance (PLAN phase)")
        print(f"{'─' * 60}")
        for e in budget_events[:1]:
            print(f"  phase      : {e['phase']}")
            print(f"  utilization: {e['utilization']:.1%}")
            for slot, alloc in e["allocations"].items():
                print(f"    {slot:<16} {alloc:>8} tokens")

        if compaction_events:
            print(f"\n{'─' * 60}")
            print("  Compaction")
            print(f"{'─' * 60}")
            for e in compaction_events:
                print(f"  reclaimed  : {e['total_tokens_reclaimed']} tokens")
                print(f"  final util : {e['final_utilization']:.1%}")

        print(f"\n{'━' * 60}\n")
        await agent.close()
    finally:
        agent_mod.AnthropicAdapter = original


if __name__ == "__main__":
    asyncio.run(main())
