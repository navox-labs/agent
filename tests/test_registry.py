from __future__ import annotations

"""Tests for agent/tools/registry.py — the tool registry."""

from agent.tools.base import Tool, ToolParameter, ToolResult
from agent.tools.registry import ToolRegistry


class FakeTool(Tool):
    """A minimal tool for registry tests."""

    def __init__(self, tool_name: str):
        self._name = tool_name

    @property
    def name(self):
        return self._name

    @property
    def description(self):
        return f"Fake tool: {self._name}"

    @property
    def parameters(self):
        return []

    async def execute(self, **kwargs):
        return ToolResult(success=True, data="ok")


def test_register_and_get(tool_registry):
    tool = FakeTool("test_tool")
    tool_registry.register(tool)
    assert tool_registry.get("test_tool") is tool


def test_get_nonexistent_returns_none(tool_registry):
    assert tool_registry.get("nonexistent") is None


def test_list_tools(tool_registry):
    tool_registry.register(FakeTool("a"))
    tool_registry.register(FakeTool("b"))
    tools = tool_registry.list_tools()
    assert len(tools) == 2


def test_len_and_contains(tool_registry):
    tool_registry.register(FakeTool("alpha"))
    assert len(tool_registry) == 1
    assert "alpha" in tool_registry
    assert "beta" not in tool_registry


def test_get_llm_schemas(tool_registry):
    tool_registry.register(FakeTool("x"))
    tool_registry.register(FakeTool("y"))
    schemas = tool_registry.get_llm_schemas()
    assert len(schemas) == 2
    assert all("name" in s for s in schemas)
