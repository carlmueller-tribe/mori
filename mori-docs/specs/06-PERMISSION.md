# 06: Permission System

**Status:** Draft v3.1 (Universal Resource Governance)
**Module:** `mori.permission`
**Dependencies:** Spec 01

---

## 1. Purpose

Govern access to every resource in Mori: tools, skills, memory layers, MCP servers, agents, files, and network endpoints. The permission model borrows from Unix: every resource has an owner, a group, and permissions for owner/group/other. Every identity (user, agent, skill) operates within a set of groups that determine what it can see, modify, and execute.

This is not just tool-call gating. It is the authorization layer for the entire runtime.

## 2. Design Principles

**Every resource is governed.** Tools, skills, memory layers, MCP servers, A2A agents, filesystem paths, and network domains all have permissions. No resource is exempt.

**Identity is explicit.** Every actor in the system (human user, agent instance, sub-agent, skill execution context) has an identity with group memberships. Anonymous actors get "other" permissions.

**Unix semantics, agent vocabulary.** Owner/group/other with read/write/execute, adapted to the domain: "execute" on a tool means invoke it, "read" on a memory layer means retrieve from it, "execute" on a skill means bind and run it.

**Deny wins.** If any applicable rule denies access, it is denied regardless of other rules that allow it.

**Auditable by default.** Every permission check is logged with the identity, resource, requested permission, decision, and the rule that produced it.

## 3. Core Concepts

### 3.1 Identity

```python
class Identity(MoriModel):
    """An actor in the system."""
    id: str
    name: str
    type: IdentityType
    groups: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

class IdentityType(str, Enum):
    USER = "user"           # Human operator
    AGENT = "agent"         # Agent instance (top-level or sub-agent)
    SKILL = "skill"         # Skill execution context
    SERVICE = "service"     # External service / automation
    SYSTEM = "system"       # Mori runtime itself
```

### 3.2 Groups

Groups are named sets of identities. An identity can belong to multiple groups.

```yaml
# groups.yaml
groups:
  admin:
    description: Full access to all resources
    members: ["user:carl", "user:ops-lead"]
  engineering:
    description: Engineering team members and their agents
    members: ["user:carl", "agent:code-assistant", "agent:test-runner"]
  readonly:
    description: Read-only access for monitoring and auditing
    members: ["service:monitoring", "user:auditor"]
  restricted:
    description: Limited agents with minimal permissions
    members: ["agent:customer-facing", "agent:intern-bot"]
```

### 3.3 Resources

Every governed entity is a resource with a type and an identifier.

```python
class Resource(MoriModel):
    type: ResourceType
    id: str                 # e.g., "mcp:github:create_issue", "memory:episodic"
    owner: str | None = None
    group: str | None = None

class ResourceType(str, Enum):
    TOOL = "tool"
    SKILL = "skill"
    MEMORY_LAYER = "memory_layer"
    MCP_SERVER = "mcp_server"
    AGENT = "agent"
    FILE_PATH = "file_path"
    NETWORK_DOMAIN = "network_domain"
```

### 3.4 Permissions

```python
class Permission(str, Enum):
    READ = "r"      # See/discover/retrieve
    WRITE = "w"     # Create/modify/delete
    EXECUTE = "x"   # Invoke/run/bind
```

**What r/w/x means per resource type:**

| Resource Type  | Read (r)                   | Write (w)                    | Execute (x)                  |
|----------------|----------------------------|------------------------------|------------------------------|
| tool           | See schema, discover       | Modify registration (admin)  | Invoke the tool              |
| skill          | Discover, load content     | Create, modify, deprecate    | Bind and execute             |
| memory_layer   | Retrieve records           | Write/update/delete records  | Promote across layers        |
| mcp_server     | List tools, view health    | Register/unregister          | Connect and invoke tools     |
| agent          | View card, see status      | Modify configuration         | Delegate tasks               |
| file_path      | Read file contents         | Write/create files           | Execute scripts              |
| network_domain | Resolve/lookup             | N/A                          | Make HTTP requests           |

### 3.5 Permission Rules

