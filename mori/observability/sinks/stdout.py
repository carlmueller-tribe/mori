"""StdoutSink — formatted console output for events."""

from __future__ import annotations

from mori.observability.events import (
    BoundViolationEvent,
    MoriEvent,
    RunEndEvent,
    RunStartEvent,
    StepEndEvent,
    StepStartEvent,
    ToolInvokeEvent,
    ToolResultEvent,
)

_GREY = "\033[90m"
_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_RESET = "\033[0m"


def _format_event(event: MoriEvent) -> str:
    prefix = f"  {_GREY}[mori]{_RESET}"
    if isinstance(event, RunStartEvent):
        return f'{prefix} {event.event_type} RUN   → "{event.task[:80]}" config={event.config}'
    if isinstance(event, RunEndEvent):
        color = _GREEN if event.status.value == "completed" else _RED
        return (
            f"{prefix} DONE  → {color}{event.status.value}{_RESET} in {event.total_steps} steps, "  # noqa: E501
            f"{event.total_input_tokens + event.total_output_tokens} tokens, {event.duration_ms:.0f}ms"  # noqa: E501
        )  # noqa: E501
    if isinstance(event, StepStartEvent):
        return f"{prefix} ─── step {event.step_number} ({event.phase.value}) ───"
    if isinstance(event, StepEndEvent):
        return f"{prefix} EVAL  → {event.outcome.value} ({event.duration_ms:.0f}ms)"
    if isinstance(event, ToolInvokeEvent):
        args_str = str(event.arguments)[:100] if event.arguments else ""
        return f"{prefix} ACT   → {event.tool_name}({args_str}) [{event.source.value}]"
    if isinstance(event, ToolResultEvent):
        if event.success:
            preview = (event.result_preview or "")[:80]
            return f"{prefix}        {_GREEN}✓{_RESET} {event.tool_name}: {preview} ({event.latency_ms:.0f}ms)"  # noqa: E501
        else:
            return f"{prefix}        {_RED}✗{_RESET} {event.tool_name}: {event.error}"
    if isinstance(event, BoundViolationEvent):
        return f"{prefix} {_YELLOW}BOUND{_RESET} → {event.bound_name}: {event.current_value} >= {event.limit_value}"  # noqa: E501
    return f"{prefix} {event.event_type}: {event.metadata}"


class StdoutSink:
    realtime = True  # Events are written immediately, not buffered

    async def write(self, event: MoriEvent) -> None:
        print(_format_event(event))

    async def write_batch(self, events: list[MoriEvent]) -> None:
        for event in events:
            print(_format_event(event))

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        pass
