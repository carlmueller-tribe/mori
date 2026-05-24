# 10: Plugins, Hooks, and Framework Adapters

**Status:** Draft v3
**Module:** `mori.plugins`, `mori.adapters`
**Dependencies:** Spec 01

---

## 1. Purpose

Two extension mechanisms:
- **Hooks:** attach custom logic to any lifecycle event (secret redaction, notifications, cost tracking)
- **Framework Adapters:** use external frameworks (LangGraph, CrewAI) as alternative runtimes or tool/skill sources

---

## Part A: Hooks

### A.1 Interface

```python
class HookRegistry:

    def __init__(self, config: HookConfig | None = None) -> None: ...

    # Registration
    def register(self, event_name: str, handler: HookHandler, priority: int = 100, name: str | None = None) -> str: ...
    def unregister(self, hook_id: str) -> bool: ...
    def hook(self, event_name: str, priority: int = 100) -> Callable:
        """Decorator for registering hooks."""

    # Dispatch
    async def dispatch_before(self, event_name: str, payload: Any) -> Any: ...
    async def dispatch_after(self, event_name: str, payload: Any) -> None: ...

    # Inspection
    def list_hooks(self, event_name: str | None = None) -> list[HookRegistration]: ...
    def clear(self, event_name: str | None = None) -> int: ...
```

### A.2 Configuration

```python
class HookConfig(MoriModel):
    max_hooks_per_event: int = 50
    hook_timeout_sec: float = 10.0
    fail_open: bool = True          # Hook failures don't block operations
    log_hook_errors: bool = True
    log_hook_execution: bool = False

HookHandler = Callable[[Any], Any] | Callable[[Any], Awaitable[Any]]

class HookRegistration(MoriModel):
    hook_id: str
    event_name: str
    handler_name: str
    priority: int
    registered_at: datetime
```

### A.3 Lifecycle Events

| Event Name              | Payload Type        | Before/After | Notes                              |
|-------------------------|---------------------|--------------|------------------------------------|
| `turn.start`            | TurnStartPayload    | Before       | Fires at `run()` and `resume()` entry. Can mutate input. |
| `turn.end`              | TurnEndPayload      | Before       | Fires before result returns to caller. Can mutate result. |
| `run.start`             | RunStartPayload     | After        | Observe full-run start (autonomous boundary)        |
| `run.end`               | RunEndPayload       | After        | Observe full-run end (autonomous boundary)          |
| `step.start`            | StepStartPayload    | Both         | Before: can inject context         |
| `step.end`              | StepEndPayload      | After only   | Observe step outcome               |
| `memory.read.before`    | MemoryReadPayload   | Before       | Can modify query or filters        |
| `memory.read.after`     | MemorySlice         | After        | Observe what was retrieved         |
| `memory.write.before`   | list[MemoryRecord]  | Before       | Can modify/filter records          |
| `memory.write.after`    | WriteReceipt        | After        | Observe what was written           |
| `skill.discover.before` | DiscoverPayload     | Before       | Can modify query/context           |
| `skill.discover.after`  | list[SkillCandidate]| After        | Observe candidates                 |
| `skill.load.before`     | SkillLoadPayload    | Before       | Can change disclosure level        |
| `skill.load.after`     | SkillPayload        | After        | Observe loaded content             |
| `tool.invoke.before`    | ToolCall            | Before       | Can modify arguments, redact data  |
| `tool.invoke.after`     | ToolResult          | After        | Observe result                     |
| `permission.check.after`| PermissionResult    | After        | Observe decision                   |
| `model.request.before`  | ModelRequest        | Before       | Can modify messages/tools          |
| `model.response.after`  | ModelResponse       | After        | Observe/filter model output        |

**Event name constants.** A `mori.hooks.events.HookEvents` constants class exposes the well-known event names so callers don't have to hard-code strings. String-keyed registrations remain valid for back-compat.

```python
from mori.hooks.events import HookEvents

@hooks.hook(HookEvents.TURN_START)
async def inject_context(payload): ...
```

#### A.3.1 Turn-boundary payloads

