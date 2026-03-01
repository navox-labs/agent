"""
Abstract LLM provider interface.

This defines the contract that ALL LLM providers must follow.
By coding to this interface (not to a specific API), the rest of
the agent doesn't care whether it's talking to OpenAI, Claude,
or any other LLM.

This is the Strategy Pattern: define an interface, then swap
implementations without changing the code that uses them.
"""

from abc import ABC, abstractmethod
from agent.models import LLMResponse


class LLMProvider(ABC):
    """Base class for all LLM providers."""

    @abstractmethod
    async def generate(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """
        Send messages to the LLM and get a response.

        Args:
            system: The system prompt (instructions for the LLM)
            messages: Conversation history as list of {"role": ..., "content": ...}
            tools: Optional tool definitions the LLM can call

        Returns:
            LLMResponse with either text or tool_calls
        """
        pass
