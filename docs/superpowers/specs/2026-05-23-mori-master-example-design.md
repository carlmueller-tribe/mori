# Mori Master Example — Design

**Status:** Approved
**Date:** 2026-05-23
**Author:** Carl Mueller (with Claude)
**Target file:** `examples/mori_master.py`

---

## 1. Goal

Ship a single, runnable example that demonstrates *every* governance, compliance, and audit primitive Mori provides — woven into one realistic scenario. Existing examples each show one pillar (`governance.py`, `hooks_block.py`, `observability.py`, `metrics_and_limits.py`). The master example shows them working together against a domain where this composition is actually necessary.

Success criteria:

1. Runs deterministically with `examples/run-with-op.sh examples/mori_master.py` — or `python examples/mori_master.py` without any secrets, because the model adapter is mocked.
2. All five governance branches fire on every run: an **allow**, a **redaction guard**, a **denial**, an **escalation**, and a **resume after human approval**.
3. After the runs complete, prints two artifacts derived from the audit trail: a structured **evidence pack** and a human-readable **narrative**.
4. Total length under ~400 lines of Python, single file, no new dependencies.

---

## 2. Scenario

A `legal-review-bot` reviews vendor contract `AC-2024-117` and produces redlines. The work is supervised by a named attorney (`approved_by` is captured in HITL events). The example is the script a compliance officer would point at to demonstrate how the firm's automated legal review survives audit.

Why legal contract review: it is natively governance-shaped — privileged content must never leave the firm, value thresholds drive partner approval, signing authority is reserved for humans, and every action needs chain of custody for malpractice and regulatory defense. The same Mori primitives that satisfy those legal needs satisfy SOX, HIPAA, and GDPR equivalents — legal just makes the *why* the most concrete.

---

## 3. Components exercised

| Pillar | Component | Configuration |
|---|---|---|
| Identity | `Identity(id="agent:legal-review-bot", type=AGENT, name="legal-review-bot", group="legal-automation")` | Passed to builder via `.identity(...)` |
| Permission policy | `PermissionEngine` with rules in §4 | Installed onto `agent._loop._permission` after build (matches `governance.py` pattern) |
| Hook — privileged-language redactor | `tool.invoke.before`, priority 1 | Strips `[PRIVILEGED]` / `attorney-client` content from args; logs `guard.redaction` |
| Hook — external-send confidentiality guard | `tool.invoke.before`, priority 2 | Raises `HookBlock` on `send_to_counterparty` if args contain `[INTERNAL ONLY]` |
| Hook — run-end audit closer | `run.end` | Appends a synthetic closing event for the narrative renderer |
| Control bound | `.config(max_steps=8)` | Bounded execution, surfaces in evidence pack |
| Budget | `.budget(total_context_tokens=50_000)` | Configured, surfaces in evidence pack |
| Checkpointer | `.checkpointer("inmemory")` | Required for escalation pause/resume |
| Observability | `.sink("stdout")` + `.sink("jsonl", path="audit.jsonl")` | All events captured |
| HITL | `agent.resume(thread_id, input={"approved": True, "approved_by": "...", "matter": "..."})` | Standard pattern from `governance.py` |

---

## 4. Permission policy

Loaded onto the agent after `build()`, using `PermissionEngine.load_rules(...)`. Rules in priority order (higher priority wins; deny-wins on ties):

| # | Resource | Permission | Effect | Why |
|---|---|---|---|---|
| 1 | `tool:execute_contract` | `--x` | **deny** | Signing authority is reserved for humans |
| 2 | `tool:propose_redline` (when `value_usd > 250_000`) | `--x` | **escalate** | Above-threshold redlines need partner approval |
| 3 | `tool:send_to_counterparty` | `--x` | **escalate** | Any external transmission needs human sign-off |
| 4 | `tool:propose_redline` | `--x` | **allow** | Below-threshold redlines are within agent authority |
| 5 | `tool:read_contract` | `r-x` | **allow** | Read is fine |
| 6 | `tool:ask_user` | `r-x` | **allow** | Native HITL must always be available |

Conditional rules (rule 2) use the Permission Engine's argument-aware matching. If the engine does not support arg-conditional rules out of the box, the same effect is achieved with a `tool.invoke.before` hook that raises `HookEscalate` when `value_usd > 250_000` — to be confirmed during implementation. The audit story is identical either way.

---

## 5. Tools

All defined inline as plain Python functions (deterministic, no I/O). Their return strings are written to feel like real legal-system responses so the audit trail reads convincingly.

