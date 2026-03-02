from __future__ import annotations

"""
LinkedIn Cookie Session — cookie-based browser session for Telegram users.

The original LinkedInSession uses Playwright's launch_persistent_context()
with a session directory, which requires running setup_linkedin_session.py
locally. Telegram users can't do that — they need a simpler auth method.

This class takes a LinkedIn `li_at` cookie string and injects it into a
fresh browser context. The li_at cookie is the session token LinkedIn uses
to keep you logged in — pasting it gives the bot the same access as your
browser has.

How to get your li_at cookie:
1. Open LinkedIn in your browser
2. Press F12 → Application tab → Cookies → linkedin.com
3. Copy the value of the `li_at` cookie
4. Paste it to the bot via /connect_linkedin

Reuses the same parsing logic as LinkedInSession (job cards, feed posts).
"""

import asyncio
import logging
import random
import time
from typing import Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# Rate limiting (same as LinkedInSession)
MAX_SEARCHES_PER_HOUR = 5
MIN_ACTION_DELAY_SEC = 3
MAX_ACTION_DELAY_SEC = 7
MIN_PAGE_DELAY_SEC = 8
MAX_PAGE_DELAY_SEC = 15


class LinkedInCookieSession:
    """
    Cookie-based LinkedIn session for Telegram bot users.

    Instead of a persistent browser profile, this injects the user's
    li_at cookie into a fresh context. Everything else (search, parsing,
    rate limiting) works the same as LinkedInSession.
    """

    def __init__(self, cookie: str, browser: Browser | None = None):
        """
        Args:
            cookie: The li_at cookie value from the user's LinkedIn session.
            browser: Optional shared Playwright browser instance.
                     If None, we'll launch our own.
        """
        self._cookie = cookie
        self._shared_browser = browser
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._last_action_time: float = 0
        self._search_count: int = 0
        self._search_hour_start: float = 0

    async def start(self):
        """Start the browser and inject the LinkedIn cookie."""
        if self._shared_browser:
            self._browser = self._shared_browser
        else:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )

        # Create a fresh context with anti-detection settings
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/Toronto",
        )

        # Inject the li_at cookie
        await self._context.add_cookies([
            {
                "name": "li_at",
                "value": self._cookie,
                "domain": ".linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            }
        ])

        self._page = await self._context.new_page()
        logger.info("LinkedIn cookie session started")

    async def close(self):
        """Close the context (and browser if we own it)."""
        if self._context:
            await self._context.close()
        if self._playwright:
            # We launched our own browser, so close it
            if self._browser:
                await self._browser.close()
            await self._playwright.stop()
        self._context = None
        self._page = None
        self._browser = None
        self._playwright = None
        logger.info("LinkedIn cookie session closed")

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
        if now - self._search_hour_start > 3600:
            self._search_count = 0
            self._search_hour_start = now

        if self._search_count >= MAX_SEARCHES_PER_HOUR:
            logger.warning("LinkedIn rate limit reached (%d searches/hour)", MAX_SEARCHES_PER_HOUR)
            return False
        return True

    # ── Login Check ───────────────────────────────────────────────

    async def is_logged_in(self) -> bool:
        """Check if the cookie is still valid."""
        try:
            await self._page.goto(
                "https://www.linkedin.com/feed/",
                wait_until="domcontentloaded",
                timeout=15000,
            )
            await asyncio.sleep(2)

            url = self._page.url
            if "login" in url or "authwall" in url or "checkpoint" in url:
                return False

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
        Search LinkedIn Jobs with optional connection filter.

        Args:
            keywords: Job search keywords (e.g., "ML Engineer")
            location: Location filter (e.g., "Toronto, ON")
            connection_filter: "1st", "2nd", or "" for no filter

        Returns:
            List of job dicts with title, company, location, url, connection info
        """
        if not self._check_rate_limit():
            return []

        from urllib.parse import quote_plus
        url = f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(keywords)}"

        if location:
            url += f"&location={quote_plus(location)}"

        if connection_filter == "1st":
            url += "&f_N=F"
        elif connection_filter == "2nd":
            url += "&f_N=S"

        logger.info("Searching LinkedIn Jobs: %s (filter=%s)", keywords, connection_filter or "none")
        await self._wait_human_delay(MIN_PAGE_DELAY_SEC, MAX_PAGE_DELAY_SEC)

        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._wait_human_delay()

            # Scroll to load more results
            await self._scroll_page(3)
            await self._wait_human_delay()

            self._search_count += 1

            jobs = await self._extract_job_listings()

            # Tag jobs with connection relation if filter was used
            if connection_filter:
                for job in jobs:
                    if not job.get("connection_relation"):
                        job["connection_relation"] = f"{connection_filter} degree"

            return jobs

        except Exception as e:
            logger.error("LinkedIn job search failed: %s", e)
            return []

    async def _extract_job_listings(self) -> list[dict]:
        """Extract job listings from the current LinkedIn Jobs page."""
        html = await self._page.content()
        soup = BeautifulSoup(html, "html.parser")

        jobs = []

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
            logger.warning("Could not find job cards — LinkedIn may have changed their HTML")
            text = soup.get_text(separator="\n")
            return [{"raw_text": text[:3000], "source": "linkedin_raw"}]

        for card in cards[:15]:
            job = self._parse_job_card(card)
            if job:
                jobs.append(job)

        logger.info("Extracted %d job listings from LinkedIn", len(jobs))
        return jobs

    def _parse_job_card(self, card) -> dict | None:
        """Parse a single LinkedIn job card, including connection indicators."""
        try:
            # Title
            title_el = (
                card.select_one("h3.base-search-card__title")
                or card.select_one("a.job-card-list__title")
                or card.select_one("[class*='job-title']")
                or card.select_one("h3")
            )
            title = title_el.get_text(strip=True) if title_el else None

            # Company
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

            if url and not url.startswith("http"):
                url = f"https://www.linkedin.com{url}"

            job = {
                "title": title,
                "company": company,
                "location": location,
                "url": url or "",
                "source": "linkedin",
            }

            # Extract connection indicators from the card
            card_text = card.get_text(separator=" ", strip=True).lower()

            # "X connections work here" or "X of your connections"
            connection_patterns = [
                "connection", "connections work here",
                "know someone", "alumni",
            ]
            for pattern in connection_patterns:
                if pattern in card_text:
                    # Try to extract the connection name/info
                    conn_el = (
                        card.select_one("[class*='connection']")
                        or card.select_one("[class*='social-proof']")
                    )
                    if conn_el:
                        job["connection_name"] = conn_el.get_text(strip=True)
                    else:
                        job["connection_name"] = "Connection at company"
                    break

            return job
        except Exception as e:
            logger.debug("Failed to parse job card: %s", e)
            return None

    # ── Feed Scanning ─────────────────────────────────────────────

    async def scan_feed(self, job_keywords: list[str] = None) -> list[dict]:
        """Scroll through the LinkedIn feed looking for job-related posts."""
        logger.info("Scanning LinkedIn feed for job posts...")
        await self._wait_human_delay(MIN_PAGE_DELAY_SEC, MAX_PAGE_DELAY_SEC)

        try:
            await self._page.goto(
                "https://www.linkedin.com/feed/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await self._wait_human_delay()
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

        job_phrases = [
            "#hiring", "#opentowork", "#jobopening",
            "we're hiring", "we are hiring",
            "we're looking for", "we are looking for",
            "join our team", "open position", "open role",
            "job opening", "now hiring", "come join us",
        ]
        job_phrases.extend([kw.lower() for kw in keywords])

        posts = []

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

            matched_phrases = [p for p in job_phrases if p in text]
            if not matched_phrases:
                continue

            author_el = (
                post_el.select_one("[class*='actor-name']")
                or post_el.select_one("span.feed-shared-actor__name")
            )
            author = author_el.get_text(strip=True) if author_el else "Unknown"
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
        """Navigate to a specific job posting and extract the full description."""
        logger.info("Fetching job details: %s", job_url)
        await self._wait_human_delay(MIN_PAGE_DELAY_SEC, MAX_PAGE_DELAY_SEC)

        try:
            await self._page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            await self._wait_human_delay()

            # Try to click "Show more" to expand description
            try:
                show_more = self._page.get_by_text("Show more", exact=False).first
                await show_more.click(timeout=3000)
                await asyncio.sleep(1)
            except Exception:
                pass

            html = await self._page.content()
            soup = BeautifulSoup(html, "html.parser")

            # Job description
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
                description = soup.get_text(separator="\n")
                lines = [l.strip() for l in description.splitlines() if l.strip()]
                description = "\n".join(lines)[:3000]

            title_el = (
                soup.select_one("h1.jobs-unified-top-card__job-title")
                or soup.select_one("h1")
            )
            company_el = (
                soup.select_one("a.jobs-unified-top-card__company-name")
                or soup.select_one("[class*='company']")
            )

            result = {
                "title": title_el.get_text(strip=True) if title_el else "Unknown",
                "company": company_el.get_text(strip=True) if company_el else "Unknown",
                "description": description[:5000],
                "url": job_url,
                "source": "linkedin",
            }

            # Extract "Posted by" recruiter info
            poster_info = self._extract_poster_info(soup)
            if poster_info:
                result["hiring_manager_name"] = poster_info.get("name")

            return result

        except Exception as e:
            logger.error("Failed to get job details: %s", e)
            return {"error": str(e), "url": job_url}

    def _extract_poster_info(self, soup) -> dict | None:
        """Extract the recruiter/poster info from a job detail page."""
        # LinkedIn shows "Posted by [Name]" or recruiter card on job pages
        poster_selectors = [
            "div.jobs-poster__name",
            "a.jobs-unified-top-card__subtitle-secondary-grouping",
            "[class*='hirer']",
            "[class*='poster']",
        ]

        for selector in poster_selectors:
            el = soup.select_one(selector)
            if el:
                name = el.get_text(strip=True)
                if name and len(name) < 100:
                    return {"name": name}

        # Fallback: look for "Posted by" text pattern
        for text_el in soup.find_all(string=lambda t: t and "posted by" in t.lower()):
            parent = text_el.parent
            if parent:
                full_text = parent.get_text(strip=True)
                # Extract name after "Posted by"
                if "posted by" in full_text.lower():
                    parts = full_text.lower().split("posted by", 1)
                    if len(parts) > 1:
                        name = parts[1].strip().title()
                        if name and len(name) < 100:
                            return {"name": name}

        return None

    # ── Utilities ─────────────────────────────────────────────────

    async def _scroll_page(self, scrolls: int = 3):
        """Scroll down the page like a human would."""
        for _ in range(scrolls):
            scroll_amount = random.randint(300, 700)
            await self._page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(random.uniform(0.5, 1.5))