`turn.start` and `turn.end` are the recommended hook points for governance gates — they cover both autonomous (`run(task)` → result) and chat (`run()` then `resume()` cycles) modes uniformly. They fire once per turn boundary regardless of mode.

```python
class TurnStartPayload(MoriModel):
    thread_id: ThreadId
    run_id: RunId
    input: str                       # task on run(), user_response on resume()
    is_resume: bool                  # True on resume()
    paused_tool_call: ToolCall | None  # set on resume from ask_user pause
    state: MoriState                 # read-only; mutations to fields other than `input` are ignored

class TurnEndPayload(MoriModel):
    thread_id: ThreadId
    run_id: RunId
    reason: TurnEndReason
    state: MoriState                 # read-only
    result: RunResult                # what's about to be returned to caller
    paused_prompt: str | None        # set when reason=AWAIT_USER

class TurnEndReason(StrEnum):
    COMPLETED = "completed"                # agent finished naturally
    AWAIT_USER = "await_user"              # ask_user tool invoked
    PAUSED_ESCALATE = "paused_escalate"    # PermissionEngine ESCALATE
    EXHAUSTED = "exhausted"                # max_steps reached
    ERRORED = "errored"                    # uncaught exception in loop
    BLOCKED = "blocked"                    # HookBlock at turn.start or model.request.before
```

#### A.3.2 Capability matrix per event

Hooks have three things they can do beyond observation: **transform** the payload by returning a non-None value, **block** the operation by raising `HookBlock`, or **retry** the loop by raising `HookRetry`. Not every event supports all three. See `A.5 Policy Signals` for the exceptions; this matrix is the contract.

| Event                    | observe | transform | HookBlock | HookRetry |
|--------------------------|:-------:|:---------:|:---------:|:---------:|
| `turn.start`             | ✓       | ✓         | ✓         | —         |
| `model.request.before`   | ✓       | ✓         | ✓         | ✓         |
| `model.response.after`   | ✓       | —         | —         | —         |
| `permission.check.after` | ✓       | —         | —         | —         |
| `tool.invoke.before`     | ✓       | ✓         | ✓         | —         |
| `tool.invoke.after`      | ✓       | —         | —         | —         |
| `turn.end`               | ✓       | ✓         | ✓         | ✓ (only `COMPLETED` / `EXHAUSTED`) |
| `run.start`, `run.end`   | ✓       | —         | —         | —         |
| all other `*.before`     | ✓       | ✓         | —         | —         |
| all other `*.after`      | ✓       | —         | —         | —         |

Raising `HookBlock` or `HookRetry` on an event where it isn't supported is a misuse — logged at error level and treated as if the handler returned `None`. The run continues.

### A.4 Dispatch Behavior

**Before hooks** run in priority order (lowest first). Each receives the output of the previous. If a hook returns None, the unmodified payload passes through.

```
payload_0 = original
payload_1 = hook_1(payload_0)
payload_2 = hook_2(payload_1)
final = payload_n
```

**After hooks** all receive the same payload. Return values ignored.

Each hook has a timeout (`hook_timeout_sec`). If exceeded, the hook is cancelled and treated as a failure. When `fail_open=True`, regular failures are logged but do not abort the operation.

**Policy signals (`HookBlock`, `HookRetry`) are not failures.** They are designed control-flow signals raised by a handler to veto or retry the operation. Their behavior:

- **Never swallowed by `fail_open`.** `fail_open` was designed to keep observers from breaking runs; policy decisions are not observers and must never be hidden.
- **Short-circuit the hook chain.** When raised, no lower-priority hooks for the same event run.
- **Propagate to the runtime,** which translates them per event (see A.5 Policy Signals).
- **Are logged at `info` level** (not `warning`) and emitted as a `HookPolicyEvent` to the observability stream.
- **Stamp `hook_id` and `event_name` on the exception** during propagation so the runtime knows which hook raised at which event.
- **Are misuses in `dispatch_after` handlers** — `dispatch_after` is fire-and-forget; raising a policy signal there is logged at error and swallowed.

A regular `Exception` raised by a handler keeps existing behavior: subject to `fail_open` and `hook_timeout_sec`. Only the two named policy signals bypass `fail_open`.

