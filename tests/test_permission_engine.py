"""Tests for PermissionEngine — TDD, written before implementation."""
from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

import pytest

from mori.permission.engine import PermissionEngine
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _identity(id: str, groups: list[str] | None = None, type: IdentityType = IdentityType.AGENT) -> Identity:
    return Identity(id=id, name=id, type=type, groups=groups or [])


def _resource(id: str, type: ResourceType = ResourceType.TOOL) -> Resource:
    return Resource(id=id, type=type)


def _allow_rule(
    identity_match: str = "identity",
    identity_value: str = "agent:bot",
    resource_type: ResourceType | str = ResourceType.TOOL,
    resource_pattern: str = "deploy",
    permissions: str = "r",
) -> PermissionRule:
    return PermissionRule(
        identity=IdentityPattern(match=identity_match, value=identity_value),
        resource=ResourcePattern(type=resource_type, pattern=resource_pattern),
        permissions=permissions,
        effect="allow",
    )


def _deny_rule(
    identity_match: str = "identity",
    identity_value: str = "agent:bot",
    resource_type: ResourceType | str = ResourceType.TOOL,
    resource_pattern: str = "deploy",
    permissions: str = "r",
) -> PermissionRule:
    return PermissionRule(
        identity=IdentityPattern(match=identity_match, value=identity_value),
        resource=ResourcePattern(type=resource_type, pattern=resource_pattern),
        permissions=permissions,
        effect="deny",
    )


# ---------------------------------------------------------------------------
# 1. test_engine_allow_rule
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_allow_rule():
    """ALLOW rule for specific identity+resource+permission → result allowed."""
    rule = _allow_rule()
    config = PermissionConfig(rules=[rule])
    engine = PermissionEngine(config)

    result = await engine.check(
        _identity("agent:bot"),
        _resource("deploy"),
        Permission.READ,
    )
    assert result.decision == PermissionDecision.ALLOW
    assert result.rule_applied == rule


# ---------------------------------------------------------------------------
# 2. test_engine_deny_wins
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_deny_wins():
    """One ALLOW and one DENY rule both match → DENY wins."""
    allow = _allow_rule(permissions="r")
    deny = _deny_rule(permissions="r")
    config = PermissionConfig(rules=[allow, deny])
    engine = PermissionEngine(config)

    result = await engine.check(
        _identity("agent:bot"),
        _resource("deploy"),
        Permission.READ,
    )
    assert result.decision == PermissionDecision.DENY


# ---------------------------------------------------------------------------
# 3. test_engine_default_deny
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_default_deny():
    """No matching rules → default_decision=DENY → result.allowed is False."""
    config = PermissionConfig(default_decision=PermissionDecision.DENY)
    engine = PermissionEngine(config)

    result = await engine.check(
        _identity("agent:bot"),
        _resource("deploy"),
        Permission.READ,
    )
    assert result.decision == PermissionDecision.DENY
    assert result.rule_applied is None


# ---------------------------------------------------------------------------
# 4. test_engine_wildcard_identity
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_wildcard_identity():
    """IdentityPattern(match='any') matches any identity."""
    rule = PermissionRule(
        identity=IdentityPattern(match="any", value="*"),
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="public_tool"),
        permissions="r",
        effect="allow",
    )
    config = PermissionConfig(rules=[rule])
    engine = PermissionEngine(config)

    result = await engine.check(
        _identity("some-random-agent"),
        _resource("public_tool"),
        Permission.READ,
    )
    assert result.decision == PermissionDecision.ALLOW


# ---------------------------------------------------------------------------
# 5. test_engine_glob_resource
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_glob_resource():
    """ResourcePattern glob pattern='data/*' matches resource id 'data/records'."""
    rule = PermissionRule(
        identity=IdentityPattern(match="any", value="*"),
        resource=ResourcePattern(type=ResourceType.FILE_PATH, pattern="data/*"),
        permissions="r",
        effect="allow",
    )
    config = PermissionConfig(rules=[rule])
    engine = PermissionEngine(config)

    result = await engine.check(
        _identity("user:alice"),
        _resource("data/records", type=ResourceType.FILE_PATH),
        Permission.READ,
    )
    assert result.decision == PermissionDecision.ALLOW


# ---------------------------------------------------------------------------
# 6. test_engine_escalate
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_escalate():
    """ESCALATE rule matches → decision == ESCALATE."""
    rule = PermissionRule(
        identity=IdentityPattern(match="any", value="*"),
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="sensitive_tool"),
        permissions="x",
        effect="escalate",
    )
    config = PermissionConfig(rules=[rule])
    engine = PermissionEngine(config)

    result = await engine.check(
        _identity("agent:bot"),
        _resource("sensitive_tool"),
        Permission.EXECUTE,
    )
    assert result.decision == PermissionDecision.ESCALATE


# ---------------------------------------------------------------------------
# 7. test_engine_can_sync
# ---------------------------------------------------------------------------

def test_engine_can_sync():
    """can() returns bool — True for ALLOW, False for DENY/ESCALATE."""
    allow_rule = _allow_rule()
    config = PermissionConfig(rules=[allow_rule])
    engine = PermissionEngine(config)

    assert engine.can(_identity("agent:bot"), _resource("deploy"), Permission.READ) is True
    # no matching rule → default DENY → False
    assert engine.can(_identity("agent:bot"), _resource("other"), Permission.READ) is False


