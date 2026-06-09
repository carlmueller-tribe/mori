"""Mori Master — governance, compliance, and audit in one example.

A `legal-review-bot` reviews vendor contract AC-2024-117 and produces redlines.
The work is fully governed end-to-end so the firm can defend every action in
audit. This is the example a compliance officer points at to demonstrate the
chain-of-custody guarantees Mori provides.

What this single file demonstrates:

  - Identity-scoped agent (agent:legal-review-bot, group=legal-automation)
  - PermissionEngine policy with allow / deny / escalate rules
  - tool.invoke.before hook that redacts attorney-client privileged content
  - tool.invoke.before hook that hard-blocks confidentiality leaks
  - run.end hook for closing audit signal
  - Control bound (max_steps) and context budget configured + audited
  - Checkpointer + escalate pause/resume with named human approver
  - Observability sinks (stdout + JSONL) — every action is recorded
  - Post-run rendering of two artifacts derived from the audit trail:
      (1) Compliance evidence pack (structured, AIUC-1-style mapped)
      (2) Human-readable narrative (prose, suitable for a compliance memo)

The model is mocked so all five governance branches fire deterministically on
every run (allow, redact, deny, escalate, resume-after-approval). No API key
required. Same pattern as examples/governance.py.

Usage:
    python examples/mori_master.py

Outputs:
    audit.jsonl   — raw event stream from the observability engine
    stdout        — live event stream + evidence pack + narrative
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from mori import Mori
from mori.permission.engine import PermissionEngine
from mori.permission.types import (
    Identity,
    IdentityPattern,
    IdentityType,
    PermissionRule,
    ResourcePattern,
    ResourceType,
)
from mori.types import Message, ModelResponse, RunStatus, TokenUsage, ToolCall

AUDIT_PATH = Path("audit.jsonl")
MATTER_ID = "AC-2024-117"
APPROVER = "carl.mueller@tribe.ai"

# Module-level audit tracking — populated by hooks and resume calls.
# The post-run renderers combine these with audit.jsonl to produce the
# evidence pack and narrative. (See render_evidence_pack / render_narrative.)
REDACTIONS: list[dict[str, Any]] = []
APPROVALS: list[dict[str, Any]] = []


# ── Contract content (deterministic test data) ───────────────────────────────

CONTRACT_BODY = """\
VENDOR SERVICES AGREEMENT — AC-2024-117

Clause 4 (Indemnity): Vendor indemnifies Buyer for any third-party claim
arising from Vendor's services, without limitation of liability.

