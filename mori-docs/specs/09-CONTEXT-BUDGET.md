# 09: Context Budget Manager

**Status:** Draft v3.2
**Module:** `mori.budget`
**Dependencies:** Spec 01

---

## 1. Purpose

Arbitrate the scarcest resource: the model's context window. Memory retrieval, skill loading, tool schemas, conversation history, and generation headroom all compete for the same finite token budget.

The Budget Manager does two things: allocate token budgets across functional slots, and run a graduated compaction pipeline when the context exceeds capacity. Cheap strategies run first. Expensive strategies (model calls to summarize) run only when cheap ones fail to reclaim enough space.

## 2. Interface

```python
class BudgetManager:

    def __init__(self, total_context_tokens: int, config: BudgetConfig) -> None: ...

    # Allocation
    def get_allocation(self, slot: BudgetSlot) -> TokenBudget: ...
    def get_all_allocations(self) -> dict[BudgetSlot, TokenBudget]: ...
    def remaining_total(self) -> int: ...

    # Consumption
    def consume(self, slot: BudgetSlot, tokens: int) -> ConsumeResult: ...
    def release(self, slot: BudgetSlot, tokens: int) -> None: ...
    def reset_slot(self, slot: BudgetSlot) -> None: ...

    # Rebalancing
    def rebalance(self, phase: Phase, hints: RebalanceHints | None = None) -> dict[BudgetSlot, TokenBudget]: ...

    # Compaction
    async def compact(self, state: "MoriState", modules: "CompactionModules") -> CompactionReport:
        """Run the graduated compaction pipeline until context fits or all stages exhausted."""

    def needs_compaction(self) -> bool:
        """True when total consumed exceeds compaction_threshold_pct of total_context_tokens."""

    # Reporting
    def assemble_budget_report(self) -> BudgetReport: ...
```

## 3. Configuration

```python
class BudgetSlot(str, Enum):
    SYSTEM_PROMPT = "system_prompt"
    MEMORY = "memory"
    SKILL = "skill"
    TOOL_SCHEMAS = "tool_schemas"
    CONVERSATION = "conversation"
    GENERATION = "generation"

class BudgetConfig(MoriModel):
    base_allocations: dict[BudgetSlot, float] = {
        BudgetSlot.SYSTEM_PROMPT: 0.10,
        BudgetSlot.MEMORY: 0.20,
        BudgetSlot.SKILL: 0.15,
        BudgetSlot.TOOL_SCHEMAS: 0.10,
        BudgetSlot.CONVERSATION: 0.30,
        BudgetSlot.GENERATION: 0.15,
    }
    phase_overrides: dict[Phase, dict[BudgetSlot, float]] = {
        Phase.PLAN: {BudgetSlot.MEMORY: 0.25, BudgetSlot.CONVERSATION: 0.30, BudgetSlot.SKILL: 0.10},
        Phase.ACT: {BudgetSlot.SKILL: 0.20, BudgetSlot.TOOL_SCHEMAS: 0.15, BudgetSlot.MEMORY: 0.15},
    }
    min_generation_tokens: int = 1000
    allow_over_budget: bool = True
    compaction_threshold_pct: float = 0.85    # Trigger compaction at 85% utilization
    max_result_tokens: int = 4000             # Cap per-tool-result size
```

## 4. Rebalance Hints

```python
class RebalanceHints(MoriModel):
    active_skill_tokens: int | None = None
    pending_tool_count: int | None = None
    memory_pressure: float | None = None
    conversation_length_tokens: int | None = None
```

## 5. Consume Result

```python
class ConsumeResult(MoriModel):
    ok: bool
    slot: BudgetSlot
    tokens_consumed: int
    tokens_remaining: int
    over_budget_by: int = 0
```

## 6. Budget Report

```python
class BudgetReport(MoriModel):
    total_context_tokens: int
    slots: dict[BudgetSlot, SlotReport]
    total_consumed: int
    total_remaining: int
    utilization: float
    compaction_runs: int = 0
    last_compaction: CompactionReport | None = None

class SlotReport(MoriModel):
    allocated: int
    consumed: int
    remaining: int
    utilization: float
    over_budget: bool
```

## 7. Rebalancing Algorithm

1. Start with `base_allocations` applied to `total_context_tokens`
2. Apply `phase_overrides` for the current phase (replace specified slots, keep others)
3. Normalize so allocations sum to 1.0
4. Apply `RebalanceHints` (shrink slots with known small content, redistribute)
5. Enforce `min_generation_tokens` (steal from largest non-generation slot if needed)
6. Round all allocations to integer token counts
7. Return the new allocation map

Rebalancing does NOT reset consumption. Over-budget slots are flagged in BudgetReport.

## 8. Compaction Pipeline

