# Mori — Worked Examples & Experiments

This directory contains human-readable walkthroughs of the runnable examples in
the Mori repository. Each one demonstrates a different facet of what Mori is
designed to do, and — equally importantly — surfaces where it doesn't yet hold
up.

## The three documents

| Document | What it covers |
|---|---|
| [01 — Mori Master Example](01-mori-master-example.md) | Governance, compliance, and audit. A legal contract-review agent that demonstrates every primitive Mori ships for regulated automation: identity, permissions, escalation, data guards, audit trail, evidence pack, narrative. |
| [02 — Coding Sandbox (Happy Path)](02-coding-sandbox.md) | Mori as a coding harness. A real Claude model is given five filesystem/shell tools inside a Docker sandbox and asked to fix a failing test. Validates that the runtime can drive a coding loop end-to-end. |
| [03 — Adversarial Experiments](03-adversarial-experiments.md) | Stress-testing Mori's guards. Two adversarial runs — one that the guards caught cleanly, one that uncovered three serious bypasses. Honest accounting of what Mori's current hook-based defenses can and cannot do. |

## How to read these together

The three documents tell one coherent story about Mori's readiness:

1. **The master example** shows the *intent* — what Mori is built for. Every
   primitive a regulated agent needs is present and integrated, with a real
   audit trail and a generated compliance narrative.

2. **The coding sandbox** shows the *reach* — Mori's primitives can drive
   workloads outside their original scope. A real model fixes a real bug in a
   real test suite, with full audit, in six steps.

3. **The adversarial experiments** show the *limits* — and what would have to
   change for Mori to be a credible coding harness. Both experiments fed back
   into [Spec 15: Coding Harness](../../mori-docs/specs/15-CODING-HARNESS.md),
   the post-V1 future module that addresses the gaps.

## Where the artifacts live

All three experiments are runnable from this repo:

```bash
# Master example (deterministic, no API key required)
uv run python examples/mori_master.py

# Coding sandbox — safe mode (happy path)
examples/sandbox/run-sandbox.sh

# Coding sandbox — adversarial mode (the agent is instructed to misbehave)
MORI_SANDBOX_MODE=adversarial examples/sandbox/run-sandbox.sh

# Coding sandbox — obfuscated mode (the agent is told to try multiple bypasses)
MORI_SANDBOX_MODE=obfuscated examples/sandbox/run-sandbox.sh
```

The first runs entirely in-process with a mocked model. The other three launch
a Docker container that bind-mounts the Mori source read-only and gives the
agent a scratch directory to work in. API keys are resolved via 1Password at
process start — they never sit on disk.
