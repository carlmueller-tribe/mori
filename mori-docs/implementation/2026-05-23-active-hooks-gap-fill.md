# Active Hooks v1 Gap-Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile spec/code drift for Active Hooks v1 and ship the remaining work (`HookPolicyEvent`, top-level re-exports, live-model integration tests). Existing implementation already passes 64/64 unit tests across 8 hook test files; this plan does NOT re-implement that work.

**Architecture:** Two reconciliation directions. **Spec → code** where code is canonical (`TurnEndReason` naming, `ask_user` opt-out API). **Code → spec** where spec is canonical (`HookPolicyEvent` for observability, top-level exports). End state: spec and code agree; no behavior change for existing users.

**Tech Stack:** Python 3.11+, pytest, pytest-asyncio, anthropic SDK, pydantic, structlog. Live integration tests gated by `ANTHROPIC_API_KEY` in `.env` (already present per user).

---

## File Structure

**Will create:**
- `tests/integration/__init__.py` — package marker
- `tests/integration/test_active_hooks_live.py` — live-model integration tests (3 scenarios)
- `tests/test_hook_policy_event.py` — unit tests for HookPolicyEvent + emission
- `tests/test_top_level_exports.py` — assert public API exports are importable from `mori`

**Will modify:**
- `mori/observability/events.py` — add `HookPolicyEvent` class
- `mori/hooks/registry.py` — emit `HookPolicyEvent` when `HookBlock`/`HookRetry` propagate
- `mori/__init__.py` — re-export `HookBlock`, `HookRetry`, `HookEvents`, `TurnEndReason`, `TurnStartPayload`, `TurnEndPayload`
- `mori-docs/specs/02-RUNTIME.md` — `AWAIT_USER` → `PAUSED_AWAIT_USER` (1 location)
- `mori-docs/specs/05-TOOLS-AND-PROTOCOLS.md` — rewrite Section 5.1 to reflect auto-register / opt-out API; fix `AWAIT_USER` → `PAUSED_AWAIT_USER` (1 location)
- `mori-docs/specs/10-PLUGINS-AND-ADAPTERS.md` — `AWAIT_USER` → `PAUSED_AWAIT_USER` (4 locations); add `max_retry_limit` to A.2 Configuration

**Won't touch:**
- Any existing code in `mori/hooks/`, `mori/runtime/loop.py`, `mori/tools/native/ask_user.py`, `mori/runtime/state.py`, `mori/runtime/result.py` — these implement Active Hooks correctly per the test suite.
- Existing tests — they pass.

---

## Task 1: Spec reconciliation — AWAIT_USER → PAUSED_AWAIT_USER

**Why:** Code defines `TurnEndReason.PAUSED_AWAIT_USER` (parallel with `PAUSED_ESCALATE`). Spec uses `AWAIT_USER`. Code naming is more consistent. Spec aligns to code.

**Files:**
- Modify: `mori-docs/specs/02-RUNTIME.md` (1 occurrence)
- Modify: `mori-docs/specs/05-TOOLS-AND-PROTOCOLS.md` (1 occurrence)
- Modify: `mori-docs/specs/10-PLUGINS-AND-ADAPTERS.md` (4 occurrences)

- [ ] **Step 1: Find all occurrences**

```bash
grep -rn "AWAIT_USER\b" mori-docs/specs/ | grep -v "PAUSED_AWAIT_USER"
```

Expected: 6 lines across 3 files (1 in 02-RUNTIME, 1 in 05-TOOLS, 4 in 10-PLUGINS).

- [ ] **Step 2: In `mori-docs/specs/02-RUNTIME.md`, change `TurnEndReason.AWAIT_USER` to `TurnEndReason.PAUSED_AWAIT_USER`**

Use Edit. The line is in the `_finalize_turn` code block near line 157:

```python
paused_prompt=state.paused_prompt if reason == TurnEndReason.PAUSED_AWAIT_USER else None,
```

