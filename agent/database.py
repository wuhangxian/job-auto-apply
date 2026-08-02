"""SQLite 存储岗位、评分和投递状态。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Iterator
from contextlib import contextmanager


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT DEFAULT '',
    salary TEXT DEFAULT '',
    jd TEXT DEFAULT '',
    url TEXT NOT NULL,
    canonical_url TEXT UNIQUE,
    score INTEGER DEFAULT 0,
    score_reason TEXT DEFAULT '',
    score_detail TEXT DEFAULT '',
    status TEXT DEFAULT 'new',
    applied_at TEXT,
    review_status TEXT DEFAULT '',
    review_notes TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(score);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
"""


@dataclass(frozen=True)
class Job:
    id: int
    source: str
    company: str
    title: str
    location: str
    salary: str
    jd: str
    url: str
    canonical_url: str
    score: int
    score_reason: str
    score_detail: str
    status: str
    applied_at: str | None
    review_status: str
    review_notes: str
    created_at: str
    updated_at: str


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonicalize_url(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower() or "https"
    host = (parsed.hostname or "").lower()
    port = parsed.port
    include_port = port is not None and not (
        (scheme == "https" and port == 443)
        or (scheme == "http" and port == 80)
    )
    netloc = f"{host}:{port}" if include_port else host
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def upsert_job(
        self,
        *,
        source: str,
        company: str,
        title: str,
        url: str,
        location: str = "",
        salary: str = "",
        jd: str = "",
    ) -> int | None:
        canonical = canonicalize_url(url)
        ts = now()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM jobs WHERE canonical_url = ?",
                (canonical,),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE jobs SET updated_at = ?, jd = ?
                       WHERE id = ?""",
                    (ts, jd, existing["id"]),
                )
                return existing["id"]
            cursor = conn.execute(
                """INSERT INTO jobs
                   (source, company, title, location, salary, jd, url,
                    canonical_url, created_at, updated_at)
                   VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (source, company, title, location, salary, jd, url,
                 canonical, ts, ts),
            )
            return cursor.lastrowid

    def set_score(self, job_id: int, score: int, reason: str, detail: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET score = ?, score_reason = ?, score_detail = ?, updated_at = ? WHERE id = ?",
                (score, reason, detail, now(), job_id),
            )

    def set_status(self, job_id: int, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (status, now(), job_id),
            )

    def mark_applied(self, job_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'applied', applied_at = ?, updated_at = ? WHERE id = ?",
                (now(), now(), job_id),
            )

    def set_review(self, job_id: int, status: str, notes: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET review_status = ?, review_notes = ?, updated_at = ? WHERE id = ?",
                (status, notes, now(), job_id),
            )

    def list_jobs(
        self,
        status: str | None = None,
        min_score: int = 0,
        limit: int = 500,
    ) -> list[Job]:
        query = "SELECT * FROM jobs WHERE score >= ?"
        params: list = [min_score]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY score DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_job_from_row(r) for r in rows]

    def get_unapplied_high_score(self, limit: int = 10) -> list[Job]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM jobs
                   WHERE status = 'new' AND score >= ?
                   ORDER BY score DESC LIMIT ?""",
                (0, limit),
            ).fetchall()
        return [_job_from_row(r) for r in rows]

    def stats(self) -> dict:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            applied = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'applied'").fetchone()[0]
            pending = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'pending_review'").fetchone()[0]
            rejected = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'rejected'").fetchone()[0]
            high = conn.execute("SELECT COUNT(*) FROM jobs WHERE score >= 70 AND status = 'new'").fetchone()[0]
            return {
                "total": total,
                "applied": applied,
                "pending_review": pending,
                "rejected": rejected,
                "high_score_unapplied": high,
            }


def _job_from_row(row) -> Job:
    return Job(
        id=row["id"],
        source=row["source"],
        company=row["company"],
        title=row["title"],
        location=row["location"],
        salary=row["salary"],
        jd=row["jd"],
        url=row["url"],
        canonical_url=row["canonical_url"] or "",
        score=row["score"],
        score_reason=row["score_reason"],
        score_detail=row["score_detail"] if "score_detail" in row.keys() else "",
        status=row["status"],
        applied_at=row["applied_at"],
        review_status=row["review_status"],
        review_notes=row["review_notes"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
