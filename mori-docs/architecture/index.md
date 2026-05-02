# Architecture Overview

A map of all Mori modules, their dependencies, and the data flow through a complete agent run.

## Module Dependency Graph

```mermaid
graph LR
    Agent["Mori (agent.py)"] --> Loop["AgentLoop"]
    Agent --> Registry["ToolRegistry"]
    Agent --> Obs["ObservabilityEngine"]
    Agent --> MemMod["MemoryModule"]
    Agent --> SkillsMod["SkillsModule"]
    Agent --> BudgetMgr["BudgetManager"]

    Loop --> ModelAdapter["ModelAdapter"]
    Loop --> Registry
    Loop --> Control["ControlBounds"]
    Loop --> Obs
    Loop --> MemMod
    Loop --> SkillsMod
    Loop --> BudgetMgr

    Registry --> CLIRunner["CLIRunner"]
    Registry --> MCPClient["MCPClient"]

    MemMod --> Backend["MemoryBackend"]
    MemMod --> Embedder["Embedder"]

    SkillsMod --> SkillReg["FilesystemRegistry"]
    Obs --> Sinks["EventSink(s)"]
    BudgetMgr --> CompactModules["MemoryModule\nSkillsModule\nModelAdapter\n(during compaction)"]
```

## Full Data Flow

A complete `Mori.run(task)` call traverses these phases in sequence for each loop step:

```mermaid
flowchart TD
    A["Mori.run(task)"] --> B["AgentLoop.run()"]
    B --> C["_init_state()\nRunId · ThreadId · messages=[user msg]"]
    C --> D["while RUNNING:\ncheck_bounds()"]
    D -->|bounds violated| FAIL["RunStatus.FAILED\n+ BoundViolationEvent"]
    D -->|ok| E["_phase_retrieve()\nread memory → discover + load skill"]
    E --> F["_pre_plan_compact()\nrebalance budget → run compaction if needed"]
    F --> G["_phase_plan()\nassemble_request() → model.invoke()"]
    G --> H["_phase_act()\nexecute tool calls via ToolRegistry"]
    H --> I["_phase_evaluate()\nSUCCESS if last msg is assistant with no tool_calls\nRETRY otherwise"]
    I -->|RETRY| D
    I -->|SUCCESS| J["_phase_update()\nwrite working memory record"]
    J --> K["RunStatus.COMPLETED"]
    K --> L["write episodic memory summary"]
    L --> M["RunResult.from_state()"]
```

## Context Assembly

Before each model call, `_assemble_request()` builds the message list in this order
(index 0 = injected first, appears earliest in context):

```
index 0: [Skill Context]   ← active skill payload (inserted last, ends up first)
index 1: [Memory Context]  ← retrieved memory records (inserted first)
index 2: user message      ← the original task
index 3+: prior turns      ← assistant + tool messages from previous steps
```

## Builder Wiring

`MoriBuilder.build()` assembles all modules and wires them into a single `AgentLoop`:

```python
# Simplified build() — shows the wiring order
obs     = ObservabilityEngine(sinks)                    # 1. Observability
control = ControlBounds(ControlConfig(**config))        # 2. Control
registry = ToolRegistry()                               # 3. Tools
memory  = MemoryModule(backend, config, embedder)       # 4. Memory  (optional)
skills  = SkillsModule(FilesystemRegistry(path))        # 5. Skills  (optional)
budget  = BudgetManager(BudgetConfig(**budget_cfg))     # 6. Budget  (optional)
loop    = AgentLoop(model, registry, obs, control,      # 7. Loop — holds all modules
                    memory, skills, budget)
return Mori(loop, registry, obs, ...)
```

## Spec Index

| Spec | Title | Module page | Status |
|------|-------|-------------|--------|
| 00 | Overview | *(this page)* | ✅ |
| 01 | Core Types | [`mori/types.py`](../specs/01-CORE-TYPES.md) | ✅ |
| 02 | Runtime | [Runtime](runtime.md) | ✅ |
| 03 | Memory | [Memory](memory.md) | ✅ |
| 04 | Skills | [Skills](skills.md) | ✅ |
| 05 | Tools & Protocols | [Tools & Protocols](tools-and-protocols.md) | ✅ |
| 06 | Permission Engine | *(v0.5 — in progress)* | 🔄 |
| 07 | Control | [Control](control.md) | ✅ |
| 08 | Observability | [Observability](observability.md) | ✅ |
| 09 | Context Budget | [Budget Manager](budget.md) | ✅ |
| 10 | Plugins & Hooks | *(v0.5 — in progress)* | 🔄 |
| 11 | Integration | [V1 Roadmap](../history/v1-roadmap.md) | 📋 |
| 12 | AIUC-1 Compliance | [V1 Roadmap](../history/v1-roadmap.md) | 📋 |
| 13 | Pi Patterns | [V1 Roadmap](../history/v1-roadmap.md) | 📋 |
| 14 | Resilience & Temporal | [Resilience & Temporal](resilience.md) | 📋 |
