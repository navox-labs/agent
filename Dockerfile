FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg2 && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser
RUN playwright install chromium --with-deps

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p data/users data/screenshots

# Default: run in Telegram bot mode
CMD ["python", "main.py", "--mode", "telegram"]