### A.5 Policy Signals

Two exception types let `dispatch_before` hooks change what happens, not just observe or transform. Both are defined in `mori.hooks.exceptions` and re-exported from `mori`.

```python
class HookBlock(Exception):
    """Raised by a dispatch_before hook to veto the operation.

    Short-circuits the hook chain. Propagates to the runtime, which
    translates the block per event (see translation table below).
    Never swallowed by fail_open. Carries reason, hook_id, event_name.
    """
    def __init__(self, reason: str, *, hook_id: str | None = None): ...


class HookRetry(Exception):
    """Raised by a dispatch_before hook to force a loop iteration.

    Short-circuits the hook chain. Propagates to the runtime, which
    re-enters the loop with `feedback` appended as a system message
    in the next model request. Counts toward max_steps.

    Only meaningful on events that gate model output:
      - model.request.before
      - turn.end (only when reason ∈ {COMPLETED, EXHAUSTED})

    HookRetry on any other event is misuse: logged at error, treated as None.
    """
    def __init__(self, feedback: str, *, hook_id: str | None = None): ...
```

#### A.5.1 Runtime translation table

The runtime catches policy signals at each event-firing site and translates them per the matrix below. Outcomes are deterministic — no `fail_open` override applies.

| Site                      | `HookBlock` raised →                                                                                                            | `HookRetry` raised →                                                                                                       |
|---------------------------|---------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| `turn.start`              | Run does not start. `RunResult(status=BLOCKED, reason=block.reason)` returned. `turn.end` still fires with `reason=BLOCKED`.    | Misuse: logged at error, treated as `None`.                                                                                |
| `model.request.before`    | Model not invoked. Loop exits with `RunStatus.BLOCKED`. `turn.end` fires with `reason=BLOCKED`.                                 | Loop appends `feedback` as a system message and re-enters `_phase_plan`. `step_count` increments (counts toward `max_steps`). |
| `tool.invoke.before`      | Tool not invoked. Synthetic tool result `"BLOCKED: {reason}"` is appended. Loop continues to next tool call or next step.       | Misuse: logged at error, treated as `None`.                                                                                |
| `turn.end`                | `result.status` is overwritten to `BLOCKED`. `payload.reason` set to `BLOCKED`. Caller gets the modified result.                | Only valid when `reason ∈ {COMPLETED, EXHAUSTED}`. Loop re-enters with `feedback` appended as system message. Otherwise misuse. |
| Other `before` events     | Block at the relevant event boundary (no model/tool invocation downstream of the block site).                                   | Misuse: logged at error, treated as `None`.                                                                                |
| Any `after` event         | Misuse: logged at error, swallowed.                                                                                             | Misuse: logged at error, swallowed.                                                                                        |

#### A.5.2 Observability

Every block and retry signal produces a `HookPolicyEvent` on the observability stream:

```python
class HookPolicyEvent(MoriEvent):
    event_type: Literal["hook.policy"] = "hook.policy"
    signal: Literal["HookBlock", "HookRetry"]
    event_name: str                  # which hook event the signal was raised at
    hook_id: str                     # which hook raised
    handler_name: str
    reason: str                      # the message argument to the exception
    run_id: RunId
```

Sinks must log this event prominently — policy decisions changing run outcomes should not require digging through DEBUG logs.

#### A.5.3 Edge cases

- **Multiple `HookBlock`s on the same event** is impossible — the first one short-circuits. The hook with the lowest priority value wins.
- **`HookBlock` at `turn.end`** can fire even after a successful run. This is intentional — it's the "fail the result before returning" use case (e.g., output contains PII).
- **`HookRetry` infinite loops** are bounded by `max_steps` like any other loop iteration. No separate retry counter.
- **A hook that times out** (`asyncio.TimeoutError`) is *not* treated as a block — silent failure to enforce, but visible in logs. Users who want timeout to be fatal set `fail_open=False`.

---

### A.6 Example Hooks

