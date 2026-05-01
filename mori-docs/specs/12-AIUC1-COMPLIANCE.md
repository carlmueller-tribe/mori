# 12: AIUC-1 Integration

**Status:** Draft v3.1 (Cross-Cutting)
**Module:** `mori.compliance` + annotations in every module
**Dependencies:** All prior specs

---

## 1. Purpose

AIUC-1 is not a bolt-on compliance layer. It is a cross-cutting concern woven into every Mori module. This spec documents exactly what each module does for AIUC-1, what the `mori.compliance` module adds on top, and how the system produces audit evidence.

The goal: a Tribe client using Mori's standard features is already 80% of the way to AIUC-1 certification. The remaining 20% is configuration and organizational policy, not engineering.

## 2. AIUC-1 Per Module

### 2.1 Runtime (Spec 02)

| AIUC-1 Req | Runtime Behavior |
|------------|-----------------|
| C009: Real-time feedback | `stream()` yields typed events at every phase boundary. `cancel()` and `pause()` enable real-time intervention. |
| E001-E003: Failure plans | Checkpoint/resume provides the recovery substrate. On failure, the runtime saves state, emits failure events, and returns a RunResult with full trace. |
| E015: Log model activity | Every model invocation passes through the plan phase, which emits observability events with input/output token counts, tool calls, and response metadata. |

**Runtime contract:** the agent loop MUST emit an observability event at every phase boundary. No silent phases. If a phase is skipped (e.g., no permission engine configured), a skip event is emitted.

### 2.2 Memory (Spec 03)

| AIUC-1 Req | Memory Behavior |
|------------|----------------|
| A003: Limit agent data access | Every `read()` and `write()` call checks the Permission Engine for READ or WRITE on the target memory layer. An agent in the "restricted" group cannot read episodic memory if the policy denies it. |
| A005: Prevent cross-customer exposure | Memory backends namespace records by thread_id. The personalized memory layer uses identity-scoped keys. No cross-identity leakage is possible without explicit READ permission. |
| A006: Prevent PII leakage | The `memory.write.before` hook point enables PIIGuard to scan and redact records before persistence. PII never enters the memory store. |

**Memory contract:** all memory operations MUST pass through the Permission Engine before touching the backend. The Memory Module MUST emit `memory.read` and `memory.write` observability events with layer, record count, and identity.

### 2.3 Skills (Spec 04)

| AIUC-1 Req | Skills Behavior |
|------------|----------------|
| C004: Prevent out-of-scope | Every skill artifact includes `constraints.yaml` which can declare `risk_categories`. When a skill with `risk_categories: [out_of_scope]` is active, the OutputScopeGuard activates automatically. |
| C005: Customer-defined risk | Skill manifests reference risk taxonomy category IDs. Custom risk categories defined in the taxonomy propagate to skill-level enforcement. |
| D001: Prevent hallucinations | Skills with grounding requirements (e.g., `preconditions.memory_required: ["source_documents"]`) force the retrieve phase to load context before the model reasons. This is structural grounding, not post-hoc checking. |

**Skills contract:** the Skills Module MUST check Permission Engine for READ (discover) and EXECUTE (bind/run) on every skill. Skill manifests MUST support a `risk_categories` field that references the RiskTaxonomy. Skill health tracking MUST record outcomes in observability events.

### 2.4 Tools and Protocols (Spec 05)

| AIUC-1 Req | Tools Behavior |
|------------|---------------|
| B004: Prevent endpoint scraping | ToolRegistry enforces configurable rate limits per MCP server. Exceeding the limit returns an error, not a queue. |
| B006: Prevent unauthorized actions | Every `invoke()` call checks Permission Engine for EXECUTE on the tool resource. The model only sees tools it has READ permission on. |
| D003: Restrict unsafe tool calls | Schema validation rejects malformed arguments before invocation. Permission rules can deny or escalate specific tool patterns. |
| D004: 3P testing of tool calls | Every invocation emits a `tool.invoke` + `tool.result` observability event with arguments, result, latency, and success/failure. This is the audit trail. |

**Tools contract:** `list_specs()` MUST filter tools by the active identity's READ permission. `invoke()` MUST check EXECUTE permission before calling. `invoke()` MUST validate arguments against schema before calling. Every invocation MUST emit observability events. Error rate tracking MUST be maintained per tool.

### 2.5 Permission System (Spec 06)

