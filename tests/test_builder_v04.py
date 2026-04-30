# tests/test_builder_v04.py
from unittest.mock import AsyncMock, patch
import pytest
from mori import Mori
from mori.types import Message, ModelResponse, RunStatus, TokenUsage


def _text_response(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


def test_builder_skill_registry(tmp_path):
    import textwrap
    d = tmp_path / "bug-fix"
    d.mkdir()
    (d / "manifest.yaml").write_text(textwrap.dedent("""\
        name: bug-fix
        version: 1.0.0
        description: Fix tests
        capabilities: []
        scope: {domains: [], contexts: []}
        preconditions: {tools_required: [], min_context_tokens: 0}
        constraints: {max_files: 5, requires_approval_for: []}
        triggers: {semantic: ["fix"], structural: []}
        progressive_disclosure:
          abstract: Fix a test.
          summary: Fix it.
          full: SKILL.md
    """))
    (d / "SKILL.md").write_text("# Fix\nDo it.")
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .skill_registry(str(tmp_path))
            .build()
        )
        assert agent.skills is not None


def test_builder_budget():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .budget(total_context_tokens=100_000)
            .build()
        )
        assert agent.budget is not None


def test_builder_no_skill_registry():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").build()
        assert agent.skills is None


def test_builder_no_budget():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").build()
        assert agent.budget is None


def test_builder_order_independent(tmp_path):
    import textwrap
    d = tmp_path / "s"
    d.mkdir()
    (d / "manifest.yaml").write_text(textwrap.dedent("""\
        name: s
        version: 1.0.0
        description: S
        capabilities: []
        scope: {domains: [], contexts: []}
        preconditions: {tools_required: [], min_context_tokens: 0}
        constraints: {max_files: 1, requires_approval_for: []}
        triggers: {semantic: [], structural: []}
        progressive_disclosure:
          abstract: Short abstract.
          summary: Summary.
          full: SKILL.md
    """))
    (d / "SKILL.md").write_text("# S")
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        # skill_registry before budget
        a1 = (Mori.builder().model("anthropic", api_key="x")
              .skill_registry(str(tmp_path)).budget(total_context_tokens=50_000).build())
        # budget before skill_registry
        a2 = (Mori.builder().model("anthropic", api_key="x")
              .budget(total_context_tokens=50_000).skill_registry(str(tmp_path)).build())
        assert a1.skills is not None and a1.budget is not None
        assert a2.skills is not None and a2.budget is not None


@pytest.mark.asyncio
async def test_agent_run_with_skills_and_budget(tmp_path):
    import textwrap
    d = tmp_path / "bug-fix"
    d.mkdir()
    (d / "manifest.yaml").write_text(textwrap.dedent("""\
        name: bug-fix
        version: 1.0.0
        description: Fix
        capabilities: []
        scope: {domains: [], contexts: []}
        preconditions: {tools_required: [], min_context_tokens: 0}
        constraints: {max_files: 5, requires_approval_for: []}
        triggers: {semantic: ["fix test"], structural: []}
        progressive_disclosure:
          abstract: Fix a failing test.
          summary: Trace and patch.
          full: SKILL.md
    """))
    (d / "SKILL.md").write_text("# Fix\nDo it.")
    with patch("mori.agent.AnthropicAdapter") as M:
        mock = AsyncMock()
        mock.invoke = AsyncMock(return_value=_text_response("fixed"))
        M.return_value = mock
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .skill_registry(str(tmp_path))
            .budget(total_context_tokens=100_000)
            .build()
        )
        result = await agent.run("fix the failing test")
        assert result.status == RunStatus.COMPLETED
        await agent.close()
