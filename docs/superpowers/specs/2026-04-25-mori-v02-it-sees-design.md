# Mori v0.2 "It Sees" — Design Spec

**Goal:** Add CLI tools, MCP server integration, structured observability, resource control, and per-tool metrics to the working v0.1 agent.

**Depends on:** v0.1 complete (core types, native tool registry, Anthropic adapter, AgentLoop, builder API)

**Reference specs:** 05-TOOLS-AND-PROTOCOLS (sections 5-6, 9), 07-CONTROL (section 3), 08-OBSERVABILITY (sections 2-6)

---

## 1. Components

Five components, all integrated through the AgentLoop and exposed via the builder API:

| Component | Spec | What it does |
|-----------|------|-------------|
| CLI Runner | 05 §6 | Register shell commands as tools, execute as subprocesses |
| MCP Client | 05 §5 | Connect to MCP servers, discover and invoke remote tools |
| Observability Engine | 08 §2-6 | Structured events at every phase boundary, buffered dispatch to pluggable sinks |
| Control Bounds | 07 §3 | Single authority for all resource limits, retry logic with backoff |
| Error Rate Tracking | 05 §9 | Per-tool metrics wired into the registry and observability |

---

## 2. File Structure

### New files

```
mori/
├── protocols/
│   ├── __init__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── runner.py            # CLIRunner — subprocess execution
│   │   └── args.py              # Argument formatting (flags, positional, subcommand)
│   └── mcp/
│       ├── __init__.py
│       ├── client.py             # MCPClient — JSON-RPC 2.0 (SSE, stdio, HTTP)
│       └── schema_cache.py       # Schema caching with TTL
├── observability/
│   ├── __init__.py
│   ├── engine.py                 # ObservabilityEngine — buffered emit, trace context
│   ├── events.py                 # MoriEvent base + all event types
│   └── sinks/
│       ├── __init__.py
│       ├── stdout.py              # StdoutSink — formatted console
│       └── jsonl.py               # JsonlSink — JSONL file
├── control/
│   ├── __init__.py
│   └── bounds.py                  # ControlBounds, ControlConfig, BoundCheckResult, RetryDecision
```

### Modified files

- `mori/tools/registry.py` — add `register_cli()`, `register_mcp_server()`, metrics tracking, result truncation
- `mori/runtime/loop.py` — wire observability events, delegate limit checking to ControlBounds, retry logic, remove debug mode
- `mori/agent.py` — add `.cli()`, `.mcp_server()`, `.sink()` builder methods, wire ControlBounds and ObservabilityEngine
- `mori/types.py` — add any shared types needed across modules

---

## 3. CLI Runner

### CLIRunner (`protocols/cli/runner.py`)

Executes CLI tools as subprocesses via `anyio.run_process()`.

```python
class CLIRunner:
    async def run(self, command: str, arguments: dict, config: CLIToolConfig) -> ToolResult
```

### CLIToolConfig

```python
class CLIToolConfig(MoriModel):
    command: str                        # e.g. "rg", "git", "./deploy.sh"
    args_format: Literal["positional", "flags", "subcommand"] = "flags"
    shell: bool = False
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout_sec: float = 60.0
    max_output_bytes: int = 1_048_576   # 1MB cap
    capture_stderr: bool = True
```

### Argument Formatting (`protocols/cli/args.py`)

| Format | Input | Output |
|--------|-------|--------|
| flags | `{"pattern": "TODO", "path": "."}` | `rg --pattern TODO --path .` |
| positional | `{"0": "TODO", "1": "src/"}` | `rg TODO src/` |
| subcommand | `{"action": "status", "short": true}` | `git status --short` |

Boolean handling: `{"verbose": true}` → `--verbose` (present). `{"verbose": false}` → omitted.

### Return Mapping

- Exit code 0: `ToolResult(success=True, content=stdout)`
- Exit code non-zero: `ToolResult(success=False, content=stdout, error=stderr)`
- Timeout: `ToolResult(success=False, error="Process timed out after {timeout_sec}s")`
- Output exceeds `max_output_bytes`: truncated, stderr captured separately in `metadata`

