"""FilesystemRegistry and CompositeRegistry for skill discovery."""
from __future__ import annotations
import logging
from pathlib import Path
from mori.skills.parser import parse_manifest
from mori.skills.types import SkillManifest, SkillValidationError

logger = logging.getLogger(__name__)


class FilesystemRegistry:
    def __init__(self, root: str, embedder: object | None = None) -> None:
        self._root = Path(root)
        self._embedder = embedder
        self._cache: list[SkillManifest] | None = None

    def _load(self) -> list[SkillManifest]:
        if self._cache is not None:
            return self._cache
        manifests: list[SkillManifest] = []
        for candidate in sorted(self._root.iterdir()):
            if not candidate.is_dir():
                continue
            try:
                m = parse_manifest(str(candidate))
                manifests.append(m)
            except SkillValidationError as exc:
                logger.warning("Skipping invalid skill %s: %s", candidate.name, exc)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error loading skill %s: %s", candidate.name, exc)
        self._cache = manifests
        return manifests

    def search(self, query: str, limit: int = 10) -> list[SkillManifest]:
        manifests = self._load()
        # Without embedder: return all in directory order
        return manifests[:limit]


class CompositeRegistry:
    def __init__(self, registries: list[FilesystemRegistry]) -> None:
        self._registries = registries

    def search(self, query: str, limit: int = 10) -> list[SkillManifest]:
        seen: set[str] = set()
        results: list[SkillManifest] = []
        for reg in self._registries:
            for m in reg.search(query, limit=limit):
                if m.name not in seen:
                    seen.add(m.name)
                    results.append(m)
        return results[:limit]
