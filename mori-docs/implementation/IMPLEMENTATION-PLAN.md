# Mori Implementation Plan

**Owner:** Carl Mueller
**Start Date:** April 27, 2026
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
v0.7  "It ships"        → + Postgres + streaming + docs + PyPI = public release
```

Each version has one integration test that proves the whole thing works end-to-end.

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

## Phase 0: Scaffold (Days 1-2)

**Goal:** Repo exists, CI runs, package installs.

**Reference:** `00-OVERVIEW.md` Sections 5-6

- [ ] GitHub repo with `mori/` package structure per `00-OVERVIEW.md` Section 5
- [ ] pyproject.toml: pydantic, httpx, structlog, anyio
- [ ] Optional extras: `mori[anthropic]`, `mori[openai]`, `mori[postgres]`, `mori[langgraph]`
- [ ] Pre-commit (ruff, mypy), CI (GitHub Actions), py.typed marker
- [ ] README with positioning from `00-OVERVIEW.md` Section 1

**Exit test:** `pip install -e . && python -c "from mori import Mori; print('ok')"`

---

## v0.1: "It Runs" (Days 3-12)

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

**Types (Spec 01, partial) — 1 day.** Only what v0.1 needs: identifiers, enums, messages, model types, tool types, core errors.

**Anthropic Adapter (Spec 02 Sections 10-11) — 2 days.** ModelAdapter protocol. AnthropicAdapter: system message extraction, tool schema conversion, response parsing (text + tool_use blocks), tool_result formatting.

**Tool Registry (Spec 05, native only) — 1 day.** register(), @tool() decorator, schema inference, list_specs(), invoke() with validation.

**Runtime (Spec 02, minimal) — 3 days.** MoriState, AgentLoop with model + tools. Plan/act/observe/evaluate/update phases. run() while loop. RunResult. Hardcoded step limit of 50.

**Builder (Spec 11, minimal) — 1 day.** Mori.builder(), .model(), .tool(), .build(), Mori.run(task).

### v0.1 Exit Test

```python
agent = Mori.builder().model("anthropic", model="claude-sonnet-4-20250514").tool(add).tool(multiply).build()
result = await agent.run("What is (3 + 5) * 12?")
assert result.status == "completed" and "96" in result.final_output
```

**Effort:** 8 days

---

## v0.2: "It Sees" (Days 13-22)

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

**CLI Runner (Spec 05 Section 6) — 2 days.** register_cli(), CLIRunner subprocess execution, argument formatting (flags/positional/subcommand), timeout, output cap, security.

**MCP Client (Spec 05 Section 5) — 3 days.** MCPClient: connect, discover_tools, invoke. SSE + stdio transport. JSON-RPC 2.0. Schema caching with TTL.

**Observability (Spec 08, core) — 2 days.** MoriEvent base. Core events: RunStart/End, StepStart/End, ToolInvoke/Result. ObservabilityEngine. StdoutSink, JsonlSink. Wire into runtime.

**Control Bounds (Spec 07) — 1 day.** ControlBounds: check_bounds, should_retry. Step/token/timeout/idle limits. Retry backoff.

**Error Rate Tracking (Spec 05 Section 9) — 1 day.** ToolMetrics per tool. Wire into invoke(). Include in events.

### v0.2 Exit Test

```python
result = await agent.run("Search for 'TODO' in the current directory and read the first match")
assert result.status == "completed" and result.total_tool_calls >= 2
events = load_jsonl("./traces.jsonl")
assert any(e["event_type"] == "tool.invoke" for e in events)
```

**Effort:** 9 days

---

## v0.3: "It Remembers" (Days 23-32)

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

**Types (Spec 01, memory types) — 0.5 days.** MemoryRecord, MemorySlice, WriteReceipt, ForgetPolicy, MemoryStats.

**Embedder — 1 day.** Embedder protocol. AnthropicEmbedder or OpenAIEmbedder.

**InMemory Backend — 1.5 days.** MemoryBackend protocol. InMemoryBackend: dict + numpy cosine.

**Memory Module (Spec 03) — 3 days.** Full interface: read, write, promote, forget, summarize_layer. Four-layer model. Retrieval pipeline (5 stages). MemoryConfig.

**Wire into Runtime — 2 days.** Retrieve phase reads memory. Update phase writes traces. Finalize writes episodic summary. Memory events.

**SQLite Backend — 2 days.** Full MemoryBackend implementation with embedded vector search.

### v0.3 Exit Test

```python
result = await agent.run("Look up X, then look up Y, then summarize both", thread_id="test")
stats = await agent.memory.stats()
assert stats.records_per_layer[MemoryLayer.WORKING] > 0
assert stats.records_per_layer[MemoryLayer.EPISODIC] > 0
```

**Effort:** 10 days

---

## v0.4: "It Learns" (Days 33-47)

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

**Types (Spec 01, skill types) — 0.5 days.** SkillManifest, SkillCandidate, SkillPayload, BoundSkill, etc.

**Skill Artifact Parser — 1.5 days.** Parse manifest.yaml, validate per Spec 04 Section 4.

**Filesystem Registry — 1 day.** SkillRegistry protocol. FilesystemRegistry: scan, parse, search.

**Skills Module (Spec 04) — 3 days.** discover, load, bind, record_outcome, health. Discovery pipeline. Progressive disclosure. Health tracking.

**Budget Manager (Spec 09) — 2 days.** BudgetManager. Rebalancing algorithm. BudgetReport.

**Wire into Runtime — 2 days.** Retrieve phase: skill discovery + memory, both bounded by budget. Plan phase: generation budget. Skill events.

**Example Skills — 1 day.** code-review, bug-fix, test-generation artifacts.

### v0.4 Exit Test

```python
result = await agent.run("Fix the failing test in tests/test_auth.py")
skill_events = [e for e in traces if e["event_type"] == "skill.discover"]
assert len(skill_events) > 0 and skill_events[0]["top_match"] is not None
```

**Effort:** 11 days

---

## v0.5: "It's Governed" (Days 48-62)

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

**Permission Engine (Spec 06) — 5 days.** Identity/group model. Resource/Permission types. PermissionRule with glob patterns. Resolution algorithm (deny-wins). Conditions. Wire into all modules.

**Checkpoint Store (Spec 07) — 2 days.** CheckpointStore protocol. InMemory + SQLite. MoriState JSON serialization. Wire into runtime. resume(), get_state(), get_history().

**Hooks (Spec 10 Part A) — 2 days.** HookRegistry. Priority dispatch. Before (chained modification) / after (observe). Timeout. Fail-open.

**Integration Wiring — 2 days.** Permission checks everywhere. Checkpoint on escalation. Hooks fire at all lifecycle events.

### v0.5 Exit Test

```python
result = await agent.run("Deploy version 1.2.3")
perm_events = [e for e in traces if e["event_type"] == "permission.check"]
assert any(e["decision"] in ("deny", "escalate") for e in perm_events)
```

**Effort:** 11 days

---

## v0.6: "It's Compliant" (Days 63-72)

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

**Risk Taxonomy (Spec 12 Section 3.1) — 1 day.** Models, YAML loader, wire into Permission + Observability.

**Guards (Spec 12 Section 3.2) — 3 days.** PIIGuard, IPGuard, InputFilterGuard, OutputScopeGuard. Default patterns. .guard() builder method (priority 1 hooks). RiskFlag on events.

**Evidence Exporter (Spec 12 Section 3.3) — 2 days.** EvidenceExporter. EvidencePackage. ComplianceSummary. AIUC-1 requirement mapping.

**Integration — 1 day.** Guards fire on every call. Risk flags flow. Evidence exports from real traces.

### v0.6 Exit Test

```python
result = await agent.run("Process email test@example.com, SSN 123-45-6789")
tool_events = [e for e in traces if e["event_type"] == "tool.invoke"]
for te in tool_events:
    assert "123-45-6789" not in str(te.get("arguments", ""))
