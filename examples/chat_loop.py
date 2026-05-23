"""Demo: ask_user + resume loop. The agent can pause to ask the user a question.

Requires: ANTHROPIC_API_KEY environment variable (loaded from .env).

Usage:
    # interactive
    python examples/chat_loop.py

    # scripted (for testing without a TTY): answers are read from CHAT_LOOP_ANSWERS,
    # a colon-separated string in the order the agent will ask them
    CHAT_LOOP_ANSWERS="production_db:yes" python examples/chat_loop.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from mori import Mori
from mori.types import RunStatus


def _next_scripted_answer(prompts_seen: int, scripted: list[str] | None) -> str | None:
    """Return the next scripted answer if available, else None to fall back to input()."""
    if scripted is None:
        return None
    if prompts_seen < len(scripted):
        return scripted[prompts_seen]
    return None


def main() -> int:
    scripted_raw = os.environ.get("CHAT_LOOP_ANSWERS")
    scripted: list[str] | None = scripted_raw.split(":") if scripted_raw else None

    async def _main() -> None:
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-haiku-4-5-20251001")
            .checkpointer("inmemory")
            .build()
        )

        result = await agent.run(
            "I want to migrate my database. Before doing anything, call the "
            "ask_user tool to find out which database the user wants to migrate. "
            "Then report the answer back."
        )

        prompts_seen = 0
        while result.status == RunStatus.PAUSED and result.paused_prompt is not None:
            print(f"\nAgent asks: {result.paused_prompt}")
            scripted_answer = _next_scripted_answer(prompts_seen, scripted)
            if scripted_answer is not None:
                answer = scripted_answer
                print(f"> {answer}  (scripted)")
            else:
                if not sys.stdin.isatty():
                    print(
                        "(non-interactive, no scripted answer available — aborting)",
                        file=sys.stderr,
                    )
                    break
                answer = input("> ").strip()
            prompts_seen += 1
            result = await agent.resume(result.thread_id, answer)

        print(f"\nFinal status: {result.status}")
        print(f"Steps: {result.total_steps}")
        if result.final_output:
            print(f"Output: {result.final_output}")

    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
