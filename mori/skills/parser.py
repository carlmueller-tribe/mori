"""Manifest parser and SKILL.md loader."""
from __future__ import annotations
import re
from pathlib import Path
import yaml
from mori.skills.types import SkillManifest, SkillValidationError

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def parse_manifest(skill_dir: str) -> SkillManifest:
    path = Path(skill_dir)
    manifest_path = path / "manifest.yaml"
    if not manifest_path.exists():
        raise SkillValidationError(
            f"manifest.yaml not found in {skill_dir}", path=skill_dir
        )
    raw = yaml.safe_load(manifest_path.read_text())
    if not raw:
        raise SkillValidationError("manifest.yaml is empty", path=skill_dir)

    name = str(raw.get("name", "")).strip()
    if not name:
        raise SkillValidationError("manifest 'name' must be non-empty", path=skill_dir)
    if not _NAME_RE.match(name):
        raise SkillValidationError(
            f"manifest 'name' must be alphanumeric/hyphen/underscore only, got: {name!r}",
            path=skill_dir,
        )

    version = str(raw.get("version", "")).strip()
    if not _SEMVER_RE.match(version):
        raise SkillValidationError(
            f"manifest 'version' must be semver (e.g. '1.0.0'), got: {version!r}",
            path=skill_dir,
        )

    disclosure = raw.get("progressive_disclosure", {})
    abstract = str(disclosure.get("abstract", ""))
    if len(abstract) > 100:
        raise SkillValidationError(
            f"manifest 'abstract' must be < 100 chars, got {len(abstract)}", path=skill_dir
        )

    summary = str(disclosure.get("summary", ""))
    if len(summary) // 4 > 500:
        raise SkillValidationError(
            f"manifest 'summary' exceeds 500 tokens (estimated)", path=skill_dir
        )

    skill_md_path = path / "SKILL.md"
    if not skill_md_path.exists() or skill_md_path.stat().st_size == 0:
        raise SkillValidationError(
            f"SKILL.md not found or empty in {skill_dir}", path=skill_dir
        )

    return SkillManifest(
        name=name,
        version=version,
        description=str(raw.get("description", "")),
        capabilities=list(raw.get("capabilities", [])),
        scope=dict(raw.get("scope", {})),
        preconditions=dict(raw.get("preconditions", {})),
        constraints=dict(raw.get("constraints", {})),
        triggers=dict(raw.get("triggers", {})),
        progressive_disclosure=disclosure,
        skill_dir=skill_dir,
    )


def load_skill_md(skill_dir: str) -> str:
    path = Path(skill_dir) / "SKILL.md"
    return path.read_text()