```python
# Observe/transform: redact secrets in tool arguments
@hooks.hook("tool.invoke.before", priority=10)
async def redact_secrets(payload: ToolCall) -> ToolCall:
    payload.arguments = redact(payload.arguments, SECRET_PATTERNS)
    return payload

# After: notify on failure
@hooks.hook("run.end", priority=100)
async def notify_on_failure(payload: RunEndPayload) -> None:
    if payload.status in ("failed", "timeout"):
        await slack.post(f"Run {payload.run_id}: {payload.status}")

# After: cost tracking
@hooks.hook("step.end", priority=50)
async def track_cost(payload: StepEndPayload) -> None:
    cost_tracker.record(tokens=payload.input_tokens + payload.output_tokens)

# Block: forbid production migrations from the agent path
@hooks.hook("tool.invoke.before", priority=20)
async def block_prod_writes(call: ToolCall) -> ToolCall | None:
    if call.tool_name == "apply_migration" and call.arguments.get("env") == "prod":
        raise HookBlock("production migrations must go through CI, not the agent")
    return None

# Retry: refuse ungrounded answers, force the loop to reconsider
@hooks.hook(HookEvents.TURN_END, priority=50)
async def no_speculate(payload: TurnEndPayload) -> None:
    if payload.reason != TurnEndReason.COMPLETED:
        return None
    last = payload.state.messages[-1]
    if has_ungrounded_speculation(last.content) and not has_grounding_tool_call(payload.state):
        raise HookRetry(
            "Your response contains speculation. Either ground it in a tool call "
            "or revise to remove unsupported claims."
        )
    return None

# Inject: prepend context-budget notice when the agent is near its budget
@hooks.hook(HookEvents.TURN_START, priority=30)
async def inject_budget_warning(payload: TurnStartPayload) -> TurnStartPayload:
    pct = budget.utilization_pct()
    if pct > 80:
        payload.input = f"[CONTEXT BUDGET: {pct}% used. Be concise.]\n\n{payload.input}"
    return payload

# Block at turn.start: refuse runs that look like SQL drops
@hooks.hook(HookEvents.TURN_START, priority=10)
async def block_destructive_inputs(payload: TurnStartPayload) -> None:
    if re.search(r"\bDROP\s+TABLE\b", payload.input, re.IGNORECASE):
        raise HookBlock("input contains a DROP TABLE pattern; refusing to run")
    return None
```

---

### A.7 Chat mode

`ask_user` (Spec 05 Section 5.1) is the native tool that yields the agent to the caller for input. The hook surface around chat mode is:

- **`turn.start`** fires on both `run(task)` and `resume(thread_id, user_response)`. Distinguish via `payload.is_resume`.
- **`turn.end`** fires with `reason=AWAIT_USER` when the agent invokes `ask_user`. `payload.paused_prompt` holds the question.
- **`tool.invoke.before`** fires for `ask_user` like any other tool. Operators can raise `HookBlock` to refuse `ask_user` in autonomous contexts.

See Spec 05 for the pause/resume lifecycle. The diagram below shows where the events fire:

```
agent.run("plan the migration")
  ├─ turn.start (input="plan the migration", is_resume=False)
  ├─ loop iterations
  ├─ model decides to call ask_user("which db?")
  ├─ tool.invoke.before fires (can block here)
  ├─ ask_user raises YieldToUser internally
  ├─ state.status = PAUSED, checkpoint saved
  ├─ turn.end (reason=AWAIT_USER, paused_prompt="which db?")
  └─ returns RunResult(status=PAUSED, paused_prompt="which db?")

agent.resume(thread_id, "prod-replica-1")
  ├─ checkpoint loaded
  ├─ turn.start (input="prod-replica-1", is_resume=True, paused_tool_call=<ask_user call>)
  ├─ user response injected as tool result for the paused call
  ├─ loop continues
  ├─ turn.end (reason=COMPLETED)
  └─ returns RunResult(status=COMPLETED, ...)
```

---

## Part B: Framework Adapters

### B.1 RuntimeAdapter Protocol

