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

        # Email settings (Gmail IMAP/SMTP)
        self.email_username = os.getenv("EMAIL_USERNAME", "")
        self.email_password = os.getenv("EMAIL_PASSWORD", "")
        self.imap_host = os.getenv("IMAP_HOST", "imap.gmail.com")
        self.imap_port = int(os.getenv("IMAP_PORT", "993"))
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))

        # Google Calendar (OAuth2 — file paths, not env secrets)
        self.google_credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "data/google_credentials.json")
        self.google_token_path = os.getenv("GOOGLE_TOKEN_PATH", "data/google_token.json")

        # LinkedIn session (persistent browser data directory)
        self.linkedin_session_dir = os.getenv("LINKEDIN_SESSION_DIR", "data/linkedin_session")

        # Telegram bot (Phase 13)
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_rate_limit = int(os.getenv("TELEGRAM_RATE_LIMIT", "20"))
        self.telegram_max_users_cached = int(os.getenv("TELEGRAM_MAX_USERS_CACHED", "100"))

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
