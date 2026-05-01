# v0.5 "It's Governed" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Unix-style permission checks, pluggable checkpoint persistence, and priority-ordered lifecycle hooks — so the agent can be paused on ESCALATE and resumed after approval.

**Architecture:** Three new modules (`mori.permission`, `mori.control.checkpoint`, `mori.hooks`) slot into the existing loop. The loop gains three optional dependencies — `permission`, `checkpointer`, `hooks` — all nil-safe so existing tests continue to pass. ESCALATE decisions set `state.status = PAUSED` and save a checkpoint; `AgentLoop.resume()` restores the checkpoint and re-enters the loop. Hooks are dispatched at six lifecycle events: `run.start`, `run.end`, `tool.invoke.before/after`, `model.request.before`, `model.response.after`, `permission.check.after`.

**Tech Stack:** Python 3.11, pydantic v2, anyio, PyYAML (already installed), fnmatch (stdlib), sqlite3 (stdlib)

---

## File Map

**Create:**
- `mori/permission/__init__.py`
- `mori/permission/types.py` — Identity, IdentityType, Resource, ResourceType, Permission, PermissionRule, ResourcePattern, IdentityPattern, Condition, ConditionType, PermissionResult, PermissionExplanation, PermissionConfig
- `mori/permission/engine.py` — PermissionEngine (resolution algorithm, YAML loader, fnmatch)
- `mori/control/checkpoint.py` — Checkpoint model, CheckpointStore Protocol, InMemoryCheckpoints, FileCheckpoints, SQLiteCheckpoints
- `mori/hooks/__init__.py`
- `mori/hooks/types.py` — HookConfig, HookHandler, HookRegistration
- `mori/hooks/registry.py` — HookRegistry
- `tests/test_permission_types.py`
- `tests/test_permission_engine.py`
- `tests/test_checkpoint.py`
- `tests/test_hooks.py`
- `tests/test_loop_v05.py`
- `tests/test_builder_v05.py`
- `tests/test_integration_v05.py`
- `examples/governance.py`

**Modify:**
- `mori/observability/events.py` — add `PermissionCheckEvent`
- `mori/runtime/state.py` — add `paused_reason`, `paused_tool_call`
- `mori/runtime/loop.py` — add permission/checkpoint/hook params; refactor into `_run_from_state()` + `resume()`
- `mori/runtime/result.py` — add `checkpoint_id` param to `from_state()`
- `mori/agent.py` — add `.identity()`, `.policy_file()`, `.checkpointer()`, `.hook()`; add `Mori.resume()`

**Notes on existing types (no changes needed):**
- `PermissionDecision` (ALLOW/DENY/ESCALATE) already lives in `mori/types.py:67`
- `RunStatus.PAUSED` already exists in `mori/types.py:39`
- `CheckpointId`, `ThreadId` already in `mori/types.py`
- `RunResult.checkpoint_id: CheckpointId | None = None` already in `mori/runtime/result.py`

---

## Task 1: Permission Types

**Files:**
- Create: `mori/permission/__init__.py`
- Create: `mori/permission/types.py`
- Create: `tests/test_permission_types.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_permission_types.py
from mori.permission.types import (
    Condition, ConditionType, Identity, IdentityPattern, IdentityType,
    Permission, PermissionConfig, PermissionExplanation, PermissionResult,
    PermissionRule, Resource, ResourcePattern, ResourceType,
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_permission_types.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'mori.permission'`

- [ ] **Step 3: Create the permission package**

```python
# mori/permission/__init__.py
"""Permission system for Mori — identity, resources, rules, engine."""
```

```python
# mori/permission/types.py
"""Permission system types — identities, resources, rules, results."""
from __future__ import annotations

from typing import Any, Literal
from enum import Enum
from pydantic import Field

from mori.types import MoriModel, PermissionDecision


class IdentityType(str, Enum):
    USER = "user"
    AGENT = "agent"
    SKILL = "skill"
    SERVICE = "service"
    SYSTEM = "system"


class Identity(MoriModel):
    id: str
    name: str
    type: IdentityType
    groups: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceType(str, Enum):
    TOOL = "tool"
    SKILL = "skill"
    MEMORY_LAYER = "memory_layer"
    MCP_SERVER = "mcp_server"
    AGENT = "agent"
    FILE_PATH = "file_path"
    NETWORK_DOMAIN = "network_domain"


class Resource(MoriModel):
    type: ResourceType
    id: str
    owner: str | None = None
    group: str | None = None


class Permission(str, Enum):
    READ = "r"
    WRITE = "w"
    EXECUTE = "x"


class ConditionType(str, Enum):
    RISK_CATEGORY = "risk_category"
    STEP_COUNT = "step_count"
    TOTAL_TOKENS = "total_tokens"
    TIME_OF_DAY = "time_of_day"
    TOOL_ERROR_RATE = "tool_error_rate"


class Condition(MoriModel):
    type: ConditionType
    operator: Literal["eq", "gt", "lt", "gte", "lte", "in", "not_in"]
    value: Any


class ResourcePattern(MoriModel):
    type: ResourceType | Literal["*"]
    pattern: str


class IdentityPattern(MoriModel):
    match: Literal["identity", "group", "type", "any"]
    value: str


class PermissionRule(MoriModel):
    resource: ResourcePattern
    identity: IdentityPattern
    permissions: str      # "rwx", "r--", "r-x"
    effect: Literal["allow", "deny", "escalate"]
    priority: int = 100
    conditions: list[Condition] = Field(default_factory=list)


class PermissionResult(MoriModel):
    decision: PermissionDecision
    rule_applied: PermissionRule | None = None
    explanation: str = ""


class PermissionExplanation(MoriModel):
    identity: Identity
    resource: Resource
    permission: Permission
    decision: PermissionDecision
    rules_checked: list[PermissionRule]
    rule_applied: PermissionRule | None
    reason: str


class PermissionConfig(MoriModel):
    default_decision: PermissionDecision = PermissionDecision.DENY
    audit_all_checks: bool = True
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_permission_types.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add mori/permission/__init__.py mori/permission/types.py tests/test_permission_types.py
git commit -m "feat: permission types — Identity, Resource, PermissionRule, PermissionConfig"
```

---

## Task 2: Permission Engine

**Files:**
- Create: `mori/permission/engine.py`
- Create: `tests/test_permission_engine.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_permission_engine.py
import asyncio
import pytest
from mori.permission.engine import PermissionEngine
from mori.permission.types import (
    Identity, IdentityPattern, IdentityType, Permission, PermissionConfig,
    PermissionRule, Resource, ResourcePattern, ResourceType,
)
from mori.types import PermissionDecision


def _engine() -> PermissionEngine:
    return PermissionEngine()


def _allow_rule(pattern: str = "*", resource_type: ResourceType | str = ResourceType.TOOL, priority: int = 100) -> PermissionRule:
    return PermissionRule(
        resource=ResourcePattern(type=resource_type, pattern=pattern),
        identity=IdentityPattern(match="any", value="*"),
        permissions="r-x",
        effect="allow",
        priority=priority,
    )


def test_no_rules_returns_default_deny():
    engine = _engine()
    identity = Identity(id="agent:bot", name="bot", type=IdentityType.AGENT)
    resource = Resource(type=ResourceType.TOOL, id="some_tool")
    result = asyncio.run(engine.check(identity, resource, Permission.EXECUTE))
    assert result.decision == PermissionDecision.DENY


def test_allow_rule_grants_access():
    engine = _engine()
    engine.load_rules([_allow_rule()])
    identity = Identity(id="user:carl", name="carl", type=IdentityType.USER)
    resource = Resource(type=ResourceType.TOOL, id="read_file")
    result = asyncio.run(engine.check(identity, resource, Permission.EXECUTE))
    assert result.decision == PermissionDecision.ALLOW


def test_deny_rule_overrides_allow():
    engine = _engine()
    engine.load_rules([
        _allow_rule(priority=100),
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="deploy_*"),
            identity=IdentityPattern(match="type", value="agent"),
            permissions="--x",
            effect="deny",
            priority=5,
        ),
    ])
    identity = Identity(id="agent:bot", name="bot", type=IdentityType.AGENT)
    resource = Resource(type=ResourceType.TOOL, id="deploy_prod")
    result = asyncio.run(engine.check(identity, resource, Permission.EXECUTE))
    assert result.decision == PermissionDecision.DENY


def test_escalate_rule():
    engine = _engine()
    engine.load_rules([PermissionRule(
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="database_*"),
        identity=IdentityPattern(match="any", value="*"),
        permissions="--x",
        effect="escalate",
        priority=20,
    )])
    identity = Identity(id="agent:bot", name="bot", type=IdentityType.AGENT)
    resource = Resource(type=ResourceType.TOOL, id="database_delete")
    result = asyncio.run(engine.check(identity, resource, Permission.EXECUTE))
    assert result.decision == PermissionDecision.ESCALATE


def test_glob_matching_read_star():
    engine = _engine()
    engine.load_rules([PermissionRule(
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="read_*"),
        identity=IdentityPattern(match="any", value="*"),
        permissions="--x",
        effect="allow",
    )])
    identity = Identity(id="user:carl", name="carl", type=IdentityType.USER)
    assert asyncio.run(engine.check(
        identity, Resource(type=ResourceType.TOOL, id="read_file"), Permission.EXECUTE
    )).decision == PermissionDecision.ALLOW
    assert asyncio.run(engine.check(
        identity, Resource(type=ResourceType.TOOL, id="write_file"), Permission.EXECUTE
    )).decision == PermissionDecision.DENY


def test_group_matching():
    engine = _engine()
    engine.load_groups({"engineering": ["user:carl", "agent:code-bot"]})
    engine.load_rules([PermissionRule(
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="*"),
        identity=IdentityPattern(match="group", value="engineering"),
        permissions="r-x",
        effect="allow",
    )])
    allowed = Identity(id="user:carl", name="carl", type=IdentityType.USER)
    denied = Identity(id="user:intern", name="intern", type=IdentityType.USER)
    resource = Resource(type=ResourceType.TOOL, id="some_tool")
    assert asyncio.run(engine.check(allowed, resource, Permission.EXECUTE)).decision == PermissionDecision.ALLOW
    assert asyncio.run(engine.check(denied, resource, Permission.EXECUTE)).decision == PermissionDecision.DENY


def test_group_on_identity_groups_field():
    engine = _engine()
    engine.load_rules([PermissionRule(
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="*"),
        identity=IdentityPattern(match="group", value="admin"),
        permissions="rwx",
        effect="allow",
    )])
    # identity has "admin" in its groups list even without load_groups
    identity = Identity(id="user:carl", name="carl", type=IdentityType.USER, groups=["admin"])
    result = asyncio.run(engine.check(identity, Resource(type=ResourceType.TOOL, id="deploy"), Permission.EXECUTE))
    assert result.decision == PermissionDecision.ALLOW


def test_wildcard_resource_type():
    engine = _engine()
    engine.load_rules([PermissionRule(
        resource=ResourcePattern(type="*", pattern="*"),
        identity=IdentityPattern(match="any", value="*"),
        permissions="rwx",
        effect="allow",
    )])
    identity = Identity(id="user:admin", name="admin", type=IdentityType.USER)
    for rt in [ResourceType.TOOL, ResourceType.SKILL, ResourceType.MEMORY_LAYER]:
        result = asyncio.run(engine.check(identity, Resource(type=rt, id="anything"), Permission.READ))
        assert result.decision == PermissionDecision.ALLOW


def test_load_from_yaml(tmp_path):
    policy_file = tmp_path / "policy.yaml"
    policy_file.write_text(
        "groups:\n"
        "  engineering:\n"
        "    members: [\"user:carl\"]\n"
        "rules:\n"
        "  - resource: {type: tool, pattern: \"*\"}\n"
        "    identity: {match: group, value: engineering}\n"
        "    permissions: \"r-x\"\n"
        "    effect: allow\n"
        "    priority: 50\n"
    )
    engine = _engine()
    engine.load_from_yaml(str(policy_file))
    identity = Identity(id="user:carl", name="carl", type=IdentityType.USER)
    resource = Resource(type=ResourceType.TOOL, id="any_tool")
    result = asyncio.run(engine.check(identity, resource, Permission.EXECUTE))
    assert result.decision == PermissionDecision.ALLOW


def test_can_sync():
    engine = _engine()
    engine.load_rules([_allow_rule()])
    identity = Identity(id="user:carl", name="carl", type=IdentityType.USER)
    resource = Resource(type=ResourceType.TOOL, id="some_tool")
    assert engine.can(identity, resource, Permission.READ) is True
    assert engine.can(identity, resource, Permission.WRITE) is False


def test_priority_lower_wins():
    engine = _engine()
    engine.load_rules([
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="*"),
            identity=IdentityPattern(match="any", value="*"),
            permissions="r-x",
            effect="allow",
            priority=100,
        ),
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="*"),
            identity=IdentityPattern(match="any", value="*"),
            permissions="rwx",
            effect="deny",
            priority=5,
        ),
    ])
    identity = Identity(id="user:carl", name="carl", type=IdentityType.USER)
    resource = Resource(type=ResourceType.TOOL, id="anything")
    result = asyncio.run(engine.check(identity, resource, Permission.EXECUTE))
    assert result.decision == PermissionDecision.DENY
    assert result.rule_applied is not None
    assert result.rule_applied.priority == 5
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_permission_engine.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'mori.permission.engine'`

