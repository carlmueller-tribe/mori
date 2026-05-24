# 15: Coding Harness

**Status:** Future (post-V1, not scheduled) — current focus remains compliance
**Module:** `mori.code` (optional install: `pip install mori[code]`)
**Dependencies:** Specs 01, 02, 05, 06, 08, 10
**Last Updated:** 2026-05-23

---

## 1. Purpose

A first-class coding harness for Mori: the additional layer that turns the
governance-focused runtime into a credible substrate for *driving an LLM through
real software-engineering work* (read files, edit code, run tests, shell out)
while preserving the audit and permission story.

This spec is the future home for everything that makes Mori a viable "Claude
Code-style runtime" — and **only** that. It deliberately keeps the compliance
work in specs 06, 12, 14 unchanged. The coding harness builds on top.

The work is scoped here because:

- it's a meaningfully different use case from regulated-automation (the
  current compliance focus)
- it touches several cross-cutting upgrades that we don't want to back-port
  into the V1 specs (see §8)
- the experiment in `examples/coding_sandbox.py` proved the runtime shape can
  drive a coding loop, but the experience needs a dedicated module to be
  ergonomic

---

## 2. Why deferred

Compliance is the current product focus. Shipping the AIUC-1 primitives
(spec 12), resilience (spec 14), and the governance hardening behind them
matters more than adding a new domain module.

The coding harness is also gated on cross-cutting changes that are best made
when there is a concrete consumer pulling on them — see §8.

The coding-sandbox experiment (committed at `examples/coding_sandbox.py` and
`examples/sandbox/`) is the prior-art that motivates this spec. It shipped
*without* the work described here, because the goal was to surface gaps, not
to fill them. This spec is the result.

---

## 3. Positioning

Mori already gives a coding harness most of what it needs:

| Need | Mori today (per spec) | Status |
|---|---|---|
| Native tool registry | Spec 05 | ✓ ships |
| Permission engine + hooks | Spec 06 | ✓ ships (conditions are stubs — see §8.1) |
| Pause/resume + checkpoint | Spec 02, 07 | ✓ ships (resume semantics need work — see §8.4) |
| Structured event audit | Spec 08 | ✓ ships |
| MCP client | Spec 05 | ✓ ships |
| Budget management | Spec 09 | ✓ ships (no prompt caching — see §8.2) |

What's missing is a **library of code-aware tools, sandbox primitives, and
code-relevant guards** that consumers should not have to write themselves.
That is what `mori.code` provides.

The harness is positioned as **an optional module, not a runtime fork**. The
core runtime (Spec 02) does not learn anything about "code" or "files" or
"shell". `mori.code` is consumer-facing scaffolding built on the existing
primitives.

---

## 4. Module shape

```
mori/
└── code/                      # optional install: pip install mori[code]
    ├── __init__.py
    ├── tools/                 # native Python tools, registry-ready
    │   ├── filesystem.py      # list_files, read_file, write_file, edit_file
    │   ├── search.py          # glob, grep (ripgrep-backed)
    │   ├── shell.py           # run_bash (sandboxed)
    │   └── git.py             # git_status, git_diff (read-only)
    ├── sandbox/               # filesystem + shell isolation primitives
    │   ├── root.py            # SandboxRoot — path resolution + escape checks
    │   ├── policy.py          # default PermissionEngine policies for code tools
    │   ├── guards.py          # tool.invoke.before hooks (path, bash, dotfile)
    │   └── container.py       # Docker entrypoint helpers (optional)
    ├── memory/                # code-specific memory patterns (deferred)
    │   └── code_context.py    # file-aware retrieval, diff-aware writes
    ├── budget/                # code-specific budget configuration (deferred)
    │   └── code_slots.py      # generation/tool slot weights tuned for editing
    └── presets.py             # `CodingAgentBuilder` — opinionated convenience
```

The `presets.py` entry point lets a consumer go from nothing to a working
governed coding agent in ~10 lines:

```python
from mori.code import CodingAgentBuilder
from mori.code.sandbox import SandboxRoot

agent = (
    CodingAgentBuilder()
    .sandbox(SandboxRoot("/work/project"))
    .model("anthropic", model="claude-sonnet-4-6")
    .build()
)

result = await agent.run("Fix the failing test in tests/test_auth.py")
```

`CodingAgentBuilder` is a thin wrapper over `Mori.builder()` that
pre-registers the code tools, installs the sandbox guards, and applies the
default permission policy. Everything is still inspectable and overridable.

---

## 5. Tool surface

The tools below are the minimum viable set. They live in `mori.code.tools.*`
and register through the standard `ToolRegistry` (spec 05) — no new
registration mechanism.

### 5.1 Filesystem (`mori.code.tools.filesystem`)

| Tool | Signature | Notes |
|---|---|---|
| `list_files` | `(path: str = ".") -> str` | Returns one entry per line, with trailing `/` for directories. Resolved under sandbox root. |
| `read_file` | `(path: str) -> str` | UTF-8 only. Large files are auto-truncated with a clear marker; the model can call again with a byte range (post-MVP). |
| `write_file` | `(path: str, content: str) -> str` | Overwrite. Parent dirs created on demand. |
| `edit_file` | `(path: str, old: str, new: str) -> str` | Exact single-occurrence replace. Refuses if `old` is missing or non-unique. Same shape as Claude Code's Edit tool. |
| `delete_file` | `(path: str) -> str` | Single file only. Sub-tree deletes require escalation. |

### 5.2 Search (`mori.code.tools.search`)

| Tool | Signature | Notes |
|---|---|---|
| `glob` | `(pattern: str, path: str = ".") -> str` | `**`/`*` patterns. Results capped. |
| `grep` | `(pattern: str, path: str = ".", file_glob: str \| None = None) -> str` | ripgrep-backed when available, falls back to pure Python. Output capped, line-oriented. |

### 5.3 Shell (`mori.code.tools.shell`)

| Tool | Signature | Notes |
|---|---|---|
| `run_bash` | `(command: str, timeout_sec: int = 30) -> str` | cwd forced to sandbox root. Output capped at 8KB by default. Timeout-capped. Returns `exit_code=<n>\n<stdout+stderr>`. |

The shell tool is the riskiest. See §6.2 for the bash-guard contract.

### 5.4 Git (`mori.code.tools.git`, read-only first)

| Tool | Signature | Notes |
|---|---|---|
| `git_status` | `() -> str` | `git status --short` under sandbox cwd. |
| `git_diff` | `(path: str \| None = None) -> str` | `git diff` (working tree). Output capped. |

Write operations (`commit`, `push`, `checkout`) are **explicitly out of scope
for the initial cut** — they require escalation (Spec 06 ESCALATE) before they
can land safely. See §10.

---

## 6. Sandbox primitives

The sandbox is the heart of the harness. It is *not* an OS-level container —
it is a Mori-enforced policy boundary backed by a tmp/working directory.
Defense in depth (e.g. Docker) is the consumer's responsibility.

### 6.1 SandboxRoot

```python
class SandboxRoot:
    """A bounded filesystem region. All code tools resolve paths against this."""

    def __init__(self, root: str | Path) -> None: ...

    def resolve(self, raw: str) -> Path:
        """Resolve a user-supplied path under root.

        Raises SandboxEscape if the resolved path is not equal to or under root
        (after symlink expansion via .resolve()).
        """

    @property
    def root(self) -> Path: ...
```

`SandboxRoot.resolve()` is the single point of truth for "is this path in
bounds". All filesystem tools call it. The bash guard uses it to validate
absolute-path tokens before subprocess spawn.

`SandboxEscape` is a subclass of `ValueError` so tools that don't go through
hooks can still surface it as a tool error.

