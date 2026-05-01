# 00: Mori Library Overview

**Status:** Draft v3 (Independent Runtime)
**Owner:** Carl Mueller
**Last Updated:** 2026-04-15

---

## 1. What Mori Is

Mori (森, "forest") is a Python library for building governed LLM agent systems. It provides a lightweight native runtime, layered memory, reusable skill artifacts, a managed protocol registry, declarative permissions, context budget management, and vendor-neutral observability. Everything an agent needs beyond the model itself.

Mori owns its runtime. It does not depend on LangGraph, LangChain, or any specific orchestration framework. LangGraph is supported as an optional plugin for teams that want to use LangGraph's graph primitives inside Mori or import existing LangGraph workflows as Mori skills.

## 2. Positioning

**LangGraph:** graph-based workflow orchestration with typed state channels, conditional edges, checkpointing, and LangSmith observability.

**Mori:** a complete agent runtime with its own execution loop plus the externalization layers that no framework provides: four-layer memory with retrieval pipelines, skill artifacts with progressive disclosure, a managed protocol registry, declarative permissions, dynamic context budget management, and vendor-neutral observability with pluggable sinks.

LangGraph is a workflow engine. Mori is a cognitive environment.

## 3. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                         Mori                            │
│                                                         │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐        │
│  │  Memory    │  │  Skills    │  │ Protocols  │        │
│  │  (4-layer) │  │  (novel)   │  │ (managed)  │        │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘        │
│        │               │               │                │
│  ┌─────┴───────────────┴───────────────┴──────┐         │
│  │          Context Budget Manager             │         │
│  └──────────────────┬─────────────────────────┘         │
│                     │                                   │
│  ┌──────────────────┴─────────────────────────┐         │
│  │           Agent Runtime (native)            │         │
│  │   Perceive → Plan → Validate → Act →       │         │
│  │   Observe → Evaluate → Update              │         │
│  └──────────────────┬─────────────────────────┘         │
│                     │                                   │
│  ┌────────┐  ┌──────┴─────┐  ┌──────────────┐          │
│  │Permis- │  │  Control   │  │ Observability│          │
│  │ sion   │  │  (bounds)  │  │ (open sinks) │          │
│  └────────┘  └────────────┘  └──────────────┘          │
│                                                         │
│  ┌──────────────────────────────────────────────┐       │
│  │         Plugins / Hooks / Adapters            │       │
│  │  ┌──────────┐  ┌──────────┐  ┌─────────┐    │       │
│  │  │LangGraph │  │ CrewAI   │  │ Custom  │    │       │
│  │  │ Adapter  │  │ Adapter  │  │Adapters │    │       │
│  │  └──────────┘  └──────────┘  └─────────┘    │       │
│  └──────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

## 4. Design Philosophy

**P1: Own the runtime.** Mori's agent loop is a lightweight async state machine with no external orchestration dependency. Simple, debuggable, fast.

**P2: Treat frameworks as plugins.** LangGraph, CrewAI, and other frameworks can be used inside Mori (as skill implementations, as alternative runtimes, as tool sources) but Mori never depends on them.

**P3: Representational transformation.** Every module changes the form of the task the model faces. Memory converts recall into recognition. Skills convert improvisation into guided composition. Protocols convert ad hoc coordination into structured exchange.

**P4: Minimal sufficiency.** Load only what reduces the model's cognitive burden for the current step.

**P5: Governance by default.** Permissions, audit logging, and approval gates are structural components.

**P6: Vendor-neutral.** Works with any LLM provider, any observability stack, any storage backend.

## 5. Package Map

