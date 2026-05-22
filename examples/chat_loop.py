"""Demo: ask_user + resume loop. The agent can pause to ask the user a question."""
from __future__ import annotations

import asyncio

from mori import Mori
from mori.types import RunStatus


def main() -> int:
    async def _main() -> None:
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-sonnet-4-20250514")
            .checkpointer("memory")
            .build()
        )

        result = await agent.run(
            "Migrate the user table. If you need any details, use ask_user."
        )

        while result.status == RunStatus.PAUSED and result.paused_prompt is not None:
            print(f"\nAgent asks: {result.paused_prompt}")
            answer = input("> ").strip()
            result = await agent.resume(result.thread_id, answer)

        print(f"\nFinal status: {result.status}")
        if result.final_output:
            print(f"Output: {result.final_output}")

    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
