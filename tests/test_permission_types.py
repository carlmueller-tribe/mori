from mori.permission.types import (
    Condition,
    ConditionType,
    Identity,
    IdentityPattern,
    IdentityType,
    Permission,
    PermissionConfig,
    PermissionResult,
    PermissionRule,
    ResourcePattern,
    ResourceType,
)
from mori.types import PermissionDecision


def test_identity_groups():
    identity = Identity(id="agent:bot", name="bot", type=IdentityType.AGENT, groups=["engineering"])
    assert "engineering" in identity.groups


def test_permission_enum_values():
    assert Permission.READ.value == "r"
    assert Permission.WRITE.value == "w"
    assert Permission.EXECUTE.value == "x"


def test_permission_rule_defaults():
    rule = PermissionRule(
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="deploy_*"),
        identity=IdentityPattern(match="group", value="engineering"),
        permissions="r-x",
        effect="allow",
    )
    assert rule.priority == 100
    assert rule.conditions == []


def test_permission_config_default_deny():
    config = PermissionConfig()
    assert config.default_decision == PermissionDecision.DENY


def test_permission_result_fields():
    result = PermissionResult(decision=PermissionDecision.ALLOW)
    assert result.rule_applied is None
    assert result.explanation == ""


def test_resource_type_values():
    assert ResourceType.TOOL.value == "tool"
    assert ResourceType.MEMORY_LAYER.value == "memory_layer"


def test_condition_operators():
    cond = Condition(type=ConditionType.STEP_COUNT, operator="gt", value=10)
    assert cond.operator == "gt"
    assert cond.value == 10
