"""Budget types for Mori v0.4."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from mori.types import MoriModel


class BudgetSlot(StrEnum):
    SYSTEM_PROMPT = "system_prompt"
    MEMORY = "memory"
    SKILL = "skill"
    TOOL_SCHEMAS = "tool_schemas"
    CONVERSATION = "conversation"
    GENERATION = "generation"


class BudgetConfig(MoriModel):
    total_context_tokens: int = 200_000
    compaction_threshold_pct: float = 0.85
    min_generation_tokens: int = 1000
    max_result_tokens: int = 4000
    disable_compaction: bool = False
    slot_overrides: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_overrides(self) -> BudgetConfig:
        if self.slot_overrides:
            total = sum(self.slot_overrides.values())
            if total > 1.0:
                raise ValueError(f"slot_overrides sum to {total:.3f}, must be <= 1.0")
        return self

    @model_validator(mode="after")
    def _validate_override_keys(self) -> BudgetConfig:
        valid = {s.value for s in BudgetSlot}
        unknown = set(self.slot_overrides) - valid
        if unknown:
            raise ValueError(f"slot_overrides contains unknown slots: {unknown}")
        return self


class ConsumeResult(MoriModel):
    slot: BudgetSlot
    consumed: int
    over_budget: bool


class RebalanceHints(MoriModel):
    extra_memory_tokens: int = 0
    extra_skill_tokens: int = 0


class SlotReport(MoriModel):
    slot: BudgetSlot
    allocated: int
    consumed: int
    pct_used: float


class BudgetReport(MoriModel):
    total_tokens: int
    total_consumed: int
    utilization: float
    slots: list[SlotReport]


class CompactionStage(StrEnum):
    RESULT_TRIM = "result_trim"
    SCHEMA_DEFER = "schema_defer"
    TURN_SNIP = "turn_snip"
    SKILL_DOWNGRADE = "skill_downgrade"
    MEMORY_PRUNE = "memory_prune"
    CONVERSATION_SUMMARIZE = "conversation_summarize"


class StageResult(MoriModel):
    stage: CompactionStage
    tokens_reclaimed: int
    ran: bool


class CompactionReport(MoriModel):
    stages: list[StageResult]
    total_tokens_reclaimed: int
    initial_utilization: float
    final_utilization: float


class CompactionModules(MoriModel):
    memory: Any | None = None
    skills: Any | None = None
    model: Any | None = None
    model_config = {"arbitrary_types_allowed": True}
