# User Story Implementation Workflow

This document defines the end-to-end workflow for implementing features from Linear tickets (MORI-* identifiers). It incorporates spec-driven development as a first-class step between ticket validation and implementation.

Reference: [spec-driven-workflow-walkthrough.md](./spec-driven-workflow-walkthrough.md) — full worked example with a realistic ticket.

---

## Prerequisites

- Linear ticket with MORI-* identifier
- Access to the codebase and development environment
- Python 3.11+, uv, and dev dependencies installed:
  ```bash
  uv sync --extra dev
  ```
- pre-commit hooks installed:
  ```bash
  pre-commit install
  ```

**Important**: Always run pre-commit using `pre-commit run --all-files` (pre-commit stage) or `STAGE=pre-push pre-commit run --all-files` (pre-push stage). Never skip hooks with `--no-verify`.

---

## Workflow Overview

**CRITICAL — STOP ON FAILURE**: If any step, test, validation, or check fails:

1. **STOP immediately** — do not proceed to the next phase
2. **Alert the user** with full error details and context
3. **Attempt to fix automatically** if the fix is straightforward and obvious
4. **If you cannot fix it or are unsure**: DO NOT guess, DO NOT bypass, DO NOT proceed — wait for user guidance
5. **After fixing**: Re-run all affected validations before proceeding

Examples of failures that MUST stop execution:
- Tests fail (unit, integration)
- Type checking (mypy strict) reports errors
- Ruff lint or format check fails
- Pre-commit or pre-push hooks fail
- The spec review reveals a design problem

**CRITICAL — PHASE ORDER IS FIXED**: Phases MUST execute in order 0→0.5→1→2→3→4→5→6→7→8. Never skip phases, never reorder, never jump ahead.

This workflow takes a feature from Linear ticket to merged PR through 9 phases:

0. **Validation & Setup** — Understand the ticket, its epic, and create a branch. **CHECKPOINT**: Confirm understanding with user, document clarifications in Linear.
0.5. **Spec Step** — Produce a written design document before any code. Brainstorm design questions, write the spec, extract an implementation plan.
1. **Planning Checkpoint** — Get user approval on the spec. **CHECKPOINT**: User approves spec before implementation begins.
2. **Implementation** — Update ticket to "In Progress", implement the module following the spec.
3. **Testing & Validation** — Write and run tests, ruff, mypy. **CHECKPOINT**: All checks pass before proceeding to quality review.
4. **Code Quality** — Verify patterns, conventions, type safety.
5. **Pre-Push Validation** — Full pre-push hook suite. **CHECKPOINT**: Ask user for approval before proceeding to commit.
6. **Commit & Push** — Logical commits via `gt`, push to feature branch.
7. **Pull Request** — Draft PR with summary and test plan drawn from the spec.
8. **Linear Comments** — Update Linear ticket with a comment at the end of every phase (0–7).

---

## Key Principles

### 1. Always Check Code Context

- **NEVER propose changes to code you haven't read**
- Understand existing patterns before implementing new features
- Search comprehensively for similar implementations in `mori/`

### 2. Write the Spec Before Writing Code

- Every non-trivial feature gets a design document before implementation
- The spec lives in `docs/superpowers/specs/YYYY-MM-DD-<feature>-design.md`
- The spec is the contract — if requirements change, update the spec first

### 3. Follow Existing Patterns

- Reuse established module patterns (optional-import guard, async lifecycle, protocol conformance)
- Match existing code style: ruff target py311, line-length 100, strict mypy
- Use discovered conventions consistently

### 4. Be Thorough with Testing

- Test at unit level: happy path, edge cases, error conditions
- Test optional-dependency guards (ImportError message quality matters)
- Test async code properly with pytest-asyncio

### 5. Avoid Over-Engineering

- Keep solutions simple and focused on the spec scope
- Don't add features beyond the acceptance criteria
- Don't create abstractions for one-time operations
- Don't add error handling for impossible scenarios

### 6. Never Skip Checks or Bypass Failures

- Always run pre-commit hooks: `pre-commit run --all-files`
- **If checks fail**: STOP immediately, analyze the error, fix it, re-run
- Never use `--no-verify`, never comment out failing tests
- Each phase builds on the previous — a failure in Phase N makes Phase N+1 meaningless

### 7. Be Honest with the User

- Tell users if they're wrong or have misunderstood the code
- Don't make assumptions about unclear requirements
- Report failures and blockers immediately

