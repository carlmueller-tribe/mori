# Mori v0.7 "It Enforces" — Active Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `HookRegistry` so hooks can block (`HookBlock`) or force retry (`HookRetry`), add `turn.start`/`turn.end` events that work in both autonomous and chat modes, and ship a native `ask_user` tool that yields control to the caller via the existing checkpoint/resume path.

**Architecture:** All changes are additive — no breaking changes. Two new exception types caught by `HookRegistry.dispatch_before` and propagated to the runtime. Two new events fire at every entry/exit of `_run_from_state`. A new internal `YieldToUser` signal raised by the `ask_user` tool is caught by `_phase_act`, which transitions the agent to `RunStatus.PAUSED` with `paused_reason="await_user_input"`. The existing `agent.resume(thread_id, input)` is extended to inject the user response as the paused tool call's result.

**Tech Stack:** Python 3.12+, pytest, pytest-asyncio, structlog, Pydantic v2. Repository uses `uv`. Test runner: `pytest tests/<file>::<test> -v`. All async.

**Spec:** `docs/superpowers/specs/2026-05-21-mori-v07-active-hooks-design.md`

---

## File Structure

### Create

| File | Responsibility |
|---|---|
| `mori/hooks/exceptions.py` | `HookBlock`, `HookRetry` public exceptions; `YieldToUser` internal signal |
| `mori/hooks/events.py` | `HookEvents` constants class; `TurnEndReason` enum |
| `mori/hooks/payloads.py` | `TurnStartPayload`, `TurnEndPayload` Pydantic models |
| `mori/tools/native/__init__.py` | Package marker |
| `mori/tools/native/ask_user.py` | The `ask_user` native tool implementation |
| `tests/test_hook_exceptions.py` | Construction + attribute tests for the new exceptions |
| `tests/test_hook_events_v07.py` | Constants + payload tests |
| `tests/test_hook_block.py` | `HookBlock` propagation across events |
| `tests/test_hook_retry.py` | `HookRetry` semantics + `MAX_RETRY_LIMIT` |
| `tests/test_ask_user.py` | Yield + resume integration |
| `tests/test_active_hooks_integration.py` | End-to-end scenarios |
| `tests/test_hook_invariants.py` | Property tests |
| `examples/hooks_block.py` | Demo: blocking a tool call |
| `examples/hooks_retry.py` | Demo: forcing a retry on speculation |
| `examples/chat_loop.py` | Demo: `ask_user` + resume loop |
| `mori-docs/architecture/hooks.md` | Architecture doc for the three hook modes |
| `mori-docs/architecture/chat-mode.md` | Architecture doc for chat mode |

### Modify

| File | Change |
|---|---|
| `mori/hooks/types.py` | Add `max_retry_limit: int = 3` to `HookConfig` |
| `mori/hooks/registry.py` | `dispatch_before` propagates `HookBlock`/`HookRetry` without swallowing |
| `mori/hooks/__init__.py` | Export new symbols |
| `mori/types.py` | Add `RunStatus.BLOCKED` variant |
| `mori/runtime/state.py` | Add `paused_prompt: str \| None = None` field |
| `mori/runtime/result.py` | Add `block_reason`, `block_hook_id`, `paused_prompt` fields |
| `mori/runtime/loop.py` | Fire `turn.start`/`turn.end`; catch hook exceptions; handle `YieldToUser`; resume-injection |
| `mori/tools/registry.py` | Re-raise control exceptions (`YieldToUser`, `HookBlock`, `HookRetry`) |
| `mori/agent.py` | Auto-register `ask_user`; `disable_native_tool()` builder method |
| `README.md` | Add chat-mode example to Quick Start |

---

## Task Sequence

Tasks 1-3 add the exception machinery. Tasks 4-5 add state/result fields and the new event firing. Tasks 6-10 wire each event's block/retry semantics with bounded retries. Tasks 11-15 add `ask_user` and chat mode. Tasks 16-17 add invariant tests, integration tests, examples, and docs.

---

### Task 1: HookBlock and HookRetry exception types

**Files:**
- Create: `mori/hooks/exceptions.py`
- Test: `tests/test_hook_exceptions.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hook_exceptions.py
"""Tests for HookBlock, HookRetry, YieldToUser exception types."""

from __future__ import annotations

import pytest

from mori.hooks.exceptions import HookBlock, HookRetry, YieldToUser


class TestHookBlock:
    def test_carries_reason(self) -> None:
        e = HookBlock("not allowed")
        assert e.reason == "not allowed"
        assert str(e) == "not allowed"

    def test_hook_id_optional(self) -> None:
        e = HookBlock("nope")
        assert e.hook_id is None

    def test_hook_id_settable(self) -> None:
        e = HookBlock("nope", hook_id="hook_abc")
        assert e.hook_id == "hook_abc"

    def test_is_exception(self) -> None:
        with pytest.raises(HookBlock):
            raise HookBlock("test")


class TestHookRetry:
    def test_carries_feedback(self) -> None:
        e = HookRetry("re-think")
        assert e.feedback == "re-think"
        assert str(e) == "re-think"

    def test_hook_id_optional(self) -> None:
        e = HookRetry("re-think")
        assert e.hook_id is None

    def test_is_exception(self) -> None:
        with pytest.raises(HookRetry):
            raise HookRetry("test")


class TestYieldToUser:
    def test_carries_question(self) -> None:
        e = YieldToUser("which db?")
        assert e.question == "which db?"
        assert str(e) == "which db?"

    def test_is_exception(self) -> None:
        with pytest.raises(YieldToUser):
            raise YieldToUser("test")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hook_exceptions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mori.hooks.exceptions'`

- [ ] **Step 3: Write the exceptions module**

```python
# mori/hooks/exceptions.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hook_exceptions.py -v`
Expected: PASS — all 8 tests green.

- [ ] **Step 5: Commit**

```bash
git add mori/hooks/exceptions.py tests/test_hook_exceptions.py
git commit -m "feat(hooks): add HookBlock, HookRetry, YieldToUser exception types

Public exceptions HookBlock(reason) and HookRetry(feedback) carry an
optional hook_id. Internal YieldToUser(question) signals the ask_user
tool's pause request. Wiring into the runtime arrives in later tasks."
```

---

### Task 2: HookEvents constants + TurnEndReason enum + payload types

**Files:**
- Create: `mori/hooks/events.py`
- Create: `mori/hooks/payloads.py`
- Test: `tests/test_hook_events_v07.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hook_events_v07.py
"""Tests for HookEvents constants, TurnEndReason enum, and turn payloads."""

from __future__ import annotations

from datetime import UTC, datetime

from mori.hooks.events import HookEvents, TurnEndReason
from mori.hooks.payloads import TurnEndPayload, TurnStartPayload
from mori.runtime.state import MoriState
from mori.types import RunId, ThreadId


class TestHookEvents:
    def test_new_events_defined(self) -> None:
        assert HookEvents.TURN_START == "turn.start"
        assert HookEvents.TURN_END == "turn.end"

    def test_existing_events_preserved(self) -> None:
        assert HookEvents.MODEL_REQUEST_BEFORE == "model.request.before"
        assert HookEvents.MODEL_RESPONSE_AFTER == "model.response.after"
        assert HookEvents.PERMISSION_CHECK_AFTER == "permission.check.after"
        assert HookEvents.TOOL_INVOKE_BEFORE == "tool.invoke.before"
        assert HookEvents.TOOL_INVOKE_AFTER == "tool.invoke.after"
        assert HookEvents.RUN_START == "run.start"
        assert HookEvents.RUN_END == "run.end"


class TestTurnEndReason:
    def test_all_variants(self) -> None:
        assert TurnEndReason.COMPLETED == "completed"
        assert TurnEndReason.PAUSED_AWAIT_USER == "paused_await_user"
        assert TurnEndReason.PAUSED_ESCALATE == "paused_escalate"
        assert TurnEndReason.EXHAUSTED == "exhausted"
        assert TurnEndReason.ERRORED == "errored"
        assert TurnEndReason.BLOCKED == "blocked"


class TestTurnPayloads:
    def test_turn_start_payload(self) -> None:
        p = TurnStartPayload(input="hi", thread_id=ThreadId("t1"), is_resume=False)
        assert p.input == "hi"
        assert p.thread_id == "t1"
        assert p.is_resume is False

    def test_turn_end_payload(self) -> None:
        state = MoriState(
            run_id=RunId("r1"),
            thread_id=ThreadId("t1"),
            task="x",
            started_at=datetime.now(UTC),
            last_progress_at=datetime.now(UTC),
        )
        p = TurnEndPayload(state=state, reason=TurnEndReason.COMPLETED)
        assert p.state.run_id == "r1"
        assert p.reason == TurnEndReason.COMPLETED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hook_events_v07.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mori.hooks.events'`

