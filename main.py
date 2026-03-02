#!/usr/bin/env python3
from __future__ import annotations

"""
Main entry point for the Personal AI Agent.

Four modes of operation:
    python main.py                  # Interactive CLI (default)
    python main.py --mode cli       # Interactive CLI
    python main.py --mode daemon    # Background scheduler only
    python main.py --mode both      # CLI + scheduler in parallel
    python main.py --mode telegram  # Telegram bot (multi-user, public)

The daemon mode runs the agent autonomously — it scans for jobs,
drafts outreach, checks for responses, and notifies you via email.

The 'both' mode gives you the best of both worlds: interactive chat
plus background automation running simultaneously.

The 'telegram' mode runs a public Telegram bot that anyone can use.
Each user gets their own isolated profile, memory, and job pipeline.
"""

import argparse
import asyncio
import logging
import os
import sys

# Ensure the project root is in the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
from agent.tools.job_tool import JobTool
from agent.tools.outreach_tool import OutreachTool
from agent.profile.store import ProfileStore
from agent.jobs.store import JobStore
from agent.jobs.matcher import JobMatcher
from agent.jobs.scanner import JobScanner
from agent.jobs.linkedin_session import LinkedInSession
from agent.jobs.outreach import OutreachManager
from agent.scheduler import AgentScheduler


def build_components(config: Config) -> dict:
    """
    Build all agent components. Shared by CLI, daemon, and both modes.

    Returns a dict of all components for flexible wiring.
    """
    project_root = os.path.dirname(os.path.abspath(__file__))

    # LLM provider
    llm = OpenAIProvider(api_key=config.openai_api_key)

    # Memory
    db_path = os.path.join(project_root, "data", "agent_memory.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    memory = MemoryStore(db_path=db_path)

    # Tool registry
    tools = ToolRegistry()
    tools.register(CurrentTimeTool())
    tools.register(CalculatorTool())

    # Email tool
    email_tool = None
    if config.email_username and config.email_password:
        email_tool = EmailTool(
            username=config.email_username,
            password=config.email_password,
            imap_host=config.imap_host,
            imap_port=config.imap_port,
            smtp_host=config.smtp_host,
            smtp_port=config.smtp_port,
        )
        tools.register(email_tool)

    # Browser tool
    browser = BrowserTool()
    tools.register(browser)

    # Calendar tool
    credentials_path = os.path.join(project_root, config.google_credentials_path)
    token_path = os.path.join(project_root, config.google_token_path)
    if os.path.exists(token_path):
        tools.register(CalendarTool(
            credentials_path=credentials_path,
            token_path=token_path,
        ))

    # Profile tool
    profile_store = ProfileStore(db_path=db_path)
    tools.register(ProfileTool(
        profile_store=profile_store,
        browser_tool=browser,
        llm_provider=llm,
    ))

    # Job discovery
    job_store = JobStore(db_path=db_path)
    job_matcher = JobMatcher(llm_provider=llm)

    linkedin_session_dir = os.path.join(project_root, config.linkedin_session_dir)
    linkedin_session = None
    if os.path.exists(linkedin_session_dir):
        linkedin_session = LinkedInSession(session_dir=linkedin_session_dir)

    scanner = JobScanner(
        job_store=job_store,
        job_matcher=job_matcher,
        profile_store=profile_store,
        linkedin_session=linkedin_session,
        browser_tool=browser,
        email_tool=email_tool,
    )
    tools.register(JobTool(scanner=scanner, job_store=job_store))

    # Outreach
    outreach_manager = OutreachManager(
        job_store=job_store,
        profile_store=profile_store,
        llm_provider=llm,
        email_tool=email_tool,
        linkedin_session=linkedin_session,
        notification_email=config.email_username,
    )
    tools.register(OutreachTool(outreach_manager=outreach_manager))

    # Brain
    brain = AgentBrain(llm_provider=llm, memory=memory, tools=tools)
    brain.session_id = MemoryStore.new_session_id()

    # Scheduler
    scheduler = AgentScheduler(
        scanner=scanner,
        outreach_manager=outreach_manager,
        profile_store=profile_store,
        job_store=job_store,
    )

    return {
        "brain": brain,
        "browser": browser,
        "linkedin_session": linkedin_session,
        "scheduler": scheduler,
        "tools": tools,
        "memory": memory,
    }


async def run_cli_mode(brain: AgentBrain):
    """Interactive CLI chat loop."""
    print("=" * 60)
    print("  Personal AI Agent — CLI Mode")
    print("  Type your message and press Enter.")
    print("  Type 'quit' or 'exit' to stop.")
    print("=" * 60)
    print()

    while True:
        try:
            user_input = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("You: ").strip()
            )

            if user_input.lower() in ("quit", "exit", "q"):
                print("\nGoodbye!")
                break

            if not user_input:
                continue

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


