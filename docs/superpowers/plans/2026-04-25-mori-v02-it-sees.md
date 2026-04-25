# Mori v0.2 "It Sees" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CLI tools, MCP server integration, structured observability with buffered sinks, resource control bounds, and per-tool error metrics to the working v0.1 agent.

**Architecture:** Five independent modules (CLI runner, MCP client, observability engine, control bounds, error metrics) are built and tested in isolation, then integrated through the AgentLoop and exposed via the builder API. The observability engine replaces v0.1's debug mode. ControlBounds replaces the loop's inline limit checking. The registry gains routing for CLI and MCP tool sources.

**Tech Stack:** Python 3.11+, pydantic v2, httpx (MCP SSE/HTTP), anyio (subprocess, background tasks), structlog, pytest + pytest-asyncio

---

## File Structure

### New files

```
mori/
├── observability/
│   ├── __init__.py
│   ├── events.py               # MoriEvent base + all event subtypes + SpanContext + EventSink protocol
│   ├── engine.py               # ObservabilityEngine — buffered emit, trace context, run summary
│   └── sinks/
│       ├── __init__.py
│       ├── stdout.py            # StdoutSink — formatted console output
│       └── jsonl.py             # JsonlSink — JSONL file sink
├── control/
│   ├── __init__.py
│   └── bounds.py                # ControlBounds, ControlConfig, BoundCheckResult, RetryDecision
├── protocols/
│   ├── __init__.py
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── args.py              # format_flags(), format_positional(), format_subcommand()
│   │   └── runner.py            # CLIRunner, CLIToolConfig
│   └── mcp/
│       ├── __init__.py
│       ├── schema_cache.py      # SchemaCache with TTL
│       └── client.py            # MCPClient — SSE, stdio, HTTP transports
tests/
├── test_events.py
├── test_observability.py
├── test_control.py
├── test_cli_args.py
├── test_cli_runner.py
├── test_schema_cache.py
├── test_mcp_client.py
├── test_metrics.py
├── test_registry_v02.py
├── test_loop_v02.py
├── test_builder_v02.py
└── test_integration_v02.py
```

### Modified files

- `mori/tools/registry.py` — add register_cli(), register_mcp_server(), metrics, truncation, MCP routing
- `mori/runtime/loop.py` — wire observability + control bounds, remove debug mode
- `mori/agent.py` — add .cli(), .mcp_server(), .sink() builder methods
- `mori/types.py` — add HealthStatus, AuthConfig, ServerUnavailable error

---

## Task 1: Observability Event Types

**Files:**
- Create: `mori/observability/__init__.py`
- Create: `mori/observability/events.py`
- Test: `tests/test_events.py`

- [ ] **Step 1: Write failing tests for event types**

Create `tests/test_events.py`:

```python
"""Tests for observability event types."""

from datetime import datetime, timezone
from typing import Protocol, runtime_checkable

from mori.observability.events import (
    MoriEvent,
    RunStartEvent,
    RunEndEvent,
    StepStartEvent,
    StepEndEvent,
    ToolInvokeEvent,
    ToolResultEvent,
    BoundViolationEvent,
    SpanContext,
    EventSink,
    ObservabilityConfig,
    RunSummary,
)
from mori.types import RunId, RunStatus, StepId, StepOutcome, Phase, ToolSource, TraceId


def test_mori_event_base():
    e = MoriEvent(
        event_id="evt_1",
        event_type="test",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
    )
    assert e.event_type == "test"
    assert e.risk_flags == []
    assert e.metadata == {}
    assert e.step_id is None
    assert e.trace_id is None


def test_run_start_event():
    e = RunStartEvent(
        event_id="evt_1",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        task="test task",
        config={"max_steps": 50},
    )
    assert e.event_type == "run.start"
    assert e.task == "test task"


def test_run_end_event():
    e = RunEndEvent(
        event_id="evt_2",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        status=RunStatus.COMPLETED,
        total_steps=3,
        total_input_tokens=500,
        total_output_tokens=200,
        duration_ms=1500.0,
    )
    assert e.event_type == "run.end"
    assert e.status == RunStatus.COMPLETED


def test_step_start_event():
    e = StepStartEvent(
        event_id="evt_3",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        step_id=StepId("step_1"),
        step_number=1,
        phase=Phase.PLAN,
    )
    assert e.event_type == "step.start"
    assert e.step_number == 1


def test_step_end_event():
    e = StepEndEvent(
        event_id="evt_4",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        step_id=StepId("step_1"),
        step_number=1,
        outcome=StepOutcome.SUCCESS,
        input_tokens=100,
        output_tokens=50,
        duration_ms=300.0,
    )
    assert e.event_type == "step.end"
    assert e.phase_timings == {}


def test_tool_invoke_event():
    e = ToolInvokeEvent(
        event_id="evt_5",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        tool_name="add",
        source=ToolSource.NATIVE,
        arguments={"a": 1, "b": 2},
    )
    assert e.event_type == "tool.invoke"
    assert e.server_id is None


def test_tool_result_event():
    e = ToolResultEvent(
        event_id="evt_6",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        tool_name="add",
        success=True,
        latency_ms=5.0,
    )
    assert e.event_type == "tool.result"
    assert e.error is None


def test_bound_violation_event():
    e = BoundViolationEvent(
        event_id="evt_7",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        bound_name="max_steps",
        current_value=51.0,
        limit_value=50.0,
    )
    assert e.event_type == "control.bound_violation"


def test_span_context():
    s = SpanContext(
        trace_id=TraceId("trace_1"),
        span_id="span_1",
        name="plan_phase",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
    )
    assert s.duration_ms is not None
    assert abs(s.duration_ms - 1000.0) < 1.0


def test_span_context_no_end():
    s = SpanContext(
        trace_id=TraceId("trace_1"),
        span_id="span_1",
        name="ongoing",
        start_time=datetime.now(timezone.utc),
    )
    assert s.duration_ms is None


def test_event_json_roundtrip():
    e = ToolInvokeEvent(
        event_id="evt_1",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        tool_name="search",
        source=ToolSource.CLI,
        arguments={"pattern": "TODO"},
    )
    json_str = e.model_dump_json()
    restored = ToolInvokeEvent.model_validate_json(json_str)
    assert restored.tool_name == "search"
    assert restored.source == ToolSource.CLI


def test_event_sink_is_protocol():
    assert hasattr(EventSink, "__protocol_attrs__") or callable(getattr(EventSink, "_is_protocol", None))


def test_observability_config_defaults():
    c = ObservabilityConfig()
    assert c.buffer_size == 100
    assert c.flush_interval_sec == 5.0
    assert c.include_tool_args is True
    assert c.enabled_event_types is None


def test_run_summary():
    s = RunSummary(
        run_id=RunId("run_1"),
        status=RunStatus.COMPLETED,
        total_steps=3,
        total_input_tokens=500,
        total_output_tokens=200,
        total_tool_calls=2,
        total_tool_failures=0,
        total_duration_ms=1500.0,
        avg_step_duration_ms=500.0,
        tools_used=["add", "multiply"],
        error_summary=[],
    )
    assert s.total_tool_failures == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement event types**

Create `mori/observability/__init__.py`:

```python
"""Structured observability for the Mori runtime."""
```

Create `mori/observability/events.py`:

```python
"""Event taxonomy, sink protocol, and trace context for Mori observability."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from mori.types import (
    MoriModel,
    Phase,
    RunId,
    RunStatus,
    StepId,
    StepOutcome,
    ToolSource,
    TraceId,
)


# ── Base Event ───────────────��───────────────────────────────

class MoriEvent(MoriModel):
    event_id: str
    event_type: str
    timestamp: datetime
    run_id: RunId
    step_id: StepId | None = None
    trace_id: TraceId | None = None
    span_id: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Loop Events ────────────���─────────────────────────────────

class RunStartEvent(MoriEvent):
    event_type: str = "run.start"
    task: str
    config: dict[str, Any] = Field(default_factory=dict)


class RunEndEvent(MoriEvent):
    event_type: str = "run.end"
    status: RunStatus
    total_steps: int
    total_input_tokens: int
    total_output_tokens: int
    duration_ms: float


class StepStartEvent(MoriEvent):
    event_type: str = "step.start"
    step_number: int
    phase: Phase


class StepEndEvent(MoriEvent):
    event_type: str = "step.end"
    step_number: int
    outcome: StepOutcome
    input_tokens: int
    output_tokens: int
    duration_ms: float
    phase_timings: dict[str, float] = Field(default_factory=dict)


# ── Tool Events ──────────────────────────────────────────────

class ToolInvokeEvent(MoriEvent):
    event_type: str = "tool.invoke"
    tool_name: str
    source: ToolSource
    server_id: str | None = None
    arguments: dict[str, Any] | None = None


class ToolResultEvent(MoriEvent):
    event_type: str = "tool.result"
    tool_name: str
    success: bool
    latency_ms: float
    error: str | None = None
    result_preview: str | None = None


# ── Control Events ────────────────���──────────────────────────

class BoundViolationEvent(MoriEvent):
    event_type: str = "control.bound_violation"
    bound_name: str
    current_value: float
    limit_value: float


# ── Trace Context ──────────────��───────────────────────────���─

class SpanContext(MoriModel):
    trace_id: TraceId
    span_id: str
    parent_span_id: str | None = None
    name: str
    start_time: datetime
    end_time: datetime | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds() * 1000


# ── Sink Protocol ─────────────────���──────────────────────────

@runtime_checkable
class EventSink(Protocol):
    async def write(self, event: MoriEvent) -> None: ...
    async def write_batch(self, events: list[MoriEvent]) -> None: ...
    async def flush(self) -> None: ...
    async def close(self) -> None: ...


# ── Config ───────────────────────────────────────────────────

class ObservabilityConfig(MoriModel):
    buffer_size: int = 100
    flush_interval_sec: float = 5.0
    include_model_io: bool = False
    include_tool_args: bool = True
    include_tool_results: bool = True
    max_content_length: int = 10_000
    enabled_event_types: list[str] | None = None


# ── Run Summary ──────────────���───────────────────────────────

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
    tools_used: list[str] = Field(default_factory=list)
    error_summary: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_events.py -v`
Expected: all 15 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/observability/__init__.py mori/observability/events.py tests/test_events.py
git commit -m "feat: observability event types, sink protocol, span context"
```

---

## Task 2: Control Bounds

**Files:**
- Create: `mori/control/__init__.py`
- Create: `mori/control/bounds.py`
- Test: `tests/test_control.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_control.py`:

```python
"""Tests for ControlBounds — resource limits and retry logic."""

import time
from datetime import datetime, timezone

from mori.control.bounds import (
    BoundCheckResult,
    ControlBounds,
    ControlConfig,
    RetryDecision,
)
from mori.runtime.state import MoriState
from mori.types import Message, RunId, RunStatus, ThreadId


def _make_state(**overrides) -> MoriState:
    defaults = {
        "run_id": RunId("run_test"),
        "thread_id": ThreadId("thread_test"),
        "task": "test",
        "status": RunStatus.RUNNING,
        "started_at": datetime.now(timezone.utc),
        "last_progress_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return MoriState(**defaults)


def test_config_defaults():
    c = ControlConfig()
    assert c.max_steps == 50
    assert c.max_total_tokens == 2_000_000
    assert c.idle_timeout_sec == 300.0
    assert c.max_retries_per_tool == 2


def test_check_bounds_ok():
    bounds = ControlBounds(config=ControlConfig())
    state = _make_state(step_count=5, total_input_tokens=100, total_output_tokens=50)
    result = bounds.check_bounds(state)
    assert result.ok is True
    assert result.violated_bounds == []


def test_check_bounds_step_limit():
    bounds = ControlBounds(config=ControlConfig(max_steps=10))
    state = _make_state(step_count=10)
    result = bounds.check_bounds(state)
    assert result.ok is False
    assert "max_steps" in result.violated_bounds


def test_check_bounds_token_limit():
    bounds = ControlBounds(config=ControlConfig(max_total_tokens=1000))
    state = _make_state(total_input_tokens=600, total_output_tokens=500)
    result = bounds.check_bounds(state)
    assert result.ok is False
    assert "max_total_tokens" in result.violated_bounds


def test_check_bounds_run_timeout():
    bounds = ControlBounds(config=ControlConfig(run_timeout_sec=0.001))
    state = _make_state(
        started_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    result = bounds.check_bounds(state)
    assert result.ok is False
    assert "run_timeout" in result.violated_bounds


def test_check_bounds_idle_timeout():
    bounds = ControlBounds(config=ControlConfig(idle_timeout_sec=0.001))
    state = _make_state(
        last_progress_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    result = bounds.check_bounds(state)
    assert result.ok is False
    assert "idle_timeout" in result.violated_bounds


def test_check_bounds_reports_current_values():
    bounds = ControlBounds(config=ControlConfig(max_steps=10))
    state = _make_state(step_count=12)
    result = bounds.check_bounds(state)
    assert result.current_values["step_count"] == 12


def test_should_retry_first_attempt():
    bounds = ControlBounds(config=ControlConfig(max_retries_per_tool=3, retry_backoff_base_sec=1.0))
    decision = bounds.should_retry(ValueError("fail"), attempt=0)
    assert decision.should_retry is True
    assert decision.wait_sec == 1.0
    assert decision.attempt == 0


def test_should_retry_backoff():
    bounds = ControlBounds(config=ControlConfig(max_retries_per_tool=3, retry_backoff_base_sec=1.0))
    d1 = bounds.should_retry(ValueError("fail"), attempt=1)
    assert d1.wait_sec == 2.0
    d2 = bounds.should_retry(ValueError("fail"), attempt=2)
    assert d2.wait_sec == 4.0


def test_should_retry_exhausted():
    bounds = ControlBounds(config=ControlConfig(max_retries_per_tool=2))
    decision = bounds.should_retry(ValueError("fail"), attempt=2)
    assert decision.should_retry is False


def test_should_retry_backoff_capped():
    bounds = ControlBounds(config=ControlConfig(max_retries_per_tool=20, retry_backoff_base_sec=1.0))
    decision = bounds.should_retry(ValueError("fail"), attempt=10)
    assert decision.wait_sec <= 60.0


def test_record_progress():
    bounds = ControlBounds(config=ControlConfig(idle_timeout_sec=1000))
    state = _make_state(last_progress_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    # Before recording progress, idle timeout should fire
    result = bounds.check_bounds(state)
    assert result.ok is False
    # Record progress resets the reference time
    bounds.record_progress()
    state.last_progress_at = datetime.now(timezone.utc)
    result2 = bounds.check_bounds(state)
    assert result2.ok is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_control.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ControlBounds**

Create `mori/control/__init__.py`:

```python
"""Resource bounds and retry logic."""
```

Create `mori/control/bounds.py`:

```python
"""ControlBounds — single authority for all resource limits."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from pydantic import Field

