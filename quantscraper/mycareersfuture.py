"""Layer 4 -- MyCareersFuture, Singapore's statutory job portal.

Not an ordinary aggregator: under the **Fair Consideration Framework** an
employer must advertise a role here, for a minimum run, before it may apply for
an Employment Pass. So for exactly the roles a foreigner could take, the portal
is a register substantially complete *by law* -- the property that makes
`fi_se` and the SEC bulk files worth more than any search box.

No key, no quota, no session cookie.

**Two enumerable surfaces, and the obvious one is the wrong one.**

`POST /v2/search` is what the website calls, and it advertises a `_links.last`
of page 672. **That link is a lie**: page 99 answers and page 100 onward return
**HTTP 418** -- an Elasticsearch `max_result_window` of 10,000 wearing a joke
status code. Believing the advertised `last` produces a walk that dies 85%
short. It is at least loud, which is the only reason it was cheap to find.

`GET /v2/jobs` is the one to use. Measured against the live API it pages to the
end with no ceiling, is **bigger** (84,743 postings against search's 67,272),
carries the **full description** in the list response so this needs no body
backfill, carries **`metadata.expiryDate`** as a published closing date, and is
already sorted newest first -- 0 inversions over the first 9,485 rows, which is
what makes an incremental top-up safe.

**The search endpoint is worth keeping written down as the fallback.** If
`/v2/jobs` ever grows a window of its own, the partition that beats it is the
portal's own category taxonomy, and that partition is *provably* a complete
cover: the union of all 43 categories is exactly the unfiltered total. The 43rd
name was nearly missed -- 42 summed 66 short, and the gap was
`Telecommunications`, which never appeared in a 1,200-row sample. A bogus
category returns HTTP 400 rather than an empty result, so the endpoint is its
own oracle for whether a name is real.

**Paging guards, per the Workday lesson.** A page-count bound is a silent cap
on exactly the boards that matter, so `MAX_PAGES` is five times the real length
-- a backstop against a server that never terminates, not a limit on how big
the portal may be. The walk stops on a short page, or on one whose contents
repeat the previous: a server ignoring `page` serves page one forever and never
returns an empty page.

**The index moves under the walk, so the sweep audits its own arithmetic.**
`total` drifted by 14 across a single walk and 6 rows in the first 10,094
arrived twice, so distinct postings collected are compared against the
advertised total and any shortfall is reported rather than absorbed.

**This board is not one firm's own, so `employer` carries the advertiser name**
-- the same contract JobStream follows. `domain` is NULL for every row: the
portal publishes no employer website. What it *does* publish is the **UEN**,
Singapore's statutory company number, which is a far better identity key than a
name and has no column to live in yet.

**`deadline` is `metadata.expiryDate`, a published field**, set on every row
walked and genuinely chosen by the employer -- 7-, 14- and 30-day runs all
appear. Note the downstream consequence: the board pins an approaching deadline
above everything else, and this source hands it ~85,000 dated postings where the
rest of the corpus has almost none.

**`department` stays NULL deliberately.** The portal has no department field.
It does publish `positionLevels` and `minimumYearsExperience`, and both are
tempting to park in `department` -- do not. `tagging.py` folds `department` into
the *title* when reading rank and role, so a level parked there becomes a third
door to seniority opened covertly through a field the tagger reads as the job's
name. That is the `Trading Operations` mistake with a new coat of paint.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass

from . import db, http
from .models import Job

NAME = "mycareersfuture"
TOKEN = "singapore"  # one national portal, so the board identifier is constant

# `/v2/jobs`, not the `/v2/search` the website uses: search answers page 99 and
# returns HTTP 418 from page 100 on, so it cannot enumerate the portal.
LIST_URL = "https://api.mycareersfuture.gov.sg/v2/jobs?limit={limit}&page={page}"

# 100 is the maximum the API accepts; 200 is HTTP 400. Asserted rather than
# merely used, so raising it fails here instead of at the far end of a sweep.
PAGE_SIZE = 100

# A backstop against a server that never returns a short page, not a limit on
# how big the portal may be. The real walk ends at page 847.
MAX_PAGES = 5_000

# An implausibly small result is a failure. The portal holds ~85,000 postings;
# it would have to lose three quarters of them before this stayed quiet. The
# sharper check is the shortfall against the total the portal itself advertises
# -- this only catches the case where the endpoint changed shape entirely.
MIN_EXPECTED = 20_000

# The index shifts while the walk runs, so a few postings slide across a page
# boundary and are seen twice or not at all. 6 duplicates in the first 10,094
# rows; anything past this is a truncation, not turbulence.
SHORTFALL_TOLERANCE = 0.02

# The portal's own taxonomy, whose union is exactly the unfiltered total. Kept
# for two reasons: it is the partition that enumerates the board if `/v2/jobs`
# ever grows a result window, and it is the highest-value gate available for
# this source -- the same argument `_OFF_INDUSTRY_FIELDS` makes for JobStream's
# occupation fields. A posting usually carries more than one (676 of a 1,200-row
# sample did), so a gate on these has to be a subset test, not an equality test.
CATEGORIES = (
    "Accounting / Auditing / Taxation", "Admin / Secretarial",
    "Advertising / Media", "Architecture / Interior Design",
    "Banking and Finance", "Building and Construction", "Consulting",
    "Customer Service", "Design", "Education and Training", "Engineering",
    "Entertainment", "Environment / Health", "Events / Promotions", "F&B",
    "General Management", "General Work", "Healthcare / Pharmaceutical",
    "Hospitality", "Human Resources", "Information Technology", "Insurance",
    "Legal", "Logistics / Supply Chain", "Manufacturing",
    "Marketing / Public Relations", "Medical / Therapy Services", "Others",
    "Personal Care / Beauty", "Precision Engineering", "Professional Services",
    "Public / Civil Service", "Purchasing / Merchandising",
    "Real Estate / Property Management", "Repair and Maintenance",
    "Risk Management", "Sales / Retail", "Sciences / Laboratory / R&D",
    "Security and Investigation", "Social Services", "Telecommunications",
    "Travel / Tourism", "Wholesale Trade",
)

_TAGS = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class Sweep:
    """What one walk of the portal did, and whether to believe it."""

    pages: int
    seen: int  # distinct postings collected
    written: int
    advertised: int  # what the portal said the total was on the first page
    repeats: int  # rows the moving index served twice
    partial: bool  # a `since` top-up, so `advertised` is not the target

    @property
    def shortfall(self) -> int:
        return 0 if self.partial else max(self.advertised - self.seen, 0)

    @property
    def problem(self) -> str | None:
        """The one thing a caller has to check. None means the sweep is sound."""
        if self.partial:
            return None
        if self.seen < MIN_EXPECTED:
            return (
                f"collected {self.seen:,d} postings, expected at least "
                f"{MIN_EXPECTED:,d} -- treating as a broken source"
            )
        if self.advertised and self.shortfall > self.advertised * SHORTFALL_TOLERANCE:
            return (
                f"collected {self.seen:,d} of the {self.advertised:,d} the portal "
                f"advertised -- {self.shortfall:,d} short, which is truncation "
                f"rather than a moving index"
            )
        return None


def _text(value: str | None) -> str | None:
    """Plain text out of the portal's HTML descriptions.

    Tags are stripped before entities are decoded, never after: an employer who
    writes a literal `&lt;p&gt;` in their prose would otherwise have it decoded
    into a tag and then eaten.
    """
    if not value:
        return None
    return " ".join(html.unescape(_TAGS.sub(" ", value)).split()) or None


def _employer(row: dict) -> str | None:
    """The advertiser, preferring the firm being hired for over the agency.

    Recruiters post on behalf of clients here and `hiringCompany` names the real
    employer when they do. It is null far more often than not -- either the
    poster is the employer, or `isHideHiringEmployerName` is set -- and then the
    posting company is the only name published.
    """
    hiring = row.get("hiringCompany") or {}
    posted = row.get("postedCompany") or {}
    return hiring.get("name") or posted.get("name") or None


def _category(row: dict) -> str | None:
    """The portal's own categories, verbatim and in a stable order.

    Sorted only so an unchanged posting does not rewrite the column on every
    poll; the labels themselves are untouched.
    """
    names = sorted(
        name
        for entry in row.get("categories") or []
        if (name := entry.get("category"))
    )
    return ", ".join(names) or None


def _location(row: dict) -> str | None:
    """Where the job is, in words the geography lexicon can read.

    A gate makes every gap in a place list a deleted posting, so the country
    name leads and the district follows it. `Islandwide` is the portal's "no
    fixed site" and names no place, so it is dropped rather than written out.

    Overseas postings take the employer's own answer. Some of them say
    `Singapore` anyway -- a Tuas address filed on the foreign form -- and that
    is their word about their own office, not ours.
    """
    address = row.get("address") or {}
    districts = [
        name
        for entry in address.get("districts") or []
        if (name := entry.get("location"))
    ]
    if address.get("isOverseas") or "Overseas" in districts:
        return address.get("overseasCountry") or "Overseas"
    named = [name for name in districts if name != "Islandwide"]
    return ", ".join(["Singapore", *named])


def _job(row: dict) -> Job:
    metadata = row.get("metadata") or {}
    return Job(
        ats=NAME,
        token=TOKEN,
        # The portal's own primary key, and the tail of every job URL. The
        # human-facing `metadata.jobPostId` ("MCF-2026-1386577") is not used as
        # the identity: a repost mints a new one for the same advertisement.
        job_id=row["uuid"],
        title=row.get("title") or "",
        # A national portal advertises for everyone and publishes no employer
        # website, so without the name these are postings from nobody.
        employer=_employer(row),
        category=_category(row),
        url=metadata.get("jobDetailsUrl"),
        location=_location(row),
        # Deliberately empty -- see the module docstring.
        department=None,
        posted_at=metadata.get("newPostingDate"),
        # A published field, not a phrase mined out of the body.
        deadline=metadata.get("expiryDate"),
        description=_text(row.get("description")),
    )


def fetch_page(number: int, *, category: str | None = None) -> tuple[list[dict], int]:
    """One page of the listing. Returns its rows and the total it advertises."""
    assert PAGE_SIZE <= 100, "the API rejects a limit above 100 with HTTP 400"
    url = LIST_URL.format(limit=PAGE_SIZE, page=number)
    if category:
        url += "&categories=" + urllib.parse.quote(category)
    payload = json.loads(http.get_text(url, timeout=90, retries=3))
    return payload.get("results") or [], int(payload.get("total") or 0)


def walk(
    *, since: str | None = None, max_pages: int = MAX_PAGES, category: str | None = None
) -> Iterator[tuple[list[dict], int]]:
    """Page the portal newest-first, yielding (rows, advertised total).

    `since` is an ISO date. The walk stops once an entire page is older than it,
    which is a cheap daily top-up: the ordering is by posting *date*, so rows
    sharing a day are in no particular order and stopping on a whole page rather
    than on a row leaves a full day of slack at the boundary.

    Stops on a short page, on a page that repeats the previous one, or at
    `max_pages` -- which is a backstop against a server that does neither, not a
    cap on how big the portal may be.
    """
    previous: set[str] = set()
    for number in range(max_pages):
        rows, advertised = fetch_page(number, category=category)
        if not rows:
            return
        current = {row.get("uuid") for row in rows}
        if current == previous:
            # A server ignoring `page` serves page one forever and never
            # returns an empty page, so nothing else here would terminate.
            return
        previous = current

        yield rows, advertised

        if len(rows) < PAGE_SIZE:
            return
        if since and max(
            (row.get("metadata") or {}).get("newPostingDate") or "" for row in rows
        ) < since:
            return


def run(
    connection: sqlite3.Connection,
    *,
    since: str | None = None,
    max_pages: int = MAX_PAGES,
) -> Sweep:
    """Sweep the portal into `jobs`. Returns what happened and whether to trust it.

    **No durable cursor, unlike JobStream, and that is the point.** A full walk
    is ~850 requests and about twenty-five minutes, which is cheap enough to
    just do -- and doing it refreshes `last_seen` on every posting still live,
    which is how a listing goes missing here. A cursor would save time and would
    be the thing that silently loses a posting. `since` exists for a top-up
    between full sweeps and says so in the returned `Sweep.partial`.
    """
    seen: set[str] = set()
    written = repeats = pages = advertised = 0

    for rows, total in walk(since=since, max_pages=max_pages):
        pages += 1
        advertised = advertised or total
        fresh = []
        for row in rows:
            if not row.get("uuid"):
                continue
            if row["uuid"] in seen:
                repeats += 1
                continue
            seen.add(row["uuid"])
            fresh.append(_job(row))
        # The portal publishes no employer website, so there is no domain to
        # bridge to `firms`; the UEN it does publish has nowhere to go yet.
        written += db.upsert_jobs(connection, None, fresh)

    return Sweep(
        pages=pages,
        seen=len(seen),
        written=written,
        advertised=advertised,
        repeats=repeats,
        partial=since is not None,
    )
