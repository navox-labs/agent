"""
CLI Frontend — a terminal-based chat interface.

This is the simplest frontend: a REPL (Read-Eval-Print Loop).
1. Read user input from the terminal
2. Send it to the agent brain
3. Print the response
4. Repeat

This is what you'll use to test the agent during development.
Later, Discord/Telegram/WhatsApp become additional frontends
that all talk to the same brain.
"""

import asyncio
import logging
import os
from agent.config import Config
from agent.brain import AgentBrain
from agent.llm.openai_provider import OpenAIProvider
from agent.memory.store import MemoryStore
from agent.tools.registry import ToolRegistry
from agent.tools.example_tools import CurrentTimeTool, CalculatorTool


async def run_cli(brain: AgentBrain):
    """Run the interactive CLI chat loop."""
    print("=" * 60)
    print("  Personal AI Agent — CLI Mode")
    print("  Type your message and press Enter.")
    print("  Type 'quit' or 'exit' to stop.")
    print("=" * 60)
    print()

    while True:
        try:
            # Read user input
            user_input = input("You: ").strip()

            # Check for exit commands
            if user_input.lower() in ("quit", "exit", "q"):
                print("\nGoodbye!")
                break

            # Skip empty input
            if not user_input:
                continue

            # Process through the agent brain
            print("\nAgent: ", end="", flush=True)
            response = await brain.process(
                user_message=user_input,
                context={"frontend": "cli"},
            )
            print(response)
            print()

        except (KeyboardInterrupt, EOFError):
            print("\n\nGoodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}\n")


def main():
    """
    Entry point: wire everything together and start the CLI.

    This is the "dependency injection" pattern:
    1. Load config (API keys from .env)
    2. Create the LLM provider
    3. Create the brain with the provider
    4. Start the CLI with the brain

    Each component only knows about its dependencies, not how they're created.
    """
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Load configuration
    config = Config()
    config.validate()

    # Create the LLM provider
    llm = OpenAIProvider(api_key=config.openai_api_key)

    # Create persistent memory (ensures data/ directory exists)
    db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "agent_memory.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    memory = MemoryStore(db_path=db_path)

    # Create and register tools
    tools = ToolRegistry()
    tools.register(CurrentTimeTool())
    tools.register(CalculatorTool())

    # Create the agent brain with memory and tools
    brain = AgentBrain(llm_provider=llm, memory=memory, tools=tools)

    # Give this session a unique ID so messages are grouped together
    brain.session_id = MemoryStore.new_session_id()

    # Start the CLI
    asyncio.run(run_cli(brain))


# This allows running with: python -m agent.frontends.cli
if __name__ == "__main__":
    main()