- [ ] **Step 3: Write events.py and payloads.py**

```python
# mori/hooks/events.py
"""Typed constants for known hook events. String registration stays valid."""

from __future__ import annotations

from enum import StrEnum


class HookEvents:
    """Constants for hook event names.

    Strings are intentional — they match the existing string-keyed
    registration API and stay valid for back-compat.
    """

    TURN_START = "turn.start"
    TURN_END = "turn.end"
    MODEL_REQUEST_BEFORE = "model.request.before"
    MODEL_RESPONSE_AFTER = "model.response.after"
    PERMISSION_CHECK_AFTER = "permission.check.after"
    TOOL_INVOKE_BEFORE = "tool.invoke.before"
    TOOL_INVOKE_AFTER = "tool.invoke.after"
    RUN_START = "run.start"
    RUN_END = "run.end"


class TurnEndReason(StrEnum):
    COMPLETED = "completed"
    PAUSED_AWAIT_USER = "paused_await_user"
    PAUSED_ESCALATE = "paused_escalate"
    EXHAUSTED = "exhausted"
    ERRORED = "errored"
    BLOCKED = "blocked"
```

```python
# mori/hooks/payloads.py
"""Payload types for turn.start and turn.end hook events."""

from __future__ import annotations

from mori.hooks.events import TurnEndReason
from mori.runtime.state import MoriState
from mori.types import MoriModel, ThreadId


class TurnStartPayload(MoriModel):
    input: str
    thread_id: ThreadId
    is_resume: bool


class TurnEndPayload(MoriModel):
    state: MoriState
    reason: TurnEndReason
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hook_events_v07.py -v`
Expected: PASS — all 4 tests green.

- [ ] **Step 5: Commit**

```bash
git add mori/hooks/events.py mori/hooks/payloads.py tests/test_hook_events_v07.py
git commit -m "feat(hooks): add HookEvents constants, TurnEndReason, turn payloads

HookEvents class exposes typed string constants for all known events
(7 existing + turn.start/turn.end). TurnEndReason enum covers the
6 reasons a turn can end. TurnStartPayload and TurnEndPayload are
the payload types for the new events."
```

---

### Task 3: HookRegistry propagates HookBlock and HookRetry

**Files:**
- Modify: `mori/hooks/registry.py:89-95` (`dispatch_before`)
- Modify: `mori/hooks/types.py:14-19` (add `max_retry_limit`)
- Modify: `mori/hooks/__init__.py` (export new symbols)
- Test: `tests/test_hook_block.py` (block propagation only; runtime handling later)
- Test: `tests/test_hook_retry.py` (retry propagation only; runtime handling later)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hook_block.py
"""HookBlock propagation through HookRegistry.dispatch_before."""

from __future__ import annotations

import pytest

from mori.hooks.exceptions import HookBlock
from mori.hooks.registry import HookRegistry


@pytest.mark.asyncio
async def test_dispatch_before_propagates_hook_block() -> None:
    reg = HookRegistry()

    async def blocker(payload: object) -> None:
        raise HookBlock("not allowed")

    reg.register("e", blocker)
    with pytest.raises(HookBlock) as exc:
        await reg.dispatch_before("e", {"x": 1})
    assert exc.value.reason == "not allowed"
    assert exc.value.hook_id is not None  # registry stamped it


@pytest.mark.asyncio
async def test_hook_block_short_circuits_chain() -> None:
    reg = HookRegistry()
    later_ran = False

    async def blocker(payload: object) -> None:
        raise HookBlock("stop")

    async def later(payload: object) -> object:
        nonlocal later_ran
        later_ran = True
        return payload

    reg.register("e", blocker, priority=50)
    reg.register("e", later, priority=100)
    with pytest.raises(HookBlock):
        await reg.dispatch_before("e", {})
    assert later_ran is False


@pytest.mark.asyncio
async def test_hook_block_not_swallowed_when_fail_open_true() -> None:
    from mori.hooks.types import HookConfig

    reg = HookRegistry(config=HookConfig(fail_open=True))

    async def blocker(payload: object) -> None:
        raise HookBlock("never silenced")

    reg.register("e", blocker)
    with pytest.raises(HookBlock):
        await reg.dispatch_before("e", {})
```

```python
# tests/test_hook_retry.py
"""HookRetry propagation through HookRegistry.dispatch_before."""

from __future__ import annotations

import pytest

from mori.hooks.exceptions import HookRetry
from mori.hooks.registry import HookRegistry
from mori.hooks.types import HookConfig


@pytest.mark.asyncio
async def test_dispatch_before_propagates_hook_retry() -> None:
    reg = HookRegistry()

    async def retrier(payload: object) -> None:
        raise HookRetry("re-think")

    reg.register("e", retrier)
    with pytest.raises(HookRetry) as exc:
        await reg.dispatch_before("e", {})
    assert exc.value.feedback == "re-think"
    assert exc.value.hook_id is not None


@pytest.mark.asyncio
async def test_hook_retry_not_swallowed_when_fail_open_true() -> None:
    reg = HookRegistry(config=HookConfig(fail_open=True))

    async def retrier(payload: object) -> None:
        raise HookRetry("silenced?")

    reg.register("e", retrier)
    with pytest.raises(HookRetry):
        await reg.dispatch_before("e", {})


def test_hook_config_has_max_retry_limit_default() -> None:
    config = HookConfig()
    assert config.max_retry_limit == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hook_block.py tests/test_hook_retry.py -v`
Expected: FAIL — `HookBlock` is currently swallowed by the generic `except Exception` in `_call`; `HookConfig.max_retry_limit` does not exist.

- [ ] **Step 3: Add max_retry_limit to HookConfig**

Replace the full body of `mori/hooks/types.py`:

```python
# mori/hooks/types.py
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
    max_retry_limit: int = 3


class HookRegistration(MoriModel):
    hook_id: str
    event_name: str
    handler_name: str
    priority: int
    registered_at: datetime
    model_config = {"frozen": False, "extra": "forbid"}
```

- [ ] **Step 4: Modify HookRegistry to propagate HookBlock/HookRetry**

Edit `mori/hooks/registry.py`. Add imports at top:

```python
from mori.hooks.exceptions import HookBlock, HookRetry
```

Replace `_call` and `dispatch_before` with the new implementation:

```python
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
                current = result
        return current
```

- [ ] **Step 5: Export new symbols from `mori/hooks/__init__.py`**

```python
# mori/hooks/__init__.py
"""Hooks — priority-ordered lifecycle callbacks."""

from mori.hooks.events import HookEvents, TurnEndReason
from mori.hooks.exceptions import HookBlock, HookRetry, YieldToUser
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
    "YieldToUser",
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_hook_block.py tests/test_hook_retry.py tests/test_hooks.py -v`
Expected: All new tests PASS. Existing `tests/test_hooks.py` PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
git add mori/hooks/registry.py mori/hooks/types.py mori/hooks/__init__.py \
        tests/test_hook_block.py tests/test_hook_retry.py
git commit -m "feat(hooks): propagate HookBlock and HookRetry through dispatch_before

HookRegistry no longer swallows HookBlock/HookRetry exceptions even
when fail_open=True. Both exceptions short-circuit the chain — later
hooks for the same event don't run. Adds max_retry_limit (default 3)
to HookConfig for bounding HookRetry loops. Runtime handling of the
propagated exceptions arrives in later tasks."
```

---

### Task 4: State and result fields for v0.7

**Files:**
- Modify: `mori/types.py` (add `RunStatus.BLOCKED`)
- Modify: `mori/runtime/state.py` (add `paused_prompt`)
- Modify: `mori/runtime/result.py` (add `block_reason`, `block_hook_id`, `paused_prompt`)
- Test: extend `tests/test_state.py`, `tests/test_result.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state.py`:

