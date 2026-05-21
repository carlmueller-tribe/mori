# Mori v0.7 "It Enforces" — Active Hooks Design Spec

**Date:** 2026-05-21
**Branch:** v0.7/active-hooks
**Status:** Draft

---

## 1. Goal

Extend Mori's existing `HookRegistry` so that hooks can do three things they cannot do today:

1. **Block.** Any registered hook can veto an operation via `raise HookBlock(reason)`. Today, only the declarative `PermissionEngine` can deny; hooks can only observe and transform.
2. **Force a retry.** Output-validating hooks can `raise HookRetry(feedback)` to make the loop iterate again with the feedback injected as a system message.
3. **Gate turn boundaries.** Two new events — `turn.start` and `turn.end` — fire at the boundaries that matter to a human consumer of the agent. They work identically in autonomous and chat modes.

In addition, v0.7 makes Mori chat-capable by shipping a native `ask_user(question)` tool that yields control to the caller, who resumes via the existing `agent.resume(thread_id, input)` path.

### Motivation

Mori's positioning is "governed, auditable LLM agent systems." Today, governance lives in two places:

- `PermissionEngine` — declarative, deny-wins, per-(identity, resource, condition) rules
- `HookRegistry` — observe-only or transform-only; cannot deny

The gap is **imperative gates**: checks that the declarative engine cannot express ("scan this prompt for shell substitution patterns," "block if the model's last response speculates without grounding"). The post *Rules Are Aspirational* (Phin Argofy, 2026-05-20) makes the case that prose rules and skill workflows are routinely rationalized past by the model itself, and that mechanical gates running outside the model's reasoning loop are the missing layer. Mori has the loop and the registry; it does not yet have the gate semantics.

---

## 2. Scope

### In scope (v0.7)

- `HookBlock` and `HookRetry` exception types caught by `HookRegistry.dispatch_before` and propagated to the runtime
- Two new events: `turn.start`, `turn.end` (work in both autonomous and chat modes)
- Typed event constants module (`HookEvents`) — string registration stays valid
- Native `ask_user` tool that yields control to the caller
- `agent.resume(thread_id, input)` change: when a paused `ask_user` call exists, inject the input as that call's tool result
- `TurnEndReason` enum
- Bounded retry: `MAX_RETRY_LIMIT` (default 3 per step) to prevent infinite loops
- Documentation and one example per capability
- Unit + integration + property tests

### Out of scope (deferred to later specs)

- **File-based hook config** — operators registering hooks via YAML/TOML/JSON. Deferred to "Active Hooks v2: Operator Config."
- **Default hook library** — shipping Mori's own no-speculate, secrets-scanner, etc. Deferred to "Active Hooks v2: Stock Hooks."
- **Typed event taxonomy refactor** — replacing string event names with a typed `HookEvent[PayloadT]` Protocol. Deferred to "Hook Events v2: Typed Taxonomy."
- **`permission.check.before` event** — symmetry with `permission.check.after`. Today's `tool.invoke.before` already provides an imperative block point for tool calls; adding a second block point creates a "which layer do I block at" decision for users. Defer until a use case requires it.
- **Phase-level events** (`phase.plan.before`, etc.) — Mori's per-phase observability already covers this for observation; no use case yet for blocking inside a phase.

---

## 3. Architectural Principle

Active Hooks v0.7 follows an additive design principle: **one hook system, three capabilities.**

> **P8: Hooks are one mechanism with three modes.** A registered hook can *observe* (via `dispatch_after`), *transform* (return a mutated payload from `dispatch_before`), or *gate* (raise `HookBlock` / `HookRetry` from `dispatch_before`). Splitting these into separate registries or APIs would force users to learn parallel systems for what is conceptually one decision point. This matches the Claude Code hook model: 28 hooks across 10 event types using one hook concept, with the discipline encoded in exit codes (here, exceptions).

This sits alongside the existing P1-P7 principles in `mori-docs/architecture/`.

---

## 4. API Surface

Three new public symbols. Everything else is unchanged.

### 4.1 `mori.hooks.exceptions`

```python
class HookBlock(Exception):
    """Raised by a `dispatch_before` hook to veto the operation.

    Short-circuits the hook chain (later-priority hooks don't run).
    Propagates to the runtime, which translates it into a denial per event.

    Carries the reason and the hook_id that raised it.
    """
    def __init__(self, reason: str, *, hook_id: str | None = None) -> None:
        self.reason = reason
        self.hook_id = hook_id
        super().__init__(reason)


class HookRetry(Exception):
    """Raised by a `dispatch_before` hook to force a loop iteration.

    Short-circuits the hook chain. The runtime appends `feedback` as a
    system message and iterates again, bounded by MAX_RETRY_LIMIT.

    Only meaningful on events that gate model output (model.request.before,
    turn.end). Raising on observe-only events logs a warning and is ignored.
    """
    def __init__(self, feedback: str, *, hook_id: str | None = None) -> None:
        self.feedback = feedback
        self.hook_id = hook_id
        super().__init__(feedback)
```

