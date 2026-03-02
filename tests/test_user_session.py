from __future__ import annotations

"""Tests for agent/users.py — UserSessionManager for multi-user isolation."""

import os
import tempfile

import pytest
from unittest.mock import AsyncMock

from agent.config import Config
from agent.models import LLMResponse
from agent.users import UserSessionManager


@pytest.fixture
def mock_config():
    """Config with a mock API key."""
    config = Config.__new__(Config)
    config.openai_api_key = "test-key"
    config.email_username = ""
    config.email_password = ""
    config.linkedin_session_dir = ""
    config.google_credentials_path = ""
    config.google_token_path = ""
    return config


@pytest.fixture
def session_manager(mock_config, tmp_path):
    """UserSessionManager with a temp data directory and mock LLM."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = LLMResponse(text="mock response")

    return UserSessionManager(
        config=mock_config,
        data_dir=str(tmp_path),
        max_cached=3,
        llm_provider=mock_llm,
    )


async def test_get_brain_creates_new_session(session_manager, tmp_path):
    """First call for a user creates a new brain with isolated stores."""
    brain = await session_manager.get_brain("user_1")
    assert brain is not None
    assert session_manager.active_sessions == 1

    # User's database should exist on disk
    user_db = os.path.join(str(tmp_path), "user_1", "agent.db")
    assert os.path.exists(user_db)


async def test_get_brain_returns_cached(session_manager):
    """Second call for the same user returns the cached brain."""
    brain1 = await session_manager.get_brain("user_1")
    brain2 = await session_manager.get_brain("user_1")
    assert brain1 is brain2
    assert session_manager.active_sessions == 1


async def test_different_users_get_different_brains(session_manager):
    """Different users get different brain instances."""
    brain1 = await session_manager.get_brain("user_1")
    brain2 = await session_manager.get_brain("user_2")
    assert brain1 is not brain2
    assert session_manager.active_sessions == 2


async def test_session_eviction(session_manager):
    """Sessions are evicted when cache exceeds max_cached (3)."""
    await session_manager.get_brain("user_1")
    await session_manager.get_brain("user_2")
    await session_manager.get_brain("user_3")
    assert session_manager.active_sessions == 3

    # Adding a 4th user should evict user_1
    await session_manager.get_brain("user_4")
    assert session_manager.active_sessions == 3


async def test_evicted_user_data_persists(session_manager, tmp_path):
    """Evicted user's data still exists on disk."""
    await session_manager.get_brain("user_1")
    await session_manager.get_brain("user_2")
    await session_manager.get_brain("user_3")
    await session_manager.get_brain("user_4")  # evicts user_1

    # user_1's database should still exist on disk
    user_db = os.path.join(str(tmp_path), "user_1", "agent.db")
    assert os.path.exists(user_db)


async def test_get_profile_store(session_manager):
    """Can retrieve a user's ProfileStore from an active session."""
    await session_manager.get_brain("user_1")
    store = session_manager.get_profile_store("user_1")
    assert store is not None


async def test_get_profile_store_nonexistent(session_manager):
    """Returns None for a user with no active session."""
    store = session_manager.get_profile_store("nonexistent")
    assert store is None


async def test_brain_has_session_id(session_manager):
    """Each brain gets a unique session ID."""
    brain = await session_manager.get_brain("user_1")
    assert brain.session_id is not None
    assert len(brain.session_id) == 8
