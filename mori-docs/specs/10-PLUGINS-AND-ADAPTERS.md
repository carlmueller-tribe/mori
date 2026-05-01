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

| Event Name              | Payload Type       | Before/After | Notes                              |
|-------------------------|--------------------|--------------|------------------------------------|
| `run.start`             | RunStartPayload    | Both         | Before: can modify task/config     |
| `run.end`               | RunEndPayload      | After only   | Observe final status               |
| `step.start`            | StepStartPayload   | Both         | Before: can inject context         |
| `step.end`              | StepEndPayload     | After only   | Observe step outcome               |
| `memory.read.before`    | MemoryReadPayload  | Before       | Can modify query or filters        |
| `memory.read.after`     | MemorySlice        | After        | Observe what was retrieved         |
| `memory.write.before`   | list[MemoryRecord] | Before       | Can modify/filter records          |
| `memory.write.after`    | WriteReceipt       | After        | Observe what was written           |
| `skill.discover.before` | DiscoverPayload    | Before       | Can modify query/context           |
| `skill.discover.after`  | list[SkillCandidate]| After       | Observe candidates                 |
| `skill.load.before`     | SkillLoadPayload   | Before       | Can change disclosure level        |
| `skill.load.after`      | SkillPayload       | After        | Observe loaded content             |
| `tool.invoke.before`    | ToolCall           | Before       | Can modify arguments, redact data  |
| `tool.invoke.after`     | ToolResult         | After        | Observe result                     |
| `permission.check.after`| PermissionResult   | After        | Observe decision                   |
| `model.request.before`  | ModelRequest       | Before       | Can modify messages/tools          |
| `model.response.after`  | ModelResponse      | After        | Observe/filter model output        |

### A.4 Dispatch Behavior

**Before hooks** run in priority order (lowest first). Each receives the output of the previous. If a hook returns None, the unmodified payload passes through.

```
payload_0 = original
payload_1 = hook_1(payload_0)
payload_2 = hook_2(payload_1)
final = payload_n
```

**After hooks** all receive the same payload. Return values ignored.

Each hook has a timeout (`hook_timeout_sec`). If exceeded, the hook is cancelled and treated as a failure. When `fail_open=True`, failures are logged but do not abort the operation.

### A.5 Example Hooks

```python
@hooks.hook("tool.invoke.before", priority=10)
async def redact_secrets(payload: ToolCall) -> ToolCall:
    payload.arguments = redact(payload.arguments, SECRET_PATTERNS)
    return payload

@hooks.hook("run.end", priority=100)
async def notify_on_failure(payload: RunEndPayload) -> None:
    if payload.status in ("failed", "timeout"):
        await slack.post(f"Run {payload.run_id}: {payload.status}")

@hooks.hook("step.end", priority=50)
async def track_cost(payload: StepEndPayload) -> None:
    cost_tracker.record(tokens=payload.input_tokens + payload.output_tokens)
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

**Adapters:**
- [ ] RuntimeAdapter protocol is implementable by a third party
- [ ] LangGraphAdapter produces a working agent
- [ ] langgraph_as_tool wraps a graph as a callable tool
- [ ] langgraph_as_skill produces a valid SkillManifest
- [ ] Mori works without any adapter installed (native runtime is default)