| AIUC-1 Req | Permission Behavior |
|------------|---------------------|
| A003: Limit agent data access | Memory layer r/w/x per identity/group |
| B006: Prevent unauthorized actions | Universal resource governance across all resource types |
| B007: Enforce user access privileges | Identity/group model with configurable policies |
| D003: Restrict unsafe tool calls | Tool execute permissions with conditions and escalation |
| E004: Assign accountability | Every check logged with identity, resource, decision, and matching rule |

**Permission contract:** every module MUST call the Permission Engine before accessing any resource. The Permission Engine MUST log every check via the Observability Engine. Deny-wins semantics MUST be enforced.

### 2.6 Control (Spec 07)

| AIUC-1 Req | Control Behavior |
|------------|-----------------|
| E001-E003: Failure plans | Checkpoint store enables recovery from any failure state. The runtime can resume from the last successful step. |
| B008: Protect deployment environment | Checkpoint data is serialized via Pydantic (no pickle). Checkpoint stores can enforce encryption at rest. |

**Control contract:** checkpoint serialization MUST NOT use pickle or any format that enables code execution on deserialization. Checkpoint stores SHOULD support encryption at rest via configuration.

### 2.7 Observability (Spec 08)

| AIUC-1 Req | Observability Behavior |
|------------|----------------------|
| E015: Log model activity | Structured events for every model invocation, tool call, memory operation, permission check, and skill load. |
| C008: Monitor risk categories | Every event carries an optional `risk_flags` field populated by guards and the risk taxonomy. |
| E008: Review internal processes | Event aggregation enables periodic compliance reviews. |
| E014: Transparency reports | Evidence exporter (see Section 3) maps events to AIUC-1 requirements. |

**Observability contract:** every MoriEvent MUST support a `risk_flags: list[RiskFlag]` field. Sinks MUST NOT silently drop events. The engine MUST support flush-on-shutdown to prevent data loss.

### 2.8 Budget (Spec 09)

| AIUC-1 Req | Budget Behavior |
|------------|----------------|
| B009: Limit output over-exposure | Budget constraints on the generation slot cap output length. Combined with output guards, this limits information exposure. |

### 2.9 Hooks (Spec 10)

| AIUC-1 Req | Hooks Behavior |
|------------|---------------|
| B005: Real-time input filtering | InputFilterGuard registers as a before-hook on model requests. |
| A006: Prevent PII leakage | PIIGuard registers as before-hooks on tool invocations, model responses, and memory writes. |
| A004: Protect IP | IPGuard registers as an after-hook on model responses. |
| C009: Real-time feedback | Custom hooks enable intervention at any point. |

**Hooks contract:** guards (Section 3.2) MUST register at priority 1 (before all user hooks). Guards with `action=block` MUST prevent the operation from proceeding. Guard detections MUST be logged as observability events with risk_flags.

## 3. The `mori.compliance` Module

This module provides three additions that sit on top of the per-module behaviors above.

### 3.1 Risk Taxonomy

A YAML-configurable risk classification that every module references.

```python
class RiskTaxonomy(MoriModel):
    categories: list[RiskCategory]
    default_severity: Severity = Severity.MEDIUM

class RiskCategory(MoriModel):
    id: str                     # "harmful_content", "pii_exposure", etc.
    name: str
    description: str
    severity: Severity
    action: RiskAction          # log, warn, escalate, block
    examples: list[str] = Field(default_factory=list)

class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class RiskAction(str, Enum):
    LOG = "log"
    WARN = "warn"
    ESCALATE = "escalate"
    BLOCK = "block"
```

**Integration:** the RiskTaxonomy is loaded at startup and shared across:
- Permission Engine: rules can reference risk categories in conditions
- Skills Module: skill manifests declare relevant risk categories
- Observability Engine: events carry risk_flags referencing taxonomy category IDs
- Guards: guard detections map to taxonomy categories

### 3.2 Data Guards

Built-in hook implementations for common data protection patterns.

