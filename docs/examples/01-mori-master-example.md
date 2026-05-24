# 01 — Mori Master Example: Governance, Compliance & Audit

> **TL;DR.** A `legal-review-bot` reviews a vendor contract end-to-end under
> full governance. Every action is permission-checked, privileged content is
> redacted before it leaves the firm, signing authority is reserved for
> humans, and value-thresholded redlines pause for partner approval. After
> the run, the example reads its own audit log back and prints a compliance
> evidence pack and a human-readable narrative. Six steps of real work, eight
> audit event types, zero special configuration.

**File:** [`examples/mori_master.py`](../../examples/mori_master.py)
**Design spec:** [`docs/superpowers/specs/2026-05-23-mori-master-example-design.md`](../superpowers/specs/2026-05-23-mori-master-example-design.md)
**Runs in:** the host process, no API key required (model is mocked for
determinism — same pattern as `examples/governance.py`).

---

## What it demonstrates

The example wires together every primitive Mori ships for governed
automation:

| Pillar | Mori primitive | What the example uses it for |
|---|---|---|
| **Identity** | `Identity(id="agent:legal-review-bot", group="legal-automation")` | Scopes every action; appears in every permission check and audit event. |
| **Permissions** | `PermissionEngine` rules with `allow` / `deny` / `escalate` effects | Routine redlines pass, signing is denied outright, material redlines and external transmission pause for human approval. |
| **Data guard (hook)** | `tool.invoke.before` hook with priority 1 | Scans tool arguments for `[PRIVILEGED]...[/PRIVILEGED]` markers and redacts them *before* the tool invocation event records anything. |
| **HITL pause/resume** | `checkpointer("inmemory")` + `agent.resume(thread_id, input={"approved": True, "approved_by": "..."})` | Run pauses on escalation, named partner approves, run resumes. Two approval cycles in the demo. |
| **Control bound** | `.config(max_steps=12)` | Bounded execution; surfaces in evidence pack. |
| **Context budget** | `.budget(total_context_tokens=50_000)` | Configured + audited. |
| **Observability** | `.sink("stdout")` + `.sink("jsonl", path="audit.jsonl")` | Full event stream captured to disk for post-run rendering. |

## The scenario

Vendor contract `AC-2024-117` arrives with two clauses to review. The agent:

1. **Reads the contract** (`read_contract` — allowed under policy)
2. **Drafts a routine $50k redline** with a `[PRIVILEGED]...[/PRIVILEGED]`
   internal litigation note attached. The data guard redacts the privileged
   note before the tool is invoked. The audit log shows the *redacted* args.
3. **Attempts to execute (sign) the contract** — the policy denies signing
   outright. The model receives the denial, adapts.
4. **Drafts a material $500k redline** — exceeds the agent's delegated
   authority. Run pauses for partner approval. `RunStatus.PAUSED` is returned
   with a checkpoint id.
5. **Operator approves** — `agent.resume(thread_id, input={"approved": True,
   "approved_by": "carl.mueller@tribe.ai", "matter": "AC-2024-117"})`. The
   policy is updated to permit the approved action. Run resumes.
6. **Agent attempts to send to counterparty** — also requires approval
   (external transmission is always human-gated). Pauses again.
7. **Operator approves the send.** Run resumes and completes with a final
   assistant message: *"Redlines posted (1 routine, 1 material) and draft
   transmitted to counterparty."*

## How to run it

```bash
uv run python examples/mori_master.py
```

No API key required. The model adapter is mocked with a scripted sequence of
`ModelResponse` objects so all five governance branches fire deterministically
on every run.

## What the output looks like

Three sections print in order: a live event stream from the stdout sink, the
compliance evidence pack, and the human-readable narrative.

### Live event stream (excerpt)