- [ ] **Step 3: Implement the Permission Engine**

```python
# mori/permission/engine.py
"""PermissionEngine — resolution algorithm, YAML loader, fnmatch glob matching."""
from __future__ import annotations

import fnmatch
from typing import Any

import yaml

from mori.permission.types import (
    Condition, ConditionType, Identity, IdentityPattern, Permission,
    PermissionConfig, PermissionExplanation, PermissionResult, PermissionRule,
    Resource, ResourcePattern, ResourceType,
)
from mori.types import PermissionDecision


class PermissionEngine:
    def __init__(self, config: PermissionConfig | None = None) -> None:
        self._config = config or PermissionConfig()
        self._rules: list[PermissionRule] = []
        self._groups: dict[str, list[str]] = {}

    def register_identity(self, identity: Identity) -> None:
        pass  # Identities are checked inline; registration is optional for group lookup

    def add_to_group(self, identity_id: str, group: str) -> None:
        self._groups.setdefault(group, [])
        if identity_id not in self._groups[group]:
            self._groups[group].append(identity_id)

    def remove_from_group(self, identity_id: str, group: str) -> None:
        if group in self._groups:
            self._groups[group] = [i for i in self._groups[group] if i != identity_id]

    def load_rules(self, rules: list[PermissionRule]) -> None:
        self._rules.extend(rules)

    def load_groups(self, groups: dict[str, list[str]]) -> None:
        for group, members in groups.items():
            self._groups.setdefault(group, [])
            for m in members:
                if m not in self._groups[group]:
                    self._groups[group].append(m)

    def load_from_yaml(self, path: str) -> None:
        with open(path) as f:
            data = yaml.safe_load(f)
        if "groups" in data:
            for group_name, group_data in data["groups"].items():
                members = group_data.get("members", []) if isinstance(group_data, dict) else group_data
                self.load_groups({group_name: members})
        if "rules" in data:
            self.load_rules([PermissionRule.model_validate(r) for r in data["rules"]])

    def _resource_matches(self, pattern: ResourcePattern, resource: Resource) -> bool:
        if pattern.type != "*" and pattern.type != resource.type:
            return False
        return fnmatch.fnmatch(resource.id, pattern.pattern)

    def _identity_matches(self, pattern: IdentityPattern, identity: Identity) -> bool:
        if pattern.match == "any":
            return True
        if pattern.match == "identity":
            return identity.id == pattern.value
        if pattern.match == "group":
            # Check engine-registered groups OR identity.groups field
            registered = self._groups.get(pattern.value, [])
            return identity.id in registered or pattern.value in identity.groups
        if pattern.match == "type":
            return identity.type.value == pattern.value
        return False

    def _permission_bit_set(self, rule_permissions: str, permission: Permission) -> bool:
        idx = {"r": 0, "w": 1, "x": 2}[permission.value]
        return len(rule_permissions) > idx and rule_permissions[idx] != "-"

    def _conditions_met(self, conditions: list[Condition], context: dict[str, Any]) -> bool:
        for cond in conditions:
            val = context.get(cond.type.value)
            if val is None:
                continue
            op, cv = cond.operator, cond.value
            checks = {
                "eq": val == cv, "gt": val > cv, "lt": val < cv,
                "gte": val >= cv, "lte": val <= cv,
                "in": val in cv, "not_in": val not in cv,
            }
            if not checks.get(op, True):
                return False
        return True

    def _check_sync(
        self, identity: Identity, resource: Resource, permission: Permission,
        context: dict[str, Any] | None = None,
    ) -> PermissionResult:
        ctx = context or {}
        matching = [
            r for r in self._rules
            if self._resource_matches(r.resource, resource)
            and self._identity_matches(r.identity, identity)
        ]
        matching.sort(key=lambda r: r.priority)

        allowed = False
        for rule in matching:
            if not self._conditions_met(rule.conditions, ctx):
                continue
            if not self._permission_bit_set(rule.permissions, permission):
                continue
            if rule.effect == "deny":
                return PermissionResult(decision=PermissionDecision.DENY, rule_applied=rule)
            if rule.effect == "escalate":
                return PermissionResult(decision=PermissionDecision.ESCALATE, rule_applied=rule)
            if rule.effect == "allow":
                allowed = True

        if allowed:
            return PermissionResult(decision=PermissionDecision.ALLOW)
        return PermissionResult(decision=self._config.default_decision)

    async def check(
        self, identity: Identity, resource: Resource, permission: Permission,
        context: dict[str, Any] | None = None,
    ) -> PermissionResult:
        return self._check_sync(identity, resource, permission, context)

    async def check_batch(
        self, identity: Identity, checks: list[tuple[Resource, Permission]],
        context: dict[str, Any] | None = None,
    ) -> list[PermissionResult]:
        return [self._check_sync(identity, r, p, context) for r, p in checks]

    def can(self, identity: Identity, resource: Resource, permission: Permission) -> bool:
        return self._check_sync(identity, resource, permission).decision == PermissionDecision.ALLOW

    def get_effective_permissions(self, identity: Identity, resource: Resource) -> str:
        bits = ""
        for p in [Permission.READ, Permission.WRITE, Permission.EXECUTE]:
            result = self._check_sync(identity, resource, p)
            bits += p.value if result.decision == PermissionDecision.ALLOW else "-"
        return bits

    def explain(self, identity: Identity, resource: Resource, permission: Permission) -> PermissionExplanation:
        result = self._check_sync(identity, resource, permission)
        matching = [
            r for r in self._rules
            if self._resource_matches(r.resource, resource)
            and self._identity_matches(r.identity, identity)
        ]
        matching.sort(key=lambda r: r.priority)
        rule_info = f" via rule priority={result.rule_applied.priority}" if result.rule_applied else " (no matching rule → default)"
        return PermissionExplanation(
            identity=identity, resource=resource, permission=permission,
            decision=result.decision, rules_checked=matching, rule_applied=result.rule_applied,
            reason=f"Decision: {result.decision.value}{rule_info}",
        )

    def list_accessible(self, identity: Identity, resource_type: ResourceType) -> list[Resource]:
        return []
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_permission_engine.py -v
```

Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add mori/permission/engine.py tests/test_permission_engine.py
git commit -m "feat: PermissionEngine — deny-wins resolution, glob matching, YAML policy loader"
```

---

## Task 3: Checkpoint Store

**Files:**
- Create: `mori/control/checkpoint.py`
- Create: `tests/test_checkpoint.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_checkpoint.py
from datetime import datetime, timezone

import pytest

from mori.control.checkpoint import (
    Checkpoint, FileCheckpoints, InMemoryCheckpoints, SQLiteCheckpoints,
)
from mori.runtime.state import MoriState
from mori.types import RunId, RunStatus, ThreadId


def _state(thread_id: str = "t1") -> MoriState:
    now = datetime.now(timezone.utc)
    return MoriState(
        run_id=RunId("run_test"), thread_id=ThreadId(thread_id),
        task="test task", status=RunStatus.RUNNING,
        started_at=now, last_progress_at=now,
    )


@pytest.mark.asyncio
async def test_inmemory_save_and_load():
    store = InMemoryCheckpoints()
    state = _state()
    cid = await store.save(state)
    cp = await store.load(cid)
    assert cp is not None
    assert cp.checkpoint_id == cid


@pytest.mark.asyncio
async def test_inmemory_load_latest():
    store = InMemoryCheckpoints()
    state = _state("t1")
    await store.save(state)
    cid2 = await store.save(state)
    cp = await store.load_latest(ThreadId("t1"))
    assert cp is not None
    assert cp.checkpoint_id == cid2


@pytest.mark.asyncio
async def test_inmemory_load_latest_unknown_thread_returns_none():
    store = InMemoryCheckpoints()
    cp = await store.load_latest(ThreadId("unknown"))
    assert cp is None


