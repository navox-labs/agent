from __future__ import annotations

"""
Job Scanner — unified multi-source job discovery.

This is the brain of the job search pipeline. It coordinates scanning
across multiple sources:

1. LinkedIn Jobs — search by keywords, location, connection degree
2. LinkedIn Feed — scroll feed for #hiring posts from your network
3. Indeed — search the largest job board
4. Email Inbox — find recruiter emails and job alert notifications
5. Google Search — fallback search for jobs on any site

After discovering raw job listings, each one gets:
- Scored against the user's profile (via JobMatcher from Phase 7)
- Deduped and stored in the job database (via JobStore from Phase 7)
- Connection info attached if available

The scanner is source-agnostic — adding a new source means adding one
method and plugging it into scan_all().
"""

import hashlib
import logging
from typing import Optional
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from agent.jobs.email_finder import extract_hiring_info
from agent.jobs.linkedin_session import LinkedInSession
from agent.jobs.matcher import JobMatcher
from agent.jobs.store import JobStore
from agent.profile.store import ProfileStore

logger = logging.getLogger(__name__)


class JobScanner:
    """
    Unified scanner that searches multiple sources for job listings.

    Each source method returns raw job dicts. The scanner then:
    1. Deduplicates (using job_id = hash of URL or title+company)
    2. Scores each job against the user's profile
    3. Stores results in the job database
    """

    def __init__(
        self,
        job_store: JobStore,
        job_matcher: JobMatcher,
        profile_store: ProfileStore,
        linkedin_session: Optional[LinkedInSession] = None,
        browser_tool=None,
        email_tool=None,
    ):
        self._store = job_store
        self._matcher = job_matcher
        self._profile = profile_store
        self._linkedin = linkedin_session
        self._browser = browser_tool
        self._email = email_tool

    # ── Unified Scan ──────────────────────────────────────────────

    async def scan_all(
        self,
        keywords: str,
        location: str = "",
        sources: list[str] = None,
    ) -> dict:
        """
        Scan all available sources for matching jobs.

        Args:
            keywords: Job search keywords (e.g., "ML Engineer")
            location: Location filter (e.g., "Toronto")
            sources: Which sources to scan. Default: all available.
                     Options: "linkedin", "indeed", "email", "google"

        Returns:
            Summary dict with total found, new jobs saved, and per-source counts.
        """
        available_sources = sources or ["linkedin", "indeed", "email", "google"]
        results = {"total_found": 0, "new_jobs": 0, "by_source": {}}

        # Check for recent scan to avoid hammering sources
        for source in available_sources:
            recent = await self._store.get_recent_scan(source, keywords, hours=4)
            if recent:
                logger.info(
                    "Skipping %s scan — already scanned '%s' %d hours ago (%d results)",
                    source, keywords,
                    4, recent["results_found"],
                )
                results["by_source"][source] = {
                    "status": "skipped",
                    "reason": "scanned recently",
                    "last_results": recent["results_found"],
                }
                continue

            # Run the source-specific scanner
            raw_jobs = await self._scan_source(source, keywords, location)
            scored_jobs = await self._score_and_store(raw_jobs, source)

            results["total_found"] += len(raw_jobs)
            results["new_jobs"] += scored_jobs["new_count"]
            results["by_source"][source] = {
                "status": "scanned",
                "found": len(raw_jobs),
                "new": scored_jobs["new_count"],
                "top_score": scored_jobs["top_score"],
            }

            # Log the scan
            await self._store.log_scan(
                source=source,
                query=keywords,
                results_found=len(raw_jobs),
                new_jobs=scored_jobs["new_count"],
            )

        return results

    async def _scan_source(
        self, source: str, keywords: str, location: str
    ) -> list[dict]:
        """Dispatch to the appropriate source scanner."""
        if source == "linkedin":
            return await self.scan_linkedin(keywords, location)
        elif source == "indeed":
            return await self.scan_indeed(keywords, location)
        elif source == "email":
            return await self.scan_email_inbox(keywords)
        elif source == "google":
            return await self.scan_google_jobs(keywords, location)
        else:
            logger.warning("Unknown source: %s", source)
            return []

    # ── LinkedIn ──────────────────────────────────────────────────

    async def scan_linkedin(self, keywords: str, location: str = "") -> list[dict]:
        """
        Search LinkedIn Jobs. Requires a logged-in LinkedIn session.

        When a session is available, runs TWO searches:
        1. 2nd-degree connection filter — jobs where you have connections
        2. Unfiltered — all matching jobs

        Falls back to Google search if no LinkedIn session is available.
        """
        if not self._linkedin:
            logger.info("No LinkedIn session — falling back to Google search for LinkedIn jobs")
            return await self._search_linkedin_via_google(keywords, location)

        try:
            # Check if session is still logged in
            logged_in = await self._linkedin.is_logged_in()
            if not logged_in:
                logger.warning("LinkedIn session expired — reconnect via /connect_linkedin")
                return await self._search_linkedin_via_google(keywords, location)

            all_jobs = []
            seen_urls = set()

            # Search 1: 2nd-degree connections (most actionable)
            logger.info("Searching LinkedIn with 2nd-degree connection filter")
            connection_jobs = await self._linkedin.search_jobs(
                keywords=keywords,
                location=location,
                connection_filter="2nd",
            )
            for job in connection_jobs:
                job.setdefault("connection_relation", "2nd degree")
                url = job.get("url", "")
                if url:
                    seen_urls.add(url)
                all_jobs.append(job)

            # Search 2: All results (no filter)
            logger.info("Searching LinkedIn (all results)")
            general_jobs = await self._linkedin.search_jobs(
                keywords=keywords,
                location=location,
            )
            for job in general_jobs:
                url = job.get("url", "")
                if url and url not in seen_urls:
                    all_jobs.append(job)
                    seen_urls.add(url)

            logger.info(
                "LinkedIn scan: %d connection jobs + %d general = %d total",
                len(connection_jobs), len(general_jobs), len(all_jobs),
            )
            return all_jobs

        except Exception as e:
            logger.error("LinkedIn scan failed: %s", e)
            return []

    async def scan_linkedin_feed(self, keywords: list[str] = None) -> list[dict]:
        """Scan LinkedIn feed for job-related posts. Requires LinkedIn session."""
        if not self._linkedin:
            logger.info("No LinkedIn session available for feed scanning")
            return []

        try:
            return await self._linkedin.scan_feed(job_keywords=keywords)
        except Exception as e:
            logger.error("LinkedIn feed scan failed: %s", e)
            return []

    async def _search_linkedin_via_google(
        self, keywords: str, location: str
    ) -> list[dict]:
        """
        Fallback: search for LinkedIn job posts via Google.

        This works without a LinkedIn session but returns fewer results.
        """
        if not self._browser:
            return []

        query = f"site:linkedin.com/jobs {keywords}"
        if location:
            query += f" {location}"

        try:
            result = await self._browser.execute(action="search", query=query)
            if not result.success:
                return []

            # Parse Google results for LinkedIn job links
            return self._parse_google_job_results(
                result.data.get("results", ""), "linkedin"
            )
        except Exception as e:
            logger.error("Google LinkedIn fallback failed: %s", e)
            return []

    # ── Indeed ────────────────────────────────────────────────────

    async def scan_indeed(self, keywords: str, location: str = "") -> list[dict]:
        """
        Search Indeed for job listings via browser.

        Indeed is more bot-friendly than LinkedIn — no login needed,
        and the HTML structure is more predictable.
        """
        if not self._browser:
            logger.info("No browser available for Indeed scanning")
            return []

        url = f"https://www.indeed.com/jobs?q={quote_plus(keywords)}"
        if location:
            url += f"&l={quote_plus(location)}"

        try:
            result = await self._browser.execute(action="navigate", url=url)
            if not result.success:
                return []

            page_text = result.data.get("content", "") if isinstance(result.data, dict) else ""

            # Navigate and get HTML for parsing
            html_result = await self._browser.execute(action="get_links")
            links = html_result.data.get("links", []) if html_result.success else []

            jobs = []
            for link in links:
                link_text = link.get("text", "")
                link_url = link.get("url", "")

                # Indeed job links typically contain the job title
                # and link to /viewjob or /rc/clk
                if "/viewjob" in link_url or "/rc/clk" in link_url or "/pagead/" in link_url:
                    if link_text and len(link_text) > 5:
                        if not link_url.startswith("http"):
                            link_url = f"https://www.indeed.com{link_url}"
                        jobs.append({
                            "title": link_text,
                            "company": "Unknown",  # Will be extracted from detail page
                            "url": link_url,
                            "source": "indeed",
                        })

            # Also try to extract from page text
            if not jobs:
                jobs = self._parse_indeed_text(page_text)

            logger.info("Found %d jobs on Indeed", len(jobs))
            return jobs[:15]

        except Exception as e:
            logger.error("Indeed scan failed: %s", e)
            return []

    def _parse_indeed_text(self, text: str) -> list[dict]:
        """Parse Indeed page text as a fallback when HTML parsing fails."""
        jobs = []
        lines = text.strip().splitlines()

        for i, line in enumerate(lines):
            line = line.strip()
            # Indeed listings typically have a job title followed by company name
            # Look for lines that seem like job titles (reasonable length, capitalized)
            if 10 < len(line) < 100 and not line.startswith(("http", "Sign", "Post", "Find")):
                # Check if the next line could be a company name
                company = lines[i + 1].strip() if i + 1 < len(lines) else "Unknown"
                if len(company) > 50:
                    company = "Unknown"

                jobs.append({
                    "title": line,
                    "company": company,
                    "url": "",
                    "source": "indeed",
                })

        return jobs[:10]

    # ── Email Inbox ───────────────────────────────────────────────

    async def scan_email_inbox(self, keywords: str = "") -> list[dict]:
        """
        Search email inbox for recruiter messages and job alerts.

        Looks for:
        - Emails from known recruiter domains
        - Subject lines containing job-related keywords
        - Job alert notification emails
        """
        if not self._email:
            logger.info("No email tool available for inbox scanning")
            return []

        jobs = []

        # Search patterns for job-related emails
        search_queries = [
            "subject:opportunity",
            "subject:position",
            "subject:hiring",
            "subject:job alert",
            "subject:new jobs",
        ]

        if keywords:
            search_queries.append(f"subject:{keywords}")

        for query in search_queries:
            try:
                result = await self._email.execute(
                    action="search", query=query, limit=5
                )
                if not result.success:
                    continue

                emails = result.data.get("emails", [])
                for email_data in emails:
                    subject = email_data.get("subject", "")
                    body = email_data.get("body_preview", "")
                    sender = email_data.get("from", "")

                    jobs.append({
                        "title": subject,
                        "company": sender,
                        "description": body[:500],
                        "url": "",  # Emails don't have direct job URLs
                        "source": "email",
                        "raw_email": {
                            "from": sender,
                            "subject": subject,
                            "date": email_data.get("date", ""),
                        },
                    })
            except Exception as e:
                logger.debug("Email search '%s' failed: %s", query, e)
                continue

        # Deduplicate by subject
        seen = set()
        unique_jobs = []
        for job in jobs:
            key = job["title"].lower().strip()
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)

        logger.info("Found %d job-related emails", len(unique_jobs))
        return unique_jobs[:15]

    # ── Google Fallback ───────────────────────────────────────────

    async def scan_google_jobs(self, keywords: str, location: str = "") -> list[dict]:
        """
        Search Google for job postings as a fallback source.

        This catches jobs on company career pages, smaller job boards,
        and any site that Google indexes.
        """
        if not self._browser:
            logger.info("No browser available for Google job search")
            return []

        query = f"{keywords} jobs"
        if location:
            query += f" {location}"

        try:
            result = await self._browser.execute(action="search", query=query)
            if not result.success:
                return []

            return self._parse_google_job_results(
                result.data.get("results", ""), "google"
            )
        except Exception as e:
            logger.error("Google job search failed: %s", e)
            return []

    def _parse_google_job_results(self, text: str, source: str) -> list[dict]:
        """Parse Google search results text into job listings."""
        jobs = []
        lines = text.strip().splitlines()

        for line in lines:
            line = line.strip()
            # Look for lines that look like job titles
            # Google results often have "Title - Company" format
            if " - " in line and 10 < len(line) < 150:
                parts = line.split(" - ", 1)
                title = parts[0].strip()
                company = parts[1].strip() if len(parts) > 1 else "Unknown"

                # Skip navigation/UI text
                skip_words = ["sign in", "create", "about", "help", "privacy", "terms"]
                if any(w in title.lower() for w in skip_words):
                    continue

                jobs.append({
                    "title": title,
                    "company": company,
                    "url": "",
                    "source": source,
                })

        return jobs[:10]

    # ── Scoring & Storage ─────────────────────────────────────────

    async def _score_and_store(self, raw_jobs: list[dict], source: str) -> dict:
        """
        Score each job against the user's profile and store in the database.

        Returns a summary dict with new_count and top_score.
        """
        profile_text = await self._profile.get_profile_summary()

        new_count = 0
        top_score = 0

        for raw_job in raw_jobs:
            # Generate a unique job_id
            job_id = self._generate_job_id(raw_job)
            raw_job["job_id"] = job_id

            # Set defaults
            raw_job.setdefault("source", source)
            raw_job.setdefault("company", "Unknown")
            raw_job.setdefault("title", "Unknown Position")
            raw_job.setdefault("url", "")

            # Score against profile if we have both profile and job description
            if profile_text and raw_job.get("description"):
                try:
                    analysis = await self._matcher.analyze_match(
                        job_description=raw_job["description"],
                        profile_text=profile_text,
                    )
                    raw_job["match_score"] = analysis.match_score
                    raw_job["matched_skills"] = analysis.matched_skills
                    raw_job["missing_skills"] = analysis.missing_skills
                    raw_job["gap_analysis"] = analysis.gap_analysis
                    raw_job["resume_tailoring"] = analysis.resume_tailoring
                except Exception as e:
                    logger.warning("Scoring failed for %s: %s", raw_job["title"], e)

            # Extract hiring manager email if we have a name or can find one
            if raw_job.get("hiring_manager_name") or raw_job.get("source") == "linkedin":
                hiring_info = extract_hiring_info(
                    hiring_manager_name=raw_job.get("hiring_manager_name"),
                    company=raw_job.get("company", ""),
                    job_url=raw_job.get("url", ""),
                )
                if hiring_info.get("hiring_manager_emails"):
                    raw_job["hiring_manager_email"] = hiring_info["hiring_manager_emails"][0]

            # Store in database (dedup handled by INSERT OR IGNORE)
            is_new = await self._store.save_job(raw_job)
            if is_new:
                new_count += 1

            score = raw_job.get("match_score", 0) or 0
            if score > top_score:
                top_score = score

        return {"new_count": new_count, "top_score": top_score}

    def _generate_job_id(self, job: dict) -> str:
        """Generate a unique ID for deduplication."""
        # Prefer URL-based ID (most reliable)
        if job.get("url"):
            return hashlib.md5(job["url"].encode()).hexdigest()[:16]

        # Fallback: hash of title + company
        key = f"{job.get('title', '')}-{job.get('company', '')}".lower()
        return hashlib.md5(key.encode()).hexdigest()[:16]

    # ── Single Job Details ────────────────────────────────────────

    async def get_job_details(self, job_url: str) -> dict:
        """
        Fetch the full description of a specific job.

        Routes to the appropriate source based on the URL.
        """
        if "linkedin.com" in job_url and self._linkedin:
            return await self._linkedin.get_job_details(job_url)
        elif self._browser:
            # Generic browser fetch for any job URL
            result = await self._browser.execute(action="navigate", url=job_url)
            if result.success:
                return {
                    "description": result.data.get("content", ""),
                    "title": result.data.get("title", "Unknown"),
                    "url": job_url,
                }
            return {"error": result.error, "url": job_url}
        else:
            return {"error": "No browser available", "url": job_url}