from mori.runtime.state import MoriState
from mori.types import MoriModel


class ControlConfig(MoriModel):
    max_steps: int = 50
    max_total_tokens: int = 2_000_000
    step_timeout_sec: float = 120.0
    run_timeout_sec: float = 3600.0
    idle_timeout_sec: float = 300.0
    max_retries_per_tool: int = 2
    retry_backoff_base_sec: float = 1.0


class BoundCheckResult(MoriModel):
    ok: bool
    violated_bounds: list[str] = Field(default_factory=list)
    current_values: dict[str, float] = Field(default_factory=dict)


class RetryDecision(MoriModel):
    should_retry: bool
    wait_sec: float = 0.0
    attempt: int = 0


class ControlBounds:
    """Single authority for all resource limits."""

    def __init__(self, config: ControlConfig) -> None:
        self._config = config
        self._last_progress = time.monotonic()

    def check_bounds(self, state: MoriState) -> BoundCheckResult:
        """Check all resource bounds against current state."""
        violated: list[str] = []
        values: dict[str, float] = {}
        now = datetime.now(timezone.utc)

        # Step limit
        values["step_count"] = float(state.step_count)
        if state.step_count >= self._config.max_steps:
            violated.append("max_steps")

        # Token limit
        total_tokens = state.total_input_tokens + state.total_output_tokens
        values["total_tokens"] = float(total_tokens)
        if total_tokens >= self._config.max_total_tokens:
            violated.append("max_total_tokens")

        # Run timeout
        run_elapsed = (now - state.started_at).total_seconds()
        values["run_elapsed_sec"] = run_elapsed
        if run_elapsed >= self._config.run_timeout_sec:
            violated.append("run_timeout")

        # Idle timeout
        idle_elapsed = (now - state.last_progress_at).total_seconds()
        values["idle_elapsed_sec"] = idle_elapsed
        if idle_elapsed >= self._config.idle_timeout_sec:
            violated.append("idle_timeout")

        return BoundCheckResult(
            ok=len(violated) == 0,
            violated_bounds=violated,
            current_values=values,
        )

    def should_retry(self, error: Exception, attempt: int) -> RetryDecision:
        """Decide whether to retry a failed tool call."""
        if attempt >= self._config.max_retries_per_tool:
            return RetryDecision(should_retry=False, attempt=attempt)

        wait = self._config.retry_backoff_base_sec * (2 ** attempt)
        wait = min(wait, 60.0)

        return RetryDecision(should_retry=True, wait_sec=wait, attempt=attempt)

    def record_progress(self) -> None:
        """Reset the idle timer."""
        self._last_progress = time.monotonic()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_control.py -v`
Expected: all 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/control/__init__.py mori/control/bounds.py tests/test_control.py
git commit -m "feat: ControlBounds — resource limits, retry backoff, idle detection"
```

---

## Task 3: CLI Argument Formatting

**Files:**
- Create: `mori/protocols/__init__.py`
- Create: `mori/protocols/cli/__init__.py`
- Create: `mori/protocols/cli/args.py`
- Test: `tests/test_cli_args.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cli_args.py`:

```python
"""Tests for CLI argument formatting."""

from mori.protocols.cli.args import format_args


def test_flags_basic():
    result = format_args({"pattern": "TODO", "path": "."}, format="flags")
    assert result == ["--pattern", "TODO", "--path", "."]


def test_flags_boolean_true():
    result = format_args({"verbose": True}, format="flags")
    assert result == ["--verbose"]


def test_flags_boolean_false():
    result = format_args({"verbose": False}, format="flags")
    assert result == []


def test_flags_mixed():
    result = format_args({"pattern": "TODO", "verbose": True, "quiet": False}, format="flags")
    assert "--pattern" in result
    assert "TODO" in result
    assert "--verbose" in result
    assert "--quiet" not in result


def test_positional_basic():
    result = format_args({"0": "TODO", "1": "src/"}, format="positional")
    assert result == ["TODO", "src/"]


def test_positional_ordering():
    result = format_args({"2": "c", "0": "a", "1": "b"}, format="positional")
    assert result == ["a", "b", "c"]


def test_subcommand_basic():
    result = format_args({"action": "status"}, format="subcommand")
    assert result == ["status"]


def test_subcommand_with_flags():
    result = format_args({"action": "status", "short": True}, format="subcommand")
    assert result[0] == "status"
    assert "--short" in result


def test_subcommand_with_value_flags():
    result = format_args({"action": "log", "n": "5"}, format="subcommand")
    assert result[0] == "log"
    assert "--n" in result
    assert "5" in result


def test_empty_args():
    result = format_args({}, format="flags")
    assert result == []


def test_int_value_converted_to_string():
    result = format_args({"count": 5}, format="flags")
    assert result == ["--count", "5"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_args.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement argument formatting**

Create `mori/protocols/__init__.py`:

```python
"""Protocol implementations — CLI, MCP, A2A."""
```

Create `mori/protocols/cli/__init__.py`:

```python
"""CLI tool execution."""
```

Create `mori/protocols/cli/args.py`:

```python
"""Format tool arguments into command-line argument lists."""

from __future__ import annotations

from typing import Any, Literal


def format_args(
    arguments: dict[str, Any],
    format: Literal["flags", "positional", "subcommand"],
) -> list[str]:
    """Convert a dict of arguments to a command-line argument list."""
    if format == "flags":
        return _format_flags(arguments)
    elif format == "positional":
        return _format_positional(arguments)
    elif format == "subcommand":
        return _format_subcommand(arguments)
    else:
        raise ValueError(f"Unknown format: {format}")


def _format_flags(arguments: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for key, value in arguments.items():
        if isinstance(value, bool):
            if value:
                result.append(f"--{key}")
        else:
            result.append(f"--{key}")
            result.append(str(value))
    return result


def _format_positional(arguments: dict[str, Any]) -> list[str]:
    sorted_keys = sorted(arguments.keys(), key=lambda k: int(k))
    return [str(arguments[k]) for k in sorted_keys]


def _format_subcommand(arguments: dict[str, Any]) -> list[str]:
    result: list[str] = []
    action = arguments.get("action")
    if action:
        result.append(str(action))

    for key, value in arguments.items():
        if key == "action":
            continue
        if isinstance(value, bool):
            if value:
                result.append(f"--{key}")
        else:
            result.append(f"--{key}")
            result.append(str(value))
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_args.py -v`
Expected: all 12 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/protocols/__init__.py mori/protocols/cli/__init__.py mori/protocols/cli/args.py tests/test_cli_args.py
git commit -m "feat: CLI argument formatting — flags, positional, subcommand"
```

---

## Task 4: CLI Runner

**Files:**
- Create: `mori/protocols/cli/runner.py`
- Test: `tests/test_cli_runner.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_cli_runner.py`:

```python
"""Tests for CLIRunner — uses real subprocesses."""

import pytest

from mori.protocols.cli.runner import CLIRunner, CLIToolConfig


@pytest.fixture
def runner():
    return CLIRunner()


async def test_run_echo(runner):
    config = CLIToolConfig(command="echo", args_format="positional")
    result = await runner.run(arguments={"0": "hello world"}, config=config)
    assert result.success is True
    assert "hello world" in result.content


async def test_run_flags_format(runner):
    config = CLIToolConfig(command="echo", args_format="flags")
    result = await runner.run(arguments={"n": "test"}, config=config)
    assert result.success is True


async def test_run_exit_code_nonzero(runner):
    config = CLIToolConfig(command="false")
    result = await runner.run(arguments={}, config=config)
    assert result.success is False


async def test_run_timeout(runner):
    config = CLIToolConfig(command="sleep", args_format="positional", timeout_sec=0.1)
    result = await runner.run(arguments={"0": "10"}, config=config)
    assert result.success is False
    assert "timed out" in (result.error or "").lower()


async def test_run_captures_stderr(runner):
    config = CLIToolConfig(
        command="sh",
        args_format="positional",
        shell=False,
    )
    result = await runner.run(
        arguments={"0": "-c", "1": "echo err >&2; exit 1"},
        config=config,
    )
    assert result.success is False
    assert "err" in (result.error or "") or "err" in result.metadata.get("stderr", "")


async def test_run_output_cap(runner):
    config = CLIToolConfig(
        command="python3",
        args_format="positional",
        max_output_bytes=50,
    )
    result = await runner.run(
        arguments={"0": "-c", "1": "print('x' * 200)"},
        config=config,
    )
    assert result.success is True
    assert len(result.content.encode()) <= 60  # Allow small overhead


async def test_run_with_cwd(runner, tmp_path):
    config = CLIToolConfig(command="pwd", cwd=str(tmp_path))
    result = await runner.run(arguments={}, config=config)
    assert result.success is True
    assert str(tmp_path) in result.content


async def test_run_with_env(runner):
    config = CLIToolConfig(
        command="sh",
        args_format="positional",
        env={"MORI_TEST_VAR": "hello123"},
    )
    result = await runner.run(
        arguments={"0": "-c", "1": "echo $MORI_TEST_VAR"},
        config=config,
    )
    assert result.success is True
    assert "hello123" in result.content


async def test_run_latency_tracked(runner):
    config = CLIToolConfig(command="echo", args_format="positional")
    result = await runner.run(arguments={"0": "hi"}, config=config)
    assert result.latency_ms > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli_runner.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement CLIRunner**

Create `mori/protocols/cli/runner.py`:

```python
"""CLIRunner — execute CLI tools as subprocesses."""

from __future__ import annotations

import os
import time
from typing import Any, Literal

import anyio

from mori.protocols.cli.args import format_args
from mori.types import MoriModel, ToolResult


class CLIToolConfig(MoriModel):
    command: str
    args_format: Literal["positional", "flags", "subcommand"] = "flags"
    shell: bool = False
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout_sec: float = 60.0
    max_output_bytes: int = 1_048_576
    capture_stderr: bool = True


class CLIRunner:
    """Execute CLI tools as subprocesses."""

    async def run(
        self,
        arguments: dict[str, Any],
        config: CLIToolConfig,
    ) -> ToolResult:
        """Build command, execute subprocess, capture output."""
        args_list = format_args(arguments, format=config.args_format)
        cmd = [config.command] + args_list

        env: dict[str, str] | None = None
        if config.env:
            env = {**os.environ, **config.env}

        start = time.monotonic()
        try:
            result = await anyio.run_process(
                cmd,
                cwd=config.cwd,
                env=env,
                stderr=anyio.PIPE if config.capture_stderr else None,
            )

            elapsed_ms = (time.monotonic() - start) * 1000
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

            # Cap output
            if len(stdout.encode()) > config.max_output_bytes:
                stdout = stdout.encode()[:config.max_output_bytes].decode("utf-8", errors="replace")

            if result.returncode == 0:
                return ToolResult(
                    tool_name=config.command,
                    call_id="",
                    success=True,
                    content=stdout.strip(),
                    latency_ms=elapsed_ms,
                    metadata={"stderr": stderr, "exit_code": result.returncode},
                )
            else:
                return ToolResult(
                    tool_name=config.command,
                    call_id="",
                    success=False,
                    content=stdout.strip(),
                    error=stderr.strip() or f"Exit code {result.returncode}",
                    latency_ms=elapsed_ms,
                    metadata={"stderr": stderr, "exit_code": result.returncode},
                )

        except TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=config.command,
                call_id="",
                success=False,
                content="",
                error=f"Process timed out after {config.timeout_sec}s",
                latency_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=config.command,
                call_id="",
                success=False,
                content="",
                error=str(exc),
                latency_ms=elapsed_ms,
            )