```
mori/
├── __init__.py
├── agent.py                  # Mori builder + top-level API
├── types.py                  # Spec 01: shared types
├── runtime/                  # Spec 02: native agent runtime
│   ├── __init__.py
│   ├── loop.py               # Core agent loop (async state machine)
│   ├── state.py              # MoriState
│   ├── phases.py             # Phase implementations
│   ├── router.py             # Routing logic between phases
│   ├── checkpoint.py         # Checkpoint save/restore
│   └── planner.py            # Plan object management
├── memory/                   # Spec 03: memory module
│   ├── __init__.py
│   ├── module.py
│   ├── layers.py
│   ├── retrieval.py
│   ├── backends/
│   │   ├── base.py
│   │   ├── inmemory.py
│   │   └── sqlite.py
│   └── compression.py
├── skills/                   # Spec 04: skills module
│   ├── __init__.py
│   ├── module.py
│   ├── artifact.py
│   ├── registry.py
│   ├── disclosure.py
│   ├── binding.py
│   └── lifecycle.py
├── protocols/                # Spec 05: protocol module
│   ├── __init__.py
│   ├── module.py
│   ├── mcp/
│   │   ├── client.py         # Native MCP client (JSON-RPC 2.0)
│   │   ├── registry.py
│   │   └── schema_cache.py
│   ├── cli/
│   │   ├── runner.py          # CLI subprocess execution
│   │   └── args.py            # Argument formatting (flags, positional, subcommand)
│   └── a2a/
│       ├── registry.py
│       └── client.py
├── permission/               # Spec 06
│   ├── __init__.py
│   ├── engine.py
│   ├── policy.py
│   └── scopes.py
├── control/                  # Spec 07
│   ├── __init__.py
│   ├── bounds.py
│   └── retry.py
├── observability/            # Spec 08
│   ├── __init__.py
│   ├── engine.py
│   ├── events.py
│   ├── trace.py
│   └── sinks/
│       ├── stdout.py
│       ├── jsonl.py
│       └── otlp.py
├── budget/                   # Spec 09
│   ├── __init__.py
│   ├── manager.py
│   └── allocator.py
├── plugins/                  # Spec 10
│   ├── __init__.py
│   └── hooks.py
├── adapters/                 # Spec 10b: framework adapters
│   ├── __init__.py
│   ├── base.py               # RuntimeAdapter protocol
│   └── langgraph.py          # Optional LangGraph adapter
├── model/                    # Model adapters (Spec 02 Sections 10-12)
│   ├── __init__.py
│   ├── base.py               # ModelAdapter protocol, StreamChunk
│   ├── anthropic.py          # Anthropic Claude adapter (primary)
│   └── openai.py             # OpenAI / OpenAI-compatible adapter
└── config/
    ├── __init__.py
    └── loader.py
├── compliance/                # Spec 12: AIUC-1 primitives
│   ├── __init__.py
│   ├── taxonomy.py            # RiskTaxonomy config object
│   ├── guards.py              # PIIGuard, IPGuard, InputFilterGuard, OutputScopeGuard
│   └── evidence.py            # EvidenceExporter, ComplianceSummary
├── templates/                 # Spec 13: prompt templates
│   ├── __init__.py
│   └── registry.py            # PromptTemplateRegistry
├── instructions/              # Spec 13: AGENTS.md loader
│   ├── __init__.py
│   └── loader.py              # InstructionLoader
```

## 6. Dependencies

**Core (zero framework deps):**
- `pydantic` (type validation)
- `httpx` (HTTP client for MCP, A2A)
- `structlog` (structured logging)
- `anyio` (async runtime)

**Optional:**
- `langgraph` (LangGraph adapter plugin)
- `anthropic` (Anthropic model adapter)
- `openai` (OpenAI model adapter)
- `opentelemetry-*` (OTLP sink)
- `numpy` (vector similarity in memory backends)
- `asyncpg` + `pgvector` (Postgres memory backend)

## 7. Spec Index

| Spec | Title                  | Description                                        |
|------|------------------------|----------------------------------------------------|
| 00   | Overview               | This document                                      |
| 01   | Core Types             | Shared types, enums, base models, errors           |
| 02   | Runtime                | Native agent loop, state, checkpointing, streaming |
| 03   | Memory Module          | Four-layer memory, retrieval, backends, lifecycle  |
| 04   | Skills Module          | Artifacts, registry, discovery, disclosure, binding|
| 05   | Tools and Protocols    | ToolRegistry, native tools, CLI tools, MCP client, A2A |
| 06   | Permission Engine      | Declarative policy, scope hierarchy, enforcement   |
| 07   | Control Engine         | Resource bounds, retry logic                       |
| 08   | Observability Engine   | Structured events, pluggable sinks                 |
| 09   | Context Budget Manager | Dynamic allocation, rebalancing, compression       |
| 10   | Plugins and Hooks      | Hook system + framework adapters                   |
| 11   | Integration Patterns   | Cross-module flows, builder API, startup           |
| 12   | AIUC-1 Compliance      | Risk taxonomy, data guards, evidence exporter      |
| 13   | Pi Patterns            | Tree sessions, compaction, AGENTS.md, steering, skills compat |

## 8. Implementation Sequence

**Phase 1 (Runtime + Protocols):** Specs 01, 02, 05, 07, 08
A working agent loop that calls MCP tools, enforces resource bounds, and emits structured traces. Runnable with zero framework dependencies.

**Phase 2 (Differentiators):** Specs 03, 04, 09
Four-layer memory, skill discovery with progressive disclosure, and context budget management.

**Phase 3 (Governance + Extensions):** Specs 06, 10, 11
Permission engine, hook system, framework adapters, AIUC-1 compliance primitives, and full integration docs.
