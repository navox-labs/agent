from __future__ import annotations

"""
Job Store — SQLite persistence for discovered jobs and outreach tracking.

This is the agent's job pipeline database. Every job found from any source
(LinkedIn, Indeed, email, Twitter) gets stored here with:
- Match score and analysis (from the Navox-ported matching engine)
- Connection information (who do you know at this company?)
- Outreach status (new → notified → drafting → approved → sent → responded)
- Full tracking of sent messages and responses

The schema mirrors Navox's job_matches table but adds outreach tracking
fields that the autonomous agent needs.
"""

import json
import sqlite3
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class JobStore:
    """
    SQLite-backed storage for the job discovery pipeline.

    Uses the same database file as the agent memory (data/agent_memory.db)
    to keep everything in one place.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_tables()

    def _init_tables(self):
        """Create job tracking tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT,
                    url TEXT NOT NULL,
                    description TEXT,
                    source TEXT NOT NULL,
                    match_score INTEGER,
                    matched_skills TEXT,
                    missing_skills TEXT,
                    gap_analysis TEXT,
                    resume_tailoring TEXT,
                    connection_name TEXT,
                    connection_relation TEXT,
                    status TEXT DEFAULT 'new',
                    outreach_draft TEXT,
                    outreach_sent_at DATETIME,
                    outreach_platform TEXT,
                    response_received_at DATETIME,
                    profile_shared BOOLEAN DEFAULT FALSE,
                    notes TEXT,
                    discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS scan_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    query TEXT,
                    results_found INTEGER,
                    new_jobs INTEGER,
                    scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_status
                    ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_source
                    ON jobs(source);
                CREATE INDEX IF NOT EXISTS idx_jobs_score
                    ON jobs(match_score DESC);
                CREATE INDEX IF NOT EXISTS idx_scan_history_source
                    ON scan_history(source, scanned_at);
            """)
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Job CRUD ───────────────────────────────────────────────────

    async def save_job(self, job: dict) -> bool:
        """
        Save a discovered job. Returns True if it's new (not a duplicate).

        Uses INSERT OR IGNORE keyed on job_id — if the job already exists,
        the insert silently does nothing and we return False.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO jobs
                   (job_id, title, company, location, url, description, source,
                    match_score, matched_skills, missing_skills, gap_analysis,
                    resume_tailoring, connection_name, connection_relation)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job["job_id"],
                    job["title"],
                    job["company"],
                    job.get("location", ""),
                    job["url"],
                    job.get("description", ""),
                    job["source"],
                    job.get("match_score"),
                    json.dumps(job.get("matched_skills", [])),
                    json.dumps(job.get("missing_skills", [])),
                    job.get("gap_analysis", ""),
                    json.dumps(job.get("resume_tailoring")) if job.get("resume_tailoring") else None,
                    job.get("connection_name"),
                    job.get("connection_relation"),
                ),
            )
            conn.commit()
            is_new = cursor.rowcount > 0
            if is_new:
                logger.info("New job saved: %s at %s", job["title"], job["company"])
            return is_new
        finally:
            conn.close()

    async def get_jobs(
        self,
        status: str | None = None,
        source: str | None = None,
        min_score: int | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Get tracked jobs with optional filters."""
        conn = self._connect()
        try:
            query = "SELECT * FROM jobs WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)
            if source:
                query += " AND source = ?"
                params.append(source)
            if min_score is not None:
                query += " AND match_score >= ?"
                params.append(min_score)

            query += " ORDER BY match_score DESC, discovered_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    async def get_job_by_id(self, job_id: str) -> dict | None:
        """Get a specific job by its job_id."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    async def update_status(self, job_id: str, status: str, notes: str | None = None):
        """Update a job's pipeline status."""
        conn = self._connect()
        try:
            if notes:
                conn.execute(
                    "UPDATE jobs SET status = ?, notes = ? WHERE job_id = ?",
                    (status, notes, job_id),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status = ? WHERE job_id = ?",
                    (status, job_id),
                )
            conn.commit()
            logger.info("Job %s status → %s", job_id, status)
        finally:
            conn.close()

    async def set_outreach_draft(self, job_id: str, draft: str, platform: str):
        """Store an outreach draft for a job."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE jobs SET outreach_draft = ?, outreach_platform = ?, status = 'drafting' WHERE job_id = ?",
                (draft, platform, job_id),
            )
            conn.commit()
        finally:
            conn.close()

    async def mark_outreach_sent(self, job_id: str):
        """Record that outreach was sent."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE jobs SET outreach_sent_at = CURRENT_TIMESTAMP, status = 'sent' WHERE job_id = ?",
                (job_id,),
            )
            conn.commit()
        finally:
            conn.close()

    async def mark_response_received(self, job_id: str):
        """Record that a response was received."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE jobs SET response_received_at = CURRENT_TIMESTAMP, status = 'responded' WHERE job_id = ?",
                (job_id,),
            )
            conn.commit()
        finally:
            conn.close()

    async def mark_profile_shared(self, job_id: str):
        """Record that profile/resume was shared."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE jobs SET profile_shared = TRUE WHERE job_id = ?",
                (job_id,),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Scan History ───────────────────────────────────────────────

    async def log_scan(self, source: str, query: str, results_found: int, new_jobs: int):
        """Record a scan for history and rate-limiting."""
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO scan_history (source, query, results_found, new_jobs) VALUES (?, ?, ?, ?)",
                (source, query, results_found, new_jobs),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_recent_scan(self, source: str, query: str, hours: int = 4) -> dict | None:
        """
        Check if we ran this same scan recently.

        Used to avoid hammering sources — if the same keywords+source
        were scanned within the last N hours, return the cached result
        instead of hitting the web again.
        """
        conn = self._connect()
        try:
            cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
            row = conn.execute(
                "SELECT * FROM scan_history WHERE source = ? AND query = ? AND scanned_at > ? ORDER BY scanned_at DESC LIMIT 1",
                (source, query, cutoff),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ── Stats ──────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        """Get summary stats for the job pipeline."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) as count FROM jobs GROUP BY status"
            ).fetchall()
            stats = {row["status"]: row["count"] for row in rows}

            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            avg_score = conn.execute(
                "SELECT AVG(match_score) FROM jobs WHERE match_score IS NOT NULL"
            ).fetchone()[0]

            return {
                "total_jobs": total,
                "average_match_score": round(avg_score, 1) if avg_score else 0,
                "by_status": stats,
            }
        finally:
            conn.close()

    # ── Helpers ────────────────────────────────────────────────────

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        """Convert a database row to a clean dict for the LLM."""
        d = dict(row)
        # Parse JSON fields back into Python objects
        for field in ("matched_skills", "missing_skills"):
            if d.get(field):
                try:
                    d[field] = json.loads(d[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        if d.get("resume_tailoring"):
            try:
                d["resume_tailoring"] = json.loads(d["resume_tailoring"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d