### Security

- Arguments passed as a list to subprocess (no shell injection) when `shell=False`
- `shell=True` is opt-in. When used, a warning event is emitted via observability. No blocking (Permission Engine is v0.5).
- `timeout_sec` hard-kills the process if exceeded
- `max_output_bytes` prevents memory exhaustion

---

## 4. MCP Client

### MCPClient (`protocols/mcp/client.py`)

Native MCP client speaking JSON-RPC 2.0.

```python
class MCPClient:
    def __init__(self, name: str, url: str, transport: str, auth: AuthConfig | None = None) -> None
    async def connect(self) -> None
    async def discover_tools(self) -> list[ToolSpec]
    async def invoke(self, tool_name: str, arguments: dict) -> ToolResult
    async def health_check(self) -> HealthStatus
    async def close(self) -> None
```

### Transport Support

| Transport | Mechanism | Use Case | Build Order |
|-----------|-----------|----------|-------------|
| SSE | Server-Sent Events over HTTP | Long-lived remote servers | First |
| stdio | Subprocess stdin/stdout | Local tool servers | Second |
| HTTP | Stateless POST requests | Serverless, REST-style | Third |

All three transports are built. SSE is prioritized first as it's the most common deployment.

**SSE transport:** Uses `httpx` with SSE streaming. Persistent connection. Server pushes events, client sends requests via POST.

**stdio transport:** Spawns subprocess, communicates via stdin/stdout JSON-RPC messages.

**HTTP transport:** Stateless POST requests per call. Simplest transport.

### Schema Caching (`protocols/mcp/schema_cache.py`)

```python
class SchemaCache:
    def __init__(self, ttl_sec: float = 300.0) -> None
    def get(self, server_name: str) -> list[ToolSpec] | None
    def put(self, server_name: str, specs: list[ToolSpec]) -> None
    def is_stale(self, server_name: str) -> bool
    def invalidate(self, server_name: str) -> None
```

- Tool schemas cached after discovery. TTL default 300s.
- On invoke, if cache is stale, client re-discovers before calling.
- Arguments validated against cached schema before sending — `SchemaValidationError` on mismatch (no network call wasted).

### Registration Flow

`registry.register_mcp_server("github", url="...")`:
1. Creates `MCPClient` with SSE transport
2. Calls `connect()`, then `discover_tools()`
3. Registers each discovered tool as `RegisteredTool(source=MCP, fn=None, server_id="github")`
4. Returns list of registered `ToolId`s

On `registry.invoke(name, args)`, the registry routes MCP-sourced tools through the `MCPClient.invoke()` method.

---

## 5. Observability Engine

### ObservabilityEngine (`observability/engine.py`)

```python
class ObservabilityEngine:
    def __init__(self, sinks: list[EventSink], config: ObservabilityConfig) -> None
    async def emit(self, event: MoriEvent) -> None
    async def emit_batch(self, events: list[MoriEvent]) -> None
    def start_trace(self, run_id: RunId) -> TraceId
    def start_span(self, trace_id: TraceId, name: str, parent_span_id: str | None = None) -> SpanContext
    def end_span(self, span: SpanContext) -> None
    def get_run_summary(self, run_id: RunId) -> RunSummary
    async def flush(self) -> None
    async def close(self) -> None
```

### Buffered Pipeline

Events are pushed to an internal buffer. Flushed to all sinks when:

- Buffer hits `buffer_size` (default 100)
- `flush_interval_sec` elapses (default 5.0s)
- `flush()` or `close()` is called explicitly
- Run ends (flush-on-shutdown per AIUC-1 contract)

The flush timer runs as a background `anyio` task, started on engine init, cancelled on close.

### ObservabilityConfig

```python
class ObservabilityConfig(MoriModel):
    buffer_size: int = 100
    flush_interval_sec: float = 5.0
    include_model_io: bool = False
    include_tool_args: bool = True
    include_tool_results: bool = True
    max_content_length: int = 10_000
    enabled_event_types: list[str] | None = None   # None = all
```

