"""
Abstract Tool interface — the plugin contract.

Every tool in the agent (email, browser, calendar, etc.) implements
this base class. This is the Strategy Pattern:

1. Define an interface (Tool)
2. Each tool implements it differently (EmailTool, BrowserTool, etc.)
3. The brain doesn't care which tool it's running — it just calls execute()

The key method is to_llm_schema() — it converts the tool definition into
the JSON format that LLMs expect for "function calling" / "tool use".
When you tell GPT-4o "you have these tools available", this is the format it needs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolParameter:
    """
    Describes one parameter a tool accepts.

    This maps directly to JSON Schema properties that LLMs understand.
    For example:
        ToolParameter("timezone", "string", "IANA timezone like America/New_York")
    becomes:
        {"type": "string", "description": "IANA timezone like America/New_York"}
    """
    name: str
    type: str           # "string", "integer", "boolean", "number"
    description: str
    required: bool = True
    enum: list | None = None  # Restrict to specific values


@dataclass
class ToolResult:
    """
    The result of executing a tool.

    Every tool returns this, so the brain has a consistent format
    to feed back to the LLM.
    """
    success: bool
    data: Any
    error: str | None = None


class Tool(ABC):
    """
    Base class for all agent tools.

    To create a new tool, subclass this and implement:
    - name: unique identifier (e.g., "email", "browser", "calendar")
    - description: what it does (the LLM reads this to decide when to use it)
    - parameters: what inputs it needs
    - execute(): the actual logic

    Example:
        class MyTool(Tool):
            @property
            def name(self): return "my_tool"

            @property
            def description(self): return "Does something useful"

            @property
            def parameters(self): return [
                ToolParameter("input", "string", "The input to process")
            ]

            async def execute(self, input="") -> ToolResult:
                result = do_something(input)
                return ToolResult(success=True, data=result)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """What this tool does. The LLM reads this to decide when to use it."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> list[ToolParameter]:
        """List of parameters this tool accepts."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Run the tool with the given arguments."""
        ...

    def to_llm_schema(self) -> dict:
        """
        Convert this tool to the JSON schema format LLMs expect.

        This is what gets sent to the API as a "tool definition".
        The LLM reads the name, description, and parameter schemas
        to understand what the tool does and how to call it.

        Output format (matches Claude's tool_use format):
        {
            "name": "get_current_time",
            "description": "Get the current time in a timezone",
            "input_schema": {
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "description": "..."}
                },
                "required": ["timezone"]
            }
        }
        """
        properties = {}
        for p in self.parameters:
            prop = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": [p.name for p in self.parameters if p.required],
            },
        }
