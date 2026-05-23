"""Public exceptions (HookBlock, HookRetry) and internal signal (YieldToUser)."""

from __future__ import annotations


class HookBlock(Exception):
    """Raised by a dispatch_before hook to veto the operation.

    Short-circuits the hook chain. Propagates to the runtime, which
    translates it into a denial per the event type (see spec §6.2).
    Never swallowed regardless of fail_open — policy decisions are not errors.
    """

    def __init__(self, reason: str, *, hook_id: str | None = None) -> None:
        self.reason = reason
        self.hook_id = hook_id
        super().__init__(reason)


class HookRetry(Exception):
    """Raised by a dispatch_before hook to force a loop iteration.

    Short-circuits the hook chain. The runtime appends `feedback` as a
    system message and iterates again, bounded by HookConfig.max_retry_limit.
    Only meaningful on events that gate model output (model.request.before,
    turn.end). On observe-only events: logged + ignored.
    """

    def __init__(self, feedback: str, *, hook_id: str | None = None) -> None:
        self.feedback = feedback
        self.hook_id = hook_id
        super().__init__(feedback)


class YieldToUser(Exception):
    """Internal signal raised by the ask_user tool to pause the agent.

    Not part of the public API. Caught by `_phase_act` in the loop, which
    transitions state to RunStatus.PAUSED with paused_reason='await_user_input'.
    """

    def __init__(self, question: str) -> None:
        self.question = question
        super().__init__(question)
