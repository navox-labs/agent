from __future__ import annotations

"""
LinkedIn Session — persistent browser session with anti-detection.

This is separate from the generic BrowserTool because LinkedIn needs:
1. Persistent cookies — so you stay logged in between sessions
2. Human-like browsing — random delays, realistic scrolling, typed input
3. Rate limiting — max N searches/hour, minimum delay between actions
4. Isolated context — LinkedIn session doesn't interfere with other browsing

How persistent sessions work:
- Playwright's launch_persistent_context() saves cookies, localStorage,
  and session data to a directory (data/linkedin_session/)
- First time: run scripts/setup_linkedin_session.py to manually log in
  in a visible browser. Your session is saved to disk.
- After that: every time we launch, the saved session is loaded automatically.
  No re-login needed (until the session expires, typically weeks).

Anti-detection:
- Realistic user-agent string
- --disable-blink-features=AutomationControlled hides Playwright fingerprints
- Random delays between actions (2-5s) to look human
- Typing with keystroke delays instead of instant paste
- Scrolling with random speed
"""

import asyncio
import logging
import os
import random
import time
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, BrowserContext, Page

logger = logging.getLogger(__name__)

# Rate limiting
MAX_SEARCHES_PER_HOUR = 5
MIN_ACTION_DELAY_SEC = 3
MAX_ACTION_DELAY_SEC = 7
MIN_PAGE_DELAY_SEC = 8
MAX_PAGE_DELAY_SEC = 15


