"""Layer 4 -- JobTech JobStream, Sweden's incremental change feed.

Every job advertised in Sweden is published to Platsbanken, and JobTech exposes
it as a delta feed: ask for everything changed since a timestamp and get back
new ads, edited ads, and -- the part that matters -- **withdrawn ones**. No key,
no quota.

This is the one source that makes a whole hub complete rather than well
covered. Firm-level ATS polling only ever reaches firms we resolved to a feed;
this reaches every Swedish employer, including the ones whose careers page we
tiered C and the ones we have not resolved a domain for at all.

**Delta polling is the whole point, so the cursor is durable.** `feed_state`
holds the last timestamp seen; a run resumes from it and asks only for what
changed. A full re-read is never needed and would be 49 MB a day.

**Resume with overlap.** The cursor is rewound by a few minutes before each
poll. Re-reading an ad costs an idempotent upsert; missing one because it landed
in the same second as the cursor costs a posting, and this project trades
duplicates for coverage every time.

**Withdrawn ads arrive with every field but `id` set to null.** Feeding one
through the normal upsert blanks the title, employer and description of a job we
already hold -- the record survives but becomes unreadable. Removals therefore
take a separate path that touches only `removed_at`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from . import db, http
from .models import Job
from .resolve import domain_of

NAME = "jobtech"
TOKEN = "jobstream"  # one national feed, so the board identifier is constant

URL = "https://jobstream.api.jobtechdev.se/stream?date={since}"

SCHEMA = """
CREATE TABLE IF NOT EXISTS feed_state (
    feed       TEXT PRIMARY KEY,
    cursor     TEXT NOT NULL,   -- epoch milliseconds, as the feed reports them
    updated_at TEXT NOT NULL
);
"""

# Re-read this much on every resume. Cheap insurance against a boundary ad.
OVERLAP = timedelta(minutes=10)

# How far back a first run reaches when there is no cursor yet.
COLD_START = timedelta(hours=24)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def cursor(connection: sqlite3.Connection) -> datetime:
    """Where the next poll starts."""
    connection.executescript(SCHEMA)
    row = connection.execute(
        "SELECT cursor FROM feed_state WHERE feed = ?", (NAME,)
    ).fetchone()
    if not row:
        return datetime.now(timezone.utc) - COLD_START
    seen = datetime.fromtimestamp(int(row["cursor"]) / 1000, timezone.utc)
    return seen - OVERLAP


def save_cursor(connection: sqlite3.Connection, milliseconds: int) -> None:
    with connection:
        connection.execute(
            "INSERT INTO feed_state (feed, cursor, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (feed) DO UPDATE SET cursor = excluded.cursor,"
            " updated_at = excluded.updated_at",
            (NAME, str(milliseconds), db.now()),
        )


def fetch(since: datetime) -> list[dict]:
    return json.loads(http.get_text(URL.format(since=_iso(since)), timeout=180, retries=2))


def _job(ad: dict) -> Job:
    employer = ad.get("employer") or {}
    address = ad.get("workplace_address") or {}
    occupation = ad.get("occupation") or {}
    return Job(
        ats=NAME,
        token=TOKEN,
        job_id=str(ad["id"]),
        title=ad.get("headline") or "",
        # A national feed advertises for everyone, and only half of its ads
        # carry an employer URL we can resolve to a domain. Without the name
        # the other half are postings from nobody.
        employer=employer.get("name") or employer.get("workplace"),
        # The coarse taxonomy bucket -- "Hälso- och sjukvård", "Data/IT" --
        # not the leaf occupation, which is already in `department`. Twenty-odd
        # values, and most of them are trades this project can never want.
        category=(ad.get("occupation_field") or {}).get("label"),
        url=ad.get("webpage_url"),
        location=", ".join(
            part
            for part in (address.get("municipality"), address.get("region"))
            if part
        )
        or None,
        # The taxonomy label, not a guess. Classification stays a read-time job.
        department=occupation.get("label"),
        posted_at=ad.get("publication_date"),
        # The only source in the pipeline that publishes a closing date as a
        # field rather than as prose. Every ad carries one, which is what makes
        # the board's deadline ordering real instead of decorative.
        deadline=ad.get("application_deadline"),
        description=ad.get("description", {}).get("text")
        if isinstance(ad.get("description"), dict)
        else ad.get("description"),
    )


def apply(connection: sqlite3.Connection, ads: list[dict]) -> tuple[int, int, int]:
    """Write a batch. Returns (written, withdrawn, highest timestamp seen)."""
    live = [ad for ad in ads if not ad.get("removed") and ad.get("id")]
    gone = [ad for ad in ads if ad.get("removed") and ad.get("id")]

    written = 0
    for ad in live:
        employer = ad.get("employer") or {}
        # Employer URL is the bridge to `firms`; roughly half of ads carry one.
        db.upsert_jobs(connection, domain_of(employer.get("url")), [_job(ad)])
        written += 1

    with connection:
        connection.executemany(
            "UPDATE jobs SET removed_at = ?, last_seen = ?"
            " WHERE ats = ? AND token = ? AND job_id = ?",
            [
                (ad.get("removed_date") or db.now(), db.now(), NAME, TOKEN, str(ad["id"]))
                for ad in gone
            ],
        )

    latest = max((int(ad["timestamp"]) for ad in ads if ad.get("timestamp")), default=0)
    return written, len(gone), latest


def run(
    connection: sqlite3.Connection, since: datetime | None = None
) -> tuple[int, int, int]:
    """One delta poll. Returns (ads seen, written, withdrawn).

    `since` overrides the stored cursor to replay a window already polled. That
    is what a new column needs: the ads are held but the field was dropped on
    the way in, and re-reading the feed is one request against a source that is
    designed for exactly this. Replay is safe -- every write is an idempotent
    upsert, and the cursor only ever moves to the newest timestamp seen.
    """
    connection.executescript(SCHEMA)
    since = since or cursor(connection)
    ads = fetch(since)
    if not ads:
        return 0, 0, 0

    written, withdrawn, latest = apply(connection, ads)
    if latest:
        save_cursor(connection, latest)
    return len(ads), written, withdrawn
