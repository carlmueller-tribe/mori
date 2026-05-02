"""Hook system types."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from mori.types import MoriModel

HookHandler = Callable[[Any], Any] | Callable[[Any], Awaitable[Any]]


class HookConfig(MoriModel):
    max_hooks_per_event: int = 50
    hook_timeout_sec: float = 10.0
    fail_open: bool = True
    log_hook_errors: bool = True


class HookRegistration(MoriModel):
    hook_id: str
    event_name: str
    handler_name: str
    priority: int
    registered_at: datetime
    model_config = {"frozen": False, "extra": "forbid"}
