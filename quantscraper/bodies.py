"""Layer 3C -- fetching the description a list endpoint did not carry.

**55,828 of 72,471 postings have no body, and it is one source's doing.**
Workday is the largest board format in the pipeline by a wide margin, and its
CXS *list* endpoint returns a title, a location and a path -- no description at
all. Every other reader gets a body for free from the same request that lists
the job, so nothing made this visible; the postings look complete until you ask
what the tagger had to work with.

**This is the tagger's precision problem, not a cosmetic one.** `fit: unknown`
and `relevance: unknown` are the same 12,365 postings, and 4,696 of the ones
reaching the board are Workday. `lexicon.judge` deliberately refuses to reject
a bare `Analyst`, `Associate` or `Specialist` on its title -- that refusal is
correct and it is why the bucket exists -- so the only way to empty it is to
give the classifier the text it was designed to read. A widened word list
cannot substitute: the words in those titles are the ones every employer uses.

**Fetched on demand rather than during extraction.** A body is one request per
posting, so backfilling all of Workday is 53,000 requests where listing it was
about 3,000. Doing that at extraction time would multiply every poll of every
board forever, to fill in postings most of which are gated off the board for
being in the wrong place or the wrong profession. Instead this runs over the
queue that would actually change an answer -- postings the tagger could not
classify -- most promising first, and it is resumable because a filled body is
its own record of having been fetched.

**`jobs.description` is a derived column and may be written.** Principle 5
makes `employers` append-only; `jobs` already has its description refreshed by
`db.upsert_jobs` on every poll, so filling a NULL is the same operation
arriving by another route.

**Jobbsafari is the second source with the same shape**, and it arrived with
48,173 Swedish postings. Its list endpoint carries a title, a company and a
place; the description lives on the detail page, which is 161 KB a posting on
the data route -- so backfilling all of Sweden would be 7.8 GB where listing it
was 98 requests. The queue is the answer here for exactly the reason it was for
Workday.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor

from . import db, http, jobbsafari, tagging

_TAGS = re.compile(r"<[^>]+>")

# Workday's detail endpoint returns the whole posting; only the description is
# wanted, and the rest is large. Bodies are capped for the same reason
# `ats.py` caps fetched markup: the tagger runs hundreds of patterns over this
# string, and one 400 KB posting stalls the pool through the GIL.
_MAX_BODY = 40_000


def _clean(html: str | None) -> str | None:
    if not html:
        return None
    return " ".join(_TAGS.sub(" ", html).split())[:_MAX_BODY] or None


def workday_body(row) -> str | None:
    """The description for one Workday posting.

    `token` is `tenant|wdN|site[|host]` and `job_id` is the `externalPath` the
    list endpoint returned, which is exactly what the detail endpoint appends.
    Both Workday hosts are handled the same way they are in `extract.workday`.
    """
    token, path = row["token"], row["job_id"]
    parts = token.split("|")
    if len(parts) not in (3, 4) or not path:
        return None
    tenant, wd, site = parts[:3]
    host = parts[3] if len(parts) == 4 else "myworkdayjobs.com"
    origin = (
        f"https://{wd}.{host}"
        if host == "myworkdaysite.com"
        else f"https://{tenant}.{wd}.{host}"
    )
    url = f"{origin}/wday/cxs/{tenant}/{site}{path}"
    try:
        payload = json.loads(http.get_text(url, timeout=25, retries=1))
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError,
            TimeoutError, OSError):
        return None
    except Exception:  # noqa: BLE001 -- one hostile tenant must not stop the run
        return None
    info = payload.get("jobPostingInfo")
    if not isinstance(info, dict):
        return None
    return _clean(info.get("jobDescription"))


# One deploy id for the whole run. **Behind a lock, because this pass runs
# twelve threads and the id is one shared cell**: a bare `list.clear()` then
# `list.append()` leaves a window in which another worker reads index 0 of an
# empty list, and an `IndexError` raised inside `pool.map` ends the run rather
# than the posting.
_JOBBSAFARI_DEPLOY: list[str] = []
_DEPLOY_LOCK = threading.Lock()


def _jobbsafari_deploy(*, refresh: bool = False) -> str | None:
    """The current deploy id, fetching or re-fetching it at most once at a time.

    `jobbsafari.build_id()` is one HTTP call and it happens inside the lock on
    purpose: twelve workers discovering a stale id at the same moment should
    make one request between them, not twelve.
    """
    with _DEPLOY_LOCK:
        if refresh:
            _JOBBSAFARI_DEPLOY.clear()
        if not _JOBBSAFARI_DEPLOY:
            try:
                _JOBBSAFARI_DEPLOY.append(jobbsafari.build_id())
            except Exception:  # noqa: BLE001 -- one bad run must not stop the pool
                return None
        return _JOBBSAFARI_DEPLOY[0]


def jobbsafari_body(row) -> str | None:
    """The description for one Jobbsafari posting.

    **The slug is required and cannot be synthesised.** It ends in the posting
    id, but `/jobb/{id}` and `/jobb/x-{id}` both 404 -- so the address is
    `jobs.url`, which is why the fetchers take the row rather than the token
    and the id. Every other source addresses a posting from those two; this one
    does not, and inventing a third convention to keep the old signature would
    have been the worse trade.

    The data route answers 161 KB against the rendered page's 463 KB, and both
    carry `jobEntry.description`.
    """
    url = row["url"]
    if not url or "/jobb/" not in url:
        return None
    slug = url.rsplit("/jobb/", 1)[1].split("?")[0]
    for attempt in (0, 1):
        # A deploy mid-pass 404s an id that worked a second ago, so the second
        # attempt asks for a fresh one.
        deploy = _jobbsafari_deploy(refresh=bool(attempt))
        if deploy is None:
            return None
        address = f"{jobbsafari.SITE}/_next/data/{deploy}/jobb/{slug}.json"
        try:
            payload = json.loads(http.get_text(address, timeout=25, retries=1))
        except Exception:  # noqa: BLE001 -- a 404, a timeout, a hostile page
            continue
        entry = payload.get("pageProps", {}).get("jobEntry")
        return _clean(entry.get("description")) if isinstance(entry, dict) else None
    return None


# Keyed on `jobs.ats`, and each fetcher takes the whole row: a posting is
# addressed by `token` and `job_id` on Workday and by `url` on Jobbsafari, and
# there is no third thing they have in common.
FETCHERS = {"workday": workday_body, "jobbsafari": jobbsafari_body}


def targets(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Body-less postings whose verdict a body could actually change.

    Ordered by whether the posting is still live, then by whether the tagger
    already placed it somewhere the board keeps. A body fetched for a posting
    already gated as another profession answers a question nobody asked.
    """
    placeholders = ",".join("?" * len(FETCHERS))
    return connection.execute(
        f"""
        SELECT j.ats, j.token, j.job_id, j.url
        FROM jobs j
        JOIN job_tags r ON r.ats = j.ats AND r.token = j.token
                       AND r.job_id = j.job_id
                       AND r.dimension = 'relevance' AND r.tagger = ?
        LEFT JOIN job_tags x ON x.ats = j.ats AND x.token = j.token
                            AND x.job_id = j.job_id
                            AND x.dimension = 'exclusion_reason'
                            AND x.tagger = ?
        WHERE j.ats IN ({placeholders})
          AND (j.description IS NULL OR j.description = '')
          AND j.removed_at IS NULL
          -- The whole point of the queue: a posting the tagger could not
          -- place. Anything it already decided needs no help.
          AND r.value = 'unknown'
          -- Not already gated off the board for being somewhere else or
          -- something else. Those are 50,000 postings and none of them
          -- becomes a quant job by acquiring a description.
          AND x.value IS NULL
        ORDER BY j.first_seen DESC
        LIMIT ?
        """,
        (tagging.TAGGER, tagging.TAGGER, *FETCHERS, limit),
    ).fetchall()


