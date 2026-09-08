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

-- Where a delta feed resumes. Two sources keep a cursor -- JobStream's is epoch
-- milliseconds and job-room.ch's is a date -- and it is one column because the
-- *shape* of a cursor is the source's business and the storage is not. It lived
-- in both modules, as two `CREATE TABLE` statements free to drift.
CREATE TABLE IF NOT EXISTS feed_state (
    feed       TEXT PRIMARY KEY,
    cursor     TEXT NOT NULL,   -- opaque here; the reader knows what it means
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    row_count   INTEGER NOT NULL,
    ok          INTEGER NOT NULL,
    error       TEXT
);

-- What each Layer 3 board answered, and how long it has been answering it.
--
-- **`runs` is per *source* and Layer 3 is a thousand boards under one name**,
-- so a board that has 404'd every week for months was invisible to every report
-- here: `extract.run` returned its failures, `cli._jobs` printed the first ten
-- and dropped the rest, and `alerts` -- whose whole job is noticing silence --
-- reads `runs` and therefore could not see Layer 3 at all. Measured over all
-- 1,182 tier-A boards: 42 fail, and 27 of those are 404s holding no postings,
-- which is the population that makes the other fifteen unreadable.
--
-- One row per board rather than one per poll, because the question is "is this
-- board still answering", not "what did it say in March". `failures` is
-- **consecutive** and resets on any success, so it separates a vendor having a
-- bad morning from a board that has been dead since spring.
--
-- **Deliberately reported and never acted on automatically.** Retiring a board
-- on N failures is the obvious next step and it is unsafe: Topdanmark's board
-- answered 422 on every pod and every request body while Workday's own status
-- page read "we are experiencing a service interruption" -- a vendor outage is
-- indistinguishable from a dead board from here, and auto-retiring during one
-- would delete every posting on every board that vendor serves.
CREATE TABLE IF NOT EXISTS board_polls (
    ats        TEXT NOT NULL,
    token      TEXT NOT NULL,
    domain     TEXT,
    polled_at  TEXT NOT NULL,   -- the most recent attempt, successful or not
    ok         INTEGER NOT NULL,
    postings   INTEGER,         -- what the last successful poll returned
    failures   INTEGER NOT NULL DEFAULT 0,   -- consecutive, reset by a success
    last_ok    TEXT,
    error      TEXT,
    PRIMARY KEY (ats, token)
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
    # **WAL is here for the concurrency, not the speed** -- measured, it is
    # worth about 1.1x on the writes, and classification dominates a re-tag
    # roughly three to one. What it buys is a reader running while a writer
    # holds the database, which is what the `busy_timeout` above exists to
    # survive: `domains` and `ats` are both hours against different hosts and
    # are meant to run side by side.
    #
    # `NORMAL` rather than `FULL` is the deliberate half. Under WAL it is
    # durable against a process crash and gives up only the last commits to an
    # OS or power failure -- and every table it protects here is derived and
    # rebuilt on demand. The raw registry tables are append-only and written
    # once per fetch, where the cost does not arise.
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
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
    # `page_watch` is created by `pages.SCHEMA` rather than by this module's,
    # and that is fine: `_migrate` skips a table that does not exist yet, and a
    # fresh install gets these from the `CREATE TABLE` there. Only an install
    # that already has the table needs them added.
    ("page_watch", "polled_at", "TEXT"),
    ("page_watch", "failures", "INTEGER NOT NULL DEFAULT 0"),
    ("page_watch", "error", "TEXT"),
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


def cursor(connection: sqlite3.Connection, feed: str) -> str | None:
    """The stored resume point for `feed`, or None if it has never run."""
    row = connection.execute(
        "SELECT cursor FROM feed_state WHERE feed = ?", (feed,)
    ).fetchone()
    return row["cursor"] if row else None


def save_cursor(connection: sqlite3.Connection, feed: str, value: str) -> None:
    """Move `feed`'s resume point. Written as text; the reader decodes it."""
    with connection:
        connection.execute(
            "INSERT INTO feed_state (feed, cursor, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (feed) DO UPDATE SET cursor = excluded.cursor,"
            " updated_at = excluded.updated_at",
            (feed, value, now()),
        )


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


def record_board_polls(
    connection: sqlite3.Connection, outcomes: Iterable[tuple]
) -> int:
    """Record what each board answered. `outcomes` is `(ats, token, domain,
    ok, postings, error)`.

    **`failures` is consecutive and the arithmetic happens in the `ON CONFLICT`
    clause on purpose.** Reading the old count into Python and writing it back
    is a read-modify-write, which is the race that emptied `labels.csv` once
    already; letting SQLite do `failures + 1` in the same statement cannot lose
    a poll. The values in `VALUES` are the *first* poll of a board -- the insert
    branch -- and the `DO UPDATE` branch is every poll after it.

    A failure deliberately leaves `postings` and `last_ok` alone, so the row
    still says what the board held when it last worked. That is the number
    worth having when deciding whether a dead board matters.
    """
    timestamp = now()
    rows = [
        (
            ats, token, domain, timestamp, int(bool(ok)),
            postings if ok else None,   # a failure keeps what the board held
            0 if ok else 1,             # this row's own first outcome
            timestamp if ok else None,
            None if ok else error,
        )
        for ats, token, domain, ok, postings, error in outcomes
    ]
    with connection:
        connection.executemany(
            """
            INSERT INTO board_polls
                (ats, token, domain, polled_at, ok, postings, failures,
                 last_ok, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (ats, token) DO UPDATE SET
                domain    = excluded.domain,
                polled_at = excluded.polled_at,
                ok        = excluded.ok,
                postings  = CASE WHEN excluded.ok THEN excluded.postings
                                 ELSE board_polls.postings END,
                failures  = CASE WHEN excluded.ok THEN 0
                                 ELSE board_polls.failures + 1 END,
                last_ok   = CASE WHEN excluded.ok THEN excluded.polled_at
                                 ELSE board_polls.last_ok END,
                error     = excluded.error
            """,
            rows,
        )
    return len(rows)


def prune_board_polls(connection: sqlite3.Connection) -> int:
    """Forget boards nothing polls any more. Returns rows removed.

    **The `sites.py` lesson one table over, and it appeared the same week.**
    Norron's reader was removed on purpose and `sites.register` now withdraws
    its `ats_resolution` row -- but its `board_polls` row stayed, so
    `failing_boards` went on reporting a board that no longer exists and
    `alerts` would have carried it forever. A capability removed needs every
    registration removed with it, and this table is a second registration.

    Pruned on *not resolvable* rather than on *not polled this run*, which is
    the distinction that makes it safe: `jobs --limit` deliberately polls a
    subset, so deleting whatever a run did not reach would throw away the
    history of every board below the limit.
    """
    with connection:
        cursor = connection.execute(
            """
            DELETE FROM board_polls
            WHERE NOT EXISTS (
                SELECT 1 FROM ats_resolution a
                WHERE a.ats = board_polls.ats
                  AND a.token = board_polls.token
                  AND a.tier = 'A'
            )
            """
        )
    return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0


def failing_boards(
    connection: sqlite3.Connection, minimum: int = 1
) -> list[sqlite3.Row]:
    """Boards whose last poll failed, worst first.

    Ordered by what they are costing rather than by how long they have been
    broken: a board that has failed twice holding 879 postings matters more
    than one that has failed thirty times holding none, and the 404s in this
    corpus are overwhelmingly the second kind.
    """
    return connection.execute(
        "SELECT * FROM board_polls WHERE ok = 0 AND failures >= ?"
        " ORDER BY COALESCE(postings, 0) DESC, failures DESC",
        (minimum,),
    ).fetchall()