- [ ] **Step 3: In `mori-docs/specs/05-TOOLS-AND-PROTOCOLS.md`, change "reason=AWAIT_USER" to "reason=PAUSED_AWAIT_USER" in the lifecycle text**

Line ~229:

```markdown
6. Fires `turn.end` with `reason=PAUSED_AWAIT_USER` (see Spec 10 A.3)
```

- [ ] **Step 4: In `mori-docs/specs/10-PLUGINS-AND-ADAPTERS.md`, fix all 4 occurrences**

The locations:
- Line ~113: `paused_prompt: str | None        # set when reason=PAUSED_AWAIT_USER`
- Line ~117: `PAUSED_AWAIT_USER = "paused_await_user"      # ask_user tool invoked`
- Line ~302: `**`turn.end`** fires with `reason=PAUSED_AWAIT_USER` when the agent invokes `ask_user`.`
- Line ~315: `├─ turn.end (reason=PAUSED_AWAIT_USER, paused_prompt="which db?")`
- Line ~413: `- [ ] `turn.end.reason` correctly identifies COMPLETED / PAUSED_AWAIT_USER / PAUSED_ESCALATE / EXHAUSTED / ERRORED / BLOCKED`

- [ ] **Step 5: Verify zero remaining naked `AWAIT_USER`**

```bash
grep -rn "AWAIT_USER\b" mori-docs/specs/ | grep -v "PAUSED_AWAIT_USER"
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add mori-docs/specs/02-RUNTIME.md mori-docs/specs/05-TOOLS-AND-PROTOCOLS.md mori-docs/specs/10-PLUGINS-AND-ADAPTERS.md
git commit -m "docs(active-hooks): reconcile TurnEndReason naming to PAUSED_AWAIT_USER"
```

---

## Task 2: Spec reconciliation — `ask_user` is auto-register / opt-out

**Why:** Spec describes `.ask_user()` as opt-in builder method. Code auto-registers `ask_user` via `_NATIVE_TOOLS = {"ask_user"}` and supports opt-out via `_disabled_native_tools`. Code is canonical; spec must reflect actual API.

**Files:**
- Modify: `mori-docs/specs/05-TOOLS-AND-PROTOCOLS.md` Section 5.1 (the entire ask_user section)

- [ ] **Step 1: Read the current Section 5.1 to understand the size of the rewrite**

```bash
sed -n '/### 5.1 `ask_user`/,/### 5.2/p' mori-docs/specs/05-TOOLS-AND-PROTOCOLS.md
```

- [ ] **Step 2: Confirm the disable mechanism in code**

```bash
grep -n "disable_native_tool\|disable_ask_user\|_disabled_native_tools" mori/agent.py | head -10
```

Expected: shows `_disabled_native_tools: set[str]` field and a method that adds to it.

- [ ] **Step 3: Rewrite Section 5.1 "Enabling" subsection**

Replace the opt-in narrative with opt-out. The "Enabling" subsection currently says:

> **Enabling.** Disabled by default. Opt-in via the builder:
> ```python
> .ask_user()                  # enable chat mode
> ```

Replace with:

```markdown
**Enabling.** Auto-registered by the builder. To disable (e.g., for autonomous batch agents that should not be able to ask the user), opt out explicitly:

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-6")
    .checkpointer(SqliteCheckpointer(path="./threads.db"))
    .disable_native_tool("ask_user")    # opt out of chat mode
    .build()
)
```