```

Note: `anyio.run_process` does not have a built-in timeout. We need to use `anyio.fail_after` for timeout enforcement. Update the `run` method's try block:

Replace the `try:` block with:

```python
        start = time.monotonic()
        try:
            with anyio.fail_after(config.timeout_sec):
                result = await anyio.run_process(
                    cmd,
                    cwd=config.cwd,
                    env=env,
                    stderr=anyio.PIPE if config.capture_stderr else None,
                )

            elapsed_ms = (time.monotonic() - start) * 1000
            stdout = result.stdout.decode("utf-8", errors="replace")
            stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

            # Cap output
            if len(stdout.encode()) > config.max_output_bytes:
                stdout = stdout.encode()[:config.max_output_bytes].decode("utf-8", errors="replace")

            if result.returncode == 0:
                return ToolResult(
                    tool_name=config.command,
                    call_id="",
                    success=True,
                    content=stdout.strip(),
                    latency_ms=elapsed_ms,
                    metadata={"stderr": stderr, "exit_code": result.returncode},
                )
            else:
                return ToolResult(
                    tool_name=config.command,
                    call_id="",
                    success=False,
                    content=stdout.strip(),
                    error=stderr.strip() or f"Exit code {result.returncode}",
                    latency_ms=elapsed_ms,
                    metadata={"stderr": stderr, "exit_code": result.returncode},
                )

        except TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=config.command,
                call_id="",
                success=False,
                content="",
                error=f"Process timed out after {config.timeout_sec}s",
                latency_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=config.command,
                call_id="",
                success=False,
                content="",
                error=str(exc),
                latency_ms=elapsed_ms,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_runner.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/protocols/cli/runner.py tests/test_cli_runner.py
git commit -m "feat: CLIRunner — subprocess execution with timeout, output cap, env"
```

---

## Task 5: Observability Sinks

**Files:**
- Create: `mori/observability/sinks/__init__.py`
- Create: `mori/observability/sinks/stdout.py`
- Create: `mori/observability/sinks/jsonl.py`
- Test: `tests/test_sinks.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sinks.py`:

```python
"""Tests for StdoutSink and JsonlSink."""

import json
from datetime import datetime, timezone
from pathlib import Path

from mori.observability.events import (
    MoriEvent,
    RunStartEvent,
    ToolInvokeEvent,
    ToolSource,
)
from mori.observability.sinks.jsonl import JsonlSink
from mori.observability.sinks.stdout import StdoutSink
from mori.types import RunId


def _make_event(**overrides) -> MoriEvent:
    defaults = {
        "event_id": "evt_1",
        "event_type": "test",
        "timestamp": datetime.now(timezone.utc),
        "run_id": RunId("run_1"),
    }
    defaults.update(overrides)
    return MoriEvent(**defaults)


async def test_stdout_sink_write(capsys):
    sink = StdoutSink()
    event = RunStartEvent(
        event_id="evt_1",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        task="test task",
    )
    await sink.write(event)
    captured = capsys.readouterr()
    assert "run.start" in captured.out
    assert "test task" in captured.out


async def test_stdout_sink_flush_noop():
    sink = StdoutSink()
    await sink.flush()  # Should not raise


async def test_stdout_sink_close_noop():
    sink = StdoutSink()
    await sink.close()  # Should not raise


async def test_jsonl_sink_write(tmp_path):
    path = tmp_path / "traces.jsonl"
    sink = JsonlSink(path=str(path))
    event = _make_event(event_type="test.event")
    await sink.write(event)
    await sink.flush()

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_type"] == "test.event"
    assert parsed["run_id"] == "run_1"

    await sink.close()


async def test_jsonl_sink_write_batch(tmp_path):
    path = tmp_path / "traces.jsonl"
    sink = JsonlSink(path=str(path))

    events = [_make_event(event_id=f"evt_{i}", event_type="batch") for i in range(5)]
    await sink.write_batch(events)
    await sink.flush()

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 5

    await sink.close()


async def test_jsonl_sink_multiple_writes(tmp_path):
    path = tmp_path / "traces.jsonl"
    sink = JsonlSink(path=str(path))

    await sink.write(_make_event(event_id="evt_1"))
    await sink.write(_make_event(event_id="evt_2"))
    await sink.flush()

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 2

    await sink.close()


async def test_jsonl_sink_close_flushes(tmp_path):
    path = tmp_path / "traces.jsonl"
    sink = JsonlSink(path=str(path))
    await sink.write(_make_event())
    await sink.close()

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 1


async def test_stdout_sink_write_batch(capsys):
    sink = StdoutSink()
    events = [
        _make_event(event_type="first"),
        _make_event(event_type="second"),
    ]
    await sink.write_batch(events)
    captured = capsys.readouterr()
    assert "first" in captured.out
    assert "second" in captured.out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sinks.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement sinks**

Create `mori/observability/sinks/__init__.py`:

```python
"""Pluggable event sinks for observability."""
```

Create `mori/observability/sinks/stdout.py`:

```python
"""StdoutSink — formatted console output for events."""

from __future__ import annotations

from mori.observability.events import (
    MoriEvent,
    RunStartEvent,
    RunEndEvent,
    StepStartEvent,
    StepEndEvent,
    ToolInvokeEvent,
    ToolResultEvent,
    BoundViolationEvent,
)

_GREY = "\033[90m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_RESET = "\033[0m"


def _format_event(event: MoriEvent) -> str:
    prefix = f"  {_GREY}[mori]{_RESET}"

    if isinstance(event, RunStartEvent):
        return f"{prefix} RUN   → \"{event.task[:80]}\" config={event.config}"

    if isinstance(event, RunEndEvent):
        color = _GREEN if event.status.value == "completed" else _RED
        return (
            f"{prefix} DONE  → {color}{event.status.value}{_RESET} in {event.total_steps} steps, "
            f"{event.total_input_tokens + event.total_output_tokens} tokens, {event.duration_ms:.0f}ms"
        )

    if isinstance(event, StepStartEvent):
        return f"{prefix} ─── step {event.step_number} ({event.phase.value}) ───"

    if isinstance(event, StepEndEvent):
        return f"{prefix} EVAL  → {event.outcome.value} ({event.duration_ms:.0f}ms)"

    if isinstance(event, ToolInvokeEvent):
        args_str = str(event.arguments)[:100] if event.arguments else ""
        return f"{prefix} ACT   → {event.tool_name}({args_str}) [{event.source.value}]"

    if isinstance(event, ToolResultEvent):
        if event.success:
            preview = (event.result_preview or "")[:80]
            return f"{prefix}        {_GREEN}✓{_RESET} {event.tool_name}: {preview} ({event.latency_ms:.0f}ms)"
        else:
            return f"{prefix}        {_RED}✗{_RESET} {event.tool_name}: {event.error}"

    if isinstance(event, BoundViolationEvent):
        return (
            f"{prefix} {_YELLOW}BOUND{_RESET} → {event.bound_name}: "
            f"{event.current_value} >= {event.limit_value}"
        )

    return f"{prefix} {event.event_type}: {event.metadata}"


class StdoutSink:
    """Write events to stdout as formatted text."""

    async def write(self, event: MoriEvent) -> None:
        print(_format_event(event))

    async def write_batch(self, events: list[MoriEvent]) -> None:
        for event in events:
            print(_format_event(event))

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        pass
```

Create `mori/observability/sinks/jsonl.py`:

```python
"""JsonlSink — write events as JSON Lines to a file."""

from __future__ import annotations

import io
from typing import Any

from mori.observability.events import MoriEvent


class JsonlSink:
    """Write events as one JSON object per line to a file."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._file: io.TextIOWrapper = open(path, "a", encoding="utf-8")

    async def write(self, event: MoriEvent) -> None:
        line = event.model_dump_json()
        self._file.write(line + "\n")

    async def write_batch(self, events: list[MoriEvent]) -> None:
        for event in events:
            line = event.model_dump_json()
            self._file.write(line + "\n")

    async def flush(self) -> None:
        self._file.flush()

    async def close(self) -> None:
        self._file.flush()
        self._file.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sinks.py -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/observability/sinks/__init__.py mori/observability/sinks/stdout.py mori/observability/sinks/jsonl.py tests/test_sinks.py
git commit -m "feat: StdoutSink and JsonlSink for event output"
```

---

## Task 6: Observability Engine

**Files:**
- Create: `mori/observability/engine.py`
- Test: `tests/test_observability.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_observability.py`:

