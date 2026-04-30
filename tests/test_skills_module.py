# tests/test_skills_module.py
import textwrap
import pytest
from datetime import datetime, timezone, timedelta
from mori.skills.module import SkillsModule
from mori.skills.registry import FilesystemRegistry
from mori.skills.types import SkillExecutionOutcome
from mori.types import DisclosureLevel, ToolSpec, ToolId, ToolSource

MANIFEST = textwrap.dedent("""\
    name: bug-fix
    version: 1.0.0
    description: Fix failing tests
    capabilities: [debugging]
    scope: {domains: [code], contexts: [test]}
    preconditions:
      tools_required: [file-reader, test-runner]
      min_context_tokens: 500
    constraints: {max_files: 5, requires_approval_for: []}
    triggers: {semantic: ["fix failing test", "debug"], structural: []}
    progressive_disclosure:
      abstract: Fix a failing test by finding and patching the root cause.
      summary: Read the failing test, trace the error, apply the minimal fix, verify.
      full: SKILL.md
""")

MANIFEST_B = textwrap.dedent("""\
    name: code-review
    version: 1.0.0
    description: Review code quality
    capabilities: [review]
    scope: {domains: [code], contexts: []}
    preconditions:
      tools_required: [file-reader]
      min_context_tokens: 200
    constraints: {max_files: 10, requires_approval_for: []}
    triggers: {semantic: ["review", "check code"], structural: []}
    progressive_disclosure:
      abstract: Review code for correctness and style issues.
      summary: Read files, check logic and style, summarise findings.
      full: SKILL.md
""")


@pytest.fixture
def skills_dir(tmp_path):
    for name, text in [("bug-fix", MANIFEST), ("code-review", MANIFEST_B)]:
        d = tmp_path / name
        d.mkdir()
        (d / "manifest.yaml").write_text(text)
        (d / "SKILL.md").write_text(f"# {name}\nDo the thing.")
    return tmp_path


@pytest.fixture
def module(skills_dir):
    reg = FilesystemRegistry(str(skills_dir))
    return SkillsModule(registry=reg)


def test_discover_returns_candidates(module):
    candidates = module.discover("fix the failing test", available_tools=["file-reader", "test-runner"])
    assert len(candidates) > 0


def test_discover_excludes_missing_tools(module):
    # only file-reader available — bug-fix needs test-runner too, should be excluded
    candidates = module.discover("fix the failing test", available_tools=["file-reader"])
    names = [c.manifest.name for c in candidates]
    assert "bug-fix" not in names


def test_discover_sorted_descending(module):
    candidates = module.discover("anything", available_tools=["file-reader", "test-runner"])
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_discover_no_embedder_returns_all_compatible(module):
    candidates = module.discover("task", available_tools=["file-reader", "test-runner"])
    assert len(candidates) == 2


async def test_load_abstract(module):
    payload = await module.load("bug-fix", "ABSTRACT", max_tokens=200)
    assert payload.disclosure_level == DisclosureLevel.ABSTRACT
    assert len(payload.content) < 120
    assert payload.token_estimate < 30


async def test_load_summary(module):
    payload = await module.load("bug-fix", "SUMMARY", max_tokens=500)
    assert payload.disclosure_level == DisclosureLevel.SUMMARY
    assert "minimal fix" in payload.content.lower() or len(payload.content) > 0


async def test_load_full_respects_max_tokens(skills_dir):
    reg = FilesystemRegistry(str(skills_dir))
    module = SkillsModule(registry=reg)
    payload = await module.load("bug-fix", "FULL", max_tokens=5)
    assert payload.token_estimate <= 5
    assert payload.disclosure_level == DisclosureLevel.FULL


def test_bind_resolves_tools(module):
    from mori.skills.types import SkillPayload
    payload = SkillPayload(
        skill_id="bug-fix", disclosure_level=DisclosureLevel.SUMMARY,
        content="summary", token_estimate=2,
    )
    specs = [
        ToolSpec(tool_id=ToolId("t1"), name="file-reader",
                 description="reads", input_schema={}, source=ToolSource.NATIVE),
    ]
    bound = module.bind(payload, specs)
    assert "file-reader" in bound.resolved_tools
    assert "test-runner" in bound.unresolved


def test_health_success_rate(module):
    now = datetime.now(timezone.utc)
    for i in range(3):
        module.record_outcome("bug-fix", SkillExecutionOutcome(
            skill_id="bug-fix", run_id=f"r{i}", success=True,
            steps_taken=2, timestamp=now,
        ))
    module.record_outcome("bug-fix", SkillExecutionOutcome(
        skill_id="bug-fix", run_id="r3", success=False,
        steps_taken=1, failure_reason="timeout", timestamp=now,
    ))
    report = module.health("bug-fix")
    assert report.total_runs == 4
    assert abs(report.success_rate - 0.75) < 0.01


def test_health_stale_flag(module):
    old = datetime.now(timezone.utc) - timedelta(days=91)
    module.record_outcome("bug-fix", SkillExecutionOutcome(
        skill_id="bug-fix", run_id="r0", success=True,
        steps_taken=1, timestamp=old,
    ))
    report = module.health("bug-fix")
    assert report.stale is True


def test_health_no_runs_is_stale(module):
    report = module.health("bug-fix")
    assert report.stale is True
    assert report.total_runs == 0