@pytest.mark.asyncio
async def test_checkpoint_restore_round_trips_state():
    store = InMemoryCheckpoints()
    state = _state()
    state.step_count = 3
    state.total_tool_calls = 5
    cid = await store.save(state)
    cp = await store.load(cid)
    restored = cp.restore()
    assert restored.step_count == 3
    assert restored.total_tool_calls == 5
    assert restored.task == "test task"


@pytest.mark.asyncio
async def test_inmemory_list():
    store = InMemoryCheckpoints()
    state = _state("t1")
    await store.save(state)
    await store.save(state)
    checkpoints = await store.list(ThreadId("t1"))
    assert len(checkpoints) == 2


@pytest.mark.asyncio
async def test_inmemory_delete():
    store = InMemoryCheckpoints()
    state = _state()
    cid = await store.save(state)
    await store.delete(cid)
    assert await store.load(cid) is None


@pytest.mark.asyncio
async def test_file_checkpoints_save_and_restore(tmp_path):
    store = FileCheckpoints(str(tmp_path))
    state = _state("t1")
    state.step_count = 7
    cid = await store.save(state)
    cp = await store.load(cid)
    assert cp is not None
    restored = cp.restore()
    assert restored.step_count == 7
    assert restored.task == "test task"


@pytest.mark.asyncio
async def test_file_checkpoints_load_latest(tmp_path):
    store = FileCheckpoints(str(tmp_path))
    state = _state("t1")
    await store.save(state)
    cid2 = await store.save(state)
    cp = await store.load_latest(ThreadId("t1"))
    assert cp is not None


@pytest.mark.asyncio
async def test_file_checkpoints_list(tmp_path):
    store = FileCheckpoints(str(tmp_path))
    state = _state("t1")
    await store.save(state)
    await store.save(state)
    checkpoints = await store.list(ThreadId("t1"))
    assert len(checkpoints) == 2


@pytest.mark.asyncio
async def test_sqlite_checkpoints_save_and_restore(tmp_path):
    store = SQLiteCheckpoints(str(tmp_path / "ckpts.db"))
    state = _state("t1")
    state.step_count = 4
    cid = await store.save(state)
    cp = await store.load(cid)
    assert cp is not None
    restored = cp.restore()
    assert restored.step_count == 4


@pytest.mark.asyncio
async def test_sqlite_checkpoints_load_latest(tmp_path):
    store = SQLiteCheckpoints(str(tmp_path / "ckpts.db"))
    state = _state("t1")
    await store.save(state)
    await store.save(state)
    cp = await store.load_latest(ThreadId("t1"))
    assert cp is not None


@pytest.mark.asyncio
async def test_sqlite_checkpoints_list(tmp_path):
    store = SQLiteCheckpoints(str(tmp_path / "ckpts.db"))
    state = _state("t1")
    await store.save(state)
    await store.save(state)
    checkpoints = await store.list(ThreadId("t1"))
    assert len(checkpoints) == 2


@pytest.mark.asyncio
async def test_sqlite_checkpoints_delete(tmp_path):
    store = SQLiteCheckpoints(str(tmp_path / "ckpts.db"))
    state = _state()
    cid = await store.save(state)
    await store.delete(cid)
    assert await store.load(cid) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_checkpoint.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'mori.control.checkpoint'`

- [ ] **Step 3: Implement checkpoint.py**

```python
# mori/control/checkpoint.py
"""Checkpoint store — protocol + InMemory / File / SQLite backends."""
from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from mori.types import CheckpointId, MoriModel, ThreadId


class Checkpoint(MoriModel):
    checkpoint_id: CheckpointId
    thread_id: ThreadId
    state_json: str
    created_at: datetime

    def restore(self):  # -> MoriState (avoid circular import)
        from mori.runtime.state import MoriState
        return MoriState.model_validate_json(self.state_json)


def _new_cid() -> CheckpointId:
    return CheckpointId(f"ckpt_{secrets.token_hex(8)}")


@runtime_checkable
class CheckpointStore(Protocol):
    async def save(self, state) -> CheckpointId: ...
    async def load_latest(self, thread_id: ThreadId) -> Checkpoint | None: ...
    async def load(self, checkpoint_id: CheckpointId) -> Checkpoint | None: ...
    async def list(self, thread_id: ThreadId) -> list[Checkpoint]: ...
    async def delete(self, checkpoint_id: CheckpointId) -> None: ...


class InMemoryCheckpoints:
    def __init__(self) -> None:
        self._store: dict[CheckpointId, Checkpoint] = {}
        self._order: dict[ThreadId, list[CheckpointId]] = {}

    async def save(self, state) -> CheckpointId:
        cid = _new_cid()
        cp = Checkpoint(
            checkpoint_id=cid, thread_id=state.thread_id,
            state_json=state.model_dump_json(), created_at=datetime.now(timezone.utc),
        )
        self._store[cid] = cp
        self._order.setdefault(state.thread_id, []).append(cid)
        return cid

    async def load_latest(self, thread_id: ThreadId) -> Checkpoint | None:
        cids = self._order.get(thread_id, [])
        return self._store.get(cids[-1]) if cids else None

    async def load(self, checkpoint_id: CheckpointId) -> Checkpoint | None:
        return self._store.get(checkpoint_id)

    async def list(self, thread_id: ThreadId) -> list[Checkpoint]:
        return [self._store[c] for c in self._order.get(thread_id, []) if c in self._store]

    async def delete(self, checkpoint_id: CheckpointId) -> None:
        if checkpoint_id in self._store:
            cp = self._store.pop(checkpoint_id)
            self._order[cp.thread_id] = [c for c in self._order.get(cp.thread_id, []) if c != checkpoint_id]


class FileCheckpoints:
    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, cid: CheckpointId) -> Path:
        return self._dir / f"{cid}.json"

    async def save(self, state) -> CheckpointId:
        cid = _new_cid()
        cp = Checkpoint(
            checkpoint_id=cid, thread_id=state.thread_id,
            state_json=state.model_dump_json(), created_at=datetime.now(timezone.utc),
        )
        self._path(cid).write_text(cp.model_dump_json())
        return cid

    async def load_latest(self, thread_id: ThreadId) -> Checkpoint | None:
        checkpoints = await self.list(thread_id)
        return max(checkpoints, key=lambda c: c.created_at) if checkpoints else None

    async def load(self, checkpoint_id: CheckpointId) -> Checkpoint | None:
        p = self._path(checkpoint_id)
        return Checkpoint.model_validate_json(p.read_text()) if p.exists() else None

    async def list(self, thread_id: ThreadId) -> list[Checkpoint]:
        result = []
        for f in self._dir.glob("ckpt_*.json"):
            cp = Checkpoint.model_validate_json(f.read_text())
            if cp.thread_id == thread_id:
                result.append(cp)
        return sorted(result, key=lambda c: c.created_at)

    async def delete(self, checkpoint_id: CheckpointId) -> None:
        p = self._path(checkpoint_id)
        if p.exists():
            p.unlink()


