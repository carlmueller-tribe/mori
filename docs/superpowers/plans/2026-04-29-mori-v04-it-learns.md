# Mori v0.4 "It Learns" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Skills Module (filesystem skill discovery, loading, binding) and Budget Manager (per-slot context tracking + 6-stage compaction pipeline) to the Mori agent library.

**Architecture:** Two new packages (`mori/budget/`, `mori/skills/`) built independently then wired into `AgentLoop` via an expanded `_phase_retrieve` and a new `_pre_plan_compact` call. Builder gets `.skill_registry()` and `.budget()`; existing agents are unaffected when neither is called.

**Tech Stack:** Python 3.11, pydantic v2, pyyaml (new dep added to pyproject.toml), anyio — no new network dependencies.

---

## File Map

**Create:**
- `mori/budget/__init__.py`
- `mori/budget/types.py`
- `mori/budget/manager.py`
- `mori/skills/__init__.py`
- `mori/skills/types.py`
- `mori/skills/parser.py`
- `mori/skills/registry.py`
- `mori/skills/module.py`
- `skills/bug-fix/manifest.yaml` + `skills/bug-fix/SKILL.md`
- `skills/code-review/manifest.yaml` + `skills/code-review/SKILL.md`
- `skills/test-generation/manifest.yaml` + `skills/test-generation/SKILL.md`
- `examples/skills_and_budget.py`
- `tests/test_budget_types.py`
- `tests/test_budget_manager.py`
- `tests/test_skill_types.py`
- `tests/test_skill_parser.py`
- `tests/test_skill_registry.py`
- `tests/test_skills_module.py`
- `tests/test_loop_v04.py`
- `tests/test_builder_v04.py`
- `tests/test_integration_v04.py`

**Modify:**
- `pyproject.toml` — add `pyyaml>=6.0`
- `mori/observability/events.py` — add `SkillDiscoverEvent`, `SkillLoadEvent`, `BudgetRebalanceEvent`, `CompactionEvent`
- `mori/runtime/state.py` — add `active_skill_payload: Any | None = None`
- `mori/runtime/loop.py` — expand `_phase_retrieve`, add `_pre_plan_compact`, update `_assemble_request`, add `_skills`/`_budget` to `__init__`
- `mori/agent.py` — add `.skill_registry()`, `.budget()` builder methods + `Mori.skills`/`Mori.budget` properties

---

### Task 1: Budget Types

**Files:**
- Create: `mori/budget/__init__.py`
- Create: `mori/budget/types.py`
- Create: `tests/test_budget_types.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_budget_types.py
import pytest
from pydantic import ValidationError
from mori.budget.types import (
    BudgetSlot, BudgetConfig, ConsumeResult, RebalanceHints,
    SlotReport, BudgetReport, CompactionStage, StageResult,
    CompactionReport, CompactionModules,
)

def test_budget_slot_values():
    assert BudgetSlot.SYSTEM_PROMPT == "system_prompt"
    assert BudgetSlot.GENERATION == "generation"

def test_budget_config_defaults():
    cfg = BudgetConfig()
    assert cfg.total_context_tokens == 200_000
    assert cfg.compaction_threshold_pct == 0.85
    assert cfg.min_generation_tokens == 1000
    assert cfg.max_result_tokens == 4000
    assert cfg.disable_compaction is False
    assert cfg.slot_overrides == {}

def test_budget_config_slot_overrides_exceeding_1_raises():
    with pytest.raises(ValidationError):
        BudgetConfig(slot_overrides={
            "system_prompt": 0.20,
            "memory": 0.25,
            "skill": 0.20,
            "tool_schemas": 0.15,
            "conversation": 0.35,
            "generation": 0.20,
        })

def test_consume_result():
    r = ConsumeResult(slot=BudgetSlot.MEMORY, consumed=500, over_budget=False)
    assert r.slot == BudgetSlot.MEMORY
    assert r.consumed == 500
    assert r.over_budget is False

def test_compaction_report_totals():
    stages = [
        StageResult(stage=CompactionStage.RESULT_TRIM, tokens_reclaimed=200, ran=True),
        StageResult(stage=CompactionStage.SCHEMA_DEFER, tokens_reclaimed=0, ran=False),
    ]
    report = CompactionReport(
        stages=stages,
        total_tokens_reclaimed=200,
        initial_utilization=0.90,
        final_utilization=0.82,
    )
    assert report.total_tokens_reclaimed == 200
    assert report.final_utilization == 0.82

def test_compaction_modules_arbitrary_types():
    class Fake:
        pass
    m = CompactionModules(memory=Fake(), skills=None, model=None)
    assert m.memory is not None
    assert m.skills is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_budget_types.py -v
```
Expected: `ModuleNotFoundError: No module named 'mori.budget'`

- [ ] **Step 3: Create `mori/budget/__init__.py`**

```python
# mori/budget/__init__.py
```
(empty)

- [ ] **Step 4: Create `mori/budget/types.py`**

```python
"""Budget types for Mori v0.4."""
from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import Field, model_validator
from mori.types import MoriModel


class BudgetSlot(str, Enum):
    SYSTEM_PROMPT = "system_prompt"
    MEMORY        = "memory"
    SKILL         = "skill"
    TOOL_SCHEMAS  = "tool_schemas"
    CONVERSATION  = "conversation"
    GENERATION    = "generation"


class BudgetConfig(MoriModel):
    total_context_tokens: int = 200_000
    compaction_threshold_pct: float = 0.85
    min_generation_tokens: int = 1000
    max_result_tokens: int = 4000
    disable_compaction: bool = False
    slot_overrides: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_overrides(self) -> BudgetConfig:
        if self.slot_overrides and sum(self.slot_overrides.values()) > 1.0:
            raise ValueError(
                f"slot_overrides sum to {sum(self.slot_overrides.values()):.3f}, must be <= 1.0"
            )
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


class CompactionStage(str, Enum):
    RESULT_TRIM             = "result_trim"
    SCHEMA_DEFER            = "schema_defer"
    TURN_SNIP               = "turn_snip"
    SKILL_DOWNGRADE         = "skill_downgrade"
    MEMORY_PRUNE            = "memory_prune"
    CONVERSATION_SUMMARIZE  = "conversation_summarize"


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
    model_config = {"arbitrary_types_allowed": True, "frozen": False, "extra": "forbid"}
```

- [ ] **Step 5: Run tests — expect pass**

```
pytest tests/test_budget_types.py -v
```
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add mori/budget/__init__.py mori/budget/types.py tests/test_budget_types.py
git commit -m "feat: budget types — BudgetSlot, BudgetConfig, compaction report types"
```

---

### Task 2: BudgetManager Core

**Files:**
- Create: `mori/budget/manager.py`
- Create: `tests/test_budget_manager.py`

- [ ] **Step 1: Write failing tests for core manager (no compaction)**

```python
# tests/test_budget_manager.py
import pytest
from mori.budget.types import BudgetSlot, BudgetConfig, RebalanceHints
from mori.budget.manager import BudgetManager
from mori.types import Phase


@pytest.fixture
def mgr():
    return BudgetManager(BudgetConfig(total_context_tokens=100_000))


def test_get_allocation_system_prompt(mgr):
    b = mgr.get_allocation(BudgetSlot.SYSTEM_PROMPT)
    assert b.allocated == 10_000  # 10% of 100k


def test_get_allocation_generation(mgr):
    b = mgr.get_allocation(BudgetSlot.GENERATION)
    assert b.allocated == 15_000  # 15% of 100k


def test_consume_tracks_usage(mgr):
    result = mgr.consume(BudgetSlot.MEMORY, 500)
    assert result.consumed == 500
    assert result.over_budget is False
    assert mgr.get_allocation(BudgetSlot.MEMORY).consumed == 500


def test_consume_flags_over_budget(mgr):
    result = mgr.consume(BudgetSlot.SKILL, 20_000)  # slot is 15k
    assert result.over_budget is True


def test_release_frees_tokens(mgr):
    mgr.consume(BudgetSlot.MEMORY, 1000)
    mgr.release(BudgetSlot.MEMORY, 400)
    assert mgr.get_allocation(BudgetSlot.MEMORY).consumed == 600


def test_release_never_goes_negative(mgr):
    mgr.release(BudgetSlot.MEMORY, 9999)
    assert mgr.get_allocation(BudgetSlot.MEMORY).consumed == 0


def test_reset_slot(mgr):
    mgr.consume(BudgetSlot.CONVERSATION, 5000)
    mgr.reset_slot(BudgetSlot.CONVERSATION)
    assert mgr.get_allocation(BudgetSlot.CONVERSATION).consumed == 0


def test_rebalance_no_overrides(mgr):
    budgets = mgr.rebalance(Phase.RETRIEVE)
    total_allocated = sum(b.allocated for b in budgets.values())
    assert abs(total_allocated - 100_000) <= 100  # rounding tolerance


def test_rebalance_plan_phase(mgr):
    budgets = mgr.rebalance(Phase.PLAN)
    total = sum(b.allocated for b in budgets.values())
    assert abs(total - 100_000) <= 100
    # MEMORY should be ~25% of 100k
    assert budgets[BudgetSlot.MEMORY].allocated > 20_000


def test_min_generation_enforced():
    mgr = BudgetManager(BudgetConfig(total_context_tokens=10_000, min_generation_tokens=2000))
    b = mgr.get_allocation(BudgetSlot.GENERATION)
    assert b.allocated >= 2000


def test_needs_compaction_false_below_threshold(mgr):
    mgr.consume(BudgetSlot.CONVERSATION, 50_000)  # 50% of 100k, below 85%
    assert mgr.needs_compaction() is False


def test_needs_compaction_true_above_threshold(mgr):
    mgr.consume(BudgetSlot.CONVERSATION, 90_000)  # 90% of 100k
    assert mgr.needs_compaction() is True


def test_needs_compaction_disabled():
    mgr = BudgetManager(BudgetConfig(total_context_tokens=100_000, disable_compaction=True))
    mgr.consume(BudgetSlot.CONVERSATION, 99_000)
    assert mgr.needs_compaction() is False


def test_budget_report(mgr):
    mgr.consume(BudgetSlot.MEMORY, 1000)
    report = mgr.assemble_budget_report()
    assert report.total_tokens == 100_000
    assert report.total_consumed >= 1000
    assert len(report.slots) == 6
```

- [ ] **Step 2: Run — expect `ModuleNotFoundError: No module named 'mori.budget.manager'`**

```
pytest tests/test_budget_manager.py -v
```

- [ ] **Step 3: Create `mori/budget/manager.py`**

```python
"""BudgetManager — per-slot token allocation and compaction orchestration."""
from __future__ import annotations
from typing import Any
from mori.budget.types import (
    BudgetConfig, BudgetSlot, CompactionModules, CompactionReport,
    CompactionStage, ConsumeResult, RebalanceHints, SlotReport,
    BudgetReport, StageResult,
)
from mori.types import Phase, TokenBudget

_BASE_ALLOC: dict[BudgetSlot, float] = {
    BudgetSlot.SYSTEM_PROMPT: 0.10,
    BudgetSlot.MEMORY:        0.20,
    BudgetSlot.SKILL:         0.15,
    BudgetSlot.TOOL_SCHEMAS:  0.10,
    BudgetSlot.CONVERSATION:  0.30,
    BudgetSlot.GENERATION:    0.15,
}