```python
def test_paused_prompt_default_none() -> None:
    from datetime import UTC, datetime

    from mori.runtime.state import MoriState
    from mori.types import RunId, ThreadId

    state = MoriState(
        run_id=RunId("r1"),
        thread_id=ThreadId("t1"),
        task="x",
        started_at=datetime.now(UTC),
        last_progress_at=datetime.now(UTC),
    )
    assert state.paused_prompt is None


def test_paused_prompt_settable() -> None:
    from datetime import UTC, datetime

    from mori.runtime.state import MoriState
    from mori.types import RunId, ThreadId

    state = MoriState(
        run_id=RunId("r1"),
        thread_id=ThreadId("t1"),
        task="x",
        started_at=datetime.now(UTC),
        last_progress_at=datetime.now(UTC),
        paused_prompt="which db?",
    )
    assert state.paused_prompt == "which db?"
```

Append to `tests/test_result.py`:

```python
def test_result_blocked_fields_default_none() -> None:
    from mori.runtime.result import RunResult
    from mori.types import RunId, RunStatus, ThreadId

    r = RunResult(
        run_id=RunId("r1"),
        thread_id=ThreadId("t1"),
        status=RunStatus.COMPLETED,
        task="x",
    )
    assert r.block_reason is None
    assert r.block_hook_id is None
    assert r.paused_prompt is None


def test_result_blocked_fields_settable() -> None:
    from mori.runtime.result import RunResult
    from mori.types import RunId, RunStatus, ThreadId

    r = RunResult(
        run_id=RunId("r1"),
        thread_id=ThreadId("t1"),
        status=RunStatus.BLOCKED,
        task="x",
        block_reason="prod migration",
        block_hook_id="hook_abc",
    )
    assert r.status == "blocked"
    assert r.block_reason == "prod migration"


def test_run_status_has_blocked() -> None:
    from mori.types import RunStatus

    assert RunStatus.BLOCKED == "blocked"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_state.py tests/test_result.py -v -k "paused_prompt or blocked or block_reason"`
Expected: FAIL — fields don't exist; `RunStatus.BLOCKED` doesn't exist.

- [ ] **Step 3: Add RunStatus.BLOCKED**

Edit `mori/types.py`. In the `RunStatus` StrEnum (around line 38-45), add `BLOCKED = "blocked"` after `CANCELLED`:

```python
class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
```

- [ ] **Step 4: Add `paused_prompt` to MoriState**

Edit `mori/runtime/state.py`. Add the field right after `paused_tool_call`:

```python
    # Pause context (set when status == RunStatus.PAUSED after ESCALATE decision
    # or after an ask_user yield)
    paused_reason: str | None = None
    paused_tool_call: ToolCall | None = None
    paused_prompt: str | None = None
```

- [ ] **Step 5: Add fields to RunResult**

Edit `mori/runtime/result.py`. Add the three fields to `RunResult`:

```python
class RunResult(MoriModel):
    run_id: RunId
    thread_id: ThreadId
    status: RunStatus
    task: str
    final_output: str | None = None
    messages: list[Message] = Field(default_factory=list)
    total_steps: int = 0
    total_usage: TokenUsage = TokenUsage(input_tokens=0, output_tokens=0)
    total_tool_calls: int = 0
    total_duration_ms: float = 0.0
    checkpoint_id: CheckpointId | None = None
    block_reason: str | None = None
    block_hook_id: str | None = None
    paused_prompt: str | None = None
```

Also update `from_state` to propagate `paused_prompt`:

```python
        return RunResult(
            run_id=state.run_id,
            thread_id=state.thread_id,
            status=state.status,
            task=state.task,
            final_output=final_output,
            messages=state.messages,
            total_steps=state.step_count,
            total_usage=TokenUsage(
                input_tokens=state.total_input_tokens,
                output_tokens=state.total_output_tokens,
            ),
            total_tool_calls=state.total_tool_calls,
            total_duration_ms=duration_ms,
            checkpoint_id=checkpoint_id,
            paused_prompt=state.paused_prompt,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_state.py tests/test_result.py tests/test_types.py -v`
Expected: All tests PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add mori/types.py mori/runtime/state.py mori/runtime/result.py \
        tests/test_state.py tests/test_result.py
git commit -m "feat(runtime): add BLOCKED status + paused_prompt + block fields

RunStatus.BLOCKED is the new terminal state when a hook vetoes the
run. MoriState.paused_prompt holds the question text from ask_user.
RunResult exposes block_reason, block_hook_id, and paused_prompt to
the caller. Runtime wiring arrives in later tasks."
```

---

### Task 5: Fire turn.start and turn.end events (no block/retry yet)

**Files:**
- Modify: `mori/runtime/loop.py` (fire `turn.start` in `run()`/`resume()`, fire `turn.end` in `_run_from_state`)
- Test: extend `tests/test_loop_hooks_v05.py` or create `tests/test_turn_events.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_turn_events.py`:

```python
"""turn.start and turn.end fire on run() and resume()."""

from __future__ import annotations

from typing import Any

import pytest

from mori.hooks.events import HookEvents, TurnEndReason
from mori.hooks.registry import HookRegistry
from tests.conftest import build_minimal_agent  # See conftest helpers


@pytest.mark.asyncio
async def test_turn_start_fires_on_run() -> None:
    seen: list[Any] = []
    reg = HookRegistry()

    async def capture(payload: Any) -> None:
        seen.append(payload)
        return None

    reg.register(HookEvents.TURN_START, capture)
    agent = build_minimal_agent(hook_registry=reg)
    await agent.run("hello")
    assert len(seen) == 1
    assert seen[0].input == "hello"
    assert seen[0].is_resume is False


@pytest.mark.asyncio
async def test_turn_end_fires_on_run() -> None:
    seen: list[Any] = []
    reg = HookRegistry()

    async def capture(payload: Any) -> None:
        seen.append(payload)
        return None

    reg.register(HookEvents.TURN_END, capture)
    agent = build_minimal_agent(hook_registry=reg)
    await agent.run("hello")
    assert len(seen) == 1
    assert seen[0].reason in {TurnEndReason.COMPLETED, TurnEndReason.EXHAUSTED}
```

`build_minimal_agent` should already exist or be added to `tests/conftest.py`. If it doesn't, add a helper that builds an agent with a stub model returning a no-tool-calls assistant message immediately (so the loop terminates on the first iteration).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_turn_events.py -v`
Expected: FAIL — turn.start and turn.end events are never fired.

- [ ] **Step 3: Wire turn.start in `AgentLoop.run`**

Edit `mori/runtime/loop.py`. In the `run` method (~line 405), add the `turn.start` dispatch before `_run_from_state` is called:

```python
    async def run(
        self,
        task: str,
        thread_id: ThreadId | None = None,
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        thread_id = thread_id or ThreadId(f"th_{_uid()}")
        state = self._init_state(task=task, thread_id=thread_id, context=context)
        if self._hooks:
            from mori.hooks.events import HookEvents
            from mori.hooks.payloads import TurnStartPayload

            await self._hooks.dispatch_before(
                HookEvents.TURN_START,
                TurnStartPayload(input=task, thread_id=thread_id, is_resume=False),
            )
        # ... existing run.start event emission and _run_from_state call ...
```

(Preserve all existing `_emit(RunStartEvent(...))` and `dispatch_after("run.start", ...)` lines unchanged. Only add the turn.start dispatch_before call before them.)

- [ ] **Step 4: Wire turn.start in `AgentLoop.resume`**

Same edit pattern inside `resume(self, thread_id, input)` — fire `turn.start` with `is_resume=True` before `_run_from_state` is called. Use the raw `input` as the `input` field if it's a string, else `input.get("response", "")`.

- [ ] **Step 5: Wire turn.end in `_run_from_state`**

Inside `_run_from_state`, immediately before the existing `run.end` `dispatch_after` (around line 575), add the `turn.end` `dispatch_before`:

```python
        if self._hooks:
            from mori.hooks.events import HookEvents, TurnEndReason
            from mori.hooks.payloads import TurnEndPayload

            reason = self._map_status_to_turn_end_reason(state.status)
            await self._hooks.dispatch_before(
                HookEvents.TURN_END,
                TurnEndPayload(state=state, reason=reason),
            )
        # existing run.end dispatch_after stays here, unchanged
```