class SQLiteCheckpoints:
    def __init__(self, path: str) -> None:
        self._path = path
        conn = sqlite3.connect(path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cp_thread ON checkpoints(thread_id)")
        conn.commit()
        conn.close()

    def _row_to_checkpoint(self, row: tuple) -> Checkpoint:
        return Checkpoint(
            checkpoint_id=CheckpointId(row[0]), thread_id=ThreadId(row[1]),
            state_json=row[2], created_at=datetime.fromisoformat(row[3]),
        )

    async def save(self, state) -> CheckpointId:
        cid = _new_cid()
        conn = sqlite3.connect(self._path)
        conn.execute(
            "INSERT INTO checkpoints VALUES (?, ?, ?, ?)",
            (cid, state.thread_id, state.model_dump_json(), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        conn.close()
        return cid

    async def load_latest(self, thread_id: ThreadId) -> Checkpoint | None:
        conn = sqlite3.connect(self._path)
        row = conn.execute(
            "SELECT checkpoint_id, thread_id, state_json, created_at FROM checkpoints "
            "WHERE thread_id = ? ORDER BY created_at DESC LIMIT 1", (thread_id,)
        ).fetchone()
        conn.close()
        return self._row_to_checkpoint(row) if row else None

    async def load(self, checkpoint_id: CheckpointId) -> Checkpoint | None:
        conn = sqlite3.connect(self._path)
        row = conn.execute(
            "SELECT checkpoint_id, thread_id, state_json, created_at FROM checkpoints "
            "WHERE checkpoint_id = ?", (checkpoint_id,)
        ).fetchone()
        conn.close()
        return self._row_to_checkpoint(row) if row else None

    async def list(self, thread_id: ThreadId) -> list[Checkpoint]:
        conn = sqlite3.connect(self._path)
        rows = conn.execute(
            "SELECT checkpoint_id, thread_id, state_json, created_at FROM checkpoints "
            "WHERE thread_id = ? ORDER BY created_at ASC", (thread_id,)
        ).fetchall()
        conn.close()
        return [self._row_to_checkpoint(r) for r in rows]

    async def delete(self, checkpoint_id: CheckpointId) -> None:
        conn = sqlite3.connect(self._path)
        conn.execute("DELETE FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,))
        conn.commit()
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_checkpoint.py -v
```

Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add mori/control/checkpoint.py tests/test_checkpoint.py
git commit -m "feat: checkpoint store — InMemory, File, SQLite backends with MoriState round-trip"
```

---

## Task 4: Hook Types + HookRegistry

**Files:**
- Create: `mori/hooks/__init__.py`
- Create: `mori/hooks/types.py`
- Create: `mori/hooks/registry.py`
- Create: `tests/test_hooks.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hooks.py
import asyncio
import pytest
from mori.hooks.registry import HookRegistry
from mori.hooks.types import HookConfig


@pytest.mark.asyncio
async def test_before_hooks_fire_in_priority_order():
    registry = HookRegistry()
    order = []
    registry.register("test.event", lambda p: order.append(10) or p, priority=10)
    registry.register("test.event", lambda p: order.append(20) or p, priority=20)
    registry.register("test.event", lambda p: order.append(5) or p, priority=5)
    await registry.dispatch_before("test.event", "payload")
    assert order == [5, 10, 20]


@pytest.mark.asyncio
async def test_before_hook_modifies_payload():
    registry = HookRegistry()
    registry.register("test.event", lambda p: p + "_modified", priority=10)
    result = await registry.dispatch_before("test.event", "original")
    assert result == "original_modified"


@pytest.mark.asyncio
async def test_before_hook_none_passes_through():
    registry = HookRegistry()
    registry.register("test.event", lambda p: None, priority=10)
    result = await registry.dispatch_before("test.event", "original")
    assert result == "original"


@pytest.mark.asyncio
async def test_after_hook_ignores_return_value():
    registry = HookRegistry()
    received = []
    registry.register("test.after", lambda p: received.append(p) or "ignored")
    await registry.dispatch_after("test.after", "payload")
    assert received == ["payload"]


@pytest.mark.asyncio
async def test_async_handler():
    registry = HookRegistry()

    async def async_hook(p):
        await asyncio.sleep(0)
        return p + "_async"

    registry.register("test.event", async_hook, priority=10)
    result = await registry.dispatch_before("test.event", "data")
    assert result == "data_async"


@pytest.mark.asyncio
async def test_fail_open_swallows_hook_error():
    registry = HookRegistry(config=HookConfig(fail_open=True))

    def bad_hook(p):
        raise RuntimeError("hook failed")

    registry.register("test.event", bad_hook, priority=10)
    result = await registry.dispatch_before("test.event", "safe")
    assert result == "safe"


@pytest.mark.asyncio
async def test_fail_closed_propagates_hook_error():
    registry = HookRegistry(config=HookConfig(fail_open=False))

    def bad_hook(p):
        raise RuntimeError("hook failed")

    registry.register("test.event", bad_hook, priority=10)
    with pytest.raises(RuntimeError):
        await registry.dispatch_before("test.event", "safe")


def test_unregister_removes_hook():
    registry = HookRegistry()
    hid = registry.register("test.event", lambda p: p, priority=10)
    registry.unregister(hid)
    assert registry.list_hooks("test.event") == []


def test_decorator_registers_hook():
    registry = HookRegistry()

    @registry.hook("test.event", priority=5)
    def my_hook(p):
        return p

    hooks = registry.list_hooks("test.event")
    assert len(hooks) == 1
    assert hooks[0].handler_name == "my_hook"


def test_max_hooks_per_event():
    registry = HookRegistry(config=HookConfig(max_hooks_per_event=2))
    registry.register("test.event", lambda p: p, priority=10)
    registry.register("test.event", lambda p: p, priority=20)
    with pytest.raises(ValueError, match="Max hooks"):
        registry.register("test.event", lambda p: p, priority=30)


def test_clear_removes_all_hooks():
    registry = HookRegistry()
    registry.register("event.a", lambda p: p)
    registry.register("event.b", lambda p: p)
    count = registry.clear()
    assert count == 2
    assert registry.list_hooks() == []


def test_clear_event_name_removes_only_that_event():
    registry = HookRegistry()
    registry.register("event.a", lambda p: p)
    registry.register("event.b", lambda p: p)
    registry.clear("event.a")
    assert registry.list_hooks("event.a") == []
    assert len(registry.list_hooks("event.b")) == 1


@pytest.mark.asyncio
async def test_hook_timeout_fail_open():
    registry = HookRegistry(config=HookConfig(hook_timeout_sec=0.01, fail_open=True))

    async def slow_hook(p):
        await asyncio.sleep(10)
        return p

    registry.register("test.event", slow_hook, priority=10)
    result = await registry.dispatch_before("test.event", "original")
    assert result == "original"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_hooks.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'mori.hooks'`

- [ ] **Step 3: Create hook types**

```python
# mori/hooks/__init__.py
"""Hooks — priority-ordered lifecycle callbacks."""
```

```python
# mori/hooks/types.py
"""Hook system types."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable

from mori.types import MoriModel

HookHandler = Callable[[Any], Any] | Callable[[Any], Awaitable[Any]]


class HookConfig(MoriModel):
    max_hooks_per_event: int = 50
    hook_timeout_sec: float = 10.0
    fail_open: bool = True
    log_hook_errors: bool = True


class HookRegistration(MoriModel):
    hook_id: str
    event_name: str
    handler_name: str
    priority: int
    registered_at: datetime
    model_config = {"frozen": False, "extra": "forbid"}
```

- [ ] **Step 4: Create HookRegistry**

```python
# mori/hooks/registry.py
"""HookRegistry — priority dispatch with timeout and fail_open."""
from __future__ import annotations

import asyncio
import inspect
import secrets
import structlog
from datetime import datetime, timezone
from typing import Any, Callable

from mori.hooks.types import HookConfig, HookHandler, HookRegistration

log = structlog.get_logger()


class HookRegistry:
    def __init__(self, config: HookConfig | None = None) -> None:
        self._config = config or HookConfig()
        # event_name -> [(priority, hook_id, handler)]
        self._hooks: dict[str, list[tuple[int, str, HookHandler]]] = {}
        self._registrations: dict[str, HookRegistration] = {}

    def register(
        self, event_name: str, handler: HookHandler,
        priority: int = 100, name: str | None = None,
    ) -> str:
        hooks = self._hooks.setdefault(event_name, [])
        if len(hooks) >= self._config.max_hooks_per_event:
            raise ValueError(
                f"Max hooks per event ({self._config.max_hooks_per_event}) reached for '{event_name}'"
            )
        hook_id = f"hook_{secrets.token_hex(6)}"
        hooks.append((priority, hook_id, handler))
        hooks.sort(key=lambda t: t[0])
        self._registrations[hook_id] = HookRegistration(
            hook_id=hook_id, event_name=event_name,
            handler_name=name or getattr(handler, "__name__", repr(handler)),
            priority=priority, registered_at=datetime.now(timezone.utc),
        )
        return hook_id

    def unregister(self, hook_id: str) -> bool:
        if hook_id not in self._registrations:
            return False
        reg = self._registrations.pop(hook_id)
        self._hooks[reg.event_name] = [t for t in self._hooks.get(reg.event_name, []) if t[1] != hook_id]
        return True

    def hook(self, event_name: str, priority: int = 100) -> Callable:
        def decorator(fn: HookHandler) -> HookHandler:
            self.register(event_name, fn, priority=priority, name=fn.__name__)
            return fn
        return decorator

    async def _call(self, handler: HookHandler, payload: Any) -> Any:
        try:
            if inspect.iscoroutinefunction(handler):
                coro = handler(payload)
            else:
                loop = asyncio.get_event_loop()
                coro = loop.run_in_executor(None, handler, payload)
            return await asyncio.wait_for(coro, timeout=self._config.hook_timeout_sec)
        except asyncio.TimeoutError:
            if self._config.log_hook_errors:
                log.warning("hook.timeout", handler=getattr(handler, "__name__", "?"))
            if not self._config.fail_open:
                raise
            return None
        except Exception as exc:
            if self._config.log_hook_errors:
                log.warning("hook.error", handler=getattr(handler, "__name__", "?"), error=str(exc))
            if not self._config.fail_open:
                raise
            return None

    async def dispatch_before(self, event_name: str, payload: Any) -> Any:
        current = payload
        for _priority, _hook_id, handler in self._hooks.get(event_name, []):
            result = await self._call(handler, current)
            if result is not None:
                current = result
        return current

    async def dispatch_after(self, event_name: str, payload: Any) -> None:
        for _priority, _hook_id, handler in self._hooks.get(event_name, []):
            await self._call(handler, payload)

    def list_hooks(self, event_name: str | None = None) -> list[HookRegistration]:
        if event_name is not None:
            return [r for r in self._registrations.values() if r.event_name == event_name]
        return list(self._registrations.values())

    def clear(self, event_name: str | None = None) -> int:
        if event_name is not None:
            removed = len(self._hooks.pop(event_name, []))
            for hid in [hid for hid, r in self._registrations.items() if r.event_name == event_name]:
                del self._registrations[hid]
            return removed
        count = sum(len(v) for v in self._hooks.values())
        self._hooks.clear()
        self._registrations.clear()
        return count
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_hooks.py -v
```

Expected: 13 passed

- [ ] **Step 6: Commit**

```bash
git add mori/hooks/__init__.py mori/hooks/types.py mori/hooks/registry.py tests/test_hooks.py
git commit -m "feat: HookRegistry — priority dispatch, timeout, fail_open, sync+async handlers"
```

---

## Task 5: PermissionCheckEvent + MoriState Additions

**Files:**
- Modify: `mori/observability/events.py`
- Modify: `mori/runtime/state.py`
- Create: `tests/test_permission_event.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_permission_event.py
from datetime import datetime, timezone

from mori.observability.events import PermissionCheckEvent
from mori.runtime.state import MoriState
from mori.types import RunId, RunStatus, ThreadId


def test_permission_check_event():
    event = PermissionCheckEvent(
        event_id="evt_1",
        timestamp=datetime.now(timezone.utc),
        run_id=RunId("run_test"),
        identity_id="agent:bot",
        resource_type="tool",
        resource_id="deploy_prod",
        permission="x",
        decision="escalate",
        duration_ms=0.5,
    )
    assert event.event_type == "permission.check"
    assert event.decision == "escalate"
    assert event.rule_applied_priority is None


def test_moristate_paused_fields():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    state = MoriState(
        run_id=RunId("run_1"),
        thread_id=ThreadId("t1"),
        task="test",
        status=RunStatus.PAUSED,
        started_at=now,
        last_progress_at=now,
        paused_reason="ESCALATE: deploy requires approval",
    )
    assert state.paused_reason == "ESCALATE: deploy requires approval"
    assert state.paused_tool_call is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_permission_event.py -v 2>&1 | head -15
```

Expected: `ImportError: cannot import name 'PermissionCheckEvent'` and attribute error on `paused_reason`

- [ ] **Step 3: Add PermissionCheckEvent to events.py**

Add after the `MemoryWriteEvent` class in `mori/observability/events.py`:

```python
# ── Permission Events ────────────────────────────────────────

class PermissionCheckEvent(MoriEvent):
    event_type: str = "permission.check"
    identity_id: str
    resource_type: str
    resource_id: str
    permission: str           # "r", "w", or "x"
    decision: str             # "allow", "deny", or "escalate"
    rule_applied_priority: int | None = None
    duration_ms: float
```

- [ ] **Step 4: Add paused fields to MoriState**

In `mori/runtime/state.py`, add after `active_skill_payload`:

```python
    # Governance — set when status == PAUSED
    paused_reason: str | None = None
    paused_tool_call: Any | None = None
```

- [ ] **Step 5: Run tests to verify they pass**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_permission_event.py -v && python -m pytest tests/test_state.py -v
```

Expected: 2 + existing state tests passed

- [ ] **Step 6: Run full suite to check nothing broke**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: same pass count as before + 2 new tests (≥355 passed, 3 voyageai xfail)

- [ ] **Step 7: Commit**

```bash
git add mori/observability/events.py mori/runtime/state.py tests/test_permission_event.py
git commit -m "feat: PermissionCheckEvent + MoriState paused_reason/paused_tool_call fields"
```

---

## Task 6: Loop Integration — Checkpoint

**Files:**
- Modify: `mori/runtime/loop.py`
- Modify: `mori/runtime/result.py`
- Create: `tests/test_loop_checkpoint_v05.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_loop_checkpoint_v05.py
import pytest
from unittest.mock import AsyncMock

from mori.control.checkpoint import InMemoryCheckpoints
from mori.model.base import ModelAdapter
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import (
    Message, ModelResponse, RunStatus, ThreadId, TokenUsage, ToolCall,
)


def _text(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="end_turn",
    )


def _tool(tid, name, args):
    return ModelResponse(
        message=Message(role="assistant", content="", tool_calls=[ToolCall(id=tid, name=name, arguments=args)]),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="tool_use",
    )


@pytest.fixture
def mock_model():
    model = AsyncMock(spec=ModelAdapter)
    model.model_id = "test"
    model.supports_tool_use = True
    model.max_context_tokens = 100000
    return model


@pytest.mark.asyncio
async def test_loop_saves_checkpoint_on_completion(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    checkpointer = InMemoryCheckpoints()
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), checkpointer=checkpointer)
    result = await loop.run("test", thread_id=ThreadId("t1"))
    assert result.status == RunStatus.COMPLETED
    assert result.checkpoint_id is not None
    checkpoints = await checkpointer.list(ThreadId("t1"))
    assert len(checkpoints) >= 1


@pytest.mark.asyncio
async def test_loop_periodic_checkpoint_every_n_steps(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool("c1", "add", {"a": 1, "b": 2}),
        _tool("c2", "add", {"a": 3, "b": 4}),
        _text("done"),
    ])
    checkpointer = InMemoryCheckpoints()
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    loop = AgentLoop(
        model=mock_model, tools=registry, checkpointer=checkpointer,
        checkpoint_every_n_steps=2,
    )
    result = await loop.run("test", thread_id=ThreadId("t1"))
    assert result.status == RunStatus.COMPLETED
    checkpoints = await checkpointer.list(ThreadId("t1"))
    assert len(checkpoints) >= 2  # at least 1 periodic + 1 final


@pytest.mark.asyncio
async def test_loop_without_checkpointer_still_works(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry())
    result = await loop.run("test")
    assert result.status == RunStatus.COMPLETED
    assert result.checkpoint_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_loop_checkpoint_v05.py -v 2>&1 | head -20
```

Expected: `TypeError: AgentLoop.__init__() got an unexpected keyword argument 'checkpointer'`

- [ ] **Step 3: Add checkpoint_id param to RunResult.from_state()**

In `mori/runtime/result.py`, modify `from_state`:

```python
    @staticmethod
    def from_state(state: MoriState, duration_ms: float, checkpoint_id: CheckpointId | None = None) -> RunResult:
        """Build a RunResult from the final MoriState."""
        final_output: str | None = None
        for msg in reversed(state.messages):
            if msg.role == "assistant" and isinstance(msg.content, str) and msg.content:
                final_output = msg.content
                break

        return RunResult(
            run_id=state.run_id,
            thread_id=state.thread_id,
            status=state.status,
            task=state.task,
            final_output=final_output,
            messages=state.messages,
            total_steps=state.step_count,
            total_usage=TokenUsage(
                input_tokens=state.total_input_tokens,
                output_tokens=state.total_output_tokens,
            ),
            total_tool_calls=state.total_tool_calls,
            total_duration_ms=duration_ms,
            checkpoint_id=checkpoint_id,
        )
```

- [ ] **Step 4: Refactor loop.py — add checkpointer param and _run_from_state()**

In `mori/runtime/loop.py`, update `__init__` to add `checkpointer` and `checkpoint_every_n_steps`:

```python
    def __init__(
        self,
        model: ModelAdapter,
        tools: ToolRegistry,
        observability: ObservabilityEngine | None = None,
        control: ControlBounds | None = None,
        memory: Any | None = None,
        skills: Any | None = None,
        budget: Any | None = None,
        checkpointer: Any | None = None,
        checkpoint_every_n_steps: int = 5,
        permission: Any | None = None,
        identity: Any | None = None,
        hooks: Any | None = None,
    ) -> None:
        self._model = model
        self._tools = tools
        self._obs = observability
        if control is None:
            from mori.control.bounds import ControlBounds, ControlConfig
            control = ControlBounds(config=ControlConfig())
        self._control = control
        self._memory = memory
        self._skills = skills
        self._budget = budget
        self._checkpointer = checkpointer
        self._checkpoint_every_n_steps = checkpoint_every_n_steps
        self._permission = permission
        self._identity = identity
        self._hooks = hooks
```

Refactor `run()` to extract the core loop body into `_run_from_state()`:

```python
    async def run(
        self, task: str, thread_id: ThreadId | None = None, context: dict[str, Any] | None = None,
    ) -> RunResult:
        state = self._init_state(task, thread_id, context)
        return await self._run_from_state(state)

    async def resume(self, thread_id: ThreadId, input: dict[str, Any]) -> RunResult:
        if not self._checkpointer:
            raise ValueError("Cannot resume: no checkpointer configured")
        cp = await self._checkpointer.load_latest(thread_id)
        if cp is None:
            raise ValueError(f"No checkpoint found for thread {thread_id}")
        state = cp.restore()
        approved = input.get("approved", False)
        msg = f"[Resume] {'Approved' if approved else 'Rejected'}. Details: {input}"
        state.messages.append(Message(role="user", content=msg))
        state.status = RunStatus.RUNNING
        state.paused_reason = None
        state.paused_tool_call = None
        return await self._run_from_state(state)

    async def _run_from_state(self, state: MoriState) -> RunResult:
        from mori.observability.events import (
            BoundViolationEvent, RunEndEvent, RunStartEvent, StepEndEvent, StepStartEvent,
        )

        start_time = time.monotonic()

        await self._emit(RunStartEvent(
            event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
            run_id=state.run_id, task=state.task,
            config={"max_steps": self._control._config.max_steps},
        ))

        while state.status == RunStatus.RUNNING:
            state.step_count += 1
            step_start = time.monotonic()
            step_id = StepId(f"step_{state.run_id}_{state.step_count:04d}")

            # Periodic checkpoint
            if (
                self._checkpointer
                and state.step_count % self._checkpoint_every_n_steps == 0
            ):
                await self._checkpointer.save(state)

            bound_check = self._control.check_bounds(state)
            if not bound_check.ok:
                for bound in bound_check.violated_bounds:
                    await self._emit(BoundViolationEvent(
                        event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                        run_id=state.run_id, bound_name=bound,
                        current_value=bound_check.current_values.get("step_count", 0),
                        limit_value=float(getattr(self._control._config, bound, 0)),
                    ))
                state.status = RunStatus.FAILED
                break

            await self._emit(StepStartEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id, step_id=step_id, step_number=state.step_count, phase=Phase.PLAN,
            ))

            await self._phase_retrieve(state)
            await self._pre_plan_compact(state)
            await self._phase_plan(state)
            await self._phase_act(state)

            if state.status == RunStatus.PAUSED:
                break

            outcome = self._phase_evaluate(state)
            await self._phase_update(state)

            step_elapsed = (time.monotonic() - step_start) * 1000
            await self._emit(StepEndEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id, step_id=step_id, step_number=state.step_count,
                outcome=outcome, input_tokens=0, output_tokens=0, duration_ms=step_elapsed,
            ))

            if outcome == StepOutcome.SUCCESS:
                state.status = RunStatus.COMPLETED
                break

            self._control.record_progress()
            state.last_progress_at = datetime.now(timezone.utc)

        elapsed_ms = (time.monotonic() - start_time) * 1000

        # Save checkpoint on completion or pause
        checkpoint_id = None
        if self._checkpointer:
            checkpoint_id = await self._checkpointer.save(state)

        await self._emit(RunEndEvent(
            event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
            run_id=state.run_id, status=state.status, total_steps=state.step_count,
            total_input_tokens=state.total_input_tokens, total_output_tokens=state.total_output_tokens,
            duration_ms=elapsed_ms,
        ))

        # Write episodic summary (memory)
        if self._memory and state.status != RunStatus.PAUSED:
            from mori.observability.events import MemoryWriteEvent
            from mori.types import MemoryRecord, MemoryRecordId, MemoryLayer
            run_result = RunResult.from_state(state, duration_ms=elapsed_ms)
            tools_used: set[str] = set()
            for msg in state.messages:
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        tools_used.add(tc.name)
            ep_content = (
                f'Run "{state.task[:100]}": {state.status.value} in {state.step_count} steps. '
                f'Tools: {", ".join(sorted(tools_used)) or "none"}. '
                f'Result: {(run_result.final_output or "")[:200]}'
            )
            record = MemoryRecord(
                record_id=MemoryRecordId(f"mem_{secrets.token_hex(12)}"),
                layer=MemoryLayer.EPISODIC, content=ep_content,
                created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
                provenance="loop:episodic",
            )
            receipt = await self._memory.write([record])
            await self._emit(MemoryWriteEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id, layer=MemoryLayer.EPISODIC,
                record_ids=[str(r) for r in receipt.record_ids], records_written=1,
            ))

        if self._obs:
            await self._obs.flush()

        return RunResult.from_state(state, duration_ms=elapsed_ms, checkpoint_id=checkpoint_id)
