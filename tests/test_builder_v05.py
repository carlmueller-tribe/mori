import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mori import Mori
from mori.permission.types import Identity, IdentityType
from mori.types import Message, ModelResponse, RunStatus, ThreadId, TokenUsage, ToolCall


def _text(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="end_turn",
    )


def test_builder_identity():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .identity(Identity(id="agent:bot", name="bot", type=IdentityType.AGENT, groups=["engineering"]))
            .build()
        )
        assert agent.identity is not None
        assert agent.identity.id == "agent:bot"


def test_builder_checkpointer_inmemory():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").checkpointer("inmemory").build()
        assert agent.checkpointer is not None


def test_builder_checkpointer_file(tmp_path):
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .checkpointer("file", directory=str(tmp_path))
            .build()
        )
        assert agent.checkpointer is not None


def test_builder_checkpointer_sqlite(tmp_path):
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .checkpointer("sqlite", path=str(tmp_path / "ckpts.db"))
            .build()
        )
        assert agent.checkpointer is not None


def test_builder_policy_file(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "rules:\n"
        "  - resource: {type: tool, pattern: \"*\"}\n"
        "    identity: {match: any, value: \"*\"}\n"
        "    permissions: \"r-x\"\n"
        "    effect: allow\n"
    )
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").policy_file(str(policy)).build()
        assert agent.permission is not None


def test_builder_hook():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        fired = []
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .hook("run.end", lambda p: fired.append("end"))
            .build()
        )
        assert agent.hooks is not None
        assert len(agent.hooks.list_hooks("run.end")) == 1


@pytest.mark.asyncio
async def test_mori_resume(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "rules:\n"
        "  - resource: {type: tool, pattern: \"deploy_*\"}\n"
        "    identity: {match: any, value: \"*\"}\n"
        "    permissions: \"--x\"\n"
        "    effect: escalate\n"
        "    priority: 10\n"
    )
    with patch("mori.agent.AnthropicAdapter") as M:
        mock_adapter = AsyncMock()
        mock_adapter.model_id = "test"
        mock_adapter.supports_tool_use = True
        mock_adapter.max_context_tokens = 100000
        mock_adapter.invoke = AsyncMock(side_effect=[
            ModelResponse(
                message=Message(role="assistant", content="",
                    tool_calls=[ToolCall(id="c1", name="deploy_prod", arguments={"version": "1.2.3"})]),
                usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="tool_use",
            ),
            ModelResponse(
                message=Message(role="assistant", content="",
                    tool_calls=[ToolCall(id="c2", name="deploy_prod", arguments={"version": "1.2.3"})]),
                usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="tool_use",
            ),
            _text("deployed successfully"),
        ])
        M.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(lambda version: f"deploying {version}", description="Deploy to prod", name="deploy_prod")
            .checkpointer("inmemory")
            .policy_file(str(policy))
            .build()
        )
        result = await agent.run("Deploy 1.2.3", thread_id="resume_thread")
        assert result.status == RunStatus.PAUSED

        # Swap permission engine to allow-all and resume
        from mori.permission.engine import PermissionEngine
        from mori.permission.types import IdentityPattern, PermissionRule, ResourcePattern
        engine = PermissionEngine()
        engine.load_rules([PermissionRule(
            resource=ResourcePattern(type="*", pattern="*"),
            identity=IdentityPattern(match="any", value="*"),
            permissions="rwx", effect="allow",
        )])
        agent._loop._permission = engine
        result2 = await agent.resume(thread_id="resume_thread", input={"approved": True})
        assert result2.status == RunStatus.COMPLETED