```python
"""Tests for ObservabilityEngine — buffered event dispatch."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from mori.observability.engine import ObservabilityEngine
from mori.observability.events import (
    MoriEvent,
    ObservabilityConfig,
    RunStartEvent,
    RunEndEvent,
    ToolInvokeEvent,
    ToolResultEvent,
    EventSink,
    RunSummary,
)
from mori.types import RunId, RunStatus, ToolSource, TraceId


def _make_event(event_type: str = "test", **overrides) -> MoriEvent:
    defaults = {
        "event_id": "evt_1",
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc),
        "run_id": RunId("run_1"),
    }
    defaults.update(overrides)
    return MoriEvent(**defaults)


@pytest.fixture
def mock_sink():
    sink = AsyncMock()
    sink.write = AsyncMock()
    sink.write_batch = AsyncMock()
    sink.flush = AsyncMock()
    sink.close = AsyncMock()
    return sink


async def test_emit_dispatches_to_sink(mock_sink):
    engine = ObservabilityEngine(
        sinks=[mock_sink],
        config=ObservabilityConfig(buffer_size=1),
    )
    event = _make_event()
    await engine.emit(event)
    await engine.flush()
    mock_sink.write_batch.assert_called()
    await engine.close()


async def test_emit_buffers_until_threshold(mock_sink):
    engine = ObservabilityEngine(
        sinks=[mock_sink],
        config=ObservabilityConfig(buffer_size=5, flush_interval_sec=999),
    )
    for i in range(3):
        await engine.emit(_make_event(event_id=f"evt_{i}"))

    # Not flushed yet — buffer not full
    mock_sink.write_batch.assert_not_called()

    # Push to threshold
    for i in range(3, 5):
        await engine.emit(_make_event(event_id=f"evt_{i}"))

    # Now flushed
    mock_sink.write_batch.assert_called_once()
    events = mock_sink.write_batch.call_args[0][0]
    assert len(events) == 5

    await engine.close()


async def test_flush_drains_buffer(mock_sink):
    engine = ObservabilityEngine(
        sinks=[mock_sink],
        config=ObservabilityConfig(buffer_size=100),
    )
    await engine.emit(_make_event())
    await engine.emit(_make_event())
    await engine.flush()

    mock_sink.write_batch.assert_called_once()
    events = mock_sink.write_batch.call_args[0][0]
    assert len(events) == 2

    await engine.close()


async def test_close_flushes_remaining(mock_sink):
    engine = ObservabilityEngine(
        sinks=[mock_sink],
        config=ObservabilityConfig(buffer_size=100),
    )
    await engine.emit(_make_event())
    await engine.close()

    mock_sink.write_batch.assert_called_once()
    mock_sink.close.assert_called_once()


async def test_multiple_sinks():
    sink1 = AsyncMock()
    sink2 = AsyncMock()
    engine = ObservabilityEngine(
        sinks=[sink1, sink2],
        config=ObservabilityConfig(buffer_size=1),
    )
    await engine.emit(_make_event())
    await engine.flush()

    sink1.write_batch.assert_called()
    sink2.write_batch.assert_called()
    await engine.close()


async def test_start_trace():
    engine = ObservabilityEngine(sinks=[], config=ObservabilityConfig())
    trace_id = engine.start_trace(RunId("run_1"))
    assert trace_id.startswith("trace_")
    await engine.close()


async def test_start_and_end_span():
    engine = ObservabilityEngine(sinks=[], config=ObservabilityConfig())
    trace_id = engine.start_trace(RunId("run_1"))
    span = engine.start_span(trace_id, "test_span")
    assert span.trace_id == trace_id
    assert span.end_time is None

    engine.end_span(span)
    assert span.end_time is not None
    assert span.duration_ms is not None
    assert span.duration_ms >= 0

    await engine.close()


async def test_enabled_event_types_filter(mock_sink):
    engine = ObservabilityEngine(
        sinks=[mock_sink],
        config=ObservabilityConfig(
            buffer_size=1,
            enabled_event_types=["run.start"],
        ),
    )
    await engine.emit(RunStartEvent(
        event_id="evt_1",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        task="test",
    ))
    await engine.emit(_make_event(event_type="other.type"))
    await engine.flush()

    # Only run.start should have been buffered
    if mock_sink.write_batch.called:
        events = mock_sink.write_batch.call_args[0][0]
        event_types = [e.event_type for e in events]
        assert "other.type" not in event_types

    await engine.close()


async def test_get_run_summary():
    engine = ObservabilityEngine(sinks=[], config=ObservabilityConfig())

    await engine.emit(RunStartEvent(
        event_id="evt_1",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        task="test",
    ))
    await engine.emit(ToolResultEvent(
        event_id="evt_2",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        tool_name="add",
        success=True,
        latency_ms=5.0,
    ))
    await engine.emit(ToolResultEvent(
        event_id="evt_3",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        tool_name="fail",
        success=False,
        latency_ms=10.0,
        error="broke",
    ))
    await engine.emit(RunEndEvent(
        event_id="evt_4",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_1"),
        status=RunStatus.COMPLETED,
        total_steps=2,
        total_input_tokens=300,
        total_output_tokens=100,
        duration_ms=1000.0,
    ))

    summary = engine.get_run_summary(RunId("run_1"))
    assert summary.total_tool_calls == 2
    assert summary.total_tool_failures == 1
    assert summary.status == RunStatus.COMPLETED
    assert "add" in summary.tools_used
    assert "fail" in summary.tools_used

    await engine.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_observability.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ObservabilityEngine**

Create `mori/observability/engine.py`:

```python
"""ObservabilityEngine — buffered event dispatch with trace context."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from mori.observability.events import (
    EventSink,
    MoriEvent,
    ObservabilityConfig,
    RunEndEvent,
    RunSummary,
    SpanContext,
    ToolResultEvent,
)
from mori.types import RunId, RunStatus, TraceId


class ObservabilityEngine:
    """Buffered event dispatch to pluggable sinks."""

    def __init__(
        self,
        sinks: list[Any],
        config: ObservabilityConfig | None = None,
    ) -> None:
        self._sinks = sinks
        self._config = config or ObservabilityConfig()
        self._buffer: list[MoriEvent] = []
        self._all_events: list[MoriEvent] = []

    async def emit(self, event: MoriEvent) -> None:
        """Buffer an event. Flush when buffer is full."""
        if self._config.enabled_event_types is not None:
            if event.event_type not in self._config.enabled_event_types:
                return

        self._buffer.append(event)
        self._all_events.append(event)

        if len(self._buffer) >= self._config.buffer_size:
            await self._flush_buffer()

    async def emit_batch(self, events: list[MoriEvent]) -> None:
        """Buffer multiple events."""
        for event in events:
            await self.emit(event)

    def start_trace(self, run_id: RunId) -> TraceId:
        """Start a new trace for a run."""
        return TraceId(f"trace_{secrets.token_hex(12)}")

    def start_span(
        self,
        trace_id: TraceId,
        name: str,
        parent_span_id: str | None = None,
    ) -> SpanContext:
        """Start a new span within a trace."""
        return SpanContext(
            trace_id=trace_id,
            span_id=f"span_{secrets.token_hex(8)}",
            parent_span_id=parent_span_id,
            name=name,
            start_time=datetime.now(timezone.utc),
        )

    def end_span(self, span: SpanContext) -> None:
        """End a span by setting its end_time."""
        span.end_time = datetime.now(timezone.utc)

    def get_run_summary(self, run_id: RunId) -> RunSummary:
        """Compute a summary from collected events for a given run."""
        run_events = [e for e in self._all_events if e.run_id == run_id]

        status = RunStatus.RUNNING
        total_steps = 0
        total_input_tokens = 0
        total_output_tokens = 0
        total_tool_calls = 0
        total_tool_failures = 0
        total_duration_ms = 0.0
        tools_used: set[str] = set()
        errors: list[str] = []

        for event in run_events:
            if isinstance(event, RunEndEvent):
                status = event.status
                total_steps = event.total_steps
                total_input_tokens = event.total_input_tokens
                total_output_tokens = event.total_output_tokens
                total_duration_ms = event.duration_ms
            elif isinstance(event, ToolResultEvent):
                total_tool_calls += 1
                tools_used.add(event.tool_name)
                if not event.success:
                    total_tool_failures += 1
                    if event.error:
                        errors.append(event.error)

        avg_step_ms = total_duration_ms / total_steps if total_steps > 0 else 0.0

        return RunSummary(
            run_id=run_id,
            status=status,
            total_steps=total_steps,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_tool_calls=total_tool_calls,
            total_tool_failures=total_tool_failures,
            total_duration_ms=total_duration_ms,
            avg_step_duration_ms=avg_step_ms,
            tools_used=sorted(tools_used),
            error_summary=errors,
        )

    async def flush(self) -> None:
        """Flush buffered events to all sinks."""
        await self._flush_buffer()
        for sink in self._sinks:
            await sink.flush()

    async def close(self) -> None:
        """Flush remaining events and close all sinks."""
        await self._flush_buffer()
        for sink in self._sinks:
            await sink.flush()
            await sink.close()

    async def _flush_buffer(self) -> None:
        """Send buffered events to all sinks and clear the buffer."""
        if not self._buffer:
            return

        events = list(self._buffer)
        self._buffer.clear()

        for sink in self._sinks:
            await sink.write_batch(events)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_observability.py -v`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/observability/engine.py tests/test_observability.py
git commit -m "feat: ObservabilityEngine — buffered dispatch, trace context, run summary"
```

---

## Task 7: MCP Schema Cache

**Files:**
- Create: `mori/protocols/mcp/__init__.py`
- Create: `mori/protocols/mcp/schema_cache.py`
- Test: `tests/test_schema_cache.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_schema_cache.py`:

```python
"""Tests for MCP schema cache with TTL."""

import time

from mori.protocols.mcp.schema_cache import SchemaCache
from mori.types import ToolId, ToolSource, ToolSpec


def _make_spec(name: str) -> ToolSpec:
    return ToolSpec(
        tool_id=ToolId(f"mcp:{name}"),
        name=name,
        description=f"Tool {name}",
        input_schema={"type": "object"},
        source=ToolSource.MCP,
    )


def test_put_and_get():
    cache = SchemaCache(ttl_sec=300)
    specs = [_make_spec("search"), _make_spec("read")]
    cache.put("github", specs)

    result = cache.get("github")
    assert result is not None
    assert len(result) == 2
    assert result[0].name == "search"


def test_get_missing():
    cache = SchemaCache()
    assert cache.get("nonexistent") is None


def test_is_stale_fresh():
    cache = SchemaCache(ttl_sec=300)
    cache.put("server", [_make_spec("tool")])
    assert cache.is_stale("server") is False


def test_is_stale_expired():
    cache = SchemaCache(ttl_sec=0.001)
    cache.put("server", [_make_spec("tool")])
    time.sleep(0.01)
    assert cache.is_stale("server") is True


def test_is_stale_missing():
    cache = SchemaCache()
    assert cache.is_stale("nonexistent") is True


def test_invalidate():
    cache = SchemaCache()
    cache.put("server", [_make_spec("tool")])
    cache.invalidate("server")
    assert cache.get("server") is None


def test_invalidate_missing():
    cache = SchemaCache()
    cache.invalidate("nonexistent")  # Should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_schema_cache.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement SchemaCache**

Create `mori/protocols/mcp/__init__.py`:

```python
"""MCP client and schema caching."""
```

Create `mori/protocols/mcp/schema_cache.py`:

```python
"""Schema cache with TTL for MCP tool discovery."""

from __future__ import annotations

import time

from mori.types import ToolSpec


class SchemaCache:
    """Cache MCP tool schemas with time-based expiration."""

    def __init__(self, ttl_sec: float = 300.0) -> None:
        self._ttl_sec = ttl_sec
        self._cache: dict[str, tuple[float, list[ToolSpec]]] = {}

    def get(self, server_name: str) -> list[ToolSpec] | None:
        """Get cached specs, or None if missing."""
        entry = self._cache.get(server_name)
        if entry is None:
            return None
        return entry[1]

    def put(self, server_name: str, specs: list[ToolSpec]) -> None:
        """Cache specs with current timestamp."""
        self._cache[server_name] = (time.monotonic(), specs)

    def is_stale(self, server_name: str) -> bool:
        """Check if cache entry is expired or missing."""
        entry = self._cache.get(server_name)
        if entry is None:
            return True
        cached_at, _ = entry
        return (time.monotonic() - cached_at) >= self._ttl_sec

    def invalidate(self, server_name: str) -> None:
        """Remove a cache entry."""
        self._cache.pop(server_name, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_schema_cache.py -v`
Expected: all 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/protocols/mcp/__init__.py mori/protocols/mcp/schema_cache.py tests/test_schema_cache.py
git commit -m "feat: MCP schema cache with TTL expiration"
```

---

## Task 8: MCP Client

**Files:**
- Create: `mori/protocols/mcp/client.py`
- Modify: `mori/types.py` — add AuthConfig, HealthStatus, ServerUnavailable
- Test: `tests/test_mcp_client.py`

- [ ] **Step 1: Add supporting types to mori/types.py**

Append to the end of `mori/types.py`, before the error hierarchy section:

```python
# ── Health & Auth ────────────────────────────────────────────

class HealthStatus(MoriModel):
    healthy: bool
    component: str
    message: str = ""
    latency_ms: float | None = None


class AuthConfig(MoriModel):
    type: Literal["bearer", "api_key", "oauth2", "none"] = "none"
    token: str | None = None
    token_env: str | None = None
    header_name: str = "Authorization"
```

And add to the error hierarchy:

```python
class ServerUnavailable(ToolError):
    pass
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_mcp_client.py`:

```python
"""Tests for MCPClient — uses mocked HTTP/SSE server."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mori.protocols.mcp.client import MCPClient
from mori.types import AuthConfig, ToolSource