```

Also delete the old `run()` method body (now replaced by `_run_from_state`). The imports at the top of `_run_from_state` replace the ones that were in `run()`.

- [ ] **Step 5: Run tests to verify they pass**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_loop_checkpoint_v05.py -v
```

Expected: 3 passed

- [ ] **Step 6: Run full suite to check nothing broke**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: ≥358 passed, same 3 voyageai xfail

- [ ] **Step 7: Commit**

```bash
git add mori/runtime/loop.py mori/runtime/result.py tests/test_loop_checkpoint_v05.py
git commit -m "feat: loop checkpoint — save every N steps + on completion/pause; add resume()"
```

---

## Task 7: Loop Integration — Permission Check + Pause

**Files:**
- Modify: `mori/runtime/loop.py` (`_phase_act`)
- Create: `tests/test_loop_permission_v05.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_loop_permission_v05.py
import pytest
from unittest.mock import AsyncMock

from mori.control.checkpoint import InMemoryCheckpoints
from mori.model.base import ModelAdapter
from mori.permission.engine import PermissionEngine
from mori.permission.types import (
    Identity, IdentityPattern, IdentityType, Permission, PermissionRule,
    Resource, ResourcePattern, ResourceType,
)
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import (
    Message, ModelResponse, RunStatus, ThreadId, TokenUsage, ToolCall,
)


def _text(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="end_turn",
    )


def _tool_resp(tid, name, args):
    return ModelResponse(
        message=Message(role="assistant", content="", tool_calls=[ToolCall(id=tid, name=name, arguments=args)]),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="tool_use",
    )


@pytest.fixture
def mock_model():
    model = AsyncMock(spec=ModelAdapter)
    model.model_id = "test"
    model.supports_tool_use = True
    model.max_context_tokens = 100000
    return model


def _allow_engine() -> PermissionEngine:
    engine = PermissionEngine()
    engine.load_rules([PermissionRule(
        resource=ResourcePattern(type=ResourceType.TOOL, pattern="*"),
        identity=IdentityPattern(match="any", value="*"),
        permissions="r-x", effect="allow",
    )])
    return engine


def _deny_engine(pattern: str) -> PermissionEngine:
    engine = PermissionEngine()
    engine.load_rules([
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="*"),
            identity=IdentityPattern(match="any", value="*"),
            permissions="r-x", effect="allow", priority=100,
        ),
        PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern=pattern),
            identity=IdentityPattern(match="any", value="*"),
            permissions="--x", effect="deny", priority=5,
        ),
    ])
    return engine


def _escalate_engine(pattern: str) -> PermissionEngine:
    engine = PermissionEngine()
    engine.load_rules([PermissionRule(
        resource=ResourcePattern(type=ResourceType.TOOL, pattern=pattern),
        identity=IdentityPattern(match="any", value="*"),
        permissions="--x", effect="escalate", priority=10,
    )])
    return engine


@pytest.mark.asyncio
async def test_allowed_tool_completes(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "add", {"a": 1, "b": 2}),
        _text("3"),
    ])
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    identity = Identity(id="user:carl", name="carl", type=IdentityType.USER)
    loop = AgentLoop(model=mock_model, tools=registry, permission=_allow_engine(), identity=identity)
    result = await loop.run("add 1+2")
    assert result.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_denied_tool_returns_error_result_and_continues(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "deploy_prod", {"version": "1.2.3"}),
        _text("cannot deploy, permission denied"),
    ])
    registry = ToolRegistry()
    registry.register("deploy_prod", lambda version: "deployed", description="Deploy")
    identity = Identity(id="agent:bot", name="bot", type=IdentityType.AGENT)
    loop = AgentLoop(model=mock_model, tools=registry, permission=_deny_engine("deploy_prod"), identity=identity)
    result = await loop.run("deploy 1.2.3")
    assert result.status == RunStatus.COMPLETED
    # Tool result message should contain the denial
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert any("Permission denied" in str(m.content) for m in tool_msgs)


@pytest.mark.asyncio
async def test_escalate_pauses_run(mock_model):
    mock_model.invoke = AsyncMock(return_value=_tool_resp("c1", "deploy_prod", {"version": "1.2.3"}))
    registry = ToolRegistry()
    registry.register("deploy_prod", lambda version: "deployed", description="Deploy")
    identity = Identity(id="agent:bot", name="bot", type=IdentityType.AGENT)
    checkpointer = InMemoryCheckpoints()
    loop = AgentLoop(
        model=mock_model, tools=registry,
        permission=_escalate_engine("deploy_prod"), identity=identity,
        checkpointer=checkpointer,
    )
    result = await loop.run("deploy 1.2.3", thread_id=ThreadId("t_esc"))
    assert result.status == RunStatus.PAUSED
    assert result.checkpoint_id is not None


@pytest.mark.asyncio
async def test_resume_after_escalate_completes(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "deploy_prod", {"version": "1.2.3"}),
        _tool_resp("c2", "deploy_prod", {"version": "1.2.3"}),
        _text("deployed successfully"),
    ])
    registry = ToolRegistry()
    registry.register("deploy_prod", lambda version: f"deployed {version}", description="Deploy")
    identity = Identity(id="agent:bot", name="bot", type=IdentityType.AGENT)
    checkpointer = InMemoryCheckpoints()
    loop = AgentLoop(
        model=mock_model, tools=registry,
        permission=_escalate_engine("deploy_prod"), identity=identity,
        checkpointer=checkpointer,
    )
    tid = ThreadId("t_resume")
    result = await loop.run("deploy 1.2.3", thread_id=tid)
    assert result.status == RunStatus.PAUSED

    # Replace engine with allow-all and resume
    loop._permission = _allow_engine()
    result2 = await loop.resume(thread_id=tid, input={"approved": True})
    assert result2.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_loop_without_permission_still_works(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "add", {"a": 1, "b": 2}),
        _text("3"),
    ])
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    loop = AgentLoop(model=mock_model, tools=registry)
    result = await loop.run("add 1+2")
    assert result.status == RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_permission_check_event_emitted(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "add", {"a": 1, "b": 2}),
        _text("3"),
    ])
    from mori.observability.engine import ObservabilityEngine
    from mori.observability.events import ObservabilityConfig

    collected = []

    class Sink:
        realtime = True
        async def write(self, e): collected.append(e)
        async def write_batch(self, es): collected.extend(es)
        async def flush(self): pass
        async def close(self): pass

    obs = ObservabilityEngine(sinks=[Sink()], config=ObservabilityConfig(buffer_size=100))
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    identity = Identity(id="user:carl", name="carl", type=IdentityType.USER)
    loop = AgentLoop(
        model=mock_model, tools=registry, observability=obs,
        permission=_allow_engine(), identity=identity,
    )
    await loop.run("add 1+2")
    await obs.flush()
    event_types = [e.event_type for e in collected]
    assert "permission.check" in event_types
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_loop_permission_v05.py -v 2>&1 | head -15
```

