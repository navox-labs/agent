# Navox Agent

**Autonomous AI agent that finds jobs, matches them to your profile, and drafts outreach — while you sleep.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-green.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/Tests-57%20passing-brightgreen.svg)](tests/)

Built by [Navox Labs](https://navox.tech) — uses your [Navox profileCard](https://navox.tech) for smart job matching and outreach.

---

## What It Does

Navox Agent scans LinkedIn, Indeed, Google, and your email inbox for job opportunities. It scores each one against your resume using GPT-4o, identifies connections at the company, and drafts personalized outreach messages. You approve or edit before anything gets sent. It runs in the background on your machine — no cloud, no subscription, fully private.

```
$ python main.py --mode both

============================================================
  Navox Agent — CLI + Daemon Mode
  Interactive chat + background automation.
  Type 'quit' or 'exit' to stop.
============================================================

[Scheduler] Starting scan cycle...
[Scheduler] Scanning LinkedIn for "ML Engineer" in "Toronto"...
[Scheduler] Scanning Indeed for "ML Engineer" in "Toronto"...
[Scheduler] Found 23 jobs, 8 new. Top match: 87%

You: show me the top matches

Agent: Here are your top job matches from the latest scan:

  1. Senior ML Engineer at Shopify (87% match)
     Matched: Python, PyTorch, MLOps, Distributed Systems
     Missing: Kubernetes
     Connection: Sarah Chen (2nd degree on LinkedIn)
     Source: LinkedIn

  2. ML Platform Engineer at Cohere (82% match)
     Matched: Python, ML Infrastructure, Docker
     Missing: Ray, Spark
     Source: Indeed

  3. Applied Scientist at Scale AI (76% match)
     Matched: Python, Deep Learning, NLP
     Missing: Rust, C++
     Connection: James Wu (shared group: Toronto ML)
     Source: LinkedIn

You: draft outreach to Sarah Chen for the Shopify role

Agent: Here's the draft for Sarah:

  Hi Sarah,

  I noticed the Senior ML Engineer role at Shopify and wanted to
  reach out. I've been building ML infrastructure for the past 4
  years — my background in PyTorch and distributed systems aligns
  well with what the team is looking for.

  Would you be open to a quick chat about the role? I'd love to
  hear what the team is working on.

  Here's my profile: https://navox.tech/card/jsmith

  Reply APPROVE to send via LinkedIn DM, EDIT to modify, or SKIP.

You: approve

Agent: Outreach sent to Sarah Chen via LinkedIn DM.
       I'll notify you when she responds.
```

---

## Features

- **Multi-source job scanning** — LinkedIn Jobs, LinkedIn Feed (#hiring posts), Indeed, Google, and your email inbox (recruiter messages + job alerts)
- **Smart matching engine** — Scores every job against your profile using GPT-4o. Returns matched/missing skills, gap analysis, and resume tailoring tips
- **Navox profileCard integration** — Uses your Navox profile for matching accuracy and shares it with connections during outreach
- **Personalized outreach** — Drafts messages referencing the specific role, your matched skills, and the connection relationship. Supports email and LinkedIn DM
- **Human-in-the-loop** — Never sends anything without your explicit approval. APPROVE, EDIT, or SKIP every draft
- **Autonomous scheduler** — Scans for new jobs every 4 hours, checks for responses every 30 minutes, processes approvals every 15 minutes
- **Persistent memory** — Remembers your preferences, conversation history, and entire job pipeline across sessions
- **Three run modes** — Interactive CLI, background daemon, or both simultaneously
- **Privacy-first** — Runs entirely on your machine. Your resume, job data, and API keys never leave your computer

---

## Quick Start

```bash
git clone https://github.com/navox-labs/agent.git
cd agent
./setup.sh
```

Then add your OpenAI API key:

```bash
nano .env    # Set OPENAI_API_KEY=sk-...
```

Start the agent:

```bash
source .venv/bin/activate
python main.py
```

Tell it about yourself:

```
You: I'm a senior ML engineer with 5 years of experience in Python,
     PyTorch, and MLOps. Looking for roles in Toronto or remote.
     Here's my profile: navox.tech/card/jsmith
```

---

## How It Works

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   LinkedIn   │     │    Indeed     │     │    Email     │
│   Jobs/Feed  │     │              │     │    Inbox     │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       └──────────┬─────────┘──────────┬─────────┘
                  │                    │
           ┌──────▼────────────────────▼──────┐
           │         Job Scanner              │
           │   Deduplicate + normalize        │
           └──────────────┬───────────────────┘
                          │
           ┌──────────────▼───────────────────┐
           │     Matching Engine (GPT-4o)     │
           │   Score against your profile     │
           │   Matched / missing skills       │
           │   Gap analysis + resume tips     │
           └──────────────┬───────────────────┘
                          │
           ┌──────────────▼───────────────────┐
           │       Outreach Pipeline          │
           │   Draft → You Approve → Send     │
           │   Email or LinkedIn DM           │
           └──────────────┬───────────────────┘
                          │
           ┌──────────────▼───────────────────┐
           │       Response Monitor           │
           │   Checks inbox every 30 min      │
           │   Notifies you immediately       │
           └──────────────────────────────────┘
```

**The Agent Loop:** The brain receives your message, builds context (system prompt + conversation history + preferences), sends it to GPT-4o, and if the LLM returns tool calls, executes them and loops back until a final text response is ready. This is what makes it an *agent*, not a chatbot — it chains multiple tools autonomously to complete complex tasks.

---

## Tools

The agent has 8 tools it can use autonomously:

| Tool | What it does |
|------|-------------|
| **email** | Read, search, and send emails via Gmail IMAP/SMTP |
| **browser** | Navigate websites, Google search, extract text, take screenshots |
| **calendar** | List, create, update, and delete Google Calendar events |
| **profile** | Store and manage your resume/Navox profileCard for matching |
| **jobs** | Search across LinkedIn, Indeed, Google, email. Filter and track your pipeline |
| **outreach** | Draft, edit, approve, and send personalized outreach messages |
| **calculator** | Evaluate math expressions |
| **time** | Get current date/time in any timezone |

---

## Configuration

All config lives in `.env`. Copy from `.env.example` during setup:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | **Yes** | Your OpenAI API key ([get one](https://platform.openai.com/api-keys)) |
| `EMAIL_USERNAME` | No | Gmail address for email tool + outreach notifications |
| `EMAIL_PASSWORD` | No | Gmail App Password ([how to get one](https://support.google.com/accounts/answer/185833)) |
| `GOOGLE_CREDENTIALS_PATH` | No | Path to Google OAuth credentials for Calendar |
| `LINKEDIN_SESSION_DIR` | No | Directory for persistent LinkedIn browser session |

**Optional integrations:**

```bash
# LinkedIn scanning (one-time manual login, session persists)
python scripts/setup_linkedin_session.py

# Google Calendar
python scripts/setup_google_oauth.py
```

---

## Run Modes

```bash
python main.py                # Interactive CLI (default)
python main.py --mode daemon  # Background scheduler only
python main.py --mode both    # CLI + scheduler in parallel
```

| Mode | What it does |
|------|-------------|
| **cli** | Chat with the agent interactively. Search jobs, review matches, draft outreach. |
| **daemon** | Fully autonomous. Scans every 4h, checks responses every 30min, emails you summaries. |
| **both** | Best of both — background automation + interactive chat simultaneously. |

---

## Navox Integration

[Navox](https://navox.tech) turns your resume into an AI-powered profileCard that recruiters can chat with. The agent uses your Navox profile in two ways:

1. **Matching** — Your profileCard data (skills, experience, education) is used to score job relevance. The matching engine was ported directly from Navox's production API.

2. **Sharing** — When the agent drafts outreach to a connection, it includes your Navox profileCard link so they can explore your background interactively.

Create your profileCard at [navox.tech](https://navox.tech), then tell the agent:

```
You: here's my profile: navox.tech/card/yourname
```

---

## Project Structure

```
agent/
├── brain.py               # Core agent loop (LLM + tool orchestration)
├── config.py              # Environment config loader
├── models.py              # Shared data models
├── scheduler.py           # Autonomous background scheduler
├── llm/
│   ├── base.py            # LLM provider interface
│   └── openai_provider.py # OpenAI GPT-4o implementation
├── memory/
│   └── store.py           # SQLite persistent memory
├── profile/
│   └── store.py           # User profile storage
├── jobs/
│   ├── scanner.py         # Multi-source job scanner
│   ├── matcher.py         # Job-profile matching engine
│   ├── store.py           # Job pipeline database
│   ├── outreach.py        # Outreach lifecycle manager
│   └── linkedin_session.py
├── tools/
│   ├── base.py            # Tool interface (Strategy Pattern)
│   ├── registry.py        # Tool registry
│   ├── email_tool.py      # Gmail IMAP/SMTP
│   ├── browser_tool.py    # Playwright headless browser
│   ├── calendar_tool.py   # Google Calendar
│   ├── profile_tool.py    # Profile management
│   ├── job_tool.py        # Job search + pipeline
│   └── outreach_tool.py   # Outreach drafting + sending
└── frontends/
    └── cli.py             # Terminal chat interface
```

---

## Tests

```bash
source .venv/bin/activate
pytest           # 57 tests, runs in <1 second
pytest -v        # Verbose output
```

---

## License

MIT — see [LICENSE](LICENSE).

Built by [Navox Labs](https://navox.tech).