flagged = [e for e in traces if e.get("risk_flags")]
assert len(flagged) > 0
```

**Effort:** 7 days

---

## v0.7: "It Ships" (Days 73-90)

**Goal:** Production backends, streaming, OpenAI support, LangGraph adapter, docs, PyPI.

### Tasks

**OpenAI Adapter (Spec 02 Section 12) — 1 day**
**Postgres Backends (Spec 03, 07) — 3 days**
**Streaming (Spec 02 Section 8) — 2 days**
**YAML Config (Spec 11 Section 5) — 1 day**
**OTLP Sink (Spec 08 Section 6) — 1 day**
**LangGraph Adapter (Spec 10 Part B) — 3 days**
**Documentation — 3 days**
**PyPI Release — 1 day**

### v0.7 Exit Test

```python
agent = Mori.from_config("./mori.yaml")
async for event in agent.stream("Analyze Q3 sales data"):
    print(f"{event.type}: {event.data}")
```

**Effort:** 15 days

---

## Timeline

| Version | Days | Calendar | What You Demo |
|---------|------|----------|---------------|
| Phase 0 | 1-2 | Apr 27-28 | "Repo is live" |
| v0.1 | 3-12 | Apr 29 - May 12 | "Watch it call tools and solve a problem" |
| v0.2 | 13-22 | May 13 - May 26 | "It runs shell commands and MCP tools. Here are the traces." |
| v0.3 | 23-32 | May 27 - Jun 9 | "It remembers what it learned across steps" |
| v0.4 | 33-47 | Jun 10 - Jun 27 | "It found a skill file and followed the procedure" |
| v0.5 | 48-62 | Jun 30 - Jul 18 | "It can't touch deploy. It paused for approval. I resumed it." |
| v0.6 | 63-72 | Jul 21 - Aug 1 | "It redacted the SSN. Here's the AIUC-1 evidence package." |
| v0.7 | 73-90 | Aug 4 - Aug 28 | "`pip install mori`. Try it." |

**Total:** 90 working days (~18 weeks) to v0.1.0 on PyPI.

## Parallelization

Each version is sequential, but within a version:

| Version | Parallelizable Pairs |
|---------|---------------------|
| v0.2 | CLI Runner ‖ MCP Client |
| v0.3 | Embedder + Backend ‖ Memory Module |
| v0.4 | Skills Module ‖ Budget Manager |
| v0.5 | Permission ‖ Checkpoints ‖ Hooks |
| v0.6 | Guards ‖ Evidence Exporter |
| v0.7 | Postgres ‖ Streaming ‖ OpenAI ‖ LangGraph ‖ Docs |

With 2 engineers: ~60 days. With 3: ~45 days.
