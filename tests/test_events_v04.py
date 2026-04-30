# tests/test_events_v04.py
from datetime import datetime, timezone
from mori.observability.events import (
    SkillDiscoverEvent, SkillLoadEvent,
    BudgetRebalanceEvent, CompactionEvent,
)
from mori.budget.types import BudgetSlot, CompactionStage, StageResult
from mori.types import RunId, DisclosureLevel


def _now():
    return datetime.now(timezone.utc)


def test_skill_discover_event():
    e = SkillDiscoverEvent(
        event_id="e1", timestamp=_now(), run_id=RunId("r1"),
        task_preview="fix the test",
        candidates_found=2,
        top_match_name="bug-fix",
        top_match_score=0.95,
        duration_ms=5.0,
    )
    assert e.event_type == "skill.discover"
    assert e.top_match_name == "bug-fix"


def test_skill_load_event():
    e = SkillLoadEvent(
        event_id="e2", timestamp=_now(), run_id=RunId("r1"),
        skill_id="bug-fix",
        disclosure_level=DisclosureLevel.SUMMARY,
        token_estimate=120,
        duration_ms=2.0,
    )
    assert e.event_type == "skill.load"
    assert e.disclosure_level == DisclosureLevel.SUMMARY


def test_budget_rebalance_event():
    e = BudgetRebalanceEvent(
        event_id="e3", timestamp=_now(), run_id=RunId("r1"),
        phase="plan",
        allocations={BudgetSlot.MEMORY: 25_000, BudgetSlot.CONVERSATION: 30_000},
        total_consumed=10_000,
        utilization=0.10,
    )
    assert e.event_type == "budget.rebalance"
    assert BudgetSlot.MEMORY in e.allocations


def test_compaction_event():
    stages = [StageResult(stage=CompactionStage.RESULT_TRIM, tokens_reclaimed=500, ran=True)]
    e = CompactionEvent(
        event_id="e4", timestamp=_now(), run_id=RunId("r1"),
        stages_run=stages,
        total_tokens_reclaimed=500,
        final_utilization=0.80,
    )
    assert e.event_type == "budget.compaction"
    assert e.total_tokens_reclaimed == 500


def test_mori_state_has_active_skill_payload():
    from datetime import datetime, timezone
    from mori.runtime.state import MoriState
    from mori.types import RunId, ThreadId, RunStatus
    state = MoriState(
        run_id=RunId("r1"), thread_id=ThreadId("t1"), task="test",
        status=RunStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
        last_progress_at=datetime.now(timezone.utc),
    )
    assert state.active_skill_payload is None
    state.active_skill_payload = "anything"
    assert state.active_skill_payload == "anything"
