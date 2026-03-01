"""
Configuration loader.

This module loads settings from a .env file into environment variables.
The pattern: secrets live in .env (never committed to git), and this module
provides a clean Config object so the rest of the code never touches
os.environ directly.
"""

import os
from dotenv import load_dotenv

# Load .env file from the project root
load_dotenv()


class Config:
    """Central configuration loaded from environment variables."""

    def __init__(self):
        # LLM API keys
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")

        # Agent settings
        self.default_llm = os.getenv("DEFAULT_LLM", "openai")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.db_path = os.getenv("DB_PATH", "data/agent_memory.db")
        self.max_context_messages = int(os.getenv("MAX_CONTEXT_MESSAGES", "20"))

    def validate(self):
        """Check that required config values are present."""
        missing = []
        if not self.openai_api_key:
            missing.append("OPENAI_API_KEY")

        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                f"Copy .env.example to .env and fill in your API keys."
            )