```
========================================================================
  RUN 1 — initial review (pauses on material redline)
========================================================================
  [mori] run.start RUN   → "Review contract AC-2024-117 and propose appropriate redlines."
  [mori] ─── step 1 (plan) ───
  [mori] permission.check: {}
  [mori] ACT   → read_contract({'contract_id': 'AC-2024-117'}) [native]
  [mori]        ✓ read_contract: VENDOR SERVICES AGREEMENT — AC-2024-117 ...
  [mori] ─── step 2 (plan) ───
  [mori] permission.check: {}
2026-05-23 16:09:21 [info] hook.payload_mutated  handler=redact_privileged_content
  [mori] ACT   → propose_routine_redline({'contract_id': '...', 'rationale': 'Cap Vendor indemnity...'})
  [mori]        ✓ propose_routine_redline: REDLINE r-7841 posted on AC-2024-117 ...
  [mori] ─── step 3 (plan) ───        ← model tries execute_contract, gets DENIED
  [mori] EVAL  → retry
  [mori] ─── step 4 (plan) ───        ← model tries material redline, ESCALATES
  [mori] DONE  → paused in 4 steps, 144 tokens
  [run.end hook] status=paused
```

### Compliance evidence pack (excerpt)

```
========================================================================
  COMPLIANCE EVIDENCE PACK
========================================================================
  Matter:            AC-2024-117
  Agent identity:    agent:legal-review-bot  (group: legal-automation)
  Bounds in effect:  max_steps=12, token_budget=50000
  Run window:        2026-05-23T23:10:02Z → 2026-05-23T23:10:02Z
  Wall time:         1.1 ms across 3 run(s)

  ── Permission decisions (7: 4 allow / 1 deny / 2 escalate) ──
    ✓ allow     read_contract                     rule=55518039
    ✓ allow     propose_routine_redline           rule=f852b3eb
    ✗ DENY      execute_contract                  rule=33362e8f
    ⚠ escalate  propose_material_redline          rule=b663efb2
    ✓ allow     propose_material_redline          rule=f93d75dc
    ⚠ escalate  send_to_counterparty              rule=43596334
    ✓ allow     send_to_counterparty              rule=72cc1d16

  ── Guard activations (1) ──
    redaction   tool:propose_routine_redline       marker=[PRIVILEGED]  bytes_removed=83

  ── Human approvals (2) ──
    23:10:02 UTC  carl.mueller@tribe.ai  approved propose_material_redline  matter=AC-2024-117
    23:10:02 UTC  carl.mueller@tribe.ai  approved send_to_counterparty       matter=AC-2024-117

  ── Tool invocations (4) ──
    ✓  read_contract             args={contract_id=AC-2024-117}                       (0.0ms)
    ✓  propose_routine_redline   args={contract_id=AC-2024-117, clause=..., rationale=...}  (0.0ms)
    ✓  propose_material_redline  args={contract_id=AC-2024-117, clause=..., value_usd=500000.0}  (0.0ms)
    ✓  send_to_counterparty      args={contract_id=AC-2024-117}                       (0.0ms)

  ── Run totals ──
    steps: 8   tool calls: 4   model calls: 8   tokens in: 394   tokens out: 250

  ── AIUC-1 mapping ──
    B006 unauthorized actions      ✓ 1 deny logged with matching rule
    D003 unsafe tool calls         ✓ 4 invocations recorded
    E004 accountability            ✓ 2 named human approvals captured
    E015 model activity logged     ✓ 3 runs, full token accounting
```

### Human-readable narrative (excerpt)

