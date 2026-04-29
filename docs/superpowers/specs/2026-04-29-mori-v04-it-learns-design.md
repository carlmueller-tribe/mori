# Mori v0.4 "It Learns" — Design Spec

**Date:** 2026-04-29
**Branch:** v0.4/it-learns
**Status:** Approved

---

## 1. Goal

Agent discovers reusable skill procedures and follows them. A Budget Manager governs context window allocation across all content slots and runs a graduated compaction pipeline to prevent overflow.

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(read_file, description="Read a file")
    .cli("pytest", command="pytest", description="Run tests", args_format="flags")
    .memory_backend("sqlite", path="./memory.db")
    .skill_registry("./skills/")
    .budget(total_context_tokens=200_000)
    .sink("stdout")
    .build()
)
result = await agent.run("Fix the failing test in tests/test_auth.py")
```

---

## 2. Architecture

Two new top-level modules; one runtime loop expansion; no new loop phases.

```
mori/
├── skills/
│   ├── module.py       # SkillsModule — discover, load, bind, record_outcome, health
│   ├── registry.py     # SkillRegistry protocol, FilesystemRegistry, CompositeRegistry
│   ├── parser.py       # manifest.yaml validation + SKILL.md loader
│   └── types.py        # SkillManifest, SkillCandidate, SkillPayload, BoundSkill, …
├── budget/
│   ├── manager.py      # BudgetManager — allocate, consume, rebalance, compact
│   └── types.py        # BudgetSlot, BudgetConfig, CompactionStage, CompactionReport, …
├── runtime/
│   └── loop.py         # _phase_retrieve expanded; compact() before _phase_plan
└── agent.py            # .skill_registry() and .budget() builder methods

skills/                 # artifact directories (outside package)
├── bug-fix/
│   ├── manifest.yaml
│   └── SKILL.md
├── code-review/
│   ├── manifest.yaml
│   └── SKILL.md
└── test-generation/
    ├── manifest.yaml
    └── SKILL.md
```

New observability events: `SkillDiscoverEvent`, `SkillLoadEvent`, `BudgetRebalanceEvent`, `CompactionEvent`.

---

## 3. Skills Module

### 3.1 Types (`mori/skills/types.py`)

```python
SkillManifest          # parsed manifest.yaml — name, version, description, capabilities,
                       # scope, preconditions, constraints, triggers, progressive_disclosure

SkillCandidate         # manifest + score (float) + compatibility_report (CompatibilityReport)

CompatibilityReport    # tools_satisfied: bool, missing_tools: list[str],
                       # context_fits: bool, required_tokens: int

SkillPayload           # skill_id, disclosure_level, content (str), token_estimate (int)

BoundSkill             # payload + resolved_tools: dict[str, ToolSpec]
                       #        + unresolved: list[str]

SkillExecutionOutcome  # skill_id, run_id, success, steps_taken,
                       # failure_reason: str | None, timestamp

SkillHealthReport      # skill_id, total_runs, success_rate, avg_steps,
                       # common_failures: list[str], last_used, stale: bool

SkillValidationError   # raised by parser on invalid manifests
```

### 3.2 Manifest Schema

```yaml
name: string                      # alphanumeric, hyphen, underscore only
version: string                   # semver (e.g. "1.0.0")
description: string

capabilities:
  - string

scope:
  domains: [string]
  contexts: [string]

preconditions:
  tools_required: [string]        # tool names the agent must have registered
  min_context_tokens: int

constraints:
  max_files: int
  requires_approval_for: [string]

triggers:
  semantic: [string]              # phrases used for embedding-based discovery
  structural: [string]

progressive_disclosure:
  abstract: string                # < 100 chars
  summary: string                 # < 500 tokens
  full: "SKILL.md"
