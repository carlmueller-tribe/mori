# 05: Tools and Protocols

**Status:** Draft v3
**Module:** `mori.tools`, `mori.protocols`
**Dependencies:** Spec 01
**Phase:** 1

---

## 1. Purpose

Manage all tools the agent can call. A tool is a callable with a schema. Tools can come from five sources: native Python functions, CLI programs, MCP servers, A2A agent delegation, or OpenAPI endpoints. The Tool Registry provides a unified interface regardless of source.

## 2. Design Principle

Tools are callables with schemas. The source doesn't matter.

```python
# A Python function is a tool:
@mori.tool(description="Read a file from disk")
async def read_file(path: str) -> str:
    async with aiofiles.open(path) as f:
        return await f.read()

# A CLI program is a tool:
agent.tools.register_cli(
    name="rg_search",
    command="rg",
    description="Search files with ripgrep",
    args_schema={"pattern": {"type": "string"}, "path": {"type": "string", "default": "."}},
)

# An MCP server provides tools:
agent.tools.register_mcp_server("github", url="http://localhost:3001")

# All three show up in the same registry and are callable the same way.
```

## 3. Tool Registry

The central registry that holds all tools regardless of source.

```python
class ToolRegistry:
    def __init__(self, config: ToolRegistryConfig | None = None) -> None: ...

    # --- Registration ---

    def register(
        self,
        name: str,
        fn: Callable,
        description: str,
        input_schema: dict | None = None,
        tags: list[str] | None = None,
    ) -> ToolId:
        """Register a native Python function as a tool.

        If input_schema is None, it is inferred from the function's
        type annotations using pydantic or inspect.
        """

    def tool(
        self,
        description: str,
        name: str | None = None,
        tags: list[str] | None = None,
    ) -> Callable:
        """Decorator for registering tools.

        @tools.tool(description="Read a file")
        async def read_file(path: str) -> str: ...
        """

    async def register_mcp_server(
        self,
        name: str,
        url: str,
        transport: Literal["sse", "stdio", "http"] = "sse",
        auth: AuthConfig | None = None,
    ) -> list[ToolId]:
        """Connect to an MCP server, discover its tools, register them.
        Returns the IDs of all discovered tools."""

    def register_cli(
        self,
        name: str,
        command: str,
        description: str,
        args_schema: dict | None = None,
        args_format: Literal["positional", "flags", "subcommand"] = "flags",
        shell: bool = False,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: float = 60.0,
        tags: list[str] | None = None,
    ) -> ToolId:
        """Register a CLI program or shell command as a tool.

        command: the executable (e.g., "rg", "git", "python", "./my-script.sh")
        args_format: how tool arguments are mapped to command-line args:
          - "flags": {"pattern": "foo", "path": "."} → rg --pattern foo --path .
          - "positional": {"pattern": "foo", "path": "."} → rg foo .
          - "subcommand": {"action": "status"} → git status
        shell: if True, run via shell (enables pipes, redirects). Use with caution.
        cwd: working directory for the subprocess.
        env: additional environment variables merged with current env.
        timeout_sec: max wall-clock time for the subprocess.
        """

    async def register_openapi(
        self,
        name: str,
        spec_url: str,
        auth: AuthConfig | None = None,
    ) -> list[ToolId]:
        """Parse an OpenAPI spec and register each endpoint as a tool."""

    def unregister(self, tool_id: ToolId) -> bool: ...

    # --- Discovery ---

    def list_specs(self, source: ToolSource | None = None, tags: list[str] | None = None) -> list[ToolSpec]:
        """List all tool specs, optionally filtered."""

    def get_spec(self, name: str) -> ToolSpec | None: ...

    def search(self, query: str, limit: int = 10) -> list[ToolSpec]:
        """Semantic search over tool names and descriptions."""

    # --- Invocation ---

    async def invoke(
        self,
        name: str,
        arguments: dict,
    ) -> ToolResult:
        """Invoke a tool by name, regardless of source.

        For native tools: call the function directly.
        For CLI tools: build the command, run subprocess, return stdout/stderr.
        For MCP tools: route through the MCP client.
        For OpenAPI tools: make the HTTP request.

        Validates arguments against schema before invocation.
        """

    async def invoke_batch(
        self,
        calls: list[tuple[str, dict]],
        concurrency: int = 5,
    ) -> list[ToolResult]:
        """Execute multiple tool calls with bounded concurrency."""

    # --- Health ---

    async def health_check(self) -> dict[str, HealthStatus]:
        """Check health of all remote tool sources (MCP servers, APIs)."""

    async def close(self) -> None:
        """Disconnect from all remote sources."""
```

## 4. Schema Inference for Native Tools

When a Python function is registered without an explicit `input_schema`, Mori infers it:

