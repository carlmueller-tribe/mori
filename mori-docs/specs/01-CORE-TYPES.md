# 01: Core Types

**Status:** Draft v3
**Module:** `mori.types`
**Dependencies:** `pydantic`

---

## 1. Purpose

Shared vocabulary for the entire library. No external framework types. Mori types are self-contained and serializable. Tools are Python callables first, MCP second.

## 2. Identifiers

```python
from typing import NewType

RunId = NewType("RunId", str)            # "run_{ulid}"
StepId = NewType("StepId", str)          # "step_{run_ulid}_{seq:04d}"
TraceId = NewType("TraceId", str)        # "trace_{ulid}"
SkillId = NewType("SkillId", str)        # "{registry}:{name}:{version}"
ToolId = NewType("ToolId", str)          # "{source}:{tool_name}"
MemoryRecordId = NewType("MemoryRecordId", str)
PlanId = NewType("PlanId", str)
CheckpointId = NewType("CheckpointId", str)
ThreadId = NewType("ThreadId", str)
```

## 3. Enumerations

```python
from enum import Enum

class Phase(str, Enum):
    RETRIEVE = "retrieve"
    PLAN = "plan"
    VALIDATE = "validate"
    ACT = "act"
    OBSERVE = "observe"
    EVALUATE = "evaluate"
    UPDATE = "update"

class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

class StepOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    ESCALATE = "escalate"
    SKIP = "skip"

class MemoryLayer(str, Enum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PERSONALIZED = "personalized"

class DisclosureLevel(str, Enum):
    ABSTRACT = "abstract"
    SUMMARY = "summary"
    FULL = "full"

class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"

class ToolSource(str, Enum):
    NATIVE = "native"       # Python callable
    CLI = "cli"             # Shell command / subprocess
    MCP = "mcp"             # MCP server
    A2A = "a2a"             # Agent delegation
    OPENAPI = "openapi"     # OpenAPI endpoint

class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
```

## 4. Base Models

```python
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal, Callable, Any

class MoriModel(BaseModel):
    model_config = {"frozen": False, "extra": "forbid"}

class ImmutableModel(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}
```

### 4.1 Token Budget

```python
class TokenBudget(MoriModel):
    allocated: int
    consumed: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.allocated - self.consumed)

    @property
    def utilization(self) -> float:
        return self.consumed / self.allocated if self.allocated > 0 else 0.0
```

### 4.2 Message Types

```python
class Message(MoriModel):
    """A single message in the conversation."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict]
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list["ToolCall"] | None = None

class ToolCall(MoriModel):
    """A tool call request from the model."""
    id: str
    name: str
    arguments: dict

class TokenUsage(ImmutableModel):
    input_tokens: int
    output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens
```

### 4.3 Model Interaction Types

```python
class ModelRequest(MoriModel):
    messages: list[Message]
    tools: list["ToolSpec"] | None = None
    max_tokens: int = 4096
    temperature: float = 0.0
    stop_sequences: list[str] | None = None
    metadata: dict = Field(default_factory=dict)

class ModelResponse(MoriModel):
    message: Message
    usage: TokenUsage
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "stop_sequence"]
    raw: dict = Field(default_factory=dict)
```

### 4.4 Tool Types

A tool in Mori is a callable with a schema. It can come from anywhere: a plain Python function, an MCP server, an OpenAPI endpoint, or an agent delegation.

```python
class ToolSpec(MoriModel):
    """Description of a callable tool, regardless of source."""
    tool_id: ToolId
    name: str
    description: str
    input_schema: dict              # JSON Schema for arguments
    source: ToolSource = ToolSource.NATIVE
    server_id: str | None = None    # Only for MCP/A2A/OpenAPI sources
    tags: list[str] = Field(default_factory=list)

class ToolResult(MoriModel):
    """Result from any tool invocation."""
    tool_name: str
    call_id: str
    success: bool
    content: str | list[dict]
    error: str | None = None
    latency_ms: float = 0.0
    metadata: dict = Field(default_factory=dict)

class RegisteredTool(MoriModel):
    """A tool registered in the tool registry with its callable."""
    spec: ToolSpec
    fn: Callable[..., Any] | None = None    # The actual callable (None for remote tools)
    model_config = {"arbitrary_types_allowed": True}
```

### 4.5 Memory Types

