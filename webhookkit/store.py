"""Persistence for events and their processing state."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id    TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    sequence    INTEGER NOT NULL,
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | processed | dead
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_status ON events (status, sequence);
"""


@dataclass(frozen=True)
class Event:
    event_id: str
    type: str
    sequence: int
    payload: str
    status: str = "pending"
    attempts: int = 0
    last_error: str | None = None


class SqliteStore:
    def __init__(self, path: str = ":memory:"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)

    def insert_event(self, event: Event, received_at: str) -> bool:
        """Return False when the event id already exists (a provider retry)."""
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "INSERT INTO events (event_id, type, sequence, payload, status, attempts,"
                    " received_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (event.event_id, event.type, event.sequence, event.payload,
                     event.status, event.attempts, received_at))
                return True
            except sqlite3.IntegrityError:
                return False

    def get(self, event_id: str) -> Event | None:
        row = self._conn.execute("SELECT * FROM events WHERE event_id = ?",
                                 (event_id,)).fetchone()
        return self._row(row) if row else None

    def pending(self) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE status = 'pending' ORDER BY sequence").fetchall()
        return [self._row(r) for r in rows]

    def mark(self, event_id: str, status: str, error: str | None = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE events SET status = ?, attempts = attempts + 1, last_error = ?"
                " WHERE event_id = ?", (status, error, event_id))

    def last_processed_sequence(self, event_type: str) -> int:
        """Highest sequence already applied for this event type (0 if none)."""
        row = self._conn.execute(
            "SELECT MAX(sequence) AS m FROM events WHERE type = ? AND status = 'processed'",
            (event_type,)).fetchone()
        return int(row["m"] or 0)

    def count(self, status: str | None = None) -> int:
        if status:
            return self._conn.execute("SELECT COUNT(*) FROM events WHERE status = ?",
                                      (status,)).fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    @staticmethod
    def _row(row: sqlite3.Row) -> Event:
        return Event(row["event_id"], row["type"], row["sequence"], row["payload"],
                     row["status"], row["attempts"], row["last_error"])

    def close(self) -> None:
        self._conn.close()