```
========================================================================
  NARRATIVE
========================================================================

At 23:10:02 UTC, agent legal-review-bot opened matter AC-2024-117 under
attorney supervision (group: legal-automation). The agent's authority was
bounded at 12 reasoning steps and a 50,000-token context budget, with signing
authority reserved for human counsel and value-based escalation thresholds in
effect.

The agent first read the full contract (1 tool call, allowed under policy).
It then drafted a routine redline on the indemnity clause; before
transmission, the privileged-language guard detected an [PRIVILEGED] internal
litigation note and redacted 83 bytes from the tool arguments. The redaction
is recorded as event 11 in the audit log.

The agent next attempted to execute the contract directly. This was denied
under the policy rule for execute_contract (signing reserved for humans). The
agent received the denial in the next reasoning step and adapted its plan.

The agent then proposed a material redline valued at $500,000. Because this
exceeded the agent's delegated authority, the run paused for partner
approval. carl.mueller@tribe.ai approved the redline at 23:10:02 UTC; the run
resumed and the redline was posted.

The agent then attempted to send the redlined draft to the counterparty.
Because external transmission always requires human sign-off, the run paused
again. carl.mueller@tribe.ai approved transmission at 23:10:02 UTC; the
draft was sent.

The matter completed at 23:10:02 UTC. Across 3 runs the agent took 8
reasoning steps, made 4 tool calls (1 denied, 2 escalated and human-approved,
1 with redaction applied), and consumed 644 tokens of model context in 1 ms
of wall time. All actions are attributable to either the supervising agent
identity or to a named human approver.
```

## Why the narrative is generated from the audit log, not the model

The compliance pack and the narrative are both rendered by post-run Python
that walks `audit.jsonl`. The model does not produce them. This matters for
two reasons:

1. **The narrative cannot misreport.** It draws timestamps from the
   `run.start` / `run.end` events, identities from the permission check
   events, dollar values from the tool-invoke argument records. If the
   audit log says the model attempted `execute_contract`, the narrative
   says so — no opportunity for the model to whitewash.

2. **The narrative is reproducible.** Re-running the renderer on the same
   `audit.jsonl` produces the same narrative. This is the property an
   auditor or regulator actually cares about.

## What this example proves about Mori

| Claim | Evidence in this example |
|---|---|
| Identity flows through every event | All 7 permission checks include `identity_id=agent:legal-review-bot`. |
| Permissions are real, not advisory | `execute_contract` was attempted and the deny appears in `tool.result` + `permission.check` events. |
| Data guards run *before* observability records args | The `[PRIVILEGED]` block never appears in the `tool.invoke` event for `propose_routine_redline` — only the redacted form does. |
| Pause/resume preserves state | Two escalations, each resumed with the exact same `thread_id`, no state lost. |
| Approvals are named and timestamped | Both approvals carry `approved_by=carl.mueller@tribe.ai` and ISO-8601 timestamps. |
| The audit log is sufficient to reconstruct what happened | The narrative is built from it alone. |

## What's deliberately out of scope

Memory layers, skill artifacts, MCP tools, multi-identity scenarios, and the
real Anthropic API are all *orthogonal* to this story and would dilute it.
They have their own examples ([`examples/memory_*.py`](../../examples/),
[`examples/skills_and_budget.py`](../../examples/skills_and_budget.py),
[`examples/observability.py`](../../examples/observability.py)).

## What's still missing in Mori itself

A few rough edges the example surfaces (all captured in
[Spec 15 §8](../../mori-docs/specs/15-CODING-HARNESS.md)):

- `RunResult.paused_reason` is not surfaced — only `paused_prompt` is, which
  is `None` for an escalation pause. Callers have to assume which kind of
  pause they got. (Spec 15 §8.6)
- Swapping the permission engine for the resumed run uses
  `agent._loop._permission = engine` — private API. (Spec 15 §8.7)
- The step counter keeps incrementing across resumes, which surprises bound
  configuration on long HITL flows. (Spec 15 §8.4)

These don't affect the demo, but they would matter for production use.

## See also

- [02 — Coding Sandbox (Happy Path)](02-coding-sandbox.md) — same primitives,
  different domain.
- [03 — Adversarial Experiments](03-adversarial-experiments.md) — what
  happens when the model misbehaves.
- [Spec 12: AIUC-1 Compliance](../../mori-docs/specs/12-AIUC1-COMPLIANCE.md)
  — the requirements this example maps onto.
