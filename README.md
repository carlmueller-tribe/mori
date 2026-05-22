<p align="center">
  <img src="mori-docs/mori-icon.png" alt="Mori" width="360" />
</p>

<h1 align="center">Mori (森)</h1>
<p align="center"><em>The cognitive environment for LLM agents.</em></p>

---

Mori is a Python library for building governed, auditable LLM agent systems. It provides a complete native runtime — not a workflow wrapper — with the layers that production agents need but most frameworks leave out: structured memory, reusable skill artifacts, declarative permissions, dynamic context budget management, and vendor-neutral observability with a full audit trail.

Each agent is an independent tree. The forest shares structure.

## Why Mori

Most agent frameworks answer the question *how do I wire steps together*. Mori answers the harder questions: who approved this action, what did the model see when it decided, where does the compliance evidence live, and what happens when the context window runs out.

Governance, audibility, and resource control are structural — not bolt-ons.

## What's Inside

| Module | What it does |
|---|---|
| **Runtime** | Lightweight async state machine: perceive → plan → validate → act → observe → evaluate → update |
| **Memory** | Four-layer memory (working, episodic, semantic, procedural) with pluggable backends |
| **Skills** | Reusable skill artifacts with progressive disclosure — agents discover and follow procedures |
| **Protocols** | Native MCP client, CLI tool runner, A2A registry |
| **Permissions** | Declarative policy engine with scope hierarchy and approval gates |
| **Control** | Resource bounds, retry logic, and checkpoint save/restore |
| **Observability** | Structured event stream with pluggable sinks (stdout, JSONL, OTLP) |
| **Budget** | Dynamic context allocation and graduated compaction |
| **Compliance** | AIUC-1 primitives: risk taxonomy, data guards, evidence exporter |

## Install

Clone the repo and install in editable mode:

```bash
git clone https://github.com/carlmueller-tribe/mori.git
cd mori
pip install -e .
```

With Anthropic support:

```bash
pip install -e ".[anthropic]"
```

## Quick Start

```python
from mori import Mori

agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(read_file, description="Read a file")
    .memory_backend("sqlite", path="./memory.db")
    .skill_registry("./skills/")
    .budget(total_context_tokens=200_000)
    .sink("stdout")
    .build()
)

result = await agent.run("Fix the failing test in tests/test_auth.py")
```

### Chat Mode

The agent can pause mid-run to ask the user a question and resume after the
user responds. A checkpointer is required so state is preserved across the
pause.

```python
# Chat mode: agent can pause to ask the user a question
from mori import Mori
from mori.types import RunStatus

agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .checkpointer("memory")
    .build()
)

result = await agent.run("Apply the user_email migration if it's safe")
while result.status == RunStatus.PAUSED and result.paused_prompt:
    answer = input(f"{result.paused_prompt}\n> ")
    result = await agent.resume(result.thread_id, answer)
```

## Design Principles

- **Own the runtime.** No external orchestration dependency. Simple, debuggable, fast.
- **Treat frameworks as plugins.** LangGraph, CrewAI, and others can run inside Mori — Mori never depends on them.
- **Governance by default.** Permissions, audit logging, and approval gates are structural components.
- **Vendor-neutral.** Works with any LLM provider, any observability stack, any storage backend.
- **Minimal sufficiency.** Load only what reduces the model's cognitive burden for the current step.

## Documentation

Full architecture documentation lives in [`mori-docs/`](mori-docs/). To browse it locally:

```bash
pip install -e ".[docs]"
mkdocs serve
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

The docs cover every module with 6-tier progressive disclosure (TL;DR → API surface → internals → annotated examples), a version history narrative from v0.1 through V1, and a roadmap for proposed modules.

Raw specs: [`mori-docs/specs/`](mori-docs/specs/)

## Status

Under heavy active development. APIs may change without notice between versions.
