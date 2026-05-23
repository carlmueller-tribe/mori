# AGENTS.md

This file provides guidance for agents when working with code in this repository.

## Development Commands

### Setup

```bash
uv sync --extra dev      # install all dependencies
pre-commit install       # install git hooks
gt auth                  # authenticate Graphite CLI (one-time)
mise install             # install pinned tool versions (Python 3.11, trivy, ripgrep)
```

### Core checks

```bash
mise run check                             # lint + typecheck + tests + trivy (one command)
```

Or individually:

```bash
uv run ruff check mori/ tests/ examples/   # lint
uv run ruff format mori/ tests/ examples/  # format
uv run mypy mori/                          # strict type check — 0 errors required
uv run pytest                              # full test suite
mise run trivy:scan                        # HIGH/CRITICAL vuln scan against uv.lock
pre-commit run --all-files                 # all pre-commit hooks
```

---

## Development Flow

For **any task that edits the codebase**, follow this exact flow. No exceptions.

### 1. Create a branch and worktree

```bash
# On main — Graphite creates and tracks the branch
gt sync
gt create -m "feat(scope): short description (MORI-N)"

# Add an isolated worktree for it
git worktree add .worktrees/<short-name> <branch-name>

# All remaining work happens inside the worktree
cd .worktrees/<short-name>
```

`.worktrees/` is gitignored. Use `gt log` to confirm the branch name.

### 2. Implement, then validate

```bash
# run all checks — repeat until all pass
mise run check                                    # lint + typecheck + tests + trivy
uv run ruff check mori/ tests/ examples/ --fix   # auto-fix ruff violations if needed
pre-commit run --all-files                        # full hook suite
```

**STOP on any failure** — fix the root cause before proceeding. Never use `--no-verify`.

### 3. Commit and submit

```bash
# commit inside the worktree
gt modify -am "feat(scope): description (MORI-N)"

# open/update PR on GitHub
gt submit
```

Never push directly to `main`. Never `git push` — always `gt submit`.

---

## Stacking strategy

Each superpowers implementation task maps to a **branch in a stack**. Graphite stacks branches on top of each other, each targeting its parent as the base.

```
main
 └── feat/mori-42-postgres-schema      ← models + migration
      └── feat/mori-42-postgres-search ← pgvector retrieval
           └── feat/mori-42-postgres-tests ← integration tests
```

**Default rule**: one branch per task (data model, search logic, tests, docs).

**Exception**: if the entire ticket is a small, naturally atomic change (≤ 3 files, one concern), use a single branch.

Submit the full stack at once:

```bash
gt submit --stack
```

Graphite creates one PR per branch, each with a focused diff.

---

## Full implementation workflow

Every feature or bugfix follows the 9-phase process:

> `docs/engineering/user-story-implementation-workflow.md`

**Phase order is fixed: 0 → 0.5 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8**

| Phase | Name | Gate |
|-------|------|------|
| 0 | Validation & Setup | Confirm understanding with user |
| 0.5 | Spec Step | Write design doc before any code |
| 1 | Planning Checkpoint | User approves spec |
| 2 | Implementation | Follow the spec |
| 3 | Testing & Validation | ruff ✓, mypy ✓, pytest ✓, pre-commit ✓ |
| 4 | Code Quality | Pattern consistency, spec compliance |
| 5 | Pre-Push Validation | User approves before committing |
| 6 | Commit & Push | `gt modify` + `gt submit` |
| 7 | Pull Request | `gt submit` (PR per stack layer) |
| 8 | Linear Comments | Comment at end of every phase |

See [`docs/engineering/spec-driven-workflow-walkthrough.md`](docs/engineering/spec-driven-workflow-walkthrough.md) for a full worked example.

---

## Project architecture

```
mori/               # library source (organized by spec module)
├── types.py        # shared types — check here before defining new ones
├── model/          # model adapters (AnthropicAdapter, etc.)
├── memory/         # memory backends, embedder, retrieval, module
├── runtime/        # AgentLoop, MoriState, RunResult
├── tools/          # ToolRegistry, schema, CLI/MCP protocols
├── skills/         # SkillModule, registry, parser
├── observability/  # ObservabilityEngine, events, sinks
├── budget/         # BudgetManager, types
├── control/        # ControlBounds, checkpoint
├── permission/     # PermissionEngine, types
└── hooks/          # HookRegistry, types
tests/              # flat — one file per module
examples/           # runnable usage examples
mori-docs/specs/    # library design specs (00-OVERVIEW.md is the package map)
docs/engineering/   # development workflow guides
```

### Key patterns (read these before implementing)

- **Optional-import guard**: `mori/model/anthropic.py`
- **Async lifecycle** (`connect`/`close`/`__aenter__`/`__aexit__`): `mori/protocols/mcp/client.py`
- **Backend protocol**: `mori/memory/backends/base.py`
- **Package layout**: `mori-docs/specs/00-OVERVIEW.md`

---

## Relevant configuration files

| File | Purpose |
|------|---------|
| `pyproject.toml` | ruff rules, mypy config, pytest config, dependencies |
| `.pre-commit-config.yaml` | hook definitions (ruff, mypy, codespell, trivy) |
| `.mise.toml` | pins Python 3.11, trivy 0.69.3, ripgrep 14.1.1 |
| `.cz.toml` | commitizen semver config |
| `ellipsis.yaml` | AI review rules (protocol conformance, type safety, security) |
| `graphite.md` | `gt` workflow reference |
| `uv.lock` | pinned dependency lockfile — commit changes to this |

---

## Secrets and `.env`

`.env` does NOT contain raw secrets. It contains 1Password references:

```
ANTHROPIC_API_KEY="op://Employee/ANTHROPIC_API_KEY/credential"
```

Run examples through the wrapper so `op` resolves references at process start
and secrets never touch disk:

```bash
examples/run-with-op.sh examples/basic_agent.py
```

The wrapper is just `op run --env-file=./.env -- uv run python "$@"`.

If `python-dotenv` loads `.env` directly (no `op run`), the literal `op://...`
string becomes the API key and the call will fail with an auth error — that is
expected. Always go through `op run` (or the wrapper) for any example that
needs a real model call.

First-time setup:

```bash
brew install 1password-cli   # if not already installed
op signin                    # sign into Tribe's 1Password account
```

---

## Dependency policy

New dependencies must go through a PR — never add deps directly on `main`. This ensures lockfile diffs are reviewed before reaching other developers.

```bash
# add to pyproject.toml, then regenerate the lockfile
uv add <package>           # core dep
uv add --dev <package>     # dev dep
```

---

## 🚫 Team rule: never run `git` directly — always run `gt` instead

See [`graphite.md`](graphite.md) for full guidance on the Graphite CLI (`gt`) for branch management and stacked PRs.

Exception: `git worktree add/remove` and `git push origin main` (trunk sync only) are fine to run directly.

---

## Commit message format

```
<type>(<scope>): <short description> (MORI-N)
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

Multi-line:

```bash
gt modify -am "$(cat <<'EOF'
feat(memory): add PostgresBackend with pgvector (MORI-42)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## mypy strict mode

mypy strict is a hard gate on every commit. Rules:

- 0 errors required — pre-commit hook will block the commit otherwise
- No `# type: ignore` without an inline comment explaining why
- Optional third-party imports use the guard pattern in `mori/model/anthropic.py`
- Missing stubs → add the module to `[[tool.mypy.overrides]]` in `pyproject.toml`