```python
def read_contract(contract_id: str) -> str:
    """Read a contract from the contract management system."""
    # returns a hardcoded contract body for AC-2024-117 with two clauses

def propose_redline(contract_id: str, clause: str, rationale: str, value_usd: float) -> str:
    """Propose a redline (suggested edit) to a contract clause."""
    # returns a confirmation string with redline ID

def send_to_counterparty(contract_id: str) -> str:
    """Send the current contract draft to the counterparty's counsel."""
    # returns a confirmation with send timestamp

def execute_contract(contract_id: str) -> str:
    """Execute (sign) the contract. Reserved for humans."""
    # should never actually run — policy denies before invocation
    return "EXECUTED"   # but unreachable
```

---

## 6. Deterministic 5-act arc

The mocked model adapter (same pattern as `governance.py`) returns a scripted sequence of `ModelResponse` objects so the agent walks the arc identically every time.

| Act | Model decision | Expected runtime behavior |
|---|---|---|
| 1 | Tool call: `read_contract("AC-2024-117")` | Permission allow → tool runs → result fed back |
| 2 | Tool call: `propose_redline(contract_id="AC-2024-117", clause="indemnity", rationale="cap at 1x fees. [PRIVILEGED] internal strategy: ...", value_usd=50_000)` | Redactor hook strips `[PRIVILEGED] ...` from args → emits `guard.redaction` → tool runs with sanitized args → allowed |
| 3 | Tool call: `execute_contract("AC-2024-117")` | Permission **deny** → tool not invoked → denial returned to model → `permission.deny` event |
| 4 | Tool call: `propose_redline(..., value_usd=500_000)` | Permission **escalate** → run pauses → `RunStatus.PAUSED` returned with `paused_prompt` and `checkpoint_id` |
| 5a | (After `agent.resume(...)`) Tool call: `send_to_counterparty("AC-2024-117")` | Permission **escalate** → pauses again |
| 5b | (After second resume) Plain assistant message: "Redlines posted and sent. Awaiting counterparty response." | `RunStatus.COMPLETED` |

Each `ModelResponse` is hand-authored in the script. Token counts are realistic-ish but small.

---

## 7. Post-run artifacts

After both runs complete, the script reads `audit.jsonl` back from disk and renders two outputs.

### 7.1 Evidence pack (structured, printed to stdout)

A section-by-section dump:

```
═══ COMPLIANCE EVIDENCE PACK ═══
Matter:           AC-2024-117
Agent identity:   agent:legal-review-bot (group: legal-automation)
Bounds in effect: max_steps=8, token_budget=50000
Run window:       14:03:17.221Z → 14:03:22.844Z (wall: 5.62s, model time: 1.21s)

── Permission decisions ──
  ✓ allow     tool:read_contract           rule#5  identity=agent:legal-review-bot
  ✓ allow     tool:propose_redline         rule#4  (value=$50,000)
  ✗ DENY      tool:execute_contract        rule#1  reason="signing reserved for humans"
  ⚠ escalate  tool:propose_redline         rule#2  (value=$500,000)
  ✓ allow     tool:propose_redline         rule#4  (post-approval, approved_by=carl.mueller@tribe.ai)
  ⚠ escalate  tool:send_to_counterparty    rule#3
  ✓ allow     tool:send_to_counterparty    rule#3  (post-approval, approved_by=carl.mueller@tribe.ai)

── Guard activations (1) ──
  redaction   tool:propose_redline  step 2  matched=[PRIVILEGED]  bytes_removed=58

── Human approvals (2) ──
  14:03:21Z  carl.mueller@tribe.ai  approved propose_redline (value=$500,000)  matter=AC-2024-117
  14:03:22Z  carl.mueller@tribe.ai  approved send_to_counterparty               matter=AC-2024-117

── Tool invocations (4) ──
  step 1  read_contract        (allowed)   12ms
  step 2  propose_redline      (allowed, args redacted)  18ms
  step 4  propose_redline      (allowed after escalation)  17ms
  step 6  send_to_counterparty (allowed after escalation)  41ms

── Run totals ──
  steps: 7   tool_calls: 4   model_calls: 5   tokens_in: 125   tokens_out: 47

── AIUC-1 mapping ──
  B006 unauthorized actions      ✓ 1 deny logged with matching rule
  D003 unsafe tool calls         ✓ all invocations schema-validated, denials recorded
  E004 accountability            ✓ 2 named human approvals captured
  E015 model activity logged     ✓ 5 model invocations with token accounting
```

The pack is built by iterating `audit.jsonl`, bucketing events by type, and formatting. No model involvement — the renderer is pure Python over the event stream.

### 7.2 Narrative (prose, printed to stdout)

A second pass over the same events produces a human-readable account suitable for pasting into a compliance memo. Formal but plain — not legalese, not chatty. Times are sourced from event timestamps, identities from event fields, dollar values from tool arguments. The renderer is deterministic.