### Event Taxonomy (`observability/events.py`)

All events inherit from `MoriEvent`:

```python
class MoriEvent(MoriModel):
    event_id: str
    event_type: str
    timestamp: datetime
    run_id: RunId
    step_id: StepId | None = None
    trace_id: TraceId | None = None
    span_id: str | None = None
    risk_flags: list[str] = Field(default_factory=list)   # AIUC-1 requirement
    metadata: dict = Field(default_factory=dict)
```

**Loop events:**
- `RunStartEvent` — `event_type="run.start"`, task, config
- `RunEndEvent` — `event_type="run.end"`, status, total_steps, tokens, duration
- `StepStartEvent` — `event_type="step.start"`, step_number, phase
- `StepEndEvent` — `event_type="step.end"`, step_number, outcome, tokens, duration, phase_timings

**Tool events:**
- `ToolInvokeEvent` — `event_type="tool.invoke"`, tool_name, source, server_id, arguments
- `ToolResultEvent` — `event_type="tool.result"`, tool_name, success, latency_ms, error, result_preview

**Control events:**
- `BoundViolationEvent` — `event_type="control.bound_violation"`, bound_name, current_value, limit_value

### Trace Context

```python
class SpanContext(MoriModel):
    trace_id: TraceId
    span_id: str
    parent_span_id: str | None = None
    name: str
    start_time: datetime
    end_time: datetime | None = None

    @property
    def duration_ms(self) -> float | None
```

### EventSink Protocol

```python
class EventSink(Protocol):
    async def write(self, event: MoriEvent) -> None
    async def write_batch(self, events: list[MoriEvent]) -> None
    async def flush(self) -> None
    async def close(self) -> None
```

**StdoutSink** (`sinks/stdout.py`): Formatted console output. Replaces the v0.1 `debug=True` mode.

**JsonlSink** (`sinks/jsonl.py`): One JSON object per line, written to a file path. Uses synchronous buffered IO (file opened on init, line written per event, flushed on `flush()`/`close()`).

### RunSummary

```python
class RunSummary(MoriModel):
    run_id: RunId
    status: RunStatus
    total_steps: int
    total_input_tokens: int
    total_output_tokens: int
    total_tool_calls: int
    total_tool_failures: int
    total_duration_ms: float
    avg_step_duration_ms: float
    tools_used: list[str]
    error_summary: list[str]
```

---

## 6. Control Bounds

### ControlBounds (`control/bounds.py`)

Single authority for all resource limits. Replaces the current `_should_terminate()` logic in `AgentLoop`.

```python
class ControlBounds:
    def __init__(self, config: ControlConfig) -> None
    def check_bounds(self, state: MoriState) -> BoundCheckResult
    def should_retry(self, error: Exception, attempt: int) -> RetryDecision
    def record_progress(self) -> None   # Resets the idle timer (called when a step makes progress)
```

### ControlConfig

```python
class ControlConfig(MoriModel):
    max_steps: int = 50
    max_total_tokens: int = 2_000_000
    step_timeout_sec: float = 120.0
    run_timeout_sec: float = 3600.0
    idle_timeout_sec: float = 300.0
    max_retries_per_tool: int = 2
    retry_backoff_base_sec: float = 1.0
```

### BoundCheckResult

```python
class BoundCheckResult(MoriModel):
    ok: bool
    violated_bounds: list[str] = Field(default_factory=list)
    current_values: dict[str, float] = Field(default_factory=dict)
```

### RetryDecision

```python
class RetryDecision(MoriModel):
    should_retry: bool
    wait_sec: float = 0.0
    attempt: int = 0
```

**Backoff formula:** `retry_backoff_base_sec * 2^attempt`, capped at 60s.

### Loop Integration

Each step in the loop:
1. Calls `control.check_bounds(state)` before `_phase_plan`
2. If `not result.ok` → sets `state.status = FAILED`, emits `BoundViolationEvent`, breaks
3. On tool failure in `_phase_act` → calls `control.should_retry(error, attempt)`
4. If retry → waits backoff, re-invokes
5. If no retry → injects error message into conversation as before

