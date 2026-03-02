from __future__ import annotations

"""
Reusable profile extraction helpers.

These functions extract professional profile text from various input sources
(PDF files, URLs, raw text). Extracted from ProfileTool so both the CLI
profile tool and the Telegram bot can reuse them without going through
the tool interface.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)


def extract_pdf_text(file_path: str) -> str:
    """
    Extract text from a PDF file.

    Returns the concatenated text from all pages, or an empty string on failure.
    Raises FileNotFoundError if the file doesn't exist.
    Raises ImportError if PyPDF2 is not installed.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    import PyPDF2

    text_parts = []
    with open(file_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)

    return "\n".join(text_parts)


def extract_txt_text(file_path: str) -> str:
    """Extract text from a plain text file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "r") as f:
        return f.read()


def extract_file_text(file_path: str) -> str:
    """
    Extract text from a file based on its extension.

    Supports .pdf and .txt files.
    Raises ValueError for unsupported file types.
    """
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return extract_pdf_text(file_path)
    elif ext == ".txt":
        return extract_txt_text(file_path)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Use .pdf or .txt")


async def extract_profile_from_url(url: str, browser_tool, llm_provider) -> str:
    """
    Fetch a URL (LinkedIn or Navox profileCard) and extract profile text.

    Uses the browser tool to navigate to the page, then optionally uses
    the LLM to clean up raw page text into structured profile data.

    Returns the extracted profile text.
    Raises RuntimeError on fetch or extraction failure.
    """
    # Normalize URL
    if not url.startswith("http"):
        url = f"https://{url}"

    # Fetch the page
    nav_result = await browser_tool.execute(action="navigate", url=url)
    if not nav_result.success:
        raise RuntimeError(f"Failed to fetch URL: {nav_result.error}")

    page_text = nav_result.data.get("text", "") if isinstance(nav_result.data, dict) else str(nav_result.data)

    if not page_text or len(page_text.strip()) < 50:
        raise RuntimeError("Page returned too little text. It may not have loaded correctly.")

    # Use LLM to extract structured profile from raw page text
    if llm_provider:
        try:
            response = await llm_provider.generate(
                system=(
                    "You are a profile data extractor. Extract professional profile "
                    "information from raw web page text. Return a clean, structured "
                    "summary including: name, title/position, location, bio, skills, "
                    "experience, education, and any other relevant professional details. "
                    "Keep it concise but comprehensive."
                ),
                messages=[{
                    "role": "user",
                    "content": f"Extract the professional profile from this page text:\n\n{page_text[:5000]}",
                }],
            )
            return response.text
        except Exception as e:
            logger.warning("LLM extraction failed, using raw text: %s", e)
            return page_text
    else:
        return page_text


def detect_profile_input_type(text: str) -> str:
    """
    Detect what kind of profile input the user sent.

    Returns:
        "linkedin_url" — if text contains a LinkedIn profile URL
        "navox_url" — if text contains a Navox profileCard URL
        "raw_text" — otherwise
    """
    text_lower = text.lower()

    if "linkedin.com/in/" in text_lower:
        return "linkedin_url"
    if "navox.tech/card/" in text_lower:
        return "navox_url"

    return "raw_text"


def extract_url_from_text(text: str) -> str | None:
    """
    Extract the first URL from a text string.

    Returns the URL or None if no URL is found.
    """
    url_pattern = r'https?://[^\s<>\"\']+|(?:www\.|linkedin\.com|navox\.tech)[^\s<>\"\']*'
    match = re.search(url_pattern, text)
    if match:
        url = match.group(0)
        if not url.startswith("http"):
            url = f"https://{url}"
        return url
    return None