# ---------------------------------------------------------------------------
# 8. test_engine_explain
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_explain():
    """explain() returns PermissionExplanation with correct fields."""
    rule = _allow_rule()
    config = PermissionConfig(rules=[rule])
    engine = PermissionEngine(config)

    identity = _identity("agent:bot")
    resource = _resource("deploy")
    perm = Permission.READ

    explanation = await engine.explain(identity, resource, perm)

    assert isinstance(explanation, PermissionExplanation)
    assert explanation.identity == identity
    assert explanation.resource == resource
    assert explanation.permission == perm
    assert explanation.decision == PermissionDecision.ALLOW
    assert explanation.rule_applied == rule
    assert len(explanation.rules_checked) >= 1


# ---------------------------------------------------------------------------
# 9. test_engine_add_remove_rule
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_add_remove_rule():
    """add_rule and remove_rule modify the engine's rule set."""
    config = PermissionConfig()
    engine = PermissionEngine(config)

    # Initially no rules → DENY
    result = await engine.check(_identity("agent:bot"), _resource("deploy"), Permission.READ)
    assert result.decision == PermissionDecision.DENY

    rule = PermissionRule(
        id="test-rule",
        identity=IdentityPattern(match="identity", value="agent:bot"),
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="deploy"),
        permissions="r",
        effect="allow",
    )
    engine.add_rule(rule)

    result = await engine.check(_identity("agent:bot"), _resource("deploy"), Permission.READ)
    assert result.decision == PermissionDecision.ALLOW

    engine.remove_rule("test-rule")

    result = await engine.check(_identity("agent:bot"), _resource("deploy"), Permission.READ)
    assert result.decision == PermissionDecision.DENY


# ---------------------------------------------------------------------------
# 10. test_engine_from_yaml
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_from_yaml():
    """load a YAML file, verify engine grants correct decision via check()."""
    yaml_content = textwrap.dedent("""\
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
    """)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    engine = PermissionEngine.from_yaml(tmp_path)

    # Matching resource → ALLOW
    result = await engine.check(
        _identity("any-user"),
        _resource("public/tool-a"),
        Permission.READ,
    )
    assert result.decision == PermissionDecision.ALLOW

    # Non-matching resource → DENY (default)
    result = await engine.check(
        _identity("any-user"),
        _resource("private/secret"),
        Permission.READ,
    )
    assert result.decision == PermissionDecision.DENY


# ---------------------------------------------------------------------------
# 11. test_engine_group_match
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_group_match():
    """IdentityPattern(match='group', value='admins') matches identity with that group."""
    rule = PermissionRule(
        identity=IdentityPattern(match="group", value="admins"),
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="admin_tool"),
        permissions="x",
        effect="allow",
    )
    config = PermissionConfig(rules=[rule])
    engine = PermissionEngine(config)

    # Identity in admins group → ALLOW
    admin = _identity("user:alice", groups=["admins", "engineering"])
    result = await engine.check(admin, _resource("admin_tool"), Permission.EXECUTE)
    assert result.decision == PermissionDecision.ALLOW

    # Identity NOT in admins group → DENY (default)
    non_admin = _identity("user:bob", groups=["engineering"])
    result = await engine.check(non_admin, _resource("admin_tool"), Permission.EXECUTE)
    assert result.decision == PermissionDecision.DENY


# ---------------------------------------------------------------------------
# 12. test_engine_type_match
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_type_match():
    """IdentityPattern(match='type', value='user') matches any USER identity."""
    rule = PermissionRule(
        identity=IdentityPattern(match="type", value="user"),
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="user_tool"),
        permissions="r",
        effect="allow",
    )
    config = PermissionConfig(rules=[rule])
    engine = PermissionEngine(config)

    user = _identity("user:alice", type=IdentityType.USER)
    result = await engine.check(user, _resource("user_tool"), Permission.READ)
    assert result.decision == PermissionDecision.ALLOW

    agent = _identity("agent:bot", type=IdentityType.AGENT)
    result = await engine.check(agent, _resource("user_tool"), Permission.READ)
    assert result.decision == PermissionDecision.DENY


# ---------------------------------------------------------------------------
# 13. test_engine_deny_beats_escalate
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_engine_deny_beats_escalate():
    """DENY wins over ESCALATE and ALLOW."""
    rules = [
        PermissionRule(
            id="r-allow",
            identity=IdentityPattern(match="any", value="*"),
            resource=ResourcePattern(type="*", pattern="*"),
            permissions="rwx",
            effect="allow",
        ),
        PermissionRule(
            id="r-escalate",
            identity=IdentityPattern(match="any", value="*"),
            resource=ResourcePattern(type="*", pattern="*"),
            permissions="rwx",
            effect="escalate",
        ),
        PermissionRule(
            id="r-deny",
            identity=IdentityPattern(match="any", value="*"),
            resource=ResourcePattern(type="*", pattern="*"),
            permissions="rwx",
            effect="deny",
        ),
    ]
    config = PermissionConfig(rules=rules, default_decision=PermissionDecision.ALLOW)
    engine = PermissionEngine(config)

    result = await engine.check(
        _identity("user:alice", type=IdentityType.USER),
        _resource("data/x", type=ResourceType.FILE_PATH),
        Permission.READ,
    )
    assert result.decision == PermissionDecision.DENY


# ---------------------------------------------------------------------------
# 14. test_engine_remove_rule_unknown_id
# ---------------------------------------------------------------------------

def test_engine_remove_rule_unknown_id():
    """remove_rule raises KeyError for an unknown rule ID."""
    config = PermissionConfig()
    engine = PermissionEngine(config)
    with pytest.raises(KeyError):
        engine.remove_rule("does-not-exist")