_PHASE_OVERRIDES: dict[Phase, dict[BudgetSlot, float]] = {
    Phase.PLAN: {
        BudgetSlot.MEMORY:       0.25,
        BudgetSlot.CONVERSATION: 0.30,
        BudgetSlot.SKILL:        0.10,
    },
    Phase.ACT: {
        BudgetSlot.SKILL:        0.20,
        BudgetSlot.TOOL_SCHEMAS: 0.15,
        BudgetSlot.MEMORY:       0.15,
    },
}


class BudgetManager:
    def __init__(self, config: BudgetConfig) -> None:
        self._config = config
        self._budgets: dict[BudgetSlot, TokenBudget] = {}
        self._defer_schemas: bool = False
        self._init_allocations()

    # ── Allocation ───────────────────────────────────────────

    def _alloc_from_fractions(self, fractions: dict[BudgetSlot, float]) -> None:
        total = self._config.total_context_tokens
        for slot, pct in fractions.items():
            existing = self._budgets.get(slot)
            consumed = existing.consumed if existing else 0
            self._budgets[slot] = TokenBudget(allocated=max(0, int(total * pct)),
                                              consumed=consumed)

    def _enforce_min_generation(self) -> None:
        gen = self._budgets[BudgetSlot.GENERATION]
        min_gen = self._config.min_generation_tokens
        if gen.allocated >= min_gen:
            return
        deficit = min_gen - gen.allocated
        candidates = sorted(
            [s for s in BudgetSlot if s != BudgetSlot.GENERATION],
            key=lambda s: self._budgets[s].allocated,
            reverse=True,
        )
        for slot in candidates:
            available = self._budgets[slot].allocated
            steal = min(deficit, available)
            self._budgets[slot] = TokenBudget(
                allocated=available - steal,
                consumed=self._budgets[slot].consumed,
            )
            deficit -= steal
            if deficit <= 0:
                break
        self._budgets[BudgetSlot.GENERATION] = TokenBudget(
            allocated=min_gen, consumed=gen.consumed
        )

    def _init_allocations(self) -> None:
        overrides = self._config.slot_overrides
        fractions = {s: overrides.get(s.value, v) for s, v in _BASE_ALLOC.items()}
        self._alloc_from_fractions(fractions)
        self._enforce_min_generation()

    # ── Public Interface ─────────────────────────────────────

    def get_allocation(self, slot: BudgetSlot) -> TokenBudget:
        return self._budgets[slot]

    def consume(self, slot: BudgetSlot, tokens: int) -> ConsumeResult:
        b = self._budgets[slot]
        new_consumed = b.consumed + tokens
        self._budgets[slot] = TokenBudget(allocated=b.allocated, consumed=new_consumed)
        return ConsumeResult(slot=slot, consumed=new_consumed,
                             over_budget=new_consumed > b.allocated)

    def release(self, slot: BudgetSlot, tokens: int) -> None:
        b = self._budgets[slot]
        self._budgets[slot] = TokenBudget(
            allocated=b.allocated, consumed=max(0, b.consumed - tokens)
        )

    def reset_slot(self, slot: BudgetSlot) -> None:
        b = self._budgets[slot]
        self._budgets[slot] = TokenBudget(allocated=b.allocated, consumed=0)

    def rebalance(
        self, phase: Phase, hints: RebalanceHints | None = None
    ) -> dict[BudgetSlot, TokenBudget]:
        fractions = dict(_BASE_ALLOC)
        if phase in _PHASE_OVERRIDES:
            fractions.update(_PHASE_OVERRIDES[phase])
        total_pct = sum(fractions.values())
        fractions = {k: v / total_pct for k, v in fractions.items()}
        # Apply per-slot config overrides
        config_overrides = self._config.slot_overrides
        if config_overrides:
            for slot_str, pct in config_overrides.items():
                try:
                    fractions[BudgetSlot(slot_str)] = pct
                except ValueError:
                    pass
        self._alloc_from_fractions(fractions)
        self._enforce_min_generation()
        if hints:
            if hints.extra_memory_tokens:
                b = self._budgets[BudgetSlot.MEMORY]
                self._budgets[BudgetSlot.MEMORY] = TokenBudget(
                    allocated=b.allocated + hints.extra_memory_tokens,
                    consumed=b.consumed,
                )
            if hints.extra_skill_tokens:
                b = self._budgets[BudgetSlot.SKILL]
                self._budgets[BudgetSlot.SKILL] = TokenBudget(
                    allocated=b.allocated + hints.extra_skill_tokens,
                    consumed=b.consumed,
                )
        return dict(self._budgets)

    def recount_from_state(self, state: Any) -> None:
        for slot in BudgetSlot:
            self.reset_slot(slot)
        for msg in state.messages:
            content = msg.content if isinstance(msg.content, str) else ""
            tokens = len(content) // 4
            if msg.role == "system":
                if "[Memory Context]" in content:
                    self.consume(BudgetSlot.MEMORY, tokens)
                elif "[Skill Context]" in content:
                    self.consume(BudgetSlot.SKILL, tokens)
                else:
                    self.consume(BudgetSlot.SYSTEM_PROMPT, tokens)
            else:
                self.consume(BudgetSlot.CONVERSATION, tokens)

    def needs_compaction(self) -> bool:
        if self._config.disable_compaction:
            return False
        total_consumed = sum(b.consumed for b in self._budgets.values())
        threshold = self._config.total_context_tokens * self._config.compaction_threshold_pct
        return total_consumed > threshold

    def assemble_budget_report(self) -> BudgetReport:
        total = self._config.total_context_tokens
        total_consumed = sum(b.consumed for b in self._budgets.values())
        slots = [
            SlotReport(
                slot=slot,
                allocated=b.allocated,
                consumed=b.consumed,
                pct_used=b.consumed / b.allocated if b.allocated > 0 else 0.0,
            )
            for slot, b in self._budgets.items()
        ]
        return BudgetReport(
            total_tokens=total,
            total_consumed=total_consumed,
            utilization=total_consumed / total if total > 0 else 0.0,
            slots=slots,
        )

    async def compact(self, state: Any, modules: CompactionModules) -> CompactionReport:
        initial_utilization = self.assemble_budget_report().utilization
        stage_results: list[StageResult] = []

        pipeline = [
            (CompactionStage.RESULT_TRIM,            self._stage_result_trim),
            (CompactionStage.SCHEMA_DEFER,           self._stage_schema_defer),
            (CompactionStage.TURN_SNIP,              self._stage_turn_snip),
            (CompactionStage.SKILL_DOWNGRADE,        self._stage_skill_downgrade),
            (CompactionStage.MEMORY_PRUNE,           self._stage_memory_prune),
            (CompactionStage.CONVERSATION_SUMMARIZE, self._stage_conversation_summarize),
        ]

        for stage_enum, stage_fn in pipeline:
            if not self.needs_compaction():
                stage_results.append(StageResult(stage=stage_enum, tokens_reclaimed=0, ran=False))
                continue
            reclaimed = await stage_fn(state, modules)
            stage_results.append(StageResult(stage=stage_enum, tokens_reclaimed=reclaimed, ran=True))

        final_report = self.assemble_budget_report()
        return CompactionReport(
            stages=stage_results,
            total_tokens_reclaimed=sum(r.tokens_reclaimed for r in stage_results),
            initial_utilization=initial_utilization,
            final_utilization=final_report.utilization,
        )

    # ── Compaction Stages ────────────────────────────────────

    async def _stage_result_trim(self, state: Any, _: CompactionModules) -> int:
        max_chars = self._config.max_result_tokens * 4
        reclaimed = 0
        for msg in state.messages:
            content = msg.content if isinstance(msg.content, str) else ""
            if msg.role == "tool" and len(content) > max_chars:
                old_tokens = len(content) // 4
                msg.content = content[:max_chars] + "… [truncated]"
                new_tokens = len(msg.content) // 4
                reclaimed += old_tokens - new_tokens
        if reclaimed:
            self.release(BudgetSlot.CONVERSATION, reclaimed)
        return reclaimed

    async def _stage_schema_defer(self, state: Any, _: CompactionModules) -> int:
        self._defer_schemas = True
        return 0

    async def _stage_turn_snip(self, state: Any, _: CompactionModules) -> int:
        reclaimed = 0
        i = 1  # skip initial user message
        while i < len(state.messages) - 4:
            msg = state.messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                reclaimed += sum(
                    (len(tc.name) + len(str(tc.arguments))) // 4
                    for tc in msg.tool_calls
                )
                # keep text, strip tool_calls
                state.messages[i] = msg.model_copy(update={"tool_calls": None})
                i += 1
                while i < len(state.messages) and state.messages[i].role == "tool":
                    content = state.messages[i].content
                    reclaimed += len(content if isinstance(content, str) else "") // 4
                    state.messages.pop(i)
                break
            i += 1
        if reclaimed:
            self.release(BudgetSlot.CONVERSATION, reclaimed)
        return reclaimed

    async def _stage_skill_downgrade(self, state: Any, modules: CompactionModules) -> int:
        if not modules.skills or not state.active_skill_payload:
            return 0
        payload = state.active_skill_payload
        if payload.disclosure_level.value != "full":
            return 0
        skill_budget = self._budgets[BudgetSlot.SKILL].allocated
        summary_payload = await modules.skills.load(
            payload.skill_id, "SUMMARY", max_tokens=skill_budget
        )
        reclaimed = max(0, payload.token_estimate - summary_payload.token_estimate)
        state.active_skill_payload = summary_payload
        for i, msg in enumerate(state.messages):
            if msg.role == "system" and "[Skill Context]" in (
                msg.content if isinstance(msg.content, str) else ""
            ):
                state.messages[i] = msg.model_copy(update={"content": summary_payload.content})
                break
        if reclaimed:
            self.release(BudgetSlot.SKILL, reclaimed)
        return reclaimed

    async def _stage_memory_prune(self, state: Any, modules: CompactionModules) -> int:
        if not modules.memory:
            return 0
        old_tokens = state.memory_slice.total_tokens if state.memory_slice else 0
        half_budget = max(0, old_tokens // 2)
        if half_budget < 100:
            return 0
        new_slice = await modules.memory.read(
            query=state.task, task_context=state.task, max_tokens=half_budget
        )
        state.memory_slice = new_slice
        if new_slice.records:
            lines = ["[Memory Context]"]
            for r in new_slice.records:
                lines.append(
                    f"- {r.content} (layer: {r.layer.value}, confidence: {r.confidence})"
                )
            new_content: str | None = "\n".join(lines)
        else:
            new_content = None
        for i, msg in enumerate(state.messages):
            content = msg.content if isinstance(msg.content, str) else ""
            if msg.role == "system" and "[Memory Context]" in content:
                if new_content:
                    state.messages[i] = msg.model_copy(update={"content": new_content})
                else:
                    state.messages.pop(i)
                break
        reclaimed = max(0, old_tokens - new_slice.total_tokens)
        if reclaimed:
            self.release(BudgetSlot.MEMORY, reclaimed)
        return reclaimed

    async def _stage_conversation_summarize(
        self, state: Any, modules: CompactionModules
    ) -> int:
        if not modules.model or len(state.messages) <= 6:
            return 0
        to_summarize = state.messages[1:-4]
        if not to_summarize:
            return 0
        old_tokens = sum(
            len(m.content if isinstance(m.content, str) else "") // 4
            for m in to_summarize
        )
        summary_text = "\n".join(
            f"[{m.role}]: {(m.content if isinstance(m.content, str) else '')[:500]}"
            for m in to_summarize
        )
        from mori.types import Message, ModelRequest
        req = ModelRequest(
            messages=[Message(role="user", content=(
                "Summarize this conversation history concisely in 3-5 sentences, "
                f"preserving key facts and decisions:\n\n{summary_text}"
            ))],
            tools=None,
        )
        response = await modules.model.invoke(req)
        summary_content = f"[Conversation Summary]\n{response.message.content}"
        state.messages = (
            [state.messages[0],
             Message(role="system", content=summary_content)]
            + list(state.messages[-4:])
        )
        new_tokens = len(summary_content) // 4
        reclaimed = max(0, old_tokens - new_tokens)
        if reclaimed:
            self.release(BudgetSlot.CONVERSATION, reclaimed)
        return reclaimed
```

- [ ] **Step 4: Run tests — expect pass**

```
pytest tests/test_budget_manager.py -v
```
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add mori/budget/manager.py tests/test_budget_manager.py
git commit -m "feat: BudgetManager — allocate, consume, rebalance, 6-stage compaction"
```

---

### Task 3: Skill Types

**Files:**
- Create: `mori/skills/__init__.py`
- Create: `mori/skills/types.py`
- Create: `tests/test_skill_types.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_skill_types.py
import pytest
from mori.skills.types import (
    SkillManifest, SkillCandidate, CompatibilityReport,
    SkillPayload, BoundSkill, SkillExecutionOutcome,
    SkillHealthReport, SkillValidationError,
)
from mori.types import DisclosureLevel, ToolSpec, ToolId, ToolSource


def _make_manifest(**kwargs):
    base = dict(
        name="my-skill", version="1.0.0", description="Test",
        capabilities=["cap1"], scope={"domains": [], "contexts": []},
        preconditions={"tools_required": [], "min_context_tokens": 100},
        constraints={"max_files": 10, "requires_approval_for": []},
        triggers={"semantic": ["fix bug"], "structural": []},
        progressive_disclosure={
            "abstract": "Short abstract",
            "summary": "Longer summary text here",
            "full": "SKILL.md",
        },
        skill_dir="/tmp/test",
    )
    base.update(kwargs)
    return SkillManifest(**base)


def test_skill_manifest_basic():
    m = _make_manifest()
    assert m.name == "my-skill"
    assert m.version == "1.0.0"


def test_skill_payload_token_estimate():
    p = SkillPayload(
        skill_id="my-skill",
        disclosure_level=DisclosureLevel.SUMMARY,
        content="hello world",
        token_estimate=3,
    )
    assert p.token_estimate == 3


def test_bound_skill_unresolved():
    manifest = _make_manifest()
    spec = ToolSpec(
        tool_id=ToolId("t1"), name="file-reader",
        description="reads files", input_schema={}, source=ToolSource.NATIVE,
    )
    payload = SkillPayload(
        skill_id="my-skill", disclosure_level=DisclosureLevel.SUMMARY,
        content="summary", token_estimate=2,
    )
    b = BoundSkill(
        payload=payload,
        resolved_tools={"file-reader": spec},
        unresolved=["missing-tool"],
    )
    assert "file-reader" in b.resolved_tools
    assert "missing-tool" in b.unresolved


def test_skill_validation_error_is_exception():
    err = SkillValidationError("bad manifest", path="/tmp/x")
    assert "bad manifest" in str(err)
    assert isinstance(err, Exception)


def test_skill_execution_outcome():
    from datetime import datetime, timezone
    o = SkillExecutionOutcome(
        skill_id="my-skill", run_id="run_1", success=True,
        steps_taken=3, failure_reason=None,
        timestamp=datetime.now(timezone.utc),
    )
    assert o.success is True
```

- [ ] **Step 2: Run — expect `ModuleNotFoundError: No module named 'mori.skills'`**

```
pytest tests/test_skill_types.py -v
```

- [ ] **Step 3: Create `mori/skills/__init__.py`** (empty)

- [ ] **Step 4: Create `mori/skills/types.py`**

```python
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
```

- [ ] **Step 5: Run — expect pass**

```
pytest tests/test_skill_types.py -v
```
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add mori/skills/__init__.py mori/skills/types.py tests/test_skill_types.py
git commit -m "feat: skill types — SkillManifest, SkillPayload, BoundSkill, SkillHealthReport"
```

---

### Task 4: Manifest Parser + pyyaml dep

**Files:**
- Modify: `pyproject.toml`
- Create: `mori/skills/parser.py`
- Create: `tests/test_skill_parser.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_skill_parser.py
import os, textwrap
import pytest
from mori.skills.parser import parse_manifest, load_skill_md
from mori.skills.types import SkillManifest, SkillValidationError


VALID_YAML = textwrap.dedent("""\
    name: bug-fix
    version: 1.0.0
    description: Fix failing tests
    capabilities:
      - debugging
    scope:
      domains: [code]
      contexts: [test]
    preconditions:
      tools_required: [file-reader, test-runner]
      min_context_tokens: 500
    constraints:
      max_files: 5
      requires_approval_for: []
    triggers:
      semantic: ["fix failing test", "debug"]
      structural: []
    progressive_disclosure:
      abstract: Fix a failing test by isolating and patching the root cause.
      summary: Read the failing test, trace the error, apply minimal fix, verify.
      full: SKILL.md
""")


def test_parse_valid_manifest(tmp_path):
    skill_dir = tmp_path / "bug-fix"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text(VALID_YAML)
    (skill_dir / "SKILL.md").write_text("# Procedure\nDo the fix.")
    m = parse_manifest(str(skill_dir))
    assert isinstance(m, SkillManifest)
    assert m.name == "bug-fix"
    assert m.version == "1.0.0"
    assert m.skill_dir == str(skill_dir)


def test_parse_missing_manifest_raises(tmp_path):
    skill_dir = tmp_path / "no-manifest"
    skill_dir.mkdir()
    with pytest.raises(SkillValidationError, match="manifest.yaml"):
        parse_manifest(str(skill_dir))


def test_parse_invalid_semver_raises(tmp_path):
    skill_dir = tmp_path / "bad-ver"
    skill_dir.mkdir()
    bad = VALID_YAML.replace("version: 1.0.0", "version: notaversion")
    (skill_dir / "manifest.yaml").write_text(bad)
    (skill_dir / "SKILL.md").write_text("x")
    with pytest.raises(SkillValidationError, match="semver"):
        parse_manifest(str(skill_dir))


def test_parse_empty_name_raises(tmp_path):
    skill_dir = tmp_path / "no-name"
    skill_dir.mkdir()
    bad = VALID_YAML.replace("name: bug-fix", "name: ''")
    (skill_dir / "manifest.yaml").write_text(bad)
    (skill_dir / "SKILL.md").write_text("x")
    with pytest.raises(SkillValidationError, match="name"):
        parse_manifest(str(skill_dir))


def test_parse_abstract_too_long_raises(tmp_path):
    skill_dir = tmp_path / "long-abstract"
    skill_dir.mkdir()
    long_abstract = "x" * 101
    bad = VALID_YAML.replace(
        "abstract: Fix a failing test by isolating and patching the root cause.",
        f"abstract: {long_abstract}",
    )
    (skill_dir / "manifest.yaml").write_text(bad)
    (skill_dir / "SKILL.md").write_text("x")
    with pytest.raises(SkillValidationError, match="abstract"):
        parse_manifest(str(skill_dir))


def test_parse_missing_skill_md_raises(tmp_path):
    skill_dir = tmp_path / "no-md"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text(VALID_YAML)
    with pytest.raises(SkillValidationError, match="SKILL.md"):
        parse_manifest(str(skill_dir))


def test_load_skill_md(tmp_path):
    skill_dir = tmp_path / "myskill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Steps\nDo the thing.")
    content = load_skill_md(str(skill_dir))
    assert "Do the thing" in content


