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
from agent.tools.email_tool import EmailTool
from agent.tools.browser_tool import BrowserTool
from agent.tools.calendar_tool import CalendarTool
from agent.tools.profile_tool import ProfileTool
from agent.profile.store import ProfileStore


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

    # Register email tool only if credentials are configured
    if config.email_username and config.email_password:
        tools.register(EmailTool(
            username=config.email_username,
            password=config.email_password,
            imap_host=config.imap_host,
            imap_port=config.imap_port,
            smtp_host=config.smtp_host,
            smtp_port=config.smtp_port,
        ))

    # Register the browser tool (lazy — only starts Chromium when first used)
    browser = BrowserTool()
    tools.register(browser)

    # Register calendar tool only if OAuth token exists (run setup script first)
    credentials_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), config.google_credentials_path)
    token_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), config.google_token_path)
    if os.path.exists(token_path):
        tools.register(CalendarTool(
            credentials_path=credentials_path,
            token_path=token_path,
        ))

    # Register profile tool (always available — stores data in the same DB)
    profile_store = ProfileStore(db_path=db_path)
    tools.register(ProfileTool(
        profile_store=profile_store,
        browser_tool=browser,
        llm_provider=llm,
    ))

    # Create the agent brain with memory and tools
    brain = AgentBrain(llm_provider=llm, memory=memory, tools=tools)

    # Give this session a unique ID so messages are grouped together
    brain.session_id = MemoryStore.new_session_id()

    # Start the CLI (and clean up browser on exit)
    try:
        asyncio.run(run_cli(brain))
    finally:
        # Shut down the headless browser if it was started
        asyncio.run(browser.cleanup())


# This allows running with: python -m agent.frontends.cli
if __name__ == "__main__":
    main()
