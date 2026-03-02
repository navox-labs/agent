"""
Browser Tool — navigate websites, search the web, and extract content.

How this works:
- Playwright launches a headless Chromium browser (no visible window)
- We navigate to URLs, extract text, click elements, fill forms
- BeautifulSoup cleans up raw HTML into readable text for the LLM
- The browser is "lazy" — it only starts when you first use it

Key concepts:
- Headless browser: A real browser running without a GUI, controlled by code.
  Same engine as Chrome, so it renders JavaScript, handles cookies, etc.
- CSS selectors: A way to target HTML elements (e.g., "h1" for headings,
  ".class-name" for classes, "#id" for IDs). Playwright uses these to
  find elements to click or read.
- User-Agent: A string your browser sends to identify itself. We set a
  realistic one so websites don't block us as a bot.
"""

import asyncio
import logging
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, Page

from agent.tools.base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

# Maximum characters of page text to send to the LLM.
# Too much text wastes tokens and can exceed context limits.
MAX_TEXT_LENGTH = 5000


def _clean_text(html: str) -> str:
    """
    Convert raw HTML into clean, readable text.

    This is crucial — raw HTML is full of tags, scripts, and styling
    that would confuse the LLM and waste tokens. We want just the
    human-readable content.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove elements that never contain useful text
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe"]):
        tag.decompose()

    # Get text, collapse whitespace, and strip blank lines
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)

    # Truncate to save LLM context space
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH] + "\n\n... [truncated — page has more content]"

    return text


def _extract_links(html: str, base_url: str = "") -> list[dict]:
    """Extract all links from a page with their text and URLs."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        text = a_tag.get_text(strip=True)

        # Skip empty links, anchors, and javascript: links
        if not text or not href or href.startswith(("#", "javascript:")):
            continue

        # Skip duplicates
        if href in seen:
            continue
        seen.add(href)

        links.append({"text": text[:100], "url": href})

    return links[:30]  # Limit to 30 links to save context


