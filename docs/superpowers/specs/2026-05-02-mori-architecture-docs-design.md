# Mori Architecture Documentation — Design Spec

**Date:** 2026-05-02
**Author:** Carl Mueller
**Status:** Approved

---

## 1. Purpose

Produce a deep, human-readable architecture documentation site for the Mori library. The audience is human developers — contributors, library users, and people evaluating Mori. The docs must be MkDocs-ready (Material theme) and version-track the codebase from v0.1 through V1.

---

## 2. File Structure

All new files are created alongside existing content in `mori-docs/`. The existing raw design specs in `mori-docs/specs/` are left untouched — the architecture docs are a separate human-readable layer that cross-links to them.

```
mori-docs/
├── index.md                        # Hub page
├── architecture/
│   ├── index.md                    # Module map + full data flow
│   ├── runtime.md                  # AgentLoop, MoriState, phases, RunResult
│   ├── memory.md                   # 4-layer memory, retrieval, backends, lifecycle
│   ├── skills.md                   # Skill artifacts, discovery, disclosure, binding
│   ├── budget.md                   # Budget slots, compaction pipeline, rebalancing
│   ├── observability.md            # Events taxonomy, sinks, engine
│   ├── tools-and-protocols.md      # ToolRegistry, CLI runner, MCP client
│   └── control.md                  # ControlBounds, retry logic
└── history/
    ├── index.md                    # Visual version timeline
    ├── v01-it-runs.md
    ├── v02-it-sees.md
    ├── v03-it-remembers.md
    ├── v04-it-learns.md
    ├── v05-its-governed.md         # Marked "in progress"
    └── v1-roadmap.md

mkdocs.yml                          # New at project root
```

---

## 3. MkDocs Configuration

**File:** `mkdocs.yml` (project root)

```yaml
site_name: Mori
site_description: The cognitive environment for LLM agents
docs_dir: mori-docs
theme:
  name: material
  features:
    - navigation.tabs
    - navigation.sections
    - toc.integrate
    - content.code.copy
  palette:
    scheme: slate
    primary: green

nav:
  - Home: index.md
  - Architecture:
    - Overview: architecture/index.md
    - Runtime: architecture/runtime.md
    - Memory: architecture/memory.md
    - Skills: architecture/skills.md
    - Budget Manager: architecture/budget.md
    - Observability: architecture/observability.md
    - Tools & Protocols: architecture/tools-and-protocols.md
    - Control: architecture/control.md
  - Version History:
    - Timeline: history/index.md
    - "v0.1 — It Runs": history/v01-it-runs.md
    - "v0.2 — It Sees": history/v02-it-sees.md
    - "v0.3 — It Remembers": history/v03-it-remembers.md
    - "v0.4 — It Learns": history/v04-it-learns.md
    - "v0.5 — It's Governed": history/v05-its-governed.md
    - V1 Roadmap: history/v1-roadmap.md

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:pymdownx.superfences.fence_code_format
  - pymdownx.tabbed:
      alternate_style: true
  - toc:
      permalink: true
```

**MkDocs optional dependencies to add to `pyproject.toml`:**

```toml
[project.optional-dependencies]
docs = [
    "mkdocs>=1.6",
    "mkdocs-material>=9.5",
    "pymdown-extensions>=10.0",
]
```

---

## 4. Progressive Disclosure Structure (per module page)

Every page in `architecture/` follows the same 6-tier structure. Readers stop at the tier that satisfies their need.

### Tier 1 — TL;DR
2–3 sentences. What the module does and why it exists. Readable in 10 seconds.

### Tier 2 — Role in the System
Where the module sits in the dependency graph. What depends on it and what it depends on. One Mermaid flowchart showing its position in the execution loop.

### Tier 3 — Key Concepts
Bulleted glossary of the 4–8 most important types and classes. Each entry: name + one-line description. No code.

### Tier 4 — API Surface
The critical interfaces as code blocks — protocols, builder methods, key method signatures. Implementation-free; shows only the contract a caller needs to understand.

### Tier 5 — How It Works
Prose + annotated code excerpts walking through the internal design: the interesting decisions, algorithms, data flow. Complex modules get subsections (e.g. Memory gets: Retrieval Pipeline, Backend Protocol, Forget Lifecycle).

### Tier 6 — Annotated Example
A short end-to-end snippet showing the module in real use, with inline comments explaining the key moments.

---

## 5. Hub Page (`index.md`) Content

1. **What Mori is** — 2 paragraphs (library purpose, positioning vs. LangGraph)
2. **Design philosophy** — the 6 principles (P1–P6 from spec 00-OVERVIEW)
3. **Architecture diagram** — Mermaid diagram of all modules and their relationships
4. **Module directory** — table: Module | Purpose | Page link
5. **10-line quickstart** — a complete `MoriBuilder` example showing the builder API end-to-end

---

## 6. Architecture Overview Page (`architecture/index.md`) Content

1. **Module dependency graph** — Mermaid diagram showing which modules depend on which
2. **Full data flow** — annotated flow from `Mori.run(task)` through all loop phases to `RunResult`
3. **Builder wiring** — how `MoriBuilder.build()` assembles the modules
4. **Spec index** — table mapping each spec number (01–13) to its module page and implementation status