Add the mapping helper at the bottom of `AgentLoop`:

```python
    @staticmethod
    def _map_status_to_turn_end_reason(status: RunStatus) -> TurnEndReason:
        from mori.hooks.events import TurnEndReason

        if status == RunStatus.COMPLETED:
            return TurnEndReason.COMPLETED
        if status == RunStatus.PAUSED:
            return TurnEndReason.PAUSED_ESCALATE  # ask_user case overridden in Task 13
        if status == RunStatus.FAILED:
            return TurnEndReason.ERRORED
        if status == RunStatus.BLOCKED:
            return TurnEndReason.BLOCKED
        return TurnEndReason.EXHAUSTED
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_turn_events.py tests/test_loop_hooks_v05.py -v`
Expected: New tests PASS, existing tests PASS.

- [ ] **Step 7: Commit**

```bash
git add mori/runtime/loop.py tests/test_turn_events.py tests/conftest.py
git commit -m "feat(runtime): fire turn.start and turn.end hook events

turn.start fires at the top of run() and resume() with a TurnStartPayload.
turn.end fires before the existing run.end dispatch with a TurnEndPayload
including a TurnEndReason mapped from the terminal RunStatus.
Block/retry semantics on these events arrive in later tasks."
```

---

### Task 6: HookBlock on turn.start → BLOCKED RunResult

**Files:**
- Modify: `mori/runtime/loop.py` (`run` and `resume`: catch `HookBlock`)
- Test: `tests/test_active_hooks_integration.py` (new, partial; expand in later tasks)

- [ ] **Step 1: Write the failing test**

Create `tests/test_active_hooks_integration.py`:

```python
"""End-to-end integration tests for Active Hooks v0.7."""

from __future__ import annotations

from typing import Any

import pytest

from mori.hooks.events import HookEvents
from mori.hooks.exceptions import HookBlock
from mori.hooks.registry import HookRegistry
from mori.types import RunStatus
from tests.conftest import build_minimal_agent


@pytest.mark.asyncio
async def test_turn_start_block_yields_blocked_result() -> None:
    reg = HookRegistry()

    async def blocker(payload: Any) -> None:
        raise HookBlock("forbidden task", hook_id="my_hook")

    reg.register(HookEvents.TURN_START, blocker)
    agent = build_minimal_agent(hook_registry=reg)
    result = await agent.run("anything")
    assert result.status == RunStatus.BLOCKED
    assert result.block_reason == "forbidden task"
    assert result.block_hook_id is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_active_hooks_integration.py::test_turn_start_block_yields_blocked_result -v`
Expected: FAIL — `HookBlock` propagates out of `run()` instead of being translated to a `BLOCKED` result.

- [ ] **Step 3: Wrap the turn.start dispatch in run() with try/except**

In `mori/runtime/loop.py` `run`:

```python
        if self._hooks:
            from mori.hooks.events import HookEvents
            from mori.hooks.exceptions import HookBlock
            from mori.hooks.payloads import TurnStartPayload

            try:
                await self._hooks.dispatch_before(
                    HookEvents.TURN_START,
                    TurnStartPayload(input=task, thread_id=thread_id, is_resume=False),
                )
            except HookBlock as block:
                state.status = RunStatus.BLOCKED
                # Fire turn.end with reason=BLOCKED, then return
                await self._fire_turn_end(state)
                result = RunResult.from_state(state, duration_ms=0.0)
                result.block_reason = block.reason
                result.block_hook_id = block.hook_id
                return result
```

Add the helper `_fire_turn_end`:

```python
    async def _fire_turn_end(self, state: MoriState) -> None:
        if not self._hooks:
            return
        from mori.hooks.events import HookEvents
        from mori.hooks.payloads import TurnEndPayload

        reason = self._map_status_to_turn_end_reason(state.status)
        try:
            await self._hooks.dispatch_before(
                HookEvents.TURN_END,
                TurnEndPayload(state=state, reason=reason),
            )
        except Exception:
            # turn.end exceptions are handled separately (HookRetry in later task)
            raise
```

Apply the same wrapping to `resume`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_active_hooks_integration.py::test_turn_start_block_yields_blocked_result -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mori/runtime/loop.py tests/test_active_hooks_integration.py
git commit -m "feat(runtime): handle HookBlock on turn.start → BLOCKED RunResult

When a turn.start hook raises HookBlock, the loop never starts; the
run returns a RunResult with status=BLOCKED, block_reason, and
block_hook_id set. turn.end still fires with reason=BLOCKED so
observers see the boundary. run.end does NOT fire (the run never
ran any phases)."
```

---

### Task 7: HookBlock on tool.invoke.before → synthetic tool message

**Files:**
- Modify: `mori/runtime/loop.py` `_phase_act` (~line 332)
- Test: extend `tests/test_active_hooks_integration.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_active_hooks_integration.py`:

```python
@pytest.mark.asyncio
async def test_tool_invoke_block_appends_synthetic_message() -> None:
    """When a tool.invoke.before hook blocks, the tool call gets a synthetic
    blocked result message and the loop continues."""
    reg = HookRegistry()

    async def block_prod(call: Any) -> None:
        if call.arguments.get("env") == "prod":
            raise HookBlock("no prod tools", hook_id="prod_gate")
        return None

    reg.register(HookEvents.TOOL_INVOKE_BEFORE, block_prod)

    # build_minimal_agent_with_tool_call returns an agent whose first
    # model response includes a tool call to a stub tool with args
    # {"env": "prod"}, and subsequent responses are no-tool-call.
    agent = build_minimal_agent_with_tool_call(
        tool_args={"env": "prod"}, hook_registry=reg
    )
    result = await agent.run("do the thing")
    # The tool was NOT actually invoked; a synthetic blocked message is in messages
    blocked_msgs = [
        m for m in result.messages
        if m.role == "tool" and isinstance(m.content, str) and "BLOCKED" in m.content
    ]
    assert len(blocked_msgs) == 1
    assert "no prod tools" in blocked_msgs[0].content
    # Status is NOT BLOCKED — the run continued
    assert result.status != RunStatus.BLOCKED
```

`build_minimal_agent_with_tool_call` is a new test helper in `tests/conftest.py` that returns an agent whose first model response includes one tool call and whose second response is the assistant declaring "done".

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_active_hooks_integration.py::test_tool_invoke_block_appends_synthetic_message -v`
Expected: FAIL — `HookBlock` propagates out of `_phase_act` and crashes the run.

- [ ] **Step 3: Catch HookBlock in `_phase_act` around `tool.invoke.before` dispatch**

In `mori/runtime/loop.py` `_phase_act` (~line 332), wrap the dispatch:

```python
            # Before hook fires first so ToolInvokeEvent records actual arguments
            if self._hooks:
                from mori.hooks.exceptions import HookBlock

                try:
                    call = await self._hooks.dispatch_before("tool.invoke.before", call)
                except HookBlock as block:
                    blocked_msg = Message(
                        role="tool",
                        content=f"BLOCKED by {block.hook_id}: {block.reason}",
                        tool_call_id=call.id,
                    )
                    state.messages.append(blocked_msg)
                    state.total_tool_calls += 1
                    continue  # skip this tool, process next call in the loop
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_active_hooks_integration.py::test_tool_invoke_block_appends_synthetic_message -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mori/runtime/loop.py tests/test_active_hooks_integration.py tests/conftest.py
git commit -m "feat(runtime): handle HookBlock on tool.invoke.before

When a tool.invoke.before hook raises HookBlock, the tool is NOT
invoked and a synthetic tool result message ('BLOCKED by <hook>:
<reason>') is appended to the conversation. The loop continues so
the model sees the block and can replan. Distinct from turn.start
block (which terminates the whole run)."
```

---

### Task 8: HookBlock and HookRetry on model.request.before

**Files:**
- Modify: `mori/runtime/loop.py` `_phase_plan` (~line 256)
- Test: extend `tests/test_active_hooks_integration.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_active_hooks_integration.py`:

