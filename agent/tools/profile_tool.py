from __future__ import annotations

"""
Profile Tool — manage the user's professional profile for job matching.

This tool lets the LLM manage the user's profile data:
- Set profile from a Navox profileCard URL (fetched via browser)
- Set profile from a resume PDF (text extracted with PyPDF2)
- View the stored profile summary
- Get the profileCard URL for sharing with connections
- Set job search preferences (target roles, locations, industries)

The profile is the foundation of the job matching engine — every job
gets scored against this data.
"""

import logging
import os

from agent.tools.base import Tool, ToolParameter, ToolResult
from agent.profile.store import ProfileStore
from agent.jobs.matcher import JobMatcher

logger = logging.getLogger(__name__)


class ProfileTool(Tool):
    """Manage the user's professional profile for job matching."""

    def __init__(self, profile_store: ProfileStore, browser_tool=None, llm_provider=None):
        """
        Args:
            profile_store: ProfileStore instance for persisting profile data
            browser_tool: Optional BrowserTool for fetching Navox profileCards
            llm_provider: Optional LLMProvider for extracting profile text from raw HTML
        """
        self._store = profile_store
        self._browser = browser_tool
        self._llm = llm_provider

    @property
    def name(self) -> str:
        return "profile"

    @property
    def description(self) -> str:
        return (
            "Manage the user's professional profile for job matching. "
            "Actions: set_profile (from a Navox profileCard URL or resume file path), "
            "view_profile (show stored profile summary), "
            "get_profile_link (get the Navox profileCard URL for sharing), "
            "set_preferences (set job search preferences like target roles and locations)."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                "action", "string",
                "The profile action to perform",
                enum=["set_profile", "view_profile", "get_profile_link", "set_preferences"],
            ),
            ToolParameter(
                "url", "string",
                "Navox profileCard URL (e.g., navox.tech/card/jsmith) — used with 'set_profile' action",
                required=False,
            ),
            ToolParameter(
                "file_path", "string",
                "Path to a resume PDF file — used with 'set_profile' action",
                required=False,
            ),
            ToolParameter(
                "profile_text", "string",
                "Raw profile text to store directly — used with 'set_profile' action when user describes themselves",
                required=False,
            ),
            ToolParameter(
                "preferences", "string",
                "JSON string of job preferences — used with 'set_preferences' action. "
                "Example: {\"target_roles\": [\"ML Engineer\"], \"locations\": [\"Toronto\", \"Remote\"]}",
                required=False,
            ),
        ]

    async def execute(self, action: str, **kwargs) -> ToolResult:
        try:
            if action == "set_profile":
                return await self._set_profile(**kwargs)
            elif action == "view_profile":
                return await self._view_profile()
            elif action == "get_profile_link":
                return await self._get_profile_link()
            elif action == "set_preferences":
                return await self._set_preferences(**kwargs)
            else:
                return ToolResult(success=False, data=None, error=f"Unknown action: {action}")
        except Exception as e:
            logger.exception("Profile tool error")
            return ToolResult(success=False, data=None, error=f"Profile error: {e}")

    # ── Actions ────────────────────────────────────────────────────

    async def _set_profile(self, **kwargs) -> ToolResult:
        """Set the user's profile from a URL, file, or raw text."""
        url = kwargs.get("url")
        file_path = kwargs.get("file_path")
        profile_text = kwargs.get("profile_text")

        if url:
            return await self._set_profile_from_url(url)
        elif file_path:
            return await self._set_profile_from_file(file_path)
        elif profile_text:
            await self._store.set_profile_from_text(profile_text)
            return ToolResult(
                success=True,
                data={"message": "Profile stored from text input.", "length": len(profile_text)},
            )
        else:
            return ToolResult(
                success=False,
                data=None,
                error="Provide a 'url' (Navox profileCard), 'file_path' (resume PDF), or 'profile_text' (raw text).",
            )

    async def _set_profile_from_url(self, url: str) -> ToolResult:
        """Fetch a Navox profileCard URL via browser and extract profile text."""
        if not self._browser:
            return ToolResult(
                success=False,
                data=None,
                error="Browser tool not available. Cannot fetch profileCard URL.",
            )

        # Normalize URL — add https:// if missing
        if not url.startswith("http"):
            url = f"https://{url}"

        # Navigate to the profileCard page
        nav_result = await self._browser.execute(action="navigate", url=url)
        if not nav_result.success:
            return ToolResult(
                success=False,
                data=None,
                error=f"Failed to fetch profileCard: {nav_result.error}",
            )

        page_text = nav_result.data.get("text", "") if isinstance(nav_result.data, dict) else str(nav_result.data)

        if not page_text or len(page_text.strip()) < 50:
            return ToolResult(
                success=False,
                data=None,
                error="ProfileCard page returned too little text. The page may not have loaded correctly.",
            )

        # If we have an LLM, use it to clean up the extracted text into a structured profile
        if self._llm:
            try:
                response = await self._llm.generate(
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
                profile_text = response.text
            except Exception as e:
                logger.warning("LLM extraction failed, using raw text: %s", e)
                profile_text = page_text
        else:
            profile_text = page_text

        # Store the profile text and card URL
        await self._store.set_profile_from_text(profile_text)
        await self._store.set_profile_card_url(url)

        return ToolResult(
            success=True,
            data={
                "message": f"Profile loaded from {url}",
                "profile_preview": profile_text[:300] + "..." if len(profile_text) > 300 else profile_text,
                "card_url": url,
            },
        )

    async def _set_profile_from_file(self, file_path: str) -> ToolResult:
        """Extract text from a resume PDF and store it."""
        if not os.path.exists(file_path):
            return ToolResult(
                success=False,
                data=None,
                error=f"File not found: {file_path}",
            )

        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".pdf":
            try:
                import PyPDF2
            except ImportError:
                return ToolResult(
                    success=False,
                    data=None,
                    error="PyPDF2 is not installed. Run: pip install PyPDF2",
                )

            try:
                text_parts = []
                with open(file_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text_parts.append(page_text)

                profile_text = "\n".join(text_parts)

                if not profile_text.strip():
                    return ToolResult(
                        success=False,
                        data=None,
                        error="Could not extract text from PDF. The file may be image-based.",
                    )

            except Exception as e:
                return ToolResult(
                    success=False,
                    data=None,
                    error=f"Failed to read PDF: {e}",
                )

        elif ext == ".txt":
            with open(file_path, "r") as f:
                profile_text = f.read()
        else:
            return ToolResult(
                success=False,
                data=None,
                error=f"Unsupported file type: {ext}. Use .pdf or .txt",
            )

        # Store profile text and file path
        await self._store.set_profile_from_text(profile_text)
        await self._store.set_resume_path(file_path)

        return ToolResult(
            success=True,
            data={
                "message": f"Profile loaded from {os.path.basename(file_path)}",
                "pages": len(text_parts) if ext == ".pdf" else 1,
                "length": len(profile_text),
                "profile_preview": profile_text[:300] + "..." if len(profile_text) > 300 else profile_text,
            },
        )

    async def _view_profile(self) -> ToolResult:
        """View the stored profile summary."""
        context = await self._store.get_full_context()

        if not context.get("profile_text"):
            return ToolResult(
                success=True,
                data={
                    "message": "No profile stored yet. Use 'set_profile' with a Navox profileCard URL, resume PDF, or text description.",
                    "has_profile": False,
                },
            )

        return ToolResult(
            success=True,
            data={
                "has_profile": True,
                "profile_text": context["profile_text"],
                "card_url": context.get("profile_card_url"),
                "resume_path": context.get("resume_path"),
                "job_preferences": context.get("job_preferences"),
            },
        )

    async def _get_profile_link(self) -> ToolResult:
        """Get the Navox profileCard URL for sharing."""
        card_url = await self._store.get_profile_card_url()
        resume_path = await self._store.get_resume_path()

        if not card_url and not resume_path:
            return ToolResult(
                success=True,
                data={
                    "message": "No profileCard URL or resume on file. Set your profile first.",
                    "has_shareable": False,
                },
            )

        return ToolResult(
            success=True,
            data={
                "has_shareable": True,
                "card_url": card_url,
                "resume_path": resume_path,
                "message": f"ProfileCard: {card_url}" if card_url else f"Resume: {resume_path}",
            },
        )

    async def _set_preferences(self, **kwargs) -> ToolResult:
        """Set job search preferences."""
        import json

        raw = kwargs.get("preferences", "")
        if not raw:
            return ToolResult(
                success=False,
                data=None,
                error="Provide 'preferences' as a JSON string with target_roles, locations, industries, etc.",
            )

        try:
            preferences = json.loads(raw)
        except json.JSONDecodeError as e:
            return ToolResult(
                success=False,
                data=None,
                error=f"Invalid JSON in preferences: {e}",
            )

        await self._store.set_job_preferences(preferences)
        return ToolResult(
            success=True,
            data={
                "message": "Job preferences saved.",
                "preferences": preferences,
            },
        )
