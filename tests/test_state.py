"""Tests for MoriState."""

from datetime import UTC, datetime

from mori.runtime.state import MoriState
from mori.types import Message, RunId, RunStatus, ThreadId


def _make_state(**overrides) -> MoriState:
    defaults = {
        "run_id": RunId("run_test"),
        "thread_id": ThreadId("thread_test"),
        "task": "test task",
        "status": RunStatus.RUNNING,
        "started_at": datetime.now(UTC),
        "last_progress_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return MoriState(**defaults)


def test_state_defaults():
    s = _make_state()
    assert s.step_count == 0
    assert s.total_input_tokens == 0
    assert s.total_output_tokens == 0
    assert s.total_tool_calls == 0
    assert s.messages == []
    assert s.context == {}


def test_state_mutable():
    s = _make_state()
    s.step_count = 5
    s.status = RunStatus.COMPLETED
    assert s.step_count == 5
    assert s.status == RunStatus.COMPLETED


def test_state_messages():
    s = _make_state()
    s.messages.append(Message(role="user", content="hello"))
    s.messages.append(Message(role="assistant", content="hi"))
    assert len(s.messages) == 2


def test_state_json_roundtrip():
    s = _make_state()
    s.messages.append(Message(role="user", content="test"))
    s.step_count = 3
    json_str = s.model_dump_json()
    restored = MoriState.model_validate_json(json_str)
    assert restored.run_id == s.run_id
    assert restored.step_count == 3
    assert len(restored.messages) == 1


def test_state_rejects_extra_fields():
    import pytest

    with pytest.raises(Exception):
        MoriState(
            run_id=RunId("run_test"),
            thread_id=ThreadId("thread_test"),
            task="test",
            started_at=datetime.now(UTC),
            last_progress_at=datetime.now(UTC),
            bogus_field="nope",
        )


from mori.types import MemoryLayer, MemorySlice


def test_state_memory_slice_default_none():
    s = _make_state()
    assert s.memory_slice is None


def test_state_memory_slice_settable():
    s = _make_state()
    s.memory_slice = MemorySlice(
        records=[],
        total_tokens=0,
        query="test",
        layers_searched=[MemoryLayer.WORKING],
        truncated=False,
    )
    assert s.memory_slice is not None and s.memory_slice.query == "test"


def test_paused_prompt_default_none() -> None:
    from datetime import UTC, datetime

    from mori.runtime.state import MoriState
    from mori.types import RunId, ThreadId

    state = MoriState(
        run_id=RunId("r1"),
        thread_id=ThreadId("t1"),
        task="x",
        started_at=datetime.now(UTC),
        last_progress_at=datetime.now(UTC),
    )
    assert state.paused_prompt is None


def test_paused_prompt_settable() -> None:
    from datetime import UTC, datetime

    from mori.runtime.state import MoriState
    from mori.types import RunId, ThreadId

    state = MoriState(
        run_id=RunId("r1"),
        thread_id=ThreadId("t1"),
        task="x",
        started_at=datetime.now(UTC),
        last_progress_at=datetime.now(UTC),
        paused_prompt="which db?",
    )
    assert state.paused_prompt == "which db?"
