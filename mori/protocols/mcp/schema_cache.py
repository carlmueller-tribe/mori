"""Schema cache with TTL for MCP tool discovery."""
from __future__ import annotations
import time
from mori.types import ToolSpec


class SchemaCache:
    def __init__(self, ttl_sec: float = 300.0) -> None:
        self._ttl_sec = ttl_sec
        self._cache: dict[str, tuple[float, list[ToolSpec]]] = {}

    def get(self, server_name: str) -> list[ToolSpec] | None:
        entry = self._cache.get(server_name)
        return entry[1] if entry else None

    def put(self, server_name: str, specs: list[ToolSpec]) -> None:
        self._cache[server_name] = (time.monotonic(), specs)

    def is_stale(self, server_name: str) -> bool:
        entry = self._cache.get(server_name)
        if entry is None:
            return True
        return (time.monotonic() - entry[0]) >= self._ttl_sec

    def invalidate(self, server_name: str) -> None:
        self._cache.pop(server_name, None)