def test_name_invalid_chars_raises(tmp_path):
    skill_dir = tmp_path / "bad-name"
    skill_dir.mkdir()
    bad = VALID_YAML.replace("name: bug-fix", "name: 'bad name!'")
    (skill_dir / "manifest.yaml").write_text(bad)
    (skill_dir / "SKILL.md").write_text("x")
    with pytest.raises(SkillValidationError, match="name"):
        parse_manifest(str(skill_dir))
```

- [ ] **Step 2: Run — expect `ModuleNotFoundError`**

```
pytest tests/test_skill_parser.py -v
```

- [ ] **Step 3: Add pyyaml to `pyproject.toml`**

In `pyproject.toml`, in the `dependencies` list, add:
```toml
    "pyyaml>=6.0",
```

Full updated dependencies block:
```toml
dependencies = [
    "pydantic>=2.0,<3.0",
    "httpx>=0.27,<1.0",
    "structlog>=24.0",
    "anyio>=4.0,<5.0",
    "pyyaml>=6.0",
]
```

Then install:
```
pip install pyyaml
```

- [ ] **Step 4: Create `mori/skills/parser.py`**

```python
"""Manifest parser and SKILL.md loader."""
from __future__ import annotations
import re
from pathlib import Path
import yaml
from mori.skills.types import SkillManifest, SkillValidationError

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def parse_manifest(skill_dir: str) -> SkillManifest:
    path = Path(skill_dir)
    manifest_path = path / "manifest.yaml"
    if not manifest_path.exists():
        raise SkillValidationError(
            f"manifest.yaml not found in {skill_dir}", path=skill_dir
        )
    raw = yaml.safe_load(manifest_path.read_text())
    if not raw:
        raise SkillValidationError("manifest.yaml is empty", path=skill_dir)

    name = str(raw.get("name", "")).strip()
    if not name:
        raise SkillValidationError("manifest 'name' must be non-empty", path=skill_dir)
    if not _NAME_RE.match(name):
        raise SkillValidationError(
            f"manifest 'name' must be alphanumeric/hyphen/underscore only, got: {name!r}",
            path=skill_dir,
        )

    version = str(raw.get("version", "")).strip()
    if not _SEMVER_RE.match(version):
        raise SkillValidationError(
            f"manifest 'version' must be semver (e.g. '1.0.0'), got: {version!r}",
            path=skill_dir,
        )

    disclosure = raw.get("progressive_disclosure", {})
    abstract = str(disclosure.get("abstract", ""))
    if len(abstract) > 100:
        raise SkillValidationError(
            f"manifest 'abstract' must be < 100 chars, got {len(abstract)}", path=skill_dir
        )

    summary = str(disclosure.get("summary", ""))
    if len(summary) // 4 > 500:
        raise SkillValidationError(
            f"manifest 'summary' exceeds 500 tokens (estimated)", path=skill_dir
        )

    skill_md_path = path / "SKILL.md"
    if not skill_md_path.exists() or skill_md_path.stat().st_size == 0:
        raise SkillValidationError(
            f"SKILL.md not found or empty in {skill_dir}", path=skill_dir
        )

    return SkillManifest(
        name=name,
        version=version,
        description=str(raw.get("description", "")),
        capabilities=list(raw.get("capabilities", [])),
        scope=dict(raw.get("scope", {})),
        preconditions=dict(raw.get("preconditions", {})),
        constraints=dict(raw.get("constraints", {})),
        triggers=dict(raw.get("triggers", {})),
        progressive_disclosure=disclosure,
        skill_dir=skill_dir,
    )


