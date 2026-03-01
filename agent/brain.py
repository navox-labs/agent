"""
The Agent Brain — the core loop that makes this an autonomous agent.

This is the most important file in the entire project. The brain:
1. Receives a message (from CLI, Discord, Telegram, or WhatsApp)
2. Builds context (system prompt + conversation history)
3. Sends everything to the LLM
4. If the LLM returns tool calls → executes them → feeds results back → loops
5. If the LLM returns a text reply → returns it to the user

The loop at steps 3-4 is what makes this an AGENT, not just a chatbot.
A chatbot does one request-response. An agent loops until the task is done,
chaining multiple tool calls autonomously.

Example: "Check my email and schedule meetings for any urgent items"
  → Brain calls email tool → gets emails
  → Brain feeds emails back to LLM → LLM decides to call calendar tool
  → Brain calls calendar tool → creates meetings
  → Brain feeds results back to LLM → LLM composes final summary
  → Brain returns summary to user
"""

import json
import logging
from agent.llm.base import LLMProvider
from agent.models import LLMResponse

logger = logging.getLogger(__name__)

# Maximum number of tool-call loops to prevent infinite loops
MAX_TOOL_ROUNDS = 10

SYSTEM_PROMPT = """You are a helpful personal AI assistant. You help the user \
manage their daily tasks including emails, web browsing, and calendar scheduling.

You are friendly, concise, and proactive. When the user asks you to do something, \
you take action using your available tools rather than just explaining how to do it.

If you don't have the tools or information needed, say so honestly."""


class AgentBrain:
    """
    The core agent that processes messages and orchestrates tool calls.

    This class ties together:
    - An LLM provider (OpenAI, Claude, etc.)
    - A memory store (added in Phase 2)
    - A tool registry (added in Phase 3)
    """

    def __init__(self, llm_provider: LLMProvider, memory=None, tools=None):
        self.llm = llm_provider
        self.memory = memory        # Will be added in Phase 2
        self.tools = tools          # Will be added in Phase 3
        self.conversation: list[dict] = []  # In-memory conversation for now

    async def process(self, user_message: str, context: dict | None = None) -> str:
        """
        Process a user message and return the agent's response.

        This is the main entry point. Every frontend (CLI, Discord, etc.)
        calls this method with the user's message.

        Args:
            user_message: What the user said
            context: Optional metadata (which frontend, user ID, etc.)

        Returns:
            The agent's text response
        """
        # Step 1: Add the user's message to conversation history
        self.conversation.append({"role": "user", "content": user_message})

        # Step 2: Get tool definitions (if we have tools registered)
        tool_definitions = None
        if self.tools:
            tool_definitions = self.tools.get_llm_schemas()

        # Step 3-4: The agent loop — keep calling the LLM until we get a text reply
        rounds = 0
        while rounds < MAX_TOOL_ROUNDS:
            rounds += 1

            # Call the LLM
            response: LLMResponse = await self.llm.generate(
                system=SYSTEM_PROMPT,
                messages=self.conversation,
                tools=tool_definitions,
            )

            # If the LLM wants to use tools, execute them and loop back
            if response.has_tool_calls:
                # Add the assistant's tool-calling message to history
                # (OpenAI needs this to maintain the conversation flow)
                self.conversation.append(
                    self._build_assistant_tool_call_message(response)
                )

                # Execute each tool and add results to history
                for tool_call in response.tool_calls:
                    result = await self._execute_tool(tool_call)
                    self.conversation.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    })

                # Loop back to step 3 — the LLM will see the tool results
                continue

            # If the LLM gave a text reply, we're done
            else:
                self.conversation.append({
                    "role": "assistant",
                    "content": response.text,
                })
                return response.text

        # Safety: if we hit the max rounds, return what we have
        return "I've been working on this for a while. Let me summarize what I found so far."

    async def _execute_tool(self, tool_call) -> dict:
        """
        Execute a tool call and return the result.

        In Phase 1, we don't have tools yet, so this is a placeholder.
        Phase 3 will add the real tool registry and execution.
        """
        logger.info(f"Tool call requested: {tool_call.name}({tool_call.arguments})")

        if self.tools:
            tool = self.tools.get(tool_call.name)
            if tool:
                try:
                    result = await tool.execute(**tool_call.arguments)
                    return {"success": result.success, "data": result.data, "error": result.error}
                except Exception as e:
                    return {"success": False, "data": None, "error": str(e)}

        return {"success": False, "data": None, "error": f"Tool '{tool_call.name}' not found"}

    def _build_assistant_tool_call_message(self, response: LLMResponse) -> dict:
        """
        Build the assistant message that contains tool calls.

        OpenAI requires the assistant's tool-calling message to be in the
        conversation history before the tool results.
        """
        return {
            "role": "assistant",
            "content": response.text or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in response.tool_calls
            ],
        }