### 8. Execute Phases Sequentially

- Phase order is fixed: 0→0.5→1→2→3→4→5→6→7→8
- Never skip phases, never work multiple phases in parallel
- Each phase requires the previous to be complete and successful

---

## Workflow Phases

### Phase 0: Validation & Setup

**Objective**: Verify ticket validity, understand broader context, prepare the environment.

#### 0.1 Ticket Verification

- Use Linear MCP `get_issue` to read the ticket details
- Use Linear MCP `list_comments` to read all comments on the ticket
- Read thoroughly — comments often contain critical clarifications not in the description
- Verify ticket status is appropriate for work

#### 0.2 Understand Broader Context

- **Read parent epic** using Linear MCP `get_issue` on the parent issue
- **Check related tickets**: look at preceding and following tickets in the epic
- **Identify scope boundaries**: what's explicitly in vs. out of scope for this ticket
- **Check for dependencies**: note any blockers or tickets that must complete first

#### 0.3 Clarification

- If requirements are unclear, ask clarifying questions immediately
- Identify missing acceptance criteria or edge cases
- Ask about scope boundaries if unclear from epic/comments

#### 0.4 Branch Strategy

- **If on main**: pull latest, then create branch
- **If on another branch**: ask user if they want to branch from current state or switch to main first
- **Branch naming**: `{firstname}/mori-{number}-{short-description}`
  - Extract lowercase first name from `git config user.name`
  - Example: `carl/mori-42-postgres-memory-backend`
  ```bash
  gt sync
  gt checkout --trunk
  gt create -am "chore: scaffold MORI-{N} {short description}"
  ```

#### 0.5 Confirm Understanding with User

- **CRITICAL CHECKPOINT**: before starting the spec step, confirm understanding
- Summarize: core story, key acceptance criteria, scope boundaries, any assumptions
- Ask: "Is my understanding correct? Do you have any additional context?"
- If clarifications are provided, document them via Linear MCP `save_comment`
- **Do not proceed to Phase 0.5 until user confirms**

---

### Phase 0.5: The Spec Step *(spec-driven addition)*

**Objective**: Produce a written design document that answers every implementation question before writing code.

This phase replaces ad-hoc planning chat with a committed document. See [spec-driven-workflow-walkthrough.md](./spec-driven-workflow-walkthrough.md) for a full worked example.

#### 0.5.1 Read Before You Design

Before brainstorming, read the relevant existing code:

- **Protocol/interface**: what abstract class or protocol does the new module conform to?
- **Similar implementations**: find the closest existing implementation and study its pattern
- **Caller sites**: where will this module be used? What does the calling code expect?
- **Optional-import pattern**: if the feature has optional deps, read `mori/model/anthropic.py`

#### 0.5.2 Brainstorm

Work through the design one question at a time:

- **Interface**: what methods are required by the protocol? What signatures?
- **Lifecycle**: who creates this object? Who calls `connect`/`close` if applicable?
- **Data shape**: what types flow in and out? Are they already defined in `mori/types.py`?
- **Error handling**: what can fail? What does the caller need to know?
- **Optional deps**: which imports are hard requirements vs. optional extras?
- **Testing approach**: what scenarios must be covered? Can tests run without external services?

#### 0.5.3 Write the Design Document

Commit the spec at:
```
docs/superpowers/specs/YYYY-MM-DD-<feature>-design.md
```

The spec must include:

```markdown
# Design: <Feature Name> (MORI-N)

## Problem
Why this is needed.

## Scope
In: what this ticket delivers.
Out: what is explicitly excluded.

## Module Interface
Class name, location, and method signatures with types.

## Key Design Decisions
Tradeoffs made and why.

## Error Handling
What errors are raised, when, and with what messages.

## Testing
Scenarios to cover and any testing constraints (e.g., requires real DB vs. mockable).
```

#### 0.5.4 Extract the Implementation Plan

From the spec, produce an ordered task list:

```
1. Read <file> — confirm <interface>
2. Implement <module> with <key behavior>
3. Export from <__init__.py>
4. Write tests/<test_file>.py covering <scenarios>
5. Run ruff, mypy, pytest
```

This list becomes the Phase 1 approval artifact and the checklist for Phase 2 execution.

---

### Phase 1: Planning Checkpoint

**Objective**: Get user approval on the spec before writing any code.

#### 1.1 Present the Spec

Share the spec location and summarize:

