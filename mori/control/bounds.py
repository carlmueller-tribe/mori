"""ControlBounds — single authority for all resource limits."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from pydantic import Field

from mori.runtime.state import MoriState
from mori.types import MoriModel


class ControlConfig(MoriModel):
    max_steps: int = 50
    max_total_tokens: int = 2_000_000
    step_timeout_sec: float = 120.0
    run_timeout_sec: float = 3600.0
    idle_timeout_sec: float = 300.0
    max_retries_per_tool: int = 2
    retry_backoff_base_sec: float = 1.0


class BoundCheckResult(MoriModel):
    ok: bool
    violated_bounds: list[str] = Field(default_factory=list)
    current_values: dict[str, float] = Field(default_factory=dict)


class RetryDecision(MoriModel):
    should_retry: bool
    wait_sec: float = 0.0
    attempt: int = 0


class ControlBounds:
    """Single authority for all resource limits."""

    def __init__(self, config: ControlConfig) -> None:
        self._config = config
        self._last_progress = time.monotonic()

    def check_bounds(self, state: MoriState) -> BoundCheckResult:
        violated: list[str] = []
        values: dict[str, float] = {}
        now = datetime.now(UTC)

        values["step_count"] = float(state.step_count)
        if state.step_count >= self._config.max_steps:
            violated.append("max_steps")

        total_tokens = state.total_input_tokens + state.total_output_tokens
        values["total_tokens"] = float(total_tokens)
        if total_tokens >= self._config.max_total_tokens:
            violated.append("max_total_tokens")

        run_elapsed = (now - state.started_at).total_seconds()
        values["run_elapsed_sec"] = run_elapsed
        if run_elapsed >= self._config.run_timeout_sec:
            violated.append("run_timeout")

        idle_elapsed = (now - state.last_progress_at).total_seconds()
        values["idle_elapsed_sec"] = idle_elapsed
        if idle_elapsed >= self._config.idle_timeout_sec:
            violated.append("idle_timeout")

        return BoundCheckResult(
            ok=len(violated) == 0, violated_bounds=violated, current_values=values
        )  # noqa: E501

    def should_retry(self, error: Exception, attempt: int) -> RetryDecision:
        if attempt >= self._config.max_retries_per_tool:
            return RetryDecision(should_retry=False, attempt=attempt)
        wait = self._config.retry_backoff_base_sec * (2**attempt)
        wait = min(wait, 60.0)
        return RetryDecision(should_retry=True, wait_sec=wait, attempt=attempt)

    def record_progress(self) -> None:
        self._last_progress = time.monotonic()
