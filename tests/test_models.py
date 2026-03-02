from __future__ import annotations

"""Tests for agent/models.py — the core data models."""

from agent.models import Message, ToolCall, LLMResponse


def test_message_creation():
    msg = Message(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"


def test_tool_call_creation():
    tc = ToolCall(id="call_123", name="get_time", arguments={"timezone": "UTC"})
    assert tc.id == "call_123"
    assert tc.name == "get_time"
    assert tc.arguments == {"timezone": "UTC"}


def test_llm_response_has_tool_calls_true():
    tc = ToolCall(id="call_1", name="test", arguments={})
    resp = LLMResponse(text="", tool_calls=[tc])
    assert resp.has_tool_calls is True


def test_llm_response_has_tool_calls_false():
    resp = LLMResponse(text="Hello!")
    assert resp.has_tool_calls is False


def test_llm_response_defaults():
    resp = LLMResponse(text="hi")
    assert resp.tool_calls == []
    assert resp.raw_response is None
