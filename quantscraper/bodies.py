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
from typing import NamedTuple

from . import db, http, jobbsafari, tagging


class Fetched(NamedTuple):
    """What a detail page yielded. Either half may be missing.

    `location` exists because Workday's detail endpoint answers two questions
    at once and the second one was being thrown away -- see `workday_body`. A
    fetcher with nothing to add there returns None and nothing is written.
    """

    description: str | None
    location: str | None


# **The shape Workday publishes instead of a place**, and the only location
# this pass is allowed to overwrite. `Remote` is deliberately not here: the
# detail endpoint answers it with the requisition's anchor office, so treating
# it as a placeholder would pin a remote posting to a city nobody has to go to.
# `N Locations` makes no such claim -- it is a count, and the names behind it
# are strictly more than it says.
_UNRESOLVED = re.compile(r"^\s*\d+\s+locations?\s*$", re.IGNORECASE)

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


def _workday_origin(token: str) -> str | None:
    """`https://host` for a Workday token, or None if it is malformed.

    Its own function because the *throttle* is per host and this pass now has
    to know which host a row will hit before it fetches it -- see `_spread`.
    """
    parts = token.split("|")
    if len(parts) not in (3, 4):
        return None
    tenant, wd = parts[0], parts[1]
    host = parts[3] if len(parts) == 4 else "myworkdayjobs.com"
    # On `myworkdaysite.com` the subdomain is a bare `wdN`, so every tenant
    # there shares one host and one throttle slot. That is the case worth
    # getting right: keying on the tenant would spread rows that cannot be
    # spread and quietly re-cluster them.
    return (
        f"https://{wd}.{host}"
        if host == "myworkdaysite.com"
        else f"https://{tenant}.{wd}.{host}"
    )


def workday_body(row) -> Fetched:
    """The description *and the real locations* for one Workday posting.

    `token` is `tenant|wdN|site[|host]` and `job_id` is the `externalPath` the
    list endpoint returned, which is exactly what the detail endpoint appends.
    Both Workday hosts are handled the same way they are in `extract.workday`.

    **Workday's list endpoint summarises a multi-site requisition as `2
    Locations` and its detail endpoint spells them out.** That summary is the
    single largest thing in the `hub: unknown` bucket -- 8,004 postings, 58% of
    it -- and it is not a posting that named no place, it is a posting that
    named several and was read by a field too narrow to hold them. Both halves
    of that matter: the board says `unstated` where the answer is knowable, and
    a seat open in Stockholm *and* Copenhagen is exactly the posting that
    should appear under both.

    `additionalLocations` repeats `location` on some tenants and extends it on
    others, so the two are unioned and de-duplicated in published order.
    """
    token, path = row["token"], row["job_id"]
    origin = _workday_origin(token)
    if origin is None or not path:
        return Fetched(None, None)
    tenant, _, site = token.split("|")[:3]
    url = f"{origin}/wday/cxs/{tenant}/{site}{path}"
    try:
        payload = json.loads(http.get_text(url, timeout=25, retries=1))
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError,
            TimeoutError, OSError):
        return Fetched(None, None)
    except Exception:  # noqa: BLE001 -- one hostile tenant must not stop the run
        return Fetched(None, None)
    info = payload.get("jobPostingInfo")
    if not isinstance(info, dict):
        return Fetched(None, None)
    return Fetched(_clean(info.get("jobDescription")), _workday_places(info))


def _workday_places(info: dict) -> str | None:
    """`location` and `additionalLocations` as one `; `-joined string.

    Joined with a semicolon because that is what the hub reader already treats
    as a list separator, and de-duplicated because a tenant that publishes only
    one place publishes it twice -- once in each field.
    """
    places: list[str] = []
    for value in [info.get("location"), *(info.get("additionalLocations") or [])]:
        if isinstance(value, str) and (value := value.strip()) and value not in places:
            places.append(value)
    return "; ".join(places) or None


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


def jobbsafari_body(row) -> Fetched:
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
        return Fetched(None, None)
    slug = url.rsplit("/jobb/", 1)[1].split("?")[0]
    for attempt in (0, 1):
        # A deploy mid-pass 404s an id that worked a second ago, so the second
        # attempt asks for a fresh one.
        deploy = _jobbsafari_deploy(refresh=bool(attempt))
        if deploy is None:
            return Fetched(None, None)
        address = f"{jobbsafari.SITE}/_next/data/{deploy}/jobb/{slug}.json"
        try:
            payload = json.loads(http.get_text(address, timeout=25, retries=1))
        except Exception:  # noqa: BLE001 -- a 404, a timeout, a hostile page
            continue
        entry = payload.get("pageProps", {}).get("jobEntry")
        body = _clean(entry.get("description")) if isinstance(entry, dict) else None
        return Fetched(body, None)
    return Fetched(None, None)


