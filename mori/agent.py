"""Mori — top-level API and builder."""

from __future__ import annotations

from typing import Any, Callable

from mori.control.bounds import ControlBounds, ControlConfig
from mori.model.anthropic import AnthropicAdapter
from mori.observability.engine import ObservabilityEngine
from mori.observability.events import ObservabilityConfig
from mori.observability.sinks.jsonl import JsonlSink
from mori.observability.sinks.stdout import StdoutSink
from mori.runtime.loop import AgentLoop
from mori.runtime.result import RunResult
from mori.tools.registry import ToolRegistry
from mori.types import ThreadId


class MoriBuilder:
    """Fluent builder for constructing a Mori agent."""

    def __init__(self) -> None:
        self._model_adapter: Any = None
        self._tools: list[tuple[str, Callable[..., Any], str, dict[str, Any] | None]] = []
        self._cli_tools: list[dict[str, Any]] = []
        self._mcp_servers: list[dict[str, Any]] = []
        self._sinks: list[Any] = []
        self._config: dict[str, Any] = {}
        self._memory_config: dict[str, Any] | None = None
        self._skill_registry_path: str | None = None
        self._budget_config: dict[str, Any] | None = None
        self._identity: Any | None = None
        self._policy_file: str | None = None
        self._checkpointer_config: dict[str, Any] | None = None
        self._hook_handlers: list[tuple[str, Any, int]] = []

    def model(
        self,
        provider: str,
        *,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        max_tokens: int = 4096,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> MoriBuilder:
        if provider == "anthropic":
            self._model_adapter = AnthropicAdapter(
                model=model, api_key=api_key, max_tokens=max_tokens, base_url=base_url,
            )
        else:
            raise ValueError(f"Unknown model provider: {provider}. Supported: anthropic")
        return self

    def tool(
        self,
        fn: Callable[..., Any],
        description: str,
        name: str | None = None,
        input_schema: dict[str, Any] | None = None,
    ) -> MoriBuilder:
        tool_name = name or fn.__name__
        self._tools.append((tool_name, fn, description, input_schema))
        return self

    def cli(
        self,
        name: str,
        command: str,
        description: str,
        args_format: str = "flags",
        args_schema: dict[str, Any] | None = None,
        shell: bool = False,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: float = 60.0,
        tags: list[str] | None = None,
    ) -> MoriBuilder:
        self._cli_tools.append({
            "name": name, "command": command, "description": description,
            "args_format": args_format, "args_schema": args_schema,
            "shell": shell, "cwd": cwd, "env": env, "timeout_sec": timeout_sec,
            "tags": tags,
        })
        return self

    def mcp_server(
        self,
        name: str,
        url: str,
        transport: str = "sse",
        auth: Any = None,
    ) -> MoriBuilder:
        self._mcp_servers.append({"name": name, "url": url, "transport": transport, "auth": auth})
        return self

    def sink(self, sink_type: str, **kwargs: Any) -> MoriBuilder:
        if sink_type == "stdout":
            self._sinks.append(StdoutSink())
        elif sink_type == "jsonl":
            path = kwargs.get("path")
            if not path:
                raise ValueError("JsonlSink requires a 'path' argument")
            self._sinks.append(JsonlSink(path=path))
        else:
            raise ValueError(f"Unknown sink type: {sink_type}. Supported: stdout, jsonl")
        return self

    def memory_backend(self, backend_type: str, **kwargs: Any) -> MoriBuilder:
        self._memory_config = {"type": backend_type, **kwargs}
        return self

    def skill_registry(self, path: str) -> MoriBuilder:
        self._skill_registry_path = path
        return self

    def budget(
        self,
        total_context_tokens: int = 200_000,
        compaction_threshold_pct: float = 0.85,
        min_generation_tokens: int = 1000,
        max_result_tokens: int = 4000,
        disable_compaction: bool = False,
        slot_overrides: dict[str, float] | None = None,
    ) -> MoriBuilder:
        self._budget_config = {
            "total_context_tokens": total_context_tokens,
            "compaction_threshold_pct": compaction_threshold_pct,
            "min_generation_tokens": min_generation_tokens,
            "max_result_tokens": max_result_tokens,
            "disable_compaction": disable_compaction,
            "slot_overrides": slot_overrides or {},
        }
        return self

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

    def config(self, **kwargs: Any) -> MoriBuilder:
        self._config.update(kwargs)
        return self

    def build(self) -> Mori:
        if self._model_adapter is None:
            raise ValueError("A model must be configured. Call .model() before .build()")

        # 1. Observability
        obs: ObservabilityEngine | None = None
        if self._sinks:
            obs = ObservabilityEngine(sinks=self._sinks, config=ObservabilityConfig())

        # 2. Control bounds
        control_fields = {k: v for k, v in self._config.items() if k in ControlConfig.model_fields}
        control = ControlBounds(config=ControlConfig(**control_fields))

        # 3. Tool registry
        registry = ToolRegistry()
        for tool_name, fn, desc, schema in self._tools:
            registry.register(tool_name, fn, description=desc, input_schema=schema)
        for cli in self._cli_tools:
            registry.register_cli(**cli)

        # 4. Memory
        memory_module = None
        if self._memory_config:
            from mori.memory.module import MemoryModule
            from mori.memory.backends.inmemory import InMemoryBackend
            from mori.memory.backends.sqlite import SQLiteBackend
            from mori.types import MemoryConfig
            backend_type = self._memory_config["type"]
            backend: InMemoryBackend | SQLiteBackend
            if backend_type == "inmemory":
                backend = InMemoryBackend()
            elif backend_type == "sqlite":
                sqlite_backend = SQLiteBackend(path=self._memory_config["path"])
                # Note: SQLiteBackend needs initialize() — call it synchronously via sqlite3
                import sqlite3
                conn = sqlite3.connect(self._memory_config["path"])
                conn.execute("""CREATE TABLE IF NOT EXISTS memory_records (
                    record_id TEXT PRIMARY KEY, layer TEXT NOT NULL, content TEXT NOT NULL,
                    metadata TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    ttl_seconds INTEGER, provenance TEXT, confidence REAL DEFAULT 1.0, embedding BLOB)""")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_layer ON memory_records(layer)")
                conn.commit()
                conn.close()
                # Reopen via backend
                sqlite_backend._conn = sqlite3.connect(self._memory_config["path"])
                backend = sqlite_backend
            else:
                raise ValueError(f"Unknown memory backend: {backend_type}")
            embedder = None
            try:
                from mori.memory.embedder import AnthropicEmbedder
                embedder = AnthropicEmbedder()
            except ImportError:
                pass
            memory_module = MemoryModule(backend=backend, config=MemoryConfig(),
                embedder=embedder, model=self._model_adapter)

        # 5. Skills module
        skills_module = None
        if self._skill_registry_path:
            from mori.skills.registry import FilesystemRegistry
            from mori.skills.module import SkillsModule
            reg = FilesystemRegistry(self._skill_registry_path)
            skills_module = SkillsModule(registry=reg)

        # 6. Budget manager
        budget_manager = None
        if self._budget_config:
            from mori.budget.manager import BudgetManager
            from mori.budget.types import BudgetConfig
            budget_manager = BudgetManager(BudgetConfig(**self._budget_config))

        # 7. Permission engine — only created when a policy file is provided
        # (.identity() alone is not enough; without rules, default_decision=DENY blocks everything)
        permission_engine = None
        if self._policy_file:
            from mori.permission.engine import PermissionEngine
            permission_engine = PermissionEngine.from_yaml(self._policy_file)

        # 8. Checkpointer
        from mori.control.checkpoint import (
            FileCheckpoints, InMemoryCheckpoints, SQLiteCheckpoints,
        )
        checkpointer: InMemoryCheckpoints | FileCheckpoints | SQLiteCheckpoints | None = None
        if self._checkpointer_config:
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

        # 10. Agent loop
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


class Mori:
    """Top-level Mori agent."""

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
        self._loop = loop
        self._tools = tools
        self._obs = observability
        self._mcp_configs = mcp_configs or []
        self._mcp_connected = False
        self._memory = memory
        self._skills = skills
        self._budget = budget
        self._identity = identity
        self._permission = permission
        self._checkpointer = checkpointer
        self._hooks = hooks

    @staticmethod
    def builder() -> MoriBuilder:
        return MoriBuilder()

    async def run(
        self,
        task: str,
        thread_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> RunResult:
        # Lazy MCP connection
        if self._mcp_configs and not self._mcp_connected:
            for cfg in self._mcp_configs:
                await self._tools.register_mcp_server(**cfg)
            self._mcp_connected = True

        tid = ThreadId(thread_id) if thread_id else None
        return await self._loop.run(task, thread_id=tid, context=context)

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    @property
    def memory(self) -> Any:
        return self._memory

    @property
    def skills(self) -> Any:
        return self._skills

    @property
    def budget(self) -> Any:
        return self._budget

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

    async def resume(
        self,
        thread_id: str,
        input: dict[str, Any] | None = None,
    ) -> RunResult:
        return await self._loop.resume(ThreadId(thread_id), input or {})

    async def close(self) -> None:
        if self._memory:
            await self._memory.close()
        if self._obs:
            await self._obs.close()
