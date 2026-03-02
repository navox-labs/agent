from __future__ import annotations

"""Tests for agent/tools/example_tools.py — CurrentTimeTool and CalculatorTool."""

from agent.tools.example_tools import CurrentTimeTool, CalculatorTool


# ── CurrentTimeTool ──────────────────────────────────────────────

async def test_current_time_utc():
    tool = CurrentTimeTool()
    result = await tool.execute(timezone="UTC")
    assert result.success is True
    assert result.data["timezone"] == "UTC"
    assert "datetime" in result.data
    assert "date" in result.data
    assert "time" in result.data


async def test_current_time_specific_timezone():
    tool = CurrentTimeTool()
    result = await tool.execute(timezone="America/New_York")
    assert result.success is True
    assert result.data["timezone"] == "America/New_York"


async def test_current_time_invalid_timezone():
    tool = CurrentTimeTool()
    result = await tool.execute(timezone="Invalid/Zone")
    assert result.success is False
    assert "Invalid timezone" in result.error


# ── CalculatorTool ───────────────────────────────────────────────

async def test_calculator_basic():
    tool = CalculatorTool()
    result = await tool.execute(expression="2 + 2")
    assert result.success is True
    assert result.data["result"] == 4


async def test_calculator_complex():
    tool = CalculatorTool()
    result = await tool.execute(expression="(10 + 5) * 3")
    assert result.success is True
    assert result.data["result"] == 45


async def test_calculator_invalid_characters():
    tool = CalculatorTool()
    result = await tool.execute(expression="import os")
    assert result.success is False
    assert "invalid characters" in result.error
