"""Layer 3B -- watching the careers pages that run on no ATS at all.

Stage 5 tiers every domain. Tier A has a feed and Layer 3 polls it; **tier B is
3,839 firms with a careers page and nothing recognisable behind it**, and until
now nothing looked at them at all. That is the largest remaining hole in the
pipeline, and it is invisible from the tier table, which reports tier B as a
successful classification rather than as a queue.

**This watches for change; it does not extract postings, and the difference is
deliberate.** Reconnaissance on a sample of tier-B pages settles it: they carry
16 to 79 links each and between one and seven that mention a job word, and
those are `Careers`, `View Careers` and `mailto:careers@`. The individual
postings are not in the markup -- they are rendered by script, or they are not
there at all. An extractor over that emits a firm's own navigation as job
postings, which is worse than emitting nothing: it fills `jobs` with rows that
look real and are not, and read-time classification cannot undo a row that was
never a posting.

**The fingerprint is the set of links, not the text.** Page text churns on
every visit -- timestamps, cookie banners, rotating quotes -- so a text hash
reports a change every run and a change reported every run is not a signal.
Links are stable, and the way a posting normally reaches a page is by adding
one. When a firm's page is script-rendered and its links never move, this
reports nothing, which is the honest answer rather than a manufactured one.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import db, http

SCHEMA = """
CREATE TABLE IF NOT EXISTS page_watch (
    domain      TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    fingerprint TEXT NOT NULL,   -- hash of the link set
    links       TEXT NOT NULL,   -- the link set itself, newline separated
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    changed_at  TEXT,            -- NULL until the set moves for the first time
    changes     INTEGER NOT NULL DEFAULT 0
);
"""

# Bounded, and the words are matched in Python -- the unbounded version of this
# pattern is what stalled two `ats` runs for two and a half hours. See
# `ats.py` for the full account; the lesson is that a regex over fetched markup
# fails as a stall rather than an error.
_HREF = re.compile(r'href=["\']([^"\']{0,2000})["\']', re.I)

# A careers page is HTML. Anything larger than this is a media file wearing a
# content type, and scanning it holds up every other worker through the GIL.
_MAX_MARKUP = 2_000_000

# Enough to describe any real careers page. A page that offers more than this
# is a sitemap or a blog index, and its links are not what changed.
_MAX_LINKS = 500


@dataclass(frozen=True, slots=True)
class Snapshot:
    domain: str
    url: str
    links: list[str]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256("\n".join(self.links).encode()).hexdigest()[:32]


def page_links(markup: str, url: str) -> list[str]:
    """Same-site links from `markup`, as sorted unique paths.

    Query strings and fragments are dropped: a session id or a `?srsltid=`
    tracking parameter differs on every fetch, and keeping them would report a
    change on every poll for pages that never changed. Off-site links go too --
    a firm's social buttons and its CDN move for reasons that are not hiring.
    """
    site = urllib.parse.urlsplit(url)
    host = site.netloc.casefold().removeprefix("www.")
    found: set[str] = set()

    for href in _HREF.findall(markup):
        target = urllib.parse.urlsplit(urllib.parse.urljoin(url, href.strip()))
        if target.scheme not in ("http", "https"):
            continue  # mailto:, tel:, javascript:
        if target.netloc.casefold().removeprefix("www.") != host:
            continue
        path = target.path.rstrip("/") or "/"
        found.add(path)
        if len(found) >= _MAX_LINKS:
            break

    return sorted(found)


def snapshot(row: sqlite3.Row) -> Snapshot | None:
    url = row["careers_url"]
    try:
        body, landed = http.get_with_url(url, timeout=15, retries=1)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    except Exception:  # noqa: BLE001 -- one hostile host must not stop the run
        return None

    markup = body.decode("utf-8", errors="replace")[:_MAX_MARKUP]
    links = page_links(markup, landed)
    if not links:
        # No same-site links at all means the fetch did not return the page we
        # think it did -- a consent wall, a redirect to a login. Recording an
        # empty set as the baseline would report a change the moment the real
        # page came back, and would call that a hiring signal.
        return None
    return Snapshot(row["domain"], landed, links)


def targets(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Tier-B pages, least recently seen first, unseen pages before those."""
    return connection.execute(
        """
        SELECT a.domain, a.careers_url
        FROM ats_resolution a
        LEFT JOIN page_watch w ON w.domain = a.domain
        WHERE a.tier = 'B' AND a.careers_url IS NOT NULL
        ORDER BY w.last_seen IS NOT NULL, w.last_seen, a.domain
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def record(connection: sqlite3.Connection, shots: list[Snapshot]) -> int:
    """Store snapshots. Returns how many were a change on a known page.

    `changed_at` and `changes` accumulate rather than reset, so a page nobody
    has read yet still shows that it moved -- three times since March is a
    different fact from once last night.
    """
    timestamp = db.now()
    changed = 0
    with connection:
        for shot in shots:
            previous = connection.execute(
                "SELECT fingerprint FROM page_watch WHERE domain = ?", (shot.domain,)
            ).fetchone()
            moved = previous is not None and previous["fingerprint"] != shot.fingerprint
            changed += moved
            connection.execute(
                """
                INSERT INTO page_watch
                    (domain, url, fingerprint, links, first_seen, last_seen,
                     changed_at, changes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (domain) DO UPDATE SET
                    url         = excluded.url,
                    fingerprint = excluded.fingerprint,
                    links       = excluded.links,
                    last_seen   = excluded.last_seen,
                    changed_at  = CASE WHEN page_watch.fingerprint != excluded.fingerprint
                                       THEN excluded.last_seen ELSE page_watch.changed_at END,
                    changes     = page_watch.changes
                                  + (page_watch.fingerprint != excluded.fingerprint)
                """,
                (
                    shot.domain,
                    shot.url,
                    shot.fingerprint,
                    "\n".join(shot.links),
                    timestamp,
                    timestamp,
                    timestamp if moved else None,
                    1 if moved else 0,
                ),
            )
    return changed


def run(
    connection: sqlite3.Connection, limit: int, workers: int = 12
) -> tuple[int, int, int]:
    """Poll tier-B pages. Returns (polled, baselined, changed)."""
    connection.executescript(SCHEMA)
    rows = targets(connection, limit)
    if not rows:
        return 0, 0, 0

    known = {
        row["domain"]
        for row in connection.execute("SELECT domain FROM page_watch")
    }

    polled = changed = 0
    batch: list[Snapshot] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for shot in pool.map(snapshot, rows):
            polled += 1
            if shot is None:
                continue
            batch.append(shot)
            if len(batch) >= 100:
                changed += record(connection, batch)
                batch.clear()
    changed += record(connection, batch)

    baselined = sum(1 for row in rows if row["domain"] not in known)
    return polled, baselined, changed


def recent_changes(connection: sqlite3.Connection, limit: int = 20):
    connection.executescript(SCHEMA)
    return connection.execute(
        "SELECT domain, url, changed_at, changes FROM page_watch"
        " WHERE changed_at IS NOT NULL ORDER BY changed_at DESC, domain LIMIT ?",
        (limit,),
    ).fetchall()


def coverage(connection: sqlite3.Connection):
    connection.executescript(SCHEMA)
    return connection.execute(
        """
        SELECT (SELECT COUNT(*) FROM ats_resolution
                WHERE tier = 'B' AND careers_url IS NOT NULL) AS tier_b,
               (SELECT COUNT(*) FROM page_watch)              AS watched,
               (SELECT COUNT(*) FROM page_watch
                WHERE changed_at IS NOT NULL)                 AS moved
        """
    ).fetchone()
