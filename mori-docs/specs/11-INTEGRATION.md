# 11: Integration Patterns

**Status:** Draft v3
**Module:** Cross-cutting
**Dependencies:** All prior specs

---

## 1. Purpose

How Mori modules compose into a working system: the builder API, startup sequence, cross-module data flows, error recovery, and the public interface.

## 2. Builder API

```python
from mori import Mori

# Minimal: model + one native tool
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .tool(my_search_function)
    .build()
)
result = await agent.run("Find the latest sales numbers")

# Minimal with MCP
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")
    .mcp_server("filesystem", url="http://localhost:3000")
    .build()
)

# Full configuration
agent = (
    Mori.builder()
    .model("anthropic", model="claude-sonnet-4-20250514")

    # Tools: mix native functions, CLI programs, and remote sources
    .tool(read_file, description="Read a file from disk")
    .tool(write_file, description="Write content to a file")
    .tool(run_tests, description="Run the test suite")
    .cli("search_code", command="rg", description="Search code with ripgrep",
         args_schema={"pattern": {"type": "string"}, "path": {"type": "string", "default": "."}})
    .cli("git", command="git", description="Run git commands", args_format="subcommand", cwd="./repo")
    .mcp_server("github", url="http://localhost:3001")
    .mcp_server("slack", url="http://localhost:3002")

    # Memory
    .memory_backend("sqlite", path="./memory.db")

    # Skills
    .skill_registry("./skills/")
    .skill_registry("/org/shared-skills/")

    # Governance
    .policy_file("./policy.yaml")
    .checkpointer("sqlite", path="./checkpoints.db")

    # Observability
    .sink("jsonl", path="./traces.jsonl")
    .sink("stdout")

    # Limits
    .config(max_steps=100, max_total_tokens=5_000_000)

    # Hooks
    .hook("tool.invoke.before", redact_secrets, priority=10)
    .hook("run.end", notify_on_failure)

    .build()
)

# Run
result = await agent.run("Implement the feature described in issue #42")

# Stream
async for event in agent.stream("Fix the auth bug"):
    print(event.type, event.data)

# Resume after human approval
result = await agent.resume(thread_id="thread_abc", input={"approved": True})

# Inspect state
state = await agent.get_state(thread_id="thread_abc")
history = await agent.get_history(thread_id="thread_abc")
```

## 3. Mori Class

```python
class Mori:
    @staticmethod
    def builder() -> MoriBuilder: ...

    # Execution
    async def run(self, task: str, thread_id: str | None = None, context: dict | None = None) -> RunResult: ...
    async def stream(self, task: str, thread_id: str | None = None) -> AsyncIterator[StreamEvent]: ...
    async def resume(self, thread_id: str, input: dict | None = None) -> RunResult: ...
    async def cancel(self, run_id: str) -> None: ...

    # State inspection
    async def get_state(self, thread_id: str) -> MoriState | None: ...
    async def get_history(self, thread_id: str) -> list[Checkpoint]: ...

    # Module access
    @property
    def tools(self) -> ToolRegistry: ...
    @property
    def memory(self) -> MemoryModule | None: ...
    @property
    def skills(self) -> SkillsModule | None: ...
    @property
    def hooks(self) -> HookRegistry: ...

    # Lifecycle
    async def close(self) -> None: ...
```

## 4. Startup Sequence

```
1. Load configuration (mori.yaml, env vars, builder overrides)

2. Initialize Observability Engine (first: everything else emits events)
3. Initialize Control Bounds
4. Initialize Permission Engine (load policies)
5. Initialize Hook Registry

6. Initialize Tool Registry
   └── Register native Python tools
   └── Connect to MCP servers, discover tools
   └── Parse OpenAPI specs, register endpoints

7. Initialize Memory Backend + Memory Module
8. Initialize Skills Module (load registries, parse manifests)
9. Initialize Budget Manager

10. Initialize Model Adapter
11. Initialize Checkpoint Store

12. Initialize Agent Loop (wire all modules)
13. Ready
```

## 5. Configuration File

