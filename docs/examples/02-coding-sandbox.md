# 02 — Coding Sandbox: Mori Driving a Real Code-Editing Loop

> **TL;DR.** A real Claude Haiku model is given five filesystem/shell tools
> (`list_files`, `read_file`, `write_file`, `edit_file`, `run_bash`) inside a
> Docker sandbox, and asked to fix a deliberately broken `fizzbuzz.py`. It
> succeeds in **six steps, ~9 seconds, ~12K tokens** — read the test, read
> the source, run pytest to confirm the failure, edit the bug, run pytest
> again to confirm the fix, and write a clean summary. Full audit trail
> captured. All five Mori governance primitives were in line and ready; on
> the happy path, none had to fire.

**File:** [`examples/coding_sandbox.py`](../../examples/coding_sandbox.py)
**Container:** [`examples/sandbox/Dockerfile`](../../examples/sandbox/Dockerfile)
+ [`examples/sandbox/run-sandbox.sh`](../../examples/sandbox/run-sandbox.sh)
**Seed project:** [`examples/sandbox/seed/`](../../examples/sandbox/seed/)
**Runs in:** a Docker container; needs a 1Password-backed Anthropic API key.

---

## Why this experiment exists

The [master example](01-mori-master-example.md) proves Mori's governance is
real when the workload is well-scripted and the policy is the star. The
question this experiment answers is whether Mori's *primitives* (tool
registry, hooks, permissions, observability) can also drive **open-ended
code work** — the kind of thing Claude Code does. If they can, Mori has a
realistic path to becoming a coding harness. If they can't, we learn where
the gaps are.

This is an honest experiment. The goal is to surface gaps, not to ship a
product. Both the things that worked and the things that didn't end up
recorded — the latter in [Spec 15: Coding Harness](../../mori-docs/specs/15-CODING-HARNESS.md).

## What "sandbox" means here

Three layers of isolation:

1. **Docker container** — `python:3.11-slim` with non-root `agent` user, no
   privileged caps, no special device access. Repo is mounted read-only at
   `/mori-src`; a scratch directory is mounted writable at `/sandbox`.
2. **`SANDBOX_ROOT` path resolution** — every file tool resolves user-supplied
   paths against `/sandbox/project/` and rejects anything that escapes after
   symlink expansion.
3. **`tool.invoke.before` hooks** — two of them. `validate_paths` blocks any
   path arg that resolves outside the sandbox. `guard_bash` denies a
   regex-pattern denylist for shell commands and rejects absolute-path tokens
   that aren't under sandbox.

The Docker container is the *outermost* layer (honest-mistake-grade for the
host). The path validator and bash guard are the *Mori-native* defenses —
the ones being tested. Defense in depth, but the experiment is about the
middle and inner layers.

## The seed workload

```
examples/sandbox/seed/
├── README.md           # tiny description
├── fizzbuzz.py         # has a bug: returns "Buzz" for multiples of 3
└── test_fizzbuzz.py    # 10 parametrized tests that fail until the bug is fixed
```

The bug is on line 18 of `fizzbuzz.py`:

```python
if n % 3 == 0:
    return "Buzz"  # BUG: should be "Fizz"
```

## How to run it

```bash
examples/sandbox/run-sandbox.sh
```

What the launcher does:

1. Creates a fresh `/tmp/mori-sandbox-XXXX/` and copies the seed project into
   `/tmp/mori-sandbox-XXXX/project/`.
2. Builds the Docker image if it isn't cached (`mori-coding-sandbox`).
3. Resolves `ANTHROPIC_API_KEY` via 1Password (`op run --env-file .env`) so
   the key is never on disk.
4. Runs the container with the repo bind-mounted read-only, the scratch dir
   bind-mounted writable, and the API key passed as an env var to the
   process.
5. On exit, prints the scratch dir path so you can inspect the diff and the
   audit log.

## What the run looked like

### Live event stream (full)

```
========================================================================
  CODING AGENT — fizzbuzz fix
========================================================================

  [mori] run.start RUN   → "You're a coding agent. The project at your current directory has a failing test."
  [mori] ─── step 1 (plan) ───
  [mori] ACT   → list_files({'path': '.'}) [native]
  [mori]        ✓ list_files: README.md
                              fizzbuzz.py
                              test_fizzbuzz.py
  [mori] ─── step 2 (plan) ───
  [mori] ACT   → read_file({'path': 'test_fizzbuzz.py'}) [native]
  [mori]        ✓ read_file: """Tests for fizzbuzz.py."""...
  [mori] ACT   → read_file({'path': 'fizzbuzz.py'}) [native]
  [mori]        ✓ read_file: """FizzBuzz with a deliberate bug for the agent to fix."""...
  [mori] ─── step 3 (plan) ───
  [mori] ACT   → run_bash({'command': 'pytest -x'}) [native]
  [mori]        ✓ run_bash: exit_code=1  (test failure output)
  [mori] ─── step 4 (plan) ───
  [mori] ACT   → edit_file({'path': 'fizzbuzz.py',
                            'old':  '    if n % 3 == 0:\n        return "Buzz"  # BUG: should be "Fizz"',
                            'new':  '    if n % 3 == 0:\n        return "Fizz"'}) [native]
  [mori]        ✓ edit_file: edited fizzbuzz.py (replaced 1 occurrence)
  [mori] ─── step 5 (plan) ───
  [mori] ACT   → run_bash({'command': 'pytest -x'}) [native]
  [mori]        ✓ run_bash: exit_code=0  (10 passed)
  [mori] ─── step 6 (plan) ───
  [mori] EVAL  → success
  [mori] DONE  → completed in 6 steps, 12332 tokens, 8968ms
```

