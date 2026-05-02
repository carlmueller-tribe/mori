# Mori — Claude Code Instructions

## Any task that edits the codebase MUST use this workflow

No exceptions. Every codebase change goes through a Graphite branch in a git worktree.

### Step-by-step

```bash
# 1. On main — create and track the branch with Graphite
gt sync
gt create -m "feat(scope): short description (MORI-N)"

# 2. Add a worktree for it (branch name matches what gt just created)
git worktree add .worktrees/<short-name> <branch-name>

# 3. Work inside the worktree — gt commands work because worktrees share .git
cd .worktrees/<short-name>

# 4. Commit inside the worktree using gt
gt modify -am "feat(scope): description (MORI-N)"

# 5. Submit the PR from the worktree
gt submit
```

`.worktrees/` is gitignored. Branch name comes from `gt create` output — always use `gt log` if unsure.

---

## Full implementation workflow

Every feature or bugfix follows the 9-phase process in:

> `docs/engineering/user-story-implementation-workflow.md`

**Phase order is fixed: 0 → 0.5 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8**

Key gates:
- **Phase 0 checkpoint**: confirm ticket understanding with user before writing the spec
- **Phase 1 checkpoint**: user approves the spec before writing any code
- **Phase 5 checkpoint**: user approves before committing
- **Never skip phases. Never proceed past a failure.**

---

## Validation — all must pass before committing

```bash
uv run ruff check mori/ tests/ examples/   # lint
uv run ruff format mori/ tests/ examples/  # format
uv run mypy mori/                          # strict type check (0 errors required)
uv run pytest                              # 431+ tests, 0 failures
pre-commit run --all-files                 # all hooks
```

**mypy strict mode is a hard gate.** No `# type: ignore` without an inline comment explaining why. No `SKIP=mypy` on new commits.

---

## Tooling stack

| Tool | Purpose | Config |
|------|---------|--------|
| `gt` (Graphite) | Stacked PRs, branch lifecycle | `graphite.md` |
| `pre-commit` | Runs ruff, mypy, codespell, trivy on commit | `.pre-commit-config.yaml` |
| `uv` | Package management, running tools | `pyproject.toml`, `uv.lock` |
| `mise` | Pins Python 3.11, trivy, ripgrep | `.mise.toml` |
| `commitizen` | Conventional commit enforcement | `.cz.toml` |
| Greptile | Codebase-aware PR review (runs in CI) | `.github/workflows/greptile-review.yaml` |
| Ellipsis | AI review rules for protocol/type/security | `ellipsis.yaml` |

---

## Commit message format

```
<type>(<scope>): <short description> (MORI-N)
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

Multi-line via heredoc:
```bash
gt modify -am "$(cat <<'EOF'
feat(memory): add PostgresBackend with pgvector (MORI-42)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Key source patterns

- **Optional-import guard**: `mori/model/anthropic.py`
- **Async lifecycle** (`connect`/`close`): `mori/protocols/mcp/client.py`
- **Backend protocol**: `mori/memory/backends/base.py`
- **Shared types** (check before defining new ones): `mori/types.py`
- **Package layout**: `mori-docs/specs/00-OVERVIEW.md`

---

## Branch / PR rules

- **Never push directly to `main`** — always via `gt submit`
- **Never `--no-verify`** — fix the underlying issue
- **Never `git push --force`** — use `gt` to restack instead
- **PR title** ≤ 70 chars, references MORI-N
- Draft PRs are fine; mark ready when all checks pass

---

## Environment

- Python 3.11 (pinned via mise)
- `uv sync --extra dev` to install all dev deps
- `pre-commit install` after first clone
- `gt auth` to authenticate Graphite CLI
