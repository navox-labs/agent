#!/usr/bin/env python3
"""
LinkedIn Session Setup — one-time manual login.

This script opens a visible browser window so you can log into LinkedIn
manually. Once logged in, your session (cookies, localStorage) is saved
to data/linkedin_session/ and reused automatically by the agent.

Usage:
    python scripts/setup_linkedin_session.py

What happens:
1. A Chrome window opens to linkedin.com/login
2. You log in with your credentials (the script never sees your password)
3. Once the feed loads, the session is saved
4. Close the browser or press Ctrl+C to finish

The saved session typically lasts weeks before needing re-authentication.
If the agent reports "LinkedIn session expired", run this script again.
"""

import asyncio
import os
import sys

# Add project root to path so we can import agent modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.jobs.linkedin_session import LinkedInSession


async def main():
    session_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "linkedin_session",
    )

    print("=" * 60)
    print("  LinkedIn Session Setup")
    print("=" * 60)
    print()
    print(f"Session will be saved to: {session_dir}")
    print()
    print("A browser window will open. Log into LinkedIn normally.")
    print("Once you see your feed, the session is saved.")
    print("Press Ctrl+C when done.")
    print()

    session = LinkedInSession(session_dir=session_dir)

    try:
        # Launch VISIBLE browser (headless=False) for manual login
        await session.start(headless=False)

        # Navigate to LinkedIn login page
        page = session._page
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

        print("Waiting for you to log in...")
        print("(The browser will stay open until you press Ctrl+C)")
        print()

        # Poll until the user is logged in
        while True:
            await asyncio.sleep(3)

            url = page.url
            if "feed" in url or "mynetwork" in url or "messaging" in url:
                print("Login detected! Session saved successfully.")
                print(f"Session data stored in: {session_dir}")
                print()

                # Wait a bit more to let cookies settle
                await asyncio.sleep(2)

                # Verify
                logged_in = await session.is_logged_in()
                if logged_in:
                    print("Verified: LinkedIn session is active.")
                else:
                    print("Warning: Could not verify session. Try refreshing the page.")

                print()
                print("You can close the browser now, or press Ctrl+C.")

                # Keep browser open so user can verify
                await asyncio.sleep(3600)  # Wait up to an hour
                break

    except KeyboardInterrupt:
        print("\nSetup complete. Session saved.")
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