class LinkedInSession:
    """
    Persistent browser session for LinkedIn with anti-detection.

    Usage:
        session = LinkedInSession(session_dir="data/linkedin_session")
        await session.start()
        results = await session.search_jobs("ML Engineer", "Toronto")
        await session.close()
    """

    def __init__(self, session_dir: str):
        """
        Args:
            session_dir: Directory to store persistent browser data (cookies, etc.)
        """
        self._session_dir = session_dir
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._last_action_time: float = 0
        self._search_count: int = 0
        self._search_hour_start: float = 0

    async def start(self, headless: bool = True):
        """
        Start the persistent browser session.

        Args:
            headless: True for background operation, False for visible browser
                      (use False during setup_linkedin_session.py)
        """
        os.makedirs(self._session_dir, exist_ok=True)

        self._playwright = await async_playwright().start()

        # launch_persistent_context saves all browser state to session_dir
        # This includes cookies, localStorage, sessionStorage — everything
        # needed to stay logged in.
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self._session_dir,
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/Toronto",
        )

        # Use the first page if one exists, otherwise create one
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        logger.info("LinkedIn session started (headless=%s)", headless)

    async def close(self):
        """Close the browser session (cookies are saved automatically)."""
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        self._context = None
        self._page = None
        self._playwright = None
        logger.info("LinkedIn session closed")

    # ── Rate Limiting ─────────────────────────────────────────────

    async def _wait_human_delay(self, min_sec: float = None, max_sec: float = None):
        """Wait a random human-like delay between actions."""
        min_s = min_sec or MIN_ACTION_DELAY_SEC
        max_s = max_sec or MAX_ACTION_DELAY_SEC
        delay = random.uniform(min_s, max_s)
        await asyncio.sleep(delay)
        self._last_action_time = time.time()

    def _check_rate_limit(self) -> bool:
        """Check if we've exceeded the search rate limit."""
        now = time.time()
        # Reset counter every hour
        if now - self._search_hour_start > 3600:
            self._search_count = 0
            self._search_hour_start = now

        if self._search_count >= MAX_SEARCHES_PER_HOUR:
            logger.warning("LinkedIn rate limit reached (%d searches/hour)", MAX_SEARCHES_PER_HOUR)
            return False
        return True

    # ── Human-like Input ──────────────────────────────────────────

    async def _type_like_human(self, selector: str, text: str):
        """Type text with random delays between keystrokes."""
        await self._page.click(selector)
        await asyncio.sleep(0.3)
        # Clear existing text first
        await self._page.fill(selector, "")
        await asyncio.sleep(0.2)
        # Type character by character with random delays
        for char in text:
            await self._page.type(selector, char, delay=random.randint(50, 150))

    async def _scroll_page(self, scrolls: int = 3):
        """Scroll down the page like a human would."""
        for _ in range(scrolls):
            scroll_amount = random.randint(300, 700)
            await self._page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(random.uniform(0.5, 1.5))

    # ── Login Check ───────────────────────────────────────────────

    async def is_logged_in(self) -> bool:
        """Check if the current session is logged into LinkedIn."""
        try:
            await self._page.goto(
                "https://www.linkedin.com/feed/",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            await asyncio.sleep(2)

            url = self._page.url
            # If redirected to login page, we're not logged in
            if "login" in url or "authwall" in url or "checkpoint" in url:
                return False

            # Check for feed content (logged-in indicator)
            feed = await self._page.query_selector(".feed-shared-update-v2")
            nav = await self._page.query_selector(".global-nav")
            return feed is not None or nav is not None
        except Exception as e:
            logger.error("Login check failed: %s", e)
            return False

    # ── Job Search ────────────────────────────────────────────────

    async def search_jobs(
        self,
        keywords: str,
        location: str = "",
        connection_filter: str = "",
    ) -> list[dict]:
        """
        Search LinkedIn Jobs and extract listings.

        Args:
            keywords: Job search keywords (e.g., "ML Engineer")
            location: Location filter (e.g., "Toronto, ON")
            connection_filter: "1st", "2nd", or "" for no filter

        Returns:
            List of job dicts with title, company, location, url, description_preview
        """
        if not self._check_rate_limit():
            return []

        # Build LinkedIn Jobs search URL
        from urllib.parse import quote_plus
        url = f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(keywords)}"

        if location:
            url += f"&location={quote_plus(location)}"

        # Connection degree filters
        # f_N=F = 1st connections, f_N=S = 2nd connections
        if connection_filter == "1st":
            url += "&f_N=F"
        elif connection_filter == "2nd":
            url += "&f_N=S"

        logger.info("Searching LinkedIn Jobs: %s", keywords)
        await self._wait_human_delay(MIN_PAGE_DELAY_SEC, MAX_PAGE_DELAY_SEC)

        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._wait_human_delay()

            # Scroll to load more results
            await self._scroll_page(3)
            await self._wait_human_delay()

            self._search_count += 1

            # Extract job listings from the page
            return await self._extract_job_listings()

        except Exception as e:
            logger.error("LinkedIn job search failed: %s", e)
            return []

    async def _extract_job_listings(self) -> list[dict]:
        """Extract job listings from the current LinkedIn Jobs page."""
        html = await self._page.content()
        soup = BeautifulSoup(html, "html.parser")

        jobs = []

        # LinkedIn job cards — try multiple selector patterns
        # (LinkedIn changes their HTML frequently)
        card_selectors = [
            "div.job-search-card",
            "li.jobs-search-results__list-item",
            "div.jobs-search-results-list__list-item",
            "ul.scaffold-layout__list-container li",
        ]

        cards = []
        for selector in card_selectors:
            cards = soup.select(selector)
            if cards:
                break

        if not cards:
            # Fallback: extract whatever text we can
            logger.warning("Could not find job cards — LinkedIn may have changed their HTML")
            text = soup.get_text(separator="\n")
            return [{"raw_text": text[:3000], "source": "linkedin_raw"}]

        for card in cards[:15]:  # Limit to 15 results
            job = self._parse_job_card(card)
            if job:
                jobs.append(job)

        logger.info("Extracted %d job listings from LinkedIn", len(jobs))
        return jobs

    def _parse_job_card(self, card) -> dict | None:
        """Parse a single LinkedIn job card into a structured dict."""
        try:
            # Try multiple patterns for title
            title_el = (
                card.select_one("h3.base-search-card__title")
                or card.select_one("a.job-card-list__title")
                or card.select_one("[class*='job-title']")
                or card.select_one("h3")
            )
            title = title_el.get_text(strip=True) if title_el else None

            # Company name
            company_el = (
                card.select_one("h4.base-search-card__subtitle")
                or card.select_one("a.job-card-container__company-name")
                or card.select_one("[class*='company']")
                or card.select_one("h4")
            )
            company = company_el.get_text(strip=True) if company_el else "Unknown"

            # Location
            location_el = (
                card.select_one("span.job-search-card__location")
                or card.select_one("[class*='location']")
            )
            location = location_el.get_text(strip=True) if location_el else None

            # Job URL
            link_el = card.select_one("a[href*='/jobs/']") or card.select_one("a")
            url = link_el["href"] if link_el and link_el.get("href") else None

            if not title:
                return None

            # Ensure full URL
            if url and not url.startswith("http"):
                url = f"https://www.linkedin.com{url}"

            return {
                "title": title,
                "company": company,
                "location": location,
                "url": url or "",
                "source": "linkedin",
            }
        except Exception as e:
            logger.debug("Failed to parse job card: %s", e)
            return None

    # ── Feed Scanning ─────────────────────────────────────────────

    async def scan_feed(self, job_keywords: list[str] = None) -> list[dict]:
        """
        Scroll through the LinkedIn feed looking for job-related posts.

        Looks for posts containing: #hiring, "we're looking for",
        "join our team", "open position", etc.

        Args:
            job_keywords: Additional keywords to match (e.g., ["ML Engineer"])

        Returns:
            List of post dicts with text, author, url
        """
        logger.info("Scanning LinkedIn feed for job posts...")
        await self._wait_human_delay(MIN_PAGE_DELAY_SEC, MAX_PAGE_DELAY_SEC)

        try:
            await self._page.goto(
                "https://www.linkedin.com/feed/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await self._wait_human_delay()

            # Scroll through the feed to load posts
            await self._scroll_page(5)
            await self._wait_human_delay()

            html = await self._page.content()
            return self._extract_job_posts(html, job_keywords or [])

        except Exception as e:
            logger.error("LinkedIn feed scan failed: %s", e)
            return []

    def _extract_job_posts(self, html: str, keywords: list[str]) -> list[dict]:
        """Extract job-related posts from the LinkedIn feed HTML."""
        soup = BeautifulSoup(html, "html.parser")

        # Job-related phrases to look for in posts
        job_phrases = [
            "#hiring", "#opentowork", "#jobopening",
            "we're hiring", "we are hiring",
            "we're looking for", "we are looking for",
            "join our team", "open position", "open role",
            "job opening", "now hiring", "come join us",
        ]

        # Add user's custom keywords
        job_phrases.extend([kw.lower() for kw in keywords])

        posts = []

        # LinkedIn feed post containers
        post_selectors = [
            "div.feed-shared-update-v2",
            "div.occludable-update",
            "div[data-urn*='activity']",
        ]

        post_elements = []
        for selector in post_selectors:
            post_elements = soup.select(selector)
            if post_elements:
                break

        for post_el in post_elements[:20]:
            text = post_el.get_text(separator=" ", strip=True).lower()

            # Check if the post mentions any job-related phrases
            matched_phrases = [p for p in job_phrases if p in text]
            if not matched_phrases:
                continue

            # Extract author
            author_el = post_el.select_one("[class*='actor-name']") or post_el.select_one("span.feed-shared-actor__name")
            author = author_el.get_text(strip=True) if author_el else "Unknown"

            # Get the full post text (not lowercased)
            full_text = post_el.get_text(separator=" ", strip=True)

            posts.append({
                "author": author,
                "text": full_text[:500],
                "matched_phrases": matched_phrases,
                "source": "linkedin_feed",
            })

        logger.info("Found %d job-related posts in feed", len(posts))
        return posts

    # ── Job Details ───────────────────────────────────────────────

    async def get_job_details(self, job_url: str) -> dict:
        """
        Navigate to a specific job posting and extract the full description.

        Args:
            job_url: LinkedIn job URL

        Returns:
            Dict with full job description text
        """
        logger.info("Fetching job details: %s", job_url)
        await self._wait_human_delay(MIN_PAGE_DELAY_SEC, MAX_PAGE_DELAY_SEC)

        try:
            await self._page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            await self._wait_human_delay()

            # Try to click "Show more" to expand the description
            try:
                show_more = self._page.get_by_text("Show more", exact=False).first
                await show_more.click(timeout=3000)
                await asyncio.sleep(1)
            except Exception:
                pass  # No "Show more" button, description is already full

            html = await self._page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Extract job description
            desc_selectors = [
                "div.jobs-description__content",
                "div.description__text",
                "div.show-more-less-html__markup",
                "section.description",
            ]

            description = ""
            for selector in desc_selectors:
                desc_el = soup.select_one(selector)
                if desc_el:
                    description = desc_el.get_text(separator="\n", strip=True)
                    break

            if not description:
                # Fallback — get all page text
                description = soup.get_text(separator="\n")
                lines = [l.strip() for l in description.splitlines() if l.strip()]
                description = "\n".join(lines)[:3000]

            # Extract title and company from the detail page
            title_el = soup.select_one("h1.jobs-unified-top-card__job-title") or soup.select_one("h1")
            company_el = soup.select_one("a.jobs-unified-top-card__company-name") or soup.select_one("[class*='company']")

            return {
                "title": title_el.get_text(strip=True) if title_el else "Unknown",
                "company": company_el.get_text(strip=True) if company_el else "Unknown",
                "description": description[:5000],
                "url": job_url,
                "source": "linkedin",
            }

        except Exception as e:
            logger.error("Failed to get job details: %s", e)
            return {"error": str(e), "url": job_url}
