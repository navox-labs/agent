from __future__ import annotations

"""
Shared test fixtures for the entire test suite.

Each store fixture uses a temporary SQLite file that's cleaned up after the
test. We can't use ":memory:" because the stores open separate connections
for init vs operations, and each ":memory:" connection is a different DB.
"""

import os
import tempfile
import pytest
from unittest.mock import AsyncMock

from agent.models import LLMResponse
from agent.memory.store import MemoryStore
from agent.profile.store import ProfileStore
from agent.jobs.store import JobStore
from agent.tools.registry import ToolRegistry


@pytest.fixture
def memory_store():
    """MemoryStore backed by a temporary SQLite file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = MemoryStore(db_path=path)
    yield store
    os.unlink(path)


@pytest.fixture
def profile_store():
    """ProfileStore backed by a temporary SQLite file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = ProfileStore(db_path=path)
    yield store
    os.unlink(path)


@pytest.fixture
def job_store():
    """JobStore backed by a temporary SQLite file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = JobStore(db_path=path)
    yield store
    os.unlink(path)


@pytest.fixture
def mock_llm():
    """
    Mock LLMProvider that returns a configurable LLMResponse.

    Default: returns LLMResponse(text="mock response") with no tool calls.
    Override in tests: mock_llm.generate.return_value = LLMResponse(...)
    """
    llm = AsyncMock()
    llm.generate.return_value = LLMResponse(text="mock response")
    return llm


@pytest.fixture
def tool_registry():
    """Fresh, empty ToolRegistry."""
    return ToolRegistry()


@pytest.fixture
def sample_job():
    """A sample job dict matching the schema JobStore.save_job() expects."""
    return {
        "job_id": "test-job-001",
        "title": "ML Engineer",
        "company": "TestCo",
        "location": "Toronto",
        "url": "https://example.com/jobs/1",
        "description": "Build ML models using Python and PyTorch.",
        "source": "linkedin",
        "match_score": 75,
        "matched_skills": ["Python", "PyTorch"],
        "missing_skills": ["Kubernetes"],
        "gap_analysis": "Strong ML skills, missing DevOps experience.",
    }