def load_skill_md(skill_dir: str) -> str:
    path = Path(skill_dir) / "SKILL.md"
    return path.read_text()
```

- [ ] **Step 5: Run — expect pass**

```
pytest tests/test_skill_parser.py -v
```
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml mori/skills/parser.py tests/test_skill_parser.py
git commit -m "feat: manifest parser — semver/name/abstract validation + pyyaml dep"
```

---

### Task 5: FilesystemRegistry + CompositeRegistry

**Files:**
- Create: `mori/skills/registry.py`
- Create: `tests/test_skill_registry.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_skill_registry.py
import textwrap
import pytest
from mori.skills.registry import FilesystemRegistry, CompositeRegistry
from mori.skills.types import SkillManifest

MANIFEST_A = textwrap.dedent("""\
    name: alpha
    version: 1.0.0
    description: Alpha skill
    capabilities: [cap]
    scope: {domains: [], contexts: []}
    preconditions: {tools_required: [], min_context_tokens: 100}
    constraints: {max_files: 5, requires_approval_for: []}
    triggers: {semantic: ["do alpha"], structural: []}
    progressive_disclosure:
      abstract: Alpha abstract (short)
      summary: Alpha summary text for testing.
      full: SKILL.md
""")

MANIFEST_B = textwrap.dedent("""\
    name: beta
    version: 2.0.0
    description: Beta skill
    capabilities: [cap]
    scope: {domains: [], contexts: []}
    preconditions: {tools_required: [file-reader], min_context_tokens: 200}
    constraints: {max_files: 5, requires_approval_for: []}
    triggers: {semantic: ["do beta"], structural: []}
    progressive_disclosure:
      abstract: Beta abstract (short).
      summary: Beta summary text for testing.
      full: SKILL.md
""")


@pytest.fixture
def skills_dir(tmp_path):
    a = tmp_path / "alpha"
    a.mkdir()
    (a / "manifest.yaml").write_text(MANIFEST_A)
    (a / "SKILL.md").write_text("# Alpha\nDo alpha.")
    b = tmp_path / "beta"
    b.mkdir()
    (b / "manifest.yaml").write_text(MANIFEST_B)
    (b / "SKILL.md").write_text("# Beta\nDo beta.")
    return tmp_path


def test_registry_discovers_both_skills(skills_dir):
    reg = FilesystemRegistry(str(skills_dir))
    results = reg.search("anything", limit=10)
    assert len(results) == 2


def test_registry_skips_invalid_skills(skills_dir):
    bad = skills_dir / "broken"
    bad.mkdir()
    (bad / "manifest.yaml").write_text("name: ''\nversion: bad")
    reg = FilesystemRegistry(str(skills_dir))
    results = reg.search("anything", limit=10)
    assert len(results) == 2  # broken is skipped


def test_registry_returns_manifest_objects(skills_dir):
    reg = FilesystemRegistry(str(skills_dir))
    results = reg.search("query", limit=10)
    assert all(isinstance(m, SkillManifest) for m in results)


def test_registry_limit(skills_dir):
    reg = FilesystemRegistry(str(skills_dir))
    results = reg.search("query", limit=1)
    assert len(results) == 1


def test_registry_caches_on_second_call(skills_dir):
    reg = FilesystemRegistry(str(skills_dir))
    r1 = reg.search("q", limit=10)
    r2 = reg.search("q", limit=10)
    assert [m.name for m in r1] == [m.name for m in r2]


def test_composite_registry_merges(skills_dir, tmp_path):
    dir2 = tmp_path / "extra"
    dir2.mkdir()
    c = dir2 / "gamma"
    c.mkdir()
    (c / "manifest.yaml").write_text(textwrap.dedent("""\
        name: gamma
        version: 1.0.0
        description: Gamma
        capabilities: []
        scope: {domains: [], contexts: []}
        preconditions: {tools_required: [], min_context_tokens: 0}
        constraints: {max_files: 1, requires_approval_for: []}
        triggers: {semantic: ["gamma"], structural: []}
        progressive_disclosure:
          abstract: Gamma abstract here.
          summary: Gamma summary.
          full: SKILL.md
    """))
    (c / "SKILL.md").write_text("# Gamma")
    r1 = FilesystemRegistry(str(skills_dir))
    r2 = FilesystemRegistry(str(dir2))
    comp = CompositeRegistry([r1, r2])
    results = comp.search("query", limit=10)
    names = [m.name for m in results]
    assert "alpha" in names
    assert "gamma" in names
```

- [ ] **Step 2: Run — expect `ModuleNotFoundError`**

```
pytest tests/test_skill_registry.py -v
```

- [ ] **Step 3: Create `mori/skills/registry.py`**

```python
"""FilesystemRegistry and CompositeRegistry for skill discovery."""
from __future__ import annotations
import logging
from pathlib import Path
from mori.skills.parser import parse_manifest
from mori.skills.types import SkillManifest, SkillValidationError

logger = logging.getLogger(__name__)


class FilesystemRegistry:
    def __init__(self, root: str, embedder: object | None = None) -> None:
        self._root = Path(root)
        self._embedder = embedder
        self._cache: list[SkillManifest] | None = None

    def _load(self) -> list[SkillManifest]:
        if self._cache is not None:
            return self._cache
        manifests: list[SkillManifest] = []
        for candidate in sorted(self._root.iterdir()):
            if not candidate.is_dir():
                continue
            try:
                m = parse_manifest(str(candidate))
                manifests.append(m)
            except SkillValidationError as exc:
                logger.warning("Skipping invalid skill %s: %s", candidate.name, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error loading skill %s: %s", candidate.name, exc)
        self._cache = manifests
        return manifests

    def search(self, query: str, limit: int = 10) -> list[SkillManifest]:
        manifests = self._load()
        # Without embedder: return all in directory order
        return manifests[:limit]


class CompositeRegistry:
    def __init__(self, registries: list[FilesystemRegistry]) -> None:
        self._registries = registries

    def search(self, query: str, limit: int = 10) -> list[SkillManifest]:
        seen: set[str] = set()
        results: list[SkillManifest] = []
        for reg in self._registries:
            for m in reg.search(query, limit=limit):
                if m.name not in seen:
                    seen.add(m.name)
                    results.append(m)
        return results[:limit]
```

- [ ] **Step 4: Run — expect pass**

```
pytest tests/test_skill_registry.py -v
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add mori/skills/registry.py tests/test_skill_registry.py
git commit -m "feat: FilesystemRegistry + CompositeRegistry — scan, cache, skip invalid"
```

---

### Task 6: SkillsModule

**Files:**
- Create: `mori/skills/module.py`
- Create: `tests/test_skills_module.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_skills_module.py
import textwrap
import pytest
from datetime import datetime, timezone, timedelta
from mori.skills.module import SkillsModule
from mori.skills.registry import FilesystemRegistry
from mori.skills.types import SkillExecutionOutcome
from mori.types import DisclosureLevel, ToolSpec, ToolId, ToolSource

MANIFEST = textwrap.dedent("""\
    name: bug-fix
    version: 1.0.0
    description: Fix failing tests
    capabilities: [debugging]
    scope: {domains: [code], contexts: [test]}
    preconditions:
      tools_required: [file-reader, test-runner]
      min_context_tokens: 500
    constraints: {max_files: 5, requires_approval_for: []}
    triggers: {semantic: ["fix failing test", "debug"], structural: []}
    progressive_disclosure:
      abstract: Fix a failing test by finding and patching the root cause.
      summary: Read the failing test, trace the error, apply the minimal fix, verify.
      full: SKILL.md
""")

MANIFEST_B = textwrap.dedent("""\
    name: code-review
    version: 1.0.0
    description: Review code quality
    capabilities: [review]
    scope: {domains: [code], contexts: []}
    preconditions:
      tools_required: [file-reader]
      min_context_tokens: 200
    constraints: {max_files: 10, requires_approval_for: []}
    triggers: {semantic: ["review", "check code"], structural: []}
    progressive_disclosure:
      abstract: Review code for correctness and style issues.
      summary: Read files, check logic and style, summarise findings.
      full: SKILL.md
""")


@pytest.fixture
def skills_dir(tmp_path):
    for name, text in [("bug-fix", MANIFEST), ("code-review", MANIFEST_B)]:
        d = tmp_path / name
        d.mkdir()
        (d / "manifest.yaml").write_text(text)
        (d / "SKILL.md").write_text(f"# {name}\nDo the thing.")
    return tmp_path


@pytest.fixture
def module(skills_dir):
    reg = FilesystemRegistry(str(skills_dir))
    return SkillsModule(registry=reg)


def test_discover_returns_candidates(module):
    candidates = module.discover("fix the failing test", available_tools=["file-reader", "test-runner"])
    assert len(candidates) > 0


def test_discover_excludes_missing_tools(module):
    # only file-reader available — bug-fix needs test-runner too, should be excluded
    candidates = module.discover("fix the failing test", available_tools=["file-reader"])
    names = [c.manifest.name for c in candidates]
    assert "bug-fix" not in names


def test_discover_sorted_descending(module):
    candidates = module.discover("anything", available_tools=["file-reader", "test-runner"])
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_discover_no_embedder_returns_all_compatible(module):
    candidates = module.discover("task", available_tools=["file-reader", "test-runner"])
    assert len(candidates) == 2


async def test_load_abstract(module):
    payload = await module.load("bug-fix", "ABSTRACT", max_tokens=200)
    assert payload.disclosure_level == DisclosureLevel.ABSTRACT
    assert len(payload.content) < 120
    assert payload.token_estimate < 30


async def test_load_summary(module):
    payload = await module.load("bug-fix", "SUMMARY", max_tokens=500)
    assert payload.disclosure_level == DisclosureLevel.SUMMARY
    assert "minimal fix" in payload.content.lower() or len(payload.content) > 0


async def test_load_full_respects_max_tokens(skills_dir):
    reg = FilesystemRegistry(str(skills_dir))
    module = SkillsModule(registry=reg)
    payload = await module.load("bug-fix", "FULL", max_tokens=5)
    assert payload.token_estimate <= 6
    assert payload.disclosure_level == DisclosureLevel.FULL


def test_bind_resolves_tools(module):
    from mori.skills.types import SkillPayload
    payload = SkillPayload(
        skill_id="bug-fix", disclosure_level=DisclosureLevel.SUMMARY,
        content="summary", token_estimate=2,
    )
    specs = [
        ToolSpec(tool_id=ToolId("t1"), name="file-reader",
                 description="reads", input_schema={}, source=ToolSource.NATIVE),
    ]
    bound = module.bind(payload, specs)
    assert "file-reader" in bound.resolved_tools
    assert "test-runner" in bound.unresolved


def test_health_success_rate(module):
    now = datetime.now(timezone.utc)
    for i in range(3):
        module.record_outcome("bug-fix", SkillExecutionOutcome(
            skill_id="bug-fix", run_id=f"r{i}", success=True,
            steps_taken=2, timestamp=now,
        ))
    module.record_outcome("bug-fix", SkillExecutionOutcome(
        skill_id="bug-fix", run_id="r3", success=False,
        steps_taken=1, failure_reason="timeout", timestamp=now,
    ))
    report = module.health("bug-fix")
    assert report.total_runs == 4
    assert abs(report.success_rate - 0.75) < 0.01


def test_health_stale_flag(module):
    old = datetime.now(timezone.utc) - timedelta(days=91)
    module.record_outcome("bug-fix", SkillExecutionOutcome(
        skill_id="bug-fix", run_id="r0", success=True,
        steps_taken=1, timestamp=old,
    ))
    report = module.health("bug-fix")
    assert report.stale is True


def test_health_no_runs_is_stale(module):
    report = module.health("bug-fix")
    assert report.stale is True
    assert report.total_runs == 0
```

