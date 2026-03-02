from __future__ import annotations

"""
Persistent memory store backed by SQLite.

This gives the agent long-term memory across sessions. Without this,
every time you restart the CLI, the agent forgets everything — like
talking to someone with amnesia.

Three types of memory:
1. Conversations — every message, stored with timestamps and session IDs
2. Preferences — learned facts about the user (name, timezone, habits)
3. Summaries — compressed versions of old conversations to save context space

SQLite is perfect here because:
- It's a single file (data/agent_memory.db) — no database server needed
- It's built into Python (no extra dependencies)
- It handles concurrent reads well (important when multiple frontends are running)

Key concept — Context Window Management:
LLMs can only process a limited amount of text at once (the "context window").
If we sent the entire conversation history, we'd quickly run out of space.
Instead, we keep the last 20 messages in full, and summarize older ones.
"""

import sqlite3
import uuid
from datetime import datetime


class MemoryStore:
    """SQLite-backed persistent memory for the agent."""

    def __init__(self, db_path: str = "data/agent_memory.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """
        Create a new database connection.

        We use WAL (Write-Ahead Logging) mode so multiple frontends
        can read the database simultaneously without blocking each other.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Return rows as dict-like objects
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        """Create tables if they don't exist. Called once on startup."""
        conn = self._get_connection()
        try:
            conn.executescript("""
                -- Every message sent or received
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    frontend TEXT DEFAULT 'cli',
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                -- Learned user preferences
                CREATE TABLE IF NOT EXISTS preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    learned_from TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                -- Compressed conversation history
                CREATE TABLE IF NOT EXISTS summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    message_count INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                -- Index for fast lookups by session
                CREATE INDEX IF NOT EXISTS idx_conversations_session
                    ON conversations(session_id, timestamp);

                -- Index for fast preference lookups
                CREATE INDEX IF NOT EXISTS idx_preferences_key
                    ON preferences(key);
            """)
            conn.commit()
        finally:
            conn.close()

    # ── Conversation Methods ──────────────────────────────────────

    async def save_message(
        self, session_id: str, role: str, content: str, frontend: str = "cli"
    ):
        """
        Save a single message to the conversation history.

        Args:
            session_id: Groups messages into sessions (one per CLI run, etc.)
            role: "user" or "assistant"
            content: The actual message text
            frontend: Which frontend sent this ("cli", "discord", "telegram", etc.)
        """
        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO conversations (session_id, role, content, frontend) VALUES (?, ?, ?, ?)",
                (session_id, role, content, frontend),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_recent_messages(self, limit: int = 20) -> list[dict]:
        """
        Get the most recent messages across all sessions.

        These are sent to the LLM as conversation context so it knows
        what you've been talking about recently.
        """
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT role, content FROM conversations ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            # Reverse so oldest is first (LLMs expect chronological order)
            return [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
        finally:
            conn.close()

    async def get_session_messages(self, session_id: str) -> list[dict]:
        """Get all messages from a specific session."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT role, content FROM conversations WHERE session_id = ? ORDER BY timestamp",
                (session_id,),
            ).fetchall()
            return [{"role": row["role"], "content": row["content"]} for row in rows]
        finally:
            conn.close()

    # ── Preference Methods ────────────────────────────────────────

    async def get_preference(self, key: str) -> str | None:
        """
        Look up a learned preference.

        Example: get_preference("user_name") -> "Alice"
        """
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT value FROM preferences WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None
        finally:
            conn.close()

    async def set_preference(self, key: str, value: str, source: str | None = None):
        """
        Store or update a preference.

        Uses INSERT OR REPLACE so it updates if the key already exists.
        """
        conn = self._get_connection()
        try:
            conn.execute(
                """INSERT INTO preferences (key, value, learned_from, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(key) DO UPDATE SET
                       value = excluded.value,
                       learned_from = excluded.learned_from,
                       updated_at = CURRENT_TIMESTAMP""",
                (key, value, source),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_all_preferences(self) -> dict[str, str]:
        """Get all stored preferences as a dictionary."""
        conn = self._get_connection()
        try:
            rows = conn.execute("SELECT key, value FROM preferences").fetchall()
            return {row["key"]: row["value"] for row in rows}
        finally:
            conn.close()

    # ── Summary Methods ───────────────────────────────────────────

    async def save_summary(self, session_id: str, summary: str, message_count: int):
        """Save a compressed summary of a conversation session."""
        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO summaries (session_id, summary, message_count) VALUES (?, ?, ?)",
                (session_id, summary, message_count),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_recent_summaries(self, limit: int = 5) -> list[str]:
        """Get the most recent conversation summaries."""
        conn = self._get_connection()
        try:
            rows = conn.execute(
                "SELECT summary FROM summaries ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [row["summary"] for row in reversed(rows)]
        finally:
            conn.close()

    # ── Context Building ──────────────────────────────────────────

    async def build_context(self, limit: int = 20) -> dict:
        """
        Build the full context to send to the LLM.

        This combines:
        1. Recent conversation summaries (compressed old history)
        2. Recent messages (full detail)
        3. User preferences

        This is the key to making the agent feel like it "knows" you.
        """
        messages = await self.get_recent_messages(limit=limit)
        summaries = await self.get_recent_summaries(limit=5)
        preferences = await self.get_all_preferences()

        return {
            "messages": messages,
            "summaries": summaries,
            "preferences": preferences,
        }

    # ── Utility ───────────────────────────────────────────────────

    async def get_message_count(self, session_id: str | None = None) -> int:
        """Get total message count, optionally filtered by session."""
        conn = self._get_connection()
        try:
            if session_id:
                row = conn.execute(
                    "SELECT COUNT(*) as count FROM conversations WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) as count FROM conversations").fetchone()
            return row["count"]
        finally:
            conn.close()

    @staticmethod
    def new_session_id() -> str:
        """Generate a unique session ID."""
        return str(uuid.uuid4())[:8]
