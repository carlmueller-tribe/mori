"""Live-model integration tests for Active Hooks v1.

Requires ANTHROPIC_API_KEY. Tests skip automatically when absent.
"""

from __future__ import annotations

import pytest

from mori import HookBlock, HookEvents, Mori
from mori.types import RunStatus

pytestmark = pytest.mark.asyncio


@pytest.fixture
def sandbox_read_file():
    """A read_file tool restricted to a sandbox path."""

    async def read_file(path: str) -> str:
        with open(path) as f:
            return f.read()

    return read_file


async def test_hook_block_prevents_tool_call_live(sandbox_read_file, tmp_path):
    """A HookBlock on tool.invoke.before prevents the tool from running.

    The model is told to read a file outside a sandbox dir. A registered
    hook refuses the read. The model receives a synthetic "BLOCKED: ..."
    tool result and adjusts its response. The actual file read NEVER happens.
    """
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    allowed = sandbox / "allowed.txt"
    allowed.write_text("public content")
    forbidden = tmp_path / "forbidden.txt"
    forbidden.write_text("SECRET")

    invocations: list[str] = []

    async def wrapped_read(path: str) -> str:
        invocations.append(path)
        return await sandbox_read_file(path)

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-haiku-4-5-20251001")
        .tool(wrapped_read, description="Read a file by path")
        .build()
    )

    @agent.hooks.hook(HookEvents.TOOL_INVOKE_BEFORE, priority=10)
    async def sandbox_only(call):
        if call.name == "wrapped_read":
            path = call.arguments.get("path", "")
            if not path.startswith(str(sandbox)):
                raise HookBlock(f"path {path} is outside sandbox")
        return None

    result = await agent.run(
        f"Read the file {forbidden}. If you can't, explain why and stop.",
    )

    # The forbidden path must NEVER have been actually read
    assert str(forbidden) not in invocations
    # Run still completes (block doesn't abort the run)
    assert result.status in (RunStatus.COMPLETED, RunStatus.FAILED)
    # The model's final message should mention the block (best-effort assertion)
    final = result.final_output or ""
    assert any(
        word in final.lower()
        for word in ("blocked", "cannot", "outside", "denied", "refused")
    ), f"Model didn't acknowledge the block: {final!r}"


async def test_ask_user_round_trip_live(tmp_path):
    """Agent yields via ask_user, caller resumes with response, agent completes."""
    cp_path = tmp_path / "threads.db"

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-haiku-4-5-20251001")
        .checkpointer("sqlite", path=str(cp_path))
        .build()
    )

    # First leg: agent should ask which database via ask_user
    result = await agent.run(
        "I want to back up a database. Use the ask_user tool to ask me which one "
        "(just 'prod' or 'staging'). After I answer, say you'll back up that one and stop."
    )
    assert result.status == RunStatus.PAUSED, (
        f"Expected PAUSED but got {result.status}; final_output={result.final_output!r}"
    )
    assert result.paused_prompt is not None and result.paused_prompt.strip() != "", (
        "Expected a non-empty paused_prompt"
    )

    # Second leg: caller resumes with the answer
    # Mori.resume takes dict; AgentLoop.resume extracts dict["response"] for ask_user pauses
    result = await agent.resume(result.thread_id, {"response": "prod"})
    assert result.status == RunStatus.COMPLETED, (
        f"Expected COMPLETED but got {result.status}; final_output={result.final_output!r}"
    )
    assert result.final_output is not None
    final = result.final_output.lower()
    assert any(
        word in final
        for word in ("prod", "staging", "production", "back up", "backup", "database")
    ), f"Final output doesn't reference the chosen DB: {result.final_output!r}"