@pytest.fixture
def mock_httpx():
    """Mock httpx for SSE transport testing."""
    with patch("mori.protocols.mcp.client.httpx") as mock:
        yield mock


async def test_client_init():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    assert client.name == "test"
    assert client._connected is False


async def test_client_discover_tools_returns_specs():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": {
            "tools": [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}},
                },
                {
                    "name": "write_file",
                    "description": "Write a file",
                    "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
                },
            ]
        }
    }

    with patch.object(client, "_send_rpc", new_callable=AsyncMock, return_value=mock_response.json.return_value["result"]):
        specs = await client.discover_tools()

    assert len(specs) == 2
    assert specs[0].name == "read_file"
    assert specs[0].source == ToolSource.MCP
    assert specs[1].name == "write_file"


async def test_client_invoke_routes_through_rpc():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    client._connected = True

    mock_result = {"content": [{"type": "text", "text": "file contents here"}]}
    with patch.object(client, "_send_rpc", new_callable=AsyncMock, return_value=mock_result):
        result = await client.invoke("read_file", {"path": "test.txt"})

    assert result.success is True
    assert "file contents" in result.content


async def test_client_invoke_handles_error():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    client._connected = True

    with patch.object(client, "_send_rpc", new_callable=AsyncMock, side_effect=Exception("connection lost")):
        result = await client.invoke("read_file", {"path": "test.txt"})

    assert result.success is False
    assert "connection lost" in (result.error or "")


async def test_client_health_check_healthy():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    client._connected = True

    with patch.object(client, "_send_rpc", new_callable=AsyncMock, return_value={}):
        health = await client.health_check()

    assert health.healthy is True
    assert health.component == "test"


async def test_client_health_check_unhealthy():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")
    client._connected = True

    with patch.object(client, "_send_rpc", new_callable=AsyncMock, side_effect=Exception("down")):
        health = await client.health_check()

    assert health.healthy is False


async def test_client_uses_schema_cache():
    client = MCPClient(name="test", url="http://localhost:3000", transport="sse")

    mock_result = {
        "tools": [{"name": "tool1", "description": "Tool 1", "inputSchema": {"type": "object"}}]
    }
    with patch.object(client, "_send_rpc", new_callable=AsyncMock, return_value=mock_result) as mock_rpc:
        specs1 = await client.discover_tools()
        specs2 = await client.discover_tools()

    # Second call should use cache, not call RPC again
    assert mock_rpc.call_count == 1
    assert len(specs1) == 1
    assert len(specs2) == 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_mcp_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement MCPClient**

Create `mori/protocols/mcp/client.py`:

```python
"""MCPClient — native MCP client speaking JSON-RPC 2.0."""

from __future__ import annotations

import secrets
import time
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

from mori.protocols.mcp.schema_cache import SchemaCache
from mori.types import (
    AuthConfig,
    HealthStatus,
    MoriModel,
    ServerUnavailable,
    ToolId,
    ToolResult,
    ToolSource,
    ToolSpec,
)


class MCPClient:
    """Native MCP client speaking JSON-RPC 2.0."""

    def __init__(
        self,
        name: str,
        url: str,
        transport: str = "sse",
        auth: AuthConfig | None = None,
    ) -> None:
        self.name = name
        self._url = url
        self._transport = transport
        self._auth = auth
        self._connected = False
        self._cache = SchemaCache()
        self._client: Any = None

    async def connect(self) -> None:
        """Establish connection to the MCP server."""
        if httpx is None:
            raise ImportError("httpx is required for MCP client")

        headers: dict[str, str] = {}
        if self._auth and self._auth.token:
            headers[self._auth.header_name] = f"Bearer {self._auth.token}"

        self._client = httpx.AsyncClient(
            base_url=self._url,
            headers=headers,
            timeout=30.0,
        )
        self._connected = True

    async def discover_tools(self) -> list[ToolSpec]:
        """Discover tools from the server. Uses cache if fresh."""
        cached = self._cache.get(self.name)
        if cached is not None and not self._cache.is_stale(self.name):
            return cached

        result = await self._send_rpc("tools/list", {})
        tools_data = result.get("tools", [])

        specs: list[ToolSpec] = []
        for tool in tools_data:
            spec = ToolSpec(
                tool_id=ToolId(f"mcp:{self.name}:{tool['name']}"),
                name=tool["name"],
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema", {"type": "object"}),
                source=ToolSource.MCP,
                server_id=self.name,
            )
            specs.append(spec)

        self._cache.put(self.name, specs)
        return specs

    async def invoke(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Invoke a tool on the MCP server."""
        start = time.monotonic()
        try:
            result = await self._send_rpc("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })
            elapsed_ms = (time.monotonic() - start) * 1000

            # Parse MCP content response
            content_blocks = result.get("content", [])
            text_parts = [
                block.get("text", "")
                for block in content_blocks
                if block.get("type") == "text"
            ]
            content = "\n".join(text_parts) if text_parts else str(result)

            return ToolResult(
                tool_name=tool_name,
                call_id="",
                success=True,
                content=content,
                latency_ms=elapsed_ms,
                metadata={"server": self.name},
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ToolResult(
                tool_name=tool_name,
                call_id="",
                success=False,
                content="",
                error=str(exc),
                latency_ms=elapsed_ms,
                metadata={"server": self.name},
            )

    async def health_check(self) -> HealthStatus:
        """Check if the MCP server is reachable."""
        start = time.monotonic()
        try:
            await self._send_rpc("ping", {})
            elapsed_ms = (time.monotonic() - start) * 1000
            return HealthStatus(
                healthy=True,
                component=self.name,
                message="ok",
                latency_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return HealthStatus(
                healthy=False,
                component=self.name,
                message=str(exc),
                latency_ms=elapsed_ms,
            )

    async def close(self) -> None:
        """Close the connection."""
        if self._client:
            await self._client.aclose()
        self._connected = False

    async def _send_rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC 2.0 request."""
        if self._client is None:
            raise ServerUnavailable(f"Not connected to {self.name}")

        payload = {
            "jsonrpc": "2.0",
            "id": secrets.token_hex(8),
            "method": method,
            "params": params,
        }
        response = await self._client.post("/", json=payload)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            raise ServerUnavailable(
                f"MCP error: {data['error'].get('message', 'unknown')}",
                details=data["error"],
            )

        return data.get("result", {})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_mcp_client.py -v`
Expected: all 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add mori/protocols/mcp/client.py mori/types.py tests/test_mcp_client.py
git commit -m "feat: MCPClient — JSON-RPC 2.0 with schema cache and health check"
```

---

## Task 9: Error Rate Tracking + Result Truncation

**Files:**
- Modify: `mori/tools/registry.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_metrics.py`:

```python
"""Tests for per-tool metrics and result truncation in ToolRegistry."""

from datetime import datetime

from mori.tools.registry import ToolRegistry, ToolMetrics


def test_metrics_initial_state():
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    metrics = registry.get_metrics("native:add")
    assert metrics is not None
    assert metrics.total_calls == 0
    assert metrics.total_errors == 0
    assert metrics.error_rate == 0.0


async def test_metrics_increment_on_success():
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    await registry.invoke("add", {"a": 1, "b": 2})

    metrics = registry.get_metrics("native:add")
    assert metrics.total_calls == 1
    assert metrics.total_errors == 0
    assert metrics.avg_latency_ms > 0
    assert metrics.last_called is not None


async def test_metrics_increment_on_failure():
    registry = ToolRegistry()

    def fail():
        raise ValueError("boom")

    registry.register("fail", fail, description="Fails")
    await registry.invoke("fail", {})

    metrics = registry.get_metrics("native:fail")
    assert metrics.total_calls == 1
    assert metrics.total_errors == 1
    assert metrics.error_rate == 1.0
    assert metrics.last_error == "boom"


async def test_metrics_multiple_calls():
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")

    for _ in range(5):
        await registry.invoke("add", {"a": 1, "b": 2})

    metrics = registry.get_metrics("native:add")
    assert metrics.total_calls == 5
    assert metrics.total_errors == 0


def test_get_metrics_unknown_tool():
    registry = ToolRegistry()
    assert registry.get_metrics("native:nonexistent") is None


async def test_result_truncation():
    registry = ToolRegistry(max_result_tokens=10)

    def verbose() -> str:
        return "x" * 200

    registry.register("verbose", verbose, description="Verbose")
    result = await registry.invoke("verbose", {})
    assert result.success is True
    assert "[TRUNCATED" in result.content
    assert len(result.content) < 200