class BrowserTool(Tool):
    """
    Web browser tool — navigates websites and extracts content.

    Uses lazy initialization: the browser isn't started until the first
    action is requested. This saves resources when the tool is registered
    but not used in a session.
    """

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._page: Page | None = None

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Browse the web. Actions: "
            "navigate (go to a URL and get page text), "
            "search (Google search and return results), "
            "get_links (list all links on the current page), "
            "click (click a link or button by its text), "
            "screenshot (take a screenshot of the current page)."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                "action", "string",
                "The browser action to perform",
                enum=["navigate", "search", "get_links", "click", "screenshot"],
            ),
            ToolParameter(
                "url", "string",
                "URL to navigate to — used with 'navigate' action",
                required=False,
            ),
            ToolParameter(
                "query", "string",
                "Search query — used with 'search' action",
                required=False,
            ),
            ToolParameter(
                "selector", "string",
                "Text of the link/button to click — used with 'click' action",
                required=False,
            ),
        ]

    # ── Browser Lifecycle ──────────────────────────────────────────

    async def _ensure_browser(self):
        """
        Lazy initialization — start the browser only when first needed.

        Why lazy? Starting a browser takes ~1-2 seconds and uses ~100MB RAM.
        If the user never asks to browse the web, we never pay that cost.
        """
        if self._browser is None:
            logger.info("Starting headless Chromium browser...")
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",  # Less bot-like
                ],
            )
            # Create a browser context with a realistic user-agent
            context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 720},
            )
            self._page = await context.new_page()
            logger.info("Browser started successfully.")

    async def cleanup(self):
        """Shut down the browser. Called when the agent exits."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._page = None
        self._playwright = None

    # ── Main Execute ───────────────────────────────────────────────

    async def execute(self, action: str, **kwargs) -> ToolResult:
        try:
            await self._ensure_browser()

            if action == "navigate":
                url = kwargs.get("url", "")
                if not url:
                    return ToolResult(success=False, data=None, error="URL is required for navigate action")
                return await self._navigate(url)

            elif action == "search":
                query = kwargs.get("query", "")
                if not query:
                    return ToolResult(success=False, data=None, error="Query is required for search action")
                return await self._search(query)

            elif action == "get_links":
                return await self._get_links()

            elif action == "click":
                selector = kwargs.get("selector", "")
                if not selector:
                    return ToolResult(success=False, data=None, error="Selector text is required for click action")
                return await self._click(selector)

            elif action == "screenshot":
                return await self._screenshot()

            else:
                return ToolResult(success=False, data=None, error=f"Unknown action: {action}")

        except Exception as e:
            logger.exception("Browser tool error")
            return ToolResult(success=False, data=None, error=f"Browser error: {e}")

    # ── Actions ────────────────────────────────────────────────────

    async def _navigate(self, url: str) -> ToolResult:
        """Navigate to a URL and extract the page text."""
        # Add https:// if no protocol specified
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        logger.info(f"Navigating to: {url}")
        response = await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait a moment for dynamic content to load
        await self._page.wait_for_timeout(1000)

        html = await self._page.content()
        text = _clean_text(html)
        title = await self._page.title()

        return ToolResult(
            success=True,
            data={
                "title": title,
                "url": self._page.url,
                "status": response.status if response else None,
                "content": text,
            },
        )

    async def _search(self, query: str) -> ToolResult:
        """
        Perform a Google search and return the results.

        We navigate to Google's search URL directly rather than
        filling in the search box — it's simpler and more reliable.
        """
        search_url = f"https://www.google.com/search?q={quote_plus(query)}"
        logger.info(f"Searching Google for: {query}")

        await self._page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await self._page.wait_for_timeout(2000)  # Google loads results dynamically

        html = await self._page.content()
        text = _clean_text(html)

        return ToolResult(
            success=True,
            data={
                "query": query,
                "url": self._page.url,
                "results": text,
            },
        )

    async def _get_links(self) -> ToolResult:
        """List all links on the current page."""
        if not self._page.url or self._page.url == "about:blank":
            return ToolResult(success=False, data=None, error="No page loaded. Navigate to a page first.")

        html = await self._page.content()
        links = _extract_links(html, self._page.url)
        title = await self._page.title()

        return ToolResult(
            success=True,
            data={
                "page_title": title,
                "url": self._page.url,
                "link_count": len(links),
                "links": links,
            },
        )

    async def _click(self, selector: str) -> ToolResult:
        """
        Click a link or button by its visible text.

        We use Playwright's text selector — it finds elements containing
        the given text. This is more natural than CSS selectors for an LLM.
        """
        logger.info(f"Clicking element with text: {selector}")

        try:
            # Try to find and click an element with matching text
            element = self._page.get_by_text(selector, exact=False).first
            await element.click(timeout=5000)
            await self._page.wait_for_timeout(2000)  # Wait for navigation/loading

            html = await self._page.content()
            text = _clean_text(html)
            title = await self._page.title()

            return ToolResult(
                success=True,
                data={
                    "clicked": selector,
                    "new_title": title,
                    "new_url": self._page.url,
                    "content": text,
                },
            )
        except Exception as e:
            return ToolResult(
                success=False, data=None,
                error=f"Could not find or click element with text '{selector}': {e}",
            )

    async def _screenshot(self) -> ToolResult:
        """Take a screenshot of the current page (saved to data/ directory)."""
        import os
        from datetime import datetime

        if not self._page.url or self._page.url == "about:blank":
            return ToolResult(success=False, data=None, error="No page loaded. Navigate to a page first.")

        # Save screenshots to the data/ directory
        screenshots_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data", "screenshots",
        )
        os.makedirs(screenshots_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(screenshots_dir, f"screenshot_{timestamp}.png")

        await self._page.screenshot(path=filepath, full_page=False)
        title = await self._page.title()

        return ToolResult(
            success=True,
            data={
                "message": f"Screenshot saved to {filepath}",
                "page_title": title,
                "url": self._page.url,
            },
        )
