# 02: Runtime

**Status:** Draft v3
**Module:** `mori.runtime`
**Dependencies:** Specs 01, 07, 08, 09

---

## 1. Purpose

Mori's native agent runtime. A lightweight async state machine that orchestrates all externalization modules. No external framework dependency. The loop is simple: an async while loop that cycles through phases until termination.

## 2. Design Rationale

Mori's prebuilt loop follows a fixed phase order (retrieve → plan → validate → act → observe → evaluate → update) because this covers the vast majority of agentic workflows. It is not a general-purpose graph engine. Teams that need arbitrary graph topologies can use the LangGraph adapter (Spec 10) or build custom loops using Mori's modules directly.

The simplicity is the point. A linear loop with conditional skips is easier to debug, trace, and reason about than a general graph runtime. Every phase is a single async function call with typed inputs and outputs.

## 3. MoriState

```python
class MoriState(MoriModel):
    """Mutable state carried across the loop."""
    run_id: RunId
    thread_id: ThreadId
    task: str
    context: dict = Field(default_factory=dict)
    messages: list[Message] = Field(default_factory=list)
    status: RunStatus = RunStatus.RUNNING

    # Memory
    memory_slice: MemorySlice | None = None

    # Skills
    active_skill: BoundSkill | None = None

    # Plan
    plan: PlanObject | None = None

    # Counters
    step_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0

    # Timing
    started_at: datetime
    last_progress_at: datetime
```

## 4. AgentLoop

```python
class AgentLoop:
    def __init__(
        self,
        model: ModelAdapter,
        tools: ToolRegistry,
        memory: MemoryModule | None = None,
        skills: SkillsModule | None = None,
        permission: PermissionEngine | None = None,
        control: ControlBounds | None = None,
        observability: ObservabilityEngine | None = None,
        budget: BudgetManager | None = None,
        hooks: HookRegistry | None = None,
        checkpointer: CheckpointStore | None = None,
        config: LoopConfig | None = None,
    ) -> None: ...

    async def run(self, task: str, thread_id: ThreadId | None = None, context: dict | None = None) -> RunResult: ...
    async def stream(self, task: str, thread_id: ThreadId | None = None) -> AsyncIterator[StreamEvent]: ...
    async def step(self, state: MoriState) -> tuple[StepResult, MoriState]: ...
    async def pause(self, run_id: RunId) -> CheckpointId: ...
    async def resume(self, thread_id: ThreadId, input: dict | None = None) -> RunResult: ...
    async def cancel(self, run_id: RunId) -> None: ...
```

All modules are optional except `model` and `tools`. When a module is None, the loop skips phases that depend on it. An agent with just a model and tools is a basic ReAct loop. Adding memory, skills, permissions, and budget progressively enriches the loop.

## 5. Configuration

```python
class LoopConfig(MoriModel):
    max_steps: int = 50
    max_total_tokens: int = 2_000_000
    step_timeout_sec: float = 120.0
    run_timeout_sec: float = 3600.0
    idle_timeout_sec: float = 300.0
    max_retries_per_tool: int = 2
    retry_backoff_base_sec: float = 1.0
    checkpoint_interval_steps: int = 10
    max_recursion_depth: int = 3
```

## 6. Loop Implementation