```python
class PIIGuard:
    """Scans inputs, outputs, and memory writes for PII. Redacts or blocks.
    Addresses: A006 (PII leakage), A003 (data access limits)."""

    async def scan_tool_args(self, payload: ToolCall) -> ToolCall: ...
    async def scan_model_output(self, payload: ModelResponse) -> ModelResponse: ...
    async def scan_memory_write(self, records: list[MemoryRecord]) -> list[MemoryRecord]: ...

class IPGuard:
    """Scans outputs for proprietary patterns and secrets.
    Addresses: A004 (IP protection), A007 (IP violations)."""

    async def scan_output(self, payload: ModelResponse) -> ModelResponse: ...

class InputFilterGuard:
    """Detects prompt injection and adversarial input patterns.
    Addresses: B002 (detect adversarial input), B005 (input filtering)."""

    async def scan_input(self, payload: Message) -> Message: ...

class OutputScopeGuard:
    """Prevents responses outside defined topic boundaries.
    Addresses: C004 (out-of-scope), C003 (harmful outputs)."""

    async def check_output(self, payload: ModelResponse) -> ModelResponse: ...
```

**Registration:** guards register via `.guard()` on the builder, which internally registers their methods as hooks at priority 1.

```python
agent = (
    Mori.builder()
    .model(...)
    .risk_taxonomy("./risk_taxonomy.yaml")
    .guard(PIIGuard(action="redact"))
    .guard(IPGuard(secret_patterns=[r"sk-[a-zA-Z0-9]{48}"]))
    .guard(InputFilterGuard())
    .guard(OutputScopeGuard(allowed_topics=["engineering", "code", "testing"]))
    .build()
)
```

### 3.3 Evidence Exporter

Maps Mori's observability events to AIUC-1 requirement IDs and produces structured evidence packages.

```python
class EvidenceExporter:
    """Generates AIUC-1 formatted evidence from Mori events."""

    async def export_run(self, run_id: RunId, events: list[MoriEvent]) -> EvidencePackage: ...
    async def export_period(self, start: datetime, end: datetime, events: list[MoriEvent]) -> EvidencePackage: ...
    async def generate_summary(self, events: list[MoriEvent]) -> ComplianceSummary: ...

class EvidencePackage(MoriModel):
    export_id: str
    generated_at: datetime
    period_start: datetime
    period_end: datetime
    total_runs: int
    domain_coverage: dict[str, DomainEvidence]

class DomainEvidence(MoriModel):
    domain: str
    domain_name: str
    requirements_addressed: list[RequirementEvidence]

class RequirementEvidence(MoriModel):
    requirement_id: str             # "A003", "B006", "D003"
    requirement_name: str
    mandatory: bool
    mori_module: str                # Which module provides evidence
    evidence_type: Literal["log", "config", "test", "metric"]
    evidence_summary: str
    sample_events: list[dict] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)

class ComplianceSummary(MoriModel):
    period_start: datetime
    period_end: datetime
    total_runs: int
    total_tool_calls: int
    total_permission_checks: int
    total_denials: int
    total_escalations: int
    total_pii_detections: int
    total_risk_flags: dict[str, int]    # Risk category -> count
    coverage: dict[str, float]          # AIUC-1 domain -> % requirements with evidence
```

## 4. Risk-Aware Events

Every MoriEvent gains risk metadata:

```python
class MoriEvent(MoriModel):
    # ... existing fields ...
    risk_flags: list[RiskFlag] = Field(default_factory=list)

class RiskFlag(MoriModel):
    category_id: str        # From RiskTaxonomy
    severity: Severity
    detail: str
    action_taken: RiskAction
```

This makes every event self-describing with respect to risk. An auditor can filter the entire event stream by risk category.

## 5. Complete AIUC-1 Mapping

