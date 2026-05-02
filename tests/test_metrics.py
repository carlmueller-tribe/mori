"""Tests for per-tool metrics and result truncation in ToolRegistry."""

from mori.tools.registry import ToolRegistry


def test_metrics_initial_state():
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    metrics = registry.get_metrics("native:add")
    assert metrics is not None
    assert metrics.total_calls == 0
    assert metrics.total_errors == 0
    assert metrics.error_rate == 0.0


async def test_metrics_increment_on_success():
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    await registry.invoke("add", {"a": 1, "b": 2})
    metrics = registry.get_metrics("native:add")
    assert metrics.total_calls == 1
    assert metrics.total_errors == 0
    assert metrics.avg_latency_ms > 0
    assert metrics.last_called is not None


async def test_metrics_increment_on_failure():
    registry = ToolRegistry()

    def fail():
        raise ValueError("boom")

    registry.register("fail", fail, description="Fails")
    await registry.invoke("fail", {})
    metrics = registry.get_metrics("native:fail")
    assert metrics.total_calls == 1
    assert metrics.total_errors == 1
    assert metrics.error_rate == 1.0
    assert metrics.last_error == "boom"


async def test_metrics_multiple_calls():
    registry = ToolRegistry()
    registry.register("add", lambda a, b: a + b, description="Add")
    for _ in range(5):
        await registry.invoke("add", {"a": 1, "b": 2})
    metrics = registry.get_metrics("native:add")
    assert metrics.total_calls == 5
    assert metrics.total_errors == 0


def test_get_metrics_unknown_tool():
    registry = ToolRegistry()
    assert registry.get_metrics("native:nonexistent") is None


async def test_result_truncation():
    registry = ToolRegistry(max_result_tokens=10)

    def verbose() -> str:
        return "x" * 200

    registry.register("verbose", verbose, description="Verbose")
    result = await registry.invoke("verbose", {})
    assert result.success is True
    assert "[TRUNCATED" in result.content
    assert len(result.content) < 200


async def test_no_truncation_under_limit():
    registry = ToolRegistry(max_result_tokens=4000)
    registry.register("short", lambda: "hello", description="Short")
    result = await registry.invoke("short", {})
    assert "[TRUNCATED" not in result.content