```python
async def run(self, task, thread_id=None, context=None) -> RunResult:
    state = self._init_state(task, thread_id, context)

    # Restore from checkpoint if thread exists
    if self.checkpointer and thread_id:
        saved = await self.checkpointer.load_latest(thread_id)
        if saved:
            state = MoriState(**saved.state)

    # turn.start fires before any model work. HookBlock here exits early.
    if self.hooks:
        payload = TurnStartPayload(
            thread_id=state.thread_id, run_id=state.run_id, input=task,
            is_resume=False, paused_tool_call=None, state=state,
        )
        try:
            payload = await self.hooks.dispatch_before(HookEvents.TURN_START, payload)
            task = payload.input  # honor mutations to input
        except HookBlock as block:
            state.status = RunStatus.BLOCKED
            state.blocked_reason = block.reason
            return await self._finalize_turn(state, TurnEndReason.BLOCKED)

    await self._emit(RunStartEvent(run_id=state.run_id, task=task))

    while state.status == RunStatus.RUNNING:
        try:
            step_result = await self._execute_step(state)
        except HookBlock as block:
            state.status = RunStatus.BLOCKED
            state.blocked_reason = block.reason
            break
        state.step_count += 1

        # Auto-checkpoint
        if self.checkpointer and state.step_count % self.config.checkpoint_interval_steps == 0:
            await self.checkpointer.save(state)

        # Check termination
        if self._should_terminate(state, step_result):
            break

    # Final checkpoint
    if self.checkpointer:
        await self.checkpointer.save(state)

    await self._emit(RunEndEvent(run_id=state.run_id, status=state.status))
    return await self._finalize_turn(state, self._turn_end_reason_for(state))


async def _finalize_turn(self, state: MoriState, reason: TurnEndReason) -> RunResult:
    """Fire turn.end with the canonical reason; honor HookBlock/HookRetry."""
    result = RunResult.from_state(state)
    if not self.hooks:
        return result

    payload = TurnEndPayload(
        thread_id=state.thread_id, run_id=state.run_id, reason=reason,
        state=state, result=result,
        paused_prompt=state.paused_prompt if reason == TurnEndReason.AWAIT_USER else None,
    )
    try:
        payload = await self.hooks.dispatch_before(HookEvents.TURN_END, payload)
        return payload.result
    except HookBlock as block:
        # Convert any non-blocked outcome into BLOCKED before returning
        result.status = RunStatus.BLOCKED
        result.blocked_reason = block.reason
        return result
    except HookRetry as retry:
        # Only valid when reason ∈ {COMPLETED, EXHAUSTED}. Re-enter the loop
        # with feedback appended as a system message.
        if reason not in (TurnEndReason.COMPLETED, TurnEndReason.EXHAUSTED):
            log.error("hook.retry_misuse", event=HookEvents.TURN_END, reason=reason)
            return result
        state.messages.append(Message(role="system", content=retry.feedback))
        state.status = RunStatus.RUNNING
        return await self._run_from_state(state)
```

The `_finalize_turn` helper fires `turn.end` exactly once per `run()` or `resume()` call regardless of exit reason. It is the single point where `HookBlock` or `HookRetry` can change the result before it returns to the caller.

## 7. Phase Implementations

### 7.1 Retrieve

Runs if memory or skills are configured. Assembles contextual input.

```python
async def _phase_retrieve(self, state: MoriState) -> None:
    if self.budget:
        allocations = self.budget.rebalance(phase=Phase.RETRIEVE)

    if self.memory:
        max_tokens = allocations["memory"].allocated if self.budget else 2000
        state.memory_slice = await self.memory.read(
            query=state.task,
            max_tokens=max_tokens,
        )

    if self.skills and not state.active_skill:
        candidates = await self.skills.discover(
            state.task,
            available_tools=self.tools.list_specs(),
        )
        if candidates:
            payload = await self.skills.load(candidates[0].manifest.skill_id)
            state.active_skill = await self.skills.bind(
                payload, self.tools.list_specs()
            )
```

### 7.2 Plan

Calls the model with assembled context. The `model.request.before` hook may transform the request, block it (`HookBlock` → exit loop with `BLOCKED`), or force a retry (`HookRetry` → append feedback and re-enter Plan).

```python
async def _phase_plan(self, state: MoriState) -> ModelResponse:
    messages = self._assemble_messages(state)
    tools = self.tools.list_specs()
    request = ModelRequest(messages=messages, tools=tools)

    if self.hooks:
        try:
            request = await self.hooks.dispatch_before("model.request.before", request)
        except HookRetry as retry:
            state.messages.append(Message(role="system", content=retry.feedback))
            return await self._phase_plan(state)  # re-enter with feedback
        # HookBlock propagates up to the loop, which sets status=BLOCKED

    response = await self.model.invoke(request)
    if self.hooks:
        await self.hooks.dispatch_after("model.response.after", response)

    state.messages.append(response.message)
    state.total_input_tokens += response.usage.input_tokens
    state.total_output_tokens += response.usage.output_tokens
    return response
```

### 7.3 Validate

Runs if permission engine is configured and model proposed tool calls.

