"""PermissionEngine — deny-wins resolution for Mori permission rules."""
from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any

import anyio

from mori.permission.types import (
    Condition,
    ConditionType,
    Identity,
    IdentityPattern,
    IdentityType,
    Permission,
    PermissionConfig,
    PermissionExplanation,
    PermissionResult,
    PermissionRule,
    Resource,
    ResourcePattern,
    ResourceType,
)
from mori.types import PermissionDecision


class PermissionEngine:
    """Evaluate identity+resource+permission triples against a policy rule set.

    Resolution is deny-wins:
    1. Collect all rules whose identity, resource, and conditions match the query.
    2. If ANY matching rule has effect="deny"     → DENY.
    3. If ANY matching rule has effect="escalate" → ESCALATE.
    4. If ANY matching rule has effect="allow"    → ALLOW.
    5. Otherwise fall back to ``config.default_decision``.
    """

    def __init__(self, config: PermissionConfig) -> None:
        # Work on a mutable copy so mutations don't alias the config list.
        self._config = config.model_copy(deep=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check(
        self,
        identity: Identity,
        resource: Resource,
        permission: Permission,
    ) -> PermissionResult:
        """Async permission check; returns a :class:`PermissionResult`."""
        matching = [
            rule
            for rule in self._config.rules
            if self._rule_matches(rule, identity, resource, permission)
        ]

        # Deny-wins ordering
        for rule in matching:
            if rule.effect == "deny":
                return PermissionResult(
                    decision=PermissionDecision.DENY,
                    rule_applied=rule,
                    explanation=f"Denied by rule (effect=deny): {rule!r}",
                )

        for rule in matching:
            if rule.effect == "escalate":
                return PermissionResult(
                    decision=PermissionDecision.ESCALATE,
                    rule_applied=rule,
                    explanation=f"Escalated by rule (effect=escalate): {rule!r}",
                )

        for rule in matching:
            if rule.effect == "allow":
                return PermissionResult(
                    decision=PermissionDecision.ALLOW,
                    rule_applied=rule,
                    explanation=f"Allowed by rule (effect=allow): {rule!r}",
                )

        # No matching rule — fall back to configured default
        default = self._config.default_decision
        return PermissionResult(
            decision=default,
            rule_applied=None,
            explanation=f"No matching rule; default={default.value}",
        )

    def can(
        self,
        identity: Identity,
        resource: Resource,
        permission: Permission,
    ) -> bool:
        """Synchronous wrapper around :meth:`check`. Returns True iff ALLOW."""
        result = anyio.from_thread.run_sync(
            lambda: anyio.run(self.check, identity, resource, permission)
        ) if False else self._sync_check(identity, resource, permission)
        return result.decision == PermissionDecision.ALLOW

    def _sync_check(
        self,
        identity: Identity,
        resource: Resource,
        permission: Permission,
    ) -> PermissionResult:
        """Run check() synchronously without requiring an existing event loop."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # We're inside an async context — use a new thread/loop via anyio
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.check(identity, resource, permission))
                return future.result()
        else:
            return asyncio.run(self.check(identity, resource, permission))

    async def explain(
        self,
        identity: Identity,
        resource: Resource,
        permission: Permission,
    ) -> PermissionExplanation:
        """Return a full :class:`PermissionExplanation` for a permission query."""
        matching = [
            rule
            for rule in self._config.rules
            if self._rule_matches(rule, identity, resource, permission)
        ]
        result = await self.check(identity, resource, permission)
        return PermissionExplanation(
            identity=identity,
            resource=resource,
            permission=permission,
            decision=result.decision,
            rules_checked=matching,
            rule_applied=result.rule_applied,
            reason=result.explanation,
        )

    def add_rule(self, rule: PermissionRule) -> None:
        """Append a rule to the engine's policy."""
        self._config.rules.append(rule)

    def remove_rule(self, rule: PermissionRule) -> None:
        """Remove a rule from the engine's policy by object identity."""
        self._config.rules = [r for r in self._config.rules if r is not rule]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PermissionEngine":
        """Load a YAML policy file and return a configured :class:`PermissionEngine`.

        Example YAML format::

            default_decision: deny
            rules:
              - identity:
                  match: any
                  value: "*"
                resource:
                  type: tool
                  pattern: "public/*"
                permissions: "r"
                effect: allow
                priority: 10
        """
        import yaml  # lazy import — yaml is optional at module level

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        default_raw = data.get("default_decision", "deny")
        default_decision = PermissionDecision(default_raw.lower())

        rules: list[PermissionRule] = []
        for raw in data.get("rules", []):
            identity_data = raw["identity"]
            resource_data = raw["resource"]

            resource_type_raw = resource_data.get("type", "*")
            if resource_type_raw == "*":
                resource_type: ResourceType | str = "*"
            else:
                resource_type = ResourceType(resource_type_raw.lower())

            rule = PermissionRule(
                identity=IdentityPattern(
                    match=identity_data["match"],
                    value=identity_data["value"],
                ),
                resource=ResourcePattern(
                    type=resource_type,
                    pattern=resource_data["pattern"],
                ),
                permissions=raw["permissions"],
                effect=raw["effect"].lower(),
                priority=raw.get("priority", 100),
                conditions=[
                    Condition(**c) for c in raw.get("conditions", [])
                ],
            )
            rules.append(rule)

        config = PermissionConfig(
            rules=rules,
            default_decision=default_decision,
        )
        return cls(config)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rule_matches(
        self,
        rule: PermissionRule,
        identity: Identity,
        resource: Resource,
        permission: Permission,
    ) -> bool:
        """Return True if the rule applies to this identity/resource/permission."""
        return (
            self._permission_matches(rule, permission)
            and self._identity_matches(rule.identity, identity)
            and self._resource_matches(rule.resource, resource)
            and self._conditions_match(rule.conditions)
        )

    @staticmethod
    def _permission_matches(rule: PermissionRule, permission: Permission) -> bool:
        """Check whether the queried permission is covered by the rule's permissions string."""
        return permission.value in rule.permissions

    @staticmethod
    def _identity_matches(pattern: IdentityPattern, identity: Identity) -> bool:
        """Match an identity against an :class:`IdentityPattern`.

        - ``match="any"``      → always matches
        - ``match="identity"`` → exact id match against ``pattern.value``
        - ``match="group"``    → identity must belong to ``pattern.value`` group
        - ``match="type"``     → identity.type must equal ``pattern.value``
        """
        if pattern.match == "any":
            return True
        if pattern.match == "identity":
            return identity.id == pattern.value
        if pattern.match == "group":
            return pattern.value in identity.groups
        if pattern.match == "type":
            return identity.type.value == pattern.value
        return False  # unknown match type → no match

    @staticmethod
    def _resource_matches(pattern: ResourcePattern, resource: Resource) -> bool:
        """Match a resource against a :class:`ResourcePattern`.

        - ``pattern.type == "*"`` → any resource type matches
        - otherwise the resource type must equal the pattern type
        - ``pattern.pattern`` is matched with ``fnmatch.fnmatch`` (glob)
        """
        # Type check
        if pattern.type != "*":
            if resource.type != pattern.type:
                return False

        # ID / glob check
        return fnmatch.fnmatch(resource.id, pattern.pattern)

    @staticmethod
    def _conditions_match(conditions: list[Condition]) -> bool:
        """Evaluate conditions; empty list → True (always matches).

        All condition types other than ALWAYS are stubbed as True for v0.5.
        Real evaluation (time windows, IP lists, etc.) is out of scope.
        """
        if not conditions:
            return True
        # Stub: all conditions evaluate to True
        return True
