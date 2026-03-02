from __future__ import annotations

"""Tests for agent/jobs/linkedin_cookie_session.py — cookie-based LinkedIn auth."""

import sqlite3
import tempfile

from agent.jobs.linkedin_cookie_session import LinkedInCookieSession
from agent.profile.store import ProfileStore


def test_cookie_session_init():
    """LinkedInCookieSession stores the cookie and initializes clean state."""
    session = LinkedInCookieSession(cookie="test_cookie_value_123")
    assert session._cookie == "test_cookie_value_123"
    assert session._context is None
    assert session._page is None
    assert session._search_count == 0


def test_cookie_session_rate_limit():
    """Rate limiter blocks after max searches."""
    session = LinkedInCookieSession(cookie="test")
    # Simulate hitting the limit
    session._search_count = 5
    session._search_hour_start = 1e18  # Far future so window doesn't expire
    assert session._check_rate_limit() is False


def test_cookie_session_rate_limit_resets():
    """Rate limiter resets after the hour window expires."""
    session = LinkedInCookieSession(cookie="test")
    session._search_count = 5
    session._search_hour_start = 0  # Long expired
    assert session._check_rate_limit() is True
    assert session._search_count == 0


def test_parse_job_card_with_connection_indicator():
    """Parser detects connection indicators in job card text."""
    from bs4 import BeautifulSoup

    html = """
    <div class="job-search-card">
        <h3>ML Engineer</h3>
        <h4>Google</h4>
        <span class="job-search-card__location">Toronto</span>
        <a href="/jobs/view/123">View</a>
        <span class="social-proof">3 connections work here</span>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    card = soup.select_one("div.job-search-card")

    session = LinkedInCookieSession(cookie="test")
    job = session._parse_job_card(card)

    assert job is not None
    assert job["title"] == "ML Engineer"
    assert job["company"] == "Google"
    assert "connection" in job.get("connection_name", "").lower() or "connection_name" in job


def test_parse_job_card_without_connection():
    """Parser handles cards without connection indicators."""
    from bs4 import BeautifulSoup

    html = """
    <div class="job-search-card">
        <h3>Data Scientist</h3>
        <h4>Meta</h4>
        <a href="/jobs/view/456">View</a>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    card = soup.select_one("div.job-search-card")

    session = LinkedInCookieSession(cookie="test")
    job = session._parse_job_card(card)

    assert job is not None
    assert job["title"] == "Data Scientist"
    assert "connection_name" not in job


def test_extract_poster_info():
    """Poster info extraction from job detail pages."""
    from bs4 import BeautifulSoup

    html = """
    <html>
    <body>
        <div class="jobs-poster__name">Sarah Chen</div>
    </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    session = LinkedInCookieSession(cookie="test")
    info = session._extract_poster_info(soup)

    assert info is not None
    assert info["name"] == "Sarah Chen"


def test_extract_poster_info_none():
    """Returns None when no poster info found."""
    from bs4 import BeautifulSoup

    html = "<html><body><div>No poster here</div></body></html>"
    soup = BeautifulSoup(html, "html.parser")
    session = LinkedInCookieSession(cookie="test")
    info = session._extract_poster_info(soup)

    assert info is None


# ── ProfileStore LinkedIn cookie methods ─────────────────────────

def test_profile_store_linkedin_cookie():
    """ProfileStore can store and retrieve LinkedIn cookies."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = ProfileStore(db_path=db_path)
    assert store.get_linkedin_cookie() is None

    store.set_linkedin_cookie("AQEtest123cookie")
    assert store.get_linkedin_cookie() == "AQEtest123cookie"


def test_profile_store_clear_linkedin_cookie():
    """ProfileStore can clear a stored LinkedIn cookie."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    store = ProfileStore(db_path=db_path)
    store.set_linkedin_cookie("AQEtest123cookie")
    assert store.get_linkedin_cookie() is not None

    store.clear_linkedin_cookie()
    assert store.get_linkedin_cookie() is None