- [ ] **Step 2: Run — expect `ModuleNotFoundError`**

```
pytest tests/test_skills_module.py -v
```

- [ ] **Step 3: Create `mori/skills/module.py`**

```python
"""SkillsModule — discover, load, bind, record_outcome, health."""
from __future__ import annotations
import secrets
from collections import Counter, deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from mori.skills.parser import load_skill_md
from mori.skills.registry import FilesystemRegistry, CompositeRegistry
from mori.skills.types import (
    BoundSkill, CompatibilityReport, SkillCandidate, SkillExecutionOutcome,
    SkillHealthReport, SkillManifest, SkillPayload,
)
from mori.types import DisclosureLevel, ToolSpec


class SkillsModule:
    def __init__(
        self,
        registry: FilesystemRegistry | CompositeRegistry,
        embedder: Any | None = None,
    ) -> None:
        self._registry = registry
        self._embedder = embedder
        self._health_windows: dict[str, deque[SkillExecutionOutcome]] = {}

    # ── Discover ─────────────────────────────────────────────

    def discover(
        self,
        task: str,
        available_tools: list[str],
        available_tokens: int = 999_999,
        max_candidates: int = 5,
    ) -> list[SkillCandidate]:
        manifests = self._registry.search(task, limit=50)
        candidates: list[SkillCandidate] = []
        for m in manifests:
            report = self._check_compatibility(m, available_tools, available_tokens)
            if not report.tools_satisfied:
                continue
            score = 1.0  # no embedder: uniform score, sorted by registry order
            candidates.append(SkillCandidate(manifest=m, score=score,
                                              compatibility_report=report))
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:max_candidates]

    def _check_compatibility(
        self, m: SkillManifest, available_tools: list[str], available_tokens: int
    ) -> CompatibilityReport:
        required = list(m.preconditions.get("tools_required", []))
        missing = [t for t in required if t not in available_tools]
        min_ctx = int(m.preconditions.get("min_context_tokens", 0))
        return CompatibilityReport(
            tools_satisfied=len(missing) == 0,
            missing_tools=missing,
            context_fits=available_tokens >= min_ctx,
            required_tokens=min_ctx,
        )

    # ── Load ─────────────────────────────────────────────────

    async def load(
        self, skill_id: str, disclosure_level: str, max_tokens: int
    ) -> SkillPayload:
        manifests = self._registry.search("", limit=100)
        manifest = next((m for m in manifests if m.name == skill_id), None)
        if manifest is None:
            raise KeyError(f"Skill '{skill_id}' not found in registry")

        pd = manifest.progressive_disclosure
        level = DisclosureLevel(disclosure_level.lower())

        if level == DisclosureLevel.ABSTRACT:
            content = pd.get("abstract", "")
        elif level == DisclosureLevel.SUMMARY:
            content = pd.get("summary", "")
        else:  # FULL
            content = load_skill_md(manifest.skill_dir)
            max_chars = max_tokens * 4
            if len(content) > max_chars:
                content = content[:max_chars]

        token_estimate = len(content) // 4
        return SkillPayload(
            skill_id=skill_id,
            disclosure_level=level,
            content=content,
            token_estimate=token_estimate,
        )

    # ── Bind ─────────────────────────────────────────────────

    def bind(self, payload: SkillPayload, available_tools: list[ToolSpec]) -> BoundSkill:
        manifests = self._registry.search("", limit=100)
        manifest = next((m for m in manifests if m.name == payload.skill_id), None)
        required = list(manifest.preconditions.get("tools_required", [])) if manifest else []
        tool_map = {t.name: t for t in available_tools}
        resolved = {name: tool_map[name] for name in required if name in tool_map}
        unresolved = [name for name in required if name not in tool_map]
        return BoundSkill(payload=payload, resolved_tools=resolved, unresolved=unresolved)

    # ── Health ───────────────────────────────────────────────

    def record_outcome(self, skill_id: str, outcome: SkillExecutionOutcome) -> None:
        if skill_id not in self._health_windows:
            self._health_windows[skill_id] = deque(maxlen=50)
        self._health_windows[skill_id].append(outcome)

    def health(self, skill_id: str) -> SkillHealthReport:
        window = list(self._health_windows.get(skill_id, []))
        total = len(window)
        if total == 0:
            return SkillHealthReport(
                skill_id=skill_id, total_runs=0, success_rate=0.0,
                avg_steps=0.0, common_failures=[], last_used=None, stale=True,
            )
        successes = sum(1 for o in window if o.success)
        avg_steps = sum(o.steps_taken for o in window) / total
        failures = [o.failure_reason for o in window if o.failure_reason]
        common = [reason for reason, _ in Counter(failures).most_common(3)]
        last_used = max(o.timestamp for o in window)
        stale = (datetime.now(timezone.utc) - last_used) > timedelta(days=90)
        return SkillHealthReport(
            skill_id=skill_id,
            total_runs=total,
            success_rate=successes / total,
            avg_steps=avg_steps,
            common_failures=common,
            last_used=last_used,
            stale=stale,
        )
```

- [ ] **Step 4: Run — expect pass**

```
pytest tests/test_skills_module.py -v
```
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add mori/skills/module.py tests/test_skills_module.py
git commit -m "feat: SkillsModule — discover, load, bind, record_outcome, health"
```

---

### Task 7: New Events + MoriState Field

**Files:**
- Modify: `mori/observability/events.py`
- Modify: `mori/runtime/state.py`
- Create: `tests/test_events_v04.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_events_v04.py
from datetime import datetime, timezone
from mori.observability.events import (
    SkillDiscoverEvent, SkillLoadEvent,
    BudgetRebalanceEvent, CompactionEvent,
)
from mori.budget.types import BudgetSlot, CompactionStage, StageResult
from mori.types import RunId, DisclosureLevel


def _now():
    return datetime.now(timezone.utc)


def test_skill_discover_event():
    e = SkillDiscoverEvent(
        event_id="e1", timestamp=_now(), run_id=RunId("r1"),
        task_preview="fix the test",
        candidates_found=2,
        top_match_name="bug-fix",
        top_match_score=0.95,
        duration_ms=5.0,
    )
    assert e.event_type == "skill.discover"
    assert e.top_match_name == "bug-fix"


def test_skill_load_event():
    e = SkillLoadEvent(
        event_id="e2", timestamp=_now(), run_id=RunId("r1"),
        skill_id="bug-fix",
        disclosure_level=DisclosureLevel.SUMMARY,
        token_estimate=120,
        duration_ms=2.0,
    )
    assert e.event_type == "skill.load"
    assert e.disclosure_level == DisclosureLevel.SUMMARY


def test_budget_rebalance_event():
    e = BudgetRebalanceEvent(
        event_id="e3", timestamp=_now(), run_id=RunId("r1"),
        phase="plan",
        allocations={BudgetSlot.MEMORY: 25_000, BudgetSlot.CONVERSATION: 30_000},
        total_consumed=10_000,
        utilization=0.10,
    )
    assert e.event_type == "budget.rebalance"
    assert BudgetSlot.MEMORY in e.allocations


def test_compaction_event():
    stages = [StageResult(stage=CompactionStage.RESULT_TRIM, tokens_reclaimed=500, ran=True)]
    e = CompactionEvent(
        event_id="e4", timestamp=_now(), run_id=RunId("r1"),
        stages_run=stages,
        total_tokens_reclaimed=500,
        final_utilization=0.80,
    )
    assert e.event_type == "budget.compaction"
    assert e.total_tokens_reclaimed == 500


def test_mori_state_has_active_skill_payload():
    from datetime import datetime, timezone
    from mori.runtime.state import MoriState
    from mori.types import RunId, ThreadId, RunStatus
    state = MoriState(
        run_id=RunId("r1"), thread_id=ThreadId("t1"), task="test",
        status=RunStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        last_progress_at=datetime.now(timezone.utc),
    )
    assert state.active_skill_payload is None
    state.active_skill_payload = "anything"
    assert state.active_skill_payload == "anything"
```

- [ ] **Step 2: Run — expect failures on missing event classes**

```
pytest tests/test_events_v04.py -v
```

- [ ] **Step 3: Add events to `mori/observability/events.py`**

After the existing `MemoryWriteEvent` class (after line 113), add:

```python
# ── Skills Events ────────────────────────────────────────────

class SkillDiscoverEvent(MoriEvent):
    event_type: str = "skill.discover"
    task_preview: str
    candidates_found: int
    top_match_name: str | None = None
    top_match_score: float | None = None
    duration_ms: float


class SkillLoadEvent(MoriEvent):
    event_type: str = "skill.load"
    skill_id: str
    disclosure_level: DisclosureLevel
    token_estimate: int
    duration_ms: float


# ── Budget Events ────────────────────────────────────────────

class BudgetRebalanceEvent(MoriEvent):
    event_type: str = "budget.rebalance"
    phase: str
    allocations: dict[BudgetSlot, int]
    total_consumed: int
    utilization: float


class CompactionEvent(MoriEvent):
    event_type: str = "budget.compaction"
    stages_run: list[Any]
    total_tokens_reclaimed: int
    final_utilization: float
```

Also add the needed imports at the top of `events.py`. After the existing imports, add:
```python
from mori.budget.types import BudgetSlot
```
And ensure `DisclosureLevel` is imported (it comes from `mori.types` which is already imported via the wildcard pattern — add it explicitly to the import list if needed).

The full updated imports block at the top of `mori/observability/events.py`:
```python
from mori.types import (
    DisclosureLevel,
    MemoryLayer,
    MoriModel,
    Phase,
    RunId,
    RunStatus,
    StepId,
    StepOutcome,
    ToolSource,
    TraceId,
)
```

- [ ] **Step 4: Add `active_skill_payload` to `mori/runtime/state.py`**

After line 31 (`memory_slice: MemorySlice | None = None`), add:

```python
    # Skills
    active_skill_payload: Any | None = None
```

`Any` is already imported at the top of state.py.

- [ ] **Step 5: Run — expect pass**

```
pytest tests/test_events_v04.py -v
```
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add mori/observability/events.py mori/runtime/state.py tests/test_events_v04.py
git commit -m "feat: v0.4 events — SkillDiscover, SkillLoad, BudgetRebalance, Compaction + state field"
```

---

### Task 8: Loop Integration