`ask_user` is the only built-in native tool today. The `disable_native_tool(name)` builder method also accepts future native tool names.
```

- [ ] **Step 4: Update the "Requires checkpointer" subsection**

Currently it implies `.ask_user()` triggers the check. Change to: any time `ask_user` is enabled (the default), `.build()` requires `.checkpointer(...)` to have been called first. If not, raise `BuilderError("ask_user requires a checkpointer; call .checkpointer() before .build()")`.

Replace:

> **Requires checkpointer.** Calling `.ask_user()` on a builder without `.checkpointer(...)` raises `BuilderError("ask_user requires a checkpointer; call .checkpointer() first")` at build time. The pause must persist somewhere for `resume()` to work.

With:

```markdown
**Requires checkpointer.** When `ask_user` is enabled (the default), `.build()` requires a checkpointer to have been configured. If `.checkpointer(...)` was not called, build raises `BuilderError("ask_user requires a checkpointer; call .checkpointer() before .build(), or .disable_native_tool('ask_user')")`. The pause must persist somewhere for `resume()` to work.
```

- [ ] **Step 5: Update Section 5 intro to say auto-registered, not opt-in**

The current intro reads:

> Mori ships a small set of built-in native tools that the agent can use to interact with its runtime environment. They are registered automatically by the builder when enabled. Each is opt-in — autonomous agents (the default) should not be able to invoke them by default.

Replace the second sentence:

```markdown
Mori ships a small set of built-in native tools that the agent can use to interact with its runtime environment. They are auto-registered by the builder. Each can be disabled via `.disable_native_tool(name)` — autonomous batch agents that must not interact with humans should disable `ask_user` explicitly.
```

- [ ] **Step 6: Update the IMPLEMENTATION-PLAN.md v0.7 task description for Chat Mode**

The task currently mentions `.ask_user()` builder method. Update to match the actual API:

```bash
grep -n "ask_user.* (Spec 05 Section 5)" mori-docs/implementation/IMPLEMENTATION-PLAN.md
```

Replace `.ask_user() builder method (opt-in; requires checkpointer)` with `auto-registration via _NATIVE_TOOLS; disable_native_tool("ask_user") for opt-out; build-time check that checkpointer is configured`.

- [ ] **Step 7: Commit**

```bash
git add mori-docs/specs/05-TOOLS-AND-PROTOCOLS.md mori-docs/implementation/IMPLEMENTATION-PLAN.md
git commit -m "docs(active-hooks): reconcile ask_user API — auto-register with disable_native_tool() opt-out"
```

---

## Task 3: Spec reconciliation — add `max_retry_limit` to HookConfig docs

**Why:** Code has `HookConfig.max_retry_limit: int = 3`. Spec's A.2 Configuration section omits this field.

**Files:**
- Modify: `mori-docs/specs/10-PLUGINS-AND-ADAPTERS.md` Section A.2

- [ ] **Step 1: Read the current A.2 Configuration block**

```bash
sed -n '/### A.2 Configuration/,/### A.3/p' mori-docs/specs/10-PLUGINS-AND-ADAPTERS.md
```

Expected: HookConfig class has `max_hooks_per_event`, `hook_timeout_sec`, `fail_open`, `log_hook_errors`, `log_hook_execution`. Missing: `max_retry_limit`.

- [ ] **Step 2: Confirm the field in code**

```bash
grep -n "max_retry_limit" mori/hooks/types.py
```

Expected: `max_retry_limit: int = 3`.

- [ ] **Step 3: Add `max_retry_limit` to the HookConfig class block in the spec**

Replace the HookConfig code block:

```python
class HookConfig(MoriModel):
    max_hooks_per_event: int = 50
    hook_timeout_sec: float = 10.0
    fail_open: bool = True          # Hook failures don't block operations
    log_hook_errors: bool = True
    log_hook_execution: bool = False
    max_retry_limit: int = 3        # HookRetry attempts per turn before giving up
```

- [ ] **Step 4: Add a paragraph in A.5 Policy Signals (Edge cases) noting the retry limit**

Currently the spec says:

> **`HookRetry` infinite loops** are bounded by `max_steps` like any other loop iteration. No separate retry counter.

This contradicts code. Replace with:

```markdown
- **`HookRetry` retry limit.** `HookConfig.max_retry_limit` (default 3) caps how many times the same event can re-raise `HookRetry` within a single turn. Exceeding the limit converts the retry into a `HookBlock` with reason `"max retry limit exceeded"`. Also bounded by `max_steps` overall.
```

- [ ] **Step 5: Commit**

```bash
git add mori-docs/specs/10-PLUGINS-AND-ADAPTERS.md
git commit -m "docs(active-hooks): add max_retry_limit to HookConfig spec; correct retry-limit semantics"
```

---

## Task 4: HookPolicyEvent — observability event class

**Why:** Spec describes `HookPolicyEvent` emitted to the observability stream on every `HookBlock`/`HookRetry` propagation. Code does not have this class. Without it, sinks can't observe policy signals as first-class events.

**Files:**
- Create: `tests/test_hook_policy_event.py`
- Modify: `mori/observability/events.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_hook_policy_event.py`:

```python
"""HookPolicyEvent — observability event for HookBlock/HookRetry."""

