import os, textwrap
import pytest
from mori.skills.parser import parse_manifest, load_skill_md
from mori.skills.types import SkillManifest, SkillValidationError


VALID_YAML = textwrap.dedent("""\
    name: bug-fix
    version: 1.0.0
    description: Fix failing tests
    capabilities:
      - debugging
    scope:
      domains: [code]
      contexts: [test]
    preconditions:
      tools_required: [file-reader, test-runner]
      min_context_tokens: 500
    constraints:
      max_files: 5
      requires_approval_for: []
    triggers:
      semantic: ["fix failing test", "debug"]
      structural: []
    progressive_disclosure:
      abstract: Fix a failing test by isolating and patching the root cause.
      summary: Read the failing test, trace the error, apply minimal fix, verify.
      full: SKILL.md
""")


def test_parse_valid_manifest(tmp_path):
    skill_dir = tmp_path / "bug-fix"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text(VALID_YAML)
    (skill_dir / "SKILL.md").write_text("# Procedure\nDo the fix.")
    m = parse_manifest(str(skill_dir))
    assert isinstance(m, SkillManifest)
    assert m.name == "bug-fix"
    assert m.version == "1.0.0"
    assert m.skill_dir == str(skill_dir)


def test_parse_missing_manifest_raises(tmp_path):
    skill_dir = tmp_path / "no-manifest"
    skill_dir.mkdir()
    with pytest.raises(SkillValidationError, match="manifest.yaml"):
        parse_manifest(str(skill_dir))


def test_parse_invalid_semver_raises(tmp_path):
    skill_dir = tmp_path / "bad-ver"
    skill_dir.mkdir()
    bad = VALID_YAML.replace("version: 1.0.0", "version: notaversion")
    (skill_dir / "manifest.yaml").write_text(bad)
    (skill_dir / "SKILL.md").write_text("x")
    with pytest.raises(SkillValidationError, match="semver"):
        parse_manifest(str(skill_dir))


def test_parse_empty_name_raises(tmp_path):
    skill_dir = tmp_path / "no-name"
    skill_dir.mkdir()
    bad = VALID_YAML.replace("name: bug-fix", "name: ''")
    (skill_dir / "manifest.yaml").write_text(bad)
    (skill_dir / "SKILL.md").write_text("x")
    with pytest.raises(SkillValidationError, match="name"):
        parse_manifest(str(skill_dir))


def test_parse_abstract_too_long_raises(tmp_path):
    skill_dir = tmp_path / "long-abstract"
    skill_dir.mkdir()
    long_abstract = "x" * 101
    bad = VALID_YAML.replace(
        "abstract: Fix a failing test by isolating and patching the root cause.",
        f"abstract: {long_abstract}",
    )
    (skill_dir / "manifest.yaml").write_text(bad)
    (skill_dir / "SKILL.md").write_text("x")
    with pytest.raises(SkillValidationError, match="abstract"):
        parse_manifest(str(skill_dir))


def test_parse_missing_skill_md_raises(tmp_path):
    skill_dir = tmp_path / "no-md"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text(VALID_YAML)
    with pytest.raises(SkillValidationError, match="SKILL.md"):
        parse_manifest(str(skill_dir))


def test_load_skill_md(tmp_path):
    skill_dir = tmp_path / "myskill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Steps\nDo the thing.")
    content = load_skill_md(str(skill_dir))
    assert "Do the thing" in content


def test_name_invalid_chars_raises(tmp_path):
    skill_dir = tmp_path / "bad-name"
    skill_dir.mkdir()
    bad = VALID_YAML.replace("name: bug-fix", "name: 'bad name!'")
    (skill_dir / "manifest.yaml").write_text(bad)
    (skill_dir / "SKILL.md").write_text("x")
    with pytest.raises(SkillValidationError, match="name"):
        parse_manifest(str(skill_dir))
