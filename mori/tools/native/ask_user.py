"""ask_user — pause the agent and yield to the caller for a response."""

from __future__ import annotations

from mori.hooks.exceptions import YieldToUser


async def ask_user(question: str) -> str:
    """Ask the calling user a question and wait for their response.

    Raising YieldToUser is caught by the agent loop, which transitions
    state to RunStatus.PAUSED and saves a checkpoint. The caller resumes
    via `agent.resume(thread_id, user_response)`; the resume injects the
    response as this tool's result.
    """
    raise YieldToUser(question)
