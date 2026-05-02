"""Tests for mori.types — identifiers, enums, base models."""

import pytest

from mori.types import (
    ImmutableModel,
    Message,
    ModelRequest,
    ModelResponse,
    MoriError,
    MoriModel,
    Phase,
    RegisteredTool,
    RunId,
    RunStatus,
    StepLimitExceeded,
    StepOutcome,
    TokenBudget,
    TokenUsage,
    ToolCall,
    ToolError,
    ToolId,
    ToolInvocationError,
    ToolResult,
    ToolSource,
    ToolSpec,
)


def test_run_id_is_str():
    rid = RunId("run_abc123")
    assert isinstance(rid, str)
    assert rid == "run_abc123"


def test_phase_enum_values():
    assert Phase.RETRIEVE == "retrieve"
    assert Phase.PLAN == "plan"
    assert Phase.VALIDATE == "validate"
    assert Phase.ACT == "act"
    assert Phase.OBSERVE == "observe"
    assert Phase.EVALUATE == "evaluate"
    assert Phase.UPDATE == "update"


def test_run_status_enum_values():
    assert RunStatus.PENDING == "pending"
    assert RunStatus.RUNNING == "running"
    assert RunStatus.PAUSED == "paused"
    assert RunStatus.COMPLETED == "completed"
    assert RunStatus.FAILED == "failed"
    assert RunStatus.TIMEOUT == "timeout"
    assert RunStatus.CANCELLED == "cancelled"


def test_step_outcome_enum_values():
    assert StepOutcome.SUCCESS == "success"
    assert StepOutcome.FAILURE == "failure"
    assert StepOutcome.RETRY == "retry"
    assert StepOutcome.ESCALATE == "escalate"
    assert StepOutcome.SKIP == "skip"


def test_tool_source_enum_values():
    assert ToolSource.NATIVE == "native"
    assert ToolSource.CLI == "cli"
    assert ToolSource.MCP == "mcp"
    assert ToolSource.A2A == "a2a"
    assert ToolSource.OPENAPI == "openapi"


def test_mori_model_rejects_extra_fields():
    class Sample(MoriModel):
        x: int

    with pytest.raises(Exception):
        Sample(x=1, y=2)  # type: ignore[call-arg]


def test_mori_model_allows_mutation():
    class Sample(MoriModel):
        x: int

    s = Sample(x=1)
    s.x = 2
    assert s.x == 2


def test_immutable_model_rejects_mutation():
    class Sample(ImmutableModel):
        x: int

    s = Sample(x=1)
    with pytest.raises(Exception):
        s.x = 2  # type: ignore[misc]


def test_token_budget_remaining():
    b = TokenBudget(allocated=1000, consumed=300)
    assert b.remaining == 700


def test_token_budget_remaining_never_negative():
    b = TokenBudget(allocated=100, consumed=200)
    assert b.remaining == 0


def test_token_budget_utilization():
    b = TokenBudget(allocated=1000, consumed=500)
    assert b.utilization == 0.5


def test_token_budget_utilization_zero_allocated():
    b = TokenBudget(allocated=0, consumed=0)
    assert b.utilization == 0.0


def test_message_with_text_content():
    m = Message(role="user", content="hello")
    assert m.role == "user"
    assert m.content == "hello"


def test_message_with_tool_calls():
    tc = ToolCall(id="call_1", name="add", arguments={"a": 1, "b": 2})
    m = Message(role="assistant", content="", tool_calls=[tc])
    assert len(m.tool_calls) == 1
    assert m.tool_calls[0].name == "add"


def test_token_usage_total():
    u = TokenUsage(input_tokens=100, output_tokens=50)
    assert u.total == 150


def test_tool_spec_defaults():
    spec = ToolSpec(
        tool_id=ToolId("native:add"),
        name="add",
        description="Add numbers",
        input_schema={"type": "object", "properties": {"a": {"type": "integer"}}},
    )
    assert spec.source.value == "native"
    assert spec.tags == []
    assert spec.server_id is None


def test_tool_result_success():
    r = ToolResult(tool_name="add", call_id="call_1", success=True, content="8")
    assert r.success is True
    assert r.error is None


def test_model_request_defaults():
    req = ModelRequest(messages=[Message(role="user", content="hi")])
    assert req.max_tokens == 4096
    assert req.temperature == 0.0


def test_model_response_roundtrip():
    resp = ModelResponse(
        message=Message(role="assistant", content="hi"),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )
    data = resp.model_dump()
    restored = ModelResponse.model_validate(data)
    assert restored.stop_reason == "end_turn"
    assert restored.usage.total == 15


def test_tool_spec_json_roundtrip():
    spec = ToolSpec(
        tool_id=ToolId("native:add"),
        name="add",
        description="Add",
        input_schema={"type": "object"},
    )
    json_str = spec.model_dump_json()
    restored = ToolSpec.model_validate_json(json_str)
    assert restored.name == "add"


def test_registered_tool_holds_callable():
    def my_fn(x: int) -> int:
        return x

    spec = ToolSpec(
        tool_id=ToolId("native:my_fn"),
        name="my_fn",
        description="test",
        input_schema={"type": "object"},
    )
    rt = RegisteredTool(spec=spec, fn=my_fn)
    assert rt.fn is my_fn


def test_mori_error_hierarchy():
    e = StepLimitExceeded("too many steps", details={"limit": 50})
    assert isinstance(e, MoriError)
    assert e.details == {"limit": 50}


def test_tool_error_hierarchy():
    e = ToolInvocationError("failed")
    assert isinstance(e, ToolError)
    assert isinstance(e, MoriError)
