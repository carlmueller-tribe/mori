# Mori Implementation Plan

**Owner:** Carl Mueller
**Status:** Planning

---

## Philosophy

Every milestone produces a working application. Not a collection of modules waiting for integration. Each version builds on the last, adding capability without breaking what already works.

```
v0.1  "It runs"         → model + native tools = working ReAct agent
v0.2  "It sees"         → + CLI tools + MCP + observability = real tooling with traces
v0.3  "It remembers"    → + memory = context persists across steps
v0.4  "It learns"       → + skills + budget = procedural reuse with context management
v0.5  "It's governed"   → + permissions + checkpoints + hooks = production-grade governance
v0.6  "It's compliant"  → + AIUC-1 guards + evidence = audit-ready
v0.7  "It's integrated" → + Postgres + streaming + adapters + Active Hooks + chat mode = feature-complete (internal)
```

Each version has one integration test that proves the whole thing works end-to-end.

**Documentation is continuous.** Every public API, builder method, hook event, and lifecycle change is documented in the same change that ships it. Specs in `mori-docs/specs/` are kept current as code lands. There is no dedicated "documentation phase" — docs that lag the code are a regression, treated like a failing test. This applies equally to internal-only releases: documentation quality is the same whether or not the artifact ever leaves this repo.

**Mori is internal.** No PyPI release is planned. The roadmap ends at feature-completeness; distribution decisions happen separately, if at all.

---

## Spec Reference Index

| Spec | File | Summary |
|------|------|---------|
| 00 | `00-OVERVIEW.md` | Architecture, package map, dependencies |
| 01 | `01-CORE-TYPES.md` | Types, enums, base models, errors |
| 02 | `02-RUNTIME.md` | Native agent loop, state, phases, model adapters |
| 03 | `03-MEMORY.md` | Four-layer memory, retrieval pipeline, backends |
| 04 | `04-SKILLS.md` | Skill artifacts, registry, discovery, disclosure, binding |
| 05 | `05-TOOLS-AND-PROTOCOLS.md` | ToolRegistry, native/CLI tools, MCP client |
| 06 | `06-PERMISSION.md` | Identity/group/resource rwx permission system |
| 07 | `07-CONTROL.md` | Resource bounds, retry, checkpoint store |
| 08 | `08-OBSERVABILITY.md` | Event taxonomy, sinks, trace context |
| 09 | `09-CONTEXT-BUDGET.md` | Dynamic allocation, rebalancing, compression |
| 10 | `10-PLUGINS-AND-ADAPTERS.md` | Hooks, LangGraph adapter |
| 11 | `11-INTEGRATION.md` | Builder API, startup, config, cross-module flows |
| 12 | `12-AIUC1-COMPLIANCE.md` | Risk taxonomy, guards, evidence exporter |

---

## Phase 0: Scaffold

**Goal:** Repo exists, CI runs, package installs.

**Reference:** `00-OVERVIEW.md` Sections 5-6

- [ ] GitHub repo with `mori/` package structure per `00-OVERVIEW.md` Section 5
- [ ] pyproject.toml: pydantic, httpx, structlog, anyio
- [ ] Optional extras: `mori[anthropic]`, `mori[openai]`, `mori[postgres]`, `mori[langgraph]`
- [ ] Pre-commit (ruff, mypy), CI (GitHub Actions), py.typed marker
- [ ] README with positioning from `00-OVERVIEW.md` Section 1

**Exit test:** `pip install -e . && python -c "from mori import Mori; print('ok')"`

---

## v0.1: "It Runs"

**Goal:** The simplest possible working agent. A model, some Python functions as tools, and a loop that calls them.

```python
from mori import Mori

agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(add, description="Add two numbers")
    .build()
)
result = await agent.run("What is 3 + 5?")
```

### Tasks

**Types (Spec 01, partial).** Only what v0.1 needs: identifiers, enums, messages, model types, tool types, core errors.

**Anthropic Adapter (Spec 02 Sections 10-11).** ModelAdapter protocol. AnthropicAdapter: system message extraction, tool schema conversion, response parsing (text + tool_use blocks), tool_result formatting.