```yaml
# mori.yaml
model:
  provider: anthropic
  model: claude-sonnet-4-20250514
  api_key_env: ANTHROPIC_API_KEY

tools:
  mcp_servers:
    - name: filesystem
      url: http://localhost:3000
    - name: github
      url: http://localhost:3001
      auth:
        type: bearer
        token_env: GITHUB_TOKEN
  cli:
    - name: search_code
      command: rg
      description: Search code with ripgrep
      args_format: flags
      timeout_sec: 30
    - name: git
      command: git
      description: Run git commands
      args_format: subcommand
      cwd: ./repo

memory:
  backend: sqlite
  backend_config:
    path: ./memory.db
  embedding_model: text-embedding-3-small

skills:
  registries:
    - path: ./skills/
    - path: /org/shared-skills/

permission:
  policy_files:
    - ./policy.yaml
  default_decision: deny

checkpointer:
  type: sqlite
  path: ./checkpoints.db

observability:
  sinks:
    - type: jsonl
      path: ./traces.jsonl
    - type: stdout

control:
  max_steps: 100
  max_total_tokens: 5000000
  run_timeout_sec: 3600
  idle_timeout_sec: 300

budget:
  base_allocations:
    system_prompt: 0.10
    memory: 0.20
    skill: 0.15
    tool_schemas: 0.10
    conversation: 0.30
    generation: 0.15
```

## 6. Cross-Module Data Flows

Six flows, all mediated by the agent loop:

**Memory → Skills (Experience Distillation):** recurring successful episodic patterns become candidate skill artifacts. Utility function, not automatic.

**Skills → Memory (Execution Recording):** every skill execution writes traces to episodic memory. Automatic in the update phase.

**Skills → Tools (Capability Invocation):** bound skill steps invoke tools via the ToolRegistry. Automatic in the act phase.

**Tools → Skills (Capability Generation):** new tool registrations seed skill authoring opportunities. Advisory, not automatic.

**Memory → Tools (Strategy Selection):** historical tool success rates inform the model's tool choice via memory context. Automatic in the retrieve phase.

**Tools → Memory (Result Assimilation):** tool results are written to working memory. Automatic in the observe phase.

## 7. Error Recovery

**Tool failure:** ControlBounds.should_retry() decides retry with backoff. After exhaustion, the error is injected as a tool message and the model decides next steps.

**Skill mismatch:** observe phase records failure via skills.record_outcome(). Next retrieve phase re-discovers with updated context.

**Budget exhaustion:** retrieve phase gets compressed allocations. Memory re-retrieves with tighter budget. Skills fall back to SUMMARY disclosure. Conversation summarizes older turns.

**Pause/resume:** validate phase sets status=PAUSED on ESCALATE. Checkpoint is saved. Caller provides input via agent.resume(). Loop continues from saved state.

## 8. Graceful Degradation

Every module except model and tools is optional. The agent degrades gracefully:

| Missing Module | Effect                                    |
|----------------|-------------------------------------------|
| Memory         | No retrieval, no episodic recording       |
| Skills         | No skill discovery, model improvises      |
| Permission     | All tool calls are allowed                |
| Budget         | No context allocation management          |
| Observability  | No structured events (still runs)         |
| Checkpointer   | No pause/resume, no recovery from crashes |
| Hooks          | No custom lifecycle logic                 |

## 9. Test Criteria

- [ ] Builder with model + 1 native tool produces a working agent
- [ ] Builder with model + 1 MCP server produces a working agent
- [ ] Builder with model + 1 CLI tool produces a working agent
- [ ] Builder from YAML config matches builder from code
- [ ] run() returns RunResult with correct status
- [ ] stream() yields typed events
- [ ] resume() continues from a paused checkpoint
- [ ] get_state() returns current state for a thread
- [ ] get_history() returns all checkpoints for a thread
- [ ] Each module can be omitted without crashing
- [ ] close() shuts down all modules
- [ ] Tool failure triggers retry then fallback
- [ ] Budget exhaustion triggers compression
- [ ] Native tools, CLI tools, and MCP tools coexist in the same registry
- [ ] AnthropicAdapter produces correct tool schemas and handles tool results
- [ ] OpenAIAdapter produces correct tool schemas and handles tool results