async def test_no_truncation_under_limit():
    registry = ToolRegistry(max_result_tokens=4000)
    registry.register("short", lambda: "hello", description="Short")
    result = await registry.invoke("short", {})
    assert "[TRUNCATED" not in result.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_metrics.py -v`
Expected: FAIL — `ToolRegistry` doesn't accept `max_result_tokens` yet

- [ ] **Step 3: Update ToolRegistry with metrics and truncation**

Replace the entire contents of `mori/tools/registry.py`:

```python
"""Tool registry for native Python callables, with metrics and truncation."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import Field

from mori.tools.schema import infer_schema
from mori.types import (
    MoriModel,
    RegisteredTool,
    ToolId,
    ToolInvocationError,
    ToolResult,
    ToolSource,
    ToolSpec,
)


class ToolMetrics(MoriModel):
    tool_id: ToolId
    total_calls: int = 0
    total_errors: int = 0
    avg_latency_ms: float = 0.0
    last_error: str | None = None
    last_called: datetime | None = None
    _total_latency_ms: float = 0.0

    model_config = {"frozen": False, "extra": "forbid"}

    @property
    def error_rate(self) -> float:
        return self.total_errors / self.total_calls if self.total_calls > 0 else 0.0


class ToolRegistry:
    """Central registry for tools with metrics tracking."""

    def __init__(self, max_result_tokens: int = 4000) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._metrics: dict[str, ToolMetrics] = {}
        self._max_result_tokens = max_result_tokens

    def register(
        self,
        name: str,
        fn: Callable[..., Any],
        description: str,
        input_schema: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """Register a Python function as a tool. Returns the tool ID."""
        tool_id = ToolId(f"native:{name}")

        if input_schema is None:
            input_schema = infer_schema(fn)

        spec = ToolSpec(
            tool_id=tool_id,
            name=name,
            description=description,
            input_schema=input_schema,
            source=ToolSource.NATIVE,
            tags=tags or [],
        )
        self._tools[name] = RegisteredTool(spec=spec, fn=fn)
        self._metrics[tool_id] = ToolMetrics(tool_id=tool_id)
        return tool_id

    def tool(
        self,
        description: str,
        name: str | None = None,
        tags: list[str] | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator for registering tools."""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = name or fn.__name__
            self.register(tool_name, fn, description=description, tags=tags)
            return fn

        return decorator

    def list_specs(self) -> list[ToolSpec]:
        """List all registered tool specs."""
        return [rt.spec for rt in self._tools.values()]

    def get_spec(self, name: str) -> ToolSpec | None:
        """Get a tool spec by name."""
        rt = self._tools.get(name)
        return rt.spec if rt else None

    def get_metrics(self, tool_id: str) -> ToolMetrics | None:
        """Get metrics for a tool by ID."""
        return self._metrics.get(tool_id)

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Invoke a tool by name with the given arguments."""
        rt = self._tools.get(name)
        if rt is None:
            raise ToolInvocationError(f"Tool '{name}' not found")

        if rt.fn is None:
            raise ToolInvocationError(f"Tool '{name}' has no callable")

        metrics = self._metrics.get(rt.spec.tool_id)
        start = time.monotonic()

        try:
            if asyncio.iscoroutinefunction(rt.fn):
                raw_result = await rt.fn(**arguments)
            else:
                raw_result = rt.fn(**arguments)

            elapsed_ms = (time.monotonic() - start) * 1000
            content = str(raw_result) if not isinstance(raw_result, str) else raw_result
            content = self._truncate(content)

            result = ToolResult(
                tool_name=name,
                call_id="",
                success=True,
                content=content,
                latency_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            result = ToolResult(
                tool_name=name,
                call_id="",
                success=False,
                content="",
                error=str(exc),
                latency_ms=elapsed_ms,
            )

        # Update metrics
        if metrics:
            metrics.total_calls += 1
            metrics._total_latency_ms += result.latency_ms
            metrics.avg_latency_ms = metrics._total_latency_ms / metrics.total_calls
            metrics.last_called = datetime.now(timezone.utc)
            if not result.success:
                metrics.total_errors += 1
                metrics.last_error = result.error

        return result

    def _truncate(self, content: str) -> str:
        """Truncate content if it exceeds max_result_tokens."""
        max_chars = self._max_result_tokens * 4  # Approximate: 4 chars per token
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + f"\n[TRUNCATED: output exceeded {self._max_result_tokens} tokens]"
```

- [ ] **Step 4: Run metrics tests**

Run: `pytest tests/test_metrics.py -v`
Expected: all 7 tests PASS

- [ ] **Step 5: Run existing registry tests to ensure no regression**

Run: `pytest tests/test_registry.py -v`
Expected: all 14 tests PASS

- [ ] **Step 6: Commit**

```bash
git add mori/tools/registry.py tests/test_metrics.py
git commit -m "feat: per-tool metrics tracking and result truncation in registry"
```

---

## Task 10: Registry Extensions — register_cli, register_mcp_server

**Files:**
- Modify: `mori/tools/registry.py`
- Test: `tests/test_registry_v02.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_registry_v02.py`:

```python
"""Tests for v0.2 registry extensions — CLI and MCP tool registration."""

from unittest.mock import AsyncMock, patch

import pytest

from mori.protocols.cli.runner import CLIToolConfig
from mori.tools.registry import ToolRegistry
from mori.types import ToolSource


def test_register_cli():
    registry = ToolRegistry()
    tool_id = registry.register_cli(
        name="search_code",
        command="rg",
        description="Search with ripgrep",
        args_format="flags",
        args_schema={
            "pattern": {"type": "string"},
            "path": {"type": "string", "default": "."},
        },
    )
    assert tool_id == "cli:search_code"

    spec = registry.get_spec("search_code")
    assert spec is not None
    assert spec.source == ToolSource.CLI
    assert spec.name == "search_code"


def test_register_cli_with_options():
    registry = ToolRegistry()
    registry.register_cli(
        name="git",
        command="git",
        description="Git commands",
        args_format="subcommand",
        cwd="/tmp",
        timeout_sec=30.0,
    )
    spec = registry.get_spec("git")
    assert spec is not None


async def test_invoke_cli_tool():
    registry = ToolRegistry()
    registry.register_cli(
        name="echo_test",
        command="echo",
        description="Echo text",
        args_format="positional",
    )
    result = await registry.invoke("echo_test", {"0": "hello"})
    assert result.success is True
    assert "hello" in result.content


async def test_invoke_cli_tool_tracks_metrics():
    registry = ToolRegistry()
    registry.register_cli(
        name="echo_test",
        command="echo",
        description="Echo",
        args_format="positional",
    )
    await registry.invoke("echo_test", {"0": "hi"})

    metrics = registry.get_metrics("cli:echo_test")
    assert metrics is not None
    assert metrics.total_calls == 1


def test_list_specs_includes_cli():
    registry = ToolRegistry()
    registry.register("native_tool", lambda: "ok", description="Native")
    registry.register_cli("cli_tool", command="echo", description="CLI", args_format="flags")

    specs = registry.list_specs()
    assert len(specs) == 2
    sources = {s.source for s in specs}
    assert ToolSource.NATIVE in sources
    assert ToolSource.CLI in sources


async def test_register_mcp_server():
    registry = ToolRegistry()

    mock_client = AsyncMock()
    mock_client.name = "test_server"
    mock_client.discover_tools = AsyncMock(return_value=[])

    with patch("mori.tools.registry.MCPClient", return_value=mock_client):
        tool_ids = await registry.register_mcp_server(
            name="test_server",
            url="http://localhost:3000",
        )

    mock_client.connect.assert_called_once()
    assert isinstance(tool_ids, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_registry_v02.py -v`
Expected: FAIL — `register_cli` doesn't exist yet

- [ ] **Step 3: Add register_cli and register_mcp_server to ToolRegistry**

Add these imports to the top of `mori/tools/registry.py`:

```python
from mori.protocols.cli.runner import CLIRunner, CLIToolConfig
from mori.protocols.mcp.client import MCPClient
```

Add these methods to the `ToolRegistry` class, after `get_metrics`:

```python
    def register_cli(
        self,
        name: str,
        command: str,
        description: str,
        args_format: str = "flags",
        args_schema: dict[str, Any] | None = None,
        shell: bool = False,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: float = 60.0,
        tags: list[str] | None = None,
    ) -> str:
        """Register a CLI program as a tool."""
        tool_id = ToolId(f"cli:{name}")

        config = CLIToolConfig(
            command=command,
            args_format=args_format,
            shell=shell,
            cwd=cwd,
            env=env,
            timeout_sec=timeout_sec,
        )

        input_schema = args_schema or {"type": "object", "properties": {}}

        spec = ToolSpec(
            tool_id=tool_id,
            name=name,
            description=description,
            input_schema=input_schema,
            source=ToolSource.CLI,
            tags=tags or [],
        )

        runner = CLIRunner()
        self._tools[name] = RegisteredTool(spec=spec, fn=None)
        self._cli_configs[name] = (runner, config)
        self._metrics[tool_id] = ToolMetrics(tool_id=tool_id)
        return tool_id

    async def register_mcp_server(
        self,
        name: str,
        url: str,
        transport: str = "sse",
        auth: Any = None,
    ) -> list[str]:
        """Connect to an MCP server, discover tools, register them."""
        client = MCPClient(name=name, url=url, transport=transport, auth=auth)
        await client.connect()

        specs = await client.discover_tools()
        self._mcp_clients[name] = client

        tool_ids: list[str] = []
        for spec in specs:
            self._tools[spec.name] = RegisteredTool(spec=spec, fn=None)
            self._metrics[spec.tool_id] = ToolMetrics(tool_id=spec.tool_id)
            tool_ids.append(spec.tool_id)

        return tool_ids
```

Update `__init__` to add the new storage:

```python
    def __init__(self, max_result_tokens: int = 4000) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        self._metrics: dict[str, ToolMetrics] = {}
        self._cli_configs: dict[str, tuple[CLIRunner, CLIToolConfig]] = {}
        self._mcp_clients: dict[str, MCPClient] = {}
        self._max_result_tokens = max_result_tokens
```

Update the `invoke` method to route CLI and MCP tools. Replace the "if rt.fn is None" check with:

```python
        # Route by source
        if rt.spec.source == ToolSource.CLI:
            cli_entry = self._cli_configs.get(name)
            if cli_entry is None:
                raise ToolInvocationError(f"CLI tool '{name}' has no runner config")
            runner, config = cli_entry
            result = await runner.run(arguments=arguments, config=config)
            result.tool_name = name
        elif rt.spec.source == ToolSource.MCP:
            server_id = rt.spec.server_id
            if server_id is None or server_id not in self._mcp_clients:
                raise ToolInvocationError(f"MCP tool '{name}' has no connected server")
            client = self._mcp_clients[server_id]
            result = await client.invoke(name, arguments)
        elif rt.fn is not None:
            # Native tool
            start = time.monotonic()
            try:
                if asyncio.iscoroutinefunction(rt.fn):
                    raw_result = await rt.fn(**arguments)
                else:
                    raw_result = rt.fn(**arguments)

                elapsed_ms = (time.monotonic() - start) * 1000
                content = str(raw_result) if not isinstance(raw_result, str) else raw_result
                content = self._truncate(content)

                result = ToolResult(
                    tool_name=name,
                    call_id="",
                    success=True,
                    content=content,
                    latency_ms=elapsed_ms,
                )
            except Exception as exc:
                elapsed_ms = (time.monotonic() - start) * 1000
                result = ToolResult(
                    tool_name=name,
                    call_id="",
                    success=False,
                    content="",
                    error=str(exc),
                    latency_ms=elapsed_ms,
                )
        else:
            raise ToolInvocationError(f"Tool '{name}' has no callable")

        # Truncate content
        if result.success and isinstance(result.content, str):
            result.content = self._truncate(result.content)
```

Note: This replaces the existing invoke logic — the native path is preserved, CLI and MCP paths are added.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_registry_v02.py tests/test_registry.py tests/test_metrics.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add mori/tools/registry.py tests/test_registry_v02.py
git commit -m "feat: register_cli and register_mcp_server — CLI/MCP tool routing"
```

---

## Task 11: Loop Refactor — Wire Observability + Control Bounds

**Files:**
- Modify: `mori/runtime/loop.py`
- Test: `tests/test_loop_v02.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_loop_v02.py`:

```python
"""Tests for v0.2 loop — observability events and control bounds."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from mori.control.bounds import ControlBounds, ControlConfig
from mori.model.base import ModelAdapter
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import (
    ObservabilityConfig,
    RunStartEvent,
    RunEndEvent,
    StepStartEvent,
    StepEndEvent,
    ToolInvokeEvent,
    ToolResultEvent,
    BoundViolationEvent,
)
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import (
    Message,
    ModelResponse,
    RunStatus,
    ToolCall,
    TokenUsage,
)


def _text_response(text: str, input_tokens: int = 50, output_tokens: int = 20) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="end_turn",
    )


def _tool_response(tool_id: str, tool_name: str, arguments: dict) -> ModelResponse:
    return ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id=tool_id, name=tool_name, arguments=arguments)],
        ),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="tool_use",
    )


@pytest.fixture
def mock_model():
    model = AsyncMock(spec=ModelAdapter)
    model.model_id = "test-model"
    model.supports_tool_use = True
    model.max_context_tokens = 100000
    return model


@pytest.fixture
def registry_with_add():
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    return registry


