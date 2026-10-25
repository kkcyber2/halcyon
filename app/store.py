"""SQLite persistence. Same schema local and deployed, no ORM."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.booking import Booking, SlotKind

DB_PATH = os.environ.get("HALCYON_DB", "halcyon.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT    NOT NULL,
    start_iso   TEXT    NOT NULL,
    duration    INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL,
    company     TEXT    DEFAULT '',
    brief       TEXT    DEFAULT '',
    reference   TEXT    NOT NULL UNIQUE,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_start ON bookings(start_iso);

CREATE TABLE IF NOT EXISTS enquiries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    email       TEXT    NOT NULL,
    budget      TEXT    DEFAULT '',
    message     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""


def connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init(path: str | None = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def session(path: str | None = None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_booking(row: sqlite3.Row) -> Booking:
    return Booking(
        kind=SlotKind(row["kind"]),
        start=datetime.fromisoformat(row["start_iso"]),
        duration_min=row["duration"],
        reference=row["reference"],
    )


def list_bookings(path: str | None = None) -> list[Booking]:
    with session(path) as conn:
        rows = conn.execute("SELECT * FROM bookings ORDER BY start_iso").fetchall()
    return [_row_to_booking(r) for r in rows]


def list_bookings_detail(path: str | None = None) -> list[dict]:
    """Bookings plus the client-facing detail, for the admin view."""
    with session(path) as conn:
        rows = conn.execute("SELECT * FROM bookings ORDER BY start_iso").fetchall()
    return [
        {
            "reference": r["reference"],
            "kind": r["kind"],
            "start": r["start_iso"],
            "duration": r["duration"],
            "name": r["name"],
            "email": r["email"],
            "company": r["company"],
            "brief": r["brief"],
        }
        for r in rows
    ]


def get_booking_detail(reference: str, path: str | None = None) -> dict | None:
    """One booking by its public reference, or None when it does not exist."""
    with session(path) as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE reference = ?", (reference,)
        ).fetchone()
    if row is None:
        return None
    return {
        "reference": row["reference"],
        "kind": row["kind"],
        "start": row["start_iso"],
        "duration": row["duration"],
        "name": row["name"],
        "email": row["email"],
        "company": row["company"],
        "brief": row["brief"],
    }


def add_booking(
    kind: SlotKind,
    start: datetime,
    duration: int,
    name: str,
    email: str,
    reference: str,
    company: str = "",
    brief: str = "",
    path: str | None = None,
) -> None:
    with session(path) as conn:
        conn.execute(
            "INSERT INTO bookings (kind, start_iso, duration, name, email, company, brief,"
            " reference, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                kind.value,
                start.isoformat(),
                duration,
                name,
                email,
                company,
                brief,
                reference,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def count_bookings_on(day_iso: str, path: str | None = None) -> int:
    with session(path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE start_iso LIKE ?", (f"{day_iso}%",)
        ).fetchone()[0]


def add_enquiry(name: str, email: str, message: str, budget: str = "",
                path: str | None = None) -> None:
    with session(path) as conn:
        conn.execute(
            "INSERT INTO enquiries (name, email, budget, message, created_at)"
            " VALUES (?,?,?,?,?)",
            (name, email, budget, message, datetime.now().isoformat(timespec="seconds")),
        )
