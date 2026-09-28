"""
Persistence layer.

Two tables:
  candidates(id, name, created_at)
  events(id, candidate_id, event_type, from_stage, to_stage, at, note)

`events` is the audit trail. Rows are only ever INSERTed, never UPDATEd or
DELETEd, from application code. A candidate's current stage is always
derived by reading the latest event for that candidate -- there is no
separate "current_stage" column to fall out of sync.
"""
import sqlite3
import os

from .timeutil import now_iso

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,      -- 'created', 'advanced', 'rejected'
    from_stage TEXT,               -- NULL for 'created'
    to_stage TEXT NOT NULL,
    at TEXT NOT NULL,              -- ISO 8601 UTC timestamp
    note TEXT,
    FOREIGN KEY (candidate_id) REFERENCES candidates(id)
);

CREATE INDEX IF NOT EXISTS idx_events_candidate ON events(candidate_id);
"""


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # If another process/thread is mid-write, wait up to 5s instead of
    # immediately raising "database is locked".
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def reset_db():
    """Wipe all data. Used only by the seed script / tests."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()


# ---------------------------------------------------------------------------
# Writes (append-only)
# ---------------------------------------------------------------------------

def create_candidate(name, note=None):
    conn = get_conn()
    try:
        ts = now_iso()
        cur = conn.execute(
            "INSERT INTO candidates (name, created_at) VALUES (?, ?)",
            (name, ts),
        )
        candidate_id = cur.lastrowid
        conn.execute(
            "INSERT INTO events (candidate_id, event_type, from_stage, to_stage, at, note) "
            "VALUES (?, 'created', NULL, 'Applied', ?, ?)",
            (candidate_id, ts, note),
        )
        conn.commit()
        return candidate_id
    finally:
        conn.close()


def record_event(candidate_id, event_type, from_stage, to_stage, note=None):
    conn = get_conn()
    try:
        ts = now_iso()
        conn.execute(
            "INSERT INTO events (candidate_id, event_type, from_stage, to_stage, at, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (candidate_id, event_type, from_stage, to_stage, ts, note),
        )
        conn.commit()
        return ts
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_candidate(candidate_id):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_events(candidate_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM events WHERE candidate_id = ? ORDER BY id ASC",
            (candidate_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_events():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM events ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_candidates():
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM candidates ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
