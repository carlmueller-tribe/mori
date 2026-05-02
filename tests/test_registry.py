"""Tests for ToolRegistry — native Python tools only."""

import pytest

from mori.tools.registry import ToolRegistry
from mori.types import ToolInvocationError, ToolSource


def test_register_sync_function():
    registry = ToolRegistry()

    def add(a: int, b: int) -> int:
        return a + b

    tool_id = registry.register("add", add, description="Add two numbers")
    assert tool_id == "native:add"

    specs = registry.list_specs()
    assert len(specs) == 1
    assert specs[0].name == "add"
    assert specs[0].source == ToolSource.NATIVE
    assert specs[0].description == "Add two numbers"


def test_register_async_function():
    registry = ToolRegistry()

    async def fetch(url: str) -> str:
        return f"fetched {url}"

    tool_id = registry.register("fetch", fetch, description="Fetch URL")
    assert tool_id == "native:fetch"


def test_register_with_decorator():
    registry = ToolRegistry()

    @registry.tool(description="Multiply two numbers")
    def multiply(a: int, b: int) -> int:
        return a * b

    specs = registry.list_specs()
    assert len(specs) == 1
    assert specs[0].name == "multiply"


def test_register_decorator_with_custom_name():
    registry = ToolRegistry()

    @registry.tool(description="Multiply", name="mul")
    def multiply(a: int, b: int) -> int:
        return a * b

    specs = registry.list_specs()
    assert specs[0].name == "mul"


async def test_invoke_sync_tool():
    registry = ToolRegistry()

    def add(a: int, b: int) -> int:
        return a + b

    registry.register("add", add, description="Add two numbers")
    result = await registry.invoke("add", {"a": 3, "b": 5})
    assert result.success is True
    assert result.content == "8"
    assert result.tool_name == "add"
    assert result.latency_ms > 0


async def test_invoke_async_tool():
    registry = ToolRegistry()

    async def greet(name: str) -> str:
        return f"hello {name}"

    registry.register("greet", greet, description="Greet")
    result = await registry.invoke("greet", {"name": "world"})
    assert result.success is True
    assert result.content == "hello world"


async def test_invoke_tool_that_raises():
    registry = ToolRegistry()

    def fail(x: int) -> int:
        raise ValueError("bad input")

    registry.register("fail", fail, description="Always fails")
    result = await registry.invoke("fail", {"x": 1})
    assert result.success is False
    assert "bad input" in (result.error or "")


async def test_invoke_unknown_tool():
    registry = ToolRegistry()
    with pytest.raises(ToolInvocationError, match="not found"):
        await registry.invoke("nonexistent", {})


def test_list_specs_empty():
    registry = ToolRegistry()
    assert registry.list_specs() == []


def test_get_spec():
    registry = ToolRegistry()

    def add(a: int, b: int) -> int:
        return a + b

    registry.register("add", add, description="Add")
    spec = registry.get_spec("add")
    assert spec is not None
    assert spec.name == "add"


def test_get_spec_missing():
    registry = ToolRegistry()
    assert registry.get_spec("nope") is None


def test_schema_inferred_on_register():
    registry = ToolRegistry()

    def divide(numerator: float, denominator: float) -> float:
        return numerator / denominator

    registry.register("divide", divide, description="Divide")
    spec = registry.get_spec("divide")
    assert spec is not None
    assert spec.input_schema["properties"]["numerator"]["type"] == "number"
    assert set(spec.input_schema["required"]) == {"numerator", "denominator"}


def test_explicit_schema_overrides_inference():
    registry = ToolRegistry()

    def search(q: str) -> str:
        return q

    custom_schema = {
        "type": "object",
        "properties": {"q": {"type": "string", "description": "Search query"}},
        "required": ["q"],
    }
    registry.register("search", search, description="Search", input_schema=custom_schema)
    spec = registry.get_spec("search")
    assert spec is not None
    assert spec.input_schema["properties"]["q"]["description"] == "Search query"


async def test_invoke_tool_returning_dict():
    registry = ToolRegistry()

    def info() -> dict:
        return {"status": "ok", "count": 42}

    registry.register("info", info, description="Get info")
    result = await registry.invoke("info", {})
    assert result.success is True
    assert "ok" in result.content