from __future__ import annotations

from datetime import datetime

import pytest

from mori.observability.events import HookPolicyEvent
from mori.types import RunId


def test_hook_policy_event_block() -> None:
    event = HookPolicyEvent(
        event_id="evt_1",
        timestamp=datetime.now(),
        run_id=RunId("run_1"),
        signal="HookBlock",
        event_name="tool.invoke.before",
        hook_id="hook_abc123",
        handler_name="block_prod_writes",
        reason="production migrations must go through CI",
    )
    assert event.event_type == "hook.policy"
    assert event.signal == "HookBlock"
    assert event.event_name == "tool.invoke.before"
    assert event.reason == "production migrations must go through CI"


def test_hook_policy_event_retry() -> None:
    event = HookPolicyEvent(
        event_id="evt_2",
        timestamp=datetime.now(),
        run_id=RunId("run_2"),
        signal="HookRetry",
        event_name="turn.end",
        hook_id="hook_xyz789",
        handler_name="no_speculate",
        reason="response contains speculation; revise",
    )
    assert event.signal == "HookRetry"


def test_hook_policy_event_signal_is_constrained() -> None:
    """signal field must be 'HookBlock' or 'HookRetry' — pydantic Literal."""
    with pytest.raises(Exception):  # ValidationError
        HookPolicyEvent(
            event_id="evt_3",
            timestamp=datetime.now(),
            run_id=RunId("run_3"),
            signal="NotASignal",  # invalid
            event_name="turn.end",
            hook_id="hook_1",
            handler_name="h",
            reason="r",
        )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_hook_policy_event.py -v
```

Expected: 3 errors, all `ImportError: cannot import name 'HookPolicyEvent' from 'mori.observability.events'`.

- [ ] **Step 3: Add the `HookPolicyEvent` class to `mori/observability/events.py`**

Locate the section with other event classes (after `PermissionCheckEvent` around line 163) and add:

```python
class HookPolicyEvent(MoriEvent):
    """Policy signal raised by a hook (HookBlock or HookRetry).

    Emitted to the observability stream whenever a registered hook raises
    HookBlock or HookRetry inside dispatch_before. Sinks must surface these
    prominently — policy decisions changing run outcomes should not require
    digging through DEBUG logs.
    """

    event_type: str = "hook.policy"
    signal: Literal["HookBlock", "HookRetry"]
    event_name: str            # which hook event the signal was raised at
    hook_id: str               # which hook raised
    handler_name: str
    reason: str                # the message argument to the exception
```

Add `Literal` to the existing `typing` import at the top of the file:

```python
from typing import Any, Literal, Protocol, runtime_checkable
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_hook_policy_event.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add mori/observability/events.py tests/test_hook_policy_event.py
git commit -m "feat(observability): add HookPolicyEvent for HookBlock/HookRetry signals"
```

---

## Task 5: Emit `HookPolicyEvent` from registry on policy signal propagation

**Why:** `HookPolicyEvent` exists now (Task 4). It must actually be emitted when `dispatch_before` propagates a `HookBlock` or `HookRetry`. The natural emission point is the registry, so every catch site automatically observes policy decisions.

**Files:**
- Modify: `mori/hooks/registry.py` — accept an optional observability engine; emit on policy signal propagation
- Modify: `mori/runtime/loop.py` — pass the engine to the registry on construction (or via a setter)
- Modify: `tests/test_hook_policy_event.py` — add an end-to-end emission test

- [ ] **Step 1: Add a failing end-to-end test**

Append to `tests/test_hook_policy_event.py`:

```python
import asyncio
from unittest.mock import AsyncMock

