"""Demo: force a retry with HookRetry when the previous response speculates.

Requires: ANTHROPIC_API_KEY environment variable (loaded from .env).

Usage:
    python examples/hooks_retry.py

This example asks a question that the model cannot answer from training data
(real-time system metrics). If the model speculates anyway, the hook injects
feedback and forces the loop to re-think.
"""
from __future__ import annotations

import asyncio

from dotenv import load_dotenv

load_dotenv()

from mori import Mori
from mori.hooks import HookEvents, HookRetry

SPECULATION_MARKERS = (
    "probably is",
    "should be",
    "i believe",
    "presumably",
    "i'd guess",
    "i'd estimate",
    "i would estimate",
    "i don't have",
)


async def require_grounding(request):
    """If the last assistant message contains speculation without a tool call, retry."""
    for msg in reversed(request.messages):
        if msg.role == "assistant" and isinstance(msg.content, str):
            last = msg.content.lower()
            speculated = any(m in last for m in SPECULATION_MARKERS)
            if speculated and not msg.tool_calls:
                raise HookRetry(
                    "Your previous response speculates without using a tool. "
                    "If you genuinely cannot answer, say so explicitly and stop. "
                    "Do not guess.",
                    hook_id="no_speculation",
                )
            break
    return None


def main() -> int:
    async def _main() -> None:
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-haiku-4-5-20251001")
            .hook(HookEvents.MODEL_REQUEST_BEFORE, require_grounding, priority=50)
            .build()
        )

        result = await agent.run(
            "What's the current load average on prod-web-01? "
            "If you cannot find out, say so plainly."
        )
        print(f"status={result.status}")
        print(f"steps={result.total_steps}")
        print(f"final: {result.final_output}")

    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