async def run_daemon_mode(scheduler: AgentScheduler):
    """Background scheduler only — no user interaction."""
    print("=" * 60)
    print("  Personal AI Agent — Daemon Mode")
    print("  Running autonomously in the background.")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)
    print()

    try:
        await scheduler.start()
    except KeyboardInterrupt:
        await scheduler.stop()
        print("\nDaemon stopped.")


async def run_both_mode(brain: AgentBrain, scheduler: AgentScheduler):
    """CLI + scheduler running in parallel."""
    print("=" * 60)
    print("  Personal AI Agent — CLI + Daemon Mode")
    print("  Interactive chat + background automation.")
    print("  Type 'quit' or 'exit' to stop.")
    print("=" * 60)
    print()

    # Run CLI and scheduler concurrently
    scheduler_task = asyncio.create_task(scheduler.start())

    try:
        await run_cli_mode(brain)
    finally:
        await scheduler.stop()
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


async def run_telegram_mode(config: Config):
    """
    Run the Telegram bot frontend (multi-user, public).

    This bypasses build_components() (which is single-user) and uses
    UserSessionManager to create per-user Brain instances on demand.
    """
    from agent.users import UserSessionManager
    from agent.frontends.telegram_bot import TelegramBot

    if not config.telegram_bot_token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN not set in .env.\n"
            "Get a bot token from @BotFather on Telegram."
        )

    project_root = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(project_root, "data", "users")
    os.makedirs(data_dir, exist_ok=True)

    print("=" * 60)
    print("  Navox Agent — Telegram Bot Mode")
    print("  Running as a public Telegram bot.")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)
    print()

    session_manager = UserSessionManager(
        config=config,
        data_dir=data_dir,
        max_cached=config.telegram_max_users_cached,
    )

    bot = TelegramBot(
        token=config.telegram_bot_token,
        session_manager=session_manager,
        rate_limit=config.telegram_rate_limit,
    )

    await bot.start()


def main():
    parser = argparse.ArgumentParser(description="Navox Agent")
    parser.add_argument(
        "--mode",
        choices=["cli", "daemon", "both", "telegram"],
        default="cli",
        help="Run mode: cli (interactive), daemon (background), both (cli + daemon), telegram (public bot)",
    )
    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Load config and build components
    config = Config()
    config.validate()

    # Telegram mode uses its own component wiring (UserSessionManager)
    if args.mode == "telegram":
        try:
            asyncio.run(run_telegram_mode(config))
        except KeyboardInterrupt:
            print("\nShutting down...")
        return

    # All other modes use the single-user component graph
    components = build_components(config)

    brain = components["brain"]
    browser = components["browser"]
    scheduler = components["scheduler"]

    # Run the selected mode
    try:
        if args.mode == "cli":
            asyncio.run(run_cli_mode(brain))
        elif args.mode == "daemon":
            asyncio.run(run_daemon_mode(scheduler))
        elif args.mode == "both":
            asyncio.run(run_both_mode(brain, scheduler))
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        asyncio.run(browser.cleanup())


if __name__ == "__main__":
    main()