```

Validation rules:
- `name` non-empty, alphanumeric/hyphen/underscore only
- `version` valid semver
- `abstract` under 100 characters
- `summary` under 500 tokens (estimated as `len / 4`)
- `SKILL.md` must exist and be non-empty

### 3.3 FilesystemRegistry (`mori/skills/registry.py`)

Scans a directory for subdirectories containing `manifest.yaml`. Parses and caches manifests on first call. Invalid manifests are logged and skipped — one bad skill never blocks the registry.

`search(query, limit)`:
- With embedder: cosine similarity between embedded query and embedded trigger phrases + description
- Without embedder: returns all manifests in directory order (model picks from full list)

`CompositeRegistry` wraps multiple `FilesystemRegistry` instances and merges their results.

### 3.4 SkillsModule (`mori/skills/module.py`)

**`discover(task, available_tools, max_candidates=5)`**

Three stages:
1. Semantic match — embed task + score against trigger phrases, or return all in order
2. Compatibility check — are `tools_required` present in `available_tools`? Does `min_context_tokens` fit within the SKILL budget slot?
3. Rank — `0.7 * semantic_score + 0.3 * compatibility_score` (or `1.0 * compatibility_score` when no embedder)

Returns `list[SkillCandidate]` sorted descending. Incompatible skills (missing tools) excluded.

**`load(skill_id, disclosure_level, max_tokens)`**

Returns `SkillPayload` at ABSTRACT / SUMMARY / FULL level. FULL reads `SKILL.md` and truncates to `max_tokens`. Never loads FULL speculatively — caller must explicitly request it.

**`bind(payload, available_tools)`**

Maps `preconditions.tools_required` against available tool names. Returns `BoundSkill` with:
- `resolved_tools`: matched `ToolSpec` objects
- `unresolved`: names with no match (not an error — caller decides how to handle)

**`record_outcome(skill_id, outcome)`**

Appends to in-memory health window (last 50 runs per skill, circular buffer).

**`health(skill_id)`**

Computes `SkillHealthReport` from window: success rate, average steps, most common failure reasons, stale flag (no use in last 90 days).

---

## 4. Budget Manager

### 4.1 Slots and Default Allocation (`mori/budget/types.py`)

```python
class BudgetSlot(str, Enum):
    SYSTEM_PROMPT = "system_prompt"   # 10%
    MEMORY        = "memory"          # 20%
    SKILL         = "skill"           # 15%
    TOOL_SCHEMAS  = "tool_schemas"    # 10%
    CONVERSATION  = "conversation"    # 30%
    GENERATION    = "generation"      # 15%
```

Phase overrides (applied during rebalance):
- `Phase.PLAN`: MEMORY → 25%, CONVERSATION → 30%, SKILL → 10%
- `Phase.ACT`:  SKILL → 20%, TOOL_SCHEMAS → 15%, MEMORY → 15%

`min_generation_tokens = 1000` enforced at all times — stolen from the largest non-generation slot if needed.

### 4.2 BudgetManager Interface (`mori/budget/manager.py`)

```python
class BudgetManager:
    def get_allocation(slot: BudgetSlot) -> TokenBudget
    def consume(slot: BudgetSlot, tokens: int) -> ConsumeResult
    def release(slot: BudgetSlot, tokens: int) -> None
    def reset_slot(slot: BudgetSlot) -> None
    def rebalance(phase: Phase, hints: RebalanceHints | None = None) -> dict[BudgetSlot, TokenBudget]
    def needs_compaction() -> bool          # true when consumed > 85% of total
    async def compact(state, modules: CompactionModules) -> CompactionReport
    def assemble_budget_report() -> BudgetReport