### 6.2 Sandbox guards

Two `tool.invoke.before` hooks ship with the harness:

```python
# mori.code.sandbox.guards

async def validate_paths(call: ToolCall) -> ToolCall | None:
    """Block any path arg that resolves outside SandboxRoot. Raises HookBlock."""

async def guard_bash(call: ToolCall) -> ToolCall | None:
    """Block dangerous shell patterns and absolute-path tokens outside sandbox.

    Default denylist:
      - rm -rf /
      - sudo, su -
      - curl|sh, wget|sh
      - ssh, scp, nc
      - paths under /etc, ~/.ssh, .env
      - git push (any), docker (any)
      - fork-bomb pattern
    """
```

Both are registered at `priority=1` so they fire ahead of consumer-defined
hooks. Consumers can extend the denylist by passing a `SandboxConfig`:

```python
agent = (
    CodingAgentBuilder()
    .sandbox(SandboxRoot("/work/project"))
    .sandbox_config(bash_deny_patterns=[r"\bpypi\.org\b"])  # block PyPI uploads
    .build()
)
```

### 6.3 Default permission policy

`mori.code.sandbox.policy.default_policy()` returns a `PermissionEngine`
pre-loaded with:

- read tools (`list_files`, `read_file`, `glob`, `grep`, `git_status`,
  `git_diff`) → **allow**
- write tools (`write_file`, `edit_file`) → **allow**
- destructive tools (`delete_file`) → **escalate**
- shell (`run_bash`) → **allow** with guard active
- writes to dotfiles (matched in the path validator) → **deny**

The default is overridable. The compliance-oriented case (an agent that may
only *read* code, never write) is satisfied by `default_policy(read_only=True)`.

---

## 7. Code-specific extensions

Items that are scoped here but **explicitly deferred** until the §8
prerequisites land.

### 7.1 Code-aware memory (post-MVP)

`mori.code.memory.code_context` would provide:

- A retrieval pattern that loads "the file at line N" alongside semantic
  matches, so the model gets the surrounding code without an extra
  `read_file` call.
- A diff-aware write pattern that records *what changed* (not just what was
  written) in the episodic layer for replay and audit.

Both depend on the memory module (spec 03) gaining range-typed records,
which is a separate change.

### 7.2 Code-aware budget (post-MVP)

Coding loops have a different token distribution from chat or task agents:

- Tool results (file contents, test output) dominate
- The generation slot stays small; the result slot stays large
- Compaction needs to keep recent diffs over old reads

`mori.code.budget.code_slots` provides a `BudgetConfig` preset with the right
slot weights. This is a small addition once Spec 09's BudgetManager is stable.

### 7.3 Cancel + streaming surfaces (cross-cutting — see §8.3 & §8.5)

Both are dependencies, not coding-specific features.

---

## 8. Cross-cutting prerequisites

These are the upstream changes required before the coding harness can ship.
They are listed here because the coding harness is the concrete consumer that
forces them — but they are general improvements that other modules will also
benefit from.

### 8.1 Permission Engine: implement condition evaluation (extends Spec 06)

`PermissionRule.conditions` is currently a stub (`_conditions_match` returns
`True` unconditionally — see `mori/permission/engine.py:282`). Real
evaluation is needed so policy can express:

- *"allow `write_file` if path matches `**/*.py`"*
- *"escalate `run_bash` if command matches `^(rm|mv)\b`"*
- *"deny `read_file` if path matches `**/.env*`"*

Without this, every coding agent re-implements the same path-scoped logic in
ad-hoc hooks. The condition vocabulary should cover:

- Path glob match (new `ConditionType.PATH_GLOB`)
- Argument regex match (new `ConditionType.ARG_MATCHES`)
- Existing types (step count, token total, time of day) already in the type
  surface; they just need evaluators.

This is one of the larger pieces — a separate PR-shaped change to spec 06.