# Keyed on `jobs.ats`, and each fetcher takes the whole row: a posting is
# addressed by `token` and `job_id` on Workday and by `url` on Jobbsafari, and
# there is no third thing they have in common.
FETCHERS = {"workday": workday_body, "jobbsafari": jobbsafari_body}


def targets(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Postings one detail fetch could change the answer for.

    **Two queues, because the detail page settles two different questions.**
    The first is the original one: a body-less posting the tagger could not
    place, ordered so that a posting already gated as another profession is
    never fetched -- a body answers no question there.

    The second is a posting whose *location* is Workday's `N Locations`
    summary. That one is not filtered on `relevance` and not filtered on
    whether a body is already held, because neither has anything to do with the
    fault: the posting names several places, the list endpoint published a
    count instead of the names, and the board consequently files it under
    `unstated` however well it reads. It is still filtered on the gates, for
    the same reason the first queue is.

    **`UNION` rather than one `WHERE` with an `OR`.** The two arms want
    different index paths and putting them in one predicate denies both: the
    planner drove the whole thing from `job_tags_by_value (dimension=?)`,
    scanning every relevance row in the corpus, and the pass took **34.6s** to
    decide what to fetch. Split, the second arm needs no `job_tags` join at all
    -- it does not care what the tagger made of the posting, only that the
    location is a count -- and drives from `jobs`.

    One `--limit` still bounds the whole pass, and `UNION` de-duplicates a
    posting that is in both queues so it is fetched once.
    """
    boards = ",".join("?" * len(FETCHERS))
    return connection.execute(
        f"""
        SELECT * FROM (
            -- Queue one: the tagger could not place it and has no text to
            -- place it with.
            SELECT j.ats, j.token, j.job_id, j.url, j.location, j.first_seen
            FROM jobs j
            JOIN job_tags r ON r.ats = j.ats AND r.token = j.token
                           AND r.job_id = j.job_id
                           AND r.dimension = 'relevance' AND r.tagger = ?
            LEFT JOIN job_tags x ON x.ats = j.ats AND x.token = j.token
                                AND x.job_id = j.job_id
                                AND x.dimension = 'exclusion_reason'
                                AND x.tagger = ?
            WHERE j.ats IN ({boards})
              AND j.removed_at IS NULL
              AND (j.description IS NULL OR j.description = '')
              AND r.value = 'unknown'
              -- Not already gated off the board for being somewhere else or
              -- something else. Those are 50,000 postings and none of them
              -- becomes a quant job by acquiring a description.
              AND x.value IS NULL

            UNION

            -- Queue two: it named several places and the list endpoint gave us
            -- the count. Not filtered on relevance, and no `r` join for the
            -- same reason: how well a posting reads has nothing to do with
            -- whether we know where it is. Still filtered on the gates, since
            -- a posting already off the board for being another profession
            -- does not come back by acquiring an address.
            SELECT j.ats, j.token, j.job_id, j.url, j.location, j.first_seen
            FROM jobs j
            LEFT JOIN job_tags x ON x.ats = j.ats AND x.token = j.token
                                AND x.job_id = j.job_id
                                AND x.dimension = 'exclusion_reason'
                                AND x.tagger = ?
            WHERE j.ats IN ({boards})
              AND j.removed_at IS NULL
              AND x.value IS NULL
              AND (j.location GLOB '[0-9]* Location'
                   OR j.location GLOB '[0-9]* Locations')
        )
        ORDER BY first_seen DESC
        LIMIT ?
        """,
        (tagging.TAGGER, tagging.TAGGER, *FETCHERS,
         tagging.TAGGER, *FETCHERS, limit),
    ).fetchall()


def _host_of(row: sqlite3.Row) -> str:
    """Which host this row's fetch will hit, for `_spread`.

    `http._throttle` books its interval per host, so this is the resource the
    pool is actually contending for. Jobbsafari is one site, so every row of it
    shares a key -- correctly: they genuinely cannot be spread.
    """
    if row["ats"] == "workday":
        return _workday_origin(row["token"]) or "workday:malformed"
    return row["ats"]


def _spread(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """Round-robin the queue over its hosts, keeping each host's own order.

    **A twelve-thread pool over a queue sorted by date is close to a
    one-thread pool.** `targets` orders by `first_seen DESC` so a `--limit`
    keeps the most promising rows -- and a board polled this morning
    contributes its whole batch at once, so that ordering arrives clustered by
    tenant. With `MIN_INTERVAL_S` booked per host, twelve workers then queue
    behind one tenant's one-second slot: 335 consecutive `usbank` rows are 335
    seconds however many threads are watching, and the run is the sum of those
    stretches rather than the longest of them. Measured on the live queue, the
    longest same-host run falls **335 -> 102** when the hosts are interleaved,
    and the wall time with it -- roughly 90 minutes to roughly 12 for 5,372
    rows.

    **12 minutes is the floor and no ordering beats it.** The biggest tenant
    contributes 723 rows and the throttle allows one a second, so a pass is
    never shorter than its largest board. That is the number to check before
    suspecting this function: if a run takes far longer, the queue has
    re-clustered; if it takes about that, it is doing as well as politeness
    permits.

    **Selection and order are separate decisions and only the order changes
    here.** `targets` still picks the newest rows; this only decides what to
    fetch first among the rows already chosen, which is the same split the
    `jobs` parallelisation had to make -- *spread the sample across hosts, or
    a concurrency change measures nothing.*
    """
    queues: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        queues.setdefault(_host_of(row), []).append(row)
    out: list[sqlite3.Row] = []
    while queues:
        for host in list(queues):
            out.append(queues[host].pop(0))
            if not queues[host]:
                del queues[host]
    return out


def run(
    connection: sqlite3.Connection, limit: int, workers: int = 12
) -> tuple[int, int, int]:
    """Fill in missing descriptions and unresolved places.

    Returns (attempted, filled, placed). The last two are counted separately
    because they are separate faults with separate cures, and one total would
    hide a pass that fetched five thousand pages and resolved no location.
    """
    rows = _spread(targets(connection, limit))
    if not rows:
        return 0, 0, 0

    def work(row: sqlite3.Row) -> tuple[sqlite3.Row, Fetched]:
        return row, FETCHERS[row["ats"]](row)

    attempted = filled = placed = 0
    batch: list[tuple[str | None, str | None, str, str, str]] = []
    # Written in batches, like every other long pass here: this is tens of
    # minutes of network work and losing it to one exception means fetching
    # bodies we already have.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row, got in pool.map(work, rows):
            attempted += 1
            body = got.description or None
            # **Only ever over the placeholder.** A posting that published a
            # real place keeps it: the detail endpoint is a second opinion, not
            # a better one, and overwriting a good location with it would be a
            # write nobody asked for on the strength of nothing.
            where = got.location if _UNRESOLVED.match(row["location"] or "") else None
            if not body and not where:
                continue
            filled += bool(body)
            placed += bool(where)
            batch.append((body, where, row["ats"], row["token"], row["job_id"]))
            if len(batch) >= 100:
                _write(connection, batch)
                batch.clear()
    _write(connection, batch)
    return attempted, filled, placed


def _write(connection: sqlite3.Connection, batch) -> None:
    """Store the descriptions and places, and retire the verdicts reached without them.

    **A body that arrives after the tag is a body the tagger never reads.**
    `tagging.postings` selects postings with no row at the *current* version,
    so a posting classified on its title this morning is finished as far as
    `tag` is concerned -- and fetching its description in the afternoon changes
    nothing until the next version bump. That is how 585 Swedish postings
    reached the board: they arrived, tagged `unknown` on a six-word title,
    and the body that would have settled them came too late to be read.

    It is worth settling, because for these sources a body is nearly decisive.
    Measured over Jobbsafari: **4% of postings with a body stay `unknown`
    against 28% without one** -- `lexicon.judge`'s `no_markets_signal` is the
    only rule in the pipeline that can resolve an `unknown` on evidence of
    absence, and it needs a document to be absent from.

    So the tags go, and the next `tag` re-reads the posting with the body in
    front of it. Deleting from `job_tags` is safe in a way deleting from `jobs`
    would not be: it is derived, `tag` rebuilds it from the posting on demand,
    and `prune` already deletes from it. Only the current version's rows are
    touched, so an older tagger's history is left exactly as it was.
    """
    if not batch:
        return
    with connection:
        # `COALESCE` because either half may be missing: a row fetched for its
        # body must not blank a location, and a row fetched for its location
        # must not blank a body it already had.
        connection.executemany(
            "UPDATE jobs SET description = COALESCE(?, description),"
            "                location = COALESCE(?, location)"
            " WHERE ats = ? AND token = ? AND job_id = ?",
            batch,
        )
        connection.executemany(
            "DELETE FROM job_tags"
            " WHERE ats = ? AND token = ? AND job_id = ? AND tagger = ?",
            [(ats, token, job_id, tagging.TAGGER) for *_, ats, token, job_id in batch],
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
