"""Tests for ControlBounds — resource limits and retry logic."""

import time
from datetime import datetime, timezone

from mori.control.bounds import (
    BoundCheckResult,
    ControlBounds,
    ControlConfig,
    RetryDecision,
)
from mori.runtime.state import MoriState
from mori.types import Message, RunId, RunStatus, ThreadId


def _make_state(**overrides) -> MoriState:
    defaults = {
        "run_id": RunId("run_test"),
        "thread_id": ThreadId("thread_test"),
        "task": "test",
        "status": RunStatus.RUNNING,
        "started_at": datetime.now(timezone.utc),
        "last_progress_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return MoriState(**defaults)


def test_config_defaults():
    c = ControlConfig()
    assert c.max_steps == 50
    assert c.max_total_tokens == 2_000_000
    assert c.idle_timeout_sec == 300.0
    assert c.max_retries_per_tool == 2


def test_check_bounds_ok():
    bounds = ControlBounds(config=ControlConfig())
    state = _make_state(step_count=5, total_input_tokens=100, total_output_tokens=50)
    result = bounds.check_bounds(state)
    assert result.ok is True
    assert result.violated_bounds == []


def test_check_bounds_step_limit():
    bounds = ControlBounds(config=ControlConfig(max_steps=10))
    state = _make_state(step_count=10)
    result = bounds.check_bounds(state)
    assert result.ok is False
    assert "max_steps" in result.violated_bounds


def test_check_bounds_token_limit():
    bounds = ControlBounds(config=ControlConfig(max_total_tokens=1000))
    state = _make_state(total_input_tokens=600, total_output_tokens=500)
    result = bounds.check_bounds(state)
    assert result.ok is False
    assert "max_total_tokens" in result.violated_bounds


def test_check_bounds_run_timeout():
    bounds = ControlBounds(config=ControlConfig(run_timeout_sec=0.001))
    state = _make_state(
        started_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    result = bounds.check_bounds(state)
    assert result.ok is False
    assert "run_timeout" in result.violated_bounds


def test_check_bounds_idle_timeout():
    bounds = ControlBounds(config=ControlConfig(idle_timeout_sec=0.001))
    state = _make_state(
        last_progress_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    result = bounds.check_bounds(state)
    assert result.ok is False
    assert "idle_timeout" in result.violated_bounds


def test_check_bounds_reports_current_values():
    bounds = ControlBounds(config=ControlConfig(max_steps=10))
    state = _make_state(step_count=12)
    result = bounds.check_bounds(state)
    assert result.current_values["step_count"] == 12


def test_should_retry_first_attempt():
    bounds = ControlBounds(config=ControlConfig(max_retries_per_tool=3, retry_backoff_base_sec=1.0))
    decision = bounds.should_retry(ValueError("fail"), attempt=0)
    assert decision.should_retry is True
    assert decision.wait_sec == 1.0
    assert decision.attempt == 0


def test_should_retry_backoff():
    bounds = ControlBounds(config=ControlConfig(max_retries_per_tool=3, retry_backoff_base_sec=1.0))
    d1 = bounds.should_retry(ValueError("fail"), attempt=1)
    assert d1.wait_sec == 2.0
    d2 = bounds.should_retry(ValueError("fail"), attempt=2)
    assert d2.wait_sec == 4.0


def test_should_retry_exhausted():
    bounds = ControlBounds(config=ControlConfig(max_retries_per_tool=2))
    decision = bounds.should_retry(ValueError("fail"), attempt=2)
    assert decision.should_retry is False


def test_should_retry_backoff_capped():
    bounds = ControlBounds(config=ControlConfig(max_retries_per_tool=20, retry_backoff_base_sec=1.0))
    decision = bounds.should_retry(ValueError("fail"), attempt=10)
    assert decision.wait_sec <= 60.0


def test_record_progress():
    bounds = ControlBounds(config=ControlConfig(idle_timeout_sec=1000))
    state = _make_state(last_progress_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    result = bounds.check_bounds(state)
    assert result.ok is False
    bounds.record_progress()
    state.last_progress_at = datetime.now(timezone.utc)
    result2 = bounds.check_bounds(state)
    assert result2.ok is True