```python
class RuntimeAdapter(Protocol):
    """Allows an external framework to serve as Mori's execution engine."""

    async def run(self, task: str, state: MoriState, tools: ToolRegistry, memory: MemoryModule | None, skills: SkillsModule | None, config: LoopConfig) -> RunResult: ...
    async def stream(self, task: str, state: MoriState, tools: ToolRegistry, **kwargs) -> AsyncIterator[StreamEvent]: ...
```

### B.2 LangGraph Adapter (optional: `pip install mori[langgraph]`)

```python
class LangGraphAdapter(RuntimeAdapter):
    """Wraps Mori modules into a LangGraph StateGraph."""

    def __init__(self, graph_builder: Callable | None = None): ...
    async def run(self, task, state, tools, memory, skills, config) -> RunResult: ...
    async def stream(self, task, state, tools, **kwargs) -> AsyncIterator[StreamEvent]: ...
```

Usage:

```python
from mori import Mori
from mori.adapters.langgraph import LangGraphAdapter

agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .runtime(LangGraphAdapter())
    .tool(read_file)
    .build()
)
```

### B.3 Importing LangGraph Workflows

```python
def langgraph_as_tool(graph, name, description, input_schema) -> RegisteredTool: ...
def langgraph_as_skill(graph, name, version, description, triggers) -> SkillManifest: ...
```

---

## 3. AIUC-1 Contracts

Per `12-AIUC1-COMPLIANCE.md` Section 2.9:
- Guards (PIIGuard, IPGuard, etc.) MUST register at priority 1 (before all user hooks)
- Guards with `action=block` MUST prevent the operation from proceeding
- Guard detections MUST be logged as observability events with risk_flags

## 4. Test Criteria

**Hooks:**
- [ ] Registered hooks are called in priority order (lowest first)
- [ ] Before hooks can modify the payload; downstream hooks see modified version
- [ ] After hooks receive the final payload; return values ignored
- [ ] A failing hook does not block operation when fail_open=True
- [ ] A failing hook blocks operation when fail_open=False
- [ ] Hook timeout cancels a slow hook
- [ ] unregister removes a hook
- [ ] Both sync and async handlers are supported
- [ ] max_hooks_per_event is enforced

**Policy signals (`HookBlock`, `HookRetry`):**
- [ ] `HookBlock` raised in a before hook short-circuits the chain (later-priority hooks don't run)
- [ ] `HookBlock` is never swallowed by `fail_open=True`
- [ ] `HookBlock` at `turn.start` prevents the run from starting; `RunResult.status == BLOCKED`
- [ ] `HookBlock` at `tool.invoke.before` appends a synthetic `"BLOCKED: ..."` tool result; loop continues
- [ ] `HookBlock` at `turn.end` overwrites `result.status` to `BLOCKED` before returning to caller
- [ ] `HookRetry` at `model.request.before` causes loop to append feedback as system message and re-enter `_phase_plan`
- [ ] `HookRetry` at `turn.end` with `reason=COMPLETED` causes loop to continue with feedback
- [ ] `HookRetry` on an unsupported event is logged at error and treated as `None` (run not affected)
- [ ] `hook_id` and `event_name` are stamped on every propagated policy signal
- [ ] `HookPolicyEvent` is emitted to the observability stream for every block/retry signal
- [ ] Policy signals raised inside a `dispatch_after` handler are logged at error and swallowed

**Turn-boundary events:**
- [ ] `turn.start` fires once at `run(task)` entry with `is_resume=False`
- [ ] `turn.start` fires once at `resume(thread_id, input)` entry with `is_resume=True` and the prior `paused_tool_call` populated
- [ ] `turn.end` fires exactly once per `run()` or `resume()` call regardless of exit reason
- [ ] `turn.end.reason` correctly identifies COMPLETED / AWAIT_USER / PAUSED_ESCALATE / EXHAUSTED / ERRORED / BLOCKED

**Adapters:**
- [ ] RuntimeAdapter protocol is implementable by a third party
- [ ] LangGraphAdapter produces a working agent
- [ ] langgraph_as_tool wraps a graph as a callable tool
- [ ] langgraph_as_skill produces a valid SkillManifest
- [ ] Mori works without any adapter installed (native runtime is default)