from mori.hooks.exceptions import HookBlock
from mori.hooks.registry import HookRegistry
from mori.observability.engine import ObservabilityEngine


@pytest.mark.asyncio
async def test_dispatch_before_emits_hook_policy_event_on_block() -> None:
    """When dispatch_before catches a HookBlock, HookPolicyEvent must be emitted."""
    obs = AsyncMock(spec=ObservabilityEngine)
    registry = HookRegistry(observability=obs)

    @registry.hook("tool.invoke.before", priority=10, name="blocker")
    async def blocker(payload):
        raise HookBlock("denied for test")

    with pytest.raises(HookBlock):
        await registry.dispatch_before("tool.invoke.before", payload={"tool": "foo"})

    # Find the HookPolicyEvent in emitted events
    emit_calls = [c.args[0] for c in obs.emit.call_args_list]
    policy_events = [e for e in emit_calls if isinstance(e, HookPolicyEvent)]
    assert len(policy_events) == 1
    assert policy_events[0].signal == "HookBlock"
    assert policy_events[0].event_name == "tool.invoke.before"
    assert policy_events[0].handler_name == "blocker"
    assert policy_events[0].reason == "denied for test"
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
uv run pytest tests/test_hook_policy_event.py::test_dispatch_before_emits_hook_policy_event_on_block -v
```

Expected: fails with either `TypeError: HookRegistry() got unexpected keyword argument 'observability'` or `AssertionError: len(policy_events) == 0`.

- [ ] **Step 3: Modify `HookRegistry.__init__` to accept an optional observability engine**

In `mori/hooks/registry.py`, update the constructor:

```python
def __init__(
    self,
    config: HookConfig | None = None,
    observability: Any | None = None,  # ObservabilityEngine, but avoid circular import
) -> None:
    self._config = config or HookConfig()
    self._observability = observability
    # ... rest unchanged
```

- [ ] **Step 4: Emit `HookPolicyEvent` in the `dispatch_before` catch block**

Find the existing `except (HookBlock, HookRetry):` block in `dispatch_before` (around line 77 per the earlier grep). Add emission BEFORE the `raise`:

```python
except (HookBlock, HookRetry) as policy_signal:
    # Stamp metadata if missing
    if not policy_signal.hook_id:
        policy_signal.hook_id = hook_id
    policy_signal.event_name = event_name

    # Emit HookPolicyEvent so sinks observe the decision
    if self._observability is not None:
        from datetime import UTC, datetime
        from mori.observability.events import HookPolicyEvent
        event = HookPolicyEvent(
            event_id=f"evt_{secrets.token_hex(6)}",
            timestamp=datetime.now(UTC),
            run_id=getattr(policy_signal, "run_id", None) or "unknown",
            signal=type(policy_signal).__name__,
            event_name=event_name,
            hook_id=hook_id,
            handler_name=getattr(handler, "__name__", "<unknown>"),
            reason=str(policy_signal),
        )
        await self._observability.emit(event)

    raise
```

(Adjust `secrets`/`datetime` imports as needed — they may already be imported.)

- [ ] **Step 5: Wire observability through the AgentLoop to the registry**

In `mori/runtime/loop.py`, find where `HookRegistry` is constructed or received. If `AgentLoop.__init__` takes `hooks` and `observability`, after both are set:

```python
# After self._hooks and self._obs are both set
if self._hooks is not None and self._obs is not None:
    self._hooks._observability = self._obs
