"""AgentLoop — the core agent execution loop."""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from mori.budget.types import BudgetSlot
from mori.model.base import ModelAdapter
from mori.runtime.result import RunResult
from mori.runtime.state import MoriState
from mori.tools.registry import ToolRegistry
from mori.types import (
    Message,
    ModelRequest,
    Phase,
    RunId,
    RunStatus,
    StepId,
    StepOutcome,
    ThreadId,
    ToolSource,
)

if TYPE_CHECKING:
    from mori.control.bounds import ControlBounds
    from mori.observability.engine import ObservabilityEngine
    from mori.observability.events import MoriEvent


def _uid() -> str:
    return secrets.token_hex(12)


class AgentLoop:
    """Agent loop: plan -> act -> evaluate, with observability and control bounds."""

    def __init__(
        self,
        model: ModelAdapter,
        tools: ToolRegistry,
        observability: ObservabilityEngine | None = None,
        control: ControlBounds | None = None,
        memory: Any | None = None,
        skills: Any | None = None,
        budget: Any | None = None,
        checkpointer: Any | None = None,
        checkpoint_every_n_steps: int = 5,
        permission: Any | None = None,
        identity: Any | None = None,
        hooks: Any | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._obs = observability
        if control is None:
            from mori.control.bounds import ControlBounds, ControlConfig

            control = ControlBounds(config=ControlConfig())
        self._control = control
        self._memory = memory
        self._skills = skills
        self._budget = budget
        self._checkpointer = checkpointer
        self._checkpoint_every_n_steps = checkpoint_every_n_steps
        self._permission = permission
        self._identity = identity
        self._hooks = hooks

    async def _emit(self, event: MoriEvent) -> None:
        if self._obs:
            await self._obs.emit(event)

    def _init_state(
        self, task: str, thread_id: ThreadId | None = None, context: dict[str, Any] | None = None
    ) -> MoriState:  # noqa: E501
        now = datetime.now(UTC)
        return MoriState(
            run_id=RunId(f"run_{_uid()}"),
            thread_id=thread_id or ThreadId(f"thread_{_uid()}"),
            task=task,
            context=context or {},
            messages=[Message(role="user", content=task)],
            status=RunStatus.RUNNING,
            started_at=now,
            last_progress_at=now,
        )

    async def _phase_retrieve(self, state: MoriState) -> None:
        # Memory read (unchanged from v0.3)
        if self._memory:
            from mori.observability.events import MemoryReadEvent

            start = time.monotonic()
            memory_slice = await self._memory.read(
                query=state.task, task_context=state.task, max_tokens=2000
            )
            elapsed = (time.monotonic() - start) * 1000
            state.memory_slice = memory_slice
            if self._budget:
                self._budget.consume(BudgetSlot.MEMORY, memory_slice.total_tokens)
            await self._emit(
                MemoryReadEvent(
                    event_id=f"evt_{_uid()}",
                    timestamp=datetime.now(UTC),
                    run_id=state.run_id,
                    query=state.task,
                    layers=list(memory_slice.layers_searched),
                    records_returned=len(memory_slice.records),
                    tokens_consumed=memory_slice.total_tokens,
                    duration_ms=elapsed,
                )
            )

        # Skill discovery + load
        if self._skills:
            from mori.observability.events import SkillDiscoverEvent, SkillLoadEvent

            available_tool_names = [s.name for s in self._tools.list_specs()]
            skill_budget_tokens = (
                self._budget.get_allocation(BudgetSlot.SKILL).allocated if self._budget else 999_999
            )
            disc_start = time.monotonic()
            candidates = self._skills.discover(
                state.task,
                available_tools=available_tool_names,
                available_tokens=skill_budget_tokens,
            )
            disc_elapsed = (time.monotonic() - disc_start) * 1000

            top = candidates[0] if candidates else None
            await self._emit(
                SkillDiscoverEvent(
                    event_id=f"evt_{_uid()}",
                    timestamp=datetime.now(UTC),
                    run_id=state.run_id,
                    task_preview=state.task[:80],
                    candidates_found=len(candidates),
                    top_match_name=top.manifest.name if top else None,
                    top_match_score=top.score if top else None,
                    duration_ms=disc_elapsed,
                )
            )

            if top and top.compatibility_report.context_fits:
                load_start = time.monotonic()
                payload = await self._skills.load(
                    top.manifest.name, "SUMMARY", max_tokens=skill_budget_tokens
                )
                load_elapsed = (time.monotonic() - load_start) * 1000
                state.active_skill_payload = payload
                if self._budget:
                    self._budget.consume(BudgetSlot.SKILL, payload.token_estimate)
                await self._emit(
                    SkillLoadEvent(
                        event_id=f"evt_{_uid()}",
                        timestamp=datetime.now(UTC),
                        run_id=state.run_id,
                        skill_id=payload.skill_id,
                        disclosure_level=payload.disclosure_level,
                        token_estimate=payload.token_estimate,
                        duration_ms=load_elapsed,
                    )
                )

    async def _pre_plan_compact(self, state: MoriState) -> None:
        if not self._budget:
            return
        from mori.budget.types import CompactionModules
        from mori.observability.events import BudgetRebalanceEvent, CompactionEvent

        budgets = self._budget.rebalance(Phase.PLAN)
        report = self._budget.assemble_budget_report()
        await self._emit(
            BudgetRebalanceEvent(
                event_id=f"evt_{_uid()}",
                timestamp=datetime.now(UTC),
                run_id=state.run_id,
                phase=Phase.PLAN.value,
                allocations={slot: b.allocated for slot, b in budgets.items()},
                total_consumed=report.total_consumed,
                utilization=report.utilization,
            )
        )

        if self._budget.needs_compaction():
            compact_report = await self._budget.compact(
                state,
                CompactionModules(
                    memory=self._memory,
                    skills=self._skills,
                    model=self._model,
                ),
            )
            await self._emit(
                CompactionEvent(
                    event_id=f"evt_{_uid()}",
                    timestamp=datetime.now(UTC),
                    run_id=state.run_id,
                    stages_run=compact_report.stages,
                    total_tokens_reclaimed=compact_report.total_tokens_reclaimed,
                    final_utilization=compact_report.final_utilization,
                )
            )

    def _assemble_request(self, state: MoriState) -> ModelRequest:
        # Schema deferral (Stage 2 compaction)
        if self._budget and self._budget._defer_schemas:
            recent_tools: set[str] = set()
            for msg in state.messages[-6:]:
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        recent_tools.add(tc.name)
            tool_specs = []
            for spec in self._tools.list_specs():
                if spec.name in recent_tools:
                    tool_specs.append(spec)
                else:
                    from mori.types import ToolSpec

                    tool_specs.append(
                        ToolSpec(
                            tool_id=spec.tool_id,
                            name=spec.name,
                            description=spec.description,
                            input_schema={},
                            source=spec.source,
                        )
                    )
        else:
            tool_specs = self._tools.list_specs()

        messages = list(state.messages)

        # Insert memory context first (gets pushed to index 1 by skill insertion)
        if state.memory_slice and state.memory_slice.records:
            lines = ["[Memory Context]"]
            for r in state.memory_slice.records:
                lines.append(f"- {r.content} (layer: {r.layer.value}, confidence: {r.confidence})")
            messages.insert(0, Message(role="system", content="\n".join(lines)))

        # Insert skill context last (ends up at index 0)
        if state.active_skill_payload:
            p = state.active_skill_payload
            lines = [f"[Skill Context] ({p.skill_id})", p.content]
            messages.insert(0, Message(role="system", content="\n".join(lines)))

        return ModelRequest(messages=messages, tools=tool_specs if tool_specs else None)

    async def _phase_plan(self, state: MoriState) -> None:
        request = self._assemble_request(state)
        if self._hooks:
            request = await self._hooks.dispatch_before("model.request.before", request)
        response = await self._model.invoke(request)
        if self._hooks:
            await self._hooks.dispatch_after("model.response.after", response)
        state.messages.append(response.message)
        state.total_input_tokens += response.usage.input_tokens
        state.total_output_tokens += response.usage.output_tokens

    async def _phase_act(self, state: MoriState) -> None:
        last_msg = state.messages[-1]
        if not last_msg.tool_calls:
            return

        from mori.observability.events import PermissionCheckEvent, ToolInvokeEvent, ToolResultEvent

        for call in last_msg.tool_calls:
            # Permission check (if engine configured)
            if self._permission:
                from mori.permission.types import (
                    Identity,
                    IdentityType,
                    Permission,
                    Resource,
                    ResourceType,
                )
                from mori.types import PermissionDecision

                effective_identity = self._identity or Identity(
                    id="agent:anonymous",
                    name="anonymous",
                    type=IdentityType.AGENT,
                )
                perm_result = await self._permission.check(
                    effective_identity,
                    Resource(type=ResourceType.TOOL, id=call.name),
                    Permission.EXECUTE,
                )

                await self._emit(
                    PermissionCheckEvent(
                        event_id=f"evt_{_uid()}",
                        timestamp=datetime.now(UTC),
                        run_id=state.run_id,
                        identity_id=effective_identity.id,
                        resource_id=call.name,
                        permission=Permission.EXECUTE.value,
                        decision=perm_result.decision.value,
                        rule_id=(perm_result.rule_applied.id if perm_result.rule_applied else None),
                        explanation=perm_result.explanation,
                    )
                )

                if self._hooks:
                    await self._hooks.dispatch_after("permission.check.after", perm_result)

                if perm_result.decision == PermissionDecision.DENY:
                    deny_content = f"Permission denied: not authorized to invoke '{call.name}'"
                    state.messages.append(
                        Message(role="tool", content=deny_content, tool_call_id=call.id)
                    )  # noqa: E501
                    state.total_tool_calls += 1
                    continue

                if perm_result.decision == PermissionDecision.ESCALATE:
                    state.status = RunStatus.PAUSED
                    state.paused_reason = f"ESCALATE: '{call.name}' requires approval"
                    state.paused_tool_call = call
                    return

            spec = self._tools.get_spec(call.name)
            source: ToolSource = spec.source if spec else ToolSource.NATIVE

            # Before hook fires first so ToolInvokeEvent records actual arguments
            if self._hooks:
                call = await self._hooks.dispatch_before("tool.invoke.before", call)

            await self._emit(
                ToolInvokeEvent(
                    event_id=f"evt_{_uid()}",
                    timestamp=datetime.now(UTC),
                    run_id=state.run_id,
                    tool_name=call.name,
                    source=source,
                    arguments=call.arguments,
                )
            )

            result = await self._tools.invoke(call.name, call.arguments)

            # After hook (observe ToolResult)
            if self._hooks:
                await self._hooks.dispatch_after("tool.invoke.after", result)

            await self._emit(
                ToolResultEvent(
                    event_id=f"evt_{_uid()}",
                    timestamp=datetime.now(UTC),
                    run_id=state.run_id,
                    tool_name=call.name,
                    success=result.success,
                    latency_ms=result.latency_ms,
                    error=result.error,
                    result_preview=str(result.content)[:200] if result.content else None,
                )
            )

            content: str | list[dict[str, Any]] = (
                result.content if result.success else f"ERROR: {result.error}"
            )  # noqa: E501
            state.messages.append(Message(role="tool", content=content, tool_call_id=call.id))
            state.total_tool_calls += 1

    def _phase_evaluate(self, state: MoriState) -> StepOutcome:
        last_msg = state.messages[-1]
        if last_msg.role == "tool":
            return StepOutcome.RETRY
        if last_msg.role == "assistant" and not last_msg.tool_calls:
            return StepOutcome.SUCCESS
        return StepOutcome.RETRY

    async def _phase_update(self, state: MoriState) -> None:
        if not self._memory:
            return
        from mori.observability.events import MemoryWriteEvent
        from mori.types import MemoryLayer, MemoryRecord, MemoryRecordId

        content = f"Step {state.step_count}: Task: {state.task[:100]}. Tool calls: {state.total_tool_calls}."  # noqa: E501
        record = MemoryRecord(
            record_id=MemoryRecordId(f"mem_{secrets.token_hex(12)}"),
            layer=MemoryLayer.WORKING,
            content=content,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            provenance="loop:update",
        )
        receipt = await self._memory.write([record])
        await self._emit(
            MemoryWriteEvent(
                event_id=f"evt_{_uid()}",
                timestamp=datetime.now(UTC),
                run_id=state.run_id,
                layer=MemoryLayer.WORKING,
                record_ids=[str(r) for r in receipt.record_ids],
                records_written=len(receipt.record_ids),  # noqa: E501
            )
        )

    async def run(
        self, task: str, thread_id: ThreadId | None = None, context: dict[str, Any] | None = None
    ) -> RunResult:  # noqa: E501
        state = self._init_state(task, thread_id, context)
        return await self._run_from_state(state)

    async def resume(self, thread_id: ThreadId, input: dict[str, Any]) -> RunResult:
        if not self._checkpointer:
            raise ValueError("Cannot resume: no checkpointer configured")
        cp = await self._checkpointer.load_latest(thread_id)
        if cp is None:
            raise ValueError(f"No checkpoint found for thread {thread_id}")
        state = cp.restore()
        if state.status != RunStatus.PAUSED:
            raise ValueError(
                f"Cannot resume thread {thread_id}: checkpoint has status '{state.status.value}', expected 'paused'"  # noqa: E501
            )
        approved = input.get("approved", False)
        msg = f"[Resume] {'Approved' if approved else 'Rejected'}. Details: {input}"
        state.messages.append(Message(role="user", content=msg))
        state.status = RunStatus.RUNNING
        state.paused_reason = None
        state.paused_tool_call = None
        return await self._run_from_state(state)

    async def _run_from_state(self, state: MoriState) -> RunResult:
        from mori.observability.events import (
            BoundViolationEvent,
            RunEndEvent,
            RunStartEvent,
            StepEndEvent,
            StepStartEvent,
        )

        start_time = time.monotonic()

        await self._emit(
            RunStartEvent(
                event_id=f"evt_{_uid()}",
                timestamp=datetime.now(UTC),
                run_id=state.run_id,
                task=state.task,
                config={"max_steps": self._control._config.max_steps},
            )
        )
        if self._hooks:
            await self._hooks.dispatch_after(
                "run.start", {"task": state.task, "run_id": state.run_id}
            )  # noqa: E501

        while state.status == RunStatus.RUNNING:
            state.step_count += 1
            step_start = time.monotonic()
            step_id = StepId(f"step_{state.run_id}_{state.step_count:04d}")

            # Check bounds before executing
            bound_check = self._control.check_bounds(state)
            if not bound_check.ok:
                for bound in bound_check.violated_bounds:
                    await self._emit(
                        BoundViolationEvent(
                            event_id=f"evt_{_uid()}",
                            timestamp=datetime.now(UTC),
                            run_id=state.run_id,
                            bound_name=bound,
                            current_value=bound_check.current_values.get("step_count", 0),
                            limit_value=float(getattr(self._control._config, bound, 0)),
                        )
                    )
                state.status = RunStatus.FAILED
                break

            # Periodic checkpoint
            if self._checkpointer and state.step_count % self._checkpoint_every_n_steps == 0:
                await self._checkpointer.save(state)

            await self._emit(
                StepStartEvent(
                    event_id=f"evt_{_uid()}",
                    timestamp=datetime.now(UTC),
                    run_id=state.run_id,
                    step_id=step_id,
                    step_number=state.step_count,
                    phase=Phase.PLAN,  # noqa: E501
                )
            )

            await self._phase_retrieve(state)
            await self._pre_plan_compact(state)
            await self._phase_plan(state)
            await self._phase_act(state)

            # Check if _phase_act caused a PAUSED state (e.g. permission ESCALATE)
            # cast needed: mypy narrows state.status to RUNNING in while-condition, but
            # _phase_act can mutate it to PAUSED.
            if cast(RunStatus, state.status) == RunStatus.PAUSED:
                break

            outcome = self._phase_evaluate(state)
            await self._phase_update(state)

            step_elapsed = (time.monotonic() - step_start) * 1000
            await self._emit(
                StepEndEvent(
                    event_id=f"evt_{_uid()}",
                    timestamp=datetime.now(UTC),
                    run_id=state.run_id,
                    step_id=step_id,
                    step_number=state.step_count,
                    outcome=outcome,
                    input_tokens=0,
                    output_tokens=0,
                    duration_ms=step_elapsed,
                )
            )

            if outcome == StepOutcome.SUCCESS:
                state.status = RunStatus.COMPLETED
                break

            self._control.record_progress()
            state.last_progress_at = datetime.now(UTC)

        elapsed_ms = (time.monotonic() - start_time) * 1000

        # Save final checkpoint (always, if checkpointer is present)
        checkpoint_id = None
        if self._checkpointer:
            checkpoint_id = await self._checkpointer.save(state)

        await self._emit(
            RunEndEvent(
                event_id=f"evt_{_uid()}",
                timestamp=datetime.now(UTC),
                run_id=state.run_id,
                status=state.status,
                total_steps=state.step_count,
                total_input_tokens=state.total_input_tokens,
                total_output_tokens=state.total_output_tokens,  # noqa: E501
                duration_ms=elapsed_ms,
            )
        )
        if self._hooks:
            await self._hooks.dispatch_after(
                "run.end", {"status": state.status, "run_id": state.run_id}
            )  # noqa: E501

        # Write episodic summary (memory) — skip if PAUSED
        if self._memory and state.status != RunStatus.PAUSED:
            from mori.observability.events import MemoryWriteEvent
            from mori.types import MemoryLayer, MemoryRecord, MemoryRecordId

            run_result = RunResult.from_state(
                state, duration_ms=elapsed_ms, checkpoint_id=checkpoint_id
            )  # noqa: E501
            tools_used: set[str] = set()
            for msg in state.messages:
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tools_used.add(tc.name)
            ep_content = (
                f'Run "{state.task[:100]}": {state.status.value} in {state.step_count} steps. '
                f'Tools: {", ".join(sorted(tools_used)) or "none"}. '
                f'Result: {(run_result.final_output or "")[:200]}'
            )
            record = MemoryRecord(
                record_id=MemoryRecordId(f"mem_{secrets.token_hex(12)}"),
                layer=MemoryLayer.EPISODIC,
                content=ep_content,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                provenance="loop:episodic",
            )
            receipt = await self._memory.write([record])
            await self._emit(
                MemoryWriteEvent(
                    event_id=f"evt_{_uid()}",
                    timestamp=datetime.now(UTC),
                    run_id=state.run_id,
                    layer=MemoryLayer.EPISODIC,
                    record_ids=[str(r) for r in receipt.record_ids],
                    records_written=1,
                )
            )

        if self._obs:
            await self._obs.flush()

        return RunResult.from_state(state, duration_ms=elapsed_ms, checkpoint_id=checkpoint_id)
