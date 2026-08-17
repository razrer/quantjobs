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

CREATE TABLE IF NOT EXISTS jobs (
    ats          TEXT NOT NULL,   -- greenhouse, workday, teamtailor, ...
    token        TEXT NOT NULL,   -- that ATS's board identifier
    job_id       TEXT NOT NULL,   -- the ATS's own posting id
    domain       TEXT,            -- firm domain this board was reached from
    employer     TEXT,            -- advertiser as the source named it, where
                                  -- the board is not the firm's own (JobStream)
    category     TEXT,            -- the source's own occupation classification
    title        TEXT NOT NULL,
    url          TEXT,
    location     TEXT,
    department   TEXT,
    posted_at    TEXT,
    deadline     TEXT,            -- closing date, only where the source states one
    description  TEXT,
    removed_at   TEXT,            -- withdrawn by the employer; never deleted
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    PRIMARY KEY (ats, token, job_id)
);

CREATE INDEX IF NOT EXISTS jobs_by_domain ON jobs (domain);

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
    # The long Layer 2 queues are meant to be run side by side -- `domains` and
    # `ats` are both hours of wall time against different hosts. Their writes
    # are batched and brief, but the default five-second wait is short enough
    # that one landing mid-batch aborts a run and loses the work since its last
    # flush. Waiting is always the better trade here.
    connection.execute("PRAGMA busy_timeout = 60000")
    connection.executescript(SCHEMA)
    _migrate(connection)
    return connection


# Columns added after `jobs` already existed somewhere. `CREATE TABLE IF NOT
# EXISTS` is a no-op on an existing table, so a new column has to be added
# explicitly or every install predating it reads as corrupt.
_ADDED_COLUMNS = (
    ("jobs", "removed_at", "TEXT"),
    ("jobs", "deadline", "TEXT"),
    ("jobs", "employer", "TEXT"),
    ("jobs", "category", "TEXT"),
)


def _migrate(connection: sqlite3.Connection) -> None:
    for table, column, kind in _ADDED_COLUMNS:
        existing = {
            row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if existing and column not in existing:
            with connection:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {kind}"
                )


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


def upsert_jobs(
    connection: sqlite3.Connection, domain: str | None, jobs: Iterable["object"]
) -> int:
    """Insert or refresh postings. Returns the number of rows written.

    A posting that disappears keeps its row and stops having `last_seen`
    refreshed, the same rule `employers` follows: deleting is how a listing
    goes missing without anything announcing it.
    """
    timestamp = now()
    rows = [
        (
            job.ats,
            job.token,
            job.job_id,
            domain,
            job.employer,
            job.category,
            job.title,
            job.url,
            job.location,
            job.department,
            job.posted_at,
            job.deadline,
            job.description,
            timestamp,
            timestamp,
        )
        for job in jobs
    ]
    with connection:
        connection.executemany(
            """
            INSERT INTO jobs (ats, token, job_id, domain, employer, category,
                              title, url, location, department, posted_at,
                              deadline, description, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ats, token, job_id) DO UPDATE SET
                employer    = COALESCE(excluded.employer, jobs.employer),
                category    = COALESCE(excluded.category, jobs.category),
                title       = excluded.title,
                url         = excluded.url,
                location    = excluded.location,
                department  = excluded.department,
                posted_at   = excluded.posted_at,
                -- An employer moving its closing date must move ours, so a new
                -- value wins; a source that simply stopped publishing one must
                -- not silently erase a date we already showed, so NULL loses.
                deadline    = COALESCE(excluded.deadline, jobs.deadline),
                description = COALESCE(excluded.description, jobs.description),
                last_seen   = excluded.last_seen
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