```

Or modify `mori/agent.py` builder to pass observability when constructing the registry:

```bash
grep -n "HookRegistry(" mori/agent.py mori/runtime/loop.py
```

Wire it at whichever location is canonical.

- [ ] **Step 6: Run the new test to confirm it passes**

```bash
uv run pytest tests/test_hook_policy_event.py -v
```

Expected: 4 passed.

- [ ] **Step 7: Run the full hook test suite to confirm no regressions**

```bash
uv run pytest tests/test_active_hooks_integration.py tests/test_hook_block.py tests/test_hook_retry.py tests/test_hook_exceptions.py tests/test_hook_invariants.py tests/test_hook_events_v07.py tests/test_ask_user.py tests/test_hooks.py tests/test_hook_policy_event.py -v 2>&1 | tail -10
```

Expected: 68 passed (existing 64 + new 4).

- [ ] **Step 8: Commit**

```bash
git add mori/hooks/registry.py mori/runtime/loop.py mori/agent.py tests/test_hook_policy_event.py
git commit -m "feat(active-hooks): emit HookPolicyEvent on HookBlock/HookRetry propagation"
```

---

## Task 6: Top-level re-exports

**Why:** Spec says `HookBlock`, `HookRetry`, `HookEvents`, `TurnEndReason`, `TurnStartPayload`, `TurnEndPayload` are re-exported from `mori`. Code: not re-exported.

**Files:**
- Create: `tests/test_top_level_exports.py`
- Modify: `mori/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_top_level_exports.py`:

```python
"""The Active Hooks public API must be importable from the top-level `mori` package."""

from __future__ import annotations


def test_hook_exceptions_top_level_importable() -> None:
    from mori import HookBlock, HookRetry

    assert HookBlock is not None
    assert HookRetry is not None


def test_hook_events_top_level_importable() -> None:
    from mori import HookEvents, TurnEndReason

    assert HookEvents.TURN_START == "turn.start"
    assert TurnEndReason.COMPLETED == "completed"


def test_turn_payloads_top_level_importable() -> None:
    from mori import TurnStartPayload, TurnEndPayload

    assert TurnStartPayload is not None
    assert TurnEndPayload is not None


def test_yield_to_user_NOT_top_level_importable() -> None:
    """YieldToUser is intentionally internal — must NOT be in mori.__all__."""
    import mori

    assert "YieldToUser" not in getattr(mori, "__all__", [])
    # Direct attribute access also should not work
    assert not hasattr(mori, "YieldToUser")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_top_level_exports.py -v
```

Expected: 3 import errors (HookBlock, HookEvents, TurnStartPayload not importable from mori). The 4th test (YieldToUser absence) should already pass.

- [ ] **Step 3: Read the current `mori/__init__.py` to know what's already exported**

```bash
cat mori/__init__.py
```

- [ ] **Step 4: Add the re-exports to `mori/__init__.py`**

Append (or merge into existing imports) these lines, and update `__all__`:

```python
from mori.hooks.exceptions import HookBlock, HookRetry
from mori.hooks.events import HookEvents, TurnEndReason
from mori.hooks.payloads import TurnStartPayload, TurnEndPayload
```

Add the six names to `__all__`. Do NOT add `YieldToUser`.

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run pytest tests/test_top_level_exports.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Run the full test suite to confirm nothing broke**

```bash
uv run pytest --tb=no -q 2>&1 | tail -10
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add mori/__init__.py tests/test_top_level_exports.py
git commit -m "feat(active-hooks): re-export public API from top-level mori package"
```

---

## Task 7: Live integration test infrastructure

**Why:** Existing hook tests use `AsyncMock(spec=ModelAdapter)`. The spec calls for at least one live-model test per capability. We need a pytest gating mechanism that skips live tests when `ANTHROPIC_API_KEY` is missing (so CI without secrets still passes).

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`

- [ ] **Step 1: Create the integration test package**

Create `tests/integration/__init__.py` (empty file).

- [ ] **Step 2: Create `tests/integration/conftest.py` with the skip-if-no-key fixture and a real-model fixture**

