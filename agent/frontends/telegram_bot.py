from __future__ import annotations

"""
Telegram bot frontend for the Navox Agent.

This is the public-facing frontend that makes the agent accessible to
everyone — no Python, no API keys, no terminal needed. Users interact
with the agent via Telegram, upload resumes as PDFs, paste LinkedIn URLs,
and get job matches in under 60 seconds.

Usage:
    python main.py --mode telegram

Requires TELEGRAM_BOT_TOKEN in .env (get one from @BotFather on Telegram).
"""

import logging
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ParseMode, ChatAction

from agent.users import UserSessionManager
from agent.profile.extract import (
    extract_pdf_text,
    extract_profile_from_url,
    detect_profile_input_type,
    extract_url_from_text,
)
from agent.frontends.rate_limiter import RateLimiter
from agent.frontends.formatters import (
    format_welcome_message,
    format_help_message,
    format_profile_preview,
    format_viral_share,
    format_rate_limit_message,
)

logger = logging.getLogger(__name__)

# Max PDF size: 10 MB
MAX_PDF_SIZE = 10 * 1024 * 1024

# Telegram message length limit
MAX_MESSAGE_LENGTH = 4096


class TelegramBot:
    """
    Telegram frontend for the Navox Agent.

    Mirrors the CLI frontend pattern: receives messages, calls
    brain.process(), returns responses. Adds Telegram-specific
    features: PDF upload handling, inline keyboards, onboarding flow.
    """

    def __init__(
        self,
        token: str,
        session_manager: UserSessionManager,
        rate_limit: int = 20,
    ):
        self._token = token
        self._sessions = session_manager
        self._rate_limiter = RateLimiter(max_per_user=rate_limit, window_seconds=3600)
        self._data_dir = session_manager._data_dir
        # Track users who are in the middle of pasting their LinkedIn cookie
        self._awaiting_cookie: set[str] = set()

    async def start(self):
        """Build and start the Telegram bot application."""
        app = Application.builder().token(self._token).build()

        # Command handlers
        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("profile", self._handle_profile))
        app.add_handler(CommandHandler("match", self._handle_match))
        app.add_handler(CommandHandler("help", self._handle_help))
        app.add_handler(CommandHandler("connect_linkedin", self._handle_connect_linkedin))
        app.add_handler(CommandHandler("disconnect_linkedin", self._handle_disconnect_linkedin))

        # Document handler (PDF uploads)
        app.add_handler(MessageHandler(
            filters.Document.PDF, self._handle_pdf_upload
        ))

        # Inline keyboard callbacks
        app.add_handler(CallbackQueryHandler(self._handle_callback))

        # Text message handler (catch-all — must be last)
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._handle_message
        ))

        logger.info("Telegram bot starting...")
        async with app:
            await app.start()
            await app.updater.start_polling()
            logger.info("Telegram bot is running. Press Ctrl+C to stop.")

            # Keep running until stopped
            try:
                # Block forever (until cancelled)
                import asyncio
                stop_event = asyncio.Event()
                await stop_event.wait()
            except asyncio.CancelledError:
                pass
            finally:
                await app.updater.stop()
                await app.stop()

    # ── Command Handlers ──────────────────────────────────────────

    async def _handle_start(self, update: Update, context) -> None:
        """
        /start — Onboarding flow.

        Designed for < 60 seconds to first value:
        1. Welcome message
        2. Inline keyboard with profile setup options
        """
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Upload Resume (PDF)", callback_data="onboard_pdf")],
            [InlineKeyboardButton("Paste LinkedIn URL", callback_data="onboard_linkedin")],
            [InlineKeyboardButton("Paste Navox Card URL", callback_data="onboard_navox")],
            [InlineKeyboardButton("Describe yourself", callback_data="onboard_text")],
        ])

        await update.message.reply_text(
            format_welcome_message(),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )

    async def _handle_profile(self, update: Update, context) -> None:
        """/profile — View current profile."""
        user_id = str(update.effective_user.id)
        brain = await self._sessions.get_brain(user_id)

        response = await brain.process(
            user_message="Show me my current profile.",
            context={"frontend": "telegram", "user_id": user_id},
        )

        await self._send_response(update.message, response)

    async def _handle_match(self, update: Update, context) -> None:
        """/match — Trigger a job search."""
        user_id = str(update.effective_user.id)

        if not self._rate_limiter.check(user_id):
            await update.message.reply_text(format_rate_limit_message(3600))
            return

        await update.message.chat.send_action(ChatAction.TYPING)

        brain = await self._sessions.get_brain(user_id)
        response = await brain.process(
            user_message="Search for jobs that match my profile and show me the top matches.",
            context={"frontend": "telegram", "user_id": user_id},
        )

        # Append viral share CTA
        bot_username = (await context.bot.get_me()).username
        response += format_viral_share(bot_username)

        await self._send_response(update.message, response)

    async def _handle_help(self, update: Update, context) -> None:
        """/help — Show usage instructions."""
        await update.message.reply_text(
            format_help_message(),
            parse_mode=ParseMode.HTML,
        )

    # ── LinkedIn Connection ────────────────────────────────────────

    async def _handle_connect_linkedin(self, update: Update, context) -> None:
        """
        /connect_linkedin — Start the LinkedIn authentication flow.

        Sends instructions for getting the li_at cookie and waits
        for the user to paste it.
        """
        user_id = str(update.effective_user.id)
        self._awaiting_cookie.add(user_id)

        await update.message.reply_text(
            "To connect your LinkedIn account, I need your session cookie.\n\n"
            "<b>How to get it:</b>\n"
            "1. Open LinkedIn in Chrome/Firefox\n"
            "2. Press F12 (or right-click and Inspect)\n"
            "3. Go to Application tab (Chrome) or Storage tab (Firefox)\n"
            "4. Click Cookies \u2192 linkedin.com\n"
            "5. Find the cookie named <b>li_at</b>\n"
            "6. Copy its Value and paste it here\n\n"
            "This lets me search LinkedIn on your behalf and find jobs "
            "where you have connections.\n\n"
            "Send /cancel to abort.",
            parse_mode=ParseMode.HTML,
        )

    async def _handle_disconnect_linkedin(self, update: Update, context) -> None:
        """/disconnect_linkedin — Remove stored LinkedIn cookie."""
        user_id = str(update.effective_user.id)
        profile_store = self._sessions.get_profile_store(user_id)
        if profile_store:
            profile_store.clear_linkedin_cookie()
        await update.message.reply_text(
            "LinkedIn disconnected. Your cookie has been removed.\n"
            "Job searches will fall back to Google results."
        )

    async def _handle_linkedin_cookie(self, update: Update, user_id: str, text: str) -> None:
        """Process a pasted LinkedIn cookie."""
        self._awaiting_cookie.discard(user_id)

        if text.lower() == "/cancel":
            await update.message.reply_text("LinkedIn connection cancelled.")
            return

        # Basic validation: li_at cookies are long alphanumeric strings
        cookie = text.strip()
        if len(cookie) < 50:
            await update.message.reply_text(
                "That doesn't look like a valid LinkedIn cookie. "
                "The li_at value is usually 150+ characters long.\n\n"
                "Try again with /connect_linkedin or send /cancel."
            )
            return

        await update.message.chat.send_action(ChatAction.TYPING)

        # Store and rebuild session
        await self._sessions.reconnect_linkedin(user_id, cookie)

        await update.message.reply_text(
            "LinkedIn connected! I can now search for jobs where "
            "you have 2nd-degree connections who can refer you.\n\n"
            "Try /match to find connection-filtered jobs."
        )

    # ── Message Handlers ──────────────────────────────────────────

    async def _handle_message(self, update: Update, context) -> None:
        """
        Handle text messages.

        Routes based on content:
        - LinkedIn URL → profile extraction
        - Navox URL → profile extraction
        - Everything else → brain.process()
        """
        user_id = str(update.effective_user.id)
        text = update.message.text.strip()

        if not text:
            return

        # Check if user is pasting a LinkedIn cookie
        if user_id in self._awaiting_cookie:
            await self._handle_linkedin_cookie(update, user_id, text)
            return

        # Rate limit check
        if not self._rate_limiter.check(user_id):
            await update.message.reply_text(format_rate_limit_message(3600))
            return

        # Detect profile input type
        input_type = detect_profile_input_type(text)

        if input_type == "linkedin_url":
            await self._handle_linkedin_url(update, user_id, text)
            return
        elif input_type == "navox_url":
            await self._handle_navox_url(update, user_id, text)
            return

        # General message — send to brain
        await update.message.chat.send_action(ChatAction.TYPING)

        brain = await self._sessions.get_brain(user_id)
        response = await brain.process(
            user_message=text,
            context={"frontend": "telegram", "user_id": user_id},
        )

        await self._send_response(update.message, response)

    async def _handle_pdf_upload(self, update: Update, context) -> None:
        """
        Handle resume PDF uploads.

        1. Validate file size
        2. Download from Telegram servers
        3. Extract text with PyPDF2
        4. Store as profile
        5. Show profile preview for confirmation
        """
        user_id = str(update.effective_user.id)
        document = update.message.document

        # Validate size
        if document.file_size and document.file_size > MAX_PDF_SIZE:
            await update.message.reply_text(
                "That PDF is too large (max 10 MB). "
                "Try a smaller file or describe yourself in a message."
            )
            return

        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            # Download from Telegram
            file = await document.get_file()
            user_dir = os.path.join(self._data_dir, user_id, "uploads")
            os.makedirs(user_dir, exist_ok=True)
            pdf_path = os.path.join(user_dir, "resume.pdf")
            await file.download_to_drive(pdf_path)

            # Extract text
            profile_text = extract_pdf_text(pdf_path)

            if not profile_text.strip():
                await update.message.reply_text(
                    "I couldn't extract text from that PDF. "
                    "It might be image-based. Try pasting your LinkedIn URL "
                    "or describing yourself in a message."
                )
                return

            # Store in user's profile
            brain = await self._sessions.get_brain(user_id)
            profile_store = self._sessions.get_profile_store(user_id)
            if profile_store:
                await profile_store.set_profile_from_text(profile_text)
                await profile_store.set_resume_path(pdf_path)

            # Show preview
            await update.message.reply_text(
                format_profile_preview(profile_text),
                parse_mode=ParseMode.HTML,
            )

        except Exception as e:
            logger.exception("PDF upload error for user %s", user_id)
            await update.message.reply_text(
                f"Sorry, I had trouble reading that PDF. Error: {e}\n\n"
                "Try pasting your LinkedIn URL or describing yourself in a message."
            )

    # ── URL Handlers ──────────────────────────────────────────────

    async def _handle_linkedin_url(self, update: Update, user_id: str, text: str) -> None:
        """Handle a LinkedIn profile URL."""
        await update.message.chat.send_action(ChatAction.TYPING)

        url = extract_url_from_text(text)
        if not url:
            await update.message.reply_text(
                "I couldn't find a valid LinkedIn URL in your message. "
                "Try pasting the full URL (e.g., linkedin.com/in/yourname)."
            )
            return

        brain = await self._sessions.get_brain(user_id)

        # Route through the brain so the LLM handles extraction naturally
        response = await brain.process(
            user_message=f"Load my profile from this LinkedIn URL: {url}",
            context={"frontend": "telegram", "user_id": user_id},
        )

        await self._send_response(update.message, response)

    async def _handle_navox_url(self, update: Update, user_id: str, text: str) -> None:
        """Handle a Navox profileCard URL."""
        await update.message.chat.send_action(ChatAction.TYPING)

        url = extract_url_from_text(text)
        if not url:
            await update.message.reply_text(
                "I couldn't find a valid Navox URL in your message. "
                "Try pasting the full URL (e.g., navox.tech/card/yourname)."
            )
            return

        brain = await self._sessions.get_brain(user_id)

        response = await brain.process(
            user_message=f"Load my profile from this Navox profileCard: {url}",
            context={"frontend": "telegram", "user_id": user_id},
        )

        await self._send_response(update.message, response)

    # ── Callback Handlers ─────────────────────────────────────────

    async def _handle_callback(self, update: Update, context) -> None:
        """Handle inline keyboard button presses."""
        query = update.callback_query
        await query.answer()

        data = query.data

        if data == "onboard_pdf":
            await query.message.reply_text(
                "Send me your resume as a PDF file. "
                "I'll extract your skills and experience automatically."
            )
        elif data == "onboard_linkedin":
            await query.message.reply_text(
                "Paste your LinkedIn profile URL.\n\n"
                "Example: linkedin.com/in/yourname"
            )
        elif data == "onboard_navox":
            await query.message.reply_text(
                "Paste your Navox profileCard URL.\n\n"
                "Example: navox.tech/card/yourname\n\n"
                "Don't have one? Create it at navox.tech"
            )
        elif data == "onboard_text":
            await query.message.reply_text(
                "Tell me about yourself in a message. Include:\n\n"
                "\u2022 Your current role and title\n"
                "\u2022 Years of experience\n"
                "\u2022 Key skills and technologies\n"
                "\u2022 What roles you're looking for\n"
                "\u2022 Preferred locations (or remote)\n\n"
                "Example: \"I'm a senior ML engineer with 5 years of experience "
                "in Python, PyTorch, and MLOps. Looking for roles in Toronto or remote.\""
            )

    # ── Utilities ─────────────────────────────────────────────────

    async def _send_response(self, message, text: str) -> None:
        """
        Send a response, splitting if it exceeds Telegram's 4096 char limit.

        Falls back to plain text if HTML parsing fails.
        """
        # Split into chunks if needed
        chunks = self._split_message(text)

        for chunk in chunks:
            try:
                await message.reply_text(chunk, parse_mode=ParseMode.HTML)
            except Exception:
                # Fall back to plain text if HTML parsing fails
                await message.reply_text(chunk)

    @staticmethod
    def _split_message(text: str) -> list[str]:
        """Split a message into chunks that fit Telegram's size limit."""
        if len(text) <= MAX_MESSAGE_LENGTH:
            return [text]

        chunks = []
        while text:
            if len(text) <= MAX_MESSAGE_LENGTH:
                chunks.append(text)
                break

            # Find a good split point (newline or space)
            split_at = text.rfind("\n", 0, MAX_MESSAGE_LENGTH)
            if split_at == -1:
                split_at = text.rfind(" ", 0, MAX_MESSAGE_LENGTH)
            if split_at == -1:
                split_at = MAX_MESSAGE_LENGTH

            chunks.append(text[:split_at])
            text = text[split_at:].lstrip()

        return chunks
