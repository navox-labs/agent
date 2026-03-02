from __future__ import annotations

"""Tests for agent/profile/extract.py — reusable profile extraction helpers."""

import os
import tempfile

import pytest

from agent.profile.extract import (
    extract_pdf_text,
    extract_txt_text,
    extract_file_text,
    detect_profile_input_type,
    extract_url_from_text,
)


# ── detect_profile_input_type ─────────────────────────────────────

def test_detect_linkedin_url():
    assert detect_profile_input_type("linkedin.com/in/john") == "linkedin_url"


def test_detect_linkedin_url_with_https():
    assert detect_profile_input_type("https://www.linkedin.com/in/john") == "linkedin_url"


def test_detect_navox_url():
    assert detect_profile_input_type("navox.tech/card/john") == "navox_url"


def test_detect_navox_url_with_https():
    assert detect_profile_input_type("https://navox.tech/card/john") == "navox_url"


def test_detect_raw_text():
    assert detect_profile_input_type("I am a senior ML engineer") == "raw_text"


def test_detect_case_insensitive():
    assert detect_profile_input_type("LINKEDIN.COM/IN/JOHN") == "linkedin_url"


# ── extract_url_from_text ─────────────────────────────────────────

def test_extract_url_with_https():
    url = extract_url_from_text("Check out https://linkedin.com/in/john please")
    assert url == "https://linkedin.com/in/john"


def test_extract_url_without_protocol():
    url = extract_url_from_text("My profile: navox.tech/card/jsmith")
    assert url is not None
    assert "navox.tech/card/jsmith" in url


def test_extract_url_none():
    assert extract_url_from_text("Just some plain text") is None


# ── extract_txt_text ──────────────────────────────────────────────

def test_extract_txt_text():
    fd, path = tempfile.mkstemp(suffix=".txt")
    try:
        os.write(fd, b"Senior ML Engineer with 5 years experience")
        os.close(fd)
        text = extract_txt_text(path)
        assert "ML Engineer" in text
    finally:
        os.unlink(path)


def test_extract_txt_text_file_not_found():
    with pytest.raises(FileNotFoundError):
        extract_txt_text("/nonexistent/file.txt")


# ── extract_file_text ─────────────────────────────────────────────

def test_extract_file_text_txt():
    fd, path = tempfile.mkstemp(suffix=".txt")
    try:
        os.write(fd, b"Python developer")
        os.close(fd)
        text = extract_file_text(path)
        assert "Python" in text
    finally:
        os.unlink(path)


def test_extract_file_text_unsupported():
    fd, path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    try:
        with pytest.raises(ValueError, match="Unsupported file type"):
            extract_file_text(path)
    finally:
        os.unlink(path)


def test_extract_file_text_not_found():
    with pytest.raises(FileNotFoundError):
        extract_file_text("/nonexistent/resume.pdf")