```python
async def _phase_validate(self, state: MoriState, tool_calls: list[ToolCall]) -> list[ToolCall]:
    if not self.permission:
        return tool_calls

    approved = []
    for call in tool_calls:
        call = await self.hooks.dispatch_before("tool.validate", call) if self.hooks else call
        result = await self.permission.check(ActionIntent(
            action_type="tool_call", tool_name=call.name,
        ))
        if result.decision == PermissionDecision.ALLOW:
            approved.append(call)
        elif result.decision == PermissionDecision.DENY:
            state.messages.append(Message(
                role="tool", content=f"DENIED: {result.reason}", tool_call_id=call.id,
            ))
        elif result.decision == PermissionDecision.ESCALATE:
            # Pause for human approval
            state.status = RunStatus.PAUSED
            if self.checkpointer:
                await self.checkpointer.save(state)
            return []  # Caller handles the pause
    return approved
```

### 7.4 Act

Executes approved tool calls through the tool registry. Two policy paths apply here:

- **`tool.invoke.before` may raise `HookBlock`.** The tool is not invoked; a synthetic result `"BLOCKED: {reason}"` is appended so the model sees its tool call was refused. The loop continues to the next tool call (other tools in the same response are not affected).
- **The `ask_user` native tool raises `YieldToUser` internally.** Caught here, it transitions the run to `PAUSED`, saves a checkpoint, and exits `_phase_act` cleanly. The caller resumes via `agent.resume(thread_id, user_response)`.

```python
async def _phase_act(self, state: MoriState, tool_calls: list[ToolCall]) -> list[ToolResult]:
    results = []
    for call in tool_calls:
        # tool.invoke.before may transform, block, or pass through
        if self.hooks:
            try:
                call = await self.hooks.dispatch_before("tool.invoke.before", call)
            except HookBlock as block:
                state.messages.append(Message(
                    role="tool",
                    content=f"BLOCKED: {block.reason}",
                    tool_call_id=call.id,
                ))
                state.total_tool_calls += 1
                continue

        try:
            result = await self.tools.invoke(call.name, call.arguments)
        except YieldToUser as yield_signal:
            # ask_user invoked — pause the run, save checkpoint, exit
            state.status = RunStatus.PAUSED
            state.paused_reason = "await_user_input"
            state.paused_prompt = yield_signal.question
            state.paused_tool_call = call
            if self.checkpointer:
                checkpoint_id = await self.checkpointer.save(state)
                state.last_checkpoint_id = checkpoint_id
            return results  # remaining tool calls in this response are skipped

        if self.hooks:
            await self.hooks.dispatch_after("tool.invoke.after", result)
        state.messages.append(Message(
            role="tool",
            content=result.content if isinstance(result.content, str) else str(result.content),
            tool_call_id=call.id,
        ))
        state.total_tool_calls += 1
        results.append(result)
    return results
```

**Note:** `tool.invoke.before` fires for `ask_user` like any other tool. An operator can `HookBlock` an `ask_user` call (e.g., refuse user prompts in autonomous batch contexts).

### 7.5 Observe, Evaluate, Update

```python
async def _phase_observe(self, state, results):
    """Write traces to working memory."""
    if self.memory:
        await self.memory.write([MemoryRecord(
            layer=MemoryLayer.WORKING,
            content=self._format_step_trace(state, results),
            ...
        )])

async def _phase_evaluate(self, state, response) -> StepOutcome:
    """Determine if the run should continue, complete, or fail."""
    if state.status == RunStatus.PAUSED:
        return StepOutcome.ESCALATE
    if not response.message.tool_calls:
        return StepOutcome.SUCCESS  # Model produced a final answer
    if self.control and not self.control.check_bounds(state).ok:
        return StepOutcome.FAILURE
    return StepOutcome.RETRY  # Continue the loop

async def _phase_update(self, state, step_outcome):
    """Update plan, emit events, record skill outcome."""
    if step_outcome == StepOutcome.SUCCESS:
        state.status = RunStatus.COMPLETED
    elif step_outcome == StepOutcome.FAILURE:
        state.status = RunStatus.FAILED
    state.last_progress_at = datetime.utcnow()
```

### 7.6 Resume

`agent.resume(thread_id, input)` is the entry point for continuing a paused run. It loads the most recent checkpoint, fires `turn.start` with `is_resume=True`, and — if the pause was due to `ask_user` — injects the caller's input as the tool result for the paused call before re-entering the loop.