```python
class PermissionRule(MoriModel):
    resource: ResourcePattern
    identity: IdentityPattern
    permissions: str            # Unix-style: "rwx", "r--", "r-x"
    effect: Literal["allow", "deny", "escalate"]
    priority: int = 100         # Lower = higher priority
    conditions: list[Condition] = Field(default_factory=list)

class ResourcePattern(MoriModel):
    type: ResourceType | Literal["*"]
    pattern: str                # Glob: "mcp:github:*", "memory:*", "tool:read_*"

class IdentityPattern(MoriModel):
    match: Literal["identity", "group", "type", "any"]
    value: str
```

## 4. Permission Engine Interface

```python
class PermissionEngine:
    def __init__(self, config: PermissionConfig) -> None: ...

    # Identity management
    def register_identity(self, identity: Identity) -> None: ...
    def add_to_group(self, identity_id: str, group: str) -> None: ...
    def remove_from_group(self, identity_id: str, group: str) -> None: ...

    # Permission checks
    async def check(self, identity: Identity, resource: Resource, permission: Permission) -> PermissionResult: ...
    async def check_batch(self, identity: Identity, checks: list[tuple[Resource, Permission]]) -> list[PermissionResult]: ...
    def can(self, identity: Identity, resource: Resource, permission: Permission) -> bool: ...

    # Policy management
    def load_rules(self, rules: list[PermissionRule]) -> None: ...
    def load_groups(self, groups: dict[str, list[str]]) -> None: ...
    def load_from_yaml(self, path: str) -> None: ...
    def get_effective_permissions(self, identity: Identity, resource: Resource) -> str: ...

    # Introspection
    def explain(self, identity: Identity, resource: Resource, permission: Permission) -> PermissionExplanation: ...
    def list_accessible(self, identity: Identity, resource_type: ResourceType) -> list[Resource]: ...
```

## 5. Resolution Algorithm

```
1. Collect all rules where resource pattern matches the target resource
2. Filter to rules where identity pattern matches the requesting identity
3. Sort by priority (lowest number first)
4. For each rule in order:
   a. Check conditions (risk level, step count, error rate, time of day)
   b. If conditions not met: skip this rule
   c. If effect=deny and the requested permission is set: → DENY
   d. If effect=escalate and the requested permission is set: → ESCALATE
   e. If effect=allow and the requested permission is set: → mark allowed
5. If allowed and not denied: ALLOW
6. If no rule matched: default_decision (configurable, default DENY)
```

## 6. Conditions

```python
class Condition(MoriModel):
    type: ConditionType
    operator: Literal["eq", "gt", "lt", "gte", "lte", "in", "not_in"]
    value: Any

class ConditionType(str, Enum):
    RISK_CATEGORY = "risk_category"
    STEP_COUNT = "step_count"
    TOTAL_TOKENS = "total_tokens"
    TIME_OF_DAY = "time_of_day"
    TOOL_ERROR_RATE = "tool_error_rate"
```

## 7. Runtime Integration

The Permission Engine is called by every module:

**Tool Registry (Spec 05):**
- list_specs: filter to tools where identity has READ
- invoke: check EXECUTE before calling

**Memory Module (Spec 03):**
- read: check READ on the target memory layer
- write: check WRITE on the target memory layer
- promote: check EXECUTE on the target layer

**Skills Module (Spec 04):**
- discover: filter to skills where identity has READ
- bind/execute: check EXECUTE on the skill

**Protocol Module (Spec 05):**
- register_mcp_server: check WRITE on mcp_server resource
- invoke via MCP: check EXECUTE on the mcp_server

**Agent delegation:**
- delegate: check EXECUTE on the target agent

## 8. Identity Propagation

When the runtime starts, the active identity is set from configuration:

```python
agent = (
    Mori.builder()
    .model(...)
    .identity(Identity(id="agent:code-bot", type=IdentityType.AGENT, groups=["engineering"]))
    .build()
)
```

Sub-agents inherit their parent's identity unless explicitly overridden. The permission system checks the sub-agent's identity independently, preventing privilege escalation.

