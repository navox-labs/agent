#!/usr/bin/env bash
set -e

echo "================================================"
echo "  Navox Agent — Setup"
echo "================================================"
echo ""

# 1. Check Python version (require 3.9+)
PYTHON_CMD=""
for cmd in python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 9 ]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "ERROR: Python 3.9+ is required."
    echo "Install from https://python.org"
    exit 1
fi
echo "Using $PYTHON_CMD ($($PYTHON_CMD --version))"

# 2. Create virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON_CMD -m venv .venv
fi
source .venv/bin/activate
echo "Virtual environment activated."

# 3. Install dependencies
echo "Installing Python dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# 4. Install Playwright browsers
echo "Installing Playwright Chromium browser..."
playwright install chromium

# 5. Copy .env.example to .env if it doesn't exist
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "Created .env from .env.example."
else
    echo ""
    echo ".env already exists — skipping."
fi

# 6. Create data directory
mkdir -p data/screenshots

echo ""
echo "================================================"
echo "  Setup complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo ""
echo "  1. Edit .env and add your OPENAI_API_KEY"
echo "     nano .env"
echo ""
echo "  2. (Optional) Add Gmail credentials for email features"
echo "     See .env.example for EMAIL_USERNAME and EMAIL_PASSWORD"
echo ""
echo "  3. (Optional) Set up LinkedIn session for job scanning:"
echo "     python scripts/setup_linkedin_session.py"
echo ""
echo "  4. (Optional) Set up Google Calendar:"
echo "     python scripts/setup_google_oauth.py"
echo ""
echo "Start the agent:"
echo ""
echo "  source .venv/bin/activate"
echo "  python main.py                # Interactive CLI"
echo "  python main.py --mode daemon  # Autonomous background mode"
echo "  python main.py --mode both    # CLI + background automation"
echo ""
