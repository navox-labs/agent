from __future__ import annotations

"""Tests for agent/frontends/rate_limiter.py — per-user rate limiting."""

import time
from unittest.mock import patch

from agent.frontends.rate_limiter import RateLimiter


def test_allows_under_limit():
    limiter = RateLimiter(max_per_user=3, window_seconds=3600)
    assert limiter.check("user1") is True
    assert limiter.check("user1") is True
    assert limiter.check("user1") is True


def test_blocks_over_limit():
    limiter = RateLimiter(max_per_user=2, window_seconds=3600)
    assert limiter.check("user1") is True
    assert limiter.check("user1") is True
    assert limiter.check("user1") is False  # 3rd request blocked


def test_different_users_independent():
    limiter = RateLimiter(max_per_user=1, window_seconds=3600)
    assert limiter.check("user1") is True
    assert limiter.check("user2") is True  # Different user, separate limit
    assert limiter.check("user1") is False  # user1 over limit


def test_remaining_count():
    limiter = RateLimiter(max_per_user=5, window_seconds=3600)
    assert limiter.remaining("user1") == 5
    limiter.check("user1")
    assert limiter.remaining("user1") == 4
    limiter.check("user1")
    assert limiter.remaining("user1") == 3


def test_remaining_unknown_user():
    limiter = RateLimiter(max_per_user=10, window_seconds=3600)
    assert limiter.remaining("unknown") == 10


def test_window_expiry():
    """Expired timestamps should not count toward the limit."""
    limiter = RateLimiter(max_per_user=1, window_seconds=60)

    # Manually insert an old timestamp
    limiter._timestamps["user1"] = [time.time() - 120]  # 2 minutes ago

    # Should be allowed since the old timestamp expired
    assert limiter.check("user1") is True


def test_reset():
    limiter = RateLimiter(max_per_user=1, window_seconds=3600)
    limiter.check("user1")
    assert limiter.check("user1") is False  # Over limit

    limiter.reset("user1")
    assert limiter.check("user1") is True  # Reset clears the count
