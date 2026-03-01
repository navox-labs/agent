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

BASE_SYSTEM_PROMPT = """You are a helpful personal AI assistant. You help the user \
manage their daily tasks including emails, web browsing, and calendar scheduling.

You are friendly, concise, and proactive. When the user asks you to do something, \
you take action using your available tools rather than just explaining how to do it.

If you don't have the tools or information needed, say so honestly.

If the user tells you their name, preferences, or important facts about themselves, \
remember these for future conversations."""


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
        self.memory = memory        # MemoryStore for persistent memory
        self.tools = tools          # Will be added in Phase 3
        self.conversation: list[dict] = []  # Current session messages
        self.session_id: str | None = None  # Set by frontend

    def _build_system_prompt(self, preferences: dict[str, str]) -> str:
        """
        Build the system prompt, enriched with user preferences.

        This is how the agent "knows" you — your preferences are injected
        into the system prompt so the LLM sees them on every request.
        """
        prompt = BASE_SYSTEM_PROMPT

        if preferences:
            pref_lines = "\n".join(f"- {k}: {v}" for k, v in preferences.items())
            prompt += f"\n\nHere is what you know about the user:\n{pref_lines}"

        return prompt

    async def process(self, user_message: str, context: dict | None = None) -> str:
        """
        Process a user message and return the agent's response.

        This is the main entry point. Every frontend (CLI, Discord, etc.)
        calls this method with the user's message.

        Now with memory:
        1. Load conversation history and preferences from the database
        2. Build an enriched system prompt with user preferences
        3. Run the agent loop (LLM calls + tool calls)
        4. Save the exchange to persistent memory
        """
        frontend = (context or {}).get("frontend", "cli")

        # Step 1: Load memory context (preferences + past conversation summaries)
        system_prompt = BASE_SYSTEM_PROMPT
        if self.memory:
            memory_context = await self.memory.build_context(limit=20)

            # If this is a fresh session, load recent history from the database
            if not self.conversation and memory_context["messages"]:
                self.conversation = memory_context["messages"]

            # Inject summaries into context if available
            if memory_context["summaries"]:
                summary_text = "\n".join(memory_context["summaries"])
                system_prompt = self._build_system_prompt(memory_context["preferences"])
                system_prompt += f"\n\nPrevious conversation summaries:\n{summary_text}"
            else:
                system_prompt = self._build_system_prompt(memory_context["preferences"])

        # Step 2: Add the user's message to conversation history
        self.conversation.append({"role": "user", "content": user_message})

        # Save user message to persistent memory
        if self.memory and self.session_id:
            await self.memory.save_message(
                session_id=self.session_id,
                role="user",
                content=user_message,
                frontend=frontend,
            )

        # Step 3: Get tool definitions (if we have tools registered)
        tool_definitions = None
        if self.tools:
            tool_definitions = self.tools.get_llm_schemas()

        # Step 4: The agent loop — keep calling the LLM until we get a text reply
        rounds = 0
        while rounds < MAX_TOOL_ROUNDS:
            rounds += 1

            # Call the LLM
            response: LLMResponse = await self.llm.generate(
                system=system_prompt,
                messages=self.conversation,
                tools=tool_definitions,
            )

            # If the LLM wants to use tools, execute them and loop back
            if response.has_tool_calls:
                self.conversation.append(
                    self._build_assistant_tool_call_message(response)
                )

                for tool_call in response.tool_calls:
                    result = await self._execute_tool(tool_call)
                    self.conversation.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    })

                continue

            # If the LLM gave a text reply, we're done
            else:
                self.conversation.append({
                    "role": "assistant",
                    "content": response.text,
                })

                # Save assistant response to persistent memory
                if self.memory and self.session_id:
                    await self.memory.save_message(
                        session_id=self.session_id,
                        role="assistant",
                        content=response.text,
                        frontend=frontend,
                    )

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