## 9. Policy File Format

```yaml
# policy.yaml
groups:
  admin:
    members: ["user:carl"]
  engineering:
    members: ["user:carl", "agent:code-bot", "agent:test-runner"]
  customer_facing:
    members: ["agent:support-bot"]

rules:
  # Admin: full access
  - resource: {type: "*", pattern: "*"}
    identity: {match: group, value: admin}
    permissions: "rwx"
    effect: allow
    priority: 1

  # Engineering: read/execute tools and skills
  - resource: {type: tool, pattern: "*"}
    identity: {match: group, value: engineering}
    permissions: "r-x"
    effect: allow
    priority: 50

  - resource: {type: skill, pattern: "*"}
    identity: {match: group, value: engineering}
    permissions: "r-x"
    effect: allow
    priority: 50

  # Engineering: read/write working + episodic, read-only semantic
  - resource: {type: memory_layer, pattern: "working"}
    identity: {match: group, value: engineering}
    permissions: "rw-"
    effect: allow
    priority: 50

  - resource: {type: memory_layer, pattern: "episodic"}
    identity: {match: group, value: engineering}
    permissions: "rw-"
    effect: allow
    priority: 50

  - resource: {type: memory_layer, pattern: "semantic"}
    identity: {match: group, value: engineering}
    permissions: "r--"
    effect: allow
    priority: 50

  # No agents can write personalized memory (only system/admin)
  - resource: {type: memory_layer, pattern: "personalized"}
    identity: {match: type, value: agent}
    permissions: "-w-"
    effect: deny
    priority: 10

  # Block all agents from deploy tools
  - resource: {type: tool, pattern: "deploy_*"}
    identity: {match: type, value: agent}
    permissions: "--x"
    effect: deny
    priority: 5

  # Escalate database writes for human review
  - resource: {type: tool, pattern: "database_*"}
    identity: {match: any, value: "*"}
    permissions: "--x"
    effect: escalate
    priority: 20

  # Customer-facing: only search and respond tools
  - resource: {type: tool, pattern: "*"}
    identity: {match: group, value: customer_facing}
    permissions: "---"
    effect: deny
    priority: 40

  - resource: {type: tool, pattern: "search_*"}
    identity: {match: group, value: customer_facing}
    permissions: "r-x"
    effect: allow
    priority: 30

  # Block /secrets for all agents
  - resource: {type: file_path, pattern: "/secrets/*"}
    identity: {match: type, value: agent}
    permissions: "-wx"
    effect: deny
    priority: 5

  # Escalate when error rate is high
  - resource: {type: tool, pattern: "*"}
    identity: {match: any, value: "*"}
    permissions: "--x"
    effect: escalate
    priority: 25
    conditions:
      - type: tool_error_rate
        operator: gt
        value: 0.2
```

## 10. AIUC-1 Alignment

| AIUC-1 Req | How |
|------------|-----|
| A003: Limit agent data access | Memory layer r/w/x per identity/group |
| B006: Prevent unauthorized actions | Universal resource governance, deny-wins |
| B007: Enforce user access privileges | Identity/group model |
| D003: Restrict unsafe tool calls | Tool execute permissions + conditions |
| E004: Assign accountability | Every check logged with identity + decision |

## 11. Test Criteria

- [ ] Admin group can access all resources
- [ ] Restricted group is denied non-whitelisted tools
- [ ] Deny rules override allow rules at equal priority
- [ ] Lower priority number takes precedence
- [ ] No matching rules returns default_decision (DENY)
- [ ] Glob patterns match correctly
- [ ] Wildcard resource type "*" matches all types
- [ ] Memory layer permissions checked on read, write, promote
- [ ] Skill permissions checked on discover and execute
- [ ] MCP server permissions checked on connect and invoke
- [ ] Sub-agent cannot escalate privileges beyond its own groups
- [ ] Conditions gate rule application correctly
- [ ] ESCALATE triggers checkpoint and pause
- [ ] explain() returns step-by-step resolution trace
- [ ] list_accessible() returns only readable resources
- [ ] Every check is logged via Observability Engine
