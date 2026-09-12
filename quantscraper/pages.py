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
CREATE TABLE IF NOT EXISTS page_attempts (
    domain TEXT PRIMARY KEY,
    polled_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS page_watch (
    domain      TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    fingerprint TEXT NOT NULL,   -- hash of the link set
    links       TEXT NOT NULL,   -- the link set itself, newline separated
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    changed_at  TEXT,            -- NULL until the set moves for the first time
    changes     INTEGER NOT NULL DEFAULT 0,
    -- Why a watched page stopped answering, and for how long. `last_seen` is
    -- the last *successful* read and must stay that, because the whole layer
    -- compares one successful read against the next; `polled_at` is the last
    -- attempt, and the gap between them is how long this page has been dark.
    polled_at   TEXT,
    failures    INTEGER NOT NULL DEFAULT 0,  -- consecutive, reset by a success
    error       TEXT
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


@dataclass(frozen=True, slots=True)
class Poll:
    """One attempt at one page: a snapshot, or why there is not one.

    **`snapshot` used to return `None` for three unrelated reasons** -- the
    fetch raised, a hostile host raised something else, or the page came back
    with no same-site links at all -- and `run` counted every one of them as a
    page polled. So a careers page that had 404'd for months was indistinct
    from a healthy page that had not changed, which is the same silence
    `board_polls` was built for one layer up, on a population of 3,593.

    It matters more here than the lower stakes suggest. This layer's only
    output is *a page changed*, and a page that cannot be fetched can never
    report a change -- it drops out of the watch entirely while the report goes
    on counting it as watched.
    """

    domain: str
    shot: Snapshot | None = None
    error: str | None = None


def snapshot(row: sqlite3.Row) -> Poll:
    url = row["careers_url"]
    try:
        body, landed = http.get_with_url(url, timeout=15, retries=1)
    except urllib.error.HTTPError as exc:
        return Poll(row["domain"], error=f"HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = "DNS does not resolve" if "getaddrinfo" in str(exc) else "unreachable"
        return Poll(row["domain"], error=f"{reason}: {type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001 -- one hostile host must not stop the run
        return Poll(row["domain"], error=f"unreadable: {type(exc).__name__}")

    markup = body.decode("utf-8", errors="replace")[:_MAX_MARKUP]
    links = page_links(markup, landed)
    if not links:
        # No same-site links at all means the fetch did not return the page we
        # think it did -- a consent wall, a redirect to a login. Recording an
        # empty set as the baseline would report a change the moment the real
        # page came back, and would call that a hiring signal. Still not a
        # snapshot, and now no longer indistinguishable from a 404 either.
        return Poll(row["domain"], error="no same-site links -- a wall, not the page")
    return Poll(row["domain"], shot=Snapshot(row["domain"], landed, links))


def targets(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Tier-B pages, oldest attempt first, including failed first reads."""
    return connection.execute(
        """
        SELECT a.domain, a.careers_url
        FROM ats_resolution a
        LEFT JOIN page_watch w ON w.domain = a.domain
        LEFT JOIN page_attempts p ON p.domain = a.domain
        WHERE a.tier = 'B' AND a.careers_url IS NOT NULL
        ORDER BY COALESCE(p.polled_at, w.polled_at, w.last_seen), a.domain
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def _record_attempts(connection, domains, timestamp):
    # Separate from successful snapshots: a failed first read has no fingerprint.
    connection.executemany(
        "INSERT INTO page_attempts VALUES (?, ?) ON CONFLICT(domain) "
        "DO UPDATE SET polled_at=excluded.polled_at",
        [(domain, timestamp) for domain in domains],
    )


def record(connection: sqlite3.Connection, shots: list[Snapshot]) -> int:
    """Store snapshots. Returns how many were a change on a known page.

    `changed_at` and `changes` accumulate rather than reset, so a page nobody
    has read yet still shows that it moved -- three times since March is a
    different fact from once last night.
    """
    timestamp = db.now()
    changed = 0
    with connection:
        _record_attempts(connection, (shot.domain for shot in shots), timestamp)
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
                     changed_at, changes, polled_at, failures, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
                ON CONFLICT (domain) DO UPDATE SET
                    url         = excluded.url,
                    fingerprint = excluded.fingerprint,
                    links       = excluded.links,
                    last_seen   = excluded.last_seen,
                    changed_at  = CASE WHEN page_watch.fingerprint != excluded.fingerprint
                                       THEN excluded.last_seen ELSE page_watch.changed_at END,
                    changes     = page_watch.changes
                                  + (page_watch.fingerprint != excluded.fingerprint),
                    -- A success clears the run of failures and the reason for
                    -- them, so `failures` counts the *current* outage rather
                    -- than every one this page has ever had.
                    polled_at   = excluded.polled_at,
                    failures    = 0,
                    error       = NULL
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
                    timestamp,
                ),
            )
    return changed


def record_failures(connection: sqlite3.Connection, polls: list[Poll]) -> int:
    """Count a failed poll against a page already on the watch. Returns how
    many rows were touched.

    **Only a page that has a baseline gets a row here, and that is deliberate
    rather than an omission.** The two states are already distinguishable
    without inventing a sentinel: a page with no `page_watch` row at all has
    never been read successfully, and `coverage` counts exactly those. Writing
    a placeholder row instead would put a fingerprint in the table that no page
    ever produced -- and `record`'s `moved` test compares against whatever is
    stored, so the first real read would come back as *changed*. That is the
    false hiring signal `snapshot` refuses an empty link set to avoid, arriving
    by the other door.

    `last_seen` is deliberately not touched. It is the last *successful* read
    and the whole layer compares one of those against the next; `polled_at`
    carries the attempt, and the gap between the two is the outage.
    """
    timestamp = db.now()
    with connection:
        _record_attempts(connection, (poll.domain for poll in polls), timestamp)
        cursor = connection.executemany(
            "UPDATE page_watch SET polled_at = ?, failures = failures + 1,"
            " error = ? WHERE domain = ?",
            [(timestamp, poll.error, poll.domain) for poll in polls],
        )
    return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0


def run(
    connection: sqlite3.Connection, limit: int, workers: int = 12
) -> tuple[int, int, int, list[Poll]]:
    """Poll tier-B pages. Returns (read, baselined, changed, failures).

    **The first two numbers used to count the failures too.** `polled` was
    incremented before the snapshot was tested, so a page that 404'd was
    reported as a page polled; and `baselined` counted every target that had no
    previous row, whether or not this run managed to read one -- so a page that
    has never once been fetchable was reported as a new baseline on every
    single run. Both now count what actually happened, which is why the first
    is named `read`.
    """
    connection.executescript(SCHEMA)
    rows = targets(connection, limit)
    if not rows:
        return 0, 0, 0, []

    known = {
        row["domain"]
        for row in connection.execute("SELECT domain FROM page_watch")
    }

    read = changed = baselined = 0
    failures: list[Poll] = []
    batch: list[Snapshot] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for poll in pool.map(snapshot, rows):
            if poll.shot is None:
                failures.append(poll)
                continue
            read += 1
            baselined += poll.domain not in known
            batch.append(poll.shot)
            if len(batch) >= 100:
                changed += record(connection, batch)
                batch.clear()
    changed += record(connection, batch)
    # After the successes, so a page that failed this run keeps the baseline it
    # already had and only its counter moves.
    record_failures(connection, failures)
    return read, baselined, changed, failures


def recent_changes(connection: sqlite3.Connection, limit: int = 20):
    connection.executescript(SCHEMA)
    return connection.execute(
        "SELECT domain, url, changed_at, changes FROM page_watch"
        " WHERE changed_at IS NOT NULL ORDER BY changed_at DESC, domain LIMIT ?",
        (limit,),
    ).fetchall()


def coverage(connection: sqlite3.Connection):
    """How much of tier B is actually being watched, and what is dark.

    **`watched` counted every row in `page_watch` against the tier-B total, so
    it printed 3,873 of 3,593 -- 108%, an impossible number.** The excess is
    pages that have since been *promoted*: 318 of them are tier A now and 276
    are yielding real postings, which is this layer succeeding rather than
    failing. But the row stays behind after `targets` stops selecting it, so
    the count drifted above the thing it was a share of. A coverage report that
    overstates itself is the one number nobody re-checks -- the same failure
    `coverage.unmeasured_hubs` had, where a stale hub list claimed three metros
    were measured that nothing had measured.

    So `watched` is now the intersection with tier B, `unwatched` names what is
    missing from it, and `dark` is a page that has a baseline it can no longer
    refresh -- watched in name only.
    """
    connection.executescript(SCHEMA)
    return connection.execute(
        """
        SELECT (SELECT COUNT(*) FROM ats_resolution
                WHERE tier = 'B' AND careers_url IS NOT NULL)  AS tier_b,
               (SELECT COUNT(*) FROM ats_resolution a
                JOIN page_watch w ON w.domain = a.domain
                WHERE a.tier = 'B' AND a.careers_url IS NOT NULL) AS watched,
               (SELECT COUNT(*) FROM ats_resolution a
                LEFT JOIN page_watch w ON w.domain = a.domain
                WHERE a.tier = 'B' AND a.careers_url IS NOT NULL
                  AND w.domain IS NULL)                        AS unwatched,
               (SELECT COUNT(*) FROM ats_resolution a
                JOIN page_watch w ON w.domain = a.domain
                WHERE a.tier = 'B' AND w.failures > 0)         AS dark,
               (SELECT COUNT(*) FROM page_watch
                WHERE changed_at IS NOT NULL)                  AS moved
        """
    ).fetchone()
