"""Permission system types — identities, resources, rules, results."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from mori.types import MoriModel, PermissionDecision


class IdentityType(StrEnum):
    USER = "user"
    AGENT = "agent"
    SKILL = "skill"
    SERVICE = "service"
    SYSTEM = "system"


class Identity(MoriModel):
    id: str
    name: str
    type: IdentityType
    groups: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceType(StrEnum):
    TOOL = "tool"
    SKILL = "skill"
    MEMORY_LAYER = "memory_layer"
    MCP_SERVER = "mcp_server"
    AGENT = "agent"
    FILE_PATH = "file_path"
    NETWORK_DOMAIN = "network_domain"


class Resource(MoriModel):
    type: ResourceType
    id: str
    owner: str | None = None
    group: str | None = None


class Permission(StrEnum):
    READ = "r"
    WRITE = "w"
    EXECUTE = "x"


class ConditionType(StrEnum):
    RISK_CATEGORY = "risk_category"
    STEP_COUNT = "step_count"
    TOTAL_TOKENS = "total_tokens"
    TIME_OF_DAY = "time_of_day"
    TOOL_ERROR_RATE = "tool_error_rate"


class Condition(MoriModel):
    type: ConditionType
    operator: Literal["eq", "gt", "lt", "gte", "lte", "in", "not_in"]
    value: Any


class ResourcePattern(MoriModel):
    type: ResourceType | Literal["*"]
    pattern: str


class IdentityPattern(MoriModel):
    match: Literal["identity", "group", "type", "any"]
    value: str


class PermissionRule(MoriModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    resource: ResourcePattern
    identity: IdentityPattern
    permissions: str  # "rwx", "r--", "r-x"
    effect: Literal["allow", "deny", "escalate"]
    priority: int = 100
    conditions: list[Condition] = Field(default_factory=list)


class PermissionResult(MoriModel):
    decision: PermissionDecision
    rule_applied: PermissionRule | None = None
    explanation: str = ""


class PermissionExplanation(MoriModel):
    identity: Identity
    resource: Resource
    permission: Permission
    decision: PermissionDecision
    rules_checked: list[PermissionRule]
    rule_applied: PermissionRule | None
    reason: str


class PermissionConfig(MoriModel):
    rules: list[PermissionRule] = Field(default_factory=list)
    default_decision: PermissionDecision = PermissionDecision.DENY
    audit_all_checks: bool = True