Expected: failures because permission gating doesn't exist yet

- [ ] **Step 3: Add permission gating to _phase_act**

In `mori/runtime/loop.py`, replace the `_phase_act` method with:

```python
    async def _phase_act(self, state: MoriState) -> None:
        last_msg = state.messages[-1]
        if not last_msg.tool_calls:
            return

        from mori.observability.events import PermissionCheckEvent, ToolInvokeEvent, ToolResultEvent

        for call in last_msg.tool_calls:
            # Permission check (if engine configured)
            if self._permission and self._identity:
                import time as _time
                from mori.permission.types import Permission, Resource, ResourceType
                from mori.types import PermissionDecision

                perm_start = _time.monotonic()
                perm_result = await self._permission.check(
                    self._identity,
                    Resource(type=ResourceType.TOOL, id=call.name),
                    Permission.EXECUTE,
                )
                perm_elapsed = (_time.monotonic() - perm_start) * 1000

                await self._emit(PermissionCheckEvent(
                    event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                    run_id=state.run_id,
                    identity_id=self._identity.id,
                    resource_type="tool", resource_id=call.name,
                    permission="x", decision=perm_result.decision.value,
                    rule_applied_priority=(
                        perm_result.rule_applied.priority
                        if perm_result.rule_applied else None
                    ),
                    duration_ms=perm_elapsed,
                ))

                if perm_result.decision == PermissionDecision.DENY:
                    content = f"Permission denied: not authorized to invoke '{call.name}'"
                    state.messages.append(Message(role="tool", content=content, tool_call_id=call.id))
                    state.total_tool_calls += 1
                    continue

                if perm_result.decision == PermissionDecision.ESCALATE:
                    state.status = RunStatus.PAUSED
                    state.paused_reason = f"ESCALATE: '{call.name}' requires approval"
                    state.paused_tool_call = call
                    return

            spec = self._tools.get_spec(call.name)
            source = spec.source if spec else "native"

            await self._emit(ToolInvokeEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id, tool_name=call.name, source=source,
                arguments=call.arguments,
            ))

            result = await self._tools.invoke(call.name, call.arguments)

            await self._emit(ToolResultEvent(
                event_id=f"evt_{_uid()}", timestamp=datetime.now(timezone.utc),
                run_id=state.run_id, tool_name=call.name, success=result.success,
                latency_ms=result.latency_ms, error=result.error,
                result_preview=str(result.content)[:200] if result.content else None,
            ))

            content = result.content if result.success else f"ERROR: {result.error}"
            state.messages.append(Message(role="tool", content=content, tool_call_id=call.id))
            state.total_tool_calls += 1
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_loop_permission_v05.py -v
```

Expected: 6 passed

- [ ] **Step 5: Run full suite to check nothing broke**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: ≥364 passed, same 3 voyageai xfail

- [ ] **Step 6: Commit**

```bash
git add mori/runtime/loop.py tests/test_loop_permission_v05.py
git commit -m "feat: loop permission — check EXECUTE before tool invoke; ESCALATE → PAUSED + checkpoint"
```

---

## Task 8: Loop Integration — Hook Dispatch

**Files:**
- Modify: `mori/runtime/loop.py` (hook dispatch at lifecycle events)
- Create: `tests/test_loop_hooks_v05.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_loop_hooks_v05.py
import pytest
from unittest.mock import AsyncMock

from mori.hooks.registry import HookRegistry
from mori.model.base import ModelAdapter
from mori.runtime.loop import AgentLoop
from mori.tools.registry import ToolRegistry
from mori.types import (
    Message, ModelResponse, TokenUsage, ToolCall,
)


def _text(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="end_turn",
    )


def _tool_resp(tid, name, args):
    return ModelResponse(
        message=Message(role="assistant", content="", tool_calls=[ToolCall(id=tid, name=name, arguments=args)]),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="tool_use",
    )


@pytest.fixture
def mock_model():
    model = AsyncMock(spec=ModelAdapter)
    model.model_id = "test"
    model.supports_tool_use = True
    model.max_context_tokens = 100000
    return model


@pytest.mark.asyncio
async def test_run_start_and_end_hooks_fire(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()
    fired = []
    hooks.register("run.start", lambda p: fired.append("start"))
    hooks.register("run.end", lambda p: fired.append("end"))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("test")
    assert "start" in fired
    assert "end" in fired


@pytest.mark.asyncio
async def test_tool_before_hook_modifies_arguments(mock_model):
    calls = []
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "add", {"a": 1, "b": 2}),
        _text("result"),
    ])
    registry = ToolRegistry()

    def spy_add(a, b):
        calls.append({"a": a, "b": b})
        return a + b

    registry.register("add", spy_add, description="Add")
    hooks = HookRegistry()

    def modify_hook(tool_call):
        tool_call.arguments["a"] = 99
        return tool_call

    hooks.register("tool.invoke.before", modify_hook, priority=10)
    loop = AgentLoop(model=mock_model, tools=registry, hooks=hooks)
    await loop.run("add")
    assert calls[0]["a"] == 99


@pytest.mark.asyncio
async def test_tool_after_hook_fires(mock_model):
    mock_model.invoke = AsyncMock(side_effect=[
        _tool_resp("c1", "add", {"a": 1, "b": 2}),
        _text("result"),
    ])
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    hooks = HookRegistry()
    seen_tools = []
    hooks.register("tool.invoke.after", lambda r: seen_tools.append(r.tool_name))
    loop = AgentLoop(model=mock_model, tools=registry, hooks=hooks)
    await loop.run("add")
    assert "add" in seen_tools


@pytest.mark.asyncio
async def test_model_request_before_hook_fires(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()
    requests_seen = []
    hooks.register("model.request.before", lambda req: requests_seen.append(req) or req)
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("test")
    assert len(requests_seen) >= 1


@pytest.mark.asyncio
async def test_model_response_after_hook_fires(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    hooks = HookRegistry()
    responses_seen = []
    hooks.register("model.response.after", lambda resp: responses_seen.append(resp))
    loop = AgentLoop(model=mock_model, tools=ToolRegistry(), hooks=hooks)
    await loop.run("test")
    assert len(responses_seen) >= 1


@pytest.mark.asyncio
async def test_loop_without_hooks_still_works(mock_model):
    mock_model.invoke = AsyncMock(return_value=_text("done"))
    from mori.types import RunStatus
    loop = AgentLoop(model=mock_model, tools=ToolRegistry())
    result = await loop.run("test")
    assert result.status == RunStatus.COMPLETED
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_loop_hooks_v05.py -v 2>&1 | head -15
```

