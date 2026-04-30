"""Skill types for Mori v0.4."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import Field
from mori.types import DisclosureLevel, MoriModel, ToolSpec


class SkillManifest(MoriModel):
    name: str
    version: str
    description: str
    capabilities: list[str] = Field(default_factory=list)
    scope: dict[str, Any] = Field(default_factory=dict)
    preconditions: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)
    triggers: dict[str, Any] = Field(default_factory=dict)
    progressive_disclosure: dict[str, Any] = Field(default_factory=dict)
    skill_dir: str = ""


class CompatibilityReport(MoriModel):
    tools_satisfied: bool
    missing_tools: list[str] = Field(default_factory=list)
    context_fits: bool
    required_tokens: int


class SkillCandidate(MoriModel):
    manifest: SkillManifest
    score: float
    compatibility_report: CompatibilityReport


class SkillPayload(MoriModel):
    skill_id: str
    disclosure_level: DisclosureLevel
    content: str
    token_estimate: int


class BoundSkill(MoriModel):
    payload: SkillPayload
    resolved_tools: dict[str, ToolSpec] = Field(default_factory=dict)
    unresolved: list[str] = Field(default_factory=list)
    model_config = {"arbitrary_types_allowed": True, "frozen": False, "extra": "forbid"}


class SkillExecutionOutcome(MoriModel):
    skill_id: str
    run_id: str
    success: bool
    steps_taken: int
    failure_reason: str | None = None
    timestamp: datetime


class SkillHealthReport(MoriModel):
    skill_id: str
    total_runs: int
    success_rate: float
    avg_steps: float
    common_failures: list[str] = Field(default_factory=list)
    last_used: datetime | None = None
    stale: bool


class SkillValidationError(Exception):
    def __init__(self, message: str, path: str = "") -> None:
        super().__init__(message)
        self.path = path
