from __future__ import annotations

"""Tests for agent/frontends/formatters.py — Telegram message formatting."""

from agent.frontends.formatters import (
    format_match_result,
    format_match_results,
    format_profile_preview,
    format_welcome_message,
    format_help_message,
    format_viral_share,
    format_rate_limit_message,
)


def test_format_match_result_high_score():
    job = {
        "title": "ML Engineer",
        "company": "Google",
        "match_score": 85,
        "matched_skills": ["Python", "PyTorch"],
        "missing_skills": ["Kubernetes"],
        "location": "Toronto",
    }
    result = format_match_result(job, index=1)
    assert "ML Engineer" in result
    assert "Google" in result
    assert "85/100" in result
    assert "Python" in result
    assert "Kubernetes" in result
    assert "\U0001f525" in result  # fire emoji for 80+


def test_format_match_result_medium_score():
    job = {
        "title": "Data Scientist",
        "company": "Shopify",
        "match_score": 65,
        "matched_skills": ["Python"],
        "missing_skills": [],
    }
    result = format_match_result(job, index=2)
    assert "\u2b50" in result  # star emoji for 60-79


def test_format_match_result_low_score():
    job = {
        "title": "Frontend Dev",
        "company": "Meta",
        "match_score": 40,
        "matched_skills": [],
        "missing_skills": ["React"],
    }
    result = format_match_result(job, index=3)
    assert "\U0001f4a1" in result  # lightbulb emoji for <60


def test_format_match_result_with_connection():
    job = {
        "title": "ML Engineer",
        "company": "Cohere",
        "match_score": 80,
        "matched_skills": ["Python"],
        "missing_skills": [],
        "connection_name": "Sarah Chen",
    }
    result = format_match_result(job)
    assert "Sarah Chen" in result


def test_format_match_results_empty():
    result = format_match_results([])
    assert "No job matches found" in result


def test_format_match_results_multiple():
    jobs = [
        {"title": "ML Engineer", "company": "Google", "match_score": 85, "matched_skills": [], "missing_skills": []},
        {"title": "Data Scientist", "company": "Meta", "match_score": 70, "matched_skills": [], "missing_skills": []},
    ]
    result = format_match_results(jobs)
    assert "2 matches" in result
    assert "ML Engineer" in result
    assert "Data Scientist" in result


def test_format_profile_preview_truncation():
    long_text = "A" * 1000
    result = format_profile_preview(long_text)
    assert "..." in result
    assert len(result) < len(long_text) + 200  # preview + surrounding text


def test_format_welcome_message():
    result = format_welcome_message()
    assert "Navox Agent" in result
    assert "profile" in result.lower()


def test_format_help_message():
    result = format_help_message()
    assert "/start" in result
    assert "/profile" in result
    assert "/match" in result
    assert "navox.tech" in result


def test_format_viral_share():
    result = format_viral_share("navox_agent_bot")
    assert "t.me/navox_agent_bot" in result


def test_format_rate_limit_message():
    result = format_rate_limit_message(1800)
    assert "30 minute" in result
    assert "free" in result.lower()
