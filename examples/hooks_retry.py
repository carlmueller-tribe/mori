"""Demo: force a retry with HookRetry when the response speculates without grounding."""
from __future__ import annotations

import asyncio

from mori import Mori
from mori.hooks import HookEvents, HookRetry

SPECULATION_MARKERS = ("probably is", "should be", "i believe", "presumably")


def main() -> int:
    async def _main() -> None:
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-sonnet-4-20250514")
            .build()
        )

        @agent.hooks.hook(HookEvents.MODEL_REQUEST_BEFORE, priority=50)
        async def require_grounding(request):
            for msg in reversed(request.messages):
                if msg.role == "assistant" and isinstance(msg.content, str):
                    last = msg.content.lower()
                    if any(m in last for m in SPECULATION_MARKERS) and not msg.tool_calls:
                        raise HookRetry(
                            "Previous response contains speculation without a "
                            "tool call. Re-think and ground the answer in evidence."
                        )
                    break
            return None

        result = await agent.run("What's the current load average on prod-web-01?")
        print(result.final_output)

    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