**Tool Registry (Spec 05, native only).** register(), @tool() decorator, schema inference, list_specs(), invoke() with validation.

**Runtime (Spec 02, minimal).** MoriState, AgentLoop with model + tools. Plan/act/observe/evaluate/update phases. run() while loop. RunResult. Hardcoded step limit of 50.

**Builder (Spec 11, minimal).** Mori.builder(), .model(), .tool(), .build(), Mori.run(task).

### v0.1 Exit Test

```python
agent = Mori.builder().model("anthropic", model="claude-sonnet-4-20250514").tool(add).tool(multiply).build()
result = await agent.run("What is (3 + 5) * 12?")
assert result.status == "completed" and "96" in result.final_output
```

---

## v0.2: "It Sees"

**Goal:** CLI programs and MCP servers as tools. Structured observability. Resource bounds.

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(read_file, description="Read a file")
    .cli("rg", command="rg", description="Search with ripgrep", args_format="flags")
    .mcp_server("filesystem", url="http://localhost:3000")
    .sink("stdout")
    .sink("jsonl", path="./traces.jsonl")
    .config(max_steps=20, max_total_tokens=500_000)
    .build()
)
```

### Tasks

**CLI Runner (Spec 05 Section 7).** register_cli(), CLIRunner subprocess execution, argument formatting (flags/positional/subcommand), timeout, output cap, security.

**MCP Client (Spec 05 Section 6).** MCPClient: connect, discover_tools, invoke. SSE + stdio transport. JSON-RPC 2.0. Schema caching with TTL.

**Observability (Spec 08, core).** MoriEvent base. Core events: RunStart/End, StepStart/End, ToolInvoke/Result. ObservabilityEngine. StdoutSink, JsonlSink. Wire into runtime.

**Control Bounds (Spec 07).** ControlBounds: check_bounds, should_retry. Step/token/timeout/idle limits. Retry backoff.

**Error Rate Tracking (Spec 05 Section 10).** ToolMetrics per tool. Wire into invoke(). Include in events.

### v0.2 Exit Test

```python
result = await agent.run("Search for 'TODO' in the current directory and read the first match")
assert result.status == "completed" and result.total_tool_calls >= 2
events = load_jsonl("./traces.jsonl")
assert any(e["event_type"] == "tool.invoke" for e in events)
```

---

## v0.3: "It Remembers"

**Goal:** Memory persists across steps. Retrieval enriches context.

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(search_docs, description="Search docs")
    .memory_backend("sqlite", path="./memory.db")
    .sink("stdout")
    .build()
)
result = await agent.run("Research how auth works, then write a guide", thread_id="research-1")
```

### Tasks

**Types (Spec 01, memory types).** MemoryRecord, MemorySlice, WriteReceipt, ForgetPolicy, MemoryStats.

**Embedder.** Embedder protocol. AnthropicEmbedder or OpenAIEmbedder.

**InMemory Backend.** MemoryBackend protocol. InMemoryBackend: dict + numpy cosine.

**Memory Module (Spec 03).** Full interface: read, write, promote, forget, summarize_layer. Four-layer model. Retrieval pipeline (5 stages). MemoryConfig.

**Wire into Runtime.** Retrieve phase reads memory. Update phase writes traces. Finalize writes episodic summary. Memory events.

**SQLite Backend.** Full MemoryBackend implementation with embedded vector search.

### v0.3 Exit Test

```python
result = await agent.run("Look up X, then look up Y, then summarize both", thread_id="test")
stats = await agent.memory.stats()
assert stats.records_per_layer[MemoryLayer.WORKING] > 0
assert stats.records_per_layer[MemoryLayer.EPISODIC] > 0
```

---

## v0.4: "It Learns"