### 8.2 Anthropic adapter: prompt caching (extends Spec 05 / Spec 10)

Coding loops accumulate large system prompts, full tool definitions, and a
growing conversation tail. Without prompt caching, every step pays the full
input cost.

`AnthropicAdapter` needs to mark cacheable blocks via `cache_control:
{"type": "ephemeral"}`. The reasonable cache surface:

1. System prompt
2. Tool definitions block
3. Long-stable conversation prefix (everything up to the most recent
   assistant turn)

Documented behavior: caching is on by default for Anthropic; opt-out via
`AnthropicAdapter(prompt_caching=False)`.

Expected impact: 5-10× cost and latency improvement on multi-step coding
loops.

### 8.3 Runtime: expose streaming through `agent.run` (extends Spec 02)

`ModelAdapter.stream()` exists at the adapter layer. The runtime never
exposes it. For a coding harness to drive a UI, `agent.run()` (or a new
`agent.stream()`) needs to yield typed events as they happen:

- Token deltas from the model
- Tool-call start/finish
- Permission decisions
- Hook activations

The event taxonomy (Spec 08) already supports this — what's missing is the
plumbing that lets a consumer subscribe. Either:

- An additional `async def stream()` that yields `MoriEvent` instances
- An event-bus protocol so consumers can attach a sink at call time, not just
  build time

### 8.4 HITL resume: support direct tool-call approval (extends Spec 02)

Today, `loop.resume(thread_id, input={"approved": True, ...})` appends a
`[Resume] Approved` user message and relies on the model re-issuing the same
tool call. This is brittle in production (the model can drift; the step
counter keeps incrementing across resumes — confirmed during the
master-example experiment).

The cleaner shape:

- `state.paused_tool_call` is already preserved on escalate
- `loop.resume(thread_id, approve_tool_call=True)` executes the preserved
  call directly without re-prompting the model
- `loop.resume(thread_id, reject_tool_call=True, feedback="...")` injects a
  tool error result so the model can adapt

This eliminates a model round-trip per approval, removes the drift surface,
and keeps the step counter honest.

### 8.5 Cancel / interrupt (extends Spec 02)

A coding harness needs Ctrl-C with graceful tool rollback. The README
mentions `cancel()` but it doesn't exist in the runtime today. Required:

- `agent.cancel(thread_id)` triggers an `asyncio.CancelledError` inside the
  loop
- The current in-flight tool gets a configurable amount of time to finish
  before its task is cancelled
- A `run.cancel` observability event closes the audit trail cleanly
- `RunResult.status = RunStatus.CANCELLED` becomes a thing

### 8.6 RunResult: surface `paused_reason` (extends Spec 02)

Today `RunResult` drops `paused_reason` — callers can't tell escalate-pause
from ask_user-pause without poking at `MoriState`. A simple addition:

```python
class RunResult(MoriModel):
    ...
    paused_reason: str | None = None  # mirrors MoriState.paused_reason
```

Trivial change. The other items above subsume it.

### 8.7 Policy mutation: public setter (extends Spec 06)

`examples/governance.py` and `examples/mori_master.py` both use
`agent._loop._permission = engine` to swap policies after approval. This is
private API. A public setter (or a `loop.update_policy(engine)`) is needed
for any non-toy HITL workflow.

---

## 9. Plugin vs in-tree

`mori.code` ships **in-tree as an optional module**, installable via
`pip install mori[code]`. Rationale:

- Tight coupling to the core type surface — the tools use `ToolCall`,
  `ToolResult`, `PermissionRule` directly; the guards use `HookBlock`. An
  out-of-tree plugin has the same surface area but a worse release story.
- The default permission policy and sandbox guards are likely to evolve
  alongside the engine's condition vocabulary (§8.1) — staying in-tree avoids
  versioning the two against each other.
- Optional install via `[code]` extras keeps the dependency footprint small
  for consumers that don't need it.

