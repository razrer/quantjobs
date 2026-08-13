"""SQLite storage for the employer universe.

Two tables, and both are append-only in spirit:

`employers` is never deleted from. A firm that drops out of a registry keeps
its row and simply stops having `last_seen` refreshed -- membership of the
universe is permanent, because silently dropping an employer is the single
most expensive mistake this system can make.

`runs` records the row count of every fetch. That history is what lets us
notice later that a source which normally returns 3,000 rows returned 4.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from .models import Employer

DEFAULT_PATH = Path("employers.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS employers (
    source        TEXT NOT NULL,   -- registry that reported this firm
    source_id     TEXT NOT NULL,   -- that registry's own key
    jurisdiction  TEXT NOT NULL,   -- regulator's jurisdiction, ISO 3166-1 alpha-2
    name          TEXT NOT NULL,
    category      TEXT,            -- registry's own classification, verbatim
    city          TEXT,
    country       TEXT,            -- where the firm is, which is not the regulator
    website       TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    row_count   INTEGER NOT NULL,
    ok          INTEGER NOT NULL,
    error       TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | str = DEFAULT_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def upsert_employers(
    connection: sqlite3.Connection,
    source: str,
    jurisdiction: str,
    employers: Iterable[Employer],
) -> int:
    """Insert or refresh employers. Returns the number of rows written."""
    timestamp = now()
    rows = [
        (
            source,
            employer.source_id,
            jurisdiction,
            employer.name,
            employer.category,
            employer.city,
            employer.country,
            employer.website,
            timestamp,
            timestamp,
        )
        for employer in employers
    ]
    with connection:
        connection.executemany(
            """
            INSERT INTO employers (source, source_id, jurisdiction, name, category,
                                   city, country, website, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, source_id) DO UPDATE SET
                name      = excluded.name,
                category  = excluded.category,
                city      = excluded.city,
                country   = excluded.country,
                website   = COALESCE(excluded.website, employers.website),
                last_seen = excluded.last_seen
            """,
            rows,
        )
    return len(rows)


def record_run(
    connection: sqlite3.Connection,
    source: str,
    started_at: str,
    row_count: int,
    ok: bool,
    error: str | None = None,
) -> None:
    with connection:
        connection.execute(
            "INSERT INTO runs (source, started_at, row_count, ok, error)"
            " VALUES (?, ?, ?, ?, ?)",
            (source, started_at, row_count, int(ok), error),
        )