**Goal:** Agent discovers skills and follows procedures. Budget prevents context overload.

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(read_file, description="Read a file")
    .cli("pytest", command="pytest", description="Run tests", args_format="flags")
    .memory_backend("sqlite", path="./memory.db")
    .skill_registry("./skills/")
    .sink("stdout")
    .build()
)
result = await agent.run("Fix the failing test in tests/test_auth.py")
```

### Tasks

**Types (Spec 01, skill types).** SkillManifest, SkillCandidate, SkillPayload, BoundSkill, etc.

**Skill Artifact Parser.** Parse manifest.yaml, validate per Spec 04 Section 4.

**Filesystem Registry.** SkillRegistry protocol. FilesystemRegistry: scan, parse, search.

**Skills Module (Spec 04).** discover, load, bind, record_outcome, health. Discovery pipeline. Progressive disclosure. Health tracking.

**Budget Manager (Spec 09).** BudgetManager. Rebalancing algorithm. BudgetReport.

**Wire into Runtime.** Retrieve phase: skill discovery + memory, both bounded by budget. Plan phase: generation budget. Skill events.

**Example Skills.** code-review, bug-fix, test-generation artifacts.

### v0.4 Exit Test

```python
result = await agent.run("Fix the failing test in tests/test_auth.py")
skill_events = [e for e in traces if e["event_type"] == "skill.discover"]
assert len(skill_events) > 0 and skill_events[0]["top_match"] is not None
```

---

## v0.5: "It's Governed"

**Goal:** Unix-style permissions. Pause/resume. Custom hooks.

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(read_file, description="Read a file")
    .cli("deploy", command="./deploy.sh", description="Deploy")
    .identity(Identity(id="agent:bot", type=IdentityType.AGENT, groups=["engineering"]))
    .policy_file("./policy.yaml")
    .checkpointer("sqlite", path="./checkpoints.db")
    .hook("tool.invoke.before", redact_secrets, priority=10)
    .build()
)
result = await agent.run("Deploy v1.2.3 to production")
# Paused: deploy requires escalation
result = await agent.resume(thread_id=result.thread_id, input={"approved": True})
```

### Tasks

**Permission Engine (Spec 06).** Identity/group model. Resource/Permission types. PermissionRule with glob patterns. Resolution algorithm (deny-wins). Conditions. Wire into all modules.

**Checkpoint Store (Spec 07).** CheckpointStore protocol. InMemory + SQLite. MoriState JSON serialization. Wire into runtime. resume(), get_state(), get_history().

**Hooks (Spec 10 Part A).** HookRegistry. Priority dispatch. Before (chained modification) / after (observe). Timeout. Fail-open.

**Integration Wiring.** Permission checks everywhere. Checkpoint on escalation. Hooks fire at all lifecycle events.

### v0.5 Exit Test

```python
result = await agent.run("Deploy version 1.2.3")
perm_events = [e for e in traces if e["event_type"] == "permission.check"]
assert any(e["decision"] in ("deny", "escalate") for e in perm_events)
```

---

## v0.6: "It's Compliant"

**Goal:** AIUC-1 guards active. PII redacted. Evidence exportable.

```python
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(search_customers, description="Search customers")
    .risk_taxonomy("./risk_taxonomy.yaml")
    .guard(PIIGuard(action="redact"))
    .guard(InputFilterGuard())
    .build()
)
result = await agent.run("Look up customer SSN 123-45-6789")
# SSN redacted before tool call

evidence = await EvidenceExporter(agent.risk_taxonomy).export_run(result.run_id, events)
```

### Tasks

**Risk Taxonomy (Spec 12 Section 3.1).** Models, YAML loader, wire into Permission + Observability.

**Guards (Spec 12 Section 3.2).** PIIGuard, IPGuard, InputFilterGuard, OutputScopeGuard. Default patterns. .guard() builder method (priority 1 hooks). RiskFlag on events.

**Evidence Exporter (Spec 12 Section 3.3).** EvidenceExporter. EvidencePackage. ComplianceSummary. AIUC-1 requirement mapping.

**Integration.** Guards fire on every call. Risk flags flow. Evidence exports from real traces.

### v0.6 Exit Test

