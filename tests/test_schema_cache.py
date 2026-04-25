"""Tests for MCP schema cache with TTL."""
import time
from mori.protocols.mcp.schema_cache import SchemaCache
from mori.types import ToolId, ToolSource, ToolSpec

def _make_spec(name: str) -> ToolSpec:
    return ToolSpec(tool_id=ToolId(f"mcp:{name}"), name=name, description=f"Tool {name}", input_schema={"type": "object"}, source=ToolSource.MCP)

def test_put_and_get():
    cache = SchemaCache(ttl_sec=300)
    specs = [_make_spec("search"), _make_spec("read")]
    cache.put("github", specs)
    result = cache.get("github")
    assert result is not None and len(result) == 2

def test_get_missing():
    assert SchemaCache().get("nonexistent") is None

def test_is_stale_fresh():
    cache = SchemaCache(ttl_sec=300)
    cache.put("server", [_make_spec("tool")])
    assert cache.is_stale("server") is False

def test_is_stale_expired():
    cache = SchemaCache(ttl_sec=0.001)
    cache.put("server", [_make_spec("tool")])
    time.sleep(0.01)
    assert cache.is_stale("server") is True

def test_is_stale_missing():
    assert SchemaCache().is_stale("nonexistent") is True

def test_invalidate():
    cache = SchemaCache()
    cache.put("server", [_make_spec("tool")])
    cache.invalidate("server")
    assert cache.get("server") is None

def test_invalidate_missing():
    SchemaCache().invalidate("nonexistent")  # Should not raise
