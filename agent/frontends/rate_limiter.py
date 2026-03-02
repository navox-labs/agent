from __future__ import annotations

"""
Simple in-memory rate limiter for multi-user frontends.

Tracks message counts per user in a sliding window. No persistence
needed — resets on restart, which is fine for a launch.

Default limits:
- 20 messages per user per hour (general interactions)
"""

import time


class RateLimiter:
    """Per-user sliding window rate limiter."""

    def __init__(self, max_per_user: int = 20, window_seconds: int = 3600):
        """
        Args:
            max_per_user: Maximum requests per user within the window
            window_seconds: Sliding window duration in seconds (default: 1 hour)
        """
        self._max = max_per_user
        self._window = window_seconds
        self._timestamps: dict[str, list[float]] = {}

    def check(self, user_id: str) -> bool:
        """
        Check if a user is within their rate limit.

        Returns True if the request is allowed, False if rate limited.
        Automatically records the request if allowed.
        """
        now = time.time()
        cutoff = now - self._window

        # Get or create timestamp list for this user
        if user_id not in self._timestamps:
            self._timestamps[user_id] = []

        # Remove expired timestamps
        self._timestamps[user_id] = [
            ts for ts in self._timestamps[user_id] if ts > cutoff
        ]

        # Check limit
        if len(self._timestamps[user_id]) >= self._max:
            return False

        # Record this request
        self._timestamps[user_id].append(now)
        return True

    def remaining(self, user_id: str) -> int:
        """Returns how many requests the user has left in the current window."""
        now = time.time()
        cutoff = now - self._window

        if user_id not in self._timestamps:
            return self._max

        active = [ts for ts in self._timestamps[user_id] if ts > cutoff]
        return max(0, self._max - len(active))

    def reset(self, user_id: str) -> None:
        """Reset a user's rate limit (e.g., after payment)."""
        self._timestamps.pop(user_id, None)
