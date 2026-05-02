"""Tests for schema inference from Python type annotations."""

from pydantic import BaseModel

from mori.tools.schema import infer_schema


def test_infer_from_simple_types():
    def add(a: int, b: int) -> int:
        return a + b

    schema = infer_schema(add)
    assert schema["type"] == "object"
    assert schema["properties"]["a"]["type"] == "integer"
    assert schema["properties"]["b"]["type"] == "integer"
    assert set(schema["required"]) == {"a", "b"}


def test_infer_string_param():
    def greet(name: str) -> str:
        return f"hello {name}"

    schema = infer_schema(greet)
    assert schema["properties"]["name"]["type"] == "string"


def test_infer_float_param():
    def scale(factor: float) -> float:
        return factor * 2

    schema = infer_schema(scale)
    assert schema["properties"]["factor"]["type"] == "number"


def test_infer_bool_param():
    def toggle(flag: bool) -> bool:
        return not flag

    schema = infer_schema(toggle)
    assert schema["properties"]["flag"]["type"] == "boolean"


def test_infer_optional_param():
    def search(query: str, limit: int = 10) -> str:
        return query

    schema = infer_schema(search)
    assert "query" in schema["required"]
    assert "limit" not in schema["required"]
    assert schema["properties"]["limit"]["type"] == "integer"


def test_infer_unannotated_defaults_to_string():
    def raw(data) -> str:  # type: ignore[no-untyped-def]
        return str(data)

    schema = infer_schema(raw)
    assert schema["properties"]["data"]["type"] == "string"


def test_infer_pydantic_model_param():
    class SearchInput(BaseModel):
        query: str
        max_results: int = 5

    def search(params: SearchInput) -> str:
        return params.query

    schema = infer_schema(search)
    props = schema["properties"]["params"]
    assert props["type"] == "object"
    assert "query" in props["properties"]
    assert "max_results" in props["properties"]


async def test_infer_from_async_function():
    async def fetch(url: str, timeout: float = 30.0) -> str:
        return ""

    schema = infer_schema(fetch)
    assert schema["properties"]["url"]["type"] == "string"
    assert schema["properties"]["timeout"]["type"] == "number"
    assert "url" in schema["required"]
    assert "timeout" not in schema["required"]


def test_infer_list_param():
    def process(items: list[str]) -> int:
        return len(items)

    schema = infer_schema(process)
    assert schema["properties"]["items"]["type"] == "array"
    assert schema["properties"]["items"]["items"]["type"] == "string"


def test_infer_skips_return_type():
    def add(a: int, b: int) -> int:
        return a + b

    schema = infer_schema(add)
    assert "return" not in schema.get("properties", {})
