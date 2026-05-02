"""BudgetManager — per-slot token allocation and compaction orchestration."""

from __future__ import annotations

import contextlib
from typing import Any, cast

from mori.budget.types import (
    BudgetConfig,
    BudgetReport,
    BudgetSlot,
    CompactionModules,
    CompactionReport,
    CompactionStage,
    ConsumeResult,
    RebalanceHints,
    SlotReport,
    StageResult,
)
from mori.types import Phase, TokenBudget

_BASE_ALLOC: dict[BudgetSlot, float] = {
    BudgetSlot.SYSTEM_PROMPT: 0.10,
    BudgetSlot.MEMORY: 0.20,
    BudgetSlot.SKILL: 0.15,
    BudgetSlot.TOOL_SCHEMAS: 0.10,
    BudgetSlot.CONVERSATION: 0.30,
    BudgetSlot.GENERATION: 0.15,
}

_PHASE_OVERRIDES: dict[Phase, dict[BudgetSlot, float]] = {
    Phase.PLAN: {
        BudgetSlot.MEMORY: 0.25,
        BudgetSlot.CONVERSATION: 0.30,
        BudgetSlot.SKILL: 0.10,
    },
    Phase.ACT: {
        BudgetSlot.SKILL: 0.20,
        BudgetSlot.TOOL_SCHEMAS: 0.15,
        BudgetSlot.MEMORY: 0.15,
    },
}