```

### 4.3 Compaction Pipeline — 6 Stages

Stages run in order, cheapest first. Pipeline stops as soon as `needs_compaction()` returns false. Each stage calls `release(slot, tokens_reclaimed)` after it completes.

| # | Stage | Action | Slot | Cost |
|---|-------|--------|------|------|
| 1 | Result Trim | Truncate tool results in `state.messages` to `max_result_tokens` (4000 chars) | CONVERSATION | Zero |
| 2 | Schema Defer | Replace full tool schemas with `{name, description}` stubs for tools unused in last 3 steps | TOOL_SCHEMAS | Zero |
| 3 | Turn Snip | Drop tool call/result pairs from oldest turns; keep assistant text only | CONVERSATION | Zero |
| 4 | Skill Downgrade | Reduce active skill payload from FULL → SUMMARY disclosure level | SKILL | Zero |
| 5 | Memory Prune | Re-retrieve memory at half current token budget; drop low-confidence records | MEMORY | Cheap |
| 6 | Conversation Summarize | Model call: summarize oldest N turns into one summary message inserted into `state.messages` | CONVERSATION | Expensive |

`CompactionReport` records tokens reclaimed per stage and final utilization. A `CompactionEvent` is emitted after the pipeline completes.

`CompactionModules` passed in at call time (not stored), keeping BudgetManager decoupled from other modules:

```python
class CompactionModules(MoriModel):
    memory: MemoryModule | None = None   # Stage 5
    skills: SkillsModule | None = None   # Stage 4
    model:  ModelAdapter | None = None   # Stage 6
    model_config = {"arbitrary_types_allowed": True}
```

---

## 5. Runtime Integration

### 5.1 Expanded `_phase_retrieve`

```
memory read  →  skill discover  →  skill load (SUMMARY)  →  inject both into context
```

1. Read memory (unchanged) — consume against MEMORY slot
2. `SkillsModule.discover(task, available_tools)` — top candidate loaded at SUMMARY level; consume against SKILL slot
3. Inject both as system message blocks ahead of conversation history:
   - `[Memory Context]` (existing)
   - `[Skill Context]` (new) — skill name, summary, unresolved tool warnings if any
4. Emit `SkillDiscoverEvent` (top match name + score) and `SkillLoadEvent` (disclosure level + token count)

If no skill registry is configured, step 2–4 are skipped.

### 5.2 Compaction Before `_phase_plan`

```python
await self._budget.rebalance(Phase.PLAN, hints)
if self._budget.needs_compaction():
    report = await self._budget.compact(state, CompactionModules(
        memory=self._memory,
        skills=self._skills,
        model=self._model,
    ))
    await self._emit(CompactionEvent(..., report=report))
```

Called every step before every model call. Stage 6 replaces the oldest N assistant turns in `state.messages` with a single summary message.

### 5.3 TOOL_SCHEMAS Slot Tracking

`_assemble_request` counts tool schema tokens and consumes against the TOOL_SCHEMAS slot before building the request. Schema Defer (stage 2) swaps full schemas for stubs and calls `release(TOOL_SCHEMAS, delta)`.

### 5.4 Backward Compatibility

If `.budget()` is not called on the builder, `AgentLoop._budget` is `None` and all budget code paths are skipped — no behaviour change for existing agents. If `.skill_registry()` is not called, `_skills` is `None` and discover returns empty.

Builder method order never matters. All methods are pure config collectors; `.build()` is the sole assembly point.

---

## 6. Builder API

```python
# New builder methods:
.skill_registry(path: str) -> MoriBuilder
    # Creates FilesystemRegistry at path; stored and passed to SkillsModule in build()

.budget(
    total_context_tokens: int = 200_000,
    compaction_threshold_pct: float = 0.85,
    min_generation_tokens: int = 1000,
    max_result_tokens: int = 4000,
) -> MoriBuilder
    # Creates BudgetManager with BudgetConfig; passed to AgentLoop in build()

# New Mori properties:
agent.skills -> SkillsModule | None
agent.budget -> BudgetManager | None
```

---

## 7. Skill Artifacts

Three skills in `skills/` at repo root, used by the exit test and examples.

**`skills/bug-fix/`**
- Triggers: `["fix failing test", "debug", "broken", "error", "exception", "traceback"]`
- Tools required: file-reader, test-runner
- Procedure (SKILL.md): reproduce → isolate root cause → apply minimal fix → verify tests pass

**`skills/code-review/`**
- Triggers: `["review", "code quality", "PR review", "check code", "feedback on"]`
- Tools required: file-reader
- Procedure: read files → check style, logic, test coverage → summarise findings with severity

**`skills/test-generation/`**
- Triggers: `["write tests", "add coverage", "test generation", "missing tests", "unit test"]`
- Tools required: file-reader, file-writer
- Procedure: identify untested cases → write test → verify it passes

---

## 8. Observability Events

```python
SkillDiscoverEvent   # run_id, task_preview, candidates_found, top_match_name,
                     # top_match_score, duration_ms

