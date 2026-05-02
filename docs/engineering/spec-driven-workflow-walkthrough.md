# Spec-Driven Development Walkthrough

This document demonstrates the team's full development workflow end-to-end, using a realistic fictional ticket as the example. It shows where a written spec fits into the existing phased process and what each step actually produces.

Reference: [user-story-implementation-workflow.md](./user-story-implementation-workflow.md)

---

## What Spec-Driven Development Adds

The existing workflow has a planning checkpoint early on, but it's conversational — you trace the implementation in chat and get verbal approval. On a library like this one (pure Python, async-first, protocol-neutral), that approach works but leaves a gap: decisions get made in passing, tradeoffs aren't recorded, and the PR description ends up re-explaining things that were already figured out.

Spec-driven development inserts a **written design document** between ticket validation and implementation. The spec becomes the source of truth for the entire feature: the plan, the PR summary, and the Linear comments all pull from it. The planning checkpoint becomes a review of that document rather than a chat summary.

The cost is one extra step before writing code. The payoff is fewer surprises mid-implementation and faster PR reviews.

---

## The Ticket: MORI-42

```
Title:  Add Postgres memory backend with pgvector retrieval
Epic:   MORI-30 — Production-grade memory layer
Status: Todo

Description:
  As a developer deploying Mori in production, I want a Postgres-backed
  memory backend so that agent memory persists across restarts and can
  be queried with vector similarity search.

Acceptance criteria:
  - PostgresBackend implements the MemoryBackend protocol
  - Supports store, retrieve, and delete operations
  - Vector similarity search uses pgvector (cosine distance)
  - Connection managed via asyncpg connection pool
  - Backend is optional — import only succeeds when asyncpg + pgvector installed
  - Tests cover happy path, missing-dependency error, and retrieval ranking
```

---

## Phase 0 — Validate & Setup

**Goal:** Understand the ticket fully before touching any code.

### What you do

1. Fetch the ticket via Linear MCP:
   ```
   get_issue("MORI-42")
   list_comments("MORI-42")
   get_issue("MORI-30")   # parent epic
   ```

2. Read the epic to understand what came before MORI-42 and what comes after. This surfaces scope boundaries — e.g., the epic may already have a retrieval pipeline that the Postgres backend needs to plug into.

3. Check for ambiguities. In this case:
   - "Vector similarity" — cosine only, or configurable? And does the `Embedder` live in this ticket or is it assumed to already exist?
   - "Optional import" — does this follow the existing pattern in `mori/model/anthropic.py` where the adapter raises `ImportError` at init, or is it guarded at module level?

4. Confirm understanding with the user before branching. Example summary:

   > MORI-42 asks for a Postgres memory backend using asyncpg + pgvector. I'm assuming the `Embedder` (Spec 03) already exists and this ticket is only the backend. Optional import follows the `anthropic.py` pattern — raises `ImportError` with a helpful message at `__init__` if `asyncpg` isn't installed. Is that right?

5. Once confirmed, create the branch:
   ```bash
   gt sync
   gt checkout --trunk
   gt create -am "chore: scaffold MORI-42 postgres backend"
   # branch name: carl/mori-42-postgres-memory-backend
   ```

6. Post Phase 0 comment to Linear ticket.

---

## Phase 0.5 — The Spec Step *(new)*

**Goal:** Produce a written design document that answers every implementation question before writing code.

This phase sits between Phase 0 and the planning checkpoint. It replaces the ad-hoc planning chat with a committed document.

### Step 1: Brainstorm

Work through the design by asking one question at a time. Key questions for MORI-42:

