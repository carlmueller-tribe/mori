"""v0.4 exit test — skills discovery and budget rebalance events are emitted."""

from unittest.mock import AsyncMock

import pytest

from mori import Mori
from mori.types import Message, ModelResponse, RunStatus, TokenUsage


def _text_response(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=50, output_tokens=20),
        stop_reason="end_turn",
    )


@pytest.fixture
def skills_root(tmp_path):
    import textwrap

    skills = {
        "bug-fix": (
            textwrap.dedent("""\
                name: bug-fix
                version: 1.0.0
                description: Fix failing tests
                capabilities: [debugging]
                scope: {domains: [code], contexts: [test]}
                preconditions:
                  tools_required: []
                  min_context_tokens: 0
                constraints: {max_files: 5, requires_approval_for: []}
                triggers:
                  semantic: ["fix failing test", "debug", "broken", "error"]
                  structural: []
                progressive_disclosure:
                  abstract: Fix a failing test.
                  summary: Trace and patch the root cause, verify tests pass.
                  full: SKILL.md
            """),
            "# Bug Fix\nReproduce, isolate, patch, verify.",
        ),
        "code-review": (
            textwrap.dedent("""\
                name: code-review
                version: 1.0.0
                description: Review code quality
                capabilities: [review]
                scope: {domains: [code], contexts: []}
                preconditions:
                  tools_required: []
                  min_context_tokens: 0
                constraints: {max_files: 10, requires_approval_for: []}
                triggers:
                  semantic: ["review", "code quality", "check code"]
                  structural: []
                progressive_disclosure:
                  abstract: Review code for correctness and style.
                  summary: Read files, check logic and style, summarise findings.
                  full: SKILL.md
            """),
            "# Code Review\nRead, check, summarise.",
        ),
        "test-generation": (
            textwrap.dedent("""\
                name: test-generation
                version: 1.0.0
                description: Write missing tests
                capabilities: [testing]
                scope: {domains: [code], contexts: []}
                preconditions:
                  tools_required: []
                  min_context_tokens: 0
                constraints: {max_files: 5, requires_approval_for: []}
                triggers:
                  semantic: ["write tests", "add coverage", "unit test"]
                  structural: []
                progressive_disclosure:
                  abstract: Write tests for untested code.
                  summary: Identify gaps, write pytest functions, verify.
                  full: SKILL.md
            """),
            "# Test Generation\nIdentify, write, verify.",
        ),
    }
    for name, (manifest_text, skill_md) in skills.items():
        d = tmp_path / name
        d.mkdir()
        (d / "manifest.yaml").write_text(manifest_text)
        (d / "SKILL.md").write_text(skill_md)
    return tmp_path


@pytest.mark.asyncio
async def test_exit_test_skill_discover_and_budget_rebalance(skills_root):
    """Exit test: run emits skill.discover with top_match_name=bug-fix + budget.rebalance."""
    traces = []

    class Sink:
        realtime = True

        async def write(self, e):
            traces.append(e.model_dump())

        async def write_batch(self, es):
            traces.extend(e.model_dump() for e in es)

        async def flush(self):
            pass

        async def close(self):
            pass

    with pytest.MonkeyPatch().context() as mp:
        from unittest.mock import MagicMock

        mock_adapter = AsyncMock()
        mock_adapter.invoke = AsyncMock(
            return_value=_text_response("I found and fixed the failing test.")
        )
        mock_adapter.model_id = "test"
        mock_adapter.supports_tool_use = True
        mock_adapter.max_context_tokens = 200_000
        mp.setattr("mori.agent.AnthropicAdapter", MagicMock(return_value=mock_adapter))

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .skill_registry(str(skills_root))
            .budget(total_context_tokens=200_000)
            .sink("stdout")
            .checkpointer("inmemory")
            .build()
        )
        # Inject our trace sink directly
        from mori.observability.engine import ObservabilityEngine
        from mori.observability.events import ObservabilityConfig

        agent._obs = ObservabilityEngine(sinks=[Sink()], config=ObservabilityConfig())
        agent._loop._obs = agent._obs

        result = await agent.run("Fix the failing test in tests/test_auth.py")
        await agent._obs.flush()

    assert result.status == RunStatus.COMPLETED

    skill_events = [e for e in traces if e["event_type"] == "skill.discover"]
    budget_events = [e for e in traces if e["event_type"] == "budget.rebalance"]

    assert len(skill_events) > 0, "No skill.discover events emitted"
    assert (
        skill_events[0]["top_match_name"] == "bug-fix"
    ), f"Expected top_match_name='bug-fix', got {skill_events[0].get('top_match_name')!r}"
    assert len(budget_events) > 0, "No budget.rebalance events emitted"

    await agent.close()