### Final model output

```
Perfect! All tests pass now.

## Summary

**The Bug:** In `fizzbuzz.py`, the function was returning `"Buzz"` for
multiples of 3, when it should return `"Fizz"`.

**The Fix:** Changed line 18 from:
```python
return "Buzz"  # BUG: should be "Fizz"
```
to:
```python
return "Fizz"
```

This ensures that numbers divisible by 3 (but not 15) correctly return
"Fizz", while the check for multiples of 15 (which should return "FizzBuzz")
happens first and takes precedence. All 10 tests now pass.
```

### Experiment report

```
========================================================================
  EXPERIMENT REPORT
========================================================================
  final status:       completed
  audit events:       38
  permission checks:  6
  tool invocations:   6
  path-validator blocks: 0
  bash-guard blocks:     0
  bash commands run:     2
  totals:  steps=6  tokens_in=11621  tokens_out=711  duration=8968ms

  ── Tool call sequence ──
    ✓ list_files      {path=.}                                              (1ms)
    ✓ read_file       {path=test_fizzbuzz.py}                               (3ms)
    ✓ read_file       {path=fizzbuzz.py}                                    (1ms)
    ✓ run_bash        {command=pytest -x}                                   (201ms)
    ✓ edit_file       {path=fizzbuzz.py, old="...return Buzz...", new="...return Fizz"}  (1ms)
    ✓ run_bash        {command=pytest -x}                                   (193ms)
```

### The diff the model produced

```diff
@@ -17,7 +17,7 @@
     if n % 15 == 0:
         return "FizzBuzz"
     if n % 3 == 0:
-        return "Buzz"  # BUG: should be "Fizz"
+        return "Fizz"
     if n % 5 == 0:
         return "Buzz"
     return str(n)
```

Note: the model removed the now-outdated `# BUG: should be "Fizz"` comment in
the same edit. A small detail that demonstrates the model is reasoning about
the code, not just satisfying the test.

## What this proves about Mori

The runtime, tool plumbing, and primitives can drive a real coding loop:

| Pillar | Outcome |
|---|---|
| **Tool plumbing** | Schema inference, registry, model-side tool definitions, result routing — all worked, no special config. |
| **Permission engine** | Fired 6 times, all `allow` under the policy. No spurious denials, no false positives. |
| **Audit trail** | 38 events captured across 8 event types: `run.start`, `step.start/end`, `tool.invoke/result`, `permission.check`, `budget.rebalance`, `run.end`. Full round-trip recoverable from disk. |
| **Anthropic adapter** | Handled the tool-use loop correctly end-to-end with the real API. |
| **Sandbox boundaries** | The model stayed in-bounds. (Whether this means the guards work or that the model behaved itself is the question the [adversarial experiments](03-adversarial-experiments.md) answer.) |

## What this experiment does *not* prove

Four important caveats:

1. **The guards never fired.** The path validator and bash guard were in
   line, but the model didn't try anything that would have tripped them. This
   is "the lock is closed" but not "the lock works under attack."

2. **One small task, one file.** No multi-file refactor, no dependency
   understanding, no test-driven development workflow.

3. **No HITL escalation.** All policy was `allow` — the
   pause/resume/approval flow is exercised in the [master example](01-mori-master-example.md),
   not here.

4. **Six steps is easy.** On a 30-step debugging session, prompt caching
   matters (Mori's Anthropic adapter doesn't have it yet — Spec 15 §8.2)
   and the step counter behavior across resumes gets ugly.

## Verdict

The runtime, tool registry, hooks, permissions, and audit are all working
together — **the harness shell is there**. What's missing for "Claude Code
replacement" is:

1. A library of code-aware tools (Glob, Grep, multi-file edit, streaming Bash,
   MCP integration). That's [Spec 15 §5](../../mori-docs/specs/15-CODING-HARNESS.md#5-tool-surface).
2. Prompt caching in the Anthropic adapter.
3. Streaming exposed through the runtime so the UI sees tokens as they emit.
4. An adversarial test for the guards. (Done — see [03](03-adversarial-experiments.md).)
5. Permission engine condition evaluation so path-scoped rules can live in
   policy rather than ad-hoc hooks.

That's the gap between "this experiment passed" and "we'd ship this as a
coding harness" — and it's the gap Spec 15 enumerates concretely.

## See also

- [03 — Adversarial Experiments](03-adversarial-experiments.md) — the same
  harness, with the model instructed to misbehave.
- [Spec 15: Coding Harness](../../mori-docs/specs/15-CODING-HARNESS.md) — the
  post-V1 module that addresses every gap surfaced here.
