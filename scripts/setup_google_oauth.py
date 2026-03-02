"""
Google OAuth2 Setup Script — one-time authentication for Google Calendar.

=== HOW OAUTH2 WORKS ===

When an app wants to access your Google Calendar, it can't just use your
password. Instead, Google uses OAuth2 — a 3-party handshake:

1. You (the user) tell Google: "I trust this app to see my calendar"
2. Google gives the app a short-lived ACCESS TOKEN
3. The app uses this token to call Calendar API on your behalf
4. Google also gives a REFRESH TOKEN so the app can get new access tokens
   without asking you again

The flow:
  App → Opens browser → Google login page → You click "Allow"
  → Google redirects back with an authorization code
  → App exchanges code for access token + refresh token
  → Tokens saved to data/google_token.json (reused forever)

=== SETUP INSTRUCTIONS ===

Before running this script, you need to create a Google Cloud project:

1. Go to https://console.cloud.google.com/
2. Create a new project (e.g., "My Personal Agent")
3. Enable the Google Calendar API:
   - Go to "APIs & Services" → "Library"
   - Search "Google Calendar API" → Click Enable
4. Create OAuth credentials:
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth client ID"
   - Application type: "Desktop app"
   - Download the JSON file
   - Save it as: data/google_credentials.json
5. Configure OAuth consent screen:
   - Go to "APIs & Services" → "OAuth consent screen"
   - User type: "External" (or "Internal" if using Google Workspace)
   - Fill in app name, email
   - Add scope: "Google Calendar API - .../auth/calendar"
   - Add yourself as a test user
6. Run this script: python scripts/setup_google_oauth.py

The script will open your browser, you'll log in and click "Allow",
and a token file will be saved for the agent to use.
"""

import os
import sys

# Add the project root to path so we can import our modules
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# The scope tells Google exactly what we want access to.
# "calendar" = full read/write access to Google Calendar.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# File paths
DATA_DIR = os.path.join(project_root, "data")
CREDENTIALS_FILE = os.path.join(DATA_DIR, "google_credentials.json")
TOKEN_FILE = os.path.join(DATA_DIR, "google_token.json")


def main():
    print("=" * 60)
    print("  Google Calendar OAuth2 Setup")
    print("=" * 60)
    print()

    # Check if credentials file exists
    if not os.path.exists(CREDENTIALS_FILE):
        print("ERROR: Credentials file not found!")
        print(f"Expected at: {CREDENTIALS_FILE}")
        print()
        print("To fix this:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project and enable Google Calendar API")
        print("3. Create OAuth Desktop credentials")
        print("4. Download the JSON and save it as:")
        print(f"   {CREDENTIALS_FILE}")
        print()
        print("See the docstring at the top of this script for detailed steps.")
        sys.exit(1)

    # Check if we already have a valid token
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds and creds.valid:
        print("You already have a valid token!")
        print(f"Token file: {TOKEN_FILE}")
        print("No action needed.")
        return

    if creds and creds.expired and creds.refresh_token:
        print("Token expired, refreshing...")
        creds.refresh(Request())
    else:
        # Run the OAuth flow — this opens a browser window
        print("Opening your browser for Google authentication...")
        print("(If the browser doesn't open, copy the URL from the terminal)")
        print()

        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)

    # Save the token for future use
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    print()
    print("Authentication successful!")
    print(f"Token saved to: {TOKEN_FILE}")
    print()
    print("Your agent can now access Google Calendar.")
    print("You won't need to run this script again unless you revoke access.")


if __name__ == "__main__":
    main()