```python
async def resume(self, thread_id: ThreadId, input: str | dict) -> RunResult:
    if not self.checkpointer:
        raise RuntimeError("resume requires a checkpointer")

    cp = await self.checkpointer.load_latest(thread_id)
    if not cp:
        raise RuntimeError(f"no checkpoint found for thread {thread_id}")

    state = MoriState(**cp.state)
    if state.status != RunStatus.PAUSED:
        raise RuntimeError(
            f"resume called on non-paused thread (status={state.status}); "
            f"check result.status before calling resume()"
        )

    input_text = input if isinstance(input, str) else input.get("text", "")

    # turn.start fires with is_resume=True and the in-flight tool call
    if self.hooks:
        payload = TurnStartPayload(
            thread_id=thread_id, run_id=state.run_id, input=input_text,
            is_resume=True, paused_tool_call=state.paused_tool_call, state=state,
        )
        try:
            payload = await self.hooks.dispatch_before(HookEvents.TURN_START, payload)
            input_text = payload.input
        except HookBlock as block:
            state.status = RunStatus.BLOCKED
            state.blocked_reason = block.reason
            # NB: paused_tool_call remains; caller can resume() again with different input
            return await self._finalize_turn(state, TurnEndReason.BLOCKED)

    # If paused on ask_user, satisfy the tool call with the user's response
    if state.paused_reason == "await_user_input" and state.paused_tool_call:
        state.messages.append(Message(
            role="tool",
            content=input_text,
            tool_call_id=state.paused_tool_call.id,
        ))
        state.paused_tool_call = None
        state.paused_reason = None
        state.paused_prompt = None
        state.status = RunStatus.RUNNING

    return await self._run_from_state(state)
```

**Edge cases:**

- `resume(thread_id, ...)` on a thread whose latest checkpoint has `status != PAUSED` raises `RuntimeError` with a clear message. Callers must check `result.status == PAUSED` before calling resume.
- If `turn.start` raises `HookBlock` on resume, the run ends `BLOCKED` and the paused `ask_user` call remains in the checkpoint — caller can resume again later with different input.
- The `ask_user` tool requires `checkpointer` configured. The builder enforces this at build time (`.ask_user()` without `.checkpointer(...)` raises `BuilderError`).

## 8. Streaming

```python
async def stream(self, task, thread_id=None) -> AsyncIterator[StreamEvent]:
    """Yields typed events at every phase boundary and for every tool call."""
    state = self._init_state(task, thread_id)
    yield StreamEvent(type="run.start", data={"run_id": state.run_id})

    while state.status == RunStatus.RUNNING:
        yield StreamEvent(type="step.start", data={"step": state.step_count})
        # ... run phases, yielding events for each ...
        yield StreamEvent(type="step.end", data={"outcome": outcome})

    yield StreamEvent(type="run.end", data={"status": state.status})

class StreamEvent(MoriModel):
    type: str
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

## 9. RunResult

```python
class RunResult(MoriModel):
    run_id: RunId
    thread_id: ThreadId
    status: RunStatus
    task: str
    final_output: str | None = None
    messages: list[Message]
    plan: PlanObject | None = None
    total_steps: int
    total_usage: TokenUsage
    total_tool_calls: int
    total_duration_ms: float
    checkpoint_id: CheckpointId | None = None

    # Chat mode (set when status == PAUSED, paused_reason == "await_user_input")
    paused_prompt: str | None = None

    # Active Hooks (set when status == BLOCKED via HookBlock)
    blocked_reason: str | None = None

class StepResult(MoriModel):
    step_id: StepId
    step_number: int
    outcome: StepOutcome
    response: ModelResponse | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    usage: TokenUsage
    duration_ms: float
```

## 10. Subagent Isolation

When the agent delegates work to a subagent (via A2A tool call or explicit spawning), the subagent runs in full isolation: its own MoriState, its own context window, its own compaction lifecycle. The parent never sees the subagent's full transcript. It receives only a summary result.

This serves two purposes: context management (the parent's context is not consumed by the subagent's potentially long conversation) and security (the subagent cannot leak context from the parent, and the parent cannot be poisoned by the subagent's raw outputs).

```python
class SubagentConfig(MoriModel):
    """Configuration for subagent delegation."""
    inherit_identity: bool = True           # Subagent gets parent's identity (cannot escalate)
    inherit_memory: bool = False            # Whether subagent can read parent's memory layers
    inherit_tools: bool = True              # Whether subagent gets parent's tool registry
    summary_max_tokens: int = 1000          # Max size of summary returned to parent
    max_steps: int = 30                     # Independent step limit
    max_total_tokens: int = 500_000         # Independent token budget
