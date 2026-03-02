from __future__ import annotations

"""
User session manager for multi-user frontends (Telegram, Discord, etc.).

The CLI mode is single-user — one brain, one memory store, one profile.
When running as a public Telegram bot, each user needs isolated data.

This module manages per-user component creation and caching:
- Each user gets their own SQLite database at data/users/{user_id}/agent.db
- Brain, MemoryStore, ProfileStore, JobStore are created per user
- The LLM provider is shared (stateless — just an API key wrapper)
- An LRU cache bounds active sessions in memory (data persists on disk)
"""

import asyncio
import logging
import os
from collections import OrderedDict

from agent.brain import AgentBrain
from agent.config import Config
from agent.llm.openai_provider import OpenAIProvider
from agent.memory.store import MemoryStore
from agent.profile.store import ProfileStore
from agent.jobs.store import JobStore
from agent.jobs.matcher import JobMatcher
from agent.tools.registry import ToolRegistry
from agent.tools.example_tools import CurrentTimeTool, CalculatorTool
from agent.tools.browser_tool import BrowserTool
from agent.tools.profile_tool import ProfileTool
from agent.tools.job_tool import JobTool
from agent.jobs.linkedin_cookie_session import LinkedInCookieSession
from agent.jobs.scanner import JobScanner

logger = logging.getLogger(__name__)


class UserSessionManager:
    """
    Manages per-user Brain instances with isolated stores.

    Lazily creates components on first message. Caches active sessions
    in memory with LRU eviction to bound RAM usage. Evicted users' data
    persists on disk — only the in-memory objects are freed.
    """

    def __init__(
        self,
        config: Config,
        data_dir: str,
        max_cached: int = 100,
        llm_provider: OpenAIProvider | None = None,
        browser_tool=None,
    ):
        """
        Args:
            config: Application config (API keys, settings)
            data_dir: Base directory for per-user data (e.g., "data/users")
            max_cached: Max active sessions in memory before LRU eviction
            llm_provider: Shared LLM provider (one instance for all users)
            browser_tool: Shared browser tool (one Chromium for all users)
        """
        self._config = config
        self._data_dir = data_dir
        self._max_cached = max_cached
        self._llm = llm_provider or OpenAIProvider(api_key=config.openai_api_key)
        self._browser = browser_tool
        self._sessions: OrderedDict[str, dict] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get_brain(self, user_id: str) -> AgentBrain:
        """
        Get or create a Brain for this user. Thread-safe.

        On first call for a user, builds all components (stores, tools, brain)
        and caches them. Subsequent calls return the cached brain.
        """
        async with self._lock:
            if user_id in self._sessions:
                # Move to end (most recently used)
                self._sessions.move_to_end(user_id)
                return self._sessions[user_id]["brain"]

            # Evict oldest if at capacity
            while len(self._sessions) >= self._max_cached:
                evicted_id, _ = self._sessions.popitem(last=False)
                logger.info("Evicted session for user %s from cache", evicted_id)

            # Build new session
            components = self._build_user_components(user_id)
            self._sessions[user_id] = components
            logger.info("Created new session for user %s", user_id)
            return components["brain"]

    def _build_user_components(self, user_id: str) -> dict:
        """
        Build isolated components for a user.

        Each user gets their own:
        - SQLite database at data/users/{user_id}/agent.db
        - MemoryStore, ProfileStore, JobStore
        - ToolRegistry with ProfileTool, JobTool, etc.
        - AgentBrain wired to all the above

        Shared across all users:
        - LLMProvider (stateless API key wrapper)
        - BrowserTool (one Chromium instance)
        """
        user_dir = os.path.join(self._data_dir, user_id)
        os.makedirs(user_dir, exist_ok=True)
        db_path = os.path.join(user_dir, "agent.db")

        # Per-user stores
        memory = MemoryStore(db_path=db_path)
        profile_store = ProfileStore(db_path=db_path)
        job_store = JobStore(db_path=db_path)

        # Lazily create shared browser on first use
        if self._browser is None:
            self._browser = BrowserTool()

        # Per-user tool registry
        tools = ToolRegistry()
        tools.register(CurrentTimeTool())
        tools.register(CalculatorTool())
        tools.register(self._browser)
        tools.register(ProfileTool(
            profile_store=profile_store,
            browser_tool=self._browser,
            llm_provider=self._llm,
        ))

        # Check for LinkedIn cookie → create authenticated session
        linkedin_session = None
        linkedin_cookie = profile_store.get_linkedin_cookie()
        if linkedin_cookie:
            linkedin_session = LinkedInCookieSession(cookie=linkedin_cookie)
            logger.info("LinkedIn cookie found for user %s — session will be created", user_id)

        # Job tools with scanner for real job searching
        job_matcher = JobMatcher(llm_provider=self._llm)
        scanner = JobScanner(
            job_store=job_store,
            job_matcher=job_matcher,
            profile_store=profile_store,
            linkedin_session=linkedin_session,
            browser_tool=self._browser,
        )
        tools.register(JobTool(scanner=scanner, job_store=job_store))

        # Brain
        brain = AgentBrain(llm_provider=self._llm, memory=memory, tools=tools)
        brain.session_id = MemoryStore.new_session_id()

        return {
            "brain": brain,
            "memory": memory,
            "profile_store": profile_store,
            "job_store": job_store,
            "job_matcher": job_matcher,
            "tools": tools,
        }

    def get_profile_store(self, user_id: str) -> ProfileStore | None:
        """Get a user's ProfileStore if they have an active session."""
        session = self._sessions.get(user_id)
        return session["profile_store"] if session else None

    async def reconnect_linkedin(self, user_id: str, cookie: str):
        """
        Store a LinkedIn cookie and rebuild the user's session
        so the scanner gets a LinkedIn session.
        """
        session = self._sessions.get(user_id)
        if not session:
            return

        # Store cookie
        session["profile_store"].set_linkedin_cookie(cookie)

        # Evict the cached session so it's rebuilt with the LinkedIn session
        async with self._lock:
            if user_id in self._sessions:
                del self._sessions[user_id]

        logger.info("LinkedIn reconnect for user %s — session will rebuild on next message", user_id)

    def get_job_matcher(self, user_id: str) -> JobMatcher | None:
        """Get a user's JobMatcher if they have an active session."""
        session = self._sessions.get(user_id)
        return session["job_matcher"] if session else None

    @property
    def active_sessions(self) -> int:
        """Number of currently cached sessions."""
        return len(self._sessions)
