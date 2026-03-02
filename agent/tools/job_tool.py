from __future__ import annotations

"""
Job Discovery Tool — the LLM's interface to the job search pipeline.

This tool lets the agent:
- Search for jobs across multiple sources (LinkedIn, Indeed, email, Google)
- Scan the LinkedIn feed for job-related posts
- Get full details for a specific job URL
- List and filter tracked jobs from the database
- Update job statuses in the pipeline
- View pipeline statistics

The tool delegates to the JobScanner for web operations and
JobStore for database operations.
"""

import json
import logging

from agent.tools.base import Tool, ToolParameter, ToolResult
from agent.jobs.scanner import JobScanner
from agent.jobs.store import JobStore

logger = logging.getLogger(__name__)


class JobTool(Tool):
    """Search, track, and manage job opportunities."""

    def __init__(self, scanner: JobScanner, job_store: JobStore):
        self._scanner = scanner
        self._store = job_store

    @property
    def name(self) -> str:
        return "jobs"

    @property
    def description(self) -> str:
        return (
            "Search for jobs and manage your job pipeline. "
            "Actions: search_jobs (search across LinkedIn, Indeed, email, Google), "
            "scan_feed (scan LinkedIn feed for job posts from your network), "
            "get_job_details (get full description for a specific job URL), "
            "list_jobs (show tracked jobs filtered by status/source/score), "
            "update_status (change a job's pipeline status), "
            "job_stats (summary of your job pipeline)."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                "action", "string",
                "The job action to perform",
                enum=[
                    "search_jobs", "scan_feed", "get_job_details",
                    "list_jobs", "update_status", "job_stats",
                ],
            ),
            ToolParameter(
                "keywords", "string",
                "Job search keywords (e.g., 'ML Engineer') — used with search_jobs and scan_feed",
                required=False,
            ),
            ToolParameter(
                "location", "string",
                "Location filter (e.g., 'Toronto') — used with search_jobs",
                required=False,
            ),
            ToolParameter(
                "sources", "string",
                "Comma-separated list of sources to search (linkedin,indeed,email,google) — used with search_jobs. Default: all available",
                required=False,
            ),
            ToolParameter(
                "url", "string",
                "Job URL to get details for — used with get_job_details",
                required=False,
            ),
            ToolParameter(
                "status", "string",
                "Filter or set job status — used with list_jobs and update_status. "
                "Values: new, notified, drafting, approved, sent, responded, closed",
                required=False,
            ),
            ToolParameter(
                "source", "string",
                "Filter by source — used with list_jobs. Values: linkedin, indeed, email, google",
                required=False,
            ),
            ToolParameter(
                "min_score", "integer",
                "Minimum match score filter (0-100) — used with list_jobs",
                required=False,
            ),
            ToolParameter(
                "job_id", "string",
                "Job ID — used with update_status",
                required=False,
            ),
            ToolParameter(
                "notes", "string",
                "Notes to attach — used with update_status",
                required=False,
            ),
            ToolParameter(
                "limit", "integer",
                "Maximum results to return (default: 10) — used with list_jobs",
                required=False,
            ),
        ]

    async def execute(self, action: str, **kwargs) -> ToolResult:
        try:
            if action == "search_jobs":
                return await self._search_jobs(**kwargs)
            elif action == "scan_feed":
                return await self._scan_feed(**kwargs)
            elif action == "get_job_details":
                return await self._get_job_details(**kwargs)
            elif action == "list_jobs":
                return await self._list_jobs(**kwargs)
            elif action == "update_status":
                return await self._update_status(**kwargs)
            elif action == "job_stats":
                return await self._job_stats()
            else:
                return ToolResult(success=False, data=None, error=f"Unknown action: {action}")
        except Exception as e:
            logger.exception("Job tool error")
            return ToolResult(success=False, data=None, error=f"Job tool error: {e}")

    # ── Actions ────────────────────────────────────────────────────

    async def _search_jobs(self, **kwargs) -> ToolResult:
        """Search for jobs across multiple sources."""
        keywords = kwargs.get("keywords", "")
        if not keywords:
            return ToolResult(
                success=False, data=None,
                error="'keywords' is required for search_jobs (e.g., 'ML Engineer')",
            )

        location = kwargs.get("location", "")
        sources_str = kwargs.get("sources", "")
        sources = [s.strip() for s in sources_str.split(",")] if sources_str else None

        results = await self._scanner.scan_all(
            keywords=keywords,
            location=location,
            sources=sources,
        )

        return ToolResult(
            success=True,
            data={
                "message": f"Scanned for '{keywords}'" + (f" in {location}" if location else ""),
                "total_found": results["total_found"],
                "new_jobs_saved": results["new_jobs"],
                "by_source": results["by_source"],
            },
        )

    async def _scan_feed(self, **kwargs) -> ToolResult:
        """Scan LinkedIn feed for job-related posts."""
        keywords_str = kwargs.get("keywords", "")
        keywords = [k.strip() for k in keywords_str.split(",")] if keywords_str else None

        posts = await self._scanner.scan_linkedin_feed(keywords=keywords)

        if not posts:
            return ToolResult(
                success=True,
                data={
                    "message": "No job-related posts found in LinkedIn feed. "
                    "Make sure LinkedIn session is set up (run scripts/setup_linkedin_session.py).",
                    "posts": [],
                },
            )

        return ToolResult(
            success=True,
            data={
                "message": f"Found {len(posts)} job-related posts in LinkedIn feed",
                "posts": posts,
            },
        )

    async def _get_job_details(self, **kwargs) -> ToolResult:
        """Get full description for a specific job URL."""
        url = kwargs.get("url", "")
        if not url:
            return ToolResult(
                success=False, data=None,
                error="'url' is required for get_job_details",
            )

        details = await self._scanner.get_job_details(url)

        if details.get("error"):
            return ToolResult(
                success=False, data=None,
                error=f"Failed to get job details: {details['error']}",
            )

        return ToolResult(success=True, data=details)

    async def _list_jobs(self, **kwargs) -> ToolResult:
        """List tracked jobs with optional filters."""
        status = kwargs.get("status")
        source = kwargs.get("source")
        min_score = kwargs.get("min_score")
        limit = kwargs.get("limit", 10)

        jobs = await self._store.get_jobs(
            status=status,
            source=source,
            min_score=min_score,
            limit=limit,
        )

        if not jobs:
            filters = []
            if status:
                filters.append(f"status={status}")
            if source:
                filters.append(f"source={source}")
            if min_score:
                filters.append(f"min_score={min_score}")
            filter_desc = ", ".join(filters) if filters else "none"

            return ToolResult(
                success=True,
                data={
                    "message": f"No jobs found (filters: {filter_desc}). Try searching first with search_jobs.",
                    "jobs": [],
                    "count": 0,
                },
            )

        # Format jobs for display
        formatted = []
        for job in jobs:
            formatted.append({
                "job_id": job.get("job_id", ""),
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "source": job.get("source", ""),
                "match_score": job.get("match_score"),
                "matched_skills": job.get("matched_skills", []),
                "missing_skills": job.get("missing_skills", []),
                "status": job.get("status", "new"),
                "connection_name": job.get("connection_name"),
                "discovered_at": job.get("discovered_at", ""),
            })

        return ToolResult(
            success=True,
            data={
                "count": len(formatted),
                "jobs": formatted,
            },
        )

    async def _update_status(self, **kwargs) -> ToolResult:
        """Update a job's pipeline status."""
        job_id = kwargs.get("job_id", "")
        status = kwargs.get("status", "")

        if not job_id or not status:
            return ToolResult(
                success=False, data=None,
                error="'job_id' and 'status' are required for update_status",
            )

        valid_statuses = ["new", "notified", "drafting", "approved", "sent", "responded", "closed"]
        if status not in valid_statuses:
            return ToolResult(
                success=False, data=None,
                error=f"Invalid status '{status}'. Valid: {', '.join(valid_statuses)}",
            )

        # Verify job exists
        job = await self._store.get_job_by_id(job_id)
        if not job:
            return ToolResult(
                success=False, data=None,
                error=f"No job found with ID '{job_id}'",
            )

        notes = kwargs.get("notes")
        await self._store.update_status(job_id, status, notes)

        return ToolResult(
            success=True,
            data={
                "message": f"Job '{job['title']}' status updated to '{status}'",
                "job_id": job_id,
                "previous_status": job.get("status"),
                "new_status": status,
            },
        )

    async def _job_stats(self) -> ToolResult:
        """Get pipeline statistics."""
        stats = await self._store.get_stats()

        return ToolResult(
            success=True,
            data={
                "total_jobs": stats["total_jobs"],
                "average_match_score": stats["average_match_score"],
                "by_status": stats["by_status"],
            },
        )