```python
@tools.tool(description="Add two numbers")
async def add(a: int, b: int) -> int:
    return a + b

# Inferred schema:
# {
#   "type": "object",
#   "properties": {
#     "a": {"type": "integer"},
#     "b": {"type": "integer"}
#   },
#   "required": ["a", "b"]
# }
```

Inference uses `inspect.signature` + type annotation mapping. Pydantic models as argument types produce their full JSON Schema. Unannotated arguments default to `{"type": "string"}`.

## 5. MCP Client

Mori includes a native MCP client. No `langchain-mcp-adapters` dependency.

```python
class MCPClient:
    """Native MCP client speaking JSON-RPC 2.0."""

    def __init__(self, name: str, url: str, transport: str, auth: AuthConfig | None = None) -> None: ...

    async def connect(self) -> None:
        """Establish connection (SSE, stdio, or HTTP)."""

    async def discover_tools(self) -> list[ToolSpec]:
        """Call tools/list and return parsed specs."""

    async def invoke(self, tool_name: str, arguments: dict) -> ToolResult:
        """Call tools/call with the given arguments."""

    async def health_check(self) -> HealthStatus: ...
    async def close(self) -> None: ...
```

**Transport support:**

| Transport | Mechanism                     | Use Case                |
|-----------|-------------------------------|-------------------------|
| SSE       | Server-Sent Events over HTTP  | Long-lived server       |
| stdio     | Subprocess stdin/stdout       | Local tool servers      |
| HTTP      | Stateless POST requests       | Serverless, REST-style  |

**Schema caching:** tool schemas are cached after discovery. Cache entries expire after a configurable TTL (default 300s). On invocation, if the cache is stale, the client re-discovers before calling.

**Argument validation:** before sending a tool call to the server, arguments are validated against the cached JSON Schema. Invalid arguments raise `SchemaValidationError` without making a network call.

## 6. CLI Runner

CLI tools are executed as subprocesses via `anyio`. The runner handles argument formatting, environment setup, timeout enforcement, and output capture.

```python
class CLIRunner:
    """Executes CLI tools as subprocesses."""

    async def run(
        self,
        command: str,
        arguments: dict,
        config: CLIToolConfig,
    ) -> ToolResult:
        """Build command line, execute subprocess, capture output."""

class CLIToolConfig(MoriModel):
    command: str                    # e.g., "rg", "git", "/usr/bin/python3"
    args_format: Literal["positional", "flags", "subcommand"] = "flags"
    shell: bool = False
    cwd: str | None = None
    env: dict[str, str] | None = None
    timeout_sec: float = 60.0
    max_output_bytes: int = 1_048_576   # 1MB cap on stdout/stderr
    capture_stderr: bool = True
```

**Argument formatting:**

| Format       | Arguments                        | Produced Command          |
|-------------|----------------------------------|---------------------------|
| flags       | `{"pattern": "TODO", "path": "."}` | `rg --pattern TODO --path .` |
| positional  | `{"0": "TODO", "1": "src/"}` | `rg TODO src/`            |
| subcommand  | `{"action": "status", "short": true}` | `git status --short`   |

**Boolean flag handling:** `{"verbose": true}` → `--verbose` (flag present). `{"verbose": false}` → omitted.

**Security considerations:**
- Arguments are passed as a list to `subprocess` (no shell injection) unless `shell=True`
- `shell=True` tools require explicit opt-in and should be flagged as high-risk in the Permission Engine
- The `timeout_sec` hard-kills the process if exceeded
- `max_output_bytes` prevents memory exhaustion from runaway output
- stderr is captured separately and included in ToolResult.metadata

**Return mapping:**
- Exit code 0: `ToolResult(success=True, content=stdout)`
- Exit code non-zero: `ToolResult(success=False, content=stdout, error=stderr)`
- Timeout: `ToolResult(success=False, error="Process timed out after {timeout_sec}s")`

**Example registrations:**

```python
# ripgrep for code search
tools.register_cli(
    name="search_code",
    command="rg",
    description="Search for patterns in source code using ripgrep",
    args_schema={
        "pattern": {"type": "string", "description": "Search pattern (regex)"},
        "path": {"type": "string", "default": ".", "description": "Directory to search"},
        "file_type": {"type": "string", "description": "File type filter (e.g., py, ts)"},
    },
    args_format="flags",
    timeout_sec=30.0,
)

# git operations
tools.register_cli(
    name="git",
    command="git",
    description="Run git commands",
    args_schema={
        "action": {"type": "string", "description": "Git subcommand (status, diff, log, etc.)"},
    },
    args_format="subcommand",
    cwd="/path/to/repo",
)

# pytest
tools.register_cli(
    name="run_tests",
    command="pytest",
    description="Run the test suite",
    args_schema={
        "path": {"type": "string", "default": "tests/", "description": "Test path"},
        "verbose": {"type": "boolean", "default": false},
        "k": {"type": "string", "description": "Run tests matching expression"},
    },
    args_format="flags",
    timeout_sec=120.0,
)

# Custom script
tools.register_cli(
    name="deploy_staging",
    command="./scripts/deploy.sh",
    description="Deploy to staging environment",
    args_schema={
        "version": {"type": "string", "description": "Version tag to deploy"},
    },
    args_format="positional",
    env={"DEPLOY_ENV": "staging"},
    tags=["deploy", "high-risk"],
)
```