The key insight from production agent systems: no single compaction strategy handles all types of context pressure. Cheap strategies run first. Each stage targets a different pressure type. The pipeline stops as soon as utilization drops below the threshold.

### 8.1 Pipeline Stages

```python
class CompactionStage(str, Enum):
    RESULT_TRIM = "result_trim"             # Stage 1: cheapest
    SCHEMA_DEFER = "schema_defer"           # Stage 2
    TURN_SNIP = "turn_snip"                 # Stage 3
    SKILL_DOWNGRADE = "skill_downgrade"     # Stage 4
    MEMORY_PRUNE = "memory_prune"           # Stage 5
    CONVERSATION_SUMMARIZE = "conv_summarize"  # Stage 6: most expensive
```

| Stage | What It Does | Cost | Target Slot |
|-------|-------------|------|-------------|
| 1. Result Trim | Truncate oversized tool results to `max_result_tokens` | Zero (string truncation) | CONVERSATION |
| 2. Schema Defer | Replace full tool schemas with name+description only for tools not used in recent N steps | Zero (filter) | TOOL_SCHEMAS |
| 3. Turn Snip | Drop tool call/result pairs from oldest turns, keeping only assistant text | Zero (filter) | CONVERSATION |
| 4. Skill Downgrade | Reduce active skill from FULL to SUMMARY disclosure | Zero (string swap) | SKILL |
| 5. Memory Prune | Re-retrieve memory with halved token budget, drop low-confidence records | Cheap (backend query) | MEMORY |
| 6. Conversation Summarize | Call the model to summarize the oldest N turns into a single summary message | Expensive (model call) | CONVERSATION |

### 8.2 Pipeline Execution

```python
async def compact(self, state: MoriState, modules: CompactionModules) -> CompactionReport:
    """Run stages in order until context fits or all stages exhausted."""
    report = CompactionReport()

    for stage in CompactionStage:
        if not self.needs_compaction():
            break

        tokens_before = self.remaining_total()
        await self._run_stage(stage, state, modules)
        tokens_reclaimed = self.remaining_total() - tokens_before

        report.stages_run.append(StageResult(
            stage=stage,
            tokens_reclaimed=tokens_reclaimed,
        ))

    report.final_utilization = 1.0 - (self.remaining_total() / self.total_context_tokens)
    return report
```

### 8.3 Compaction Modules

The pipeline needs access to specific modules for certain stages. These are passed in rather than stored, keeping the BudgetManager decoupled.

```python
class CompactionModules(MoriModel):
    """References to modules the compaction pipeline can call."""
    memory: "MemoryModule | None" = None    # For Stage 5 (re-retrieve)
    skills: "SkillsModule | None" = None    # For Stage 4 (downgrade)
    model: "ModelAdapter | None" = None     # For Stage 6 (summarize)
    model_config = {"arbitrary_types_allowed": True}
```

### 8.4 Compaction Report

```python
class CompactionReport(MoriModel):
    stages_run: list[StageResult] = Field(default_factory=list)
    total_tokens_reclaimed: int = 0
    final_utilization: float = 0.0

class StageResult(MoriModel):
    stage: CompactionStage
    tokens_reclaimed: int
```

## 9. Integration with Runtime

The runtime calls the compaction pipeline at one point: before the plan phase (model call).

```python
# In AgentLoop._execute_step():
if self.budget and self.budget.needs_compaction():
    report = await self.budget.compact(state, CompactionModules(
        memory=self.memory,
        skills=self.skills,
        model=self.model,
    ))
    await self._emit(CompactionEvent(report=report))
```

This mirrors the production pattern: compaction runs before every model call, cheapest strategies first, stopping as soon as the context fits.

## 10. Test Criteria

- [ ] Base allocations summing to > 1.0 raise a validation error
- [ ] get_allocation returns correct token counts
- [ ] consume tracks tokens and reports over-budget
- [ ] release frees tokens back to the slot
- [ ] reset_slot zeroes consumption
- [ ] rebalance with no phase overrides returns base allocations
- [ ] rebalance with phase overrides adjusts specified slots and normalizes
- [ ] min_generation_tokens is enforced even under pressure
- [ ] RebalanceHints reduce allocation for known-small slots
- [ ] BudgetReport correctly flags over-budget slots
- [ ] needs_compaction() triggers at correct threshold
- [ ] Pipeline runs stages in order (cheapest first)
- [ ] Pipeline stops early when utilization drops below threshold
- [ ] Result Trim truncates oversized tool outputs
- [ ] Schema Defer removes full schemas for unused tools
- [ ] Turn Snip drops tool details from old turns
- [ ] Skill Downgrade reduces disclosure level
- [ ] Memory Prune re-retrieves with tighter budget
- [ ] Conversation Summarize produces a valid summary message
- [ ] CompactionReport correctly tracks tokens reclaimed per stage
- [ ] Concurrent consume calls produce consistent totals