```python
@pytest.mark.asyncio
async def test_model_request_block_returns_blocked_result() -> None:
    reg = HookRegistry()

    async def blocker(req: Any) -> None:
        raise HookBlock("request gate", hook_id="req_gate")

    reg.register(HookEvents.MODEL_REQUEST_BEFORE, blocker)
    agent = build_minimal_agent(hook_registry=reg)
    result = await agent.run("anything")
    assert result.status == RunStatus.BLOCKED
    assert result.block_reason == "request gate"


@pytest.mark.asyncio
async def test_model_request_retry_appends_feedback_and_retries() -> None:
    """First call raises HookRetry; second call passes through."""
    from mori.hooks.exceptions import HookRetry

    call_count = 0
    reg = HookRegistry()

    async def retry_once(req: Any) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise HookRetry("think harder", hook_id="r")
        return None

    reg.register(HookEvents.MODEL_REQUEST_BEFORE, retry_once)
    agent = build_minimal_agent(hook_registry=reg)
    result = await agent.run("hello")
    # Model was invoked exactly once after the retry; the assertion is that
    # the feedback appeared as a system message in the second request.
    system_msgs = [
        m for m in result.messages
        if m.role == "system" and "think harder" in (m.content or "")
    ]
    assert len(system_msgs) >= 1
    assert result.status != RunStatus.BLOCKED
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_active_hooks_integration.py -k "model_request" -v`
Expected: FAIL — exceptions propagate out of `_phase_plan`.

- [ ] **Step 3: Wrap `model.request.before` dispatch in `_phase_plan`**

Edit `mori/runtime/loop.py` `_phase_plan`:

```python
    async def _phase_plan(self, state: MoriState) -> None:
        from mori.hooks.exceptions import HookBlock, HookRetry

        retry_count = 0
        max_retries = self._hooks._config.max_retry_limit if self._hooks else 3

        while True:
            request = self._assemble_request(state)
            if self._hooks:
                try:
                    request = await self._hooks.dispatch_before("model.request.before", request)
                except HookBlock as block:
                    state.status = RunStatus.BLOCKED
                    state.context["block_reason"] = block.reason
                    state.context["block_hook_id"] = block.hook_id
                    return
                except HookRetry as retry:
                    retry_count += 1
                    if retry_count > max_retries:
                        state.status = RunStatus.FAILED
                        state.context["error"] = "hook_retry_exhausted"
                        return
                    state.messages.append(Message(role="system", content=retry.feedback))
                    continue
            response = await self._model.invoke(request)
            if self._hooks:
                await self._hooks.dispatch_after("model.response.after", response)
            state.messages.append(response.message)
            state.total_input_tokens += response.usage.input_tokens
            state.total_output_tokens += response.usage.output_tokens
            return
```

`Message` is already imported in `loop.py`.

- [ ] **Step 4: Propagate block_reason/block_hook_id from state.context to RunResult**

In `_run_from_state`, just before constructing the `RunResult`, copy them from `state.context` if present. Add to `RunResult.from_state` an optional `block_context` argument, or post-process in `_run_from_state`:

```python
        run_result = RunResult.from_state(state, duration_ms=elapsed_ms, checkpoint_id=checkpoint_id)
        if "block_reason" in state.context:
            run_result = run_result.model_copy(update={
                "block_reason": state.context["block_reason"],
                "block_hook_id": state.context.get("block_hook_id"),
            })
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_active_hooks_integration.py -k "model_request" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add mori/runtime/loop.py tests/test_active_hooks_integration.py
git commit -m "feat(runtime): handle HookBlock and HookRetry on model.request.before

HookBlock on model.request.before sets RunStatus.BLOCKED and exits
the phase early. HookRetry appends the feedback as a system message
and re-assembles the request, bounded by HookConfig.max_retry_limit
(default 3); exhaustion sets RunStatus.FAILED with error=
'hook_retry_exhausted'."
```

---

### Task 9: HookRetry on turn.end → loop one more iteration

**Files:**
- Modify: `mori/runtime/loop.py` `_run_from_state` (where turn.end dispatches)
- Test: extend `tests/test_active_hooks_integration.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_turn_end_retry_continues_loop() -> None:
    """First completion raises HookRetry; the loop continues for another iteration."""
    from mori.hooks.exceptions import HookRetry

    call_count = 0
    reg = HookRegistry()

    async def retry_once(payload: Any) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise HookRetry("not done yet", hook_id="finisher")
        return None

    reg.register(HookEvents.TURN_END, retry_once)
    agent = build_minimal_agent(hook_registry=reg, max_steps=5)
    result = await agent.run("hi")
    # The hook fired twice: once retried, once allowed.
    assert call_count == 2
    # The "not done yet" feedback should appear in the second iteration's context.
    feedback_msgs = [
        m for m in result.messages
        if m.role == "system" and "not done yet" in (m.content or "")
    ]
    assert len(feedback_msgs) >= 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_active_hooks_integration.py::test_turn_end_retry_continues_loop -v`
Expected: FAIL — `HookRetry` propagates out of `_run_from_state`.

- [ ] **Step 3: Wrap turn.end dispatch with retry handling**

Restructure `_run_from_state` to loop on turn.end retries. The simplest correct approach is to convert the loop body into a method that can be re-entered:

```python
    async def _run_from_state(self, state: MoriState) -> RunResult:
        # ... existing setup ...

        retry_count = 0
        max_retries = self._hooks._config.max_retry_limit if self._hooks else 3

        while True:
            # existing while-loop that runs phases
            while state.status == RunStatus.RUNNING:
                # ... existing phase iteration ...

            # turn.end dispatch (was added in Task 5)
            if self._hooks:
                from mori.hooks.events import HookEvents, TurnEndReason
                from mori.hooks.exceptions import HookRetry
                from mori.hooks.payloads import TurnEndPayload

                reason = self._map_status_to_turn_end_reason(state.status)
                try:
                    await self._hooks.dispatch_before(
                        HookEvents.TURN_END,
                        TurnEndPayload(state=state, reason=reason),
                    )
                except HookRetry as retry:
                    retry_count += 1
                    if retry_count > max_retries:
                        state.status = RunStatus.FAILED
                        state.context["error"] = "turn_end_retry_exhausted"
                        break
                    state.messages.append(Message(role="system", content=retry.feedback))
                    state.status = RunStatus.RUNNING
                    continue  # re-enter the phase loop
            break

        # existing run.end dispatch_after, RunResult construction
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_active_hooks_integration.py::test_turn_end_retry_continues_loop -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mori/runtime/loop.py tests/test_active_hooks_integration.py
git commit -m "feat(runtime): handle HookRetry on turn.end → continue loop

When a turn.end hook raises HookRetry, the runtime treats the run
as not-done, appends feedback as a system message, sets status back
to RUNNING, and re-enters the phase loop. Bounded by max_retry_limit
(default 3); exhaustion sets RunStatus.FAILED with error=
'turn_end_retry_exhausted'."
```

---

### Task 10: HookRetry on observe-only events is logged and ignored

**Files:**
- Modify: `mori/hooks/registry.py` (only in `dispatch_after`; HookRetry there should warn+swallow)
- Test: `tests/test_hook_retry.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hook_retry.py`:

```python
@pytest.mark.asyncio
async def test_hook_retry_on_after_event_warns_and_swallows(caplog: Any) -> None:
    """HookRetry on an after-event (observe-only) is logged and ignored,
    not propagated."""
    import logging
    reg = HookRegistry()

    async def bad(payload: Any) -> None:
        raise HookRetry("wrong place", hook_id="bad")

    reg.register("e", bad)
    with caplog.at_level(logging.WARNING):
        await reg.dispatch_after("e", {})  # must NOT raise
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_hook_retry.py::test_hook_retry_on_after_event_warns_and_swallows -v`
Expected: FAIL — `HookRetry` propagates out of `dispatch_after`.

- [ ] **Step 3: Update `dispatch_after` to swallow HookRetry/HookBlock with a warning**

In `mori/hooks/registry.py`:

```python
    async def dispatch_after(self, event_name: str, payload: Any) -> None:
        for _priority, hook_id, handler in self._hooks.get(event_name, []):
            try:
                await self._call(handler, payload)
            except (HookBlock, HookRetry) as exc:
                # Block/retry on after-event is a hook author error — log + swallow.
                log.warning(
                    "hook.invalid_signal_on_after",
                    handler=getattr(handler, "__name__", "?"),
                    hook_id=hook_id,
                    event=event_name,
                    signal=type(exc).__name__,
                )
```

