from __future__ import annotations

"""Tests for agent/brain.py — the core agent loop."""

import json
from unittest.mock import AsyncMock

from agent.brain import AgentBrain
from agent.models import LLMResponse, ToolCall
from agent.tools.base import Tool, ToolParameter, ToolResult
from agent.tools.registry import ToolRegistry


class EchoTool(Tool):
    """A test tool that echoes its input."""

    @property
    def name(self):
        return "echo"

    @property
    def description(self):
        return "Echoes input"

    @property
    def parameters(self):
        return [ToolParameter("text", "string", "Text to echo")]

    async def execute(self, text="", **kwargs):
        return ToolResult(success=True, data={"echo": text})


async def test_simple_text_response(mock_llm):
    """LLM returns text → brain returns it directly."""
    mock_llm.generate.return_value = LLMResponse(text="Hello!")

    brain = AgentBrain(llm_provider=mock_llm)
    result = await brain.process("Hi")

    assert result == "Hello!"
    mock_llm.generate.assert_called_once()


async def test_tool_call_then_text(mock_llm):
    """LLM returns a tool call, then text on the second round."""
    # First call: LLM wants to use the echo tool
    tool_call = ToolCall(id="call_1", name="echo", arguments={"text": "hello"})
    first_response = LLMResponse(text="", tool_calls=[tool_call])

    # Second call: LLM returns final text
    second_response = LLMResponse(text="The echo said: hello")

    mock_llm.generate.side_effect = [first_response, second_response]

    registry = ToolRegistry()
    registry.register(EchoTool())

    brain = AgentBrain(llm_provider=mock_llm, tools=registry)
    result = await brain.process("Echo hello")

    assert result == "The echo said: hello"
    assert mock_llm.generate.call_count == 2


async def test_tool_not_found(mock_llm):
    """LLM calls a tool that doesn't exist → error fed back, brain completes."""
    # First call: LLM calls a nonexistent tool
    tool_call = ToolCall(id="call_1", name="nonexistent", arguments={})
    first_response = LLMResponse(text="", tool_calls=[tool_call])

    # Second call: LLM responds with text after seeing the error
    second_response = LLMResponse(text="Sorry, that tool is not available.")

    mock_llm.generate.side_effect = [first_response, second_response]

    registry = ToolRegistry()
    brain = AgentBrain(llm_provider=mock_llm, tools=registry)
    result = await brain.process("Use nonexistent tool")

    assert "not available" in result.lower() or "not found" in result.lower() or result == "Sorry, that tool is not available."


async def test_max_rounds_safety(mock_llm):
    """LLM always returns tool calls → safety message after MAX_TOOL_ROUNDS."""
    tool_call = ToolCall(id="call_1", name="echo", arguments={"text": "loop"})
    mock_llm.generate.return_value = LLMResponse(text="", tool_calls=[tool_call])

    registry = ToolRegistry()
    registry.register(EchoTool())

    brain = AgentBrain(llm_provider=mock_llm, tools=registry)
    result = await brain.process("Loop forever")

    # Should hit the safety limit and return the fallback message
    assert "working on this for a while" in result.lower()
    assert mock_llm.generate.call_count == 10  # MAX_TOOL_ROUNDS


def test_build_system_prompt_with_preferences():
    """System prompt includes user preferences when provided."""
    brain = AgentBrain(llm_provider=AsyncMock())
    prompt = brain._build_system_prompt({"name": "Alice", "timezone": "EST"})

    assert "Alice" in prompt
    assert "timezone" in prompt.lower() or "EST" in prompt