> "Spec is at `docs/superpowers/specs/YYYY-MM-DD-<feature>-design.md`.
> Implementation order is the N-step plan in the spec.
> Main tradeoff: [X vs. Y] — chose [X] because [reason].
> Does this look right?"

#### 1.2 Get Approval

- If user approves: proceed to Phase 2
- If user requests changes: update the spec, re-present, get approval
- The spec is the contract — implementation must follow it

Post Phase 1 comment to Linear ticket.

**Do not proceed to Phase 2 until user approves.**

---

### Phase 2: Implementation

**Objective**: Implement the feature following the spec and existing patterns.

#### 2.0 Update Linear Ticket Status

- Mark ticket as "In Progress" via Linear MCP `save_issue`

#### 2.1 Module Implementation

Follow the ordered task list from the spec.

**Key patterns to follow:**

**Optional-import guard** (`mori/model/anthropic.py` pattern):
```python
try:
    import some_library
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

class MyFeature:
    def __init__(self, ...):
        if not HAS_DEPS:
            raise ImportError(
                "MyFeature requires some_library. "
                "Install with: pip install mori[extra]"
            )
```

**Async lifecycle** (`mori/protocols/mcp/client.py` pattern):
- `async connect() -> None` for resource acquisition
- `async close() -> None` for cleanup
- Support async context manager (`__aenter__`/`__aexit__`)

**Protocol conformance** (`mori/memory/backends/base.py` pattern):
- Inherit from or implement the abstract base
- Don't add methods that the protocol doesn't define unless they're clearly internal

**Type annotations:**
- Full annotations on all public methods
- Use types from `mori/types.py` where they exist
- No `Any` without a comment explaining why

#### 2.2 Module Exports

Add the new class to the appropriate `__init__.py`. Guard optional exports:

```python
# mori/memory/backends/__init__.py
from .base import MemoryBackend
from .inmemory import InMemoryBackend
from .sqlite import SQLiteBackend

try:
    from .postgres import PostgresBackend
    __all__ = ["MemoryBackend", "InMemoryBackend", "SQLiteBackend", "PostgresBackend"]
except ImportError:
    __all__ = ["MemoryBackend", "InMemoryBackend", "SQLiteBackend"]
```

#### 2.3 Tests

Write tests in `tests/test_<module>.py`. Cover:

- Happy path end-to-end
- Each error condition named in the spec
- Optional-dep `ImportError` with correct message
- Edge cases (empty results, missing data, etc.)

Follow the async pattern already in `tests/conftest.py`:
```python
import pytest
import pytest_asyncio

@pytest.mark.asyncio
async def test_something():
    ...
```

---

### Phase 3: Testing & Validation

**Objective**: Verify all code is correct and all checks pass.

#### 3.1 Lint & Format

```bash
ruff check mori/ tests/
ruff format mori/ tests/
```

**CRITICAL — STOP ON FAILURE**: Fix all lint errors before proceeding.

#### 3.2 Type Check

```bash
mypy mori/
```

Mori uses strict mypy. All errors must be resolved — no `# type: ignore` without a comment explaining why.

**CRITICAL — STOP ON FAILURE**: Fix all type errors before proceeding.

#### 3.3 Run Tests

```bash
pytest tests/test_<new_module>.py -v
pytest  # full suite — verify no regressions
```

**CRITICAL — STOP ON FAILURE**: All tests must pass. Fix root causes, not symptoms.

#### 3.4 Pre-Commit Pass

```bash
pre-commit run --all-files
```

This runs ruff, mypy, and all hooks configured in `.pre-commit-config.yaml`. All must pass.

**Do not proceed to Phase 4 until all checks pass.**

---

### Phase 4: Code Quality & Consistency

**Objective**: Ensure the code follows Mori's patterns and the spec's intent.

#### 4.1 Pattern Consistency

- Does the module follow the same lifecycle pattern as similar modules?
- Does error handling match the spec exactly (error type, message format)?
- Does the optional-import guard follow the established pattern?
- Are type annotations complete and accurate?

#### 4.2 Spec Compliance

Walk through the spec's interface section line by line:

- Every method in the spec exists in the implementation
- Signatures match (parameter names, types, return types)
- Error conditions from the spec are all handled
- Nothing extra was added that the spec doesn't mention

#### 4.3 Convention Adherence

- Line length ≤ 100 characters
- No bare `except:` clauses
- No mutable default arguments
- Docstrings on public classes and methods (one line is enough)
- File organization matches the package map in `mori-docs/specs/00-OVERVIEW.md`

