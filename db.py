"""SQLite connection and schema for the Orbit Air baggage desk."""

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    id          INTEGER PRIMARY KEY,
    passenger   TEXT NOT NULL CHECK (trim(passenger) <> ''),
    flight      TEXT NOT NULL CHECK (trim(flight) <> ''),
    claim_type  TEXT NOT NULL CHECK (claim_type IN ('delayed', 'lost', 'damaged')),
    tier        TEXT NOT NULL CHECK (tier IN ('gold', 'silver', 'standard')),
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'assigned', 'escalated', 'resolved', 'closed')),
    agent       TEXT,
    note        TEXT,
    filed_at    TEXT NOT NULL,
    deadline    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY,
    claim_id    INTEGER NOT NULL REFERENCES claims (id),
    old_status  TEXT,
    new_status  TEXT NOT NULL,
    changed_by  TEXT NOT NULL,
    changed_at  TEXT NOT NULL
);
"""


def connect(path):
    """Open a SQLite database with foreign keys on and rows readable by name."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_tables(conn):
    """Create the claims and history tables if they don't exist yet."""
    conn.executescript(SCHEMA)
