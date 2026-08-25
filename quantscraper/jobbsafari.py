"""Layer 4 -- Jobbsafari, Sweden's widest job board.

Sweden had one national source, JobStream, and that is a *change* feed: what it
leaves behind is whatever happened to change inside the polled window. Widening
Sweden was therefore two questions, and only the second is about coverage -- how
much of Platsbanken we hold, and how much of Sweden Platsbanken is.

**Measured, because both were cheap to test.** Platsbanken's own search API
answers 39,636 for the unfiltered query; Jobbsafari advertises **48,550**, and
39 of 40 JobStream postings drawn at random from our database are on it under
the identical title. So this board is Platsbanken plus roughly nine thousand
more -- and the obvious alternative, streaming JobTech's 700 MB `/snapshot`,
would have bought a subset of what a hundred requests get here.

**Jobbsafari is Jobindex's Swedish sibling**, same owner, and shares none of
its problems:

    Jobindex (DK)                     Jobbsafari (SE)
    result window of 1,000            no window -- page 1,619 serves the tail
    partitioned over 81 categories    one unfiltered walk
    ~1,300 requests, 70 MB            98 requests
    robots disallows the pager        robots allows it

This module asks for `page` and `page_size` on `/lediga-jobb` and nothing else,
so unlike the Danish sweep there is no judgement call to hand back to the user.

**The surface is Next.js's own data route, not the rendered page.** The same
payload the search page ships as `__NEXT_DATA__` is served without the 900 KB
of markup at `/_next/data/{buildId}/{locale}/lediga-jobb.json`. The build id
changes on every deploy, so it is read from the page rather than pinned, and a
404 from a stale one refreshes it once before giving up.

**The board publishes its own total**, so the walk is checked rather than
trusted: what arrived is compared against what was advertised, and a shortfall
is reported as truncation rather than shrugged at.

**Paging stops on an *empty* page, never a short one, and the difference cost
the first live sweep 43,000 postings.** Page 11 came back with 499 rows instead
of 500 -- an ad withdrawn between the count and the render -- the walk read that
as the end of the board, and reported a clean, finished, wrong 5,421. Only a
page of zero means there is nothing after it. It also stops on a page repeating
the previous one exactly, because a board ignoring `page` serves page one
forever and never runs out.

**No cursor and no top-up path, deliberately.** Jobindex needs one because a
full sweep there is 1,300 requests; here it is 98, and a sweep refreshes
`last_seen` on every posting still live, which is how a listing goes missing. A
second code path that could only ever be *less* complete is not worth two
minutes.

**`endDate` is not a deadline and is not written as one.** 11.3% of rows sit
exactly 181 days after the start date and a long tail fall in the year 2650. It
is when the advertisement comes down -- the field Jobindex calls `lastdate` and
job-room.ch calls `publication.endDate` -- and the board sorts an approaching
deadline above everything else. JobStream remains the only Swedish source
publishing a real one.

**No taxonomy, and that is a real limitation rather than an oversight.** The
detail page carries `mainCategories` and `subcategories`, which is exactly what
`jobs.category` is for and what gates Denmark and Singapore -- but the *list*
endpoint returns them empty on 1,000 of 1,000 rows, and the only route to them
is `kategori=`, which robots disallows. So Swedish postings are gated by the
occupation lexicon instead.

**No employer domain, and that was measured before being given up on.**
`apply.href` resolves on 1,681 of 2,000 rows across 386 hosts, and the head of
that distribution is ATS vendors while the tail mixes an employer's own careers
host with staffing agencies standing in for clients they do not name. Nothing
on the record separates the two -- the surrogate problem job-room.ch solves with
a flag this board does not publish. A domain would only be a guess wearing an
identity's clothes.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

from . import db, http
from .models import Job

NAME = "jobbsafari"
TOKEN = "sweden"  # one national board, so the identifier is constant

SITE = "https://jobbsafari.se"  # the apex: `www` 301s the data route away
SEARCH_PATH = "/lediga-jobb"

# How many postings to ask for per request. 2,000 was accepted and returned
# 2,000 distinct rows; 500 is used because the walk is already only ~100
# requests at that size and a smaller page costs less to redo on a retry.
PAGE_SIZE = 500

# A bound on the walk, not a stop condition -- paging stops on an empty page.
# It exists so a board that starts serving rows forever ends the run instead of
# looping, and hitting it is reported as a problem rather than as a finish.
# 48,550 postings at 500 a page is 98 of them, so this is four times the board.
MAX_PAGES = 400

# Below this the source is broken rather than quiet. Sweden advertises forty
# thousand postings on an ordinary day and the seasonal trough is nothing like
# this deep; a sweep coming back under it has found a redesign, not a holiday.
MIN_EXPECTED = 15_000

# The index moves under a two-minute walk -- ads are published and withdrawn
# while it runs -- so a small gap between advertised and collected is the board
# breathing. Anything wider is truncation.
SHORTFALL_TOLERANCE = 0.02

_ISLAND = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


class Blocked(RuntimeError):
    """The board answered and carried no search response.

    Raised rather than returning an empty page, because an empty page is how
    this walk terminates: a redesigned island or a consent wall would otherwise
    read as "the board ends here" and the sweep would report a clean, wrong
    number. Same rule `jobindex.Blocked` and every reader in `sites.py` follow.
    """


@dataclass(frozen=True, slots=True)
class Page:
    """One page of results, plus what the board said about the whole query.

    `page_size` is the board's *own* default and is deliberately not used for
    anything: it reads 30 on a request that returned 500 rows, so a stop
    condition built on it would be Workday's `total: 0` in a new place. It is
    carried so that a board which starts capping the parameter shows up in the
    record rather than as a quietly short sweep.
    """

    rows: list[dict]
    hitcount: int
    page_size: int


@dataclass(slots=True)
class Sweep:
    """What one sweep did, and whether to believe it."""

    pages: int = 0
    seen: int = 0  # distinct postings collected
    written: int = 0
    repeats: int = 0  # rows a later page served again
    advertised: int = 0  # what the board said its unfiltered total was
    exhausted: bool = False  # the walk ended on an empty page rather than a bound
    partial: bool = False  # `--pages` asked for a probe, not for the board

    @property
    def problem(self) -> str | None:
        """The one thing a caller has to check. None means the sweep is sound."""
        if self.partial:
            return None
        if not self.exhausted:
            return (
                f"stopped at the {MAX_PAGES:,d}-page bound with the board still "
                "serving rows -- the walk was cut short rather than finished"
            )
        if self.seen < MIN_EXPECTED:
            return (
                f"collected {self.seen:,d} postings, expected at least "
                f"{MIN_EXPECTED:,d} -- treating as a broken source"
            )
        shortfall = self.advertised - self.seen
        if self.advertised and shortfall > self.advertised * SHORTFALL_TOLERANCE:
            return (
                f"collected {self.seen:,d} of the {self.advertised:,d} the board "
                f"advertised -- {shortfall:,d} short, which is truncation rather "
                f"than a moving index"
            )
        return None


def build_id() -> str:
    """The deploy id the data route is addressed by.

    Pinned nowhere: it changes on every deploy of the site, so a constant here
    would work until the day it silently stopped and every page 404'd at once.
    """
    markup = http.get_text(f"{SITE}{SEARCH_PATH}", timeout=60)
    island = _ISLAND.search(markup)
    if not island:
        raise Blocked("the search page carries no __NEXT_DATA__ island")
    try:
        payload = json.loads(island.group(1))
    except ValueError as exc:  # pragma: no cover -- a truncated island
        raise Blocked(f"the __NEXT_DATA__ island did not parse: {exc}") from None
    for key in ("buildId", "locale"):
        if not payload.get(key):
            raise Blocked(f"the __NEXT_DATA__ island carries no {key}")
    return f"{payload['buildId']}/{payload['locale']}"


def parse(text: str) -> Page:
    """One page of results out of either surface.

    The data route answers with `{"pageProps": ...}` and the rendered page with
    the same object wrapped in `{"props": {"pageProps": ...}}` inside a script
    tag, so one parser reads both and the HTML fallback costs nothing.
    """
    body = text.lstrip()
    if not body.startswith("{"):
        island = _ISLAND.search(text)
        if not island:
            raise Blocked("the page carries no __NEXT_DATA__ island")
        text = island.group(1)
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise Blocked(f"the search response did not parse: {exc}") from None

    props = payload.get("props", payload).get("pageProps")
    if not isinstance(props, dict):
        raise Blocked("the search response carries no pageProps")
    entries = props.get("jobEntries")
    if not isinstance(entries, dict) or not isinstance(entries.get("results"), list):
        raise Blocked("the search response carries no jobEntries")
    return Page(
        rows=entries["results"],
        hitcount=int(entries.get("count") or 0),
        page_size=int(props.get("pageSize") or 0),
    )


def fetch_page(page: int, size: int = PAGE_SIZE, *, deploy: list[str]) -> Page:
    """Page `page` of the unfiltered board.

    `deploy` is a one-element cache of the build id, mutated in place: a stale
    id 404s every request, so it is refreshed once and the page retried before
    the walk falls back to the rendered search page.
    """
    query = f"?page={page}&page_size={size}"
    last: Exception | None = None
    for attempt in (0, 1):
        try:
            if not deploy:
                deploy.append(build_id())
            url = f"{SITE}/_next/data/{deploy[0]}{SEARCH_PATH}.json{query}"
            return parse(http.get_text(url, timeout=120, retries=2))
        except Exception as exc:  # noqa: BLE001 -- any failure of the fast route
            last = exc
            # A deploy mid-walk invalidates the id, which shows up as a 404 on
            # a URL that worked a second ago. One refresh, then the slow route.
            deploy.clear()
    # 900 KB a page instead of 380, and it is the surface the site actually
    # serves to a browser, so it cannot go away while the board is up.
    try:
        return parse(http.get_text(f"{SITE}{SEARCH_PATH}{query}", timeout=120, retries=2))
    except Exception as exc:  # noqa: BLE001
        raise Blocked(f"neither surface answered page {page}: {last}; {exc}") from None


def _location(row: dict) -> str | None:
    """Every place the advertisement names, in the order it names them.

    A posting open in two cities is two chances for the reader and one row in
    the database, so both names are kept and `tagging.py` reads a hub out of
    each. Deduplicated in first-seen order: an employer listing a seat across
    three of its own offices repeats the region as often as not.
    """
    names = [
        name
        for entry in row.get("locations") or []
        if (name := ((entry.get("name") or (entry.get("area") or {}).get("name")) or "").strip())
    ]
    return ", ".join(dict.fromkeys(names)) or None


def _job(row: dict) -> Job:
    company = row.get("company") or {}
    return Job(
        ats=NAME,
        token=TOKEN,
        # The board's own key, stable across a retitling. The slug is not: it
        # is built from the headline, so an edited title would mint a second
        # row for one posting.
        job_id=str(row["pk"]),
        title=(row.get("title") or "").strip(),
        # A national board advertises for everyone, so the advertiser's name is
        # the only thing naming the firm -- see the module docstring for why no
        # domain is read off the apply link.
        employer=(company.get("name") or "").strip() or None,
        # The list endpoint returns the taxonomy empty on every row and the
        # only route to it is disallowed. A NULL category passes the read-time
        # gate, which is the safe direction to be missing in.
        category=None,
        # `slug` already ends in the posting id, and the detail page is the
        # public address of the advertisement.
        url=f"{SITE}/jobb/{row['slug']}" if row.get("slug") else None,
        location=_location(row),
        # No department field exists and nothing is smuggled into one:
        # `tagging.py` folds `department` into the title, so anything parked
        # here becomes a covert second door to seniority.
        department=None,
        posted_at=(row.get("startDate") or "")[:10] or None,
        # `endDate` is when the advertisement comes down, not when applications
        # close. See the module docstring; this is deliberately never set.
        deadline=None,
        # The list endpoint carries none. `bodies.py` fetches one per posting
        # whose verdict a description could actually change, which is a few
        # thousand requests rather than forty-eight thousand.
        description=None,
    )


def run(connection: sqlite3.Connection, *, pages: int | None = None) -> Sweep:
    """Sweep the board into `jobs`. Returns what happened and whether to trust it.

    `pages` stops early for a probe -- a reader change checked against a couple
    of hundred live rows rather than against all of Sweden. It sets `partial`,
    so the guards that compare what arrived against what the board advertised
    stand down rather than reporting a deliberate subset as truncation.
    """
    sweep = Sweep(partial=pages is not None)
    deploy: list[str] = []
    seen: set[str] = set()
    previous: set[str] = set()

    # `pages or MAX_PAGES` would read `--pages 0` as "no limit" and walk the
    # whole board while reporting a probe.
    limit = MAX_PAGES if pages is None else min(pages, MAX_PAGES)
    for page in range(1, limit + 1):
        got = fetch_page(page, deploy=deploy)
        sweep.pages += 1
        if page == 1:
            sweep.advertised = got.hitcount

        # A row with no `pk` is not addressable and `_job` would raise on it.
        # Dropped here rather than defended against three lines later, so the
        # counts below all describe the same set of rows.
        rows = [row for row in got.rows if row.get("pk")]
        ids = {str(row["pk"]) for row in rows}
        # A board ignoring `page` serves page one forever and never returns an
        # empty page, so an exhausted walk would look like an endless one.
        if ids and ids == previous:
            raise Blocked(
                f"page {page} repeated page {page - 1} exactly -- the board is "
                "ignoring the pager"
            )
        previous = ids

        fresh = [row for row in rows if str(row["pk"]) not in seen]
        sweep.repeats += len(rows) - len(fresh)
        seen.update(ids)
        if fresh:
            sweep.written += db.upsert_jobs(connection, None, [_job(row) for row in fresh])

        # **A short page is not the end of this board**, and assuming it was
        # cost the first live sweep 43,000 postings: page 11 came back with 499
        # rows instead of 500 and the walk reported a clean, finished, wrong
        # 5,421. The board drops a row from a page now and then -- an ad
        # withdrawn between the count and the render -- and only a page of
        # *zero* means there is nothing after it. Verified: at `page_size=500`
        # page 98 serves the last 50 and page 99 serves none.
        if not got.rows:
            sweep.exhausted = True
            break

    sweep.seen = len(seen)
    return sweep