### 4.2 `mori.hooks.events`

```python
class HookEvents:
    """Typed constants for known hook events. Strings stay valid for back-compat."""

    TURN_START = "turn.start"                   # NEW in v0.7
    TURN_END = "turn.end"                       # NEW in v0.7
    MODEL_REQUEST_BEFORE = "model.request.before"
    MODEL_RESPONSE_AFTER = "model.response.after"
    PERMISSION_CHECK_AFTER = "permission.check.after"
    TOOL_INVOKE_BEFORE = "tool.invoke.before"
    TOOL_INVOKE_AFTER = "tool.invoke.after"
    RUN_START = "run.start"
    RUN_END = "run.end"
```

### 4.3 `mori.tools.native.ask_user`

```python
async def ask_user(question: str) -> str:
    """Pause the agent and yield to the caller. Returns the user's response.

    Registered as a native tool. When the agent calls it, the loop:
      1. Saves a checkpoint
      2. Sets RunStatus.PAUSED, paused_reason="await_user_input",
         paused_prompt=question, paused_tool_call=<this call>
      3. Fires turn.end with reason=PAUSED_AWAIT_USER
      4. Returns control to the caller

    Caller resumes via `agent.resume(thread_id, user_response)`.
    """
```

### 4.4 Registration is unchanged

```python
@agent.hooks.hook(HookEvents.TOOL_INVOKE_BEFORE, priority=50)
async def block_prod_writes(call):
    if call.tool_name == "apply_migration" and call.args.get("env") == "prod":
        raise HookBlock("production migrations must go through CI")
    return None
```

### 4.5 Deliberately not added

- No `HookAllow` / `HookContinue` exception. Returning `None` already means "allow unchanged"; returning a payload means "allow with mutation."
- No structured `HookResult` return type. Exceptions handle block/retry; bare returns handle transform. A third return convention would create two ways to do the same thing.
- No async/sync split for the new exceptions — they work in both handler styles.

---

## 5. Event Specification

| Event | When it fires | Payload | `HookBlock`? | `HookRetry`? |
|---|---|---|---|---|
| `turn.start` (NEW) | Entry to `run(task)`; entry to `resume(thread_id, input)` | `TurnStartPayload` | yes | no |
| `model.request.before` | After request assembly, before `model.invoke` | `ModelRequest` | yes | yes |
| `model.response.after` | After `model.invoke` returns | `ModelResponse` | no (observe) | no |
| `permission.check.after` | After `PermissionEngine.check` returns | `PermissionResult` | no (observe) | no |
| `tool.invoke.before` | After permission ALLOW, before `tools.invoke` | `ToolCall` | yes | no |
| `tool.invoke.after` | After `tools.invoke` returns | `ToolResult` | no (observe) | no |
| `run.start` (existing) | Once per `run()`, before any phases | `{task, run_id}` | no (after) | no |
| `run.end` (existing) | Once per `run()`, after loop exits | `{status, run_id}` | no (after) | no |
| `turn.end` (NEW) | Every exit of `run()` or `resume()` | `TurnEndPayload` | no | yes |

### 5.1 Payload types

```python
class TurnStartPayload(MoriModel):
    input: str
    thread_id: ThreadId
    is_resume: bool   # False on initial run(), True on resume()


class TurnEndPayload(MoriModel):
    state: MoriState
    reason: TurnEndReason


class TurnEndReason(str, Enum):
    COMPLETED = "completed"
    PAUSED_AWAIT_USER = "paused_await_user"
    PAUSED_ESCALATE = "paused_escalate"
    EXHAUSTED = "exhausted"
    ERRORED = "errored"
    BLOCKED = "blocked"
```

### 5.2 Distinction between `run.*` and `turn.*`

Both pairs fire at the same moments — every entry and exit of `_run_from_state`, which today already includes pauses and resumes. The distinction is **dispatch mode and capability**, not firing point:

| Pair | Dispatch mode | Capability | Status |
|---|---|---|---|
| `run.start` / `run.end` | `dispatch_after` | observe-only | existing, unchanged |
| `turn.start` / `turn.end` | `dispatch_before` | can block (`turn.start`) / retry (`turn.end`) | new in v0.7 |

Firing order: on entry, `turn.start` fires first (and may block — see §6.2), then `run.start` fires. On exit, `turn.end` fires first (and may force retry — see §6.2), then `run.end` fires. Keeping both pairs means existing `run.*` consumers don't break, and the new events provide the gate capability without overloading the observe-only contract of the old ones.

