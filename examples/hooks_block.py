"""Demo: block a tool call with HookBlock.

Run: python examples/hooks_block.py
"""
from __future__ import annotations

import asyncio

from mori import Mori
from mori.hooks import HookBlock, HookEvents


def main() -> int:
    async def _main() -> None:
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-sonnet-4-20250514")
            .build()
        )

        @agent.hooks.hook(HookEvents.TOOL_INVOKE_BEFORE, priority=50)
        async def block_prod_writes(call):
            if call.name == "apply_migration" and call.arguments.get("env") == "prod":
                raise HookBlock("production migrations must go through CI")
            return None

        result = await agent.run("Apply the user_email migration to prod")
        print(f"status={result.status}")
        print(f"messages={len(result.messages)}")

    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