---

## 7. Error Rate Tracking

### ToolMetrics

```python
class ToolMetrics(MoriModel):
    tool_id: ToolId
    total_calls: int = 0
    total_errors: int = 0
    avg_latency_ms: float = 0.0
    last_error: str | None = None
    last_called: datetime | None = None

    @property
    def error_rate(self) -> float:
        return self.total_errors / self.total_calls if self.total_calls > 0 else 0.0
```

Tracked inside `ToolRegistry.invoke()`:
- Increments `total_calls` on every invoke
- Increments `total_errors` on failure
- Simple running average `avg_latency_ms` (total_latency / total_calls)
- Updates `last_error`, `last_called`

Accessible via `registry.get_metrics(tool_id)`. Included in `ToolResultEvent.metadata`.

### Result Truncation

After invoke, if `content` exceeds `max_result_tokens` (default 4000 tokens, approximated as chars/4), truncate and append:

```
\n[TRUNCATED: output exceeded {max_result_tokens} tokens]
```

This prevents verbose tool output (e.g., CLI dumping a large file) from consuming disproportionate context.

---

## 8. Builder API Changes

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")

    # Native tools (existing)
    .tool(read_file, description="Read a file")

    # CLI tools (new)
    .cli("rg", command="rg", description="Search with ripgrep", args_format="flags")
    .cli("git", command="git", description="Run git commands", args_format="subcommand")

    # MCP servers (new)
    .mcp_server("filesystem", url="http://localhost:3000")

    # Observability sinks (new)
    .sink("stdout")
    .sink("jsonl", path="./traces.jsonl")

    # Config — now feeds both LoopConfig and ControlConfig
    .config(max_steps=20, max_total_tokens=500_000, idle_timeout_sec=120)

    .build()
)
```

### Startup Sequence (in `build()`)

1. Create `ObservabilityEngine` with configured sinks (first — everything else emits events)
2. Create `ControlBounds` from config values
3. Create `ToolRegistry`, register native tools, register CLI tools
4. Connect MCP servers (async — `build()` remains sync, MCP connection happens on first `run()` or via an explicit `await agent.connect()`)
5. Create `AgentLoop` with model, tools, observability, control
6. Return `Mori` instance

### MCP Connection Timing

`build()` is synchronous. MCP servers require async connection. Two options handled:
- Lazy connect: MCP client connects on first `invoke()` call. Simple, no API change.
- Explicit: User calls `await agent.connect()` before `run()`. Fails fast if server is down.

Both are supported. Lazy connect is the default.

---

## 9. What Gets Replaced

| v0.1 | v0.2 |
|------|------|
| `LoopConfig.debug` + `_log()` method | `StdoutSink` via ObservabilityEngine |
| `_should_terminate()` internal logic | `ControlBounds.check_bounds()` |
| Hardcoded step/token checks in loop | Moved to `ControlBounds` |

The `debug` flag and `_log()` method are removed from `loop.py`. Users who want debug output use `.sink("stdout")`.

---

## 10. v0.2 Exit Test

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(read_file, description="Read a file")
    .cli("rg", command="rg", description="Search with ripgrep", args_format="flags",
         args_schema={"pattern": {"type": "string"}, "path": {"type": "string", "default": "."}})
    .sink("jsonl", path="./traces.jsonl")
    .config(max_steps=20)
    .build()
)
result = await agent.run("Search for 'TODO' in the current directory and read the first match")
assert result.status == "completed" and result.total_tool_calls >= 2

events = load_jsonl("./traces.jsonl")
assert any(e["event_type"] == "tool.invoke" for e in events)
```

---

## 11. Parallelization

Within v0.2, these pairs can be built in parallel:

- **CLI Runner** || **MCP Client** — independent tool sources, no shared code
- **Observability events/sinks** || **Control Bounds** — independent modules

Error Rate Tracking depends on the registry changes and observability events, so it comes after both.
