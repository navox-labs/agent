from __future__ import annotations

"""Tests for agent/jobs/email_finder.py — hiring manager email discovery."""

from agent.jobs.email_finder import (
    guess_company_domain,
    parse_name,
    guess_emails,
    extract_hiring_info,
)


# ── guess_company_domain ──────────────────────────────────────────

def test_known_company_domain():
    assert guess_company_domain("Google") == "google.com"


def test_known_company_case_insensitive():
    assert guess_company_domain("SHOPIFY") == "shopify.com"


def test_known_company_with_suffix():
    assert guess_company_domain("Google Inc.") == "google.com"


def test_unknown_company_fallback():
    domain = guess_company_domain("Acme Corp")
    assert domain == "acme.com"


def test_company_domain_from_job_url():
    domain = guess_company_domain("Acme", "https://careers.acme.io/jobs/123")
    assert domain == "careers.acme.io"


def test_company_domain_ignores_linkedin_url():
    domain = guess_company_domain("Acme Corp", "https://linkedin.com/jobs/view/123")
    assert domain == "acme.com"  # Falls back, doesn't use linkedin.com


def test_company_domain_empty():
    assert guess_company_domain("") is None
    assert guess_company_domain("Unknown") is None


# ── parse_name ────────────────────────────────────────────────────

def test_parse_name_basic():
    result = parse_name("Sarah Chen")
    assert result["first"] == "sarah"
    assert result["last"] == "chen"
    assert result["f"] == "s"


def test_parse_name_three_parts():
    result = parse_name("John Michael Doe")
    assert result["first"] == "john"
    assert result["last"] == "doe"


def test_parse_name_with_prefix():
    result = parse_name("Dr. Jane Smith")
    assert result["first"] == "jane"
    assert result["last"] == "smith"


def test_parse_name_single_name():
    assert parse_name("Madonna") is None


def test_parse_name_empty():
    assert parse_name("") is None
    assert parse_name(None) is None


# ── guess_emails ──────────────────────────────────────────────────

def test_guess_emails_basic():
    emails = guess_emails("Sarah Chen", "Shopify")
    assert "sarah.chen@shopify.com" in emails
    assert "sarah@shopify.com" in emails
    assert "schen@shopify.com" in emails


def test_guess_emails_known_domain():
    emails = guess_emails("John Doe", "Google")
    assert emails[0] == "john.doe@google.com"


def test_guess_emails_bad_name():
    emails = guess_emails("", "Google")
    assert emails == []


def test_guess_emails_bad_company():
    emails = guess_emails("Sarah Chen", "Unknown")
    assert emails == []


def test_guess_emails_multiple_patterns():
    emails = guess_emails("Sarah Chen", "Shopify")
    # Should have multiple patterns
    assert len(emails) >= 3


# ── extract_hiring_info ───────────────────────────────────────────

def test_extract_hiring_info_with_name():
    info = extract_hiring_info(
        hiring_manager_name="Sarah Chen",
        company="Shopify",
    )
    assert info["hiring_manager_name"] == "Sarah Chen"
    assert len(info["hiring_manager_emails"]) > 0
    assert "sarah.chen@shopify.com" in info["hiring_manager_emails"]


def test_extract_hiring_info_no_name():
    info = extract_hiring_info(hiring_manager_name=None, company="Shopify")
    assert info["hiring_manager_name"] is None
    assert info["hiring_manager_emails"] == []


def test_extract_hiring_info_no_company():
    info = extract_hiring_info(hiring_manager_name="Sarah Chen", company="")
    assert info["hiring_manager_emails"] == []