---

### Phase 5: Pre-Push Validation

**Objective**: Run comprehensive checks before pushing code.

#### 5.1 Full Pre-Push Suite

```bash
pre-commit run --all-files
STAGE=pre-push pre-commit run --all-files
```

This runs additional checks beyond Phase 3.4, including the full test suite and any security hooks.

**CRITICAL — STOP ON FAILURE**: Fix all failures before proceeding. Do not use `--no-verify`.

#### 5.2 Regression Check

```bash
pytest  # full suite one final time
```

Confirm no regressions in unrelated modules.

#### 5.3 Pre-Push Approval

**CRITICAL CHECKPOINT**: Before committing, summarize for the user:

- What was built (module, tests)
- All validation checks passed (ruff, mypy, pytest, pre-commit, pre-push)
- Spec compliance verified

Ask: "All validations have passed. Ready to commit?"

**Do not proceed to Phase 6 until user approves.**

---

### Phase 6: Commit & Push

**Objective**: Create clean logical commits and push to the feature branch.

**PREREQUISITES**:
- All checks pass
- User has approved in Phase 5.3

#### 6.1 Logical Commit Groups

Group related changes into separate commits. For a typical module:

```bash
# Commit 1: implementation
gt modify -am "feat(<module>): <what and why> (MORI-N)"

# Commit 2: tests (if substantive enough to separate)
gt modify --commit -am "test(<module>): <what scenarios> (MORI-N)"
```

Conventional commit types: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`

#### 6.2 Commit Message Format

```bash
gt modify -am "$(cat <<'EOF'
feat(memory): add PostgresBackend with pgvector retrieval (MORI-42)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

#### 6.3 Push

```bash
gt submit
```

Never push directly to main.

---

### Phase 7: Pull Request

**Objective**: Create a draft PR with summary and test plan from the spec.

#### 7.1 PR Creation

```bash
gh pr create --draft --title "<concise title under 70 chars>" --body "$(cat <<'EOF'
## Summary
- [Key change 1 — drawn from spec scope section]
- [Key change 2]
- [Key change 3]

## Spec
`docs/superpowers/specs/YYYY-MM-DD-<feature>-design.md`

## Closes
Closes MORI-N

## Test Plan
- [ ] Unit tests pass (`pytest tests/test_<module>.py`)
- [ ] Full suite passes (`pytest`)
- [ ] `ruff check` passes
- [ ] `mypy` passes (strict)
- [ ] `pre-commit run --all-files` passes
- [ ] `STAGE=pre-push pre-commit run --all-files` passes

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Provide the PR URL to the user after creation.

---

### Phase 8: Linear Ticket Comments

**Objective**: Update the Linear ticket with a comment at the end of every phase (0–7).

Use Linear MCP `save_comment`. Comments should be concise and product-team focused. If you revisit a phase, add a follow-up comment noting what changed and why.

##### Phase 0 Comment

```markdown
**Phase 0: Validation & Setup Complete**

**Understood:**
- [Core story summary]
- [Key acceptance criteria]
- [Scope boundaries]

**Branch created:** `carl/mori-N-short-description`

**Clarifications documented:** [Yes/No — if yes, briefly note what was clarified]
```

##### Phase 0.5 Comment

```markdown
**Phase 0.5: Spec Complete**

**Spec:** `docs/superpowers/specs/YYYY-MM-DD-<feature>-design.md`

**Key decisions:**
- [Main design decision and rationale]
- [Main tradeoff]

**Implementation plan:** [N steps, summarized in one line]
```

##### Phase 1 Comment

```markdown
**Phase 1: Planning Checkpoint Complete**

**Approach approved:**
- Module: [location and class name]
- Interface: [key methods]
- Testing: [what scenarios]

**User approved:** ✓
```

##### Phase 2 Comment

```markdown
**Phase 2: Implementation Complete**

**Implemented:**
- `mori/<path>/<module>.py` — [brief description]
- Exported from `mori/<path>/__init__.py`
- Tests: `tests/test_<module>.py` ([N] test cases)
```

##### Phase 3 Comment

```markdown
**Phase 3: Testing & Validation Complete**

**Checks passed:**
- ruff: ✓
- mypy (strict): ✓
- pytest ([N] tests): ✓
- pre-commit: ✓
```

##### Phase 4 Comment

```markdown
**Phase 4: Code Quality Review Complete**