```python
result = await agent.run("Process email test@example.com, SSN 123-45-6789")
tool_events = [e for e in traces if e["event_type"] == "tool.invoke"]
for te in tool_events:
    assert "123-45-6789" not in str(te.get("arguments", ""))
flagged = [e for e in traces if e.get("risk_flags")]
assert len(flagged) > 0
```

---

## v0.7: "It's Integrated"

**Goal:** Production backends, streaming, framework adapters, observability sinks, Active Hooks (block/retry/turn events), and chat mode via `ask_user`. Feature-complete for internal use. No public release.

### Tasks

**OpenAI Adapter (Spec 02 Section 12).** OpenAI ModelAdapter implementation: tool calls, tool results, streaming.

**Postgres Backends (Spec 03, 07).** Production MemoryBackend and CheckpointStore on Postgres + pgvector.

**Streaming (Spec 02 Section 8).** `agent.stream()` yields typed events at every phase boundary and tool call.

**YAML Config (Spec 11 Section 5).** `Mori.from_config("./mori.yaml")` builder entry point.

**OTLP Sink (Spec 08 Section 6).** Observability sink emitting OpenTelemetry-compatible traces.

**LangGraph Adapter (Spec 10 Part B).** RuntimeAdapter implementation; `langgraph_as_tool` / `langgraph_as_skill` wrappers.

**Active Hooks (Spec 10 Part A).** `HookBlock` / `HookRetry` exceptions. `turn.start` / `turn.end` events. Capability matrix per event (observe / transform / block / retry). Runtime translation table in `_phase_plan` / `_phase_act` / `_phase_evaluate`. `HookPolicyEvent` on observability stream.

**Chat Mode via `ask_user` (Spec 05 Section 5).** Native `ask_user(question)` tool. `YieldToUser` internal signal caught in `_phase_act`. Pause path: `RunStatus.PAUSED` + `paused_prompt` + checkpoint save. `resume(thread_id, input)` injects user response as tool result for paused call. auto-registration via _NATIVE_TOOLS; disable_native_tool("ask_user") for opt-out; build-time check that checkpointer is configured.

### v0.7 Exit Test

```python
agent = Mori.from_config("./mori.yaml")

# Streaming end-to-end
async for event in agent.stream("Analyze Q3 sales data"):
    print(f"{event.type}: {event.data}")

# Active Hooks: a HookBlock prevents a forbidden tool call
@agent.hooks.hook("tool.invoke.before")
async def block_prod(call):
    if call.tool_name == "apply_migration" and call.args.get("env") == "prod":
        raise HookBlock("production migrations must go through CI")

# Chat mode: agent yields, caller resumes
result = await agent.run("Plan the user-table migration")
if result.status == RunStatus.PAUSED:
    answer = input(result.paused_prompt + " ")
    result = await agent.resume(result.thread_id, answer)
assert result.status == RunStatus.COMPLETED
```

---

## Milestone Demos

What each milestone visibly demonstrates when complete:

| Version | What You Demo |
|---------|---------------|
| Phase 0 | "Repo is live" |
| v0.1 | "Watch it call tools and solve a problem" |
| v0.2 | "It runs shell commands and MCP tools. Here are the traces." |
| v0.3 | "It remembers what it learned across steps" |
| v0.4 | "It found a skill file and followed the procedure" |
| v0.5 | "It can't touch deploy. It paused for approval. I resumed it." |
| v0.6 | "It redacted the SSN. Here's the AIUC-1 evidence package." |
| v0.7 | "Feature-complete agent runtime: streaming, Postgres, LangGraph, chat mode, Active Hooks." |

## Parallelization

Each version is sequential, but within a version:

| Version | Parallelizable Pairs |
|---------|---------------------|
| v0.2 | CLI Runner ‖ MCP Client |
| v0.3 | Embedder + Backend ‖ Memory Module |
| v0.4 | Skills Module ‖ Budget Manager |
| v0.5 | Permission ‖ Checkpoints ‖ Hooks |
| v0.6 | Guards ‖ Evidence Exporter |
| v0.7 | Postgres ‖ Streaming ‖ OpenAI ‖ LangGraph ‖ Active Hooks ‖ Chat Mode |