```python
"""Pytest fixtures for live-model integration tests.

These tests require ANTHROPIC_API_KEY in the environment (e.g., via .env).
When the key is absent, all tests in this directory are skipped.
"""

from __future__ import annotations

import os

import pytest

from mori.model.anthropic import AnthropicAdapter


def pytest_collection_modifyitems(config, items):
    """Skip every test in tests/integration/ if ANTHROPIC_API_KEY is unset."""
    if os.getenv("ANTHROPIC_API_KEY"):
        return
    skip_marker = pytest.mark.skip(reason="ANTHROPIC_API_KEY not set")
    for item in items:
        if "tests/integration/" in str(item.fspath):
            item.add_marker(skip_marker)


@pytest.fixture
def anthropic_model():
    """A real AnthropicAdapter using claude-haiku for cost-efficient live tests."""
    return AnthropicAdapter(model="claude-haiku-4-5-20251001")
```

(Pick the model the user prefers — haiku is cheap and fast. Adjust if needed.)

- [ ] **Step 3: Verify the gating works**

```bash
ANTHROPIC_API_KEY="" uv run pytest tests/integration/ --collect-only -q 2>&1 | tail -5
```

Expected: tests collected but marked skipped (if any exist yet — at this point the directory is empty, so 0 tests).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/__init__.py tests/integration/conftest.py
git commit -m "test(active-hooks): scaffold live integration test infra with ANTHROPIC_API_KEY gating"
```

---

## Task 8: Live integration test — `HookBlock` blocks a tool call

**Why:** Verifies end-to-end that a registered `HookBlock` on `tool.invoke.before` actually prevents a tool from running against a real model, and that the synthetic blocked tool result reaches the model.

**Files:**
- Create: `tests/integration/test_active_hooks_live.py`

- [ ] **Step 1: Write the test**

Create `tests/integration/test_active_hooks_live.py`:

```python
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
```

- [ ] **Step 2: Run the test against the live API**

```bash
uv run pytest tests/integration/test_active_hooks_live.py::test_hook_block_prevents_tool_call_live -v -s
```

Expected: pass. If it fails on the final assertion (model wording), loosen the word list or split that into a soft assertion.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_active_hooks_live.py
git commit -m "test(active-hooks): live integration test for HookBlock on tool.invoke.before"
```

---

## Task 9: Live integration test — `ask_user` round trip

**Why:** Verifies that the agent yields when calling `ask_user`, the caller can resume with a user response, and the model continues with the response in context.

**Files:**
- Modify: `tests/integration/test_active_hooks_live.py` — add `test_ask_user_round_trip_live`

- [ ] **Step 1: Append the test to the file**

```python
async def test_ask_user_round_trip_live(tmp_path):
    """Agent yields via ask_user, caller resumes with response, agent completes."""
    from mori.control.checkpointing import SqliteCheckpointer  # adjust import

    cp_path = tmp_path / "threads.db"

    agent = (
        Mori.builder()
        .model("anthropic", model="claude-haiku-4-5-20251001")
        .checkpointer(SqliteCheckpointer(path=str(cp_path)))
        .build()
    )

    # First leg: agent should ask which database
    result = await agent.run(
        "I want to back up a database. Use ask_user to ask me which one (just 'prod' or 'staging'). "
        "After I answer, say you'll back up that one and stop."
    )
    assert result.status == RunStatus.PAUSED
    assert result.paused_prompt is not None
    assert any(w in result.paused_prompt.lower() for w in ("which", "database", "prod", "staging"))

    # Second leg: caller resumes with the answer
    result = await agent.resume(result.thread_id, "prod")
    assert result.status == RunStatus.COMPLETED
    assert result.final_output is not None
    assert "prod" in result.final_output.lower()
```

- [ ] **Step 2: Adjust imports**

Locate the actual SqliteCheckpointer class in the codebase:

```bash
grep -rn "class.*Checkpointer" mori/ --include="*.py" | head -10
```

Update the import in the test to match.

- [ ] **Step 3: Run the test**

```bash
uv run pytest tests/integration/test_active_hooks_live.py::test_ask_user_round_trip_live -v -s
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_active_hooks_live.py
git commit -m "test(active-hooks): live integration test for ask_user round trip"
```

---

## Task 10: Live integration test — `turn.start` context injection

