import pytest
from pydantic import ValidationError
from mori.budget.types import (
    BudgetSlot, BudgetConfig, ConsumeResult, RebalanceHints,
    SlotReport, BudgetReport, CompactionStage, StageResult,
    CompactionReport, CompactionModules,
)

def test_budget_slot_values():
    assert BudgetSlot.SYSTEM_PROMPT == "system_prompt"
    assert BudgetSlot.GENERATION == "generation"

def test_budget_config_defaults():
    cfg = BudgetConfig()
    assert cfg.total_context_tokens == 200_000
    assert cfg.compaction_threshold_pct == 0.85
    assert cfg.min_generation_tokens == 1000
    assert cfg.max_result_tokens == 4000
    assert cfg.disable_compaction is False
    assert cfg.slot_overrides == {}

def test_budget_config_slot_overrides_exceeding_1_raises():
    with pytest.raises(ValidationError):
        BudgetConfig(slot_overrides={
            "system_prompt": 0.20,
            "memory": 0.25,
            "skill": 0.20,
            "tool_schemas": 0.15,
            "conversation": 0.35,
            "generation": 0.20,
        })

def test_consume_result():
    r = ConsumeResult(slot=BudgetSlot.MEMORY, consumed=500, over_budget=False)
    assert r.slot == BudgetSlot.MEMORY
    assert r.consumed == 500
    assert r.over_budget is False

def test_compaction_report_totals():
    stages = [
        StageResult(stage=CompactionStage.RESULT_TRIM, tokens_reclaimed=200, ran=True),
        StageResult(stage=CompactionStage.SCHEMA_DEFER, tokens_reclaimed=0, ran=False),
    ]
    report = CompactionReport(
        stages=stages,
        total_tokens_reclaimed=200,
        initial_utilization=0.90,
        final_utilization=0.82,
    )
    assert report.total_tokens_reclaimed == 200
    assert report.final_utilization == 0.82

def test_compaction_modules_arbitrary_types():
    class Fake:
        pass
    m = CompactionModules(memory=Fake(), skills=None, model=None)
    assert m.memory is not None
    assert m.skills is None