| Req | Name | Mandatory | Mori Module | Mechanism |
|-----|------|-----------|-------------|-----------|
| A001 | Input data policy | Yes | Config | mori.yaml data policy section |
| A002 | Output data policy | Yes | Config | mori.yaml data policy section |
| A003 | Limit agent data access | Yes | Permission (Spec 06) | Memory layer r/w/x per identity/group |
| A004 | Protect IP | Yes | IPGuard | Output scanning hook |
| A005 | Cross-customer isolation | Yes | Memory (Spec 03) | Namespaced layers, thread isolation |
| A006 | Prevent PII leakage | Yes | PIIGuard | Input/output/memory scanning hooks |
| A007 | Prevent IP violations | Yes | IPGuard + Skills | Output filtering + normative constraints |
| B001 | Adversarial testing | Yes | Evidence Exporter | Structured test harness support |
| B002 | Detect adversarial input | No | InputFilterGuard | Injection pattern detection |
| B004 | Prevent scraping | Yes | Tools (Spec 05) | Rate limiting per server |
| B005 | Input filtering | No | InputFilterGuard | Pre-model scanning hook |
| B006 | Prevent unauthorized actions | Yes | Permission (Spec 06) | Universal resource governance |
| B007 | User access privileges | Yes | Permission (Spec 06) | Identity/group model |
| B008 | Protect deployment | Yes | Control (Spec 07) | No pickle, encryption-ready checkpoints |
| B009 | Limit output exposure | Yes | Budget (Spec 09) + Guards | Generation cap + output filtering |
| C001 | Risk taxonomy | Yes | RiskTaxonomy | First-class config shared across modules |
| C003 | Prevent harmful outputs | Yes | Guards + Risk Taxonomy | Output hooks per risk category |
| C004 | Prevent out-of-scope | Yes | OutputScopeGuard + Skills | Scope boundaries + constraints.yaml |
| C005 | Customer-defined risk | Yes | Risk Taxonomy + Permission | Custom categories with actions |
| C006 | Prevent output vulns | Yes | Guards | Code injection scanning |
| C007 | Flag for human review | No | Permission (Spec 06) | ESCALATE → pause → human approval |
| C008 | Monitor risk categories | No | Observability (Spec 08) | risk_flags on every event |
| C009 | Real-time intervention | No | Runtime (Spec 02) | stream() + cancel() + pause() |
| D001 | Prevent hallucinations | Yes | Skills (Spec 04) + Memory | Grounding via preconditions + retrieval |
| D003 | Restrict unsafe tool calls | Yes | Permission (Spec 06) + Tools | Policy enforcement + schema validation |
| D004 | 3P test tool calls | Yes | Observability (Spec 08) | Full audit trail of all invocations |
| E001 | Failure plan: security | Yes | Control (Spec 07) + Obs | Checkpoint/resume + failure traces |
| E004 | Assign accountability | Yes | Permission (Spec 06) | Approval events with identity |
| E008 | Review processes | Yes | Evidence Exporter | Periodic compliance summaries |
| E009 | Monitor 3P access | Yes | Tools (Spec 05) + Obs | MCP server health + access logs |
| E014 | Transparency reports | No | Evidence Exporter | Automated report generation |
| E015 | Log model activity | Yes | Observability (Spec 08) | Structured events for every operation |

## 6. Default PII and Injection Patterns

```python
def default_pii_patterns() -> list[PIIPattern]:
    return [
        PIIPattern(name="email", regex=r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
        PIIPattern(name="ssn", regex=r"\b\d{3}-\d{2}-\d{4}\b"),
        PIIPattern(name="credit_card", regex=r"\b(?:\d[ -]*?){13,16}\b"),
        PIIPattern(name="phone_us", regex=r"\b(?:\+1)?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        PIIPattern(name="api_key", regex=r"(?:sk|pk|api|key|token|secret)[-_]?[a-zA-Z0-9]{20,}"),
    ]

def default_injection_patterns() -> list[str]:
    return [
        r"(?i)ignore\s+(all\s+)?previous\s+instructions",
        r"(?i)you\s+are\s+now\s+in\s+.*mode",
        r"(?i)system\s*:\s*",
        r"(?i)forget\s+(everything|all|your)\s+(above|previous)",
        r"(?i)<\s*/?\s*system\s*>",
    ]
```

## 7. Test Criteria

- [ ] RiskTaxonomy loads from YAML and is accessible from Permission, Skills, and Observability
- [ ] PIIGuard detects all default patterns in tool arguments, model outputs, and memory writes
- [ ] PIIGuard with action=block prevents the operation from proceeding
- [ ] IPGuard detects secret patterns in model outputs
- [ ] InputFilterGuard detects injection patterns and flags/blocks
- [ ] OutputScopeGuard rejects responses outside allowed topics
- [ ] Guards register at priority 1 (before user hooks)
- [ ] risk_flags appear in observability events when guards trigger
- [ ] EvidenceExporter produces valid evidence packages
- [ ] EvidenceExporter maps events to correct AIUC-1 requirement IDs
- [ ] ComplianceSummary accurately computes coverage percentages
- [ ] Memory reads and writes are rejected when identity lacks permission
- [ ] Skill discovery filters by identity READ permission
- [ ] Tool listing filters by identity READ permission
- [ ] Every guard detection is logged via Observability
- [ ] Rate limiter on ToolRegistry prevents rapid MCP calls
