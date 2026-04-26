"""Shared vocabulary for the Mori library."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Callable, Literal, NewType

from pydantic import BaseModel, Field

# ── Identifiers ──────────────────────────────────────────────

RunId = NewType("RunId", str)
StepId = NewType("StepId", str)
TraceId = NewType("TraceId", str)
SkillId = NewType("SkillId", str)
ToolId = NewType("ToolId", str)
MemoryRecordId = NewType("MemoryRecordId", str)
PlanId = NewType("PlanId", str)
CheckpointId = NewType("CheckpointId", str)
ThreadId = NewType("ThreadId", str)


# ── Enumerations ─────────────────────────────────────────────

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
    NATIVE = "native"
    CLI = "cli"
    MCP = "mcp"
    A2A = "a2a"
    OPENAPI = "openapi"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ── Base Models ──────────────────────────────────────────────

class MoriModel(BaseModel):
    model_config = {"frozen": False, "extra": "forbid"}


class ImmutableModel(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}


# ── Token Budget ─────────────────────────────────────────────

class TokenBudget(MoriModel):
    allocated: int
    consumed: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.allocated - self.consumed)

    @property
    def utilization(self) -> float:
        return self.consumed / self.allocated if self.allocated > 0 else 0.0


# ── Message Types ────────────────────────────────────────────

class ToolCall(MoriModel):
    id: str
    name: str
    arguments: dict[str, Any]


class Message(MoriModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]]
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None


class TokenUsage(ImmutableModel):
    input_tokens: int
    output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


# ── Model Interaction Types ──────────────────────────────────

class ToolSpec(MoriModel):
    tool_id: ToolId
    name: str
    description: str
    input_schema: dict[str, Any]
    source: ToolSource = ToolSource.NATIVE
    server_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class ModelRequest(MoriModel):
    messages: list[Message]
    tools: list[ToolSpec] | None = None
    max_tokens: int = 4096
    temperature: float = 0.0
    stop_sequences: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(MoriModel):
    message: Message
    usage: TokenUsage
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "stop_sequence"]
    raw: dict[str, Any] = Field(default_factory=dict)


# ── Tool Types ───────────────────────────────────────────────

class ToolResult(MoriModel):
    tool_name: str
    call_id: str
    success: bool
    content: str | list[dict[str, Any]]
    error: str | None = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class RegisteredTool(MoriModel):
    spec: ToolSpec
    fn: Callable[..., Any] | None = None
    model_config = {"frozen": False, "extra": "forbid", "arbitrary_types_allowed": True}


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


# ── Memory Config & Lifecycle ────────────────────────────────

class MemoryConfig(MoriModel):
    default_ttl_seconds: dict[MemoryLayer, int | None] = Field(default_factory=lambda: {
        MemoryLayer.WORKING: 3600,
        MemoryLayer.EPISODIC: None,
        MemoryLayer.SEMANTIC: None,
        MemoryLayer.PERSONALIZED: None,
    })
    max_records_per_layer: dict[MemoryLayer, int] = Field(default_factory=lambda: {
        MemoryLayer.WORKING: 200,
        MemoryLayer.EPISODIC: 10_000,
        MemoryLayer.SEMANTIC: 50_000,
        MemoryLayer.PERSONALIZED: 5_000,
    })
    deduplication_threshold: float = 0.95
    conflict_resolution: Literal["highest_confidence", "most_recent", "keep_all"] = "highest_confidence"
    embedding_dimensions: int = 1536
    auto_forget_interval_sec: float = 300.0


class MemoryFilters(MoriModel):
    min_confidence: float | None = None
    max_age_seconds: int | None = None
    provenance: str | None = None
    metadata_match: dict[str, Any] | None = None
    exclude_ids: list[MemoryRecordId] = Field(default_factory=list)


class ForgetPolicy(MoriModel):
    expire_ttl: bool = True
    prune_below_confidence: float | None = 0.2
    deduplicate: bool = True
    max_records_per_layer: dict[MemoryLayer, int] | None = None


class ForgetReport(MoriModel):
    expired: int
    pruned: int
    deduplicated: int
    total_deleted: int


class MemoryStats(MoriModel):
    total_records: int
    records_per_layer: dict[MemoryLayer, int]
    estimated_tokens_per_layer: dict[MemoryLayer, int]
    oldest_record_age_seconds: dict[MemoryLayer, float | None]
    newest_record_age_seconds: dict[MemoryLayer, float | None]


# ── Error Hierarchy ──────────────────────────────────────────

class MoriError(Exception):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class StepLimitExceeded(MoriError):
    pass


class CostLimitExceeded(MoriError):
    pass


class TimeoutExceeded(MoriError):
    pass


class RunCancelled(MoriError):
    pass


class ToolError(MoriError):
    pass


class ToolInvocationError(ToolError):
    pass


class SchemaValidationError(ToolError):
    pass


class ServerUnavailable(ToolError):
    pass