def run(
    connection: sqlite3.Connection, limit: int, workers: int = 12
) -> tuple[int, int]:
    """Fill in missing descriptions. Returns (attempted, filled)."""
    rows = targets(connection, limit)
    if not rows:
        return 0, 0

    def work(row: sqlite3.Row) -> tuple[sqlite3.Row, str | None]:
        return row, FETCHERS[row["ats"]](row)

    attempted = filled = 0
    batch: list[tuple[str, str, str, str]] = []
    # Written in batches, like every other long pass here: this is tens of
    # minutes of network work and losing it to one exception means fetching
    # bodies we already have.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row, body in pool.map(work, rows):
            attempted += 1
            if not body:
                continue
            filled += 1
            batch.append((body, row["ats"], row["token"], row["job_id"]))
            if len(batch) >= 100:
                _write(connection, batch)
                batch.clear()
    _write(connection, batch)
    return attempted, filled


def _write(connection: sqlite3.Connection, batch) -> None:
    if not batch:
        return
    with connection:
        connection.executemany(
            "UPDATE jobs SET description = ?"
            " WHERE ats = ? AND token = ? AND job_id = ?",
            batch,
        )


def coverage(connection: sqlite3.Connection):
    """Bodies held per source -- the number this stage exists to move."""
    return connection.execute(
        """
        SELECT ats,
               COUNT(*) AS postings,
               SUM(description IS NOT NULL AND description != '') AS with_body
        FROM jobs
        WHERE removed_at IS NULL
        GROUP BY ats
        ORDER BY postings DESC
        """
    ).fetchall()