Expected: most tests fail (hooks don't fire yet)

- [ ] **Step 3: Add hook dispatch to loop**

In `mori/runtime/loop.py`, modify `_phase_plan` to fire model hooks:

```python
    async def _phase_plan(self, state: MoriState) -> None:
        request = self._assemble_request(state)
        if self._hooks:
            request = await self._hooks.dispatch_before("model.request.before", request)
        response = await self._model.invoke(request)
        if self._hooks:
            await self._hooks.dispatch_after("model.response.after", response)
        state.messages.append(response.message)
        state.total_input_tokens += response.usage.input_tokens
        state.total_output_tokens += response.usage.output_tokens
```

In `_phase_act`, add hook dispatch around each tool invocation (after the permission block, before `self._tools.invoke`):

```python
            # Before hook (can modify ToolCall)
            if self._hooks:
                call = await self._hooks.dispatch_before("tool.invoke.before", call)

            result = await self._tools.invoke(call.name, call.arguments)

            # After hook (observe ToolResult)
            if self._hooks:
                await self._hooks.dispatch_after("tool.invoke.after", result)
```

In `_run_from_state`, add run.start and run.end hooks after the corresponding events:

After `await self._emit(RunStartEvent(...))`:
```python
        if self._hooks:
            await self._hooks.dispatch_after("run.start", {"task": state.task, "run_id": state.run_id})
```

After `await self._emit(RunEndEvent(...))`:
```python
        if self._hooks:
            await self._hooks.dispatch_after("run.end", {"status": state.status, "run_id": state.run_id})
```

Also fire `permission.check.after` in `_phase_act` after emitting `PermissionCheckEvent`:
```python
                if self._hooks:
                    await self._hooks.dispatch_after("permission.check.after", perm_result)
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_loop_hooks_v05.py -v
```

Expected: 6 passed

- [ ] **Step 5: Run full suite**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: ≥370 passed

- [ ] **Step 6: Commit**

```bash
git add mori/runtime/loop.py tests/test_loop_hooks_v05.py
git commit -m "feat: hook dispatch — run.start/end, tool.invoke.before/after, model.request.before, model.response.after, permission.check.after"
```

---

## Task 9: Builder Integration

**Files:**
- Modify: `mori/agent.py`
- Create: `tests/test_builder_v05.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_builder_v05.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mori import Mori
from mori.permission.types import Identity, IdentityType
from mori.types import (
    Message, ModelResponse, RunStatus, ThreadId, TokenUsage, ToolCall,
)


def _text(text):
    return ModelResponse(
        message=Message(role="assistant", content=text),
        usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="end_turn",
    )


def test_builder_identity():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .identity(Identity(id="agent:bot", name="bot", type=IdentityType.AGENT, groups=["engineering"]))
            .build()
        )
        assert agent.identity is not None
        assert agent.identity.id == "agent:bot"


def test_builder_checkpointer_inmemory():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").checkpointer("inmemory").build()
        assert agent.checkpointer is not None


def test_builder_checkpointer_file(tmp_path):
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .checkpointer("file", directory=str(tmp_path))
            .build()
        )
        assert agent.checkpointer is not None


def test_builder_checkpointer_sqlite(tmp_path):
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .checkpointer("sqlite", path=str(tmp_path / "ckpts.db"))
            .build()
        )
        assert agent.checkpointer is not None


def test_builder_policy_file(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "rules:\n"
        "  - resource: {type: tool, pattern: \"*\"}\n"
        "    identity: {match: any, value: \"*\"}\n"
        "    permissions: \"r-x\"\n"
        "    effect: allow\n"
    )
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        agent = Mori.builder().model("anthropic", api_key="test").policy_file(str(policy)).build()
        assert agent.permission is not None


def test_builder_hook():
    with patch("mori.agent.AnthropicAdapter") as M:
        M.return_value = AsyncMock()
        fired = []
        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .hook("run.end", lambda p: fired.append("end"))
            .build()
        )
        assert agent.hooks is not None
        assert len(agent.hooks.list_hooks("run.end")) == 1


@pytest.mark.asyncio
async def test_mori_resume(tmp_path):
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "rules:\n"
        "  - resource: {type: tool, pattern: \"deploy_*\"}\n"
        "    identity: {match: any, value: \"*\"}\n"
        "    permissions: \"--x\"\n"
        "    effect: escalate\n"
        "    priority: 10\n"
    )
    with patch("mori.agent.AnthropicAdapter") as M:
        mock_adapter = AsyncMock()
        mock_adapter.model_id = "test"
        mock_adapter.supports_tool_use = True
        mock_adapter.max_context_tokens = 100000
        mock_adapter.invoke = AsyncMock(side_effect=[
            ModelResponse(
                message=Message(role="assistant", content="",
                    tool_calls=[ToolCall(id="c1", name="deploy_prod", arguments={"version": "1.2.3"})]),
                usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="tool_use",
            ),
            ModelResponse(
                message=Message(role="assistant", content="",
                    tool_calls=[ToolCall(id="c2", name="deploy_prod", arguments={"version": "1.2.3"})]),
                usage=TokenUsage(input_tokens=10, output_tokens=5), stop_reason="tool_use",
            ),
            _text("deployed successfully"),
        ])
        M.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(lambda version: f"deploying {version}", description="Deploy to prod", name="deploy_prod")
            .checkpointer("inmemory")
            .policy_file(str(policy))
            .build()
        )
        result = await agent.run("Deploy 1.2.3", thread_id="resume_thread")
        assert result.status == RunStatus.PAUSED

        # Swap permission engine to allow-all and resume
        from mori.permission.engine import PermissionEngine
        from mori.permission.types import IdentityPattern, PermissionRule, ResourcePattern
        engine = PermissionEngine()
        engine.load_rules([PermissionRule(
            resource=ResourcePattern(type="*", pattern="*"),
            identity=IdentityPattern(match="any", value="*"),
            permissions="rwx", effect="allow",
        )])
        agent._loop._permission = engine
        result2 = await agent.resume(thread_id="resume_thread", input={"approved": True})
        assert result2.status == RunStatus.COMPLETED
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_builder_v05.py -v 2>&1 | head -20
```

Expected: `AttributeError: 'MoriBuilder' object has no attribute 'identity'`

- [ ] **Step 3: Add builder fields and methods**

In `mori/agent.py`, in `MoriBuilder.__init__`, add:

```python
        self._identity: Any | None = None
        self._policy_file: str | None = None
        self._checkpointer_config: dict | None = None
        self._hook_handlers: list[tuple[str, Any, int]] = []
```

Add these builder methods to `MoriBuilder`:

```python
    def identity(self, identity: Any) -> MoriBuilder:
        self._identity = identity
        return self

    def policy_file(self, path: str) -> MoriBuilder:
        self._policy_file = path
        return self

    def checkpointer(self, backend_type: str, **kwargs: Any) -> MoriBuilder:
        self._checkpointer_config = {"type": backend_type, **kwargs}
        return self

    def hook(self, event_name: str, handler: Any, priority: int = 100) -> MoriBuilder:
        self._hook_handlers.append((event_name, handler, priority))
        return self
```

- [ ] **Step 4: Wire up in build()**

In `MoriBuilder.build()`, after step 6 (budget manager), add steps 7-9:

```python
        # 7. Permission engine
        permission_engine = None
        if self._policy_file or self._identity:
            from mori.permission.engine import PermissionEngine
            permission_engine = PermissionEngine()
            if self._policy_file:
                permission_engine.load_from_yaml(self._policy_file)

        # 8. Checkpointer
        checkpointer = None
        if self._checkpointer_config:
            from mori.control.checkpoint import (
                FileCheckpoints, InMemoryCheckpoints, SQLiteCheckpoints,
            )
            ctype = self._checkpointer_config["type"]
            if ctype == "inmemory":
                checkpointer = InMemoryCheckpoints()
            elif ctype == "file":
                checkpointer = FileCheckpoints(directory=self._checkpointer_config["directory"])
            elif ctype == "sqlite":
                checkpointer = SQLiteCheckpoints(path=self._checkpointer_config["path"])
            else:
                raise ValueError(f"Unknown checkpointer type: {ctype}")

        # 9. Hooks
        hook_registry = None
        if self._hook_handlers:
            from mori.hooks.registry import HookRegistry
            hook_registry = HookRegistry()
            for event_name, handler, priority in self._hook_handlers:
                hook_registry.register(event_name, handler, priority=priority)
```

Update the AgentLoop construction to pass the new params:

```python
        loop = AgentLoop(
            model=self._model_adapter, tools=registry, observability=obs,
            control=control, memory=memory_module,
            skills=skills_module, budget=budget_manager,
            checkpointer=checkpointer, permission=permission_engine,
            identity=self._identity, hooks=hook_registry,
        )

        return Mori(
            loop=loop, tools=registry, observability=obs,
            mcp_configs=self._mcp_servers, memory=memory_module,
            skills=skills_module, budget=budget_manager,
            identity=self._identity, permission=permission_engine,
            checkpointer=checkpointer, hooks=hook_registry,
        )
```

- [ ] **Step 5: Update Mori class**

In `Mori.__init__`, add:

```python
        self._identity = identity
        self._permission = permission
        self._checkpointer = checkpointer
        self._hooks = hooks
```

With matching constructor params:

```python
    def __init__(
        self,
        loop: AgentLoop,
        tools: ToolRegistry,
        observability: ObservabilityEngine | None = None,
        mcp_configs: list[dict[str, Any]] | None = None,
        memory: Any = None,
        skills: Any = None,
        budget: Any = None,
        identity: Any = None,
        permission: Any = None,
        checkpointer: Any = None,
        hooks: Any = None,
    ) -> None:
```

Add properties:

```python
    @property
    def identity(self) -> Any:
        return self._identity

    @property
    def permission(self) -> Any:
        return self._permission

    @property
    def checkpointer(self) -> Any:
        return self._checkpointer

    @property
    def hooks(self) -> Any:
        return self._hooks
```

Add `resume()` method to `Mori`:

```python
    async def resume(
        self,
        thread_id: str,
        input: dict[str, Any] | None = None,
    ) -> RunResult:
        from mori.types import ThreadId
        return await self._loop.resume(ThreadId(thread_id), input or {})
```

- [ ] **Step 6: Run tests to verify they pass**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_builder_v05.py -v
```

Expected: 7 passed

- [ ] **Step 7: Run full suite**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: ≥377 passed

- [ ] **Step 8: Commit**

```bash
git add mori/agent.py tests/test_builder_v05.py
git commit -m "feat: builder .identity() .policy_file() .checkpointer() .hook() + Mori.resume()"
```

---

## Task 10: Exit Test + Example + v0.5.0 Tag

**Files:**
- Create: `tests/test_integration_v05.py`
- Create: `examples/governance.py`

- [ ] **Step 1: Write the exit test**

```python
# tests/test_integration_v05.py
"""v0.5 exit test — permission check events appear in JSONL traces."""
import json

import pytest
from unittest.mock import AsyncMock, patch

from mori import Mori
from mori.permission.types import Identity, IdentityType
from mori.types import (
    Message, ModelResponse, RunStatus, TokenUsage, ToolCall,
)


@pytest.mark.asyncio
async def test_exit_v05_escalate_pauses_and_events_in_traces(tmp_path):
    traces_path = tmp_path / "traces.jsonl"
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "rules:\n"
        "  - resource: {type: tool, pattern: \"deploy_*\"}\n"
        "    identity: {match: type, value: agent}\n"
        "    permissions: \"--x\"\n"
        "    effect: escalate\n"
        "    priority: 10\n"
    )
    with patch("mori.agent.AnthropicAdapter") as M:
        mock_adapter = AsyncMock()
        mock_adapter.model_id = "test"
        mock_adapter.supports_tool_use = True
        mock_adapter.max_context_tokens = 100000
        mock_adapter.invoke = AsyncMock(return_value=ModelResponse(
            message=Message(
                role="assistant", content="",
                tool_calls=[ToolCall(id="c1", name="deploy_prod", arguments={"version": "1.2.3"})],
            ),
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            stop_reason="tool_use",
        ))
        M.return_value = mock_adapter

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(lambda version: f"deploying {version}", description="Deploy to prod", name="deploy_prod")
            .identity(Identity(id="agent:bot", name="bot", type=IdentityType.AGENT))
            .checkpointer("inmemory")
            .policy_file(str(policy))
            .sink("jsonl", path=str(traces_path))
            .build()
        )
        result = await agent.run("Deploy version 1.2.3", thread_id="exit_test")

    # Exit test assertion from IMPLEMENTATION-PLAN.md:
    assert result.status == RunStatus.PAUSED

    traces = [json.loads(line) for line in traces_path.read_text().splitlines() if line.strip()]
    perm_events = [e for e in traces if e["event_type"] == "permission.check"]
    assert len(perm_events) > 0, "No permission.check events found in traces"
    assert any(e["decision"] in ("deny", "escalate") for e in perm_events), \
        "No deny/escalate decision in permission events"
