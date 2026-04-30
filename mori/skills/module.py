"""SkillsModule — discover, load, bind, record_outcome, health."""
from __future__ import annotations
from collections import Counter, deque
from datetime import datetime, timezone, timedelta
from typing import Any
from mori.skills.parser import load_skill_md
from mori.skills.registry import FilesystemRegistry, CompositeRegistry, SkillRegistry
from mori.skills.types import (
    BoundSkill, CompatibilityReport, SkillCandidate, SkillExecutionOutcome,
    SkillHealthReport, SkillManifest, SkillPayload,
)
from mori.types import DisclosureLevel, ToolSpec


class SkillsModule:
    def __init__(
        self,
        registry: SkillRegistry,
        embedder: Any | None = None,
    ) -> None:
        self._registry = registry
        self._embedder = embedder
        self._health_windows: dict[str, deque[SkillExecutionOutcome]] = {}

    # ── Discover ─────────────────────────────────────────────

    def discover(
        self,
        task: str,
        available_tools: list[str],
        available_tokens: int = 999_999,
        max_candidates: int = 5,
    ) -> list[SkillCandidate]:
        manifests = self._registry.search(task, limit=50)
        candidates: list[SkillCandidate] = []
        for m in manifests:
            report = self._check_compatibility(m, available_tools, available_tokens)
            if not report.tools_satisfied:
                continue
            score = 1.0  # no embedder: uniform score, registry order preserved
            candidates.append(SkillCandidate(manifest=m, score=score,
                                              compatibility_report=report))
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:max_candidates]

    def _check_compatibility(
        self, m: SkillManifest, available_tools: list[str], available_tokens: int
    ) -> CompatibilityReport:
        required = list(m.preconditions.get("tools_required", []))
        missing = [t for t in required if t not in available_tools]
        min_ctx = int(m.preconditions.get("min_context_tokens", 0))
        return CompatibilityReport(
            tools_satisfied=len(missing) == 0,
            missing_tools=missing,
            context_fits=available_tokens >= min_ctx,
            required_tokens=min_ctx,
        )

    # ── Load ─────────────────────────────────────────────────

    async def load(
        self, skill_id: str, disclosure_level: str, max_tokens: int
    ) -> SkillPayload:
        manifests = self._registry.search("", limit=100)
        manifest = next((m for m in manifests if m.name == skill_id), None)
        if manifest is None:
            raise KeyError(f"Skill '{skill_id}' not found in registry")

        pd = manifest.progressive_disclosure
        level = DisclosureLevel(disclosure_level.lower())

        if level == DisclosureLevel.ABSTRACT:
            content = pd.get("abstract", "")
        elif level == DisclosureLevel.SUMMARY:
            content = pd.get("summary", "")
        else:  # FULL
            content = load_skill_md(manifest.skill_dir)
            max_chars = max_tokens * 4
            if len(content) > max_chars:
                content = content[:max_chars]

        token_estimate = len(content) // 4
        return SkillPayload(
            skill_id=skill_id,
            disclosure_level=level,
            content=content,
            token_estimate=token_estimate,
        )

    # ── Bind ─────────────────────────────────────────────────

    def bind(self, payload: SkillPayload, available_tools: list[ToolSpec]) -> BoundSkill:
        manifests = self._registry.search("", limit=100)
        manifest = next((m for m in manifests if m.name == payload.skill_id), None)
        required = list(manifest.preconditions.get("tools_required", [])) if manifest else []
        tool_map = {t.name: t for t in available_tools}
        resolved = {name: tool_map[name] for name in required if name in tool_map}
        unresolved = [name for name in required if name not in tool_map]
        return BoundSkill(payload=payload, resolved_tools=resolved, unresolved=unresolved)

    # ── Health ───────────────────────────────────────────────

    def record_outcome(self, skill_id: str, outcome: SkillExecutionOutcome) -> None:
        if skill_id not in self._health_windows:
            self._health_windows[skill_id] = deque(maxlen=50)
        self._health_windows[skill_id].append(outcome)

    def health(self, skill_id: str) -> SkillHealthReport:
        window = list(self._health_windows.get(skill_id, []))
        total = len(window)
        if total == 0:
            return SkillHealthReport(
                skill_id=skill_id, total_runs=0, success_rate=0.0,
                avg_steps=0.0, common_failures=[], last_used=None, stale=True,
            )
        successes = sum(1 for o in window if o.success)
        avg_steps = sum(o.steps_taken for o in window) / total
        failures = [o.failure_reason for o in window if o.failure_reason]
        common = [reason for reason, _ in Counter(failures).most_common(3)]
        last_used = max(o.timestamp for o in window)
        stale = (datetime.now(timezone.utc) - last_used) > timedelta(days=90)
        return SkillHealthReport(
            skill_id=skill_id,
            total_runs=total,
            success_rate=successes / total,
            avg_steps=avg_steps,
            common_failures=common,
            last_used=last_used,
            stale=stale,
        )
