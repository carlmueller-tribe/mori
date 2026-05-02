"""Memory layers example — direct MemoryModule API.

Demonstrates the full MemoryModule interface without running an agent:
  - write()          — insert records into specific layers
  - read_by_ids()    — fetch records by ID
  - promote()        — copy records from one layer to another
  - forget()         — expire TTL records and prune low-confidence ones
  - summarize_layer()— concatenate layer content into a passage
  - update()         — patch record content / confidence in place
  - delete()         — remove individual records
  - stats()          — count records and estimate token usage per layer

No ANTHROPIC_API_KEY required for this example — it uses InMemoryBackend
with no embedder, so writes and reads work but semantic search is disabled.
(Semantic search requires: pip install voyageai)

Usage:
    cd ~/Projects/Mori
    python examples/memory_layers.py
"""

import asyncio
import secrets
from datetime import UTC, datetime

from mori.memory.backends.inmemory import InMemoryBackend
from mori.memory.module import MemoryModule
from mori.types import (
    ForgetPolicy,
    MemoryConfig,
    MemoryLayer,
    MemoryRecord,
    MemoryRecordId,
)


def make_record(
    content: str,
    layer: MemoryLayer,
    confidence: float = 1.0,
    ttl_seconds: int | None = None,
    provenance: str = "demo",
) -> MemoryRecord:
    return MemoryRecord(
        record_id=MemoryRecordId(f"mem_{secrets.token_hex(8)}"),
        layer=layer,
        content=content,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        confidence=confidence,
        ttl_seconds=ttl_seconds,
        provenance=provenance,
    )


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


async def main() -> None:
    backend = InMemoryBackend()
    memory = MemoryModule(backend=backend, config=MemoryConfig(), embedder=None)

    # ── 1. Write records to multiple layers ──────────────────
    section("1. Write records to multiple layers")

    working_records = [
        make_record("Step 1: Retrieved user profile from database.", MemoryLayer.WORKING),
        make_record("Step 2: Ran validation checks — all passed.", MemoryLayer.WORKING),
        make_record("Step 3: Sent confirmation email to user@example.com.", MemoryLayer.WORKING),
        # Low confidence — will be pruned in step 5
        make_record(
            "Step 4: Maybe cached the result? Not sure.", MemoryLayer.WORKING, confidence=0.1
        ),
        # Short TTL — will expire in step 5 (we simulate with ttl_seconds=0)
        make_record(
            "Step 5: Temporary rate-limit token acquired.", MemoryLayer.WORKING, ttl_seconds=0
        ),  # expires immediately
    ]

    episodic_records = [
        make_record(
            'Run "onboard_user": completed in 3 steps. Tools: db_query, email_send. '
            "Result: user onboarded successfully.",
            MemoryLayer.EPISODIC,
        ),
        make_record(
            'Run "reset_password": completed in 2 steps. Tools: db_query, email_send. '
            "Result: reset link sent.",
            MemoryLayer.EPISODIC,
        ),
    ]

    receipt_w = await memory.write(working_records)
    receipt_e = await memory.write(episodic_records)
    print(f"  Written {len(receipt_w.record_ids)} working records")
    print(f"  Written {len(receipt_e.record_ids)} episodic records")

    # ── 2. Read records by ID ─────────────────────────────────
    section("2. Read specific records by ID")

    fetched = await memory.read_by_ids(
        [working_records[0].record_id, episodic_records[0].record_id]
    )
    for r in fetched:
        print(f"  [{r.layer.value}] {r.content[:70]}")

    # ── 3. Update a record ────────────────────────────────────
    section("3. Update a working-memory record")

    target_id = working_records[1].record_id
    updated = await memory.update(
        record_id=target_id,
        content="Step 2: Ran validation checks — 3 warnings, all non-blocking.",
        confidence=0.85,
    )
    print(f"  Before: {working_records[1].content}")
    print(f"  After : {updated.content}")
    print(f"  New confidence: {updated.confidence}")

    # ── 4. Promote working → semantic ────────────────────────
    section("4. Promote high-confidence working records to semantic layer")

    high_conf_ids = [
        r.record_id for r in working_records if r.confidence >= 0.5 and r.ttl_seconds is None
    ]
    new_ids = await memory.promote(
        source_layer=MemoryLayer.WORKING,
        target_layer=MemoryLayer.SEMANTIC,
        record_ids=high_conf_ids,
    )
    print(f"  Promoted {len(new_ids)} record(s) to semantic layer")

    # Also promote episodic → personalized with an abstraction function
    def abstract(contents: list[str]) -> str:
        return "Past runs: " + " | ".join(c[:60] for c in contents)

    pers_ids = await memory.promote(
        source_layer=MemoryLayer.EPISODIC,
        target_layer=MemoryLayer.PERSONALIZED,
        record_ids=[r.record_id for r in episodic_records],
        abstraction_fn=abstract,
    )
    print(f"  Promoted {len(pers_ids)} abstracted record(s) to personalized layer")

    # ── 5. Forget — expire TTL and prune low confidence ───────
    section("5. Forget: expire TTL records + prune confidence < 0.2")

    stats_before = await memory.stats()
    print(f"  Records before forget: {stats_before.total_records}")

    report = await memory.forget(
        policy=ForgetPolicy(
            expire_ttl=True,
            prune_below_confidence=0.2,
            deduplicate=False,
        )
    )
    print(f"  Expired (TTL)     : {report.expired}")
    print(f"  Pruned (conf<0.2) : {report.pruned}")
    print(f"  Total deleted     : {report.total_deleted}")

    stats_after = await memory.stats()
    print(f"  Records after forget: {stats_after.total_records}")

    # ── 6. Summarize a layer ──────────────────────────────────
    section("6. Summarize the episodic layer")

    summary = await memory.summarize_layer(MemoryLayer.EPISODIC, max_tokens=300)
    print(f"  Episodic summary ({len(summary)} chars):")
    for line in summary.splitlines():
        print(f"    {line}")

    # ── 7. Delete individual records ──────────────────────────
    section("7. Delete one semantic record")

    semantic_backend = await backend.list_records(MemoryLayer.SEMANTIC)
    if semantic_backend:
        deleted = await memory.delete([semantic_backend[0].record_id])
        print(f"  Deleted {deleted} semantic record(s)")

    # ── 8. Final stats ────────────────────────────────────────
    section("8. Final stats across all layers")

    final = await memory.stats()
    print(f"\n  {'Layer':<16} {'Records':>7}  {'~Tokens':>8}")
    print(f"  {'─'*16} {'─'*7}  {'─'*8}")
    for layer in MemoryLayer:
        count = final.records_per_layer[layer]
        tokens = final.estimated_tokens_per_layer[layer]
        print(f"  {layer.value:<16} {count:>7}  {tokens:>8}")
    print(f"  {'─'*16} {'─'*7}  {'─'*8}")
    print(f"  {'TOTAL':<16} {final.total_records:>7}")

    await memory.close()


if __name__ == "__main__":
    asyncio.run(main())
