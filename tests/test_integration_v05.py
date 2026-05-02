"""v0.5 exit test — permission check events appear in JSONL traces."""
import json
import pytest
from unittest.mock import AsyncMock, patch

from mori import Mori
from mori.permission.types import Identity, IdentityType
from mori.types import Message, ModelResponse, RunStatus, TokenUsage, ToolCall


@pytest.mark.asyncio
async def test_exit_v05_escalate_pauses_and_events_in_traces(tmp_path):
    traces_path = tmp_path / "traces.jsonl"
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "rules:\n"
        "  - resource: {type: tool, pattern: \"deploy_*\"}\n"
        "    identity: {match: type, value: agent}\n"
        "    permissions: \"--x\"\n"
        "    effect: escalate\n"
        "    priority: 10\n"
    )
    with patch("mori.agent.AnthropicAdapter") as M:
        mock_adapter = AsyncMock()
        mock_adapter.model_id = "test"
        mock_adapter.supports_tool_use = True
        mock_adapter.max_context_tokens = 100000
        mock_adapter.invoke = AsyncMock(return_value=ModelResponse(
            message=Message(
                role="assistant", content="",
                tool_calls=[ToolCall(id="c1", name="deploy_prod", arguments={"version": "1.2.3"})],
            ),
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            stop_reason="tool_use",
        ))
        M.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(lambda version: f"deploying {version}", description="Deploy to prod", name="deploy_prod")
            .identity(Identity(id="agent:bot", name="bot", type=IdentityType.AGENT))
            .checkpointer("inmemory")
            .policy_file(str(policy))
            .sink("jsonl", path=str(traces_path))
            .build()
        )
        result = await agent.run("Deploy version 1.2.3", thread_id="exit_test")

    assert result.status == RunStatus.PAUSED

    traces = [json.loads(line) for line in traces_path.read_text().splitlines() if line.strip()]
    perm_events = [e for e in traces if e["event_type"] == "permission.check"]
    assert len(perm_events) > 0, "No permission.check events found in traces"
    assert any(e["decision"] in ("deny", "escalate") for e in perm_events), \
        "No deny/escalate decision in permission events"
