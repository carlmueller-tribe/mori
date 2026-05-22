"""Demo: block a tool call with HookBlock.

Requires: ANTHROPIC_API_KEY environment variable (loaded from .env).

Usage:
    python examples/hooks_block.py
"""
from __future__ import annotations

import asyncio

from dotenv import load_dotenv

load_dotenv()

from mori import Mori
from mori.hooks import HookBlock, HookEvents


def apply_migration(name: str, env: str) -> str:
    """Apply a database migration by name to the given environment.

    Args:
        name: migration name (e.g. 'user_email')
        env: target environment (e.g. 'dev', 'staging', 'prod')
    """
    return f"Applied {name} to {env}"


async def block_prod_writes(call):
    if call.name == "apply_migration" and call.arguments.get("env") == "prod":
        raise HookBlock(
            f"production migrations must go through CI (attempted: {call.arguments.get('name')})",
            hook_id="prod_migration_gate",
        )
    return None


def main() -> int:
    async def _main() -> None:
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-haiku-4-5-20251001")
            .tool(apply_migration, "Apply a database migration to an environment")
            .hook(HookEvents.TOOL_INVOKE_BEFORE, block_prod_writes, priority=50)
            .build()
        )

        result = await agent.run(
            "Apply the user_email migration to prod by calling apply_migration."
        )
        print(f"status={result.status}")
        print(f"messages={len(result.messages)}")
        for m in result.messages:
            if m.role == "tool" and isinstance(m.content, str) and "BLOCKED" in m.content:
                print(f"  blocked message: {m.content}")
        if result.final_output:
            print(f"final: {result.final_output}")

    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