**Verified:**
- Pattern consistency with [similar module]
- Spec compliance (all interface methods match)
- Convention adherence
```

##### Phase 5 Comment

```markdown
**Phase 5: Pre-Push Validation Complete**

**All checks passed:**
- Pre-commit hooks: ✓
- Pre-push hooks: ✓
- Full test suite: ✓

**User approved to commit:** ✓
```

##### Phase 6 Comment

```markdown
**Phase 6: Commit & Push Complete**

**Commits:**
- [Commit 1 summary]
- [Commit 2 summary if multiple]

**Branch pushed:** `carl/mori-N-short-description`
```

##### Phase 7 Comment

```markdown
**Phase 7: Pull Request Created**

**PR:** [PR URL]
**Status:** Draft

**Summary:**
- [Key change 1]
- [Key change 2]

**Next step:** Review and merge
```

##### Phase 8 Comment

```markdown
**Phase 8: All Documentation Complete**

Linear updated with comments for phases 0–7.
Ticket ready for: manual status update to "In Review"
```

---

## Troubleshooting

### Mypy Strict Errors

**Symptoms**: `error: [attr-defined]`, `error: [no-untyped-def]`, etc.

- Read the error precisely — mypy tells you the file and line
- Don't add `# type: ignore` without understanding why
- Common fixes: missing return type annotation, `Any` used implicitly, missing `Optional`
- Check how similar code in `mori/` handles the same situation

### Optional Import Guard Not Working

**Symptoms**: `ImportError` not raised, or raised with wrong message

- Confirm `HAS_DEPS` is checked in `__init__`, not at module import time
- Test the guard by temporarily renaming the import in a scratch test

### Test Fails in CI but Passes Locally

**Symptoms**: pytest passes locally, fails in GitHub Actions

- Check if the test requires an env var that's set locally but not in CI
- Check if the test requires a network call — mock it instead
- Check Python version: Mori targets 3.11+; confirm no 3.12+ syntax crept in

### Pre-Commit Ruff Fix vs. Check Conflict

**Symptoms**: `ruff format` changes a file, then `ruff check` flags a different issue

- Run `ruff check --fix` first, then `ruff format`
- If they conflict, fix manually and verify both pass before committing

### gt Submit Rejected

**Symptoms**: `gt submit` fails with remote error

- Run `gt sync` to pull latest from trunk
- Resolve any conflicts, then `gt submit` again
- Never force-push unless the user explicitly asks

---

## Workflow Summary Checklist

- [ ] **Phase 0**: Validated ticket (Linear MCP), understood epic context, created branch
- [ ] **Phase 0 Checkpoint**: Confirmed understanding with user, documented clarifications in Linear
- [ ] **Phase 0.5**: Read existing code, brainstormed design, wrote spec at `docs/superpowers/specs/`
- [ ] **Phase 1**: Presented spec to user, got approval before writing any implementation code
- [ ] **Phase 2**: Updated Linear to "In Progress", implemented module following spec, wrote tests
- [ ] **Phase 3**: `ruff check` ✓, `mypy` ✓, `pytest` ✓, `pre-commit run --all-files` ✓
- [ ] **Phase 4**: Verified pattern consistency, spec compliance, convention adherence
- [ ] **Phase 5**: Full pre-push suite passes, user approved to commit
- [ ] **Phase 6**: Logical commits with HEREDOC format, pushed via `gt submit`
- [ ] **Phase 7**: Draft PR created (`gh pr create --draft`), PR URL shared with user
- [ ] **Phase 8**: Linear comments added for all phases (0–7), user informed to move ticket to "In Review"

---

## Key Files Reference

### Source

- `mori/` — library source, organized by spec module
- `mori/types.py` — shared types (check here before defining new ones)
- `mori/memory/backends/base.py` — MemoryBackend protocol (reference for backend implementations)
- `mori/model/anthropic.py` — optional-import guard pattern
- `mori/protocols/mcp/client.py` — async lifecycle pattern

### Tests

- `tests/` — all tests live here, flat
- `tests/conftest.py` — shared fixtures

### Config

- `pyproject.toml` — project config, ruff rules, mypy config, pytest config
- `.pre-commit-config.yaml` — hook definitions

### Docs

- `docs/engineering/user-story-implementation-workflow.md` — this document
- `docs/engineering/spec-driven-workflow-walkthrough.md` — full worked example
- `docs/superpowers/specs/` — one spec per feature
- `mori-docs/specs/` — library design specs (00-OVERVIEW.md is the package map)