- **Protocol fit:** What does `MemoryBackend` require? — Read `mori/memory/backends/base.py` for the abstract interface. The backend must implement `store`, `retrieve`, and `delete`.
- **Connection lifecycle:** Who owns the pool? — The backend owns it. `connect()` and `close()` methods follow the pattern already in `mori/protocols/mcp/client.py`.
- **Schema:** What does the table look like? — One row per memory entry: `id`, `agent_id`, `content` (text), `embedding` (vector), `metadata` (jsonb), `created_at`. Index on `agent_id` + HNSW index on `embedding`.
- **Retrieval:** How does similarity search work? — `retrieve(query_embedding, top_k, agent_id)` runs `ORDER BY embedding <=> $1 LIMIT $2` filtered by `agent_id`. Cosine distance (`<=>`) is what pgvector provides natively.
- **Optional import guard:** Where? — At the top of `mori/memory/backends/postgres.py`, mirror the pattern in `mori/model/anthropic.py`: try-import, expose a descriptive `ImportError` at class init.
- **Tests:** What to cover? — Happy path (store + retrieve + ranking order), delete, missing-dependency `ImportError`, empty result set.

### Step 2: The Design Document

The output of brainstorming is a written spec, committed at:

```
docs/superpowers/specs/2026-05-02-postgres-memory-backend-design.md
```

Example spec (abbreviated):

```markdown
# Design: Postgres Memory Backend (MORI-42)

## Problem
The in-memory and SQLite backends don't survive process restarts and
can't scale across multiple agent instances. Production deployments need
a shared, persistent backend with efficient similarity search.

## Scope
In: PostgresBackend class, asyncpg pool management, pgvector retrieval,
    optional-import guard, unit tests.
Out: migration tooling, connection string config helpers, multi-tenant
     row-level security, embedding generation (handled by Embedder).

## Module Interface

Class: `PostgresBackend(MemoryBackend)`
Location: `mori/memory/backends/postgres.py`

Methods:
- `__init__(dsn: str, pool_size: int = 5)` → raises ImportError if asyncpg missing
- `async connect() -> None` → creates pool, ensures table + indexes
- `async close() -> None` → closes pool
- `async store(entry: MemoryEntry) -> None`
- `async retrieve(query: EmbeddingVector, top_k: int, agent_id: str) -> list[MemoryEntry]`
- `async delete(entry_id: str) -> None`

## Schema

Table: `mori_memory`
- id (UUID, PK)
- agent_id (TEXT, not null)
- content (TEXT, not null)
- embedding (vector(1536), nullable — null if no embedder configured)
- metadata (JSONB, default '{}')
- created_at (TIMESTAMPTZ, default now())

Indexes:
- btree on agent_id
- HNSW on embedding (cosine, m=16, ef_construction=64)

## Retrieval Query

```sql
SELECT * FROM mori_memory
WHERE agent_id = $1
ORDER BY embedding <=> $2
LIMIT $3
```

Falls back to recency order (`ORDER BY created_at DESC`) if `query` is None.

## Optional Import Pattern

Follows `mori/model/anthropic.py`:
```python
try:
    import asyncpg
    from pgvector.asyncpg import register_vector
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

class PostgresBackend(MemoryBackend):
    def __init__(self, ...):
        if not HAS_DEPS:
            raise ImportError(
                "PostgresBackend requires asyncpg and pgvector. "
                "Install with: pip install mori[postgres]"
            )
```

## Testing
- `test_postgres_backend.py` using pytest with asyncpg test database or mock pool
- Happy path: store → retrieve returns in similarity order
- Delete: entry no longer returned after delete
- Missing deps: `ImportError` raised with helpful message
- Empty result: retrieve returns `[]` gracefully
```

### Step 3: The Implementation Plan

From the spec, extract an ordered task list. This becomes the planning checkpoint:

```
1. Read mori/memory/backends/base.py — confirm MemoryBackend interface
2. Read mori/memory/backends/sqlite.py — borrow connection lifecycle pattern
3. Read mori/model/anthropic.py — borrow optional-import guard pattern
4. Implement mori/memory/backends/postgres.py:
     - Optional import guard
     - PostgresBackend class with connect/close/store/retrieve/delete
5. Export PostgresBackend from mori/memory/backends/__init__.py (guarded)
6. Write tests/test_postgres_backend.py:
     - Import error test (no asyncpg)
     - Store + retrieve ranking test
     - Delete test
     - Empty retrieval test
7. Add asyncpg + pgvector to pyproject.toml [postgres] optional dep (already there — verify versions)
8. Run: ruff check, mypy, pytest
```

---

## Phase 1 — Planning Checkpoint