async def test_loop_emits_run_events(mock_model, registry_with_add):
    """Loop should emit RunStartEvent and RunEndEvent."""
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))

    collected: list = []

    class CollectorSink:
        async def write(self, event):
            collected.append(event)
        async def write_batch(self, events):
            collected.extend(events)
        async def flush(self):
            pass
        async def close(self):
            pass

    obs = ObservabilityEngine(sinks=[CollectorSink()], config=ObservabilityConfig(buffer_size=100))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, observability=obs)
    result = await loop.run("test")

    event_types = [e.event_type for e in collected]
    assert "run.start" in event_types
    assert "run.end" in event_types


async def test_loop_emits_step_events(mock_model, registry_with_add):
    """Loop should emit StepStartEvent and StepEndEvent."""
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))

    collected: list = []

    class CollectorSink:
        async def write(self, event):
            collected.append(event)
        async def write_batch(self, events):
            collected.extend(events)
        async def flush(self):
            pass
        async def close(self):
            pass

    obs = ObservabilityEngine(sinks=[CollectorSink()], config=ObservabilityConfig(buffer_size=100))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, observability=obs)
    await loop.run("test")

    event_types = [e.event_type for e in collected]
    assert "step.start" in event_types
    assert "step.end" in event_types


async def test_loop_emits_tool_events(mock_model, registry_with_add):
    """Loop should emit ToolInvokeEvent and ToolResultEvent on tool calls."""
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_response("call_1", "add", {"a": 1, "b": 2}),
        _text_response("3"),
    ])

    collected: list = []

    class CollectorSink:
        async def write(self, event):
            collected.append(event)
        async def write_batch(self, events):
            collected.extend(events)
        async def flush(self):
            pass
        async def close(self):
            pass

    obs = ObservabilityEngine(sinks=[CollectorSink()], config=ObservabilityConfig(buffer_size=100))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, observability=obs)
    await loop.run("add 1+2")

    event_types = [e.event_type for e in collected]
    assert "tool.invoke" in event_types
    assert "tool.result" in event_types


async def test_loop_uses_control_bounds(mock_model, registry_with_add):
    """Loop should use ControlBounds instead of internal checks."""
    mock_model.invoke = AsyncMock(
        return_value=_tool_response("call_n", "add", {"a": 1, "b": 1})
    )

    control = ControlBounds(config=ControlConfig(max_steps=3))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, control=control)
    result = await loop.run("loop forever")

    assert result.status == RunStatus.FAILED
    assert result.total_steps == 3


async def test_loop_emits_bound_violation(mock_model, registry_with_add):
    """Loop should emit BoundViolationEvent when bounds are exceeded."""
    mock_model.invoke = AsyncMock(
        return_value=_tool_response("call_n", "add", {"a": 1, "b": 1})
    )

    collected: list = []

    class CollectorSink:
        async def write(self, event):
            collected.append(event)
        async def write_batch(self, events):
            collected.extend(events)
        async def flush(self):
            pass
        async def close(self):
            pass

    obs = ObservabilityEngine(sinks=[CollectorSink()], config=ObservabilityConfig(buffer_size=100))
    control = ControlBounds(config=ControlConfig(max_steps=2))
    loop = AgentLoop(model=mock_model, tools=registry_with_add, observability=obs, control=control)
    await loop.run("loop")

    event_types = [e.event_type for e in collected]
    assert "control.bound_violation" in event_types


async def test_loop_without_observability_still_works(mock_model, registry_with_add):
    """Loop should work fine without observability (backward compat with v0.1)."""
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))
    loop = AgentLoop(model=mock_model, tools=registry_with_add)
    result = await loop.run("test")
    assert result.status == RunStatus.COMPLETED


async def test_loop_without_control_uses_default(mock_model, registry_with_add):
    """Loop without explicit control bounds should use default limits."""
    mock_model.invoke = AsyncMock(return_value=_text_response("done"))
    loop = AgentLoop(model=mock_model, tools=registry_with_add)
    result = await loop.run("test")
    assert result.status == RunStatus.COMPLETED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_loop_v02.py -v`
Expected: FAIL — `AgentLoop` doesn't accept `observability` or `control` params

- [ ] **Step 3: Refactor AgentLoop**

Replace the entire contents of `mori/runtime/loop.py`:

```python
"""AgentLoop — the core agent execution loop."""

from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone
from typing import Any

from mori.control.bounds import BoundCheckResult, ControlBounds, ControlConfig
from mori.model.base import ModelAdapter
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import (
    BoundViolationEvent,
    MoriEvent,
    ObservabilityConfig,
    RunEndEvent,
    RunStartEvent,
    StepEndEvent,
    StepStartEvent,
    ToolInvokeEvent,
    ToolResultEvent,
)
from mori.runtime.result import RunResult
from mori.runtime.state import MoriState
from mori.tools.registry import ToolRegistry
from mori.types import (
    Message,
    ModelRequest,
    Phase,
    RunId,
    RunStatus,
    StepId,
    StepOutcome,
    ThreadId,
)


def _uid() -> str:
    return secrets.token_hex(12)


