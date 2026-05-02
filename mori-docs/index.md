# Mori

**The cognitive environment for LLM agents.**

!!! warning "Under Active Development"
    Mori is under heavy active development. APIs may change without notice between versions.
    The modules marked **proposed** below are not yet released — they describe what is being
    built, not what you can install today. See the [V1 Roadmap](history/v1-roadmap.md) for
    the full plan.

Mori (森, "forest") is a Python library for building governed LLM agent systems. It provides
a lightweight native runtime, four-layer memory, reusable skill artifacts, a managed protocol
registry, context budget management, and vendor-neutral observability — everything an agent
needs beyond the model itself.

Mori owns its runtime. It does not depend on LangGraph, LangChain, or any specific
orchestration framework. Those are supported as optional plugins. Mori's design principle:
frameworks are guests, not landlords.

## Design Philosophy

| Principle | Statement |
|-----------|-----------|
| **P1 — Own the runtime** | Mori's agent loop is a lightweight async state machine with no external orchestration dependency. Simple, debuggable, fast. |
| **P2 — Treat frameworks as plugins** | LangGraph, CrewAI, and other frameworks can run inside Mori, but Mori never depends on them. |
| **P3 — Representational transformation** | Every module changes the form of the task the model faces. Memory converts recall into recognition. Skills convert improvisation into guided composition. |
| **P4 — Minimal sufficiency** | Load only what reduces the model's cognitive burden for the current step. |
| **P5 — Governance by default** | Permissions, audit logging, and approval gates are structural components, not add-ons. |
| **P6 — Vendor-neutral** | Works with any LLM provider, any observability stack, any storage backend. |

## Architecture

```mermaid
graph TD
    User["Your Code"] -->|"Mori.builder()"| Builder["MoriBuilder"]
    Builder -->|".build()"| Agent["Mori"]
    Agent -->|".run(task)"| Loop["AgentLoop"]

    Loop --> Memory["Memory Module\n4-layer"]
    Loop --> Skills["Skills Module\nartifacts"]
    Loop --> Budget["Budget Manager\ntoken slots"]
    Loop --> Tools["Tool Registry\nnative · CLI · MCP"]
    Loop --> Control["Control Bounds\nsteps · tokens · time"]
    Loop --> Obs["Observability Engine\nevents · sinks"]
    Loop --> Model["Model Adapter\nAnthropic · OpenAI"]

    Loop -.->|"proposed v0.5"| Permission["Permission Engine\npolicy · ESCALATE"]
    Loop -.->|"proposed v0.5"| Checkpoint["Checkpoints\nPAUSE · RESUME"]
    Loop -.->|"proposed v0.5"| Hooks["Lifecycle Hooks\n6 points"]

    Tools --> CLI["CLI Runner\nsubprocess"]
    Tools --> MCP["MCP Client\nJSON-RPC 2.0"]
    Memory --> Backends["Backends\nInMemory · SQLite"]
    Memory --> Embedder["Embedder\nVoyage AI"]
    Obs --> Sinks["Sinks\nStdout · JSONL"]

    style Permission stroke-dasharray: 5 5
    style Checkpoint stroke-dasharray: 5 5
    style Hooks stroke-dasharray: 5 5
```

## Modules

### Implemented

| Module | Added | What it does | Page |
|--------|-------|-------------|------|
| [Runtime](architecture/runtime.md) | v0.1 | Async agent loop — plan → act → evaluate with memory + skill context | [→](architecture/runtime.md) |
| [Model Adapters](architecture/model-adapters.md) | v0.1 | Provider-neutral LLM interface; Anthropic Claude adapter included | [→](architecture/model-adapters.md) |
| [Tools & Protocols](architecture/tools-and-protocols.md) | v0.1–v0.2 | Native Python callables, CLI subprocess tools, MCP server tools | [→](architecture/tools-and-protocols.md) |
| [Observability](architecture/observability.md) | v0.2 | Structured event emission to pluggable sinks (stdout, JSONL) | [→](architecture/observability.md) |
| [Control](architecture/control.md) | v0.2 | Resource bounds (max steps, tokens, timeouts) and retry logic | [→](architecture/control.md) |
| [Memory](architecture/memory.md) | v0.3 | Four-layer persistent memory (working / episodic / semantic / personalized) with vector retrieval | [→](architecture/memory.md) |
| [Skills](architecture/skills.md) | v0.4 | Filesystem-loaded task guides with progressive disclosure (abstract → summary → full) | [→](architecture/skills.md) |
| [Budget Manager](architecture/budget.md) | v0.4 | Per-slot context token tracking and 6-stage compaction pipeline | [→](architecture/budget.md) |

### Proposed

!!! note "Not yet released"
    These modules are under active design and development. The architecture pages describe
    the intended design; implementation is in progress.

| Module | Target | What it will do |
|--------|--------|----------------|
| Permission Engine | v0.5 | YAML policy files, `ALLOW` / `DENY` / `ESCALATE` decisions per identity + resource |
| Checkpoints | v0.5 | Persist and restore full agent state — enables PAUSE → human review → RESUME |
| Lifecycle Hooks | v0.5 | Fire custom handlers at 6 points: run start/end, tool before/after, model before/after |
| AIUC-1 Compliance Guards | V1 | PII guard, IP guard, input/output scope validation, evidence exporter |
| Plugin System | V1 | Framework adapters (LangGraph, CrewAI), third-party extension API |
| Integration Patterns | V1 | Multi-agent patterns, startup sequences, long-running agent recipes |
| Pi Patterns | V1 | Tree sessions, steering, AGENTS.md loader, cross-agent skill negotiation |

## Quickstart

```python
import asyncio
from mori import Mori

async def main():
    agent = (
        Mori.builder()
        .model("anthropic", model="claude-sonnet-4-20250514")
        .tool(lambda city: f"{city}: 72°F", description="Get weather", name="get_weather")
        .memory_backend("inmemory")
        .skill_registry("./skills")
        .sink("stdout")
        .budget(total_context_tokens=200_000)
        .build()
    )
    result = await agent.run("What's the weather in Paris?")
    print(result.final_output)
    await agent.close()

asyncio.run(main())
```

## Version History

| Version | Codename | What it added |
|---------|----------|---------------|
| [v0.1](history/v01-it-runs.md) | It Runs | Foundation — types, loop, tool registry, Anthropic adapter |
| [v0.2](history/v02-it-sees.md) | It Sees | Observability, control bounds, CLI tools, MCP protocol |
| [v0.3](history/v03-it-remembers.md) | It Remembers | Four-layer memory, retrieval pipeline, SQLite backend |
| [v0.4](history/v04-it-learns.md) | It Learns | Skills module, budget manager, 6-stage compaction |
| [v0.5](history/v05-its-governed.md) | It's Governed | Permission engine, checkpoints, lifecycle hooks *(in progress)* |
| [V1 Roadmap](history/v1-roadmap.md) | — | Full spec coverage: compliance, plugins, integration patterns |