```

**Delegation flow:**

```
Parent AgentLoop
  │
  ├─ Plan phase: model requests subagent delegation
  ├─ Validate phase: permission check on agent resource (EXECUTE)
  ├─ Act phase:
  │   ├─ Create child MoriState (clean messages, fresh counters)
  │   ├─ Optionally copy tool registry (filtered by child's permissions)
  │   ├─ Run child AgentLoop to completion
  │   ├─ Extract summary from child's RunResult.final_output
  │   └─ Return summary as ToolResult to parent
  │       (child's full message history is NOT returned)
  └─ Observe phase: parent records summary in working memory
```

**Identity propagation:** the subagent inherits the parent's Identity and group memberships unless explicitly overridden. The Permission Engine checks the subagent's identity independently. A restricted parent cannot spawn an unrestricted subagent.

**Compaction isolation:** the subagent has its own BudgetManager and runs its own compaction pipeline. The parent's context is unaffected by the subagent's tool outputs.

## 11. ModelAdapter Interface

```python
class ModelAdapter(Protocol):
    """Abstraction over LLM provider APIs."""

    async def invoke(self, request: ModelRequest) -> ModelResponse:
        """Send a request and return a parsed response."""

    async def stream(self, request: ModelRequest) -> AsyncIterator[StreamChunk]:
        """Stream a response token by token."""

    async def count_tokens(self, text: str) -> int:
        """Count tokens for budget management."""

    @property
    def max_context_tokens(self) -> int:
        """Maximum context window for this model."""

    @property
    def model_id(self) -> str:
        """Model identifier string."""

    @property
    def supports_tool_use(self) -> bool:
        """Whether this model supports native tool calling."""

class StreamChunk(MoriModel):
    type: Literal["text_delta", "tool_call_start", "tool_call_delta", "tool_call_end", "usage"]
    text: str | None = None
    tool_call: ToolCall | None = None
    usage: TokenUsage | None = None
```

## 12. Anthropic Adapter

**Module:** `mori.model.anthropic`
**Dependency:** `anthropic` (optional: `pip install mori[anthropic]`)

```python
class AnthropicAdapter(ModelAdapter):
    """Wraps the Anthropic SDK for Claude models."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,        # Falls back to ANTHROPIC_API_KEY env var
        max_tokens: int = 4096,
        base_url: str | None = None,        # For proxies or custom endpoints
    ) -> None: ...
```

**Request conversion (Mori → Anthropic):**

| Mori ModelRequest field | Anthropic API parameter |
|------------------------|------------------------|
| messages (role="system") | `system` parameter (extracted, not in messages array) |
| messages (role="user/assistant/tool") | `messages` array |
| tools (list[ToolSpec]) | `tools` array with `input_schema` mapped to Anthropic format |
| max_tokens | `max_tokens` |
| temperature | `temperature` |
| stop_sequences | `stop_sequences` |

**Tool schema conversion:**

```python
# Mori ToolSpec:
ToolSpec(name="search", description="Search code", input_schema={"type": "object", "properties": {...}})

# Anthropic tool format:
{"name": "search", "description": "Search code", "input_schema": {"type": "object", "properties": {...}}}
```

Anthropic's format is nearly identical to Mori's ToolSpec, making conversion straightforward.

**Response conversion (Anthropic → Mori):**

| Anthropic response field | Mori ModelResponse field |
|-------------------------|-------------------------|
| `content` blocks (type="text") | `message.content` (concatenated text) |
| `content` blocks (type="tool_use") | `message.tool_calls` (list of ToolCall) |
| `usage.input_tokens` | `usage.input_tokens` |
| `usage.output_tokens` | `usage.output_tokens` |
| `stop_reason` | `stop_reason` mapped: "end_turn" → "end_turn", "tool_use" → "tool_use", "max_tokens" → "max_tokens" |

**Tool result format (Mori → Anthropic):**

When the runtime sends tool results back to the model, they are formatted as:
```python
# Mori Message(role="tool", content="result text", tool_call_id="toolu_123")

# Anthropic format:
{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_123", "content": "result text"}]}
```

Note: Anthropic nests tool results inside a user message with `tool_result` content blocks. The adapter handles this conversion transparently.

**Streaming support:**

The Anthropic adapter maps streaming events:

| Anthropic stream event | Mori StreamChunk type |
|-----------------------|----------------------|
| `content_block_delta` (type="text_delta") | `text_delta` |
| `content_block_start` (type="tool_use") | `tool_call_start` |
| `content_block_delta` (type="input_json_delta") | `tool_call_delta` |
| `content_block_stop` (after tool_use) | `tool_call_end` |
| `message_delta` (usage) | `usage` |

**Extended thinking support:**

For models that support extended thinking (e.g., `claude-sonnet-4-20250514` with `thinking` enabled), the adapter captures thinking blocks and includes them in `ModelResponse.raw["thinking"]` for observability without exposing them in the primary message content.

**Token counting:**

```python
async def count_tokens(self, text: str) -> int:
    """Uses anthropic.count_tokens() for exact counts."""
```

## 13. OpenAI Adapter

**Module:** `mori.model.openai`
**Dependency:** `openai` (optional: `pip install mori[openai]`)

```python
class OpenAIAdapter(ModelAdapter):
    """Wraps the OpenAI SDK. Compatible with OpenAI, Azure OpenAI, and any OpenAI-compatible API."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,       # For Azure, local models, etc.
        organization: str | None = None,
    ) -> None: ...
```

**Key differences from Anthropic:**
- System messages stay in the messages array (not extracted)
- Tool results use `role="tool"` directly (no nesting)
- Tool call IDs use `call_` prefix convention
- Streaming uses different event names (SSE chunks with `delta` fields)

## 14. Test Criteria

- [ ] A task with one tool call completes in the expected number of steps
- [ ] A task with no tool calls completes in a single step (model produces final answer)
- [ ] Step limit triggers FAILED status at exactly max_steps
- [ ] Cost limit triggers FAILED when cumulative tokens exceed ceiling
- [ ] Timeout triggers after wall-clock duration
- [ ] cancel() terminates at the next phase boundary
- [ ] pause() saves a checkpoint; resume() continues from it
- [ ] ESCALATE pauses the run and produces a checkpoint
- [ ] Denied tool calls inject denial messages into conversation
- [ ] `turn.start` fires at `run()` entry with `is_resume=False`
- [ ] `turn.start` fires at `resume()` entry with `is_resume=True` and `paused_tool_call` populated
- [ ] `turn.end` fires exactly once per `run()` or `resume()` call with correct `reason`
- [ ] `HookBlock` at `turn.start` exits the run with `RunResult.status=BLOCKED`
- [ ] `HookBlock` at `model.request.before` exits the loop with `RunStatus.BLOCKED`; model not invoked
- [ ] `HookBlock` at `tool.invoke.before` appends `"BLOCKED: ..."` tool result; loop continues to next call
- [ ] `HookBlock` at `turn.end` overwrites `result.status` to `BLOCKED` before returning
- [ ] `HookRetry` at `model.request.before` appends feedback as system message and re-enters Plan
- [ ] `HookRetry` at `turn.end` with `reason ∈ {COMPLETED, EXHAUSTED}` re-enters the loop with feedback
- [ ] `HookRetry` on unsupported events is logged at error and treated as `None`
- [ ] `ask_user` tool yields the agent: `RunStatus=PAUSED`, `paused_prompt` set, checkpoint saved
- [ ] `resume(thread_id, user_response)` injects the response as the paused tool result and continues
- [ ] `resume()` on a non-paused thread raises `RuntimeError` with a clear message
- [ ] `.ask_user()` on a builder without `.checkpointer()` raises `BuilderError` at build time
- [ ] `tool.invoke.before` fires for `ask_user` like any other tool (operator can block it)
- [ ] All modules are optional: model + tools alone produces a working ReAct loop
- [ ] stream() yields events at every phase boundary
- [ ] Hooks fire at the correct points with correct payloads
- [ ] AnthropicAdapter correctly converts system messages to the system parameter
- [ ] AnthropicAdapter correctly maps tool_use content blocks to ToolCall
- [ ] AnthropicAdapter correctly formats tool_result as nested user message
- [ ] AnthropicAdapter streaming produces correct StreamChunk sequence
- [ ] OpenAIAdapter correctly handles tool calls and tool results
- [ ] Both adapters handle API errors gracefully (rate limits, network failures)
- [ ] Both adapters report accurate token usage
- [ ] Subagent runs in isolated MoriState (parent messages not visible)
- [ ] Subagent returns only summary to parent (full transcript not leaked)
- [ ] Subagent inherits parent identity but cannot escalate privileges
- [ ] Subagent respects its own independent step and token limits
- [ ] Parent context is not consumed by subagent tool outputs
