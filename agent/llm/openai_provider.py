"""
OpenAI LLM provider.

This implements the LLMProvider interface for OpenAI's API.
It translates between our generic format and OpenAI's specific
request/response format.

Key concepts:
- AsyncOpenAI: async client so we don't block while waiting for API responses
- Messages format: OpenAI uses [{"role": "system/user/assistant", "content": "..."}]
- Tool calling: OpenAI returns tool_calls in the response when it wants to use a tool
"""

import json
from openai import AsyncOpenAI
from agent.llm.base import LLMProvider
from agent.models import LLMResponse, ToolCall


class OpenAIProvider(LLMProvider):
    """OpenAI API implementation (GPT-4o, GPT-4, etc.)."""

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def generate(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """
        Call OpenAI's Chat Completions API.

        The flow:
        1. Prepend the system message to the conversation
        2. Convert our tool format to OpenAI's function format
        3. Make the API call
        4. Parse the response into our normalized LLMResponse
        """
        # OpenAI puts the system prompt as the first message
        openai_messages = [{"role": "system", "content": system}] + messages

        # Build the API call arguments
        kwargs = {
            "model": self.model,
            "messages": openai_messages,
            "max_tokens": 4096,
        }

        # If we have tools, convert them to OpenAI's format
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        # Make the async API call
        response = await self.client.chat.completions.create(**kwargs)

        # Parse OpenAI's response into our normalized format
        return self._parse_response(response)

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """
        Convert our tool definitions to OpenAI's function calling format.

        Our format (matching Claude's):
            {"name": "...", "description": "...", "input_schema": {...}}

        OpenAI's format:
            {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
        """
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool.get("input_schema", {}),
                },
            })
        return openai_tools

    def _parse_response(self, response) -> LLMResponse:
        """
        Parse OpenAI's response into our normalized LLMResponse.

        OpenAI can return:
        1. A text message (response.choices[0].message.content)
        2. Tool calls (response.choices[0].message.tool_calls)
        3. Both at the same time
        """
        choice = response.choices[0]
        message = choice.message

        # Extract text content
        text = message.content or ""

        # Extract tool calls (if any)
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                ))

        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            raw_response=response,
        )
