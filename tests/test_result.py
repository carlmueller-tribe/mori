"""Tests for RunResult and StepResult."""

from datetime import UTC, datetime

from mori.runtime.result import RunResult, StepResult
from mori.runtime.state import MoriState
from mori.types import (
    Message,
    RunId,
    RunStatus,
    StepId,
    StepOutcome,
    ThreadId,
    TokenUsage,
)


def test_run_result_from_state():
    state = MoriState(
        run_id=RunId("run_1"),
        thread_id=ThreadId("thread_1"),
        task="test task",
        status=RunStatus.COMPLETED,
        messages=[
            Message(role="user", content="What is 3+5?"),
            Message(role="assistant", content="The answer is 8."),
        ],
        step_count=2,
        total_input_tokens=100,
        total_output_tokens=50,
        total_tool_calls=1,
        started_at=datetime.now(UTC),
        last_progress_at=datetime.now(UTC),
    )
    result = RunResult.from_state(state, duration_ms=1500.0)
    assert result.run_id == "run_1"
    assert result.status == RunStatus.COMPLETED
    assert result.total_steps == 2
    assert result.total_usage.total == 150
    assert result.total_tool_calls == 1
    assert result.final_output == "The answer is 8."
    assert result.total_duration_ms == 1500.0


def test_run_result_final_output_none_when_no_assistant_message():
    state = MoriState(
        run_id=RunId("run_1"),
        thread_id=ThreadId("thread_1"),
        task="test",
        status=RunStatus.FAILED,
        messages=[Message(role="user", content="hi")],
        started_at=datetime.now(UTC),
        last_progress_at=datetime.now(UTC),
    )
    result = RunResult.from_state(state, duration_ms=100.0)
    assert result.final_output is None


def test_step_result():
    sr = StepResult(
        step_id=StepId("step_run1_0001"),
        step_number=1,
        outcome=StepOutcome.SUCCESS,
        usage=TokenUsage(input_tokens=50, output_tokens=25),
        duration_ms=200.0,
    )
    assert sr.step_number == 1
    assert sr.outcome == StepOutcome.SUCCESS
    assert sr.tool_results == []


def test_run_result_json_roundtrip():
    state = MoriState(
        run_id=RunId("run_1"),
        thread_id=ThreadId("thread_1"),
        task="test",
        status=RunStatus.COMPLETED,
        messages=[Message(role="assistant", content="done")],
        step_count=1,
        total_input_tokens=10,
        total_output_tokens=5,
        started_at=datetime.now(UTC),
        last_progress_at=datetime.now(UTC),
    )
    result = RunResult.from_state(state, duration_ms=500.0)
    json_str = result.model_dump_json()
    restored = RunResult.model_validate_json(json_str)
    assert restored.final_output == "done"
    assert restored.total_steps == 1


def test_result_blocked_fields_default_none() -> None:
    from mori.runtime.result import RunResult
    from mori.types import RunId, RunStatus, ThreadId

    r = RunResult(
        run_id=RunId("r1"),
        thread_id=ThreadId("t1"),
        status=RunStatus.COMPLETED,
        task="x",
    )
    assert r.block_reason is None
    assert r.block_hook_id is None
    assert r.paused_prompt is None


def test_result_blocked_fields_settable() -> None:
    from mori.runtime.result import RunResult
    from mori.types import RunId, RunStatus, ThreadId

    r = RunResult(
        run_id=RunId("r1"),
        thread_id=ThreadId("t1"),
        status=RunStatus.BLOCKED,
        task="x",
        block_reason="prod migration",
        block_hook_id="hook_abc",
    )
    assert r.status == "blocked"
    assert r.block_reason == "prod migration"


def test_run_status_has_blocked() -> None:
    from mori.types import RunStatus

    assert RunStatus.BLOCKED == "blocked"
