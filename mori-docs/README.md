# Mori (森) Documentation Package

**The cognitive environment for LLM agents.**

---

## Folder Structure

```
mori-docs/
├── README.md                       # This file
├── mori-icon.png                   # Torii gate icon
├── specs/                          # Design specifications (13 files)
│   ├── 00-OVERVIEW.md              # Architecture, package map, positioning
│   ├── 01-CORE-TYPES.md            # Types, enums, base models, errors
│   ├── 02-RUNTIME.md               # Native agent loop, state, phases, streaming
│   ├── 03-MEMORY.md                # Four-layer memory, retrieval pipeline, backends
│   ├── 04-SKILLS.md                # Skill artifacts, registry, discovery, disclosure
│   ├── 05-TOOLS-AND-PROTOCOLS.md   # ToolRegistry, native tools, MCP client
│   ├── 06-PERMISSION.md            # Unix-style rwx permission system
│   ├── 07-CONTROL.md               # Resource bounds, retry, checkpoint store
│   ├── 08-OBSERVABILITY.md         # Structured events, pluggable sinks
│   ├── 09-CONTEXT-BUDGET.md        # Dynamic allocation, rebalancing, compression
│   ├── 10-PLUGINS-AND-ADAPTERS.md  # Hooks, LangGraph adapter
│   ├── 11-INTEGRATION.md           # Builder API, startup, config, cross-module flows
│   └── 12-AIUC1-COMPLIANCE.md      # Risk taxonomy, guards, evidence exporter
└── implementation/
    └── IMPLEMENTATION-PLAN.md      # Phased build plan with spec references
```

Every spec is self-contained. No cross-file references for core content.

## How to Read

1. Start with `specs/00-OVERVIEW.md` for the big picture.
2. Read `implementation/IMPLEMENTATION-PLAN.md` for the build sequence.
3. For each implementation task, the plan references the exact spec and section.

## Key Numbers

- 13 specification documents, each self-contained
- 1 phased implementation plan with 229 spec references
- 4 phases, 17 weeks to v0.1.0 on PyPI
- Core dependencies: pydantic, httpx, structlog, anyio (zero framework deps)
