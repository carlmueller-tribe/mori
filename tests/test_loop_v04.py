# tests/test_loop_v04.py
import pytest
from unittest.mock import AsyncMock
from mori.budget.manager import BudgetManager
from mori.budget.types import BudgetConfig
from mori.model.base import ModelAdapter
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import ObservabilityConfig
from mori.runtime.loop import AgentLoop
from mori.skills.module import SkillsModule
from mori.skills.registry import FilesystemRegistry
from mori.tools.registry import ToolRegistry
from mori.types import Message, ModelResponse, RunStatus, TokenUsage
import textwrap


MANIFEST = textwrap.dedent("""\
    name: bug-fix
    version: 1.0.0
    description: Fix failing tests
    capabilities: [debug]
    scope: {domains: [], contexts: []}
    preconditions:
      tools_required: []
      min_context_tokens: 0
    constraints: {max_files: 5, requires_approval_for: []}
    triggers: {semantic: ["fix test"], structural: []}
    progressive_disclosure:
      abstract: Fix a failing test.
      summary: Read test, trace error, patch, verify.
      full: SKILL.md
""")


def _text_response(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


@pytest.fixture
def mock_model():
    m = AsyncMock(spec=ModelAdapter)
    m.model_id = "test"
    m.supports_tool_use = True
    m.max_context_tokens = 100_000
    m.invoke = AsyncMock(return_value=_text_response("done"))
    return m


@pytest.fixture
def skills_module(tmp_path):
    d = tmp_path / "bug-fix"
    d.mkdir()
    (d / "manifest.yaml").write_text(MANIFEST)
    (d / "SKILL.md").write_text("# Bug Fix\nDo the thing.")
    reg = FilesystemRegistry(str(tmp_path))
    return SkillsModule(registry=reg)


async def test_loop_with_skills_emits_discover_event(mock_model, skills_module):
    collected = []
    class Sink:
        realtime = True
        async def write(self, e): collected.append(e)
        async def write_batch(self, es): collected.extend(es)
        async def flush(self): pass
        async def close(self): pass
    obs = ObservabilityEngine(sinks=[Sink()], config=ObservabilityConfig(buffer_size=100))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), observability=obs,
                     skills=skills_module)
    await loop.run("fix test")
    await obs.flush()
    types = [e.event_type for e in collected]
    assert "skill.discover" in types


async def test_loop_with_skills_injects_skill_context(mock_model, skills_module):
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), skills=skills_module)
    await loop.run("fix test")
    request = mock_model.invoke.call_args[0][0]
    system_contents = " ".join(
        m.content for m in request.messages if m.role == "system"
        and isinstance(m.content, str)
    )
    assert "[Skill Context]" in system_contents


async def test_loop_without_skills_still_works(mock_model):
    loop = AgentLoop(model=mock_model, tools=ToolRegistry())
    result = await loop.run("task")
    assert result.status == RunStatus.COMPLETED


async def test_loop_with_budget_emits_rebalance_event(mock_model):
    collected = []
    class Sink:
        realtime = True
        async def write(self, e): collected.append(e)
        async def write_batch(self, es): collected.extend(es)
        async def flush(self): pass
        async def close(self): pass
    obs = ObservabilityEngine(sinks=[Sink()], config=ObservabilityConfig(buffer_size=100))
    budget = BudgetManager(BudgetConfig(total_context_tokens=50_000))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(),
                     observability=obs, budget=budget)
    await loop.run("task")
    await obs.flush()
    types = [e.event_type for e in collected]
    assert "budget.rebalance" in types


async def test_loop_without_budget_still_works(mock_model):
    loop = AgentLoop(model=mock_model, tools=ToolRegistry())
    result = await loop.run("task")
    assert result.status == RunStatus.COMPLETED
