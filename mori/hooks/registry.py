"""HookRegistry — priority dispatch with timeout and fail_open."""

from __future__ import annotations

import asyncio
import inspect
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog

from mori.hooks.exceptions import HookBlock, HookRetry
from mori.hooks.types import HookConfig, HookHandler, HookRegistration

log = structlog.get_logger()


class HookRegistry:
    def __init__(self, config: HookConfig | None = None) -> None:
        self._config = config or HookConfig()
        # event_name -> [(priority, hook_id, handler)]
        self._hooks: dict[str, list[tuple[int, str, HookHandler]]] = {}
        self._registrations: dict[str, HookRegistration] = {}

    def register(
        self,
        event_name: str,
        handler: HookHandler,
        priority: int = 100,
        name: str | None = None,
    ) -> str:
        hooks = self._hooks.setdefault(event_name, [])
        if len(hooks) >= self._config.max_hooks_per_event:
            raise ValueError(
                f"Max hooks per event ({self._config.max_hooks_per_event}) reached for '{event_name}'"  # noqa: E501
            )
        hook_id = f"hook_{secrets.token_hex(6)}"
        hooks.append((priority, hook_id, handler))
        hooks.sort(key=lambda t: t[0])
        raw_name = name or getattr(handler, "__name__", None) or repr(handler)
        handler_name: str = raw_name if isinstance(raw_name, str) else repr(raw_name)
        self._registrations[hook_id] = HookRegistration(
            hook_id=hook_id,
            event_name=event_name,
            handler_name=handler_name,
            priority=priority,
            registered_at=datetime.now(UTC),
        )
        return hook_id

    def unregister(self, hook_id: str) -> bool:
        if hook_id not in self._registrations:
            return False
        reg = self._registrations.pop(hook_id)
        self._hooks[reg.event_name] = [
            t for t in self._hooks.get(reg.event_name, []) if t[1] != hook_id
        ]  # noqa: E501
        return True

    def hook(self, event_name: str, priority: int = 100) -> Callable[[HookHandler], HookHandler]:
        def decorator(fn: HookHandler) -> HookHandler:
            self.register(event_name, fn, priority=priority, name=fn.__name__)
            return fn

        return decorator

    async def _call(self, handler: HookHandler, payload: Any) -> Any:
        try:
            if inspect.iscoroutinefunction(handler):
                awaitable: Awaitable[Any] = handler(payload)
            else:
                loop = asyncio.get_running_loop()
                awaitable = loop.run_in_executor(None, handler, payload)
            return await asyncio.wait_for(awaitable, timeout=self._config.hook_timeout_sec)
        except (HookBlock, HookRetry):
            # Policy signals are NEVER swallowed, regardless of fail_open.
            raise
        except TimeoutError:
            if self._config.log_hook_errors:
                log.warning("hook.timeout", handler=getattr(handler, "__name__", "?"))
            if not self._config.fail_open:
                raise
            return None
        except Exception as exc:
            if self._config.log_hook_errors:
                log.warning("hook.error", handler=getattr(handler, "__name__", "?"), error=str(exc))
            if not self._config.fail_open:
                raise
            return None

    async def dispatch_before(self, event_name: str, payload: Any) -> Any:
        current = payload
        for _priority, hook_id, handler in self._hooks.get(event_name, []):
            try:
                result = await self._call(handler, current)
            except HookBlock as e:
                if e.hook_id is None:
                    e.hook_id = hook_id
                raise
            except HookRetry as e:
                if e.hook_id is None:
                    e.hook_id = hook_id
                raise
            if result is not None:
                # Audit: a hook returned a non-None payload, meaning it
                # transformed the value. We log at info so operators can
                # detect silent mutations (e.g. a tool.invoke.before hook
                # rewriting tool arguments). The payload is not logged
                # itself — it may contain conversation/tool data.
                log.info(
                    "hook.payload_mutated",
                    handler=getattr(handler, "__name__", "?"),
                    hook_id=hook_id,
                    event_name=event_name,
                )
                current = result
        return current

    async def dispatch_after(self, event_name: str, payload: Any) -> None:
        for _priority, hook_id, handler in self._hooks.get(event_name, []):
            try:
                await self._call(handler, payload)
            except (HookBlock, HookRetry) as exc:
                # Block/retry on after-event is a hook author error — log + swallow.
                # Other handlers continue to process.
                if self._config.log_hook_errors:
                    log.warning(
                        "hook.invalid_signal_on_after",
                        handler=getattr(handler, "__name__", "?"),
                        hook_id=hook_id,
                        event_name=event_name,
                        signal=type(exc).__name__,
                    )

    def list_hooks(self, event_name: str | None = None) -> list[HookRegistration]:
        if event_name is not None:
            return [r for r in self._registrations.values() if r.event_name == event_name]
        return list(self._registrations.values())

    def clear(self, event_name: str | None = None) -> int:
        if event_name is not None:
            removed = len(self._hooks.pop(event_name, []))
            for hid in [
                hid for hid, r in self._registrations.items() if r.event_name == event_name
            ]:  # noqa: E501
                del self._registrations[hid]
            return removed
        count = sum(len(v) for v in self._hooks.values())
        self._hooks.clear()
        self._registrations.clear()
        return count