Clause 11 (Termination for Convenience): Buyer may terminate this Agreement
for convenience upon 90 days' notice. No termination fee applies.
"""


# ── Tools (plain functions; the runtime registers them as native tools) ─────


def read_contract(contract_id: str) -> str:
    """Read a contract from the contract management system."""
    if contract_id != MATTER_ID:
        return f"ERROR: contract {contract_id!r} not found"
    return CONTRACT_BODY


def propose_routine_redline(contract_id: str, clause: str, rationale: str) -> str:
    """Propose a routine redline (within attorney delegated authority)."""
    return f"REDLINE r-7841 posted on {contract_id} clause '{clause}'"


def propose_material_redline(
    contract_id: str, clause: str, rationale: str, value_usd: float
) -> str:
    """Propose a material redline (above $250k — requires partner approval)."""
    return (
        f"REDLINE r-7842 posted on {contract_id} clause '{clause}' "
        f"(material change, value=${value_usd:,.0f})"
    )


def send_to_counterparty(contract_id: str) -> str:
    """Send the current contract draft to opposing counsel."""
    return f"Draft of {contract_id} transmitted to counterparty at {datetime.now(UTC).isoformat()}"


def execute_contract(contract_id: str) -> str:
    """Execute (sign) the contract. Reserved for humans — policy denies this."""
    return f"UNAUTHORIZED: {contract_id} should never reach this function"


# ── Hooks ────────────────────────────────────────────────────────────────────

PRIVILEGED_RE = re.compile(r"\[PRIVILEGED\].*?\[/PRIVILEGED\]", re.DOTALL)


async def redact_privileged_content(call: ToolCall) -> ToolCall | None:
    """Strip [PRIVILEGED]...[/PRIVILEGED] segments from string args before tool runs.

    Attorney-client privileged content must not leave the firm via tool calls —
    even internal tool calls, since tool args/results show up in the audit trail
    and downstream systems. This hook redacts before the tool invocation event
    fires, so the redacted form is what gets logged.
    """
    redacted_args: dict[str, Any] = {}
    bytes_removed = 0
    for key, value in call.arguments.items():
        if not isinstance(value, str) or "[PRIVILEGED]" not in value:
            redacted_args[key] = value
            continue
        new_value, n = PRIVILEGED_RE.subn("[REDACTED: ATTORNEY-CLIENT PRIVILEGED]", value)
        redacted_args[key] = new_value
        bytes_removed += len(value) - len(new_value)
    if bytes_removed == 0:
        return None  # no change, let original through
    REDACTIONS.append(
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "tool_name": call.name,
            "marker": "[PRIVILEGED]",
            "bytes_removed": bytes_removed,
        }
    )
    return call.model_copy(update={"arguments": redacted_args})


async def block_internal_only_sends(call: ToolCall) -> ToolCall | None:
    """Defense-in-depth: never let an [INTERNAL ONLY] tag leave the firm.

    Even if policy approves a send, a confidentiality marker means stop.
    """
    if call.name != "send_to_counterparty":
        return None
    for value in call.arguments.values():
        if isinstance(value, str) and "[INTERNAL ONLY]" in value:
            from mori.hooks import HookBlock

            raise HookBlock(
                "send blocked: [INTERNAL ONLY] confidentiality marker present",
                hook_id="confidentiality_gate",
            )
    return None


def on_run_end(payload: dict[str, Any]) -> None:
    """Closing audit signal — printed to stdout for visibility."""
    status: Any = payload.get("status")
    status_value = status.value if status is not None and hasattr(status, "value") else str(status)
    print(f"\n  [run.end hook] status={status_value}")


# ── Permission policy ────────────────────────────────────────────────────────


def build_policy(
    *,
    allow_material_redline: bool = False,
    allow_send: bool = False,
) -> PermissionEngine:
    """Build the legal-review-bot policy.

    The `allow_*` overrides are flipped on after a named human approver
    authorizes the escalated action. This mirrors how a real approval system
    would issue a one-time authorization for the resumed run.
    """
    any_identity = IdentityPattern(match="group", value="legal-automation")
    rules: list[PermissionRule] = [
        # 1. Hard deny: signing is for humans only.
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="execute_contract"),
            identity=any_identity,
            permissions="--x",
            effect="deny",
            priority=100,
        ),
        # 2. Material redlines: escalate unless approved.
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="propose_material_redline"),
            identity=any_identity,
            permissions="--x",
            effect="allow" if allow_material_redline else "escalate",
            priority=80,
        ),
        # 3. External transmission: escalate unless approved.
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="send_to_counterparty"),
            identity=any_identity,
            permissions="--x",
            effect="allow" if allow_send else "escalate",
            priority=80,
        ),
        # 4. Routine redlines: within delegated authority.
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="propose_routine_redline"),
            identity=any_identity,
            permissions="--x",
            effect="allow",
            priority=50,
        ),
        # 5. Reading the contract: always fine.
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="read_contract"),
            identity=any_identity,
            permissions="r-x",
            effect="allow",
            priority=50,
        ),
        # 6. Native ask_user must remain available.
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="ask_user"),
            identity=any_identity,
            permissions="r-x",
            effect="allow",
            priority=50,
        ),
    ]
    engine = PermissionEngine()
    engine.load_rules(rules)
    return engine


# ── Mocked model responses (the deterministic 5-act script) ──────────────────


def _say(content: str) -> ModelResponse:
    return ModelResponse(
        message=Message(role="assistant", content=content),
        usage=TokenUsage(input_tokens=20, output_tokens=12),
        stop_reason="end_turn",
    )


def _call(name: str, args: dict[str, Any], call_id: str) -> ModelResponse:
    return ModelResponse(
        message=Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
        ),
        usage=TokenUsage(input_tokens=22, output_tokens=14),
        stop_reason="tool_use",
    )


SCRIPTED_RESPONSES: list[ModelResponse] = [
    # Act 1: read the contract.
    _call("read_contract", {"contract_id": MATTER_ID}, "c1"),
    # Act 2: routine redline with a PRIVILEGED note in the rationale.
    _call(
        "propose_routine_redline",
        {
            "contract_id": MATTER_ID,
            "clause": "Clause 4 (Indemnity)",
            "rationale": (
                "Cap Vendor indemnity at 1x annual fees; current draft is uncapped. "
                "[PRIVILEGED] Internal litigation note: opposing firm has settled "
                "comparable claims at 0.7x — we anchor low. [/PRIVILEGED]"
            ),
        },
        "c2",
    ),
    # Act 3: model tries to execute. Policy denies — model receives denial,
    # adapts in the next step.
    _call("execute_contract", {"contract_id": MATTER_ID}, "c3"),
    # Act 4: material redline ($500k). Policy escalates — run pauses.
    _call(
        "propose_material_redline",
        {
            "contract_id": MATTER_ID,
            "clause": "Clause 11 (Termination for Convenience)",
            "rationale": (
                "Add a $500,000 termination-for-convenience fee payable to Vendor "
                "if Buyer terminates within first 24 months."
            ),
            "value_usd": 500_000.0,
        },
        "c4",
    ),
    # --- run pauses here, agent.resume(...) is called ---
    # Act 5a: after approval, model re-issues the material redline. Now allowed.
    _call(
        "propose_material_redline",
        {
            "contract_id": MATTER_ID,
            "clause": "Clause 11 (Termination for Convenience)",
            "rationale": (
                "Add a $500,000 termination-for-convenience fee payable to Vendor "
                "if Buyer terminates within first 24 months."
            ),
            "value_usd": 500_000.0,
        },
        "c4b",
    ),
    # Act 5b: send to counterparty. Policy escalates — run pauses again.
    _call("send_to_counterparty", {"contract_id": MATTER_ID}, "c5"),
    # --- run pauses again, agent.resume(...) is called ---
    # Act 5c: after second approval, model re-issues the send. Now allowed.
    _call("send_to_counterparty", {"contract_id": MATTER_ID}, "c5b"),
    # Act 5d: assistant wraps up with a plain message — run completes.
    _say("Redlines posted (1 routine, 1 material) and draft transmitted to counterparty."),
]


# ── Main flow ────────────────────────────────────────────────────────────────


async def main() -> None:
    AUDIT_PATH.unlink(missing_ok=True)
    REDACTIONS.clear()
    APPROVALS.clear()

    with patch("mori.agent.AnthropicAdapter") as adapter_class:
        mock_adapter = AsyncMock()
        mock_adapter.model_id = "claude-mock"
        mock_adapter.supports_tool_use = True
        mock_adapter.max_context_tokens = 100_000
        mock_adapter.invoke = AsyncMock(side_effect=SCRIPTED_RESPONSES)
        adapter_class.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(read_contract, description="Read a contract from the CMS")
            .tool(
                propose_routine_redline, description="Propose a routine redline (within authority)"
            )
            .tool(
                propose_material_redline,
                description="Propose a material redline (requires partner approval)",
            )
            .tool(send_to_counterparty, description="Send draft to opposing counsel")
            .tool(execute_contract, description="Sign the contract (humans only)")
            .identity(
                Identity(
                    id="agent:legal-review-bot",
                    name="legal-review-bot",
                    type=IdentityType.AGENT,
                    groups=["legal-automation"],
                )
            )
            .budget(total_context_tokens=50_000)
            .checkpointer("inmemory")
            .hook("tool.invoke.before", redact_privileged_content, priority=1)
            .hook("tool.invoke.before", block_internal_only_sends, priority=2)
            .hook("run.end", on_run_end)
            .sink("stdout")
            .sink("jsonl", path=str(AUDIT_PATH))
            .config(max_steps=12)
            .build()
        )

        # Install initial policy: every escalation rule is active.
        agent._loop._permission = build_policy()

        thread_id = f"matter-{MATTER_ID}"

        print(f"\n{'=' * 72}\n  RUN 1 — initial review (pauses on material redline)\n{'=' * 72}")
        result = await agent.run(
            f"Review contract {MATTER_ID} and propose appropriate redlines.",
            thread_id=thread_id,
        )
        print(
            f"\n  status={result.status.value}  "
            f"checkpoint={result.checkpoint_id}  "
            f"paused_prompt={result.paused_prompt!r}"
        )
        assert result.status == RunStatus.PAUSED, result.status

        # Operator (named partner) approves the material redline. Update policy
        # to allow material redlines for the remainder of the matter.
        APPROVALS.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "approved_by": APPROVER,
                "action": "propose_material_redline",
                "matter": MATTER_ID,
            }
        )
        agent._loop._permission = build_policy(allow_material_redline=True)

        print(
            f"\n{'=' * 72}\n"
            f"  RUN 2 — resume after partner approval (pauses on external send)\n"
            f"{'=' * 72}"
        )
        result = await agent.resume(
            thread_id,
            input={
                "approved": True,
                "approved_by": APPROVER,
                "matter": MATTER_ID,
                "action": "propose_material_redline",
            },
        )
        print(
            f"\n  status={result.status.value}  "
            f"checkpoint={result.checkpoint_id}  "
            f"paused_prompt={result.paused_prompt!r}"
        )
        assert result.status == RunStatus.PAUSED, result.status

        # Operator approves the external send.
        APPROVALS.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "approved_by": APPROVER,
                "action": "send_to_counterparty",
                "matter": MATTER_ID,
            }
        )
        agent._loop._permission = build_policy(allow_material_redline=True, allow_send=True)

        print(f"\n{'=' * 72}\n  RUN 3 — resume after send approval (completes)\n{'=' * 72}")
        result = await agent.resume(
            thread_id,
            input={
                "approved": True,
                "approved_by": APPROVER,
                "matter": MATTER_ID,
                "action": "send_to_counterparty",
            },
        )
        print(f"\n  status={result.status.value}  final={result.final_output!r}")
        assert result.status == RunStatus.COMPLETED, result.status

        await agent.close()

    # ── Post-run reports ─────────────────────────────────────────────────
    events = _load_events(AUDIT_PATH)
    render_evidence_pack(events)
    render_narrative(events)


# ── Audit rendering ──────────────────────────────────────────────────────────


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _fmt_ts(ts: str) -> str:
    """Render an ISO timestamp as HH:MM:SS UTC."""
    return ts[11:19] + " UTC"


def render_evidence_pack(events: list[dict[str, Any]]) -> None:
    perm_checks = [e for e in events if e.get("event_type") == "permission.check"]
    tool_invokes = [e for e in events if e.get("event_type") == "tool.invoke"]
    tool_results = [e for e in events if e.get("event_type") == "tool.result"]
    run_starts = [e for e in events if e.get("event_type") == "run.start"]
    run_ends = [e for e in events if e.get("event_type") == "run.end"]

    first_ts = run_starts[0]["timestamp"] if run_starts else "?"
    last_ts = run_ends[-1]["timestamp"] if run_ends else "?"

    # step_count is cumulative across resumes; max gives the matter's final count.
    total_steps = max((e.get("total_steps", 0) for e in run_ends), default=0)
    total_in = sum(e.get("total_input_tokens", 0) for e in run_ends)
    total_out = sum(e.get("total_output_tokens", 0) for e in run_ends)
    total_ms = sum(e.get("duration_ms", 0.0) for e in run_ends)

    denies = [e for e in perm_checks if e.get("decision") == "deny"]
    escalates = [e for e in perm_checks if e.get("decision") == "escalate"]
    allows = [e for e in perm_checks if e.get("decision") == "allow"]

    print(f"\n{'=' * 72}\n  COMPLIANCE EVIDENCE PACK\n{'=' * 72}")
    print(f"  Matter:            {MATTER_ID}")
    print("  Agent identity:    agent:legal-review-bot  (group: legal-automation)")
    print("  Bounds in effect:  max_steps=12, token_budget=50000")
    print(f"  Run window:        {first_ts} → {last_ts}")
    print(f"  Wall time:         {total_ms:.1f} ms across {len(run_ends)} run(s)")

    print(
        f"\n  ── Permission decisions ({len(perm_checks)}: "
        f"{len(allows)} allow / {len(denies)} deny / {len(escalates)} escalate) ──"
    )
    for e in perm_checks:
        marker = {"allow": "✓ allow   ", "deny": "✗ DENY    ", "escalate": "⚠ escalate"}.get(
            e.get("decision", ""), "?"
        )
        rule_id = e.get("rule_id") or "-"
        # rule_id is a UUID; show short prefix for readability.
        rule_short = rule_id[:8] if len(rule_id) > 8 else rule_id
        print(f"    {marker}  {e['resource_id']:32}  rule={rule_short}")

    print(f"\n  ── Guard activations ({len(REDACTIONS)}) ──")
    for r in REDACTIONS:
        print(
            f"    redaction   tool:{r['tool_name']:32}  marker={r['marker']}  "
            f"bytes_removed={r['bytes_removed']}"
        )

    print(f"\n  ── Human approvals ({len(APPROVALS)}) ──")
    for a in APPROVALS:
        print(
            f"    {_fmt_ts(a['timestamp'])}  {a['approved_by']}  approved {a['action']}  "
            f"matter={a['matter']}"
        )

    print(f"\n  ── Tool invocations ({len(tool_invokes)}) ──")
    for inv, res in zip(tool_invokes, tool_results, strict=False):
        ok = "✓" if res.get("success") else "✗"
        print(
            f"    {ok}  {inv['tool_name']:32}  "
            f"args={_compact_args(inv.get('arguments'))}  "
            f"latency={res.get('latency_ms', 0.0):.1f}ms"
        )

    print("\n  ── Run totals ──")
    print(f"    steps:        {total_steps}")
    print(f"    tool calls:   {len(tool_invokes)}")
    print(f"    model calls:  {len([e for e in events if e.get('event_type') == 'step.start'])}")
    print(f"    tokens in:    {total_in}")
    print(f"    tokens out:   {total_out}")

    print("\n  ── AIUC-1 mapping ──")
    print(f"    B006 unauthorized actions      ✓ {len(denies)} deny logged with matching rule")
    print(f"    D003 unsafe tool calls         ✓ {len(tool_invokes)} invocations recorded")
    print(f"    E004 accountability            ✓ {len(APPROVALS)} named human approvals captured")
    print(f"    E015 model activity logged     ✓ {len(run_ends)} runs, full token accounting")


def _compact_args(args: dict[str, Any] | None) -> str:
    if not args:
        return "{}"
    parts: list[str] = []
    for key, value in args.items():
        text = repr(value) if not isinstance(value, str) else value
        if len(text) > 40:
            text = text[:37] + "..."
        parts.append(f"{key}={text}")
    return "{" + ", ".join(parts) + "}"


def render_narrative(events: list[dict[str, Any]]) -> None:
    perm_checks = [e for e in events if e.get("event_type") == "permission.check"]
    tool_invokes = [e for e in events if e.get("event_type") == "tool.invoke"]
    run_starts = [e for e in events if e.get("event_type") == "run.start"]
    run_ends = [e for e in events if e.get("event_type") == "run.end"]

    denies = [e for e in perm_checks if e.get("decision") == "deny"]
    escalates = [e for e in perm_checks if e.get("decision") == "escalate"]

    open_ts = _fmt_ts(run_starts[0]["timestamp"]) if run_starts else "?"
    close_ts = _fmt_ts(run_ends[-1]["timestamp"]) if run_ends else "?"
    total_ms = sum(e.get("duration_ms", 0.0) for e in run_ends)
    total_steps = max((e.get("total_steps", 0) for e in run_ends), default=0)
    total_tokens = sum(
        e.get("total_input_tokens", 0) + e.get("total_output_tokens", 0) for e in run_ends
    )

    redactions_text = (
        f"the privileged-language guard detected an [PRIVILEGED] internal litigation note "
        f"and redacted {REDACTIONS[0]['bytes_removed']} bytes from the tool arguments. "
        f"The redaction is recorded as event "
        f"{_index_of_redaction_in_events(events) or '?'} in the audit log."
        if REDACTIONS
        else "no redactions were applied."
    )

    print(f"\n{'=' * 72}\n  NARRATIVE\n{'=' * 72}\n")
    print(
        f"At {open_ts}, agent legal-review-bot opened matter {MATTER_ID} under "
        f"attorney supervision (group: legal-automation). The agent's authority "
        f"was bounded at 12 reasoning steps and a 50,000-token context budget, "
        f"with signing authority reserved for human counsel and value-based "
        f"escalation thresholds in effect."
    )
    print(
        f"\nThe agent first read the full contract (1 tool call, allowed under "
        f"policy). It then drafted a routine redline on the indemnity clause; "
        f"before transmission, {redactions_text}"
    )
    if denies:
        d = denies[0]
        print(
            f"\nThe agent next attempted to execute the contract directly. This "
            f"was denied under the policy rule for {d['resource_id']} (signing "
            f"reserved for humans). The agent received the denial in the next "
            f"reasoning step and adapted its plan."
        )
    if len(APPROVALS) >= 1 and len(escalates) >= 1:
        print(
            f"\nThe agent then proposed a material redline valued at $500,000. "
            f"Because this exceeded the agent's delegated authority, the run "
            f"paused for partner approval. {APPROVER} approved the redline at "
            f"{_fmt_ts(APPROVALS[0]['timestamp'])}; the run resumed and the "
            f"redline was posted."
        )
    if len(APPROVALS) >= 2:
        print(
            f"\nThe agent then attempted to send the redlined draft to the "
            f"counterparty. Because external transmission always requires "
            f"human sign-off, the run paused again. {APPROVER} approved "
            f"transmission at {_fmt_ts(APPROVALS[1]['timestamp'])}; the draft "
            f"was sent."
        )
    print(
        f"\nThe matter completed at {close_ts}. Across {len(run_ends)} runs the "
        f"agent took {total_steps} reasoning steps, made {len(tool_invokes)} "
        f"tool calls ({len(denies)} denied, {len(escalates)} escalated and "
        f"human-approved, {len(REDACTIONS)} with redaction applied), and "
        f"consumed {total_tokens} tokens of model context in {total_ms:.0f} ms "
        f"of wall time. All actions are attributable to either the supervising "
        f"agent identity or to a named human approver."
    )
    print()


def _index_of_redaction_in_events(events: list[dict[str, Any]]) -> int | None:
    """Find the first tool.invoke event whose redaction we'd have caused.

    We don't emit a dedicated guard.redaction event (the guard tracks redactions
    in the REDACTIONS list), so we surface the tool.invoke that the redactor
    modified — that's the one with the post-redaction args.
    """
    for i, e in enumerate(events, start=1):
        if e.get("event_type") == "tool.invoke" and e.get("tool_name") == "propose_routine_redline":
            return i
    return None


if __name__ == "__main__":
    asyncio.run(main())