---

## 7. Version History Pages (`history/`)

### Per-version page structure (`v0N-*.md`)

```
# v0.N — "[Codename]"
Released: [date]    Specs added: [list]

## What Changed
3–5 bullets: the new modules/capabilities introduced.

## Why It Mattered
1–2 paragraphs: the design reasoning — what problem this version
solved, what architectural decision was made and why.

## Architecture at This Point
Mermaid diagram showing *only the modules that existed* at this version.

## Key Files Introduced
Table: file path → what it does.

## Design Decisions Worth Noting
The non-obvious choices made at this version. Explained with the
reasoning that was live at the time.
```

### Version inventory

| Page | Version | Codename | Theme |
|------|---------|----------|-------|
| `v01-it-runs.md` | v0.1 | It Runs | Foundation: types, loop, registry, Anthropic adapter |
| `v02-it-sees.md` | v0.2 | It Sees | Protocols, observability, control bounds, CLI + MCP |
| `v03-it-remembers.md` | v0.3 | It Remembers | Four-layer memory, retrieval pipeline, SQLite backend |
| `v04-it-learns.md` | v0.4 | It Learns | Skills module + Budget manager + compaction pipeline |
| `v05-its-governed.md` | v0.5 | It's Governed | Permission engine, checkpoints, lifecycle hooks *(in progress)* |

### `history/index.md`
A visual timeline table: version | codename | date | modules added | key design decision. Links to each version page.

### `v1-roadmap.md`
Covers remaining specs (06 permission, 10 plugins/hooks, 11 integration, 12 AIUC-1 compliance, 13 Pi patterns). Describes what the complete V1 system looks like assembled — the full module set, the complete execution flow, and the governance layer.

---

## 8. Module Page Inventory

| File | Module | Key types/classes to cover |
|------|--------|---------------------------|
| `runtime.md` | AgentLoop, MoriState, RunResult | `AgentLoop`, `MoriState`, `RunResult`, `StepResult`, `Phase`, `RunStatus`, `StepOutcome` |
| `memory.md` | MemoryModule, backends, retrieval | `MemoryModule`, `MemoryBackend` (protocol), `InMemoryBackend`, `SQLiteBackend`, `Embedder`, `MemoryRecord`, `MemorySlice`, `MemoryLayer`, `ForgetPolicy`, `retrieve()` |
| `skills.md` | SkillsModule, registry, disclosure | `SkillsModule`, `FilesystemRegistry`, `SkillManifest`, `SkillCandidate`, `SkillPayload`, `BoundSkill`, `DisclosureLevel`, `CompatibilityReport`, `manifest.yaml` schema |
| `budget.md` | BudgetManager, compaction | `BudgetManager`, `BudgetConfig`, `BudgetSlot`, `CompactionStage` (6 stages), `CompactionReport`, `TokenBudget`, `rebalance()`, `compact()` |
| `observability.md` | ObservabilityEngine, events, sinks | `ObservabilityEngine`, `MoriEvent` hierarchy (12 event types), `EventSink` (protocol), `StdoutSink`, `JsonlSink`, `ObservabilityConfig`, `SpanContext`, `RunSummary` |
| `tools-and-protocols.md` | ToolRegistry, CLIRunner, MCPClient | `ToolRegistry`, `RegisteredTool`, `ToolSpec`, `ToolSource`, `CLIRunner`, `CLIToolConfig`, `MCPClient`, `SchemaCache`, `infer_schema()` |
| `control.md` | ControlBounds | `ControlBounds`, `ControlConfig`, `BoundCheckResult`, `RetryDecision` |
| `model-adapters.md` | ModelAdapter, AnthropicAdapter | `ModelAdapter` (protocol), `AnthropicAdapter`, `StreamChunk`, `max_context_tokens`, `invoke()`, `count_tokens()` |

---

## 9. Content Depth Standards

**Code snippets:** Use real code from the codebase — no invented APIs. Every snippet must be accurate to the current implementation.

**Diagrams:** Mermaid only (renders natively in MkDocs Material). Flowcharts for data flow, class diagrams for type relationships where useful.

**Progressive disclosure mechanics:** Use MkDocs Material `???` collapsible admonitions for deeper detail within a section, keeping each tier's summary visible by default.

Example:
```markdown
## How It Works

The retrieval pipeline runs in four stages...

??? note "Stage details"
    **Stage 1 — Query Expansion:** ...
    **Stage 2 — Multi-Layer Fan-Out:** ...
```

**Cross-linking:** Every module page links to its corresponding raw spec in `mori-docs/specs/` and to related module pages (e.g. Memory links to Budget, Skills links to Budget).

---

## 10. Out of Scope

- API reference auto-generated from docstrings (separate future task)
- Tutorial/getting-started section (add when library has external users)
- `reference/` section for raw type listings (the existing `mori-docs/specs/01-CORE-TYPES.md` serves this for now)
- Deploying to GitHub Pages (a one-command follow-up once the docs are written)
