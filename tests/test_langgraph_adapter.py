from __future__ import annotations

import pytest


def test_langgraph_adapter_import():
    from mori.adapters.frameworks.langgraph_adapter import LangGraphAdapter

    assert LangGraphAdapter is not None


def test_langgraph_as_tool_import():
    from mori.adapters.frameworks.langgraph_adapter import langgraph_as_tool

    assert langgraph_as_tool is not None


def test_langgraph_as_skill_import():
    from mori.adapters.frameworks.langgraph_adapter import langgraph_as_skill

    assert langgraph_as_skill is not None


def test_langgraph_adapter_satisfies_runtime_adapter_protocol():
    from mori.adapters.frameworks.langgraph_adapter import LangGraphAdapter
    from mori.runtime.adapter import RuntimeAdapter

    try:
        adapter = LangGraphAdapter()
    except ImportError:
        pytest.skip("langgraph not installed")
    assert isinstance(adapter, RuntimeAdapter)