**Goal:** Get user approval on the spec before writing any code.

With a written spec, this checkpoint is fast. Instead of reconstructing the plan from memory, you share the doc:

> "Spec is at `docs/superpowers/specs/2026-05-02-postgres-memory-backend-design.md`.
> Implementation order is the 8-step plan in the spec.
> Main tradeoff: own the pool lifecycle in the backend vs. accepting an injected pool —
> chose self-owned because it keeps the interface clean and matches how `mori/protocols/mcp/client.py` works.
> Does this look right?"

If the user approves, you proceed. If they want changes, you update the spec first, then proceed. The spec is the contract.

Post Phase 1 comment to Linear ticket.

---

## Phases 2–5 — Implementation to Validation

During implementation, the spec does three things:

**Answers questions you'd otherwise re-derive.** When you're deep in Phase 2 writing the retrieval query, the spec already says which distance operator to use and exactly when to fall back to recency order. You don't have to re-read the pgvector docs — you look at the spec.

**Keeps scope contained.** When you notice the backend could also handle embedding generation, the spec reminds you that's out of scope for MORI-42. You create a new ticket instead of expanding the module.

**Provides the Phase 4 code quality checklist.** The spec's interface table and optional-import section give you a concrete list to verify: does every method match the `MemoryBackend` protocol? Does the guard raise the right error message? Do all four test scenarios pass?

Key validation commands at each phase:

```bash
# After implementation — lint + format
ruff check mori/memory/backends/postgres.py
ruff format mori/memory/backends/postgres.py

# Type check
mypy mori/memory/backends/postgres.py

# Run tests
pytest tests/test_postgres_backend.py -v

# Full pre-commit pass
pre-commit run --all-files

# Full pre-push pass (all tests, all hooks)
STAGE=pre-push pre-commit run --all-files
```

Neither phase completes until all checks pass. No exceptions.

---

## Phases 6–8 — Commit, PR, Linear

### Commit (Phase 6)

The spec's task list maps directly to logical commits:

```bash
# Commit 1: implementation
gt modify -am "feat(memory): add PostgresBackend with pgvector retrieval (MORI-42)"

# Commit 2: tests
gt modify --commit -am "test(memory): postgres backend happy path and import guard (MORI-42)"
```

Push via Graphite:
```bash
gt submit
```

### Pull Request (Phase 7)

The PR summary writes itself from the spec:

```markdown
## Summary
- Adds `PostgresBackend` implementing `MemoryBackend` with asyncpg connection pool
- Retrieval uses pgvector cosine distance (`<=>`) with recency fallback when no embedding
- Optional import guard raises `ImportError` with install instructions if asyncpg/pgvector missing

## Closes
Closes MORI-42

## Test Plan
- [ ] `test_postgres_backend.py` passes (store/retrieve ranking, delete, import error, empty result)
- [ ] `ruff check` passes
- [ ] `mypy` passes (strict mode)
- [ ] `pre-commit run --all-files` passes
- [ ] `STAGE=pre-push pre-commit run --all-files` passes
```

### Linear Comments (Phase 8)

Each phase comment references the spec rather than re-explaining the approach. Reviewers who want detail can read the spec doc; the Linear comment is just a status update.

---

## Summary: What the Spec Bought

| Without spec | With spec |
|---|---|
| Planning lives in chat, lost after the session | Design committed to the repo, reviewable in the PR |
| Scope creep discovered mid-implementation | Out-of-scope items caught before writing code |
| PR description requires reconstructing decisions | PR summary copied from spec |
| Code review from memory | Concrete checklist from spec's interface and test sections |
| Linear comments re-explain the approach | Linear comments reference the spec |

The spec is not overhead — it's the plan you would have made anyway, written down before the code rather than after.

---

## Quick Reference: Where Everything Lives

```
docs/
  engineering/
    user-story-implementation-workflow.md   ← canonical phased workflow
    spec-driven-workflow-walkthrough.md     ← this document
  superpowers/
    specs/
      YYYY-MM-DD-<feature>-design.md        ← one spec per feature
      YYYY-MM-DD-<feature>-plan.md          ← implementation plan (from writing-plans skill)
```