Note: `_call` will not raise HookBlock/HookRetry now because we excluded them from being re-raised in this code path. To make this work, the existing `_call` should still re-raise them (Task 3 design); but here in `dispatch_after` we explicitly catch them. The `_call` change in Task 3 already does the right thing (re-raises); `dispatch_after` now wraps each call to catch.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_hook_retry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mori/hooks/registry.py tests/test_hook_retry.py
git commit -m "feat(hooks): swallow HookBlock/HookRetry raised on after-events

dispatch_after observers shouldn't be raising policy signals. If
they do, log a warning ('hook.invalid_signal_on_after') and continue
processing other handlers. Distinguishes 'I raised in the wrong place'
from 'I'm telling the runtime to stop' — only the latter is honored,
and only in dispatch_before."
```

---

### Task 11: Native ask_user tool

**Files:**
- Create: `mori/tools/native/__init__.py`
- Create: `mori/tools/native/ask_user.py`
- Test: extend `tests/test_ask_user.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ask_user.py`:

```python
"""ask_user tool yields via YieldToUser exception."""

from __future__ import annotations

import pytest

from mori.hooks.exceptions import YieldToUser
from mori.tools.native.ask_user import ask_user


@pytest.mark.asyncio
async def test_ask_user_raises_yield_to_user() -> None:
    with pytest.raises(YieldToUser) as exc:
        await ask_user("which db?")
    assert exc.value.question == "which db?"


@pytest.mark.asyncio
async def test_ask_user_question_is_required() -> None:
    with pytest.raises(TypeError):
        await ask_user()  # type: ignore[call-arg]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ask_user.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the native tools package and ask_user**

```python
# mori/tools/native/__init__.py
"""Native tools shipped with Mori."""

from mori.tools.native.ask_user import ask_user

__all__ = ["ask_user"]
```

```python
# mori/tools/native/ask_user.py
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ask_user.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mori/tools/native/__init__.py mori/tools/native/ask_user.py \
        tests/test_ask_user.py
git commit -m "feat(tools): add native ask_user tool that yields via YieldToUser

ask_user(question) raises YieldToUser(question). The agent loop's
_phase_act will catch this signal and transition to PAUSED in a
later task. The tool itself is intentionally trivial — all logic
lives in the loop's exception handling."
```

---

### Task 12: ToolRegistry re-raises control exceptions

