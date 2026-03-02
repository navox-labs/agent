from __future__ import annotations

"""
Agent Scheduler — runs the agent proactively on a schedule.

This is what makes the agent truly autonomous. Instead of waiting for
user input, the scheduler periodically triggers actions:

1. Job Scan Cycle (every 4 hours):
   - Search all sources for matching positions
   - Score each job against the user's profile
   - For high-relevance matches, draft outreach messages
   - Email the user a summary of findings

2. Response Check (every 30 minutes):
   - Check for replies to sent outreach
   - Immediately notify the user of any responses

3. Approval Check (every 15 minutes):
   - Check email for user's approval replies (APPROVE/EDIT/SKIP)
   - Process approved drafts and send outreach

The scheduler uses a simple asyncio loop instead of APScheduler
to keep dependencies minimal. Each cycle runs independently —
if one fails, the others continue.

Usage:
    python main.py --mode daemon     # Background scheduler only
    python main.py --mode both       # CLI + scheduler in parallel
"""

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Default intervals (in seconds)
SCAN_INTERVAL = 4 * 60 * 60      # 4 hours
RESPONSE_CHECK_INTERVAL = 30 * 60  # 30 minutes
APPROVAL_CHECK_INTERVAL = 15 * 60  # 15 minutes


class AgentScheduler:
    """
    Background scheduler for proactive agent actions.

    Runs three independent loops:
    - scan_cycle: discovers new jobs and notifies user
    - response_check: monitors for outreach responses
    - approval_check: processes user approval replies
    """

    def __init__(
        self,
        scanner=None,
        outreach_manager=None,
        profile_store=None,
        job_store=None,
        scan_interval: int = SCAN_INTERVAL,
        response_interval: int = RESPONSE_CHECK_INTERVAL,
        approval_interval: int = APPROVAL_CHECK_INTERVAL,
    ):
        self._scanner = scanner
        self._outreach = outreach_manager
        self._profile = profile_store
        self._store = job_store
        self._scan_interval = scan_interval
        self._response_interval = response_interval
        self._approval_interval = approval_interval
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self):
        """Start all scheduler loops."""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        logger.info("Agent scheduler starting...")
        logger.info("  Scan cycle: every %d hours", self._scan_interval // 3600)
        logger.info("  Response check: every %d minutes", self._response_interval // 60)
        logger.info("  Approval check: every %d minutes", self._approval_interval // 60)

        self._tasks = [
            asyncio.create_task(self._scan_loop()),
            asyncio.create_task(self._response_loop()),
            asyncio.create_task(self._approval_loop()),
        ]

        # Wait for all tasks (they run forever until stop() is called)
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("Scheduler stopped")

    async def stop(self):
        """Stop all scheduler loops."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks = []
        logger.info("Scheduler stopping...")

    # ── Scan Cycle ────────────────────────────────────────────────

    async def _scan_loop(self):
        """Periodically scan for new job opportunities."""
        # Small initial delay to let everything initialize
        await asyncio.sleep(5)

        while self._running:
            try:
                await self.run_scan_cycle()
            except Exception as e:
                logger.error("Scan cycle failed: %s", e)

            await asyncio.sleep(self._scan_interval)

    async def run_scan_cycle(self):
        """
        Run a single scan cycle:
        1. Get user's job preferences
        2. Search all sources
        3. Notify user of high-relevance matches
        """
        logger.info("Starting scan cycle at %s", datetime.now().isoformat())

        if not self._scanner or not self._profile:
            logger.warning("Scanner or profile not available — skipping scan")
            return

        # Check if user has a profile set
        has_profile = await self._profile.has_profile()
        if not has_profile:
            logger.info("No profile set — skipping scan. Set your profile first.")
            return

        # Get job preferences for search keywords
        preferences = await self._profile.get_job_preferences()
        if not preferences:
            logger.info("No job preferences set — skipping scan. Set preferences first.")
            return

        keywords_list = preferences.get("target_roles", [])
        locations = preferences.get("locations", [])

        if not keywords_list:
            logger.info("No target roles in preferences — skipping scan")
            return

        total_new = 0

        # Search for each role + location combination
        for keywords in keywords_list:
            for location in locations or [""]:
                try:
                    results = await self._scanner.scan_all(
                        keywords=keywords,
                        location=location,
                    )
                    total_new += results.get("new_jobs", 0)
                    logger.info(
                        "Scan '%s' in '%s': %d found, %d new",
                        keywords, location or "any",
                        results.get("total_found", 0),
                        results.get("new_jobs", 0),
                    )
                except Exception as e:
                    logger.error("Scan failed for '%s': %s", keywords, e)

        # Notify user about new high-relevance matches
        if total_new > 0 and self._outreach and self._store:
            new_jobs = await self._store.get_jobs(status="new", min_score=50)
            if new_jobs:
                await self._outreach.notify_user_new_matches(new_jobs)
                logger.info("Notified user about %d new matches", len(new_jobs))

        logger.info("Scan cycle complete: %d new jobs found", total_new)

    # ── Response Check ────────────────────────────────────────────

    async def _response_loop(self):
        """Periodically check for responses to sent outreach."""
        await asyncio.sleep(30)  # Initial delay

        while self._running:
            try:
                await self.run_response_check()
            except Exception as e:
                logger.error("Response check failed: %s", e)

            await asyncio.sleep(self._response_interval)

    async def run_response_check(self):
        """
        Check for responses to outreach we've sent.
        Immediately notifies the user of any responses.
        """
        if not self._outreach:
            return

        responses = await self._outreach.check_for_responses()

        for response in responses:
            logger.info(
                "Response received for %s at %s!",
                response.get("title"), response.get("company"),
            )
            # Notify user immediately
            await self._outreach.notify_user_response(response["job_id"])

    # ── Approval Check ────────────────────────────────────────────

    async def _approval_loop(self):
        """Periodically check for user approval replies."""
        await asyncio.sleep(60)  # Initial delay

        while self._running:
            try:
                await self.run_approval_check()
            except Exception as e:
                logger.error("Approval check failed: %s", e)

            await asyncio.sleep(self._approval_interval)

    async def run_approval_check(self):
        """
        Check email for user approval replies and process them.
        Handles APPROVE, EDIT, and SKIP responses.
        """
        if not self._outreach:
            return

        actions = await self._outreach.check_for_approvals()

        for action in actions:
            logger.info(
                "User action: %s for job %s",
                action.get("action"), action.get("job_id"),
            )
