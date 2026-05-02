# Graphite (gt) Workflow

Mori uses [Graphite](https://graphite.dev) for branch management and PR submission. Always use `gt` instead of `git` directly for branch operations — `gt` passes through to `git` for everything else.

## Setup

```bash
# Install (one-time)
brew install withgraphite/tap/graphite

# Authenticate (one-time — requires your Graphite CLI token from graphite.dev/settings)
gt auth --token <TOKEN>

# Initialize repo (one-time, already done)
gt init

# Enable shell completions
gt completion
```

## Daily Workflow

```bash
# Sync with trunk before starting new work
gt sync

# Create a new branch from trunk
gt checkout --trunk
gt create -am "chore: scaffold MORI-N short-description"
# branch name convention: {firstname}/mori-{N}-{short-description}

# Modify and amend the current branch tip
gt modify -am "feat(module): description (MORI-N)"

# Add a new commit to the current branch
gt modify --commit -am "test(module): description (MORI-N)"

# Submit branch as a PR (creates draft by default)
gt submit

# Sync all stacked branches after upstream merges
gt sync
```

## Commit Message Format

Mori uses [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject> (MORI-N)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`, `build`

Scope: the module name (e.g., `memory`, `runtime`, `protocols`, `budget`)

## Reference

- `gt sync` — pull latest from trunk, restack all local branches
- `gt create` — create a new branch
- `gt modify` — amend the current branch tip (or `--commit` for a new commit)
- `gt submit` — push branch and open/update PR on GitHub
- `gt log` — visualize the local branch stack
- `gt checkout` — switch between branches in the stack
