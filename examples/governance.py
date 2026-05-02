"""v0.5 governance demo — permission engine + hooks + escalate/resume."""

import asyncio
from unittest.mock import AsyncMock, patch

from mori import Mori
from mori.permission.engine import PermissionEngine
from mori.permission.types import (
    Identity,
    IdentityPattern,
    IdentityType,
    PermissionRule,
    ResourcePattern,
    ResourceType,
)
from mori.types import Message, ModelResponse, RunStatus, TokenUsage, ToolCall


async def main():
    with patch("mori.agent.AnthropicAdapter") as M:
        mock_adapter = AsyncMock()
        mock_adapter.model_id = "test"
        mock_adapter.supports_tool_use = True
        mock_adapter.max_context_tokens = 100000
        mock_adapter.invoke = AsyncMock(
            side_effect=[
                ModelResponse(
                    message=Message(
                        role="assistant",
                        content="",
                        tool_calls=[
                            ToolCall(id="c1", name="deploy_prod", arguments={"version": "2.0.0"})
                        ],
                    ),
                    usage=TokenUsage(input_tokens=20, output_tokens=8),
                    stop_reason="tool_use",
                ),
                ModelResponse(
                    message=Message(
                        role="assistant",
                        content="",
                        tool_calls=[
                            ToolCall(id="c2", name="deploy_prod", arguments={"version": "2.0.0"})
                        ],
                    ),
                    usage=TokenUsage(input_tokens=25, output_tokens=8),
                    stop_reason="tool_use",
                ),
                ModelResponse(
                    message=Message(
                        role="assistant", content="Deployment complete. Version 2.0.0 is live."
                    ),
                    usage=TokenUsage(input_tokens=30, output_tokens=15),
                    stop_reason="end_turn",
                ),
            ]
        )
        M.return_value = mock_adapter

        hook_log = []

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(
                lambda version: f"deployed {version}",
                description="Deploy to prod",
                name="deploy_prod",
            )
            .identity(Identity(id="agent:release-bot", name="release-bot", type=IdentityType.AGENT))
            .checkpointer("inmemory")
            .hook("run.end", lambda p: hook_log.append(f"run.end:{p['status'].value}"))
            .build()
        )

        # Load escalate policy
        engine = PermissionEngine()
        engine.load_rules(
            [
                PermissionRule(
                    resource=ResourcePattern(type=ResourceType.TOOL, pattern="deploy_*"),
                    identity=IdentityPattern(match="any", value="*"),
                    permissions="--x",
                    effect="escalate",
                    priority=5,
                )
            ]
        )
        agent._loop._permission = engine

        print("=== Run 1: initial deploy request ===")
        result = await agent.run("Deploy version 2.0.0 to production", thread_id="deploy-2.0.0")
        print(f"Status: {result.status.value}")
        print(f"Checkpoint: {result.checkpoint_id}")
        assert result.status == RunStatus.PAUSED

        # Operator approves; swap to allow-all policy
        engine2 = PermissionEngine()
        engine2.load_rules(
            [
                PermissionRule(
                    resource=ResourcePattern(type="*", pattern="*"),
                    identity=IdentityPattern(match="any", value="*"),
                    permissions="rwx",
                    effect="allow",
                )
            ]
        )
        agent._loop._permission = engine2

        print("\n=== Run 2: resume after operator approval ===")
        result2 = await agent.resume(
            thread_id="deploy-2.0.0", input={"approved": True, "approved_by": "carl"}
        )
        print(f"Status: {result2.status.value}")
        print(f"Final output: {result2.final_output}")
        print(f"Hooks fired: {hook_log}")
        assert result2.status == RunStatus.COMPLETED
        print("\n✓ Governance demo complete")


if __name__ == "__main__":
    asyncio.run(main())
