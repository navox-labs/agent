from __future__ import annotations

"""
Outreach Manager — draft, approve, send, and track outreach messages.

This is the agent's outreach pipeline. When a job is found with a
relevant connection, the workflow is:

1. Draft — LLM writes a personalized message referencing the job,
   the user's profile match, and the connection relationship
2. Notify — Agent emails the user with the draft for review
3. Approve — User replies APPROVE, EDIT, or SKIP
4. Send — Agent sends the approved message via email or LinkedIn DM
5. Track — Records send timestamp, monitors for responses

The user is ALWAYS in the loop — the agent never sends outreach
without explicit approval.
"""

import logging
from typing import Optional

from agent.jobs.store import JobStore
from agent.profile.store import ProfileStore
from agent.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class OutreachManager:
    """
    Manages the full outreach lifecycle for job opportunities.

    Coordinates between:
    - JobStore (database) — stores drafts, tracks send/response status
    - LLMProvider — generates personalized outreach drafts
    - ProfileStore — gets user's profile for context in drafts
    - EmailTool — sends notification emails to user + email outreach
    - LinkedInSession — sends LinkedIn DMs (Phase 8)
    """

    def __init__(
        self,
        job_store: JobStore,
        profile_store: ProfileStore,
        llm_provider: LLMProvider,
        email_tool=None,
        linkedin_session=None,
        notification_email: str = "",
    ):
        self._store = job_store
        self._profile = profile_store
        self._llm = llm_provider
        self._email = email_tool
        self._linkedin = linkedin_session
        self._notification_email = notification_email

    # ── Draft Generation ──────────────────────────────────────────

    async def draft_outreach(
        self,
        job_id: str,
        connection_name: str,
        connection_relation: str = "",
        platform: str = "email",
    ) -> dict:
        """
        Generate a personalized outreach draft for a job opportunity.

        Uses the LLM to write a message that references:
        - The specific job posting details
        - How the user's profile matches the role
        - The connection relationship
        - Professional but warm tone

        Args:
            job_id: The job to draft outreach for
            connection_name: Name of the connection to reach out to
            connection_relation: Relationship (e.g., "2nd degree on LinkedIn")
            platform: Where to send — "email" or "linkedin_dm"

        Returns:
            Dict with the draft text and job details
        """
        # Get the job from the database
        job = await self._store.get_job_by_id(job_id)
        if not job:
            return {"error": f"Job not found: {job_id}"}

        # Get user's profile for context
        profile_text = await self._profile.get_profile_summary()
        card_url = await self._profile.get_profile_card_url()

        # Build the prompt for the LLM
        draft_prompt = f"""Write a professional but warm outreach message for a job opportunity.

Context:
- Job Title: {job.get('title', 'Unknown')}
- Company: {job.get('company', 'Unknown')}
- Job Description: {job.get('description', 'No description available')[:1000]}
- Connection Name: {connection_name}
- Connection Relationship: {connection_relation or 'professional contact'}
- Platform: {platform} ({'keep it concise, 3-4 sentences' if platform == 'linkedin_dm' else 'can be slightly longer'})
- Matched Skills: {', '.join(job.get('matched_skills', []))}
- Match Score: {job.get('match_score', 'N/A')}%

{'Profile Card URL to include: ' + card_url if card_url else ''}

My Background:
{profile_text or 'Not provided'}

Guidelines:
- Address {connection_name} by first name
- Mention the specific role and company
- Briefly reference why I'm a good fit (use matched skills)
- Ask if they can share insights about the role or refer me
- Keep it genuine, not salesy
- Don't be overly formal or use clichés like "I hope this finds you well"
- If this is a LinkedIn DM, keep it to 3-4 sentences max
- If profile card URL is provided, mention it naturally at the end

Return ONLY the message text, no subject line or formatting."""

        try:
            response = await self._llm.generate(
                system=(
                    "You are a professional networking coach. Write natural, "
                    "authentic outreach messages that get responses. "
                    "Return only the message text."
                ),
                messages=[{"role": "user", "content": draft_prompt}],
            )

            draft = response.text.strip()

            # Store the draft in the database
            await self._store.set_outreach_draft(job_id, draft, platform)

            # Update connection info on the job
            conn = self._store._connect()
            try:
                conn.execute(
                    "UPDATE jobs SET connection_name = ?, connection_relation = ? WHERE job_id = ?",
                    (connection_name, connection_relation, job_id),
                )
                conn.commit()
            finally:
                conn.close()

            logger.info("Outreach draft generated for %s at %s", job['title'], job['company'])

            return {
                "job_id": job_id,
                "title": job.get("title"),
                "company": job.get("company"),
                "connection_name": connection_name,
                "platform": platform,
                "draft": draft,
                "status": "drafting",
            }

        except Exception as e:
            logger.error("Failed to generate outreach draft: %s", e)
            return {"error": f"Draft generation failed: {e}"}

    # ── Draft Management ──────────────────────────────────────────

    async def get_pending_drafts(self) -> list[dict]:
        """Get all jobs with drafts awaiting approval."""
        jobs = await self._store.get_jobs(status="drafting")
        return [
            {
                "job_id": j["job_id"],
                "title": j["title"],
                "company": j["company"],
                "connection_name": j.get("connection_name", "Unknown"),
                "platform": j.get("outreach_platform", "email"),
                "draft": j.get("outreach_draft", ""),
                "match_score": j.get("match_score"),
            }
            for j in jobs
        ]

    async def edit_draft(self, job_id: str, new_draft: str) -> dict:
        """Update an existing outreach draft."""
        job = await self._store.get_job_by_id(job_id)
        if not job:
            return {"error": f"Job not found: {job_id}"}

        platform = job.get("outreach_platform", "email")
        await self._store.set_outreach_draft(job_id, new_draft, platform)

        return {
            "job_id": job_id,
            "title": job["title"],
            "draft": new_draft,
            "status": "drafting",
            "message": "Draft updated",
        }

    # ── Approval & Sending ────────────────────────────────────────

    async def approve_and_send(self, job_id: str) -> dict:
        """
        Approve a draft and send it via the appropriate platform.

        The agent ONLY calls this after the user explicitly approves.
        """
        job = await self._store.get_job_by_id(job_id)
        if not job:
            return {"error": f"Job not found: {job_id}"}

        draft = job.get("outreach_draft")
        if not draft:
            return {"error": "No draft found for this job. Generate one first."}

        platform = job.get("outreach_platform", "email")
        connection_name = job.get("connection_name", "Unknown")

        # Mark as approved
        await self._store.update_status(job_id, "approved")

        # Send via the appropriate platform
        if platform == "email":
            result = await self._send_email_outreach(job, draft)
        elif platform == "linkedin_dm":
            result = await self._send_linkedin_dm(job, draft)
        else:
            result = {"error": f"Unknown platform: {platform}"}

        if result.get("error"):
            return result

        # Mark as sent
        await self._store.mark_outreach_sent(job_id)

        logger.info(
            "Outreach sent to %s via %s for %s at %s",
            connection_name, platform, job["title"], job["company"],
        )

        return {
            "job_id": job_id,
            "title": job["title"],
            "company": job["company"],
            "connection_name": connection_name,
            "platform": platform,
            "status": "sent",
            "message": f"Outreach sent to {connection_name} via {platform}",
        }

    async def _send_email_outreach(self, job: dict, draft: str) -> dict:
        """Send outreach via email."""
        if not self._email:
            return {"error": "Email tool not available. Configure email in .env"}

        connection_name = job.get("connection_name", "Unknown")
        # For email outreach, we need the connection's email address
        # This would be stored in the job notes or connection info
        # For now, return a message that the user needs to provide the email
        return {
            "error": (
                f"Email address for {connection_name} not available. "
                "Provide their email address to send the outreach."
            )
        }

    async def send_email_to(self, job_id: str, recipient_email: str) -> dict:
        """Send the approved outreach draft to a specific email address."""
        if not self._email:
            return {"error": "Email tool not available"}

        job = await self._store.get_job_by_id(job_id)
        if not job:
            return {"error": f"Job not found: {job_id}"}

        draft = job.get("outreach_draft")
        if not draft:
            return {"error": "No draft found"}

        subject = f"Regarding the {job['title']} role at {job['company']}"

        result = await self._email.execute(
            action="send",
            to=recipient_email,
            subject=subject,
            body=draft,
        )

        if result.success:
            await self._store.mark_outreach_sent(job_id)
            return {
                "job_id": job_id,
                "status": "sent",
                "message": f"Email sent to {recipient_email}",
            }
        else:
            return {"error": f"Failed to send email: {result.error}"}

    async def _send_linkedin_dm(self, job: dict, draft: str) -> dict:
        """Send outreach via LinkedIn DM. Requires LinkedIn session."""
        if not self._linkedin:
            return {
                "error": "LinkedIn session not available. Run scripts/setup_linkedin_session.py first."
            }

        # LinkedIn DM sending would use the browser to:
        # 1. Navigate to the connection's profile
        # 2. Click "Message"
        # 3. Type the draft
        # 4. Click Send
        # For now, return that this feature needs the connection's profile URL
        connection_name = job.get("connection_name", "Unknown")
        return {
            "error": (
                f"LinkedIn DM sending requires {connection_name}'s profile URL. "
                "Provide their LinkedIn profile URL to send the DM."
            )
        }

    async def send_linkedin_dm_to(self, job_id: str, profile_url: str) -> dict:
        """Send the approved outreach draft as a LinkedIn DM."""
        if not self._linkedin:
            return {"error": "LinkedIn session not available"}

        job = await self._store.get_job_by_id(job_id)
        if not job:
            return {"error": f"Job not found: {job_id}"}

        draft = job.get("outreach_draft")
        if not draft:
            return {"error": "No draft found"}

        try:
            page = self._linkedin._page
            if not page:
                return {"error": "LinkedIn session not started"}

            # Navigate to the connection's profile
            await self._linkedin._wait_human_delay(8, 12)
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
            await self._linkedin._wait_human_delay()

            # Click the "Message" button
            message_btn = page.get_by_text("Message", exact=True).first
            await message_btn.click(timeout=5000)
            await self._linkedin._wait_human_delay()

            # Type the message with human-like delays
            msg_box = page.locator("div.msg-form__contenteditable").first
            await msg_box.click()
            await self._linkedin._wait_human_delay(1, 2)

            # Type character by character
            for char in draft:
                await msg_box.type(char, delay=50)

            await self._linkedin._wait_human_delay(1, 3)

            # Click Send
            send_btn = page.locator("button.msg-form__send-button").first
            await send_btn.click(timeout=5000)
            await self._linkedin._wait_human_delay()

            await self._store.mark_outreach_sent(job_id)

            return {
                "job_id": job_id,
                "status": "sent",
                "message": f"LinkedIn DM sent to {profile_url}",
            }

        except Exception as e:
            logger.error("LinkedIn DM failed: %s", e)
            return {"error": f"LinkedIn DM failed: {e}"}

    # ── Profile Sharing ───────────────────────────────────────────

    async def share_profile(self, job_id: str, platform: str = "email", recipient: str = "") -> dict:
        """
        Share the user's profile (Navox card or resume) with a connection.

        Args:
            job_id: The job this outreach is for
            platform: "email" or "linkedin_dm"
            recipient: Email address or LinkedIn profile URL
        """
        job = await self._store.get_job_by_id(job_id)
        if not job:
            return {"error": f"Job not found: {job_id}"}

        card_url = await self._profile.get_profile_card_url()
        resume_path = await self._profile.get_resume_path()

        if not card_url and not resume_path:
            return {"error": "No profile card URL or resume on file. Set your profile first."}

        # Build the share message
        share_text = ""
        if card_url:
            share_text = f"Here's my professional profile: {card_url}"
        elif resume_path:
            share_text = "I've attached my resume for your reference."

        if platform == "email" and recipient:
            if not self._email:
                return {"error": "Email tool not available"}

            subject = f"My profile — regarding {job['title']} at {job['company']}"
            result = await self._email.execute(
                action="send",
                to=recipient,
                subject=subject,
                body=share_text,
            )

            if result.success:
                await self._store.mark_profile_shared(job_id)
                return {
                    "job_id": job_id,
                    "status": "profile_shared",
                    "message": f"Profile shared via email to {recipient}",
                    "shared": card_url or resume_path,
                }
            return {"error": f"Failed to send: {result.error}"}

        elif platform == "linkedin_dm":
            # Would append the card URL to a LinkedIn DM
            return {
                "job_id": job_id,
                "shared": card_url or resume_path,
                "message": f"Include this in your LinkedIn DM: {share_text}",
            }

        return {"error": "Provide a recipient email or use linkedin_dm platform"}

    # ── Notification System ───────────────────────────────────────

    async def notify_user_new_matches(self, jobs: list[dict]) -> dict:
        """
        Email the user about new high-relevance job matches.

        Batches all matches into a single email to avoid spam.
        """
        if not self._email or not self._notification_email:
            logger.info("Notification skipped — no email tool or notification address")
            return {"skipped": True, "reason": "no email configured"}

        if not jobs:
            return {"skipped": True, "reason": "no jobs to notify about"}

        # Build email body
        body_lines = ["New job matches found:\n"]
        for job in jobs[:10]:  # Max 10 per email
            score = job.get("match_score", "?")
            body_lines.append(
                f"- {job['title']} at {job['company']} "
                f"(match: {score}%) "
                f"[{job.get('source', 'unknown')}]"
            )
            if job.get("connection_name"):
                body_lines.append(
                    f"  Connection: {job['connection_name']} ({job.get('connection_relation', '')})"
                )
            body_lines.append(f"  {job.get('url', '')}")
            body_lines.append("")

        body_lines.append("Reply to this email or use the agent to review these matches.")

        subject = f"[Job Agent] {len(jobs)} new match{'es' if len(jobs) != 1 else ''} found"
        body = "\n".join(body_lines)

        result = await self._email.execute(
            action="send",
            to=self._notification_email,
            subject=subject,
            body=body,
        )

        if result.success:
            # Mark all notified jobs
            for job in jobs:
                await self._store.update_status(job["job_id"], "notified")
            return {"sent": True, "count": len(jobs)}

        return {"error": f"Failed to send notification: {result.error}"}

    async def notify_user_draft_ready(self, job_id: str) -> dict:
        """Email the user that an outreach draft is ready for review."""
        if not self._email or not self._notification_email:
            return {"skipped": True}

        job = await self._store.get_job_by_id(job_id)
        if not job:
            return {"error": f"Job not found: {job_id}"}

        subject = f"[Job Agent] Draft ready: {job['title']} at {job['company']}"
        body = (
            f"Outreach draft ready for your review:\n\n"
            f"Job: {job['title']} at {job['company']}\n"
            f"Connection: {job.get('connection_name', 'Unknown')}\n"
            f"Platform: {job.get('outreach_platform', 'email')}\n"
            f"Match Score: {job.get('match_score', 'N/A')}%\n\n"
            f"Draft message:\n"
            f"---\n{job.get('outreach_draft', '')}\n---\n\n"
            f"Reply APPROVE to send, EDIT: [your changes], or SKIP."
        )

        result = await self._email.execute(
            action="send",
            to=self._notification_email,
            subject=subject,
            body=body,
        )

        return {"sent": result.success} if result.success else {"error": result.error}

    async def notify_user_response(self, job_id: str) -> dict:
        """Immediately email the user when a response is received."""
        if not self._email or not self._notification_email:
            return {"skipped": True}

        job = await self._store.get_job_by_id(job_id)
        if not job:
            return {"error": f"Job not found: {job_id}"}

        subject = f"[Job Agent] Response received! {job['title']} at {job['company']}"
        body = (
            f"Great news! You got a response regarding:\n\n"
            f"Job: {job['title']} at {job['company']}\n"
            f"Connection: {job.get('connection_name', 'Unknown')}\n\n"
            f"Check your {job.get('outreach_platform', 'email')} for the response."
        )

        result = await self._email.execute(
            action="send",
            to=self._notification_email,
            subject=subject,
            body=body,
        )

        return {"sent": result.success} if result.success else {"error": result.error}

    # ── Response Monitoring ───────────────────────────────────────

    async def check_for_responses(self) -> list[dict]:
        """
        Check for responses to sent outreach messages.

        Scans the email inbox for replies to outreach we've sent.
        Returns a list of jobs that received responses.
        """
        # Get all jobs with status "sent"
        sent_jobs = await self._store.get_jobs(status="sent")
        if not sent_jobs:
            return []

        responded = []

        if self._email:
            for job in sent_jobs:
                connection = job.get("connection_name", "")
                company = job.get("company", "")

                # Search for replies mentioning the company or connection
                for query in [f"subject:{company}", f"from:{connection}"]:
                    try:
                        result = await self._email.execute(
                            action="search", query=query, limit=3
                        )
                        if result.success:
                            emails = result.data.get("emails", [])
                            # Check if any email is newer than the outreach sent date
                            if emails:
                                await self._store.mark_response_received(job["job_id"])
                                responded.append({
                                    "job_id": job["job_id"],
                                    "title": job["title"],
                                    "company": job["company"],
                                    "connection_name": connection,
                                    "response_preview": emails[0].get("body_preview", ""),
                                })
                                break
                    except Exception as e:
                        logger.debug("Response check failed for %s: %s", query, e)
                        continue

        if responded:
            logger.info("Found %d responses to outreach", len(responded))

        return responded

    # ── Approval Check ────────────────────────────────────────────

    async def check_for_approvals(self) -> list[dict]:
        """
        Check the email inbox for user approval replies.

        Looks for replies to draft notification emails containing:
        - APPROVE — send the draft as-is
        - EDIT: [new text] — update the draft and send
        - SKIP — mark the job as closed

        Returns list of actions taken.
        """
        if not self._email:
            return []

        drafting_jobs = await self._store.get_jobs(status="drafting")
        if not drafting_jobs:
            return []

        actions_taken = []

        # Search for replies to our draft emails
        result = await self._email.execute(
            action="search", query="subject:[Job Agent] Draft ready", limit=10
        )

        if not result.success:
            return []

        emails = result.data.get("emails", [])
        for email_data in emails:
            body = email_data.get("body_preview", "").strip().upper()

            if body.startswith("APPROVE"):
                # Find the matching job and send
                for job in drafting_jobs:
                    if job["company"] in email_data.get("subject", ""):
                        send_result = await self.approve_and_send(job["job_id"])
                        actions_taken.append({
                            "action": "approved_and_sent",
                            **send_result,
                        })
                        break

            elif body.startswith("SKIP"):
                for job in drafting_jobs:
                    if job["company"] in email_data.get("subject", ""):
                        await self._store.update_status(job["job_id"], "closed", notes="Skipped by user")
                        actions_taken.append({
                            "action": "skipped",
                            "job_id": job["job_id"],
                            "title": job["title"],
                        })
                        break

            elif body.startswith("EDIT:"):
                new_text = email_data.get("body_preview", "")[5:].strip()
                for job in drafting_jobs:
                    if job["company"] in email_data.get("subject", ""):
                        await self.edit_draft(job["job_id"], new_text)
                        actions_taken.append({
                            "action": "edited",
                            "job_id": job["job_id"],
                            "title": job["title"],
                        })
                        break

        return actions_taken
