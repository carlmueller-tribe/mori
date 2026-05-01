# 04: Skills Module

**Status:** Draft v3
**Module:** `mori.skills`
**Dependencies:** Spec 01, Spec 05 (ToolRegistry for binding)

---

## 1. Purpose

Externalize the procedural burden of agency. Convert repeated workflow invention into selection, loading, and composition of reusable capability packages. A skill encodes how a class of tasks should be carried out using tools.

## 2. Interface

```python
class SkillsModule:

    def __init__(self, registries: list[SkillRegistry], config: SkillsConfig, embedder: Embedder | None = None) -> None: ...

    # Discovery
    async def discover(self, task_description: str, context: TaskContext | None = None, available_tools: list[ToolSpec] | None = None, max_candidates: int = 5) -> list[SkillCandidate]: ...

    # Loading
    async def load(self, skill_id: SkillId, disclosure_level: DisclosureLevel = DisclosureLevel.SUMMARY, max_tokens: int | None = None) -> SkillPayload: ...

    # Binding (resolves against ToolRegistry.list_specs())
    async def bind(self, skill: SkillPayload, available_tools: list[ToolSpec], available_agents: list[str] | None = None) -> BoundSkill: ...

    # Composition
    async def compose(self, skills: list[SkillId], composition: CompositionSpec) -> SkillPayload: ...

    # Lifecycle
    async def record_outcome(self, skill_id: SkillId, outcome: SkillExecutionOutcome) -> None: ...
    async def health(self, skill_id: SkillId) -> SkillHealthReport: ...
    async def list_skills(self, registry: str | None = None, tags: list[str] | None = None) -> list[SkillManifest]: ...
    async def close(self) -> None: ...
```

## 3. Configuration

```python
class SkillsConfig(MoriModel):
    discovery_max_candidates: int = 10
    discovery_min_score: float = 0.3
    default_disclosure_level: DisclosureLevel = DisclosureLevel.SUMMARY
    max_full_load_tokens: int = 8000
    cache_manifests: bool = True
    manifest_refresh_interval_sec: float = 300.0
    health_window_runs: int = 50
    staleness_threshold_days: int = 90
    composition_max_depth: int = 3
```

## 4. Skill Artifact Structure

```
{skill_name}/
├── manifest.yaml          # REQUIRED
├── SKILL.md               # REQUIRED
├── constraints.yaml       # OPTIONAL
├── examples/              # OPTIONAL
└── tests/                 # OPTIONAL
```

### 4.1 Manifest Schema

```yaml
name: string                    # Alphanumeric, hyphen, underscore
version: string                 # Semver
description: string

capabilities:
  - string

scope:
  domains: [string]
  contexts: [string]

preconditions:
  tools_required: [string]      # Tool names or patterns
  memory_required: [string]
  min_context_tokens: int

constraints:
  max_files: int
  requires_approval_for: [string]
  risk_categories: [string]     # References RiskTaxonomy category IDs

triggers:
  semantic: [string]
  structural: [string]

progressive_disclosure:
  abstract: string              # < 100 chars
  summary: string               # < 500 tokens
  full: "SKILL.md"
```

### 4.2 Validation Rules

- `name` must be non-empty, alphanumeric/hyphen/underscore only
- `version` must be valid semver
- `progressive_disclosure.abstract` must be under 100 characters
- `progressive_disclosure.summary` must be under 500 tokens
- `SKILL.md` must exist and be non-empty
- If `constraints.yaml` exists, it must be valid YAML

## 5. Skill Registry Interface

```python
class SkillRegistry(Protocol):
    @property
    def name(self) -> str: ...
    async def list_manifests(self, tags: list[str] | None = None) -> list[SkillManifest]: ...
    async def get_manifest(self, skill_id: SkillId) -> SkillManifest | None: ...
    async def load_content(self, skill_id: SkillId, disclosure_level: DisclosureLevel) -> str | None: ...
    async def search(self, query: str, limit: int = 10) -> list[tuple[SkillManifest, float]]: ...
```

