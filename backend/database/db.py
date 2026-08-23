"""
db.py
-----
Minimal SQLite persistence layer for interaction history. Uses stdlib
sqlite3 directly (no ORM) since the schema is small and the project
already leans on Pydantic for validation elsewhere. Every query uses
parameterized statements (`?` placeholders) — never string formatting —
so this module is not a SQL-injection surface even though its inputs
ultimately originate from user queries.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger("linuxpilot.database")

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "linuxpilot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    intent TEXT NOT NULL,
    final_answer TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS command_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    verdict TEXT NOT NULL,
    reason TEXT NOT NULL,
    executed INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(_SCHEMA)
    logger.info("SQLite database initialized at %s", _DB_PATH)


def log_interaction(query: str, intent: str, final_answer: str, duration_ms: int) -> None:
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO interactions (query, intent, final_answer, duration_ms, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (query, intent, final_answer, duration_ms, datetime.now(timezone.utc).isoformat()),
            )
    except sqlite3.Error as exc:
        logger.error("Failed to log interaction: %s", exc)


def log_command_audit(command: str, verdict: str, reason: str, executed: bool) -> None:
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO command_audit (command, verdict, reason, executed, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (command, verdict, reason, int(executed), datetime.now(timezone.utc).isoformat()),
            )
    except sqlite3.Error as exc:
        logger.error("Failed to log command audit: %s", exc)


def get_recent_interactions(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM interactions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