```
═══ NARRATIVE ═══

At 14:03:17 UTC, agent legal-review-bot opened matter AC-2024-117 under
attorney supervision (group: legal-automation). The agent's authority was
bounded at 8 reasoning steps and a 50,000-token context budget, with signing
authority reserved for human counsel and value-based escalation thresholds
in effect.

The agent first read the full contract (1 tool call, allowed under policy
rule #5). It then drafted a $50,000 redline on the indemnity clause; before
transmission, the privileged-language guard detected an internal strategy
note marked [PRIVILEGED] and redacted 58 bytes from the tool arguments. The
redaction is recorded as event #4 in the audit log.

The agent next attempted to execute the contract directly. This was denied
under policy rule #1 (execute_contract reserved for humans). The agent
received the denial in the next reasoning step and adapted its plan.

The agent then proposed a second redline valued at $500,000. Because this
exceeded the agent's $250,000 authority threshold, the run paused for
human approval. Carl Mueller (carl.mueller@tribe.ai) approved the redline
at 14:03:21 UTC; the run resumed and the redline was posted.

The agent then attempted to send the redlined draft to the counterparty.
Because external transmission always requires human sign-off, the run
paused again. Carl Mueller approved transmission at 14:03:22 UTC; the
draft was sent.

The run completed in 7 steps, 4 tool calls (1 denied, 2 escalated and
human-approved, 1 with redaction applied), 5 model invocations totaling
172 tokens, and 5.62 seconds of wall time. All actions are attributable
to either the supervising agent identity or to a named human approver.
```

The narrative is generated *from* the audit log — never from the model — so it cannot misreport what happened. This is the property auditors care about.

---

## 8. File layout

Single file: `examples/mori_master.py`.

Sections, in order:

1. Header docstring (purpose, how to run, what it demonstrates)
2. Imports
3. Hardcoded contract body & deterministic tool functions
4. Mocked `ModelResponse` sequence (the 5-act script)
5. Hook implementations: `redact_privileged_content`, `block_internal_only_sends`, `run_end_audit_closer`
6. Permission policy builder
7. Main async function:
   - Build agent
   - Install policy
   - Run 1 (pauses on first escalation)
   - Print pause status + checkpoint id
   - Run 2 = `agent.resume(...)` with approver info (pauses again on send)
   - Run 3 = `agent.resume(...)` with approver info (completes)
8. Evidence-pack renderer (reads `audit.jsonl`, prints structured output)
9. Narrative renderer (reads `audit.jsonl`, prints prose)
10. `if __name__ == "__main__": asyncio.run(main())`

---

## 9. Why mock the model

The point of a master example is that *all* governance branches fire reliably every time someone runs it — that is what makes it useful as documentation, as a regression touchstone, and as a customer demo. Real Claude's tool-call ordering is not deterministic enough to guarantee that. The existing `governance.py` already establishes this pattern.

If real-model mode is wanted later, gate it on `MORI_MASTER_USE_REAL_MODEL=1` and accept that some acts may not fire — not in scope for this initial spec.

---

## 10. Explicit non-goals

| Pillar | Why excluded |
|---|---|
| Memory layers | Orthogonal to the governance arc; muddles the audit story |
| Skill artifacts | Same |
| MCP / CLI tools | The native function-tool path is enough to show every governance lever |
| Multiple identities | Would dilute focus on policy effects (single supervised agent is the story) |
| Real-model mode | Determinism > realism for this example |
| Persistent checkpointer | `inmemory` is sufficient; SQLite/file backends are demonstrated in other examples |

---

## 11. Risks & open questions

| Risk | Mitigation |
|---|---|
| `PermissionEngine` rule semantics may not support arg-conditional matching (e.g. `value_usd > 250_000`) | Fall back to a `tool.invoke.before` hook raising `HookEscalate` for the threshold check — audit story is identical |
| Mocked adapter contract may drift if Mori's `ModelResponse` schema changes | Catch via mypy; pin to current types in `mori.types` |
| `agent._loop._permission` access is a private hatch used by `governance.py` | Use the same hatch; if a public setter ships before merge, switch to it |
| `run.end` hook payload shape may not include all fields the narrative wants | Narrative reads from `audit.jsonl` directly, not the hook payload — hook is for symmetry only |

---

## 12. Acceptance checklist

- [ ] `python examples/mori_master.py` runs to completion without an API key, in under 5 seconds, deterministically.
- [ ] Output includes a `paused_prompt` and `checkpoint_id` after Run 1.
- [ ] `audit.jsonl` contains events of types: `run.start`, `permission.check` (≥ 6), `guard.redaction` (1), `tool.invoke`, `tool.result`, `permission.deny` (1), `permission.escalate` (≥ 2), `run.pause`, `run.resume`, `run.end`.
- [ ] Evidence pack section prints all five branches: allow, redact, deny, escalate, resume.
- [ ] Narrative section prints prose with absolute UTC timestamps drawn from event records.
- [ ] `mise run check` passes (ruff, mypy strict, pytest, trivy).