class BudgetManager:
    def __init__(self, config: BudgetConfig) -> None:
        self._config = config
        self._budgets: dict[BudgetSlot, TokenBudget] = {}
        self._defer_schemas: bool = False
        self._init_allocations()

    def _alloc_from_fractions(self, fractions: dict[BudgetSlot, float]) -> None:
        total = self._config.total_context_tokens
        for slot, pct in fractions.items():
            existing = self._budgets.get(slot)
            consumed = existing.consumed if existing else 0
            self._budgets[slot] = TokenBudget(allocated=max(0, int(total * pct)), consumed=consumed)

    def _enforce_min_generation(self) -> None:
        gen = self._budgets[BudgetSlot.GENERATION]
        min_gen = self._config.min_generation_tokens
        if gen.allocated >= min_gen:
            return
        deficit = min_gen - gen.allocated
        candidates = sorted(
            [s for s in BudgetSlot if s != BudgetSlot.GENERATION],
            key=lambda s: self._budgets[s].allocated,
            reverse=True,
        )
        for slot in candidates:
            available = self._budgets[slot].allocated
            steal = min(deficit, available)
            self._budgets[slot] = TokenBudget(
                allocated=available - steal,
                consumed=self._budgets[slot].consumed,
            )
            deficit -= steal
            if deficit <= 0:
                break
        self._budgets[BudgetSlot.GENERATION] = TokenBudget(allocated=min_gen, consumed=gen.consumed)

    def _init_allocations(self) -> None:
        overrides = self._config.slot_overrides
        fractions = {s: overrides.get(s.value, v) for s, v in _BASE_ALLOC.items()}
        self._alloc_from_fractions(fractions)
        self._enforce_min_generation()

    def get_allocation(self, slot: BudgetSlot) -> TokenBudget:
        return self._budgets[slot]

    def consume(self, slot: BudgetSlot, tokens: int) -> ConsumeResult:
        b = self._budgets[slot]
        new_consumed = b.consumed + tokens
        self._budgets[slot] = TokenBudget(allocated=b.allocated, consumed=new_consumed)
        return ConsumeResult(
            slot=slot, consumed=new_consumed, over_budget=new_consumed > b.allocated
        )

    def release(self, slot: BudgetSlot, tokens: int) -> None:
        b = self._budgets[slot]
        self._budgets[slot] = TokenBudget(
            allocated=b.allocated, consumed=max(0, b.consumed - tokens)
        )

    def reset_slot(self, slot: BudgetSlot) -> None:
        b = self._budgets[slot]
        self._budgets[slot] = TokenBudget(allocated=b.allocated, consumed=0)

    def rebalance(
        self, phase: Phase, hints: RebalanceHints | None = None
    ) -> dict[BudgetSlot, TokenBudget]:
        fractions = dict(_BASE_ALLOC)
        if phase in _PHASE_OVERRIDES:
            fractions.update(_PHASE_OVERRIDES[phase])
        # Apply per-slot config overrides before normalization
        for slot_str, pct in self._config.slot_overrides.items():
            with contextlib.suppress(ValueError):
                fractions[BudgetSlot(slot_str)] = pct
        # Normalize so fractions sum to 1.0 regardless of override combinations
        total_pct = sum(fractions.values())
        fractions = {k: v / total_pct for k, v in fractions.items()}
        self._alloc_from_fractions(fractions)
        self._enforce_min_generation()
        if hints:
            if hints.extra_memory_tokens:
                b = self._budgets[BudgetSlot.MEMORY]
                self._budgets[BudgetSlot.MEMORY] = TokenBudget(
                    allocated=b.allocated + hints.extra_memory_tokens,
                    consumed=b.consumed,
                )
            if hints.extra_skill_tokens:
                b = self._budgets[BudgetSlot.SKILL]
                self._budgets[BudgetSlot.SKILL] = TokenBudget(
                    allocated=b.allocated + hints.extra_skill_tokens,
                    consumed=b.consumed,
                )
        return dict(self._budgets)

    def recount_from_state(self, state: Any) -> None:
        """Reset all slots then recount token estimates from state.messages."""
        for slot in BudgetSlot:
            self.reset_slot(slot)
        for msg in state.messages:
            # list[dict] content (e.g. multimodal) is counted as 0 tokens — known approximation
            content = msg.content if isinstance(msg.content, str) else ""
            tokens = len(content) // 4
            if msg.role == "system":
                if "[Memory Context]" in content:
                    self.consume(BudgetSlot.MEMORY, tokens)
                elif "[Skill Context" in content:
                    self.consume(BudgetSlot.SKILL, tokens)
                else:
                    self.consume(BudgetSlot.SYSTEM_PROMPT, tokens)
            else:
                self.consume(BudgetSlot.CONVERSATION, tokens)

    def needs_compaction(self) -> bool:
        if self._config.disable_compaction:
            return False
        total_consumed = sum(b.consumed for b in self._budgets.values())
        threshold = self._config.total_context_tokens * self._config.compaction_threshold_pct
        return total_consumed > threshold

    def assemble_budget_report(self) -> BudgetReport:
        total = self._config.total_context_tokens
        total_consumed = sum(b.consumed for b in self._budgets.values())
        slots = [
            SlotReport(
                slot=slot,
                allocated=b.allocated,
                consumed=b.consumed,
                pct_used=b.consumed / b.allocated if b.allocated > 0 else 0.0,
            )
            for slot, b in self._budgets.items()
        ]
        return BudgetReport(
            total_tokens=total,
            total_consumed=total_consumed,
            utilization=total_consumed / total if total > 0 else 0.0,
            slots=slots,
        )

    async def compact(self, state: Any, modules: CompactionModules) -> CompactionReport:
        initial_utilization = self.assemble_budget_report().utilization
        stage_results: list[StageResult] = []

        pipeline = [
            (CompactionStage.RESULT_TRIM, self._stage_result_trim),
            (CompactionStage.SCHEMA_DEFER, self._stage_schema_defer),
            (CompactionStage.TURN_SNIP, self._stage_turn_snip),
            (CompactionStage.SKILL_DOWNGRADE, self._stage_skill_downgrade),
            (CompactionStage.MEMORY_PRUNE, self._stage_memory_prune),
            (CompactionStage.CONVERSATION_SUMMARIZE, self._stage_conversation_summarize),
        ]

        for stage_enum, stage_fn in pipeline:
            if not self.needs_compaction():
                stage_results.append(StageResult(stage=stage_enum, tokens_reclaimed=0, ran=False))
                continue
            reclaimed = await stage_fn(state, modules)
            stage_results.append(
                StageResult(stage=stage_enum, tokens_reclaimed=reclaimed, ran=True)
            )  # noqa: E501

        final_report = self.assemble_budget_report()
        return CompactionReport(
            stages=stage_results,
            total_tokens_reclaimed=sum(r.tokens_reclaimed for r in stage_results),
            initial_utilization=initial_utilization,
            final_utilization=final_report.utilization,
        )

    async def _stage_result_trim(self, state: Any, _: CompactionModules) -> int:
        max_chars = self._config.max_result_tokens * 4
        reclaimed = 0
        for i, msg in enumerate(state.messages):
            content = msg.content if isinstance(msg.content, str) else ""
            if msg.role == "tool" and len(content) > max_chars:
                old_tokens = len(content) // 4
                new_content = content[:max_chars] + "… [truncated]"
                state.messages[i] = msg.model_copy(update={"content": new_content})
                new_tokens = len(new_content) // 4
                reclaimed += old_tokens - new_tokens
        if reclaimed:
            self.release(BudgetSlot.CONVERSATION, reclaimed)
        return reclaimed

    async def _stage_schema_defer(self, state: Any, _: CompactionModules) -> int:
        self._defer_schemas = True
        return 0

    async def _stage_turn_snip(self, state: Any, _: CompactionModules) -> int:
        """Remove the oldest single tool-call/result round from state.messages.

        Deliberately removes only one round per invocation — conservative by design.
        If more compaction is needed, later (more aggressive) stages handle it.
        Skips the initial user message (index 0) and always preserves the last 4 messages.
        """
        reclaimed = 0
        i = 1  # skip initial user message
        while i < len(state.messages) - 4:
            msg = state.messages[i]
            if msg.role == "assistant" and msg.tool_calls:
                reclaimed += sum(
                    (len(tc.name) + len(str(tc.arguments))) // 4 for tc in msg.tool_calls
                )
                # keep assistant text, strip tool_calls
                state.messages[i] = msg.model_copy(update={"tool_calls": None})
                i += 1
                while i < len(state.messages) and state.messages[i].role == "tool":
                    content = state.messages[i].content
                    reclaimed += len(content if isinstance(content, str) else "") // 4
                    state.messages.pop(i)
                break
            i += 1
        if reclaimed:
            self.release(BudgetSlot.CONVERSATION, reclaimed)
        return reclaimed

    async def _stage_skill_downgrade(self, state: Any, modules: CompactionModules) -> int:
        if not modules.skills or not state.active_skill_payload:
            return 0
        payload = state.active_skill_payload
        if payload.disclosure_level.value != "full":
            return 0
        skill_budget = self._budgets[BudgetSlot.SKILL].allocated
        summary_payload = await modules.skills.load(
            payload.skill_id, "SUMMARY", max_tokens=skill_budget
        )
        reclaimed = cast(int, max(0, payload.token_estimate - summary_payload.token_estimate))
        state.active_skill_payload = summary_payload
        for i, msg in enumerate(state.messages):
            if msg.role == "system" and "[Skill Context]" in (
                msg.content if isinstance(msg.content, str) else ""
            ):
                state.messages[i] = msg.model_copy(update={"content": summary_payload.content})
                break
        if reclaimed:
            self.release(BudgetSlot.SKILL, reclaimed)
        return reclaimed

    async def _stage_memory_prune(self, state: Any, modules: CompactionModules) -> int:
        if not modules.memory:
            return 0
        old_tokens = state.memory_slice.total_tokens if state.memory_slice else 0
        half_budget = max(0, old_tokens // 2)
        if half_budget < 100:
            return 0
        new_slice = await modules.memory.read(
            query=state.task, task_context=state.task, max_tokens=half_budget
        )
        state.memory_slice = new_slice
        if new_slice.records:
            lines = ["[Memory Context]"]
            for r in new_slice.records:
                lines.append(f"- {r.content} (layer: {r.layer.value}, confidence: {r.confidence})")
            new_content: str | None = "\n".join(lines)
        else:
            new_content = None
        for i, msg in enumerate(state.messages):
            content = msg.content if isinstance(msg.content, str) else ""
            if msg.role == "system" and "[Memory Context]" in content:
                if new_content:
                    state.messages[i] = msg.model_copy(update={"content": new_content})
                else:
                    state.messages.pop(i)
                break
        reclaimed = cast(int, max(0, old_tokens - new_slice.total_tokens))
        if reclaimed:
            self.release(BudgetSlot.MEMORY, reclaimed)
        return reclaimed

    async def _stage_conversation_summarize(self, state: Any, modules: CompactionModules) -> int:
        if not modules.model or len(state.messages) <= 6:
            return 0
        to_summarize = state.messages[1:-4]
        if not to_summarize:
            return 0
        old_tokens = sum(
            len(m.content if isinstance(m.content, str) else "") // 4 for m in to_summarize
        )
        summary_text = "\n".join(
            f"[{m.role}]: {(m.content if isinstance(m.content, str) else '')[:500]}"
            for m in to_summarize
        )
        from mori.types import Message, ModelRequest

        req = ModelRequest(
            messages=[
                Message(
                    role="user",
                    content=(
                        "Summarize this conversation history concisely in 3-5 sentences, "
                        f"preserving key facts and decisions:\n\n{summary_text}"
                    ),
                )
            ],
            tools=None,
        )
        response = await modules.model.invoke(req)
        summary_content = f"[Conversation Summary]\n{response.message.content}"
        state.messages = [
            state.messages[0],
            Message(role="system", content=summary_content),
        ] + list(state.messages[-4:])
        new_tokens = len(summary_content) // 4
        reclaimed = max(0, old_tokens - new_tokens)
        if reclaimed:
            self.release(BudgetSlot.CONVERSATION, reclaimed)
        return reclaimed
