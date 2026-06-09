"""v0.6 exit test — adapter pattern enforced at every external boundary."""

from __future__ import annotations

import pytest

from mori.memory.embedder import Embedder
from mori.observability.sinks.base import Sink
from mori.observability.sinks.jsonl import JsonlSink
from mori.observability.sinks.stdout import StdoutSink
from mori.runtime.adapter import RuntimeAdapter


def test_sink_protocol_exported():
    assert Sink is not None


def test_stdout_and_jsonl_satisfy_sink(tmp_path):
    assert isinstance(StdoutSink(), Sink)
    assert isinstance(JsonlSink(path=str(tmp_path / "test.jsonl")), Sink)


def test_runtime_adapter_protocol_exported():
    assert RuntimeAdapter is not None


def test_embedder_protocol_exported():
    assert Embedder is not None


def test_all_adapter_subpackages_importable():
    """All adapter subpackages are importable (without optional deps installed)."""
    import importlib

    for module in [
        "mori.adapters",
        "mori.adapters.embeddings",
        "mori.adapters.frameworks",
        "mori.adapters.sinks",
    ]:
        importlib.import_module(module)


def test_voyageai_embedder_module_importable():
    """VoyageAIEmbedder module importable; ImportError fires only at instantiation."""
    import importlib

    mod = importlib.import_module("mori.adapters.embeddings.voyageai_embedder")
    assert hasattr(mod, "VoyageAIEmbedder")


def test_anthropic_embedder_deprecated():
    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from mori.memory.embedder import AnthropicEmbedder  # noqa: F401

        assert any("deprecated" in str(warning.message).lower() for warning in w)


def test_core_modules_do_not_import_from_adapters():
    """Core modules must not contain static imports from mori.adapters."""
    import ast
    import pathlib

    core_dirs = [
        "mori/runtime",
        "mori/memory",
        "mori/observability",
        "mori/budget",
        "mori/permission",
        "mori/control",
        "mori/skills",
        "mori/hooks",
    ]
    violations: list[str] = []
    for dir_path in core_dirs:
        for py_file in pathlib.Path(dir_path).rglob("*.py"):
            source = py_file.read_text()
            if "mori.adapters" not in source:
                continue
            tree = ast.parse(source)
            # Only check module-level imports (direct children of Module node).
            # Imports inside __getattr__ or other functions are intentional lazy
            # re-exports and do not constitute a boundary violation.
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.Import | ast.ImportFrom):
                    node_str = ast.unparse(node)
                    if "mori.adapters" in node_str:
                        violations.append(f"{py_file}:{node.lineno}: {node_str}")
    assert violations == [], "Core modules import from mori.adapters:\n" + "\n".join(violations)


@pytest.mark.asyncio
async def test_builder_with_runtime_adapter_delegates():
    """AgentLoop delegates to RuntimeAdapter when provided via builder."""
    from unittest.mock import MagicMock

    from mori.agent import MoriBuilder
    from mori.runtime.result import RunResult
    from mori.types import RunStatus, TokenUsage

    class EchoAdapter:
        async def run(self, task, state, tools, memory, skills):
            return RunResult(
                run_id=state.run_id,
                thread_id=state.thread_id,
                status=RunStatus.COMPLETED,
                task=task,
                final_output=f"echo: {task}",
                total_steps=1,
                total_usage=TokenUsage(input_tokens=0, output_tokens=0),
                total_tool_calls=0,
                total_duration_ms=1.0,
            )

        async def stream(self, task, state, tools, **kwargs):
            return
            yield

    builder = MoriBuilder()
    builder._model_adapter = MagicMock()
    builder._runtime_adapter = EchoAdapter()
    builder._disabled_native_tools = {"ask_user"}
    agent = builder.build()
    result = await agent.run("hello from adapter")
    assert result.final_output == "echo: hello from adapter"
    assert result.status == RunStatus.COMPLETED