A future spec ("Hook Events v2: Typed Taxonomy") may collapse the redundancy by making `run.*` deprecated aliases that fire after `turn.*`. v0.7 does not deprecate them.

---

## 6. Exception Semantics

### 6.1 Order of operations in `dispatch_before`

```python
async def dispatch_before(self, event_name: str, payload: Any) -> Any:
    current = payload
    for _priority, hook_id, handler in self._hooks.get(event_name, []):
        try:
            result = await self._call(handler, current)
        except HookBlock as e:
            e.hook_id = e.hook_id or hook_id
            raise  # NEVER swallowed, regardless of fail_open
        except HookRetry as e:
            e.hook_id = e.hook_id or hook_id
            raise  # NEVER swallowed, regardless of fail_open
        if result is not None:
            current = result
    return current
```

Two invariants:

1. **`HookBlock` and `HookRetry` are never swallowed.** They bypass `fail_open`. Policy decisions are not errors.
2. **They short-circuit the chain.** Later-priority hooks for the same event do not run.

### 6.2 Runtime handling per event

| Event | `HookBlock` effect | `HookRetry` effect |
|---|---|---|
| `turn.start` | `_run_from_state` is skipped entirely; `turn.end` fires with `reason=BLOCKED`; `run.end` does NOT fire (the run never started its phases); returns `RunResult(status=BLOCKED, block_reason, block_hook_id)` | n/a (logged + ignored) |
| `model.request.before` | Same as `turn.start` block; model is never invoked | Request re-assembled with `feedback` appended as a system message; step retries; bounded by `MAX_RETRY_LIMIT` |
| `tool.invoke.before` | Synthetic tool result `Message(role="tool", content=f"BLOCKED by {hook_id}: {reason}", tool_call_id=call.id)` appended; loop continues so model can react | n/a (logged + ignored) |
| `turn.end` | n/a (no block on after-event) | `turn.end` fires; runtime treats run as not-done; loops one more iteration with `feedback` injected; bounded by `MAX_RETRY_LIMIT` |
| All other events | n/a | n/a (logged + ignored) |

### 6.3 `MAX_RETRY_LIMIT`

Configurable on `HookConfig` (default 3). Counted per step for `model.request.before` retries; per run for `turn.end` retries. On exhaustion, the runtime exits with `status=EXHAUSTED, reason="hook_retry_exhausted"`.

---

## 7. `ask_user` Tool

### 7.1 Tool registration

`mori/tools/native/ask_user.py`. Auto-added to the tool registry when the agent is built; can be disabled via `Mori.builder().disable_native_tool("ask_user")`.

```python
ToolSpec(
    name="ask_user",
    description="Ask the calling user a question and wait for their response. "
                "Use only when you cannot proceed without human input.",
    input_schema={
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
    },
    source=ToolSource.NATIVE,
)
```

### 7.2 Yield mechanism

`ask_user` does not return normally. It raises `YieldToUser(question)` — an internal signal, not part of the public API. `_phase_act` catches it:

```python
try:
    result = await self._tools.invoke(call.name, call.arguments)
except YieldToUser as y:
    state.status = RunStatus.PAUSED
    state.paused_reason = "await_user_input"
    state.paused_prompt = y.question
    state.paused_tool_call = call
    await self._checkpointer.save(state)
    return  # _run_from_state sees PAUSED and exits
```

**Tool runner change required.** `ToolRunner.invoke` must re-raise `YieldToUser`, `HookBlock`, and `HookRetry` rather than catching them and converting to `ToolResult(success=False, error=...)`. These are control-flow signals, not tool failures. The implementation adds a sentinel set of "control exceptions" that bypass the normal try/except in the runner.

### 7.3 Resume path

`agent.resume(thread_id, input)` is modified: if the loaded checkpoint has `paused_reason=="await_user_input"` and a `paused_tool_call`, the input is injected as that tool call's result before resuming:

```python
async def resume(self, thread_id: ThreadId, input: dict[str, Any] | str) -> RunResult:
    cp = await self._checkpointer.load_latest(thread_id)
    state = cp.state
    user_text = input if isinstance(input, str) else input.get("response", "")
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
        await self._hooks.dispatch_before(HookEvents.TURN_START, TurnStartPayload(
            input=user_text, thread_id=thread_id, is_resume=True,
        ))
    return await self._run_from_state(state)
```

### 7.4 Caller-side ergonomics

```python
result = await agent.run("Migrate the user table to add an email column")

while result.status == RunStatus.PAUSED and result.paused_reason == "await_user_input":
    answer = input(f"{result.paused_prompt}\n> ")
    result = await agent.resume(result.thread_id, answer)

# result.status is now COMPLETED, EXHAUSTED, BLOCKED, or ERRORED
```

---

## 8. State Model Changes

`MoriState` gains one field (if not already present):