**Files:**
- Modify: `mori/runtime/loop.py`
- Create: `tests/test_loop_v04.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_loop_v04.py
import pytest
from unittest.mock import AsyncMock
from mori.budget.manager import BudgetManager
from mori.budget.types import BudgetConfig
from mori.memory.backends.inmemory import InMemoryBackend
from mori.memory.module import MemoryModule
from mori.model.base import ModelAdapter
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import ObservabilityConfig
from mori.runtime.loop import AgentLoop
from mori.skills.module import SkillsModule
from mori.skills.registry import FilesystemRegistry
from mori.tools.registry import ToolRegistry
from mori.types import MemoryConfig, Message, ModelResponse, RunStatus, TokenUsage
import textwrap


MANIFEST = textwrap.dedent("""\
    name: bug-fix
    version: 1.0.0
    description: Fix failing tests
    capabilities: [debug]
    scope: {domains: [], contexts: []}
    preconditions:
      tools_required: []
      min_context_tokens: 0
    constraints: {max_files: 5, requires_approval_for: []}
    triggers: {semantic: ["fix test"], structural: []}
    progressive_disclosure:
      abstract: Fix a failing test.
      summary: Read test, trace error, patch, verify.
      full: SKILL.md
""")


def _text_response(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


@pytest.fixture
def mock_model():
    m = AsyncMock(spec=ModelAdapter)
    m.model_id = "test"
    m.supports_tool_use = True
    m.max_context_tokens = 100_000
    m.invoke = AsyncMock(return_value=_text_response("done"))
    return m


@pytest.fixture
def skills_module(tmp_path):
    d = tmp_path / "bug-fix"
    d.mkdir()
    (d / "manifest.yaml").write_text(MANIFEST)
    (d / "SKILL.md").write_text("# Bug Fix\nDo the thing.")
    reg = FilesystemRegistry(str(tmp_path))
    return SkillsModule(registry=reg)


async def test_loop_with_skills_emits_discover_event(mock_model, skills_module):
    collected = []
    class Sink:
        realtime = True
        async def write(self, e): collected.append(e)
        async def write_batch(self, es): collected.extend(es)
        async def flush(self): pass
        async def close(self): pass
    obs = ObservabilityEngine(sinks=[Sink()], config=ObservabilityConfig(buffer_size=100))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), observability=obs,
                     skills=skills_module)
    await loop.run("fix test")
    await obs.flush()
    types = [e.event_type for e in collected]
    assert "skill.discover" in types


async def test_loop_with_skills_injects_skill_context(mock_model, skills_module):
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), skills=skills_module)
    await loop.run("fix test")
    request = mock_model.invoke.call_args[0][0]
    system_contents = " ".join(
        m.content for m in request.messages if m.role == "system"
        and isinstance(m.content, str)
    )
    assert "[Skill Context]" in system_contents


async def test_loop_without_skills_still_works(mock_model):
    loop = AgentLoop(model=mock_model, tools=ToolRegistry())
    result = await loop.run("task")
    assert result.status == RunStatus.COMPLETED


async def test_loop_with_budget_emits_rebalance_event(mock_model):
    collected = []
    class Sink:
        realtime = True
        async def write(self, e): collected.append(e)
        async def write_batch(self, es): collected.extend(es)
        async def flush(self): pass
        async def close(self): pass
    obs = ObservabilityEngine(sinks=[Sink()], config=ObservabilityConfig(buffer_size=100))
    budget = BudgetManager(BudgetConfig(total_context_tokens=50_000))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(),
                     observability=obs, budget=budget)
    await loop.run("task")
    await obs.flush()
    types = [e.event_type for e in collected]
    assert "budget.rebalance" in types


async def test_loop_without_budget_still_works(mock_model):
    loop = AgentLoop(model=mock_model, tools=ToolRegistry())
    result = await loop.run("task")
    assert result.status == RunStatus.COMPLETED
```

- [ ] **Step 2: Run — expect failures (no `skills` param on AgentLoop)**

```
pytest tests/test_loop_v04.py -v
```

- [ ] **Step 3: Update `mori/runtime/loop.py`**

**3a — Update `__init__` signature** (add `skills` and `budget` params):

```python
    def __init__(
        self,
        model: ModelAdapter,
        tools: ToolRegistry,
        observability: ObservabilityEngine | None = None,
        control: ControlBounds | None = None,
        memory: Any | None = None,
        skills: Any | None = None,
        budget: Any | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._obs = observability
        if control is None:
            from mori.control.bounds import ControlBounds, ControlConfig
            control = ControlBounds(config=ControlConfig())
        self._control = control
        self._memory = memory
        self._skills = skills
        self._budget = budget
```

**3b — Replace `_phase_retrieve`** with the expanded version:

```python
    async def _phase_retrieve(self, state: MoriState) -> None:
        # Memory read (unchanged)
        if self._memory:
            from mori.observability.events import MemoryReadEvent
            start = time.monotonic()
            memory_slice = await self._memory.read(
                query=state.task, task_context=state.task, max_tokens=2000
            )
            elapsed = (time.monotonic() - start) * 1000
            state.memory_slice = memory_slice
            if self._budget:
                self._budget.consume(
                    BudgetSlot.MEMORY, memory_slice.total_tokens
                )
            await self._emit(MemoryReadEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id, query=state.task,
                layers=[l for l in memory_slice.layers_searched],
                records_returned=len(memory_slice.records),
                tokens_consumed=memory_slice.total_tokens,
                duration_ms=elapsed,
            ))

        # Skill discovery + load
        if self._skills:
            from mori.observability.events import SkillDiscoverEvent, SkillLoadEvent
            available_tool_names = [s.name for s in self._tools.list_specs()]
            skill_budget_tokens = (
                self._budget.get_allocation(BudgetSlot.SKILL).allocated
                if self._budget else 999_999
            )
            disc_start = time.monotonic()
            candidates = self._skills.discover(
                state.task,
                available_tools=available_tool_names,
                available_tokens=skill_budget_tokens,
            )
            disc_elapsed = (time.monotonic() - disc_start) * 1000

            top = candidates[0] if candidates else None
            await self._emit(SkillDiscoverEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id,
                task_preview=state.task[:80],
                candidates_found=len(candidates),
                top_match_name=top.manifest.name if top else None,
                top_match_score=top.score if top else None,
                duration_ms=disc_elapsed,
            ))

            if top:
                load_start = time.monotonic()
                payload = await self._skills.load(
                    top.manifest.name, "SUMMARY", max_tokens=skill_budget_tokens
                )
                load_elapsed = (time.monotonic() - load_start) * 1000
                state.active_skill_payload = payload
                if self._budget:
                    self._budget.consume(BudgetSlot.SKILL, payload.token_estimate)
                await self._emit(SkillLoadEvent(
                    event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                    run_id=state.run_id,
                    skill_id=payload.skill_id,
                    disclosure_level=payload.disclosure_level,
                    token_estimate=payload.token_estimate,
                    duration_ms=load_elapsed,
                ))
```

**3c — Add `_pre_plan_compact` method** (new method, add after `_phase_retrieve`):

```python
    async def _pre_plan_compact(self, state: MoriState) -> None:
        if not self._budget:
            return
        from mori.observability.events import BudgetRebalanceEvent, CompactionEvent
        from mori.budget.types import CompactionModules

        budgets = self._budget.rebalance(Phase.PLAN)
        report = self._budget.assemble_budget_report()
        await self._emit(BudgetRebalanceEvent(
            event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
            run_id=state.run_id, phase=Phase.PLAN.value,
            allocations={slot: b.allocated for slot, b in budgets.items()},
            total_consumed=report.total_consumed,
            utilization=report.utilization,
        ))

        if self._budget.needs_compaction():
            compact_report = await self._budget.compact(
                state,
                CompactionModules(
                    memory=self._memory,
                    skills=self._skills,
                    model=self._model,
                ),
            )
            await self._emit(CompactionEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id,
                stages_run=compact_report.stages,
                total_tokens_reclaimed=compact_report.total_tokens_reclaimed,
                final_utilization=compact_report.final_utilization,
            ))
```

**3d — Update `_assemble_request`** to inject `[Skill Context]` and handle `_defer_schemas`:

```python
    def _assemble_request(self, state: MoriState) -> ModelRequest:
        # Schema deferral (Stage 2 compaction)
        if self._budget and self._budget._defer_schemas:
            recent_tools: set[str] = set()
            for msg in state.messages[-6:]:
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        recent_tools.add(tc.name)
            tool_specs = []
            for spec in self._tools.list_specs():
                if spec.name in recent_tools:
                    tool_specs.append(spec)
                else:
                    from mori.types import ToolSpec, ToolId
                    tool_specs.append(ToolSpec(
                        tool_id=spec.tool_id,
                        name=spec.name,
                        description=spec.description,
                        input_schema={},
                        source=spec.source,
                    ))
        else:
            tool_specs = self._tools.list_specs()

        messages = list(state.messages)

        # Inject [Memory Context]
        if state.memory_slice and state.memory_slice.records:
            lines = ["[Memory Context]"]
            for r in state.memory_slice.records:
                lines.append(
                    f"- {r.content} (layer: {r.layer.value}, confidence: {r.confidence})"
                )
            messages.insert(0, Message(role="system", content="\n".join(lines)))

        # Inject [Skill Context]
        if state.active_skill_payload:
            p = state.active_skill_payload
            lines = [f"[Skill Context: {p.skill_id}]", p.content]
            messages.insert(0, Message(role="system", content="\n".join(lines)))

        return ModelRequest(messages=messages, tools=tool_specs if tool_specs else None)
```

**3e — Insert `_pre_plan_compact` into the run loop**, immediately before `_phase_plan`:

In the `run` method, change:
```python
            await self._phase_retrieve(state)
            await self._phase_plan(state)
```
to:
```python
            await self._phase_retrieve(state)
            await self._pre_plan_compact(state)
            await self._phase_plan(state)
```

**3f — Add import** at top of `loop.py` for `BudgetSlot` and `Phase`:

After the existing imports, add:
```python
from mori.budget.types import BudgetSlot
```

`Phase` is already imported from `mori.types`.

- [ ] **Step 4: Run — expect pass**

```
pytest tests/test_loop_v04.py -v
```
Expected: 5 passed

Also run the full v0.3 test suite to confirm no regressions:
```
pytest tests/test_loop_v03.py tests/test_builder_v03.py tests/test_integration_v03.py -v
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add mori/runtime/loop.py tests/test_loop_v04.py
git commit -m "feat: loop v0.4 — expanded retrieve, skill inject, pre-plan compaction"
```

---

### Task 9: Builder Integration

