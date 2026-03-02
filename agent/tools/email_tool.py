from __future__ import annotations

"""
Email Tool — read, search, and send emails via Gmail IMAP/SMTP.

How email protocols work:
- IMAP (Internet Message Access Protocol): Used to READ emails from a server.
  Your email client (Outlook, Gmail app, etc.) uses IMAP to fetch your inbox.
  We connect to imap.gmail.com on port 993 (encrypted).

- SMTP (Simple Mail Transfer Protocol): Used to SEND emails.
  When you hit "send", your client uses SMTP to deliver the message.
  We connect to smtp.gmail.com on port 587 (encrypted).

Gmail App Passwords:
  Google won't let you use your regular password for IMAP/SMTP.
  Instead, you generate an "App Password" — a 16-character code
  that grants access to just email, not your whole Google account.

  Setup: Google Account → Security → 2-Step Verification → App Passwords
"""

import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from datetime import datetime
import logging

from agent.tools.base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


def _decode_header_value(value: str) -> str:
    """Decode an email header that might be encoded (e.g., UTF-8, Base64)."""
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def _extract_body(msg) -> str:
    """Extract the plain text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
                except Exception:
                    continue
        # Fallback: try HTML if no plain text found
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or "utf-8"
                    return f"[HTML email] {payload.decode(charset, errors='replace')[:500]}"
                except Exception:
                    continue
        return "[Could not extract email body]"
    else:
        try:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
        except Exception:
            return "[Could not decode email body]"


class EmailTool(Tool):
    """Read, search, and send emails via Gmail IMAP/SMTP."""

    def __init__(self, username: str, password: str,
                 imap_host: str = "imap.gmail.com", imap_port: int = 993,
                 smtp_host: str = "smtp.gmail.com", smtp_port: int = 587):
        self._username = username
        self._password = password
        self._imap_host = imap_host
        self._imap_port = imap_port
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port

    @property
    def name(self) -> str:
        return "email"

    @property
    def description(self) -> str:
        return (
            "Read, search, and send emails. "
            "Actions: read_inbox (get recent/unread emails), "
            "search (find emails by keyword), "
            "send (compose and send a new email), "
            "reply (reply to an email by its number from the inbox)."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                "action", "string",
                "The email action to perform",
                enum=["read_inbox", "search", "send", "reply"],
            ),
            ToolParameter(
                "query", "string",
                "Search query — used with 'search' action (e.g., 'from:boss@company.com', 'subject:invoice')",
                required=False,
            ),
            ToolParameter(
                "to", "string",
                "Recipient email address — used with 'send' action",
                required=False,
            ),
            ToolParameter(
                "subject", "string",
                "Email subject — used with 'send' action",
                required=False,
            ),
            ToolParameter(
                "body", "string",
                "Email body text — used with 'send' and 'reply' actions",
                required=False,
            ),
            ToolParameter(
                "email_number", "integer",
                "Email number from inbox listing — used with 'reply' action",
                required=False,
            ),
            ToolParameter(
                "limit", "integer",
                "Maximum number of emails to fetch (default: 5)",
                required=False,
            ),
            ToolParameter(
                "unread_only", "boolean",
                "Only show unread emails (default: false)",
                required=False,
            ),
        ]

    async def execute(self, action: str, **kwargs) -> ToolResult:
        try:
            if action == "read_inbox":
                return await self._read_inbox(
                    limit=kwargs.get("limit", 5),
                    unread_only=kwargs.get("unread_only", False),
                )
            elif action == "search":
                query = kwargs.get("query", "")
                if not query:
                    return ToolResult(success=False, data=None, error="Search query is required")
                return await self._search(query, limit=kwargs.get("limit", 5))
            elif action == "send":
                to = kwargs.get("to", "")
                subject = kwargs.get("subject", "")
                body = kwargs.get("body", "")
                if not to or not subject or not body:
                    return ToolResult(success=False, data=None, error="'to', 'subject', and 'body' are all required to send an email")
                return await self._send(to, subject, body)
            elif action == "reply":
                email_number = kwargs.get("email_number")
                body = kwargs.get("body", "")
                if email_number is None or not body:
                    return ToolResult(success=False, data=None, error="'email_number' and 'body' are required to reply")
                return await self._reply(email_number, body)
            else:
                return ToolResult(success=False, data=None, error=f"Unknown action: {action}")
        except imaplib.IMAP4.error as e:
            return ToolResult(success=False, data=None, error=f"IMAP error: {e}")
        except smtplib.SMTPException as e:
            return ToolResult(success=False, data=None, error=f"SMTP error: {e}")
        except Exception as e:
            logger.exception("Email tool error")
            return ToolResult(success=False, data=None, error=f"Email error: {e}")

    # ── IMAP Operations ───────────────────────────────────────────

    def _connect_imap(self) -> imaplib.IMAP4_SSL:
        """Connect and authenticate to the IMAP server."""
        imap = imaplib.IMAP4_SSL(self._imap_host, self._imap_port)
        imap.login(self._username, self._password)
        return imap

    def _fetch_emails(self, imap: imaplib.IMAP4_SSL, email_ids: list[bytes], limit: int) -> list[dict]:
        """Fetch and parse a list of email IDs."""
        emails = []
        # Take the most recent ones (IDs are in ascending order)
        ids_to_fetch = email_ids[-limit:] if len(email_ids) > limit else email_ids

        for i, eid in enumerate(reversed(ids_to_fetch), 1):
            _, msg_data = imap.fetch(eid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            body = _extract_body(msg)
            # Truncate long bodies to save LLM context space
            if len(body) > 500:
                body = body[:500] + "... [truncated]"

            emails.append({
                "number": i,
                "from": _decode_header_value(msg.get("From", "")),
                "to": _decode_header_value(msg.get("To", "")),
                "subject": _decode_header_value(msg.get("Subject", "")),
                "date": msg.get("Date", ""),
                "body_preview": body,
            })

        return emails

    async def _read_inbox(self, limit: int = 5, unread_only: bool = False) -> ToolResult:
        """Read recent emails from the inbox."""
        imap = self._connect_imap()
        try:
            imap.select("INBOX")

            criteria = "UNSEEN" if unread_only else "ALL"
            _, data = imap.search(None, criteria)
            email_ids = data[0].split()

            if not email_ids:
                msg = "No unread emails." if unread_only else "Inbox is empty."
                return ToolResult(success=True, data={"emails": [], "message": msg})

            emails = self._fetch_emails(imap, email_ids, limit)
            return ToolResult(
                success=True,
                data={
                    "count": len(emails),
                    "showing": f"{'unread' if unread_only else 'recent'} {len(emails)} of {len(email_ids)} total",
                    "emails": emails,
                },
            )
        finally:
            imap.logout()

    async def _search(self, query: str, limit: int = 5) -> ToolResult:
        """Search emails by keyword, sender, or subject."""
        imap = self._connect_imap()
        try:
            imap.select("INBOX")

            # Build IMAP search criteria
            # Support common patterns: from:, subject:, or plain text
            if query.startswith("from:"):
                criteria = f'FROM "{query[5:].strip()}"'
            elif query.startswith("subject:"):
                criteria = f'SUBJECT "{query[8:].strip()}"'
            else:
                criteria = f'TEXT "{query}"'

            _, data = imap.search(None, criteria)
            email_ids = data[0].split()

            if not email_ids:
                return ToolResult(success=True, data={"emails": [], "message": f"No emails found matching '{query}'"})

            emails = self._fetch_emails(imap, email_ids, limit)
            return ToolResult(
                success=True,
                data={
                    "query": query,
                    "count": len(emails),
                    "total_matches": len(email_ids),
                    "emails": emails,
                },
            )
        finally:
            imap.logout()

    # ── SMTP Operations ───────────────────────────────────────────

    async def _send(self, to: str, subject: str, body: str) -> ToolResult:
        """Send a new email."""
        msg = MIMEMultipart()
        msg["From"] = self._username
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
            server.starttls()
            server.login(self._username, self._password)
            server.send_message(msg)

        logger.info(f"Email sent to {to}: {subject}")
        return ToolResult(
            success=True,
            data={"message": f"Email sent successfully to {to}", "subject": subject},
        )

    async def _reply(self, email_number: int, body: str) -> ToolResult:
        """Reply to an email by its number from the most recent inbox listing."""
        # First, fetch the original email to get the reply-to address and subject
        imap = self._connect_imap()
        try:
            imap.select("INBOX")
            _, data = imap.search(None, "ALL")
            email_ids = data[0].split()

            if not email_ids:
                return ToolResult(success=False, data=None, error="Inbox is empty")

            # Get the email by number (1-indexed, most recent first)
            recent_ids = list(reversed(email_ids[-10:]))  # Last 10 emails
            if email_number < 1 or email_number > len(recent_ids):
                return ToolResult(success=False, data=None, error=f"Email number {email_number} is out of range (1-{len(recent_ids)})")

            target_id = recent_ids[email_number - 1]
            _, msg_data = imap.fetch(target_id, "(RFC822)")
            raw_email = msg_data[0][1]
            original = email.message_from_bytes(raw_email)

            reply_to = original.get("Reply-To") or original.get("From", "")
            original_subject = _decode_header_value(original.get("Subject", ""))
            subject = f"Re: {original_subject}" if not original_subject.startswith("Re:") else original_subject

        finally:
            imap.logout()

        # Now send the reply
        return await self._send(reply_to, subject, body)
