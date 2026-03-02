from __future__ import annotations

"""
Telegram message formatters.

Format job matches, profile summaries, and viral share text for
Telegram's message format (Markdown V2 is tricky, so we use HTML
parse mode for reliability).
"""


def format_match_result(job: dict, index: int = 1) -> str:
    """
    Format a single job match for display in Telegram.

    Uses plain text with emoji for rich formatting.
    Telegram HTML parse mode is used for bold/italic.

    Args:
        job: Job dict with title, company, match_score, matched_skills, etc.
        index: Display number (1-based)
    """
    score = job.get("match_score", 0)

    # Score emoji based on range
    if score >= 80:
        score_icon = "\U0001f525"  # fire
    elif score >= 60:
        score_icon = "\u2b50"  # star
    else:
        score_icon = "\U0001f4a1"  # lightbulb

    title = job.get("title", "Unknown Role")
    company = job.get("company", "Unknown Company")
    location = job.get("location", "")
    matched = job.get("matched_skills", [])
    missing = job.get("missing_skills", [])
    gap = job.get("gap_analysis", "")
    connection = job.get("connection_name", "")
    connection_rel = job.get("connection_relation", "")
    hiring_mgr = job.get("hiring_manager_name", "")
    hiring_email = job.get("hiring_manager_email", "")
    url = job.get("url", "")

    lines = [
        f"{score_icon} <b>{index}. {title}</b> at {company}",
        f"   Score: {score}/100",
    ]

    if location:
        lines.append(f"   Location: {location}")
    if matched:
        lines.append(f"   Matched: {', '.join(matched[:6])}")
    if missing:
        lines.append(f"   Gap: {', '.join(missing[:4])}")
    if connection:
        conn_text = f"   \U0001f91d Connection: {connection}"
        if connection_rel:
            conn_text += f" ({connection_rel})"
        lines.append(conn_text)
    elif connection_rel:
        lines.append(f"   \U0001f91d {connection_rel} connection at {company}")
    if hiring_mgr:
        mgr_text = f"   \U0001f4e7 Recruiter: {hiring_mgr}"
        if hiring_email:
            mgr_text += f" ({hiring_email})"
        lines.append(mgr_text)
    elif hiring_email:
        lines.append(f"   \U0001f4e7 Recruiter: {hiring_email}")
    if url:
        lines.append(f"   <a href=\"{url}\">View posting</a>")

    return "\n".join(lines)


def format_match_results(jobs: list[dict]) -> str:
    """Format multiple job matches into a single message."""
    if not jobs:
        return "No job matches found. Try broadening your search criteria."

    header = f"Found <b>{len(jobs)} match{'es' if len(jobs) != 1 else ''}</b>:\n"
    results = []
    for i, job in enumerate(jobs, 1):
        results.append(format_match_result(job, index=i))

    return header + "\n\n".join(results)


def format_profile_preview(profile_text: str) -> str:
    """Format an extracted profile for confirmation display."""
    # Truncate long profiles
    preview = profile_text[:800]
    if len(profile_text) > 800:
        preview += "\n..."

    return (
        "Here's what I extracted from your profile:\n\n"
        f"{_escape_html(preview)}\n\n"
        "Is this correct? Tell me what roles you're looking for, "
        "or send another file to update your profile."
    )


def format_welcome_message() -> str:
    """Format the /start welcome message."""
    return (
        "Welcome to <b>Navox Agent</b>!\n\n"
        "I find jobs that match your profile, score them against your skills, "
        "and help you draft personalized outreach to connections.\n\n"
        "Let's get started \u2014 how would you like to set up your profile?"
    )


def format_help_message() -> str:
    """Format the /help message."""
    return (
        "<b>Navox Agent \u2014 Commands</b>\n\n"
        "/start \u2014 Set up your profile\n"
        "/profile \u2014 View your current profile\n"
        "/match \u2014 Search for job matches\n"
        "/connect_linkedin \u2014 Connect LinkedIn for connection-filtered jobs\n"
        "/disconnect_linkedin \u2014 Remove LinkedIn connection\n"
        "/help \u2014 Show this help message\n\n"
        "<b>Profile setup options:</b>\n"
        "\u2022 Send a <b>resume PDF</b> \u2014 I'll extract your skills and experience\n"
        "\u2022 Paste a <b>LinkedIn URL</b> \u2014 I'll read your profile\n"
        "\u2022 Paste a <b>Navox profileCard URL</b> \u2014 Best matching accuracy\n"
        "\u2022 <b>Describe yourself</b> \u2014 Tell me about your experience\n\n"
        "After setting up your profile, just chat naturally. "
        "Ask me to find jobs, draft outreach, or anything else.\n\n"
        "Built by Navox Labs \u2014 navox.tech"
    )


def format_viral_share(bot_username: str) -> str:
    """Generate a shareable CTA to append after delivering value."""
    return (
        f"\n\n\U0001f4ac Know someone job hunting? "
        f"Share this bot: https://t.me/{bot_username}"
    )


def format_rate_limit_message(remaining_seconds: int) -> str:
    """Format the rate limit exceeded message."""
    minutes = max(1, remaining_seconds // 60)
    return (
        "You've hit the hourly message limit. "
        f"Try again in ~{minutes} minute{'s' if minutes != 1 else ''}.\n\n"
        "This limit helps keep the bot free for everyone."
    )


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
