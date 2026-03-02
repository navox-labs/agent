from __future__ import annotations

"""
Profile Store — manages the user's professional profile for job matching.

The profile is the foundation of everything the agent does:
- When scanning jobs, it scores them against YOUR profile
- When drafting outreach, it references YOUR skills and experience
- When sharing with connections, it sends YOUR Navox card or resume

Profile sources:
1. Navox profileCard URL (e.g., navox.tech/card/jsmith) — fetched via browser
2. Resume PDF — text extracted locally
3. Manual input — user tells the agent about themselves

The profile structure mirrors Navox's UserProfileContext:
- personalInfo: name, position, location, bio
- professionalData: skills[], experience[], education[]
- preferences: expertise areas, target roles
"""

import json
import logging
import os
import sqlite3

logger = logging.getLogger(__name__)


class ProfileStore:
    """
    Stores and retrieves the user's professional profile.

    Data lives in the same SQLite database as agent memory,
    in a dedicated `profile` table. This keeps everything in
    one file (data/agent_memory.db) for simplicity.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_table()

    def _init_table(self):
        """Create the profile table if it doesn't exist."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS profile (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def _set(self, key: str, value: str):
        """Set a profile key-value pair."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO profile (key, value, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()

    def _get(self, key: str) -> str | None:
        """Get a profile value by key."""
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT value FROM profile WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    # ── Profile Data ───────────────────────────────────────────────

    async def set_profile_from_text(self, profile_text: str):
        """
        Store profile data extracted from a Navox card or resume.

        The LLM extracts structured text from whatever source and passes
        it here. We store the raw text — the LLM can parse it naturally.
        """
        self._set("profile_text", profile_text)
        logger.info("Profile text stored (%d chars)", len(profile_text))

    async def set_profile_card_url(self, url: str):
        """Store the Navox profileCard URL for sharing with connections."""
        self._set("profile_card_url", url)
        logger.info("Profile card URL stored: %s", url)

    async def set_resume_path(self, path: str):
        """Store the path to the user's resume PDF."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Resume not found: {path}")
        self._set("resume_path", path)
        logger.info("Resume path stored: %s", path)

    async def get_profile_summary(self) -> str | None:
        """
        Get the profile text for LLM matching.

        This is what gets injected into the system prompt so the LLM
        can score jobs against the user's background.
        """
        return self._get("profile_text")

    async def get_profile_card_url(self) -> str | None:
        """Get the Navox profileCard URL for sharing."""
        return self._get("profile_card_url")

    async def get_resume_path(self) -> str | None:
        """Get the resume PDF path for attachment."""
        path = self._get("resume_path")
        if path and os.path.exists(path):
            return path
        return None

    async def has_profile(self) -> bool:
        """Check if a profile has been set."""
        return self._get("profile_text") is not None

    # ── Job Preferences ────────────────────────────────────────────

    async def set_job_preferences(self, preferences: dict):
        """
        Store job search preferences (target roles, locations, etc.).

        Example:
        {
            "target_roles": ["ML Engineer", "Data Scientist"],
            "locations": ["Toronto", "Remote"],
            "industries": ["AI/ML", "FinTech"],
            "connection_preference": "2nd"
        }
        """
        self._set("job_preferences", json.dumps(preferences))
        logger.info("Job preferences stored")

    async def get_job_preferences(self) -> dict | None:
        """Get stored job search preferences."""
        raw = self._get("job_preferences")
        if raw:
            return json.loads(raw)
        return None

    # ── LinkedIn Cookie ────────────────────────────────────────────

    def set_linkedin_cookie(self, cookie: str):
        """Store the user's LinkedIn li_at cookie for authenticated searches."""
        self._set("linkedin_cookie", cookie)
        logger.info("LinkedIn cookie stored")

    def get_linkedin_cookie(self) -> str | None:
        """Get the stored LinkedIn li_at cookie."""
        return self._get("linkedin_cookie")

    def clear_linkedin_cookie(self):
        """Remove the stored LinkedIn cookie."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DELETE FROM profile WHERE key = 'linkedin_cookie'")
            conn.commit()
        finally:
            conn.close()
        logger.info("LinkedIn cookie cleared")

    async def get_full_context(self) -> dict:
        """
        Get everything the LLM needs to know about the user.

        Returns a dict with profile text, card URL, resume path,
        and job preferences — all in one call for the system prompt.
        """
        return {
            "profile_text": self._get("profile_text"),
            "profile_card_url": self._get("profile_card_url"),
            "resume_path": self._get("resume_path"),
            "job_preferences": json.loads(self._get("job_preferences") or "null"),
        }
