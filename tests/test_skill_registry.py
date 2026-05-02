# tests/test_skill_registry.py
import textwrap

import pytest

from mori.skills.registry import CompositeRegistry, FilesystemRegistry
from mori.skills.types import SkillManifest

MANIFEST_A = textwrap.dedent("""\
    name: alpha
    version: 1.0.0
    description: Alpha skill
    capabilities: [cap]
    scope: {domains: [], contexts: []}
    preconditions: {tools_required: [], min_context_tokens: 100}
    constraints: {max_files: 5, requires_approval_for: []}
    triggers: {semantic: ["do alpha"], structural: []}
    progressive_disclosure:
      abstract: Alpha abstract (short)
      summary: Alpha summary text for testing.
      full: SKILL.md
""")

MANIFEST_B = textwrap.dedent("""\
    name: beta
    version: 2.0.0
    description: Beta skill
    capabilities: [cap]
    scope: {domains: [], contexts: []}
    preconditions: {tools_required: [file-reader], min_context_tokens: 200}
    constraints: {max_files: 5, requires_approval_for: []}
    triggers: {semantic: ["do beta"], structural: []}
    progressive_disclosure:
      abstract: Beta abstract (short).
      summary: Beta summary text for testing.
      full: SKILL.md
""")


@pytest.fixture
def skills_dir(tmp_path):
    a = tmp_path / "alpha"
    a.mkdir()
    (a / "manifest.yaml").write_text(MANIFEST_A)
    (a / "SKILL.md").write_text("# Alpha\nDo alpha.")
    b = tmp_path / "beta"
    b.mkdir()
    (b / "manifest.yaml").write_text(MANIFEST_B)
    (b / "SKILL.md").write_text("# Beta\nDo beta.")
    return tmp_path


def test_registry_discovers_both_skills(skills_dir):
    reg = FilesystemRegistry(str(skills_dir))
    results = reg.search("anything", limit=10)
    assert len(results) == 2


def test_registry_skips_invalid_skills(skills_dir):
    bad = skills_dir / "broken"
    bad.mkdir()
    (bad / "manifest.yaml").write_text("name: ''\nversion: bad")
    reg = FilesystemRegistry(str(skills_dir))
    results = reg.search("anything", limit=10)
    assert len(results) == 2  # broken is skipped


def test_registry_returns_manifest_objects(skills_dir):
    reg = FilesystemRegistry(str(skills_dir))
    results = reg.search("query", limit=10)
    assert all(isinstance(m, SkillManifest) for m in results)


def test_registry_limit(skills_dir):
    reg = FilesystemRegistry(str(skills_dir))
    results = reg.search("query", limit=1)
    assert len(results) == 1


def test_registry_caches_on_second_call(skills_dir):
    import shutil

    reg = FilesystemRegistry(str(skills_dir))
    r1 = reg.search("q", limit=10)
    shutil.rmtree(skills_dir / "beta")
    r2 = reg.search("q", limit=10)
    assert [m.name for m in r1] == [m.name for m in r2]


def test_registry_empty_dir(tmp_path):
    reg = FilesystemRegistry(str(tmp_path))
    assert reg.search("q") == []


def test_registry_nonexistent_root(tmp_path):
    reg = FilesystemRegistry(str(tmp_path / "does-not-exist"))
    assert reg.search("q") == []


def test_composite_registry_merges(skills_dir, tmp_path):
    dir2 = tmp_path / "extra"
    dir2.mkdir()
    c = dir2 / "gamma"
    c.mkdir()
    (c / "manifest.yaml").write_text(
        textwrap.dedent("""\
        name: gamma
        version: 1.0.0
        description: Gamma
        capabilities: []
        scope: {domains: [], contexts: []}
        preconditions: {tools_required: [], min_context_tokens: 0}
        constraints: {max_files: 1, requires_approval_for: []}
        triggers: {semantic: ["gamma"], structural: []}
        progressive_disclosure:
          abstract: Gamma abstract here.
          summary: Gamma summary.
          full: SKILL.md
    """)
    )
    (c / "SKILL.md").write_text("# Gamma")
    r1 = FilesystemRegistry(str(skills_dir))
    r2 = FilesystemRegistry(str(dir2))
    comp = CompositeRegistry([r1, r2])
    results = comp.search("query", limit=10)
    names = [m.name for m in results]
    assert "alpha" in names
    assert "gamma" in names