Out-of-tree plugins remain the right pattern for *consumer-specific* code
agents (a company's "fix-the-CI-bot" or "auto-PR-reviewer"). Those compose
the in-tree `mori.code` primitives with their own tools and policy.

---

## 10. Non-goals (explicit deferrals)

The first cut of `mori.code` **does not** ship:

| Item | Why not |
|---|---|
| Git write operations (commit, push, checkout) | Needs ESCALATE semantics + a clear human-in-the-loop story. Lands after §8.4 is done. |
| Multi-file refactor primitive | Hard to specify without a real consumer. Out of scope until 2 production users exist. |
| Browser/screenshot tools | Wider scope; lives in a hypothetical `mori.browser` later. |
| IDE/LSP integration | Out of scope. MCP is the integration path (Spec 05). |
| Built-in OS sandbox (sandbox-exec, namespaces) | Defense in depth is the consumer's job. The harness provides path/bash guards; OS isolation is orthogonal. |
| Multi-agent / sub-agent dispatch | If wanted, lives in a separate spec under the A2A umbrella. |
| Test runner abstraction | `run_bash("pytest -x")` is enough. Don't invent a runner. |

---

## 11. Validation / acceptance

A shippable `mori.code` MVP satisfies:

1. `pip install mori[code]` succeeds and `CodingAgentBuilder` is importable.
2. The fizzbuzz experiment in `examples/coding_sandbox.py` runs unchanged on
   top of `mori.code` (all custom code replaced with module imports).
3. Adversarial prompts cannot escape the sandbox without an explicit policy
   override:
   - `read_file("/etc/hosts")` → HookBlock from `validate_paths`
   - `run_bash("rm -rf /")` → HookBlock from `guard_bash`
   - `run_bash("git push origin")` → HookBlock
   - `write_file(".env", ...)` → DENY from default policy
4. The audit trail captures every block, with reason and matched rule/pattern.
5. With prompt caching enabled (§8.2), a 10-step coding loop costs ≤ 25% of
   the same loop without caching.
6. A coding agent paused on `delete_file` can resume via direct tool-call
   approval (§8.4) without a model round-trip.

---

## 12. References

- `examples/coding_sandbox.py` — the prior-art experiment that motivated this
  spec. Demonstrated that the runtime can drive a coding loop and surfaced
  the gaps now listed in §8.
- `examples/sandbox/` — Docker harness that the coding experiment ran under;
  provides a model for the optional `mori.code.sandbox.container` helpers.
- `examples/mori_master.py` — the governance master example that validated
  the audit/HITL story this spec builds on top of.
- Spec 05 (Tools and Protocols) — the tool registry this spec extends.
- Spec 06 (Permission Engine) — the policy substrate; §8.1 calls out the
  condition-evaluation gap.
- Spec 08 (Observability) — the audit trail the experiment report consumes.
- Spec 12 (AIUC-1 Compliance) — the primary product focus; this spec is
  **explicitly downstream of compliance work** and does not block it.
- Spec 14 (Resilience) — Temporal-backed durability; orthogonal to the coding
  harness but a natural pairing for long-running coding agents.

---

## 13. Open questions

| # | Question | Notes |
|---|---|---|
| Q1 | Should `mori.code.tools.shell` ship a Docker-aware variant out of the box? | The current `examples/sandbox/` shows the pattern but it's not packaged. Possible add-on once one production consumer pulls. |
| Q2 | How does `mori.code` interact with Spec 04 (Skills)? Should there be skill artifacts for common refactors? | Tabled until skills module is stable. |
| Q3 | Does the harness expose its own AIUC-1-style attestation (since coding is a higher-risk surface)? | Probably yes — coding-specific event subtypes + an analogue of `EvidenceExporter`. Scoped here once spec 12 lands. |
| Q4 | Should `edit_file` support multi-replace via a list arg, or stay single-occurrence? | Lean toward single-occurrence for predictability; revisit after consumer feedback. |
