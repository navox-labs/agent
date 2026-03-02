from __future__ import annotations

"""
Shared data models used across the agent.

Dataclasses are Python's way of creating simple classes that hold data.
Think of them as typed dictionaries with named fields.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    """A single message in a conversation."""
    role: str       # "user", "assistant", or "system"
    content: str    # The actual text


@dataclass
class ToolCall:
    """Represents the LLM asking to use a tool."""
    id: str             # Unique ID for this tool call
    name: str           # Which tool to call (e.g., "get_current_time")
    arguments: dict     # The arguments to pass (e.g., {"timezone": "Asia/Tokyo"})


@dataclass
class LLMResponse:
    """
    Normalized response from any LLM provider.

    This is key: Claude and OpenAI return responses in different formats,
    but we normalize them into this single shape so the brain doesn't
    care which LLM it's talking to.
    """
    text: str                                   # The text reply (if any)
    tool_calls: list[ToolCall] = field(default_factory=list)  # Tool calls (if any)
    raw_response: Any = None                    # Original API response for debugging

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class ToolResult:
    """Result from executing a tool."""
    success: bool
    data: Any
    error: str | None = None