SkillLoadEvent       # run_id, skill_id, disclosure_level, token_estimate, duration_ms

BudgetRebalanceEvent # run_id, phase, allocations: dict[BudgetSlot, int],
                     # total_consumed, utilization

CompactionEvent      # run_id, stages_run: list[StageResult],
                     # total_tokens_reclaimed, final_utilization
```

---

## 9. Exit Test

```python
result = await agent.run("Fix the failing test in tests/test_auth.py")
skill_events  = [e for e in traces if e["event_type"] == "skill.discover"]
budget_events = [e for e in traces if e["event_type"] == "budget.rebalance"]
assert len(skill_events) > 0
assert skill_events[0]["top_match_name"] == "bug-fix"
assert len(budget_events) > 0
```

---

## 10. Test Criteria

**Skills:**
- Valid skill artifact directory passes validation
- Missing `manifest.yaml` raises `SkillValidationError` with clear message
- Invalid semver in manifest raises `SkillValidationError`
- `abstract` > 100 chars raises `SkillValidationError`
- Discovery returns candidates sorted by composite score descending
- Discovery filters skills whose `tools_required` are not in available tools
- Discovery without embedder returns all skills in manifest directory order
- ABSTRACT disclosure returns < 30 tokens
- FULL disclosure respects `max_tokens` truncation
- Binding maps required tools to available `ToolSpec` objects
- Binding reports unresolved tools in `BoundSkill.unresolved`
- Health tracking computes correct success rate over 50-run window
- Stale skills flagged when no use in 90 days
- `FilesystemRegistry` discovers all valid artifacts; skips invalid ones
- `CompositeRegistry` merges results from multiple registries

**Budget Manager:**
- Base allocations summing to > 1.0 raise validation error
- `get_allocation` returns correct integer token counts
- `consume` tracks per-slot usage and flags over-budget
- `release` frees tokens back to slot
- `reset_slot` zeroes consumption
- `rebalance` with no phase overrides returns base allocations
- `rebalance` with phase overrides adjusts specified slots and normalises to sum to total
- `min_generation_tokens` enforced even under pressure
- `needs_compaction()` triggers at correct threshold
- Stage 1 truncates oversized tool results in state messages
- Stage 2 replaces full schemas with stubs for unused tools
- Stage 3 drops tool call/result pairs from oldest turns
- Stage 4 downgrades active skill from FULL to SUMMARY
- Stage 5 re-retrieves memory with half budget
- Stage 6 calls model and inserts summary message into state
- Pipeline stops early when utilisation drops below threshold
- `CompactionReport` correctly tracks tokens reclaimed per stage

---

## 11. Deferred to v0.5 — QuotaManager

The BudgetManager manages what fits in the context window *right now* (per-request, resets each run).
Cross-run spend tracking is a governance concern that belongs in v0.5 alongside the Permission Engine.

**QuotaManager** (v0.5 addition):
```python
.quota(
    max_tokens_per_run=50_000,
    max_tokens_per_day=5_000_000,
    max_cost_per_day_usd=10.00,
    backend="sqlite",        # persists across restarts
    on_exceeded="escalate",  # or "deny" or "warn"
)
```

Handoff from v0.4: `BudgetManager` emits a `TokenSpendEvent` at run end (input + output tokens +
estimated cost). `QuotaManager` in v0.5 accumulates these into a persistent daily ledger per identity.

Requires: identity (who is spending?), persistence (cross-run ledger), policy (quota rules),
enforcement (deny/escalate when exceeded) — all of which v0.5 introduces via the Permission Engine.