```python
paused_prompt: str | None = None   # set when paused_reason == "await_user_input"
```

`RunResult` gains three optional fields:

```python
block_reason: str | None = None
block_hook_id: str | None = None
paused_prompt: str | None = None
```

`RunStatus` gains one variant:

```python
BLOCKED = "blocked"
```

`HookConfig` gains one field:

```python
max_retry_limit: int = 3
```

---

## 9. Testing Strategy

### 9.1 Unit tests (`tests/hooks/`)

- `test_hook_block.py` — `HookBlock` propagates from each event type; short-circuits chain; `fail_open=True` does not swallow; runtime translates to correct `RunStatus` per event
- `test_hook_retry.py` — `HookRetry` injects feedback; bounded by `MAX_RETRY_LIMIT`; raised on observe-only events logs warning and is ignored
- `test_turn_events.py` — `turn.start` and `turn.end` fire on `run()` and `resume()`; payload shape; `is_resume` flag; all reason enum variants
- `test_ask_user.py` — calling `ask_user` from a tool yields; state transitions to PAUSED with correct fields; checkpoint saved; resume injects response correctly

### 9.2 Integration tests (`tests/integration/test_active_hooks.py`)

- End-to-end "no-speculation" hook: register on `model.request.before`, `HookRetry` when response speculates → loop retries with feedback until grounded or max retries
- End-to-end "block prod migration" hook: register on `tool.invoke.before`, `HookBlock` when args target production → synthetic blocked message; agent sees it and replans
- End-to-end chat loop: agent calls `ask_user`, yields, caller resumes, agent completes

### 9.3 Property tests (`tests/hooks/test_invariants.py`)

- For every `dispatch_before` event: a no-op hook (returns None) is observationally identical to no hook registered
- For every `dispatch_before` event: `HookBlock` always short-circuits — later hooks never observe the payload
- `turn.end` always fires exactly once per `turn.start` (paired invariant)

---

## 10. Migration & Backward Compatibility

### 10.1 Breaking changes

**None.** All changes are additive:

- Existing string-keyed `@registry.hook("tool.invoke.before")` registrations work unchanged
- Existing `dispatch_before` callers in `loop.py` gain block/retry capability transparently — if no hook raises, behavior is identical to today
- Existing 7 events keep their names and payload types
- `agent.run(task)` callers see no change unless the agent uses `ask_user`
- Existing `agent.resume()` callers see no change unless the prior pause was an `ask_user` yield

### 10.2 Documentation

- `mori-docs/architecture/hooks.md` — new doc explaining the three things hooks can do (observe / transform / gate) and the event taxonomy
- `mori-docs/architecture/chat-mode.md` — new doc explaining `ask_user` + resume pattern
- `README.md` Quick Start gains a chat-mode example
- `examples/hooks_block.py` — one example demonstrating `HookBlock`
- `examples/hooks_retry.py` — one example demonstrating `HookRetry`
- `examples/chat_loop.py` — one example demonstrating `ask_user` + resume

### 10.3 Rollout

Single PR, behind no feature flag. Capabilities are opt-in by use — registering a hook that raises, or calling `ask_user`. Default behavior unchanged for existing agents.

---

## 11. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      AgentLoop.run()                        │
│                                                             │
│   ┌──── turn.start ───┐                                     │
│   │  (NEW event;      │  payload: TurnStartPayload          │
│   │   blocks allowed) │                                     │
│   └─────────┬─────────┘                                     │
│             ↓                                               │
│   ┌─────────────────────────────────────────────────────┐   │
│   │  Existing loop: retrieve → plan → act → evaluate    │   │
│   │                                                     │   │
│   │  model.request.before  ─── HookBlock | HookRetry    │   │
│   │  model.response.after  ─── observe                  │   │
│   │  permission.check.after ── observe                  │   │
│   │  tool.invoke.before    ─── HookBlock                │   │
│   │  tool.invoke.after     ─── observe                  │   │
│   │                                                     │   │
│   │  ↓ if agent calls ask_user(question):               │   │
│   │    RunStatus.PAUSED, paused_reason=await_user_input │   │
│   │    paused_prompt=question                           │   │
│   └─────────────────────┬───────────────────────────────┘   │
│                         ↓                                   │
│   ┌──── turn.end ─────┐                                     │
│   │  (NEW event;      │  payload: TurnEndPayload            │
│   │   retries allowed)│  reason: TurnEndReason              │
│   └───────────────────┘                                     │
└─────────────────────────────────────────────────────────────┘

   agent.resume(thread_id, user_input)  ──► fires turn.start
   again with the new input; if a paused ask_user call exists,
   the input is injected as that tool's result.
```

---

## 12. Open Questions

None — every design question raised during brainstorming has been resolved. Items deferred to future specs are listed in §2 "Out of scope."