**Included:** `FilesystemRegistry` (reads skill directories from a local path), `CompositeRegistry` (wraps multiple registries).

## 6. Discovery Pipeline

**Stage 1: Semantic Match.** Embed task description, compute cosine similarity against cached skill embeddings (from trigger phrases + descriptions). Return top N above `discovery_min_score`.

**Stage 2: Compatibility Check.** For each candidate: are `preconditions.tools_required` available? Are `preconditions.memory_required` keys present? Is `min_context_tokens` within budget? Produce a CompatibilityReport.

**Stage 3: Rank and Filter.** Composite: `0.7 * semantic_score + 0.3 * compatibility_score`. Filter out candidates with missing required tools.

## 7. Progressive Disclosure

| Level    | Content                                         | When to Load                        | Typical Tokens |
|----------|-------------------------------------------------|-------------------------------------|----------------|
| ABSTRACT | Name + one-line description                     | Always (tool/skill listing)         | 10-30          |
| SUMMARY  | Scope, constraints, high-level procedure         | Model is choosing a skill           | 100-500        |
| FULL     | Complete guide, examples, exception handling      | Model commits to execution          | 1000-8000      |

Never load FULL speculatively. Budget Manager must approve the token allocation.

## 8. Composition

```python
class CompositionSpec(MoriModel):
    pattern: Literal["serial", "parallel", "conditional", "recursive"]
    skill_order: list[SkillId]
    conditions: dict[str, str] | None = None
    data_flow: dict[str, str] | None = None
```

## 9. Health Tracking

```python
class SkillExecutionOutcome(MoriModel):
    skill_id: SkillId
    run_id: RunId
    success: bool
    steps_taken: int
    failure_reason: str | None = None
    timestamp: datetime

class SkillHealthReport(MoriModel):
    skill_id: SkillId
    total_runs: int
    success_rate: float
    avg_steps: float
    common_failures: list[str]
    last_used: datetime | None
    last_updated: datetime | None
    stale: bool
```

## 10. Task Context

```python
class TaskContext(MoriModel):
    task_description: str
    current_plan: PlanObject | None = None
    recent_actions: list[str] = Field(default_factory=list)
    active_memory_keys: list[str] = Field(default_factory=list)
    user_preferences: dict = Field(default_factory=dict)
    environment: dict = Field(default_factory=dict)
```

## 11. AIUC-1 Contracts

Per `12-AIUC1-COMPLIANCE.md` Section 2.3:
- Skills Module MUST check Permission Engine for READ (discover) and EXECUTE (bind/run)
- Skill manifests MUST support a `risk_categories` field referencing the RiskTaxonomy
- Skills with grounding requirements (`preconditions.memory_required`) force context retrieval before reasoning (D001)
- Skill health tracking MUST record outcomes in observability events

## 12. Test Criteria

- [ ] A valid skill artifact directory passes validation
- [ ] An artifact missing manifest.yaml fails with a clear error
- [ ] Discovery returns skills sorted by composite score descending
- [ ] Discovery filters out skills with missing required tools
- [ ] Progressive disclosure at ABSTRACT level returns < 30 tokens
- [ ] Progressive disclosure at FULL level respects max_tokens truncation
- [ ] Binding maps tool requirements to available tools from ToolRegistry
- [ ] Binding reports unresolved tools in BoundSkill.unresolved
- [ ] Composition in serial mode produces phases in the correct order
- [ ] Health tracking computes correct success rate over configured window
- [ ] Stale skills are flagged when last_updated exceeds threshold
- [ ] FilesystemRegistry discovers all valid artifacts in a directory
- [ ] CompositeRegistry merges results from multiple sub-registries
- [ ] Manifests with invalid semver fail validation
- [ ] Permission Engine is checked before discover and execute