## 7. Configuration

```python
class ToolRegistryConfig(MoriModel):
    schema_cache_ttl_sec: float = 300.0
    validate_before_invoke: bool = True
    max_concurrent_invocations: int = 10
    invoke_timeout_sec: float = 60.0
    retry_on_server_error: bool = True
    max_retries: int = 2
    retry_backoff_sec: float = 1.0
    max_result_tokens: int = 4000           # Universal cap on tool result size (all sources)
    deferred_schemas: bool = False          # If True, list_specs returns name+description only;
                                            # full input_schema loaded on demand when model selects tool

class AuthConfig(MoriModel):
    type: Literal["bearer", "api_key", "oauth2", "none"] = "none"
    token: str | None = None
    token_env: str | None = None        # Read token from env var
    header_name: str = "Authorization"
```

## 8. Integration with Runtime

The runtime (Spec 02) uses the ToolRegistry in two places:

**Plan phase:** `tools.list_specs()` provides the tool schemas injected into the model request. The model sees all registered tools (native, CLI, MCP, OpenAPI) as a flat list with uniform schemas.

When `deferred_schemas=True`, `list_specs()` returns ToolSpecs with `input_schema=None`. The model sees tool names and descriptions only. When the model selects a tool, the runtime calls `tools.get_spec(name)` to load the full schema for argument validation. This saves context when the tool pool is large (20+ tools).

**Act phase:** `tools.invoke(name, arguments)` routes the call to the correct backend. The runtime does not need to know the source.

After invocation, the result content is truncated to `max_result_tokens` if it exceeds that limit. This prevents a single verbose tool output (e.g., a CLI command dumping a large file) from consuming disproportionate context. Truncation appends `\n[TRUNCATED: output exceeded {max_result_tokens} tokens]` so the model knows data was lost.

## 9. Error Rate Tracking

The registry tracks per-tool metrics:

```python
class ToolMetrics(MoriModel):
    tool_id: ToolId
    total_calls: int = 0
    total_errors: int = 0
    avg_latency_ms: float = 0.0
    last_error: str | None = None
    last_called: datetime | None = None

    @property
    def error_rate(self) -> float:
        return self.total_errors / self.total_calls if self.total_calls > 0 else 0.0
```

These metrics are available via `tools.get_metrics(tool_id)` and are included in observability events.

## 10. Test Criteria

- [ ] A native async function registered via decorator is callable via invoke()
- [ ] A native sync function registered via register() is callable via invoke()
- [ ] Schema inference produces correct JSON Schema from type annotations
- [ ] Pydantic model arguments produce their full JSON Schema
- [ ] register_cli creates a callable tool that runs a subprocess
- [ ] CLI tool with args_format="flags" produces correct command line
- [ ] CLI tool with args_format="positional" produces correct command line
- [ ] CLI tool with args_format="subcommand" produces correct command line
- [ ] CLI tool timeout kills the subprocess and returns error
- [ ] CLI tool with exit code 0 returns success=True with stdout
- [ ] CLI tool with exit code non-zero returns success=False with stderr
- [ ] CLI tool with shell=False prevents shell injection
- [ ] CLI tool max_output_bytes caps captured output
- [ ] register_mcp_server discovers and registers tools from a mock MCP server
- [ ] MCP tool invocation routes through the MCP client
- [ ] register_openapi parses a spec and registers endpoints as tools
- [ ] invoke validates arguments before calling (rejects invalid args)
- [ ] invoke_batch respects concurrency limits
- [ ] health_check reports status for remote sources
- [ ] Error rate tracking correctly computes per-tool metrics
- [ ] Schema cache expires and refreshes after TTL
- [ ] list_specs with source filter returns only matching tools (e.g., source=CLI)
- [ ] list_specs with deferred_schemas=True returns specs with input_schema=None
- [ ] get_spec with deferred_schemas=True returns the full schema on demand
- [ ] invoke truncates results exceeding max_result_tokens
- [ ] Truncated results include the TRUNCATED marker
- [ ] search returns relevant tools by description