```

- [ ] **Step 2: Run the exit test to verify it fails**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_integration_v05.py -v 2>&1 | head -15
```

Expected: Test should fail if any wiring is incomplete; if all previous tasks are done correctly, it passes immediately.

- [ ] **Step 3: Run the exit test and verify it passes**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/test_integration_v05.py -v
```

Expected: 1 passed

- [ ] **Step 4: Write the governance example**

```python
# examples/governance.py
"""v0.5 governance demo — permission engine + hooks + escalate/resume."""
import asyncio
import json

from unittest.mock import AsyncMock, patch

from mori import Mori
from mori.permission.engine import PermissionEngine
from mori.permission.types import (
    Identity, IdentityPattern, IdentityType, PermissionRule, ResourcePattern, ResourceType,
)
from mori.types import Message, ModelResponse, RunStatus, TokenUsage, ToolCall


async def main():
    # Build a policy that escalates all deploy_ tools
    with patch("mori.agent.AnthropicAdapter") as M:
        mock_adapter = AsyncMock()
        mock_adapter.model_id = "test"
        mock_adapter.supports_tool_use = True
        mock_adapter.max_context_tokens = 100000
        mock_adapter.invoke = AsyncMock(side_effect=[
            # First run: model tries to deploy → ESCALATE → PAUSED
            ModelResponse(
                message=Message(
                    role="assistant", content="",
                    tool_calls=[ToolCall(id="c1", name="deploy_prod", arguments={"version": "2.0.0"})],
                ),
                usage=TokenUsage(input_tokens=20, output_tokens=8),
                stop_reason="tool_use",
            ),
            # After resume: model retries → completes
            ModelResponse(
                message=Message(
                    role="assistant", content="",
                    tool_calls=[ToolCall(id="c2", name="deploy_prod", arguments={"version": "2.0.0"})],
                ),
                usage=TokenUsage(input_tokens=25, output_tokens=8),
                stop_reason="tool_use",
            ),
            ModelResponse(
                message=Message(role="assistant", content="Deployment complete. Version 2.0.0 is live."),
                usage=TokenUsage(input_tokens=30, output_tokens=15),
                stop_reason="end_turn",
            ),
        ])
        M.return_value = mock_adapter

        # Track hook activations
        hook_log = []

        agent = (
            Mori.builder()
            .model("anthropic", api_key="test")
            .tool(lambda version: f"deployed {version}", description="Deploy to prod", name="deploy_prod")
            .identity(Identity(id="agent:release-bot", name="release-bot", type=IdentityType.AGENT))
            .checkpointer("inmemory")
            .hook("permission.check.after", lambda r: hook_log.append(f"permission:{r.decision.value}"))
            .hook("run.end", lambda p: hook_log.append(f"run.end:{p['status'].value}"))
            .build()
        )

        # Load escalate policy
        engine = PermissionEngine()
        engine.load_rules([PermissionRule(
            resource=ResourcePattern(type=ResourceType.TOOL, pattern="deploy_*"),
            identity=IdentityPattern(match="any", value="*"),
            permissions="--x", effect="escalate", priority=5,
        )])
        agent._loop._permission = engine

        print("=== Run 1: initial deploy request ===")
        result = await agent.run("Deploy version 2.0.0 to production", thread_id="deploy-2.0.0")
        print(f"Status: {result.status.value}")
        print(f"Checkpoint: {result.checkpoint_id}")
        print(f"Hooks fired: {hook_log}")
        assert result.status == RunStatus.PAUSED

        # Operator approves; swap to allow-all policy
        engine2 = PermissionEngine()
        engine2.load_rules([PermissionRule(
            resource=ResourcePattern(type="*", pattern="*"),
            identity=IdentityPattern(match="any", value="*"),
            permissions="rwx", effect="allow",
        )])
        agent._loop._permission = engine2

        print("\n=== Run 2: resume after operator approval ===")
        result2 = await agent.resume(
            thread_id="deploy-2.0.0", input={"approved": True, "approved_by": "carl"}
        )
        print(f"Status: {result2.status.value}")
        print(f"Final output: {result2.final_output}")
        print(f"Hooks fired: {hook_log}")
        assert result2.status == RunStatus.COMPLETED
        print("\n✓ Governance demo complete")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: Run the full test suite one final time**

```
cd /Users/carlmueller/Projects/Mori && python -m pytest tests/ -q 2>&1 | tail -10
```

Expected: ≥378 passed, 3 voyageai xfail/skip, 0 errors

- [ ] **Step 6: Verify the example runs**

```
cd /Users/carlmueller/Projects/Mori && python examples/governance.py
```

Expected: prints run status `paused` then `completed` with no errors

- [ ] **Step 7: Final commit**

```bash
git add tests/test_integration_v05.py examples/governance.py
git commit -m "feat: v0.5 exit test + governance example"
```

- [ ] **Step 8: Tag v0.5.0**

```bash
git tag v0.5.0
```

---

## Self-Review Checklist

### Spec Coverage

| Spec 06 Requirement | Task |
|---------------------|------|
| Identity + IdentityType | Task 1 |
| Resource + ResourceType | Task 1 |
| Permission enum (r/w/x) | Task 1 |
| PermissionRule + ResourcePattern + IdentityPattern | Task 1 |
| Condition + ConditionType | Task 1 |
| PermissionEngine.check() — deny-wins algorithm | Task 2 |
| Glob pattern matching | Task 2 |
| Group membership matching | Task 2 |
| YAML policy loader | Task 2 |
| can() sync helper | Task 2 |
| explain() | Task 2 |
| ESCALATE → checkpoint + pause | Task 7 |
| Every check logged via Observability | Tasks 5 + 7 |

| Spec 07 Requirement | Task |
|---------------------|------|
| CheckpointStore Protocol | Task 3 |
| InMemoryCheckpoints | Task 3 |
| FileCheckpoints | Task 3 |
| SQLiteCheckpoints | Task 3 |
| MoriState JSON round-trip | Task 3 |
| load_latest() returns most recent | Task 3 |
| Save on completion + pause | Task 6 |
| Save every N steps | Task 6 |
| Mori.resume() | Tasks 6 + 9 |

| Spec 10-A Requirement | Task |
|-----------------------|------|
| HookRegistry.register / unregister | Task 4 |
| hook() decorator | Task 4 |
| dispatch_before (priority-ordered, modifiable) | Task 4 |
| dispatch_after (all receive same payload) | Task 4 |
| Hook timeout + fail_open | Task 4 |
| Sync + async handlers | Task 4 |
| max_hooks_per_event enforced | Task 4 |
| tool.invoke.before/after | Task 8 |
| model.request.before/after | Task 8 |
| run.start/end | Task 8 |
| permission.check.after | Task 8 |

### Parallelizable Tasks

Tasks 1, 3, and 4 are fully independent and can be dispatched simultaneously. Task 2 depends on Task 1. Task 5 depends on Tasks 1 and 4. Tasks 6-9 each depend on all previous tasks.

Suggested dispatch order:
- Batch 1 (parallel): Tasks 1, 3, 4
- Batch 2 (sequential): Task 2 (needs 1), Task 5 (needs 1+4)
- Batch 3 (sequential): Tasks 6 → 7 → 8 → 9 → 10