**Files:**
- Modify: `mori/agent.py`
- Create: `tests/test_builder_v04.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_builder_v04.py
from unittest.mock import AsyncMock, patch
import pytest
from mori import Mori
from mori.types import Message, ModelResponse, RunStatus, TokenUsage


def _text_response(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


def test_builder_skill_registry(tmp_path):
    import textwrap
    d = tmp_path / "bug-fix"
    d.mkdir()
    (d / "manifest.yaml").write_text(textwrap.dedent("""\
        name: bug-fix
        version: 1.0.0
        description: Fix tests
        capabilities: []
        scope: {domains: [], contexts: []}
        preconditions: {tools_required: [], min_context_tokens: 0}
        constraints: {max_files: 5, requires_approval_for: []}
        triggers: {semantic: ["fix"], structural: []}
        progressive_disclosure:
          abstract: Fix a test.
          summary: Fix it.
          full: SKILL.md
    """))
    (d / "SKILL.md").write_text("# Fix\nDo it.")
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .skill_registry(str(tmp_path))
            .build()
        )
        assert agent.skills is not None


def test_builder_budget():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .budget(total_context_tokens=100_000)
            .build()
        )
        assert agent.budget is not None


def test_builder_no_skill_registry():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").build()
        assert agent.skills is None


def test_builder_no_budget():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").build()
        assert agent.budget is None


def test_builder_order_independent(tmp_path):
    import textwrap
    d = tmp_path / "s"
    d.mkdir()
    (d / "manifest.yaml").write_text(textwrap.dedent("""\
        name: s
        version: 1.0.0
        description: S
        capabilities: []
        scope: {domains: [], contexts: []}
        preconditions: {tools_required: [], min_context_tokens: 0}
        constraints: {max_files: 1, requires_approval_for: []}
        triggers: {semantic: [], structural: []}
        progressive_disclosure:
          abstract: Short abstract.
          summary: Summary.
          full: SKILL.md
    """))
    (d / "SKILL.md").write_text("# S")
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        # skill_registry before budget
        a1 = (Mori.builder().model("anthropic", api_key="x")
              .skill_registry(str(tmp_path)).budget(total_context_tokens=50_000).build())
        # budget before skill_registry
        a2 = (Mori.builder().model("anthropic", api_key="x")
              .budget(total_context_tokens=50_000).skill_registry(str(tmp_path)).build())
        assert a1.skills is not None
        assert a2.budget is not None


@pytest.mark.asyncio
async def test_agent_run_with_skills_and_budget(tmp_path):
    import textwrap
    d = tmp_path / "bug-fix"
    d.mkdir()
    (d / "manifest.yaml").write_text(textwrap.dedent("""\
        name: bug-fix
        version: 1.0.0
        description: Fix
        capabilities: []
        scope: {domains: [], contexts: []}
        preconditions: {tools_required: [], min_context_tokens: 0}
        constraints: {max_files: 5, requires_approval_for: []}
        triggers: {semantic: ["fix test"], structural: []}
        progressive_disclosure:
          abstract: Fix a failing test.
          summary: Trace and patch.
          full: SKILL.md
    """))
    (d / "SKILL.md").write_text("# Fix\nDo it.")
    with patch("mori.agent.AnthropicAdapter") as M:
        mock = AsyncMock()
        mock.invoke = AsyncMock(return_value=_text_response("fixed"))
        M.return_value = mock
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .skill_registry(str(tmp_path))
            .budget(total_context_tokens=100_000)
            .build()
        )
        result = await agent.run("fix the failing test")
        assert result.status == RunStatus.COMPLETED
        await agent.close()
```

- [ ] **Step 2: Run — expect failures on missing builder methods**

```
pytest tests/test_builder_v04.py -v
```

- [ ] **Step 3: Update `mori/agent.py`**

**3a — Add fields to `MoriBuilder.__init__`:**

```python
        self._skill_registry_path: str | None = None
        self._budget_config: dict | None = None
```

**3b — Add builder methods** (after `memory_backend`):

```python
    def skill_registry(self, path: str) -> MoriBuilder:
        self._skill_registry_path = path
        return self

    def budget(
        self,
        total_context_tokens: int = 200_000,
        compaction_threshold_pct: float = 0.85,
        min_generation_tokens: int = 1000,
        max_result_tokens: int = 4000,
        disable_compaction: bool = False,
        slot_overrides: dict[str, float] | None = None,
    ) -> MoriBuilder:
        self._budget_config = {
            "total_context_tokens": total_context_tokens,
            "compaction_threshold_pct": compaction_threshold_pct,
            "min_generation_tokens": min_generation_tokens,
            "max_result_tokens": max_result_tokens,
            "disable_compaction": disable_compaction,
            "slot_overrides": slot_overrides or {},
        }
        return self
```

**3c — Wire up in `build()`**, at the end before `# 5. Agent loop`:

```python
        # 5. Skills module
        skills_module = None
        if self._skill_registry_path:
            from mori.skills.registry import FilesystemRegistry
            from mori.skills.module import SkillsModule
            reg = FilesystemRegistry(self._skill_registry_path)
            skills_module = SkillsModule(registry=reg)

        # 6. Budget manager
        budget_manager = None
        if self._budget_config:
            from mori.budget.manager import BudgetManager
            from mori.budget.types import BudgetConfig
            budget_manager = BudgetManager(BudgetConfig(**self._budget_config))
```

Then update the AgentLoop construction (was step 5, now step 7):
```python
        # 7. Agent loop
        loop = AgentLoop(
            model=self._model_adapter, tools=registry, observability=obs,
            control=control, memory=memory_module,
            skills=skills_module, budget=budget_manager,
        )
```

And update the `Mori(...)` construction:
```python
        return Mori(loop=loop, tools=registry, observability=obs,
                    mcp_configs=self._mcp_servers, memory=memory_module,
                    skills=skills_module, budget=budget_manager)
```

**3d — Update `Mori.__init__` and add properties:**

```python
    def __init__(
        self,
        loop: AgentLoop,
        tools: ToolRegistry,
        observability: ObservabilityEngine | None = None,
        mcp_configs: list[dict[str, Any]] | None = None,
        memory: Any = None,
        skills: Any = None,
        budget: Any = None,
    ) -> None:
        self._loop = loop
        self._tools = tools
        self._obs = observability
        self._mcp_configs = mcp_configs or []
        self._mcp_connected = False
        self._memory = memory
        self._skills = skills
        self._budget = budget
```

Add properties after `memory`:
```python
    @property
    def skills(self) -> Any:
        return self._skills

    @property
    def budget(self) -> Any:
        return self._budget
```

- [ ] **Step 4: Run — expect pass**

```
pytest tests/test_builder_v04.py -v
```
Expected: 6 passed

Also run the full builder regression suite:
```
pytest tests/test_builder.py tests/test_builder_v02.py tests/test_builder_v03.py -v
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add mori/agent.py tests/test_builder_v04.py
git commit -m "feat: builder v0.4 — .skill_registry() and .budget() methods + Mori properties"
```

---

### Task 10: Skill Artifacts

**Files:**
- Create: `skills/bug-fix/manifest.yaml` + `skills/bug-fix/SKILL.md`
- Create: `skills/code-review/manifest.yaml` + `skills/code-review/SKILL.md`
- Create: `skills/test-generation/manifest.yaml` + `skills/test-generation/SKILL.md`

- [ ] **Step 1: Create `skills/bug-fix/manifest.yaml`**

```yaml
name: bug-fix
version: 1.0.0
description: Fix a failing test or broken code by reproducing, isolating, and patching the root cause.

capabilities:
  - debugging
  - test-repair

scope:
  domains: [code, testing]
  contexts: [ci, development]

preconditions:
  tools_required: [file-reader, test-runner]
  min_context_tokens: 500

constraints:
  max_files: 10
  requires_approval_for: []

triggers:
  semantic:
    - "fix failing test"
    - "debug"
    - "broken"
    - "error"
    - "exception"
    - "traceback"
  structural: []

progressive_disclosure:
  abstract: Fix a failing test by isolating and patching the root cause.
  summary: Read the failing test to understand expected behaviour. Run it to capture the
    error. Read the source under test and trace the execution path to the failure.
    Apply the smallest possible change. Verify the test passes and no regressions
    are introduced.
  full: SKILL.md
```

- [ ] **Step 2: Create `skills/bug-fix/SKILL.md`**

```markdown
# Bug Fix Procedure

## Goal
Fix a failing test or broken code by reproducing the failure, isolating the root cause,
and applying the minimal change that makes the test pass.

## Steps

### 1. Reproduce
Read the failing test file to understand what is expected.
Run the test to confirm it fails and capture the exact error message.

### 2. Isolate Root Cause
Read the source file under test.
Trace the execution path that triggers the failure.
Identify the exact line or condition causing the error.

### 3. Apply Minimal Fix
Make the smallest possible change to fix the root cause.
Do not refactor unrelated code. Do not add features.
Change only what is necessary.

### 4. Verify
Run the failing test again — confirm it passes.
Run the full test suite — confirm no regressions were introduced.

## Constraints
- Never skip or comment out failing assertions.
- Never change the test to match broken behaviour.
- If the fix requires touching more than 3 files, stop and explain why before proceeding.
```

- [ ] **Step 3: Create `skills/code-review/manifest.yaml`**

```yaml
name: code-review
version: 1.0.0
description: Review source files for correctness, style, and test coverage.

capabilities:
  - code-review
  - quality-analysis

scope:
  domains: [code]
  contexts: [pr-review, development]

preconditions:
  tools_required: [file-reader]
  min_context_tokens: 300

constraints:
  max_files: 20
  requires_approval_for: []

triggers:
  semantic:
    - "review"
    - "code quality"
    - "PR review"
    - "check code"
    - "feedback on"
  structural: []

progressive_disclosure:
  abstract: Review code for correctness, style, and missing tests.
  summary: Read each requested file. Check naming, function length, and dead code
    (LOW severity). Check logic, null handling, and error paths (MEDIUM/HIGH).
    Identify untested public functions (MEDIUM). Summarise findings sorted
    HIGH to LOW.
  full: SKILL.md
```

- [ ] **Step 4: Create `skills/code-review/SKILL.md`**

```markdown
# Code Review Procedure

## Goal
Review one or more source files for correctness, style, and test coverage.
Summarise findings with severity labels so the author knows what to fix first.

## Steps

### 1. Read
Read each file requested. Note the language, framework, and apparent intent.

### 2. Check Style
Look for naming inconsistencies, overly long functions, dead code, and unclear
variable names. Flag each with severity LOW.

### 3. Check Logic
Look for off-by-one errors, missing null checks, unhandled error paths, and incorrect
assumptions. Flag each with severity MEDIUM or HIGH.

### 4. Check Test Coverage
Identify public functions or branches with no corresponding test.
Flag missing tests as severity MEDIUM.

### 5. Summarise
Produce a bulleted list of findings sorted HIGH → MEDIUM → LOW.
For each finding, state: file + line reference, severity, description,
and a one-sentence suggested fix.

## Constraints
- Do not rewrite the code — only comment on it.
- If the review covers more than 5 files, limit each file to at most 3 findings.
```

- [ ] **Step 5: Create `skills/test-generation/manifest.yaml`**

```yaml
name: test-generation
version: 1.0.0
description: Write tests for untested code to increase meaningful test coverage.

capabilities:
  - test-writing
  - coverage-analysis

scope:
  domains: [code, testing]
  contexts: [development, ci]

preconditions:
  tools_required: [file-reader, file-writer]
  min_context_tokens: 400

constraints:
  max_files: 10
  requires_approval_for: []

triggers:
  semantic:
    - "write tests"
    - "add coverage"
    - "test generation"
    - "missing tests"
    - "unit test"
  structural: []

progressive_disclosure:
  abstract: Write tests for untested code to increase suite coverage.
  summary: Read the source file and identify untested public functions and uncovered
    branches. Write pytest test functions with descriptive names. Each test covers
    one behaviour. Verify all new tests pass and no regressions appear.
  full: SKILL.md
```

- [ ] **Step 6: Create `skills/test-generation/SKILL.md`**

```markdown
# Test Generation Procedure

## Goal
Write tests for untested code so that the test suite gains meaningful coverage.

## Steps

### 1. Identify Untested Cases
Read the source file.
List: public functions with no tests, branches not covered by existing tests,
and error paths not exercised.

### 2. Write Tests
For each identified case, write one or more test functions using pytest.
Each test must:
- Have a descriptive name: `test_<function>_<scenario>`
- Set up minimal inputs
- Assert a specific, observable output or side-effect

### 3. Verify
Run the new tests. Confirm they pass.
If a test fails, fix the source code or the test — never loosen the assertion.

## Constraints
- Do not modify the source file unless a genuine bug is found.
- Each test function must test exactly one behaviour.
- Use `pytest.mark.parametrize` where the same logic applies to multiple inputs.
```