class AgentLoop:
    """Agent loop: plan → act → evaluate, with observability and control bounds."""

    def __init__(
        self,
        model: ModelAdapter,
        tools: ToolRegistry,
        observability: ObservabilityEngine | None = None,
        control: ControlBounds | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._obs = observability
        self._control = control or ControlBounds(config=ControlConfig())

    async def _emit(self, event: MoriEvent) -> None:
        if self._obs:
            await self._obs.emit(event)

    def _init_state(
        self,
        task: str,
        thread_id: ThreadId | None = None,
        context: dict[str, Any] | None = None,
    ) -> MoriState:
        now = datetime.now(timezone.utc)
        return MoriState(
            run_id=RunId(f"run_{_uid()}"),
            thread_id=thread_id or ThreadId(f"thread_{_uid()}"),
            task=task,
            context=context or {},
            messages=[Message(role="user", content=task)],
            status=RunStatus.RUNNING,
            started_at=now,
            last_progress_at=now,
        )

    def _assemble_request(self, state: MoriState) -> ModelRequest:
        tool_specs = self._tools.list_specs()
        return ModelRequest(
            messages=state.messages,
            tools=tool_specs if tool_specs else None,
        )

    async def _phase_plan(self, state: MoriState) -> None:
        request = self._assemble_request(state)
        response = await self._model.invoke(request)
        state.messages.append(response.message)
        state.total_input_tokens += response.usage.input_tokens
        state.total_output_tokens += response.usage.output_tokens

    async def _phase_act(self, state: MoriState) -> None:
        last_msg = state.messages[-1]
        if not last_msg.tool_calls:
            return

        for call in last_msg.tool_calls:
            now = datetime.now(timezone.utc)
            await self._emit(ToolInvokeEvent(
                event_id=f"evt_{_uid()}",
                timestamp=now,
                run_id=state.run_id,
                tool_name=call.name,
                source=self._tools.get_spec(call.name).source if self._tools.get_spec(call.name) else "native",
                arguments=call.arguments,
            ))

            result = await self._tools.invoke(call.name, call.arguments)

            await self._emit(ToolResultEvent(
                event_id=f"evt_{_uid()}",
                timestamp=datetime.now(timezone.utc),
                run_id=state.run_id,
                tool_name=call.name,
                success=result.success,
                latency_ms=result.latency_ms,
                error=result.error,
                result_preview=str(result.content)[:200] if result.content else None,
            ))

            content = result.content if result.success else f"ERROR: {result.error}"
            state.messages.append(
                Message(role="tool", content=content, tool_call_id=call.id)
            )
            state.total_tool_calls += 1

    def _phase_evaluate(self, state: MoriState) -> StepOutcome:
        last_msg = state.messages[-1]
        if last_msg.role == "tool":
            return StepOutcome.RETRY
        if last_msg.role == "assistant" and not last_msg.tool_calls:
            return StepOutcome.SUCCESS
        return StepOutcome.RETRY

    async def run(
        self,
        task: str,
        thread_id: ThreadId | None = None,
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        state = self._init_state(task, thread_id, context)
        start_time = time.monotonic()

        await self._emit(RunStartEvent(
            event_id=f"evt_{_uid()}",
            timestamp=datetime.now(timezone.utc),
            run_id=state.run_id,
            task=task,
            config={"max_steps": self._control._config.max_steps},
        ))

        while state.status == RunStatus.RUNNING:
            state.step_count += 1
            step_start = time.monotonic()
            step_id = StepId(f"step_{state.run_id}_{state.step_count:04d}")

            # Check bounds before executing
            bound_check = self._control.check_bounds(state)
            if not bound_check.ok:
                for bound in bound_check.violated_bounds:
                    await self._emit(BoundViolationEvent(
                        event_id=f"evt_{_uid()}",
                        timestamp=datetime.now(timezone.utc),
                        run_id=state.run_id,
                        bound_name=bound,
                        current_value=bound_check.current_values.get(bound.replace("max_", "").replace("_timeout", "_elapsed_sec"), 0),
                        limit_value=getattr(self._control._config, bound, 0),
                    ))
                state.status = RunStatus.FAILED
                break

            await self._emit(StepStartEvent(
                event_id=f"evt_{_uid()}",
                timestamp=datetime.now(timezone.utc),
                run_id=state.run_id,
                step_id=step_id,
                step_number=state.step_count,
                phase=Phase.PLAN,
            ))

            # Plan
            await self._phase_plan(state)

            # Act
            await self._phase_act(state)

            # Evaluate
            outcome = self._phase_evaluate(state)

            step_elapsed = (time.monotonic() - step_start) * 1000
            await self._emit(StepEndEvent(
                event_id=f"evt_{_uid()}",
                timestamp=datetime.now(timezone.utc),
                run_id=state.run_id,
                step_id=step_id,
                step_number=state.step_count,
                outcome=outcome,
                input_tokens=0,
                output_tokens=0,
                duration_ms=step_elapsed,
            ))

            if outcome == StepOutcome.SUCCESS:
                state.status = RunStatus.COMPLETED
                break

            self._control.record_progress()
            state.last_progress_at = datetime.now(timezone.utc)

        elapsed_ms = (time.monotonic() - start_time) * 1000

        await self._emit(RunEndEvent(
            event_id=f"evt_{_uid()}",
            timestamp=datetime.now(timezone.utc),
            run_id=state.run_id,
            status=state.status,
            total_steps=state.step_count,
            total_input_tokens=state.total_input_tokens,
            total_output_tokens=state.total_output_tokens,
            duration_ms=elapsed_ms,
        ))

        if self._obs:
            await self._obs.flush()

        return RunResult.from_state(state, duration_ms=elapsed_ms)
```

- [ ] **Step 4: Run v0.2 loop tests**

Run: `pytest tests/test_loop_v02.py -v`
Expected: all 7 tests PASS

- [ ] **Step 5: Run existing loop tests to check backward compat**

Run: `pytest tests/test_loop.py -v`
Expected: all tests PASS (AgentLoop still works without observability/control)

- [ ] **Step 6: Run full suite**

Run: `pytest tests/ -v --tb=short`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add mori/runtime/loop.py tests/test_loop_v02.py
git commit -m "refactor: wire observability events and control bounds into AgentLoop"
```

---

## Task 12: Builder API — .cli(), .mcp_server(), .sink()

**Files:**
- Modify: `mori/agent.py`
- Test: `tests/test_builder_v02.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_builder_v02.py`:

```python
"""Tests for v0.2 builder additions — .cli(), .mcp_server(), .sink()."""

from unittest.mock import AsyncMock, patch

import pytest

from mori import Mori
from mori.types import Message, ModelResponse, RunStatus, ToolCall, TokenUsage, ToolSource


def _text_response(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


def test_builder_cli():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .cli("search", command="rg", description="Search", args_format="flags")
            .build()
        )
        specs = agent.tools.list_specs()
        assert len(specs) == 1
        assert specs[0].name == "search"
        assert specs[0].source == ToolSource.CLI


def test_builder_multiple_cli():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .cli("rg", command="rg", description="Ripgrep", args_format="flags")
            .cli("git", command="git", description="Git", args_format="subcommand")
            .build()
        )
        specs = agent.tools.list_specs()
        assert len(specs) == 2


def test_builder_sink_stdout(tmp_path):
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .sink("stdout")
            .build()
        )
        assert agent._obs is not None


def test_builder_sink_jsonl(tmp_path):
    path = str(tmp_path / "traces.jsonl")
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .sink("jsonl", path=path)
            .build()
        )
        assert agent._obs is not None


def test_builder_config_feeds_control():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        MockAdapter.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .config(max_steps=10, idle_timeout_sec=60)
            .build()
        )
        assert agent._loop._control._config.max_steps == 10
        assert agent._loop._control._config.idle_timeout_sec == 60


async def test_builder_full_run_with_cli():
    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(
            return_value=_text_response("done")
        )
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .cli("echo", command="echo", description="Echo", args_format="positional")
            .sink("stdout")
            .config(max_steps=5)
            .build()
        )
        result = await agent.run("say hello")
        assert result.status == RunStatus.COMPLETED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_builder_v02.py -v`
Expected: FAIL ��� `.cli()` method doesn't exist yet

- [ ] **Step 3: Update agent.py**

Replace the entire contents of `mori/agent.py`:

```python
"""Mori — top-level API and builder."""

from __future__ import annotations

from typing import Any, Callable

from mori.control.bounds import ControlBounds, ControlConfig
from mori.model.anthropic import AnthropicAdapter
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import ObservabilityConfig
from mori.observability.sinks.jsonl import JsonlSink
from mori.observability.sinks.stdout import StdoutSink
from mori.runtime.loop import AgentLoop
from mori.runtime.result import RunResult
from mori.tools.registry import ToolRegistry
from mori.types import ThreadId


class MoriBuilder:
    """Fluent builder for constructing a Mori agent."""

    def __init__(self) -> None:
        self._model_adapter: Any = None
        self._tools: list[tuple[str, Callable[..., Any], str, dict[str, Any] | None]] = []
        self._cli_tools: list[dict[str, Any]] = []
        self._mcp_servers: list[dict[str, Any]] = []
        self._sinks: list[Any] = []
        self._config: dict[str, Any] = {}

    def model(
        self,
        provider: str,
        *,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        max_tokens: int = 4096,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> MoriBuilder:
        if provider == "anthropic":
            self._model_adapter = AnthropicAdapter(
                model=model, api_key=api_key, max_tokens=max_tokens, base_url=base_url,
            )
        else:
            raise ValueError(f"Unknown model provider: {provider}. Supported: anthropic")
        return self

    def tool(
        self,
        fn: Callable[..., Any],
        description: str,
        name: str | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> MoriBuilder:
        tool_name = name or fn.__name__
        self._tools.append((tool_name, fn, description, input_schema))
        return self

    def cli(
        self,
        name: str,
        command: str,
        description: str,
        args_format: str = "flags",
        args_schema: dict[str, Any] | None = None,
        shell: bool = False,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: float = 60.0,
        tags: list[str] | None = None,
    ) -> MoriBuilder:
        self._cli_tools.append({
            "name": name, "command": command, "description": description,
            "args_format": args_format, "args_schema": args_schema,
            "shell": shell, "cwd": cwd, "env": env, "timeout_sec": timeout_sec,
            "tags": tags,
        })
        return self

    def mcp_server(
        self,
        name: str,
        url: str,
        transport: str = "sse",
        auth: Any = None,
    ) -> MoriBuilder:
        self._mcp_servers.append({
            "name": name, "url": url, "transport": transport, "auth": auth,
        })
        return self

    def sink(self, sink_type: str, **kwargs: Any) -> MoriBuilder:
        if sink_type == "stdout":
            self._sinks.append(StdoutSink())
        elif sink_type == "jsonl":
            path = kwargs.get("path")
            if not path:
                raise ValueError("JsonlSink requires a 'path' argument")
            self._sinks.append(JsonlSink(path=path))
        else:
            raise ValueError(f"Unknown sink type: {sink_type}. Supported: stdout, jsonl")
        return self

    def config(self, **kwargs: Any) -> MoriBuilder:
        self._config.update(kwargs)
        return self

    def build(self) -> Mori:
        if self._model_adapter is None:
            raise ValueError("A model must be configured. Call .model() before .build()")

        # 1. Observability
        obs: ObservabilityEngine | None = None
        if self._sinks:
            obs = ObservabilityEngine(sinks=self._sinks, config=ObservabilityConfig())

        # 2. Control bounds
        control_fields = {
            k: v for k, v in self._config.items()
            if k in ControlConfig.model_fields
        }
        control = ControlBounds(config=ControlConfig(**control_fields))

        # 3. Tool registry
        registry = ToolRegistry()
        for tool_name, fn, desc, schema in self._tools:
            registry.register(tool_name, fn, description=desc, input_schema=schema)
        for cli in self._cli_tools:
            registry.register_cli(**cli)

        # 4. Agent loop
        loop = AgentLoop(
            model=self._model_adapter,
            tools=registry,
            observability=obs,
            control=control,
        )

        return Mori(loop=loop, tools=registry, observability=obs, mcp_configs=self._mcp_servers)


class Mori:
    """Top-level Mori agent."""

    def __init__(
        self,
        loop: AgentLoop,
        tools: ToolRegistry,
        observability: ObservabilityEngine | None = None,
        mcp_configs: list[dict[str, Any]] | None = None,
    ) -> None:
        self._loop = loop
        self._tools = tools
        self._obs = observability
        self._mcp_configs = mcp_configs or []
        self._mcp_connected = False

    @staticmethod
    def builder() -> MoriBuilder:
        return MoriBuilder()

    async def run(
        self,
        task: str,
        thread_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        # Lazy MCP connection
        if self._mcp_configs and not self._mcp_connected:
            for cfg in self._mcp_configs:
                await self._tools.register_mcp_server(**cfg)
            self._mcp_connected = True

        tid = ThreadId(thread_id) if thread_id else None
        return await self._loop.run(task, thread_id=tid, context=context)

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    async def close(self) -> None:
        if self._obs:
            await self._obs.close()
```

- [ ] **Step 4: Run builder v02 tests**

Run: `pytest tests/test_builder_v02.py -v`
Expected: all 7 tests PASS

- [ ] **Step 5: Run existing builder tests**

Run: `pytest tests/test_builder.py -v`
Expected: all 7 tests PASS

- [ ] **Step 6: Run full suite**

Run: `pytest tests/ -v --tb=short`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add mori/agent.py tests/test_builder_v02.py
git commit -m "feat: builder API — .cli(), .mcp_server(), .sink(), control bounds wiring"
```

---

## Task 13: v0.2 Exit Tests

**Files:**
- Create: `tests/test_integration_v02.py`

- [ ] **Step 1: Write exit tests**

Create `tests/test_integration_v02.py`:

```python
"""v0.2 exit tests — CLI tools + observability integration."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mori import Mori
from mori.types import (
    Message,
    ModelResponse,
    RunStatus,
    ToolCall,
    TokenUsage,
)


def _tool_response(tool_id: str, name: str, args: dict) -> ModelResponse:
    return ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id=tool_id, name=name, arguments=args)],
        ),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="tool_use",
    )


def _text_response(text: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=80, output_tokens=30),
        stop_reason="end_turn",
    )


async def test_v02_exit_test_cli_and_observability(tmp_path):
    """v0.2 exit test: agent uses CLI tool and events appear in JSONL."""
    traces_path = str(tmp_path / "traces.jsonl")

    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(
            side_effect=[
                _tool_response("call_1", "echo_tool", {"0": "hello from CLI"}),
                _text_response("The CLI tool returned: hello from CLI"),
            ]
        )
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .cli("echo_tool", command="echo", description="Echo text", args_format="positional")
            .sink("jsonl", path=traces_path)
            .config(max_steps=10)
            .build()
        )
        result = await agent.run("Echo something")
        await agent.close()

        assert result.status == RunStatus.COMPLETED
        assert result.total_tool_calls >= 1

        # Verify events in JSONL
        lines = Path(traces_path).read_text().strip().split("\n")
        events = [json.loads(line) for line in lines]
        event_types = [e["event_type"] for e in events]

        assert "run.start" in event_types
        assert "run.end" in event_types
        assert "tool.invoke" in event_types
        assert "tool.result" in event_types


async def test_v02_mixed_native_and_cli_tools(tmp_path):
    """Native and CLI tools coexist in same registry."""
    traces_path = str(tmp_path / "traces.jsonl")

    def add(a: int, b: int) -> int:
        return a + b

    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(
            side_effect=[
                _tool_response("call_1", "add", {"a": 3, "b": 5}),
                _tool_response("call_2", "echo_tool", {"0": "result is 8"}),
                _text_response("Added 3+5=8 and echoed it"),
            ]
        )
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(add, description="Add two numbers")
            .cli("echo_tool", command="echo", description="Echo", args_format="positional")
            .sink("jsonl", path=traces_path)
            .config(max_steps=10)
            .build()
        )
        result = await agent.run("Add 3+5 then echo the result")
        await agent.close()

        assert result.status == RunStatus.COMPLETED
        assert result.total_tool_calls == 2


async def test_v02_step_limit_with_bound_violation_event(tmp_path):
    """ControlBounds emits violation events on step limit."""
    traces_path = str(tmp_path / "traces.jsonl")

    with patch("mori.agent.AnthropicAdapter") as MockAdapter:
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(
            return_value=_tool_response("call_n", "echo_tool", {"0": "loop"})
        )
        MockAdapter.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .cli("echo_tool", command="echo", description="Echo", args_format="positional")
            .sink("jsonl", path=traces_path)
            .config(max_steps=3)
            .build()
        )
        result = await agent.run("loop forever")
        await agent.close()

        assert result.status == RunStatus.FAILED

        lines = Path(traces_path).read_text().strip().split("\n")
        events = [json.loads(line) for line in lines]
        event_types = [e["event_type"] for e in events]
        assert "control.bound_violation" in event_types
```

- [ ] **Step 2: Run exit tests**

Run: `pytest tests/test_integration_v02.py -v`
Expected: all 3 tests PASS

- [ ] **Step 3: Run full suite**

Run: `pytest tests/ -v --tb=short`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_v02.py
git commit -m "feat: v0.2 exit tests — CLI tools, observability, control bounds"
```

---

## Summary

| Task | What It Builds | Tests |
|------|---------------|-------|
| 1 | Observability event types, sink protocol, span context | ~15 |
| 2 | ControlBounds — limits, retry, idle detection | ~12 |
| 3 | CLI argument formatting (flags, positional, subcommand) | ~12 |
| 4 | CLIRunner — subprocess execution | ~9 |
| 5 | StdoutSink + JsonlSink | ~8 |
| 6 | ObservabilityEngine — buffered dispatch, trace, summary | ~9 |
| 7 | MCP schema cache with TTL | ~7 |
| 8 | MCPClient — JSON-RPC 2.0, schema cache, health | ~7 |
| 9 | Error rate tracking + result truncation in registry | ~7 |
| 10 | Registry extensions — register_cli, register_mcp_server, routing | ~6 |
| 11 | Loop refactor — observability events, control bounds | ~7 |
| 12 | Builder API �� .cli(), .mcp_server(), .sink() | ~7 |
| 13 | v0.2 exit tests — end-to-end integration | ~3 |

**Total:** ~109 new tests across 13 tasks.

**Parallelizable pairs:** Tasks 1-3 have no dependencies on each other. Tasks 4+5+6+7 are independent after their foundation tasks. Tasks 9-13 are sequential (integration work).
