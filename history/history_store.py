"""
history_store.py
================
SQLite-backed event store for HeyRudra's time-travel system.

Schema
------
events     – one row per action (file_create, file_edit, file_delete, shell_command)
snapshots  – full directory snapshots taken every 10 events (fast restore)
action_groups – labels for AI-grouped multi-step operations
"""

import os
import json
import uuid
import sqlite3
from datetime import datetime

# DB lives inside the project's /history folder
_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history")
DB_PATH = os.path.join(_DB_DIR, "heyrudra_history.db")

SNAPSHOT_EVERY = 10   # take a full snapshot every N events


# ─── Connection ────────────────────────────────────────────────────────────────

def _conn():
    os.makedirs(_DB_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


# ─── Schema ────────────────────────────────────────────────────────────────────

def init_db():
    c = _conn()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id             TEXT PRIMARY KEY,
            type           TEXT NOT NULL,
            filename       TEXT,
            content_before TEXT,
            content_after  TEXT,
            command        TEXT,
            label          TEXT,
            group_id       TEXT,
            parent_id      TEXT,
            timestamp      TEXT NOT NULL,
            cwd            TEXT
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id         TEXT PRIMARY KEY,
            event_id   TEXT,
            files_json TEXT,
            timestamp  TEXT NOT NULL,
            cwd        TEXT
        );

        CREATE TABLE IF NOT EXISTS action_groups (
            id        TEXT PRIMARY KEY,
            label     TEXT,
            timestamp TEXT NOT NULL
        );
    """)
    c.commit()
    c.close()


# ─── Write ─────────────────────────────────────────────────────────────────────

def record_event(
    type_,
    filename=None,
    content_before=None,
    content_after=None,
    command=None,
    label=None,
    group_id=None,
    cwd=None,
):
    """Insert one event and optionally take a snapshot every N events."""
    init_db()
    c = _conn()

    # Find parent
    row = c.execute(
        "SELECT id FROM events WHERE cwd=? ORDER BY timestamp DESC LIMIT 1", (cwd,)
    ).fetchone()
    parent_id = row["id"] if row else None

    event_id = str(uuid.uuid4())
    ts = datetime.now().isoformat()

    c.execute(
        """INSERT INTO events
           (id, type, filename, content_before, content_after,
            command, label, group_id, parent_id, timestamp, cwd)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (event_id, type_, filename, content_before, content_after,
         command, label, group_id, parent_id, ts, cwd),
    )
    c.commit()

    # Periodic snapshot
    count = c.execute(
        "SELECT COUNT(*) AS n FROM events WHERE cwd=?", (cwd,)
    ).fetchone()["n"]
    if count % SNAPSHOT_EVERY == 0:
        _take_snapshot(c, event_id, cwd)

    c.close()
    return event_id


def _take_snapshot(c, event_id, cwd):
    """Write a full directory snapshot to the snapshots table."""
    if not cwd or not os.path.isdir(cwd):
        return
    files = {}
    try:
        for fname in os.listdir(cwd):
            fpath = os.path.join(cwd, fname)
            if os.path.isfile(fpath) and not fname.startswith("."):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        files[fname] = f.read()
                except Exception:
                    pass
    except Exception:
        pass

    c.execute(
        "INSERT INTO snapshots (id, event_id, files_json, timestamp, cwd) VALUES (?,?,?,?,?)",
        (str(uuid.uuid4()), event_id, json.dumps(files), datetime.now().isoformat(), cwd),
    )
    c.commit()


def create_group(label):
    """Create an action group and return its id."""
    init_db()
    gid = str(uuid.uuid4())
    c = _conn()
    c.execute(
        "INSERT INTO action_groups (id, label, timestamp) VALUES (?,?,?)",
        (gid, label, datetime.now().isoformat()),
    )
    c.commit()
    c.close()
    return gid


# ─── Read ──────────────────────────────────────────────────────────────────────

def get_history(limit=20, cwd=None):
    init_db()
    c = _conn()
    if cwd:
        rows = c.execute(
            "SELECT * FROM events WHERE cwd=? ORDER BY timestamp DESC LIMIT ?",
            (cwd, limit),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_event_by_id(event_id):
    init_db()
    c = _conn()
    row = c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    c.close()
    return dict(row) if row else None


def get_events_in_group(group_id):
    init_db()
    c = _conn()
    rows = c.execute(
        "SELECT * FROM events WHERE group_id=? ORDER BY timestamp ASC", (group_id,)
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_nearest_snapshot_before(event_timestamp, cwd):
    """Return the most recent snapshot taken before event_timestamp."""
    init_db()
    c = _conn()
    row = c.execute(
        """SELECT * FROM snapshots
           WHERE cwd=? AND timestamp <= ?
           ORDER BY timestamp DESC LIMIT 1""",
        (cwd, event_timestamp),
    ).fetchone()
    c.close()
    return dict(row) if row else None


def get_events_after_snapshot(snapshot_timestamp, cwd):
    """Return all events recorded after a snapshot timestamp."""
    init_db()
    c = _conn()
    rows = c.execute(
        "SELECT * FROM events WHERE cwd=? AND timestamp > ? ORDER BY timestamp ASC",
        (cwd, snapshot_timestamp),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def total_event_count(cwd=None):
    init_db()
    c = _conn()
    if cwd:
        n = c.execute(
            "SELECT COUNT(*) AS n FROM events WHERE cwd=?", (cwd,)
        ).fetchone()["n"]
    else:
        n = c.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]
    c.close()
    return n
