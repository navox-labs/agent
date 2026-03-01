"""
Tool Registry — manages all available tools.

The registry is like a phonebook for tools:
- Tools register themselves on startup
- The brain asks the registry for tool schemas (to tell the LLM what's available)
- When the LLM wants to call a tool, the brain looks it up in the registry

This keeps the brain decoupled from individual tools — it doesn't
need to know about EmailTool or BrowserTool directly.
"""

import logging
from agent.tools.base import Tool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Central registry for all agent tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        """
        Register a tool so the agent can use it.

        Called during startup to add tools to the agent's capabilities.
        """
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name} — {tool.description}")

    def get(self, name: str) -> Tool | None:
        """Look up a tool by name. Returns None if not found."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_llm_schemas(self) -> list[dict]:
        """
        Get all tool definitions formatted for the LLM API.

        This is what gets passed to the LLM so it knows what tools
        are available and how to call them.
        """
        return [tool.to_llm_schema() for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