**Why:** Verifies that a `turn.start` hook can mutate the input payload and the model sees the mutation.

**Files:**
- Modify: `tests/integration/test_active_hooks_live.py` — add `test_turn_start_context_injection_live`

- [ ] **Step 1: Append the test**

```python
async def test_turn_start_context_injection_live():
    """A turn.start hook prepends a system note; model acknowledges it."""
    agent = (
        Mori.builder()
        .model("anthropic", model="claude-haiku-4-5-20251001")
        .build()
    )

    @agent.hooks.hook(HookEvents.TURN_START)
    async def inject_marker(payload):
        payload.input = f"[INTERNAL MARKER: SECRET-CANARY-9381]\n\n{payload.input}"
        return payload

    result = await agent.run(
        "Tell me what marker code you see in this conversation, if any. Just echo the code."
    )

    assert result.status == RunStatus.COMPLETED
    assert "SECRET-CANARY-9381" in (result.final_output or "")
```

- [ ] **Step 2: Run the test**

```bash
uv run pytest tests/integration/test_active_hooks_live.py::test_turn_start_context_injection_live -v -s
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_active_hooks_live.py
git commit -m "test(active-hooks): live integration test for turn.start input mutation"
```

---

## Task 11: Final verification

**Why:** Confirm the full Active Hooks v1 surface is green: unit tests (64+ existing + 8 new), live tests (3 new), no regressions in unrelated modules.

- [ ] **Step 1: Run the entire test suite without the live key**

```bash
ANTHROPIC_API_KEY="" uv run pytest --tb=short -q 2>&1 | tail -15
```

Expected: all unit tests pass; integration tests skipped (3 skips).

- [ ] **Step 2: Run the entire test suite WITH the live key**

```bash
uv run pytest --tb=short -q 2>&1 | tail -15
```

Expected: all unit tests pass; 3 live tests pass.

- [ ] **Step 3: Smoke-test the existing examples that exercise Active Hooks**

```bash
uv run python examples/hooks_block.py 2>&1 | tail -5
uv run python examples/hooks_retry.py 2>&1 | tail -5
uv run python examples/chat_loop.py < /dev/null 2>&1 | tail -10 || true
uv run python examples/governance.py 2>&1 | tail -5
```

Expected: each runs without traceback. `chat_loop.py` may exit early due to stdin EOF — that's fine; it shouldn't crash with an exception.

- [ ] **Step 4: Verify the documentation cross-refs are intact**

```bash
grep -rn "AWAIT_USER\b" mori-docs/ | grep -v "PAUSED_AWAIT_USER"
```

Expected: no output (Task 1 should have cleaned all of these).

```bash
grep -n "ask_user" mori-docs/specs/05-TOOLS-AND-PROTOCOLS.md | head -5
```

Expected: text reflects auto-register / opt-out (Task 2).

```bash
grep -n "max_retry_limit" mori-docs/specs/10-PLUGINS-AND-ADAPTERS.md
```

Expected: at least one match in the A.2 Configuration code block (Task 3).

- [ ] **Step 5: Final commit if there's anything outstanding**

```bash
git status
```

If clean, the plan is done. If there's anything left, fix and commit.

---

## Notes for the implementing engineer

- **No new behavior changes are introduced for existing hook users.** Every change is additive (`HookPolicyEvent`, top-level exports) or documentation-only (Tasks 1-3).
- **The 64 existing hook tests are the safety net.** Run them after every code change in Tasks 4-6 to catch regressions immediately.
- **Live tests can be flaky** because model outputs are nondeterministic. If a wording assertion fails repeatedly, prefer a structural assertion (e.g., "the model's final message exists and contains <expected-substring>") over a vocabulary assertion. Don't loosen until the assertion proves brittle.
- **Cost:** each live test uses claude-haiku for a single short conversation. Three live tests should cost well under $0.05 per full run.
- **No PyPI release.** Per the IMPLEMENTATION-PLAN Philosophy section, Mori is internal-only — these changes do not require any release-engineering tasks.
