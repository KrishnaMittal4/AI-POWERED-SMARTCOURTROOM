"""
Feedback Store — SQLite-backed user feedback on RAG answers
=============================================================
Stores 👍/👎 ratings and optional comments linked to each query+answer pair.
Over time this builds a labeled dataset that can be used to:
  - Identify weak spots in retrieval or generation
  - Tune retrieval weights (e.g. MIN_RETRIEVAL_SCORE)
  - Build ground-truth eval sets automatically

Usage (from main.py):
    from feedback_store import FeedbackStore
    store = FeedbackStore()          # creates feedback.db in project root
    store.add(question, answer, sources_json, rating, comment)
    stats = store.summary()
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone


class FeedbackStore:
    """Thread-safe SQLite feedback store (one writer at a time via lock)."""

    def __init__(self, db_path: str = "feedback.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._lock, self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at  TEXT    NOT NULL,
                    question    TEXT    NOT NULL,
                    answer      TEXT    NOT NULL,
                    sources     TEXT,
                    rating      INTEGER NOT NULL,
                    comment     TEXT,
                    top_score   REAL,
                    weak_match  INTEGER DEFAULT 0,
                    not_found   INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_rating
                ON feedback(rating)
            """)

    def add(
        self,
        question: str,
        answer: str,
        sources: list | None = None,
        rating: int = 1,
        comment: str | None = None,
        top_score: float | None = None,
        weak_match: bool = False,
        not_found: bool = False,
    ) -> int:
        """Insert a feedback entry. rating: 1 = thumbs up, -1 = thumbs down."""
        now = datetime.now(timezone.utc).isoformat()
        sources_json = json.dumps(sources) if sources else None
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                """INSERT INTO feedback
                   (created_at, question, answer, sources, rating, comment,
                    top_score, weak_match, not_found)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (now, question, answer, sources_json, rating, comment,
                 top_score, int(weak_match), int(not_found)),
            )
            return cur.lastrowid

    def recent(self, limit: int = 50) -> list[dict]:
        """Return the most recent feedback entries."""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM feedback ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def summary(self) -> dict:
        """Aggregate stats: total, thumbs up, thumbs down, ratio."""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
            up = conn.execute(
                "SELECT COUNT(*) FROM feedback WHERE rating = 1"
            ).fetchone()[0]
            down = conn.execute(
                "SELECT COUNT(*) FROM feedback WHERE rating = -1"
            ).fetchone()[0]
            return {
                "total": total,
                "thumbs_up": up,
                "thumbs_down": down,
                "satisfaction_rate": round(up / total, 3) if total > 0 else None,
            }
