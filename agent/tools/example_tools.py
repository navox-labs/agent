from __future__ import annotations

"""
Example tools to validate the tool-calling pipeline.

These simple tools prove that the full cycle works:
1. LLM sees the tool definition
2. User asks a question that requires the tool
3. LLM decides to call the tool (returns a tool_call)
4. Brain executes the tool
5. Brain feeds the result back to the LLM
6. LLM composes a final answer using the tool result

Once this works, building real tools (email, browser, calendar)
is just a matter of implementing the execute() method differently.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from agent.tools.base import Tool, ToolParameter, ToolResult


class CurrentTimeTool(Tool):
    """Get the current date and time in any timezone."""

    @property
    def name(self) -> str:
        return "get_current_time"

    @property
    def description(self) -> str:
        return "Get the current date and time. Optionally specify a timezone (IANA format like America/New_York, Europe/London, Asia/Tokyo)."

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="timezone",
                type="string",
                description="IANA timezone name (e.g., America/New_York, Europe/London, Asia/Tokyo). Defaults to UTC.",
                required=False,
            ),
        ]

    async def execute(self, timezone: str = "UTC", **kwargs) -> ToolResult:
        try:
            tz = ZoneInfo(timezone)
            now = datetime.now(tz)
            return ToolResult(
                success=True,
                data={
                    "datetime": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
                    "timezone": timezone,
                    "date": now.strftime("%A, %B %d, %Y"),
                    "time": now.strftime("%I:%M %p"),
                },
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=f"Invalid timezone '{timezone}': {e}")


class CalculatorTool(Tool):
    """Perform basic math calculations."""

    @property
    def name(self) -> str:
        return "calculator"

    @property
    def description(self) -> str:
        return "Evaluate a mathematical expression. Supports basic arithmetic (+, -, *, /), powers (**), and common functions."

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="expression",
                type="string",
                description="The math expression to evaluate (e.g., '2 + 2', '15 * 3.5', '2 ** 10')",
                required=True,
            ),
        ]

    async def execute(self, expression: str = "", **kwargs) -> ToolResult:
        try:
            # Guard against expensive expressions like "9**9**9**9**9"
            if len(expression) > 100:
                return ToolResult(success=False, data=None, error="Expression too long (max 100 characters)")

            # Only allow safe math characters
            allowed = set("0123456789+-*/.() ")
            if not all(c in allowed for c in expression):
                return ToolResult(success=False, data=None, error="Expression contains invalid characters")

            result = eval(expression)  # Safe because we validated the characters
            return ToolResult(success=True, data={"expression": expression, "result": result})
        except Exception as e:
            return ToolResult(success=False, data=None, error=f"Could not evaluate '{expression}': {e}")