```python
class MemoryRecord(MoriModel):
    record_id: MemoryRecordId
    layer: MemoryLayer
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    ttl_seconds: int | None = None
    provenance: str | None = None
    confidence: float = 1.0
    embedding: list[float] | None = None

class MemorySlice(MoriModel):
    records: list[MemoryRecord]
    total_tokens: int
    query: str
    layers_searched: list[MemoryLayer]
    truncated: bool = False
    conflicts: list[tuple[MemoryRecordId, MemoryRecordId]] = Field(default_factory=list)

class WriteReceipt(MoriModel):
    record_ids: list[MemoryRecordId]
    layer: MemoryLayer
    timestamp: datetime
```

### 4.6 Skill Types

```python
class SkillManifest(MoriModel):
    skill_id: SkillId
    name: str
    version: str
    description: str
    capabilities: list[str]
    scope: dict = Field(default_factory=dict)
    preconditions: "SkillPreconditions"
    constraints: dict = Field(default_factory=dict)
    triggers: "SkillTriggers"
    progressive_disclosure: "SkillDisclosure"

class SkillPreconditions(MoriModel):
    tools_required: list[str] = Field(default_factory=list)
    memory_required: list[str] = Field(default_factory=list)
    min_context_tokens: int = 0

class SkillTriggers(MoriModel):
    semantic: list[str] = Field(default_factory=list)
    structural: list[str] = Field(default_factory=list)

class SkillDisclosure(MoriModel):
    abstract: str
    summary: str
    full_path: str

class SkillCandidate(MoriModel):
    manifest: SkillManifest
    match_score: float
    compatibility: "CompatibilityReport"

class CompatibilityReport(MoriModel):
    tools_available: bool
    memory_available: bool
    context_sufficient: bool
    issues: list[str] = Field(default_factory=list)

class SkillPayload(MoriModel):
    skill_id: SkillId
    disclosure_level: DisclosureLevel
    content: str
    token_count: int
    constraints: dict = Field(default_factory=dict)

class BoundSkill(MoriModel):
    skill_id: SkillId
    payload: SkillPayload
    tool_bindings: dict[str, ToolId]
    agent_bindings: dict[str, str]
    unresolved: list[str] = Field(default_factory=list)
```

### 4.7 Plan Types

```python
class PlanPhase(MoriModel):
    phase_id: str
    name: str
    description: str
    skill_id: SkillId | None = None
    tool_bindings: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    status: Literal["pending", "active", "completed", "failed", "skipped"] = "pending"
    attempts: int = 0
    max_attempts: int = 3

class PlanObject(MoriModel):
    plan_id: PlanId
    task_description: str
    phases: list[PlanPhase]
    current_phase_index: int = 0
    status: RunStatus = RunStatus.PENDING
    created_at: datetime
    updated_at: datetime
```

### 4.8 Checkpoint Types

```python
class Checkpoint(MoriModel):
    checkpoint_id: CheckpointId
    thread_id: ThreadId
    run_id: RunId
    step_count: int
    state: dict                     # Serialized MoriState
    created_at: datetime
    size_bytes: int
```

## 5. Error Hierarchy

```python
class MoriError(Exception):
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}

# Runtime errors
class StepLimitExceeded(MoriError): pass
class CostLimitExceeded(MoriError): pass
class TimeoutExceeded(MoriError): pass
class RunCancelled(MoriError): pass

# Memory errors
class MemoryError_(MoriError): pass
class RecordNotFound(MemoryError_): pass
class RetrievalError(MemoryError_): pass

# Skill errors
class SkillError(MoriError): pass
class SkillNotFound(SkillError): pass
class SkillBindingError(SkillError): pass

# Tool/protocol errors
class ToolError(MoriError): pass
class ToolInvocationError(ToolError): pass
class ServerUnavailable(ToolError): pass
class SchemaValidationError(ToolError): pass

# Permission errors
class PermissionDenied(MoriError): pass
class ApprovalRequired(MoriError): pass

# Budget errors
class BudgetExhausted(MoriError): pass
```

## 6. Common Interfaces

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class Closeable(Protocol):
    async def close(self) -> None: ...

@runtime_checkable
class HealthCheckable(Protocol):
    async def health_check(self) -> "HealthStatus": ...

class HealthStatus(MoriModel):
    healthy: bool
    component: str
    message: str = ""
    latency_ms: float | None = None
```

## 7. Test Criteria

- [ ] All types round-trip through JSON serialization
- [ ] MoriModel rejects extra fields
- [ ] ImmutableModel raises on mutation
- [ ] TokenBudget.remaining never returns negative
- [ ] ToolSpec correctly represents all source types (native, MCP, A2A, OpenAPI)
- [ ] RegisteredTool can hold both a spec and a callable
- [ ] All error types are catchable at MoriError level
