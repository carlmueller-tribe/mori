"""Tests for BudgetManager — per-slot allocation, rebalance, compaction."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from mori.budget.manager import BudgetManager
from mori.budget.types import BudgetConfig, BudgetSlot, RebalanceHints
from mori.types import Phase


@pytest.fixture
def mgr():
    return BudgetManager(BudgetConfig(total_context_tokens=100_000))


def test_get_allocation_system_prompt(mgr):
    b = mgr.get_allocation(BudgetSlot.SYSTEM_PROMPT)
    assert b.allocated == 10_000  # 10% of 100k


def test_get_allocation_generation(mgr):
    b = mgr.get_allocation(BudgetSlot.GENERATION)
    assert b.allocated == 15_000  # 15% of 100k


def test_consume_tracks_usage(mgr):
    result = mgr.consume(BudgetSlot.MEMORY, 500)
    assert result.consumed == 500
    assert result.over_budget is False
    assert mgr.get_allocation(BudgetSlot.MEMORY).consumed == 500


def test_consume_flags_over_budget(mgr):
    result = mgr.consume(BudgetSlot.SKILL, 20_000)  # slot is 15k
    assert result.over_budget is True


def test_release_frees_tokens(mgr):
    mgr.consume(BudgetSlot.MEMORY, 1000)
    mgr.release(BudgetSlot.MEMORY, 400)
    assert mgr.get_allocation(BudgetSlot.MEMORY).consumed == 600


def test_release_never_goes_negative(mgr):
    mgr.release(BudgetSlot.MEMORY, 9999)
    assert mgr.get_allocation(BudgetSlot.MEMORY).consumed == 0


def test_reset_slot(mgr):
    mgr.consume(BudgetSlot.CONVERSATION, 5000)
    mgr.reset_slot(BudgetSlot.CONVERSATION)
    assert mgr.get_allocation(BudgetSlot.CONVERSATION).consumed == 0


def test_rebalance_no_overrides(mgr):
    budgets = mgr.rebalance(Phase.RETRIEVE)
    total_allocated = sum(b.allocated for b in budgets.values())
    assert abs(total_allocated - 100_000) <= 100  # rounding tolerance


def test_rebalance_plan_phase(mgr):
    budgets = mgr.rebalance(Phase.PLAN)
    total = sum(b.allocated for b in budgets.values())
    assert abs(total - 100_000) <= 100
    # MEMORY should be ~25% of 100k
    assert budgets[BudgetSlot.MEMORY].allocated > 20_000


def test_min_generation_enforced():
    mgr = BudgetManager(BudgetConfig(total_context_tokens=10_000, min_generation_tokens=2000))
    b = mgr.get_allocation(BudgetSlot.GENERATION)
    assert b.allocated >= 2000


def test_needs_compaction_false_below_threshold(mgr):
    mgr.consume(BudgetSlot.CONVERSATION, 50_000)  # 50% of 100k, below 85%
    assert mgr.needs_compaction() is False


def test_needs_compaction_true_above_threshold(mgr):
    mgr.consume(BudgetSlot.CONVERSATION, 90_000)  # 90% of 100k
    assert mgr.needs_compaction() is True


def test_needs_compaction_disabled():
    mgr = BudgetManager(BudgetConfig(total_context_tokens=100_000, disable_compaction=True))
    mgr.consume(BudgetSlot.CONVERSATION, 99_000)
    assert mgr.needs_compaction() is False


def test_budget_report(mgr):
    mgr.consume(BudgetSlot.MEMORY, 1000)
    report = mgr.assemble_budget_report()
    assert report.total_tokens == 100_000
    assert report.total_consumed >= 1000
    assert len(report.slots) == 6


# ── Compaction stage tests ────────────────────────────────────


@pytest.fixture
def msg():
    """Helper to create Message objects."""
    from mori.types import Message

    return Message


async def test_stage1_result_trim(mgr, msg):
    """Stage 1 truncates oversized tool results."""
    from mori.budget.types import CompactionModules
    from mori.types import Message

    state = MagicMock()
    long_content = "x" * 20_000
    state.messages = [
        Message(role="user", content="task"),
        Message(role="tool", content=long_content, tool_call_id="c1"),
    ]
    mgr.consume(BudgetSlot.CONVERSATION, 90_000)
    reclaimed = await mgr._stage_result_trim(state, CompactionModules())
    assert reclaimed > 0
    assert len(state.messages[1].content) < len(long_content)


async def test_stage2_schema_defer_sets_flag(mgr):
    """Stage 2 sets _defer_schemas flag."""
    from mori.budget.types import CompactionModules

    state = MagicMock()
    assert mgr._defer_schemas is False
    await mgr._stage_schema_defer(state, CompactionModules())
    assert mgr._defer_schemas is True


async def test_stage3_turn_snip_removes_oldest_tool_round(mgr):
    """Stage 3 removes oldest tool call/result pair."""
    from mori.budget.types import CompactionModules
    from mori.types import Message, ToolCall

    state = MagicMock()
    state.messages = [
        Message(role="user", content="task"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="c1", name="read", arguments={"path": "f"})],
        ),
        Message(role="tool", content="file contents here", tool_call_id="c1"),
        Message(role="assistant", content="I found it"),
        Message(role="assistant", content="done"),
        Message(role="assistant", content="final"),
    ]
    original_len = len(state.messages)
    mgr.consume(BudgetSlot.CONVERSATION, 90_000)
    reclaimed = await mgr._stage_turn_snip(state, CompactionModules())
    assert reclaimed >= 0
    # tool result message removed
    assert not any(m.role == "tool" for m in state.messages)


async def test_compaction_pipeline_stops_early(mgr):
    """Pipeline stops once needs_compaction() is False."""
    from mori.budget.types import CompactionModules
    from mori.types import Message

    state = MagicMock()
    # Include a large tool result so stage 1 can reclaim tokens and drop below threshold
    big_tool_content = "y" * 80_000  # ~20k tokens at 4 chars/token
    state.messages = [
        Message(role="user", content="x"),
        Message(role="tool", content=big_tool_content, tool_call_id="t1"),
    ]
    state.active_skill_payload = None
    state.memory_slice = None
    # Push consumption to just above threshold — stage 1 will reclaim from the oversized tool result
    mgr.consume(BudgetSlot.CONVERSATION, 86_000)
    assert mgr.needs_compaction()
    report = await mgr.compact(state, CompactionModules())
    # Pipeline ran at least one stage
    ran_stages = [r for r in report.stages if r.ran]
    assert len(ran_stages) >= 1
    # Unran stages should exist (pipeline stopped early after stage 1 reclaimed enough)
    unran_stages = [r for r in report.stages if not r.ran]
    assert len(unran_stages) >= 1


async def test_stage6_conversation_summarize(mgr):
    """Stage 6 calls model and inserts summary message."""
    from mori.budget.types import CompactionModules
    from mori.types import Message, ModelResponse, TokenUsage

    state = MagicMock()
    state.messages = [
        Message(role="user", content="task"),
        Message(role="assistant", content="step 1"),
        Message(role="assistant", content="step 2"),
        Message(role="assistant", content="step 3"),
        Message(role="assistant", content="step 4"),
        Message(role="assistant", content="step 5"),
        Message(role="assistant", content="recent 1"),
        Message(role="assistant", content="recent 2"),
        Message(role="assistant", content="recent 3"),
        Message(role="assistant", content="recent 4"),
    ]
    mock_model = AsyncMock()
    mock_model.invoke = AsyncMock(
        return_value=ModelResponse(
            message=Message(role="assistant", content="Summary of conversation."),
            usage=TokenUsage(input_tokens=100, output_tokens=20),
            stop_reason="end_turn",
        )
    )
    modules = CompactionModules(model=mock_model)
    mgr.consume(BudgetSlot.CONVERSATION, 90_000)
    reclaimed = await mgr._stage_conversation_summarize(state, modules)
    # Model was called
    mock_model.invoke.assert_called_once()
    # Summary message inserted
    assert any(
        "[Conversation Summary]" in (m.content if isinstance(m.content, str) else "")
        for m in state.messages
    )


def test_recount_from_state(mgr):
    """recount_from_state routes messages to correct slots by role and content."""
    from mori.types import Message

    state_stub = type(
        "S",
        (),
        {
            "messages": [
                Message(role="user", content="do the thing"),
                Message(role="system", content="[Memory Context]\n- fact"),
                Message(role="system", content="[Skill Context: bug-fix]\nsummary"),
                Message(role="system", content="[System Prompt] You are an agent."),
                Message(role="assistant", content="thinking..."),
            ]
        },
    )()
    mgr.consume(BudgetSlot.CONVERSATION, 5000)  # pre-existing consumption
    mgr.recount_from_state(state_stub)
    # pre-existing consumption cleared
    assert mgr.get_allocation(BudgetSlot.MEMORY).consumed > 0
    assert mgr.get_allocation(BudgetSlot.SKILL).consumed > 0
    assert mgr.get_allocation(BudgetSlot.SYSTEM_PROMPT).consumed > 0
    assert mgr.get_allocation(BudgetSlot.CONVERSATION).consumed > 0


def test_rebalance_with_hints(mgr):
    """rebalance hints add extra tokens on top of phase allocation."""
    before = mgr.get_allocation(BudgetSlot.MEMORY).allocated
    budgets = mgr.rebalance(Phase.PLAN, hints=RebalanceHints(extra_memory_tokens=5000))
    after = budgets[BudgetSlot.MEMORY].allocated
    assert after > before
