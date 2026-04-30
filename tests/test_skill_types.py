import pytest
from mori.skills.types import (
    SkillManifest, SkillCandidate, CompatibilityReport,
    SkillPayload, BoundSkill, SkillExecutionOutcome,
    SkillHealthReport, SkillValidationError,
)
from mori.types import DisclosureLevel, ToolSpec, ToolId, ToolSource


def _make_manifest(**kwargs):
    base = dict(
        name="my-skill", version="1.0.0", description="Test",
        capabilities=["cap1"], scope={"domains": [], "contexts": []},
        preconditions={"tools_required": [], "min_context_tokens": 100},
        constraints={"max_files": 10, "requires_approval_for": []},
        triggers={"semantic": ["fix bug"], "structural": []},
        progressive_disclosure={
            "abstract": "Short abstract",
            "summary": "Longer summary text here",
            "full": "SKILL.md",
        },
        skill_dir="/tmp/test",
    )
    base.update(kwargs)
    return SkillManifest(**base)


def test_skill_manifest_basic():
    m = _make_manifest()
    assert m.name == "my-skill"
    assert m.version == "1.0.0"


def test_skill_payload_token_estimate():
    p = SkillPayload(
        skill_id="my-skill",
        disclosure_level=DisclosureLevel.SUMMARY,
        content="hello world",
        token_estimate=3,
    )
    assert p.token_estimate == 3


def test_bound_skill_unresolved():
    manifest = _make_manifest()
    spec = ToolSpec(
        tool_id=ToolId("t1"), name="file-reader",
        description="reads files", input_schema={}, source=ToolSource.NATIVE,
    )
    payload = SkillPayload(
        skill_id="my-skill", disclosure_level=DisclosureLevel.SUMMARY,
        content="summary", token_estimate=2,
    )
    b = BoundSkill(
        payload=payload,
        resolved_tools={"file-reader": spec},
        unresolved=["missing-tool"],
    )
    assert "file-reader" in b.resolved_tools
    assert "missing-tool" in b.unresolved


def test_skill_validation_error_is_exception():
    err = SkillValidationError("bad manifest", path="/tmp/x")
    assert "bad manifest" in str(err)
    assert isinstance(err, Exception)


def test_skill_execution_outcome():
    from datetime import datetime, timezone
    o = SkillExecutionOutcome(
        skill_id="my-skill", run_id="run_1", success=True,
        steps_taken=3, failure_reason=None,
        timestamp=datetime.now(timezone.utc),
    )
    assert o.success is True
