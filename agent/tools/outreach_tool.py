from __future__ import annotations

"""
Outreach Tool — the LLM's interface to the outreach pipeline.

This tool lets the agent:
- Draft personalized outreach messages for job opportunities
- List pending drafts awaiting user approval
- Edit drafts before sending
- Approve and send outreach via email or LinkedIn DM
- Check for responses to sent outreach
- Share the user's profile/resume with connections

The user is ALWAYS in the loop — the agent never sends outreach
without explicit approval via the approve_draft action.
"""

import logging

from agent.tools.base import Tool, ToolParameter, ToolResult
from agent.jobs.outreach import OutreachManager

logger = logging.getLogger(__name__)


class OutreachTool(Tool):
    """Draft, review, send, and track outreach messages."""

    def __init__(self, outreach_manager: OutreachManager):
        self._outreach = outreach_manager

    @property
    def name(self) -> str:
        return "outreach"

    @property
    def description(self) -> str:
        return (
            "Manage outreach messages for job opportunities. "
            "Actions: draft_message (generate outreach for a job + connection), "
            "list_drafts (show pending drafts awaiting approval), "
            "edit_draft (modify a draft before sending), "
            "approve_draft (send the approved message — REQUIRES user approval first), "
            "send_to (send approved outreach to a specific email or LinkedIn profile), "
            "check_responses (scan for replies to sent outreach), "
            "share_profile (send resume/profileCard to a connection), "
            "notify_matches (email user about new job matches)."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                "action", "string",
                "The outreach action to perform",
                enum=[
                    "draft_message", "list_drafts", "edit_draft",
                    "approve_draft", "send_to", "check_responses",
                    "share_profile", "notify_matches",
                ],
            ),
            ToolParameter(
                "job_id", "string",
                "Job ID — used with draft_message, edit_draft, approve_draft, send_to, share_profile",
                required=False,
            ),
            ToolParameter(
                "connection_name", "string",
                "Name of the connection to reach out to — used with draft_message",
                required=False,
            ),
            ToolParameter(
                "connection_relation", "string",
                "Relationship description (e.g., '2nd degree on LinkedIn') — used with draft_message",
                required=False,
            ),
            ToolParameter(
                "platform", "string",
                "Outreach platform — 'email' or 'linkedin_dm'. Used with draft_message, send_to, share_profile",
                required=False,
            ),
            ToolParameter(
                "draft_text", "string",
                "New draft text — used with edit_draft",
                required=False,
            ),
            ToolParameter(
                "recipient", "string",
                "Email address or LinkedIn profile URL — used with send_to and share_profile",
                required=False,
            ),
        ]

    async def execute(self, action: str, **kwargs) -> ToolResult:
        try:
            if action == "draft_message":
                return await self._draft_message(**kwargs)
            elif action == "list_drafts":
                return await self._list_drafts()
            elif action == "edit_draft":
                return await self._edit_draft(**kwargs)
            elif action == "approve_draft":
                return await self._approve_draft(**kwargs)
            elif action == "send_to":
                return await self._send_to(**kwargs)
            elif action == "check_responses":
                return await self._check_responses()
            elif action == "share_profile":
                return await self._share_profile(**kwargs)
            elif action == "notify_matches":
                return await self._notify_matches(**kwargs)
            else:
                return ToolResult(success=False, data=None, error=f"Unknown action: {action}")
        except Exception as e:
            logger.exception("Outreach tool error")
            return ToolResult(success=False, data=None, error=f"Outreach error: {e}")

    # ── Actions ────────────────────────────────────────────────────

    async def _draft_message(self, **kwargs) -> ToolResult:
        """Generate an outreach draft for a job + connection."""
        job_id = kwargs.get("job_id", "")
        connection_name = kwargs.get("connection_name", "")

        if not job_id or not connection_name:
            return ToolResult(
                success=False, data=None,
                error="'job_id' and 'connection_name' are required for draft_message",
            )

        result = await self._outreach.draft_outreach(
            job_id=job_id,
            connection_name=connection_name,
            connection_relation=kwargs.get("connection_relation", ""),
            platform=kwargs.get("platform", "email"),
        )

        if result.get("error"):
            return ToolResult(success=False, data=None, error=result["error"])

        return ToolResult(
            success=True,
            data={
                "message": f"Draft created for {result['connection_name']} regarding {result['title']} at {result['company']}",
                **result,
            },
        )

    async def _list_drafts(self) -> ToolResult:
        """List all pending outreach drafts."""
        drafts = await self._outreach.get_pending_drafts()

        if not drafts:
            return ToolResult(
                success=True,
                data={
                    "message": "No pending drafts. Use draft_message to create one.",
                    "drafts": [],
                    "count": 0,
                },
            )

        return ToolResult(
            success=True,
            data={
                "count": len(drafts),
                "drafts": drafts,
            },
        )

    async def _edit_draft(self, **kwargs) -> ToolResult:
        """Edit an existing draft."""
        job_id = kwargs.get("job_id", "")
        draft_text = kwargs.get("draft_text", "")

        if not job_id or not draft_text:
            return ToolResult(
                success=False, data=None,
                error="'job_id' and 'draft_text' are required for edit_draft",
            )

        result = await self._outreach.edit_draft(job_id, draft_text)

        if result.get("error"):
            return ToolResult(success=False, data=None, error=result["error"])

        return ToolResult(success=True, data=result)

    async def _approve_draft(self, **kwargs) -> ToolResult:
        """Approve and send a draft. Only call after user explicitly approves."""
        job_id = kwargs.get("job_id", "")

        if not job_id:
            return ToolResult(
                success=False, data=None,
                error="'job_id' is required for approve_draft",
            )

        result = await self._outreach.approve_and_send(job_id)

        if result.get("error"):
            return ToolResult(success=False, data=None, error=result["error"])

        return ToolResult(success=True, data=result)

    async def _send_to(self, **kwargs) -> ToolResult:
        """Send approved outreach to a specific recipient."""
        job_id = kwargs.get("job_id", "")
        recipient = kwargs.get("recipient", "")
        platform = kwargs.get("platform", "email")

        if not job_id or not recipient:
            return ToolResult(
                success=False, data=None,
                error="'job_id' and 'recipient' are required for send_to",
            )

        if platform == "email":
            result = await self._outreach.send_email_to(job_id, recipient)
        elif platform == "linkedin_dm":
            result = await self._outreach.send_linkedin_dm_to(job_id, recipient)
        else:
            return ToolResult(
                success=False, data=None,
                error=f"Unknown platform: {platform}. Use 'email' or 'linkedin_dm'",
            )

        if result.get("error"):
            return ToolResult(success=False, data=None, error=result["error"])

        return ToolResult(success=True, data=result)

    async def _check_responses(self) -> ToolResult:
        """Check for responses to sent outreach."""
        responses = await self._outreach.check_for_responses()

        if not responses:
            return ToolResult(
                success=True,
                data={
                    "message": "No new responses found.",
                    "responses": [],
                    "count": 0,
                },
            )

        return ToolResult(
            success=True,
            data={
                "message": f"Found {len(responses)} response(s)!",
                "count": len(responses),
                "responses": responses,
            },
        )

    async def _share_profile(self, **kwargs) -> ToolResult:
        """Share the user's profile with a connection."""
        job_id = kwargs.get("job_id", "")
        platform = kwargs.get("platform", "email")
        recipient = kwargs.get("recipient", "")

        if not job_id:
            return ToolResult(
                success=False, data=None,
                error="'job_id' is required for share_profile",
            )

        result = await self._outreach.share_profile(
            job_id=job_id,
            platform=platform,
            recipient=recipient,
        )

        if result.get("error"):
            return ToolResult(success=False, data=None, error=result["error"])

        return ToolResult(success=True, data=result)

    async def _notify_matches(self, **kwargs) -> ToolResult:
        """Email the user about new job matches. Used internally by the scheduler."""
        # Get new (un-notified) jobs
        from agent.jobs.store import JobStore
        new_jobs = await self._outreach._store.get_jobs(status="new", min_score=50)

        if not new_jobs:
            return ToolResult(
                success=True,
                data={"message": "No new high-match jobs to notify about.", "count": 0},
            )

        result = await self._outreach.notify_user_new_matches(new_jobs)

        if result.get("error"):
            return ToolResult(success=False, data=None, error=result["error"])
        if result.get("skipped"):
            return ToolResult(
                success=True,
                data={"message": f"Notification skipped: {result.get('reason', 'unknown')}", "count": 0},
            )

        return ToolResult(
            success=True,
            data={
                "message": f"Notified user about {result['count']} new job matches",
                "count": result["count"],
            },
        )
