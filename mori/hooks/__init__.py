"""Hooks — priority-ordered lifecycle callbacks.

YieldToUser is intentionally NOT re-exported here. It is an internal signal
raised by the ask_user tool and caught by the agent loop; external code
should not raise or catch it. Internal callers import it directly from
mori.hooks.exceptions.
"""

from mori.hooks.events import HookEvents, TurnEndReason
from mori.hooks.exceptions import HookBlock, HookRetry
from mori.hooks.payloads import TurnEndPayload, TurnStartPayload
from mori.hooks.registry import HookRegistry
from mori.hooks.types import HookConfig, HookRegistration

__all__ = [
    "HookBlock",
    "HookConfig",
    "HookEvents",
    "HookRegistration",
    "HookRegistry",
    "HookRetry",
    "TurnEndPayload",
    "TurnEndReason",
    "TurnStartPayload",
]
