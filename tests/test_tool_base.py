from __future__ import annotations

"""Tests for agent/tools/base.py — Tool ABC and schema generation."""

from agent.tools.base import Tool, ToolParameter, ToolResult


class DummyTool(Tool):
    """A minimal tool for testing the base class contract."""

    @property
    def name(self):
        return "dummy"

    @property
    def description(self):
        return "A test tool"

    @property
    def parameters(self):
        return [
            ToolParameter("input", "string", "Test input", required=True),
            ToolParameter("count", "integer", "Optional count", required=False),
        ]

    async def execute(self, **kwargs):
        return ToolResult(success=True, data="ok")


def test_tool_parameter_defaults():
    p = ToolParameter("name", "string", "desc")
    assert p.required is True
    assert p.enum is None


def test_tool_result_defaults():
    r = ToolResult(success=True, data="test")
    assert r.error is None


def test_to_llm_schema_structure():
    tool = DummyTool()
    schema = tool.to_llm_schema()

    assert schema["name"] == "dummy"
    assert schema["description"] == "A test tool"
    assert schema["input_schema"]["type"] == "object"

    props = schema["input_schema"]["properties"]
    assert "input" in props
    assert "count" in props
    assert props["input"]["type"] == "string"
    assert props["count"]["type"] == "integer"

    # Only required params in the required list
    assert schema["input_schema"]["required"] == ["input"]


def test_to_llm_schema_with_enum():
    class EnumTool(Tool):
        @property
        def name(self):
            return "enum_tool"

        @property
        def description(self):
            return "Tool with enum"

        @property
        def parameters(self):
            return [
                ToolParameter("action", "string", "The action", enum=["read", "write"]),
            ]

        async def execute(self, **kwargs):
            return ToolResult(success=True, data="ok")

    schema = EnumTool().to_llm_schema()
    assert schema["input_schema"]["properties"]["action"]["enum"] == ["read", "write"]
