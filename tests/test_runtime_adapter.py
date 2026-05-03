from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mori.runtime.adapter import RuntimeAdapter
from mori.runtime.loop import AgentLoop
from mori.runtime.result import RunResult
from mori.types import RunStatus


class ConcreteAdapter:
    async def run(self, task, state, tools, memory, skills) -> RunResult:
        from mori.types import TokenUsage

        return RunResult(
            run_id=state.run_id,
            thread_id=state.thread_id,
            status=RunStatus.COMPLETED,
            task=task,
            final_output="adapter ran",
            total_steps=0,
            total_usage=TokenUsage(input_tokens=0, output_tokens=0),
            total_tool_calls=0,
            total_duration_ms=0.0,
        )

    async def stream(self, task, state, tools, **kwargs):
        return
        yield  # make it an async generator


def test_concrete_adapter_satisfies_protocol():
    assert isinstance(ConcreteAdapter(), RuntimeAdapter)


@pytest.mark.asyncio
async def test_agent_loop_delegates_to_runtime_adapter():
    mock_model = MagicMock()
    mock_tools = MagicMock()
    adapter = ConcreteAdapter()
    loop = AgentLoop(model=mock_model, tools=mock_tools, runtime=adapter)
    result = await loop.run("test task")
    assert result.final_output == "adapter ran"
    assert result.status == RunStatus.COMPLETED


def test_agent_loop_stores_none_runtime():
    mock_model = MagicMock()
    mock_tools = MagicMock()
    loop = AgentLoop(model=mock_model, tools=mock_tools, runtime=None)
    assert loop._runtime is None