**Files:**
- Modify: `mori/tools/registry.py:226-237`
- Test: extend `tests/test_registry.py` (or `tests/test_ask_user.py`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ask_user.py`:

```python
@pytest.mark.asyncio
async def test_tool_registry_re_raises_yield_to_user() -> None:
    """When ask_user raises YieldToUser, ToolRegistry.invoke must
    re-raise rather than wrapping in a failed ToolResult."""
    from mori.tools.registry import ToolRegistry

    registry = ToolRegistry()
    registry.register("ask_user", ask_user, description="ask the user")
    with pytest.raises(YieldToUser) as exc:
        await registry.invoke("ask_user", {"question": "which db?"})
    assert exc.value.question == "which db?"


@pytest.mark.asyncio
async def test_tool_registry_re_raises_hook_block() -> None:
    """If a tool raises HookBlock, the registry must re-raise."""
    from mori.hooks.exceptions import HookBlock
    from mori.tools.registry import ToolRegistry

    async def blocker() -> None:
        raise HookBlock("stop")

    registry = ToolRegistry()
    registry.register("blocker", blocker, description="x")
    with pytest.raises(HookBlock):
        await registry.invoke("blocker", {})


@pytest.mark.asyncio
async def test_tool_registry_re_raises_hook_retry() -> None:
    from mori.hooks.exceptions import HookRetry
    from mori.tools.registry import ToolRegistry

    async def retrier() -> None:
        raise HookRetry("again")

    registry = ToolRegistry()
    registry.register("retrier", retrier, description="x")
    with pytest.raises(HookRetry):
        await registry.invoke("retrier", {})
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_ask_user.py -v -k "re_raises"`
Expected: FAIL — the existing `except Exception` in `invoke` swallows these and returns failed ToolResults.

- [ ] **Step 3: Modify ToolRegistry.invoke to re-raise control exceptions**

In `mori/tools/registry.py:226`, change the exception clauses:

```python
        except ToolInvocationError:
            raise
        except Exception as exc:
            # Control-flow exceptions from hooks and the ask_user tool must
            # propagate. They are policy signals, not tool failures.
            from mori.hooks.exceptions import HookBlock, HookRetry, YieldToUser

            if isinstance(exc, (HookBlock, HookRetry, YieldToUser)):
                raise
            elapsed_ms = (time.monotonic() - start) * 1000
            result = ToolResult(
                tool_name=name,
                call_id="",
                success=False,
                content="",
                error=str(exc),
                latency_ms=elapsed_ms,
            )
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_ask_user.py tests/test_registry.py -v`
Expected: All PASS; no regressions in `test_registry.py`.

- [ ] **Step 5: Commit**

```bash
git add mori/tools/registry.py tests/test_ask_user.py
git commit -m "feat(tools): ToolRegistry.invoke re-raises HookBlock/HookRetry/YieldToUser

These are control-flow signals, not tool failures. Without this change,
ask_user would silently return ToolResult(success=False, error='...')
instead of pausing the agent, and tool-raised HookBlock/HookRetry would
be lost."
```

---

### Task 13: _phase_act catches YieldToUser, pauses state, saves checkpoint

**Files:**
- Modify: `mori/runtime/loop.py` `_phase_act` (~line 345)
- Modify: `mori/runtime/loop.py` `_map_status_to_turn_end_reason` (override PAUSED+await_user_input to PAUSED_AWAIT_USER)
- Test: extend `tests/test_ask_user.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_loop_pauses_on_ask_user_yield() -> None:
    """When the model calls ask_user, the loop pauses with
    paused_reason='await_user_input' and paused_prompt set."""
    agent = build_minimal_agent_with_tool_call(
        tool_name="ask_user",
        tool_args={"question": "which db?"},
        register_ask_user=True,
    )
    result = await agent.run("migrate the user table")
    assert result.status == RunStatus.PAUSED
    assert result.paused_prompt == "which db?"
    assert result.checkpoint_id is not None
```

`build_minimal_agent_with_tool_call(register_ask_user=True)` registers `ask_user` in the tool registry.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ask_user.py::test_loop_pauses_on_ask_user_yield -v`
Expected: FAIL — `YieldToUser` propagates out of `_phase_act` and crashes the run.

- [ ] **Step 3: Catch YieldToUser around the tool invocation**

In `mori/runtime/loop.py` `_phase_act`, around the existing `result = await self._tools.invoke(...)` line:

```python
            try:
                result = await self._tools.invoke(call.name, call.arguments)
            except YieldToUser as y:
                state.status = RunStatus.PAUSED
                state.paused_reason = "await_user_input"
                state.paused_prompt = y.question
                state.paused_tool_call = call
                if self._checkpointer:
                    await self._checkpointer.save(state)
                return  # exits _phase_act; _run_from_state sees PAUSED and exits
```

Add the import at the top of the file (or inline):

```python
from mori.hooks.exceptions import YieldToUser
```

Update `_map_status_to_turn_end_reason` to inspect `paused_reason`:

```python
    @staticmethod
    def _map_status_to_turn_end_reason(state_or_status: Any) -> TurnEndReason:
        from mori.hooks.events import TurnEndReason

        # Accept either a MoriState or a bare RunStatus
        if isinstance(state_or_status, RunStatus):
            status = state_or_status
            paused_reason = None
        else:
            status = state_or_status.status
            paused_reason = state_or_status.paused_reason
        if status == RunStatus.COMPLETED:
            return TurnEndReason.COMPLETED
        if status == RunStatus.PAUSED:
            if paused_reason == "await_user_input":
                return TurnEndReason.PAUSED_AWAIT_USER
            return TurnEndReason.PAUSED_ESCALATE
        if status == RunStatus.FAILED:
            return TurnEndReason.ERRORED
        if status == RunStatus.BLOCKED:
            return TurnEndReason.BLOCKED
        return TurnEndReason.EXHAUSTED
```

Update all callers (`_fire_turn_end` and the turn.end dispatch in `_run_from_state`) to pass `state` instead of `state.status`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ask_user.py tests/test_active_hooks_integration.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add mori/runtime/loop.py tests/test_ask_user.py tests/conftest.py
git commit -m "feat(runtime): _phase_act pauses on YieldToUser; turn.end reason

When a tool raises YieldToUser (today only ask_user does), _phase_act
transitions state to RunStatus.PAUSED with paused_reason='await_user_input'
and paused_prompt set, then saves a checkpoint. The turn.end mapping
distinguishes PAUSED_AWAIT_USER from PAUSED_ESCALATE based on
state.paused_reason."
```

---

### Task 14: agent.resume injects user input as paused tool result

**Files:**
- Modify: `mori/runtime/loop.py` `resume(thread_id, input)` (~line 438)
- Test: extend `tests/test_ask_user.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_resume_after_ask_user_injects_input_as_tool_result() -> None:
    """After ask_user pause, resume(thread_id, user_text) appends a tool
    result message with the user's response and continues the run."""
    agent = build_minimal_agent_with_tool_call(
        tool_name="ask_user",
        tool_args={"question": "which db?"},
        register_ask_user=True,
        # After ask_user, the model says "done" (no tool calls).
    )
    result = await agent.run("migrate the user table")
    assert result.status == RunStatus.PAUSED

    resumed = await agent.resume(result.thread_id, "production_db")
    # The resumed run should have the user's text as a tool message
    user_tool_msgs = [
        m for m in resumed.messages
        if m.role == "tool" and m.content == "production_db"
    ]
    assert len(user_tool_msgs) == 1
    assert resumed.status in {RunStatus.COMPLETED, RunStatus.RUNNING}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ask_user.py::test_resume_after_ask_user_injects_input_as_tool_result -v`
Expected: FAIL — `resume` currently doesn't inject the user input.

- [ ] **Step 3: Modify resume to inject the input**

In `mori/runtime/loop.py`:

```python
    async def resume(self, thread_id: ThreadId, input: dict[str, Any] | str) -> RunResult:
        cp = await self._checkpointer.load_latest(thread_id)
        state = cp.state
        user_text: str = input if isinstance(input, str) else input.get("response", "")

        if state.paused_reason == "await_user_input" and state.paused_tool_call:
            state.messages.append(Message(
                role="tool",
                content=user_text,
                tool_call_id=state.paused_tool_call.id,
            ))
            state.status = RunStatus.RUNNING
            state.paused_reason = None
            state.paused_prompt = None
            state.paused_tool_call = None

        if self._hooks:
            from mori.hooks.events import HookEvents
            from mori.hooks.exceptions import HookBlock
            from mori.hooks.payloads import TurnStartPayload

            try:
                await self._hooks.dispatch_before(
                    HookEvents.TURN_START,
                    TurnStartPayload(input=user_text, thread_id=thread_id, is_resume=True),
                )
            except HookBlock as block:
                state.status = RunStatus.BLOCKED
                await self._fire_turn_end(state)
                result = RunResult.from_state(state, duration_ms=0.0)
                result.block_reason = block.reason
                result.block_hook_id = block.hook_id
                return result

        return await self._run_from_state(state)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_ask_user.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add mori/runtime/loop.py tests/test_ask_user.py
git commit -m "feat(runtime): resume injects user input as paused tool result

agent.resume(thread_id, user_text) checks for a paused ask_user call.
If present, the user's text is appended as a tool result message with
the paused call's id, paused_* state is cleared, and the loop resumes.
turn.start fires with is_resume=True; HookBlock on resume yields a
BLOCKED RunResult just like on initial run()."
```

---

### Task 15: Auto-register ask_user; builder.disable_native_tool

**Files:**
- Modify: `mori/agent.py` (builder + agent construction)
- Test: extend `tests/test_builder.py` (or `test_builder_v07.py`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_builder_v07.py`:

```python
"""ask_user is auto-registered; disable_native_tool removes it."""

from __future__ import annotations

import pytest

from mori import Mori


def test_ask_user_auto_registered() -> None:
    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .build()
    )
    specs = agent.tools.list_specs()
    assert any(s.name == "ask_user" for s in specs)


def test_disable_native_tool_removes_ask_user() -> None:
    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .disable_native_tool("ask_user")
        .build()
    )
    specs = agent.tools.list_specs()
    assert not any(s.name == "ask_user" for s in specs)


def test_disable_unknown_native_tool_raises() -> None:
    with pytest.raises(ValueError, match="not a native tool"):
        Mori.builder().disable_native_tool("not_a_tool")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_builder_v07.py -v`
Expected: FAIL — neither auto-registration nor `disable_native_tool` exists.

- [ ] **Step 3: Add the builder method and auto-registration**

In `mori/agent.py`, the builder class:

- Add a class attribute or instance attribute `_disabled_native_tools: set[str] = set()` and initialize in `__init__`
- Add the method:

```python
    _NATIVE_TOOLS = {"ask_user"}

    def disable_native_tool(self, name: str) -> Self:
        if name not in self._NATIVE_TOOLS:
            raise ValueError(f"'{name}' is not a native tool")
        self._disabled_native_tools.add(name)
        return self
```

- In the `build` method, after the ToolRegistry is created and before the AgentLoop is constructed, register native tools that aren't disabled:

```python
        # Native tools (Mori-shipped)
        from mori.tools.native import ask_user as ask_user_fn

        if "ask_user" not in self._disabled_native_tools:
            registry.register(
                "ask_user",
                ask_user_fn,
                description="Ask the calling user a question and wait for their "
                            "response. Use only when you cannot proceed without "
                            "human input.",
                input_schema={
                    "type": "object",
                    "properties": {"question": {"type": "string"}},
                    "required": ["question"],
                },
            )
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_builder_v07.py tests/test_builder.py -v`
Expected: All PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add mori/agent.py tests/test_builder_v07.py
git commit -m "feat(builder): auto-register ask_user; .disable_native_tool('ask_user')

ask_user is registered in every Mori-built agent by default so callers
get chat-mode behavior without manual wiring. Mori.builder()
.disable_native_tool('ask_user') removes it for agents that should
never pause for input."
```

---

### Task 16: Hook invariant property tests

**Files:**
- Create: `tests/test_hook_invariants.py`

- [ ] **Step 1: Write the property tests**

```python
"""Hook system invariants — properties that must hold across all events."""

from __future__ import annotations

from typing import Any

import pytest

from mori.hooks.events import HookEvents
from mori.hooks.exceptions import HookBlock
from mori.hooks.registry import HookRegistry


_BEFORE_EVENTS = [
    HookEvents.TURN_START,
    HookEvents.MODEL_REQUEST_BEFORE,
    HookEvents.TOOL_INVOKE_BEFORE,
    HookEvents.TURN_END,
]


@pytest.mark.asyncio
@pytest.mark.parametrize("event", _BEFORE_EVENTS)
async def test_noop_hook_observationally_identical(event: str) -> None:
    """A no-op hook (returns None) is observationally identical to no hook
    being registered."""
    payload = {"key": "value"}

    reg_with = HookRegistry()
    reg_with.register(event, lambda p: None)
    result_with = await reg_with.dispatch_before(event, payload)

    reg_without = HookRegistry()
    result_without = await reg_without.dispatch_before(event, payload)

    assert result_with == result_without == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("event", _BEFORE_EVENTS)
async def test_hook_block_short_circuits_chain(event: str) -> None:
    """HookBlock always short-circuits — later hooks never observe the payload,
    on every block-capable event."""
    later_saw = []
    reg = HookRegistry()

    async def blocker(p: Any) -> None:
        raise HookBlock("stop", hook_id="b")

    async def later(p: Any) -> None:
        later_saw.append(p)

    reg.register(event, blocker, priority=50)
    reg.register(event, later, priority=100)
    with pytest.raises(HookBlock):
        await reg.dispatch_before(event, {"x": 1})
    assert later_saw == []
```

- [ ] **Step 2: Run to verify they pass**

Run: `uv run pytest tests/test_hook_invariants.py -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_hook_invariants.py
git commit -m "test(hooks): property tests for noop identity and block short-circuit

Two invariants checked across every block-capable event:
1. A no-op hook (returns None) is observationally identical to no hook
2. HookBlock always short-circuits — later hooks never observe payload"
```

---

### Task 17: Examples, integration tests, and docs

**Files:**
- Create: `examples/hooks_block.py`
- Create: `examples/hooks_retry.py`
- Create: `examples/chat_loop.py`
- Create: `mori-docs/architecture/hooks.md`
- Create: `mori-docs/architecture/chat-mode.md`
- Modify: `README.md`
- Modify: `tests/test_active_hooks_integration.py` (add end-to-end chat-loop test)

- [ ] **Step 1: Write the end-to-end chat-loop integration test**

Append to `tests/test_active_hooks_integration.py`:

```python
@pytest.mark.asyncio
async def test_e2e_chat_loop() -> None:
    """Full chat-loop integration: agent calls ask_user, yields, caller
    resumes with a response, agent completes."""
    agent = build_minimal_agent_with_tool_call(
        tool_name="ask_user",
        tool_args={"question": "which db?"},
        register_ask_user=True,
    )
    result = await agent.run("migrate the user table")
    assert result.status == RunStatus.PAUSED
    assert result.paused_prompt == "which db?"

    final = await agent.resume(result.thread_id, "production_db")
    assert final.status == RunStatus.COMPLETED
    # The conversation contains the user's response as a tool message
    assert any(
        m.role == "tool" and m.content == "production_db"
        for m in final.messages
    )
```

- [ ] **Step 2: Run to verify it passes**

Run: `uv run pytest tests/test_active_hooks_integration.py::test_e2e_chat_loop -v`
Expected: PASS.

- [ ] **Step 3: Write `examples/hooks_block.py`**

```python
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
```

- [ ] **Step 4: Write `examples/hooks_retry.py`**

```python
"""Demo: force a retry with HookRetry when the response speculates without grounding."""
from __future__ import annotations

import asyncio

from mori import Mori
from mori.hooks import HookEvents, HookRetry

SPECULATION_MARKERS = ("probably is", "should be", "I believe", "presumably")


def main() -> int:
    async def _main() -> None:
        agent = (
            Mori.builder()
            .model("anthropic", model="claude-sonnet-4-20250514")
            .build()
        )

        @agent.hooks.hook(HookEvents.MODEL_REQUEST_BEFORE, priority=50)
        async def require_grounding(request):
            # Inspect the last assistant message in the conversation, if any.
            for msg in reversed(request.messages):
                if msg.role == "assistant" and isinstance(msg.content, str):
                    last = msg.content.lower()
                    if any(m in last for m in SPECULATION_MARKERS) and not msg.tool_calls:
                        raise HookRetry(
                            "Previous response contains speculation without a "
                            "tool call. Re-think and ground the answer in evidence."
                        )
                    break
            return None

        result = await agent.run("What's the current load average on prod-web-01?")
        print(result.final_output)

    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Write `examples/chat_loop.py`**

```python
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
```

- [ ] **Step 6: Write `mori-docs/architecture/hooks.md`**

```markdown
# Hooks

Mori hooks are priority-ordered callbacks that fire at well-defined lifecycle
events. Each hook is one of three modes:

| Mode | Mechanism | Example |
|---|---|---|
| **Observe** | Register on a `*.after` event; return is ignored | logging, metrics, audit trail |
| **Transform** | Register on a `*.before` event; return a new payload to mutate it | adding system messages, rewriting tool args |
| **Gate** | Register on a `*.before` event; `raise HookBlock(reason)` to veto, or `raise HookRetry(feedback)` to force a retry | enforcement, output validation |

The three modes are not separate APIs — they're three ways of using the same
`@registry.hook(event, priority)` decorator.

## Event Catalog

| Event | When | Payload | Block? | Retry? |
|---|---|---|---|---|
| `turn.start` | entry to `run()` / `resume()` | `TurnStartPayload` | yes | no |
| `model.request.before` | before model invoke | `ModelRequest` | yes | yes |
| `model.response.after` | after model invoke | `ModelResponse` | — | — |
| `permission.check.after` | after permission check | `PermissionResult` | — | — |
| `tool.invoke.before` | before tool runs | `ToolCall` | yes | no |
| `tool.invoke.after` | after tool runs | `ToolResult` | — | — |
| `run.start` (legacy) | once per `run()` | `{task, run_id}` | — | — |
| `run.end` (legacy) | once per `run()` | `{status, run_id}` | — | — |
| `turn.end` | every exit of `run()` / `resume()` | `TurnEndPayload` | no | yes |

## Why hooks aren't permissions

`PermissionEngine` answers declarative questions ("can identity X do permission Y
on resource Z"). Hooks answer imperative questions ("does this specific request,
right now, in this specific shape, look wrong"). Use permissions for stable
identity/resource policy. Use hooks for content-aware, code-driven checks.

## Bounded retries

`HookRetry` is bounded by `HookConfig.max_retry_limit` (default 3). Exhaustion
sets `RunStatus.FAILED` with `error="hook_retry_exhausted"` (model.request.before)
or `"turn_end_retry_exhausted"` (turn.end).
```

- [ ] **Step 7: Write `mori-docs/architecture/chat-mode.md`**

```markdown
# Chat Mode

Mori is autonomous by default — `agent.run(task)` runs to completion. In v0.7,
Mori is also chat-capable: the agent can pause mid-run to ask the user a
question and resume after the user responds.

## The `ask_user` tool

`ask_user(question: str) -> str` is a native tool registered automatically on
every Mori agent (unless `.disable_native_tool("ask_user")` is called).

When the agent invokes it, the loop:

1. Transitions to `RunStatus.PAUSED` with `paused_reason="await_user_input"`
2. Sets `state.paused_prompt = question`
3. Saves a checkpoint
4. Fires `turn.end` with `reason=PAUSED_AWAIT_USER`
5. Returns control to the caller

## Caller pattern

```python
result = await agent.run("Migrate the user table")
while result.status == RunStatus.PAUSED and result.paused_prompt:
    answer = input(f"{result.paused_prompt}\n> ")
    result = await agent.resume(result.thread_id, answer)
```

The user's response is injected as the paused tool call's result so the agent
sees it as `ask_user`'s return value.

## When NOT to use ask_user

The agent should call `ask_user` only when it cannot proceed without input.
Repeated asks for things the agent could figure out itself are a sign of
prompt or skill design issues, not a runtime issue.
```

- [ ] **Step 8: Update README Quick Start with a chat example**

Append to the README Quick Start section a short snippet showing `ask_user` and the resume loop pattern.

- [ ] **Step 9: Run the full test suite**

Run: `uv run pytest -x -q`
Expected: All tests PASS, no regressions.

- [ ] **Step 10: Commit**

```bash
git add examples/hooks_block.py examples/hooks_retry.py examples/chat_loop.py \
        mori-docs/architecture/hooks.md mori-docs/architecture/chat-mode.md \
        README.md tests/test_active_hooks_integration.py
git commit -m "docs(v07): examples and architecture docs for Active Hooks

Three examples (block, retry, chat loop) demonstrating each capability.
Two new architecture docs covering the hook model and chat mode. README
Quick Start gains a chat-loop snippet."
```

---

## Self-Review

**Spec coverage:**
- §4.1 HookBlock / HookRetry → Task 1
- §4.2 HookEvents constants → Task 2
- §4.3 ask_user tool → Tasks 11, 13, 14, 15
- §4.4 Registration unchanged → No task needed (additive)
- §5 Event table & payloads → Tasks 2, 5
- §5.1 Payload types → Task 2
- §5.2 run.* vs turn.* distinction → Task 5
- §6 Exception semantics → Tasks 3, 6, 7, 8, 9, 10
- §6.3 MAX_RETRY_LIMIT → Tasks 3, 8, 9
- §7 ask_user tool → Tasks 11-15
- §8 State/result fields → Task 4
- §9 Tests → Tasks 1-16
- §10 Migration/docs → Task 17
- §12 No open questions

All spec sections have at least one task. ✓

**Placeholder scan:** No TBD/TODO/"similar to" placeholders. ✓

**Type consistency:** `HookEvents.TURN_START`, `TurnStartPayload`, `TurnEndPayload`, `TurnEndReason`, `RunStatus.BLOCKED`, `paused_prompt`, `block_reason`, `block_hook_id`, `max_retry_limit`, `YieldToUser.question` are used consistently across all tasks. ✓