- [ ] **Step 7: Verify all 3 skill artifacts parse cleanly**

```python
# run inline (no test file needed — uses parser from Task 4)
python -c "
from mori.skills.parser import parse_manifest
for name in ['bug-fix', 'code-review', 'test-generation']:
    m = parse_manifest(f'skills/{name}')
    print(f'OK: {m.name} v{m.version}')
"
```
Expected:
```
OK: bug-fix v1.0.0
OK: code-review v1.0.0
OK: test-generation v1.0.0
```

- [ ] **Step 8: Commit**

```bash
git add skills/
git commit -m "feat: skill artifacts — bug-fix, code-review, test-generation"
```

---

### Task 11: Example + Exit Test

**Files:**
- Create: `examples/skills_and_budget.py`
- Create: `tests/test_integration_v04.py`

- [ ] **Step 1: Write failing exit test**

```python
# tests/test_integration_v04.py
"""v0.4 exit test — skills discovery and budget rebalance events are emitted."""
from unittest.mock import AsyncMock
import pytest
from mori import Mori
from mori.types import Message, ModelResponse, RunStatus, TokenUsage


def _text_response(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="end_turn",
    )


@pytest.fixture
def skills_root(tmp_path):
    import textwrap
    skills = {
        "bug-fix": (
            textwrap.dedent("""\
                name: bug-fix
                version: 1.0.0
                description: Fix failing tests
                capabilities: [debugging]
                scope: {domains: [code], contexts: [test]}
                preconditions:
                  tools_required: []
                  min_context_tokens: 0
                constraints: {max_files: 5, requires_approval_for: []}
                triggers:
                  semantic: ["fix failing test", "debug", "broken", "error"]
                  structural: []
                progressive_disclosure:
                  abstract: Fix a failing test.
                  summary: Trace and patch the root cause, verify tests pass.
                  full: SKILL.md
            """),
            "# Bug Fix\nReproduce, isolate, patch, verify.",
        ),
        "code-review": (
            textwrap.dedent("""\
                name: code-review
                version: 1.0.0
                description: Review code quality
                capabilities: [review]
                scope: {domains: [code], contexts: []}
                preconditions:
                  tools_required: []
                  min_context_tokens: 0
                constraints: {max_files: 10, requires_approval_for: []}
                triggers:
                  semantic: ["review", "code quality", "check code"]
                  structural: []
                progressive_disclosure:
                  abstract: Review code for correctness and style.
                  summary: Read files, check logic and style, summarise findings.
                  full: SKILL.md
            """),
            "# Code Review\nRead, check, summarise.",
        ),
        "test-generation": (
            textwrap.dedent("""\
                name: test-generation
                version: 1.0.0
                description: Write missing tests
                capabilities: [testing]
                scope: {domains: [code], contexts: []}
                preconditions:
                  tools_required: []
                  min_context_tokens: 0
                constraints: {max_files: 5, requires_approval_for: []}
                triggers:
                  semantic: ["write tests", "add coverage", "unit test"]
                  structural: []
                progressive_disclosure:
                  abstract: Write tests for untested code.
                  summary: Identify gaps, write pytest functions, verify.
                  full: SKILL.md
            """),
            "# Test Generation\nIdentify, write, verify.",
        ),
    }
    for name, (manifest_text, skill_md) in skills.items():
        d = tmp_path / name
        d.mkdir()
        (d / "manifest.yaml").write_text(manifest_text)
        (d / "SKILL.md").write_text(skill_md)
    return tmp_path


@pytest.mark.asyncio
async def test_exit_test_skill_discover_and_budget_rebalance(skills_root):
    """Exit test: run emits skill.discover with top_match_name=bug-fix + budget.rebalance."""
    traces = []

    class Sink:
        realtime = True
        async def write(self, e): traces.append(e.model_dump())
        async def write_batch(self, es): traces.extend(e.model_dump() for e in es)
        async def flush(self): pass
        async def close(self): pass

    with pytest.MonkeyPatch().context() as mp:
        import mori.agent as agent_mod
        from unittest.mock import MagicMock
        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(
            return_value=_text_response("I found and fixed the failing test.")
        )
        mock_adapter.model_id = "test"
        mock_adapter.supports_tool_use = True
        mock_adapter.max_context_tokens = 200_000
        mp.setattr("mori.agent.AnthropicAdapter", MagicMock(return_value=mock_adapter))

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .skill_registry(str(skills_root))
            .budget(total_context_tokens=200_000)
            .sink("stdout")
            .build()
        )
        # Inject our trace sink directly
        from mori.observability.engine import ObservabilityEngine
        from mori.observability.events import ObservabilityConfig
        agent._obs = ObservabilityEngine(sinks=[Sink()], config=ObservabilityConfig())
        agent._loop._obs = agent._obs

        result = await agent.run("Fix the failing test in tests/test_auth.py")
        await agent._obs.flush()

    assert result.status == RunStatus.COMPLETED

    skill_events = [e for e in traces if e["event_type"] == "skill.discover"]
    budget_events = [e for e in traces if e["event_type"] == "budget.rebalance"]

    assert len(skill_events) > 0, "No skill.discover events emitted"
    assert skill_events[0]["top_match_name"] == "bug-fix", (
        f"Expected top_match_name='bug-fix', got {skill_events[0].get('top_match_name')!r}"
    )
    assert len(budget_events) > 0, "No budget.rebalance events emitted"

    await agent.close()
```

- [ ] **Step 2: Run — expect failure (missing wiring)**

```
pytest tests/test_integration_v04.py -v
```

- [ ] **Step 3: Run the full test suite to confirm all v0.3 tests still pass**

```
pytest tests/ -v --ignore=tests/test_integration_v04.py
```
Expected: all existing tests pass

- [ ] **Step 4: Fix any failures from Step 3, then re-run exit test**

```
pytest tests/test_integration_v04.py -v
```
Expected: 1 passed

- [ ] **Step 5: Create `examples/skills_and_budget.py`**

```python
"""Skills and budget example — v0.4 "It Learns".

Demonstrates:
  - .skill_registry() — discovers the three built-in skills
  - .budget()         — tracks context allocation per slot
  - skill.discover event showing top match for the task
  - budget.rebalance event showing per-slot allocation

No ANTHROPIC_API_KEY required — uses a mock model adapter.

Usage:
    cd ~/Projects/Mori
    python examples/skills_and_budget.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from mori import Mori
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import ObservabilityConfig
from mori.types import Message, ModelResponse, RunStatus, TokenUsage


def _mock_adapter() -> object:
    adapter = AsyncMock()
    adapter.model_id = "mock"
    adapter.supports_tool_use = True
    adapter.max_context_tokens = 200_000
    adapter.invoke = AsyncMock(
        return_value=ModelResponse(
            message=Message(role="assistant",
                            content="I traced the error and applied a minimal fix."),
            usage=TokenUsage(input_tokens=300, output_tokens=80),
            stop_reason="end_turn",
        )
    )
    return adapter


async def main() -> None:
    skills_root = str(Path(__file__).parent.parent / "skills")

    traces: list[dict] = []

    class TraceSink:
        realtime = True
        async def write(self, e):
            traces.append(e.model_dump())
        async def write_batch(self, es):
            traces.extend(e.model_dump() for e in es)
        async def flush(self): pass
        async def close(self): pass

    import mori.agent as agent_mod
    original = agent_mod.AnthropicAdapter
    agent_mod.AnthropicAdapter = MagicMock(return_value=_mock_adapter())

    try:
        agent = (
            Mori.builder()
            .model("anthropic", api_key="demo")
            .skill_registry(skills_root)
            .budget(total_context_tokens=200_000)
            .build()
        )
        agent._obs = ObservabilityEngine(
            sinks=[TraceSink()], config=ObservabilityConfig()
        )
        agent._loop._obs = agent._obs

        print(f"\n{'━' * 60}")
        print("  Task: Fix the failing test in tests/test_auth.py")
        print(f"{'━' * 60}\n")

        result = await agent.run("Fix the failing test in tests/test_auth.py")
        await agent._obs.flush()

        print(f"  Status : {result.status.value}")
        print(f"  Steps  : {result.total_steps}")

        skill_events = [e for e in traces if e["event_type"] == "skill.discover"]
        budget_events = [e for e in traces if e["event_type"] == "budget.rebalance"]
        compaction_events = [e for e in traces if e["event_type"] == "budget.compaction"]

        print(f"\n{'─' * 60}")
        print("  Skill Discovery")
        print(f"{'─' * 60}")
        for e in skill_events:
            print(f"  candidates : {e['candidates_found']}")
            print(f"  top match  : {e['top_match_name']}  (score={e['top_match_score']})")

        print(f"\n{'─' * 60}")
        print("  Budget Rebalance (PLAN phase)")
        print(f"{'─' * 60}")
        for e in budget_events[:1]:
            print(f"  phase      : {e['phase']}")
            print(f"  utilization: {e['utilization']:.1%}")
            for slot, alloc in e["allocations"].items():
                print(f"    {slot:<16} {alloc:>8} tokens")

        if compaction_events:
            print(f"\n{'─' * 60}")
            print("  Compaction")
            print(f"{'─' * 60}")
            for e in compaction_events:
                print(f"  reclaimed  : {e['total_tokens_reclaimed']} tokens")
                print(f"  final util : {e['final_utilization']:.1%}")

        print(f"\n{'━' * 60}\n")
        await agent.close()
    finally:
        agent_mod.AnthropicAdapter = original


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Run the example to confirm output**

```
cd /Users/carlmueller/Projects/Mori
python examples/skills_and_budget.py
```
Expected: prints task, status=completed, skill discovery showing bug-fix as top match, budget rebalance with 6 slot allocations.

- [ ] **Step 7: Run the complete test suite**

```
pytest tests/ -v
```
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add examples/skills_and_budget.py tests/test_integration_v04.py
git commit -m "feat: v0.4 exit test + skills_and_budget example"
```

---

### Task 12: Final Integration Pass

**Files:** no new files — verification and tag only.

- [ ] **Step 1: Run full test suite**

```
pytest tests/ -v
```
Expected: all tests pass, including `test_integration_v04.py::test_exit_test_skill_discover_and_budget_rebalance`

- [ ] **Step 2: Run the three examples that existed before v0.4**

```
python examples/memory_layers.py
```
Expected: 8 sections complete, no errors.

- [ ] **Step 3: Verify skill artifacts parse via registry**

```python
python -c "
from mori.skills.registry import FilesystemRegistry
reg = FilesystemRegistry('skills')
manifests = reg.search('', limit=10)
for m in manifests:
    print(f'{m.name}  v{m.version}  triggers={m.triggers[\"semantic\"][:2]}')
"
```
Expected:
```
bug-fix  v1.0.0  triggers=['fix failing test', 'debug']
code-review  v1.0.0  triggers=['review', 'code quality']
test-generation  v1.0.0  triggers=['write tests', 'add coverage']
```

- [ ] **Step 4: Final commit and tag**

```bash
git add -A
git commit -m "feat: Mori v0.4 'It Learns' — Skills Module + Budget Manager complete"
git tag v0.4.0
```
