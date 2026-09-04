"""Layer 4 -- job-room.ch, Switzerland's public employment service.

SECO's own portal, and not an ordinary aggregator: under the
**Stellenmeldepflicht** an employer must report a vacancy in a high-unemployment
occupation to the public employment service before advertising it anywhere else.
For those occupations it is a register complete *by law*; for everything else it
is a wide net, exactly as Platsbanken turned out to be.

**No key, no account, no session.** This source was recorded as blocked on a
registered API programme, and that was our own bug: the 401 was measured against
`/api/jobadservice/api/...`, one `/api/` too many. The real path is the one the
public site itself calls and it answers a bare unauthenticated POST with full
postings. The registered API *is* real and is a different thing -- it lets an
employer manage its **own** postings, and no read endpoint on it returns the
register.

**The `Link` header advertises a last page that does not exist.** With `size=1`
it offers `rel="last"` at page 80,459, and the API returns **HTTP 412** for any
request whose `page * size` reaches 10,000 -- an Elasticsearch
`max_result_window` wearing a status code. Believing the advertised `last`
builds a walk that dies 88% short. MyCareersFuture's 418 one country over, and
loud for the same lucky reason.

**The partition that looks obvious is not a cover, and this was measured.** The
26 cantons sum to 78,355 against a total of 80,460: `FL` is a 27th code
(Liechtenstein) no list of Swiss cantons contains, and ~2,100 postings carry no
canton at all, which no value of the filter can reach. So geography is not used
to slice.

**What is used is the two-ended walk.** `sort=date_asc` is the exact reverse of
`date_desc` -- verified over a whole canton, same set precisely reversed -- so a
slice of `T` postings is covered by reading the first 10,000 forwards and the
last `T - 10,000` backwards. That doubles the reachable slice to 20,000 for
fifteen lines and no extra request on the common path, which is what makes a
daily poll safe: a single day is ~9,400, only 6% under the ceiling.

**Above 20,000 this fails loudly rather than returning most of the answer**,
because a round number in the output is what a cap looks like from outside.

**A cold start reaches the last few days, not the whole board, and that is the
source's shape rather than a shortfall.** `onlineSince` is nested, so the slices
are 9,401 at one day and 12,028 at two -- and 27,403 at a week, past what any
walk can read. The board is a rolling 60-day window, so polling daily converges
on all of it within 60 days and then holds.

**`publication.endDate` is not a deadline and must not be written as one.**
Every ad carries one and it is tempting, because the board pins an approaching
deadline above everything else. Measured over 2,000 ads: **81% sit exactly 30
days after the start date and 12.8% exactly 60** -- two round defaults, which is
a "how long should this run?" dropdown, not a date an employer chose. Writing it
would hand ~80,000 Swiss postings a fabricated deadline and sort every one above
the postings publishing a real one.

**`company.website` is usually the recruiter's, and `surrogate` is the tell.**
The field is present on 19% of ads and the top six domains are all staffing
agencies. `company.surrogate` marks a stand-in record, and **372 of 379 websites
in a 2,000-ad sample came from surrogate rows**; the seven that did not are the
real employers. So a domain is recorded only from a non-surrogate company --
0.3% of rows, every one correct. `employer` still carries the advertiser
verbatim either way, the contract every board that is not one firm's own
follows.

**Removal is not observable here.** The search returns only `PUBLISHED_PUBLIC`
ads, so a withdrawn one simply stops appearing and there is no removal channel
of the kind JobStream publishes. Postings go stale the ordinary way: the row
stays and `last_seen` stops moving.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date

from . import db, http
from .models import Job
from .resolve import domain_of, is_platform_domain

NAME = "jobroom"
TOKEN = "switzerland"  # one national portal, so the board identifier is constant

URL = "https://www.job-room.ch/jobadservice/api/jobAdvertisements/_search"

# `page * size` may not reach this. Asserted against rather than merely used:
# the boundary was measured at three different page sizes and is exactly 10,000
# in every one of them.
WINDOW = 10_000

# What a two-ended walk can actually read. The first 10,000 forwards and the
# last 10,000 backwards overlap for any slice smaller than this and leave a
# hole for any slice larger, so this is a hard ceiling on a single query.
REACH = 2 * WINDOW

# The API accepts 1,000 and is content with it; larger sizes were not pushed,
# because 10 requests per 10,000 postings is already cheap and a page that big
# is a large JSON parse per request.
PAGE_SIZE = 1_000

# `onlineSince` is rejected above 60, and 60 returns the unfiltered total -- the
# board is a rolling 60-day window and holds nothing older.
MAX_ONLINE_SINCE = 60

# Re-read this many days on every resume. `onlineSince` has whole-day
# resolution, so there is no finer overlap available; one day is also the
# smallest slice the filter can express.
OVERLAP_DAYS = 1


@dataclass(frozen=True, slots=True)
class Sweep:
    """What one poll did, and whether to believe it."""

    days: int  # the `onlineSince` window asked for
    pages: int
    seen: int  # distinct postings collected
    written: int
    advertised: int  # what the portal said the slice held
    repeats: int  # rows the moving index served twice

    @property
    def shortfall(self) -> int:
        return max(self.advertised - self.seen, 0)

    @property
    def problem(self) -> str | None:
        """The one thing a caller has to check. None means the poll is sound.

        There is deliberately no absolute floor of the kind `MIN_EXPECTED` sets
        on a registry. This is a delta, so a quiet window is a true answer and
        a floor would only fire on the days it should not. What replaces it is
        sharper: the portal states how many postings the slice holds, so a walk
        that returns fewer than it was told about has truncated, and says so.

        **Which makes a missing total a failure in its own right, not a free
        pass.** The whole audit is that one number, so reading no count at all
        disables the only check there is -- and it happened: a case-sensitive
        header lookup found nothing over HTTP/2, the count read as zero, and a
        walk that stopped dead on the 10,000-row result window reported
        success with a suspiciously round 10,000 postings. A guard that goes
        quiet when its evidence goes missing is worse than no guard, because
        the output still says the poll was sound.
        """
        if not self.advertised and self.seen:
            return (
                f"the portal stated no total, so the {self.seen:,d} postings "
                f"collected cannot be checked for truncation"
            )
        if self.advertised > REACH:
            return (
                f"the last {self.days} day(s) hold {self.advertised:,d} postings, "
                f"more than the {REACH:,d} a two-ended walk can reach -- poll more "
                f"often, or slice the query further"
            )
        if self.shortfall:
            return (
                f"collected {self.seen:,d} of the {self.advertised:,d} the portal "
                f"advertised -- {self.shortfall:,d} short"
            )
        return None


def _page(days: int, page: int, sort: str) -> tuple[list[dict], int]:
    """One page of the search. Returns its rows and the total it advertises.

    The count is only ever in the `x-total-count` header -- the body is a bare
    JSON array with no envelope, so there is nothing else to read it from.
    `http` lowercases header names, because this lookup was case-sensitive
    once and the count silently read as zero over HTTP/2.
    """
    assert page * PAGE_SIZE < WINDOW, "the API answers 412 past the result window"
    body = json.dumps({"onlineSince": days}).encode()
    raw, headers = http.post_json_with_headers(
        f"{URL}?page={page}&size={PAGE_SIZE}&sort={sort}", body, timeout=90, retries=3
    )
    return json.loads(raw) or [], int(headers.get("x-total-count") or 0)


def _walk_end(days: int, sort: str, wanted: int) -> tuple[list[dict], int, int]:
    """Read up to `wanted` postings from one end. Returns (rows, pages, total)."""
    rows: list[dict] = []
    pages = advertised = 0
    while len(rows) < wanted and pages * PAGE_SIZE < WINDOW:
        page, total = _page(days, pages, sort)
        advertised = advertised or total
        pages += 1
        if not page:
            break
        rows += page
        if len(page) < PAGE_SIZE:
            break  # a short page is the end of the slice
    return rows, pages, advertised


def walk(days: int) -> tuple[list[dict], int, int]:
    """Every posting online in the last `days`. Returns (rows, pages, total).

    Forwards for the first 10,000, then backwards for whatever the window left
    behind. The backwards leg is skipped entirely on the common path, so a
    daily poll costs exactly the ten requests it looks like it should.
    """
    rows, pages, advertised = _walk_end(days, "date_desc", WINDOW)
    remaining = advertised - len(rows)
    if remaining > 0:
        # Reading the far end of the same ordering. `date_asc` is the exact
        # reverse, so these are the rows the forward leg could not reach --
        # and a slice under `REACH` overlaps in the middle rather than
        # leaving a hole, which is what `Sweep.repeats` then counts.
        tail, tail_pages, _ = _walk_end(days, "date_asc", min(remaining, WINDOW))
        rows += tail
        pages += tail_pages
    return rows, pages, advertised


def cursor(connection: sqlite3.Connection) -> int:
    """How many days back the next poll should read.

    Whole days, because that is the only resolution `onlineSince` has. The
    stored cursor is the date of the last successful poll; the window is the
    gap since then plus an overlap, and re-reading a day costs an idempotent
    upsert while missing one costs a posting.
    """
    stored = db.cursor(connection, NAME)
    if stored is None:
        return OVERLAP_DAYS + 1  # cold start: as far back as one walk reaches
    gap = (date.today() - date.fromisoformat(stored)).days
    return max(1, min(gap + OVERLAP_DAYS, MAX_ONLINE_SINCE))


def save_cursor(connection: sqlite3.Connection, when: date | None = None) -> None:
    db.save_cursor(connection, NAME, (when or date.today()).isoformat())


def _description(content: dict) -> tuple[str, str | None]:
    """(title, description) from the one language an ad is written in.

    `jobDescriptions` is a list and every ad in a 500-row sample carried
    exactly one entry, so this is not a language choice -- it is a list of one
    that would silently become a language choice if that ever changed. Taking
    the first is what the site itself renders.
    """
    entries = content.get("jobDescriptions") or []
    if not entries:
        return "", None
    return entries[0].get("title") or "", entries[0].get("description")


def _location(content: dict) -> str | None:
    """City and canton, in words the geography lexicon can read.

    The canton code follows the city because the board gates on geography and
    a bare `Zug` is also a German word; `Zug, ZG` is not. Postings abroad carry
    their own country and keep it.
    """
    where = content.get("location") or {}
    parts = [where.get("city"), where.get("cantonCode")]
    country = where.get("countryIsoCode")
    if country and country != "CH":
        parts.append(country)
    return ", ".join(part for part in parts if part) or None


def _domain(content: dict) -> str | None:
    """The employer's own domain, and only ever the employer's.

    A surrogate company record is an agency's stand-in for an employer it does
    not name, and its website is the agency's -- 372 of the 379 websites in a
    2,000-ad sample. Recording those would file a posting under a firm that
    never advertised it, which is the mis-attribution this project treats as
    expensive. `is_platform_domain` guards the rest, as it does in the four
    other layers that reach for a domain.
    """
    company = content.get("company") or {}
    if company.get("surrogate"):
        return None
    found = domain_of(company.get("website"))
    return None if is_platform_domain(found) else found


def _job(ad: dict) -> Job:
    content = ad.get("jobContent") or {}
    title, description = _description(content)
    return Job(
        ats=NAME,
        token=TOKEN,
        # The portal's own UUID, and the tail of its detail URL. The
        # `stellennummerEgov` beside it is the AVAM reference an employer
        # quotes, not a handle for the advertisement.
        job_id=str(ad["id"]),
        title=title,
        # A national portal advertises for everyone, so the advertiser's name
        # is the only identity most of these rows have -- see `_domain`.
        employer=(content.get("company") or {}).get("name"),
        # The source's own taxonomy, which is the gate `CLAUDE.md` prefers over
        # any word list. It is stored as the bare AVAM code because that is all
        # the portal publishes here: the occupation object carries codes and no
        # labels, and the reference service that would name them is not open.
        # So this cannot gate anything yet, and is kept rather than dropped
        # because re-deriving it later would cost a re-poll of the whole board.
        category=", ".join(
            str(code)
            for entry in content.get("occupations") or []
            if (code := entry.get("avamOccupationCode"))
        )
        or None,
        # The portal's own page rather than `jobContent.externalUrl`, which is
        # the employer's site and is missing on 1.6% of ads. This one is
        # derivable for every row and always resolves.
        url=f"https://www.job-room.ch/job-search/{ad['id']}",
        location=_location(content),
        # No department field exists, and nothing is parked here: `tagging.py`
        # folds `department` into the title when reading rank and role, so a
        # value smuggled in becomes a covert third door to seniority.
        department=None,
        posted_at=(ad.get("publication") or {}).get("startDate"),
        # Deliberately absent -- `publication.endDate` is a display window, not
        # an application deadline. See the module docstring.
        deadline=None,
        description=description,
    )


def run(connection: sqlite3.Connection, days: int | None = None) -> Sweep:
    """One poll. Returns what happened and whether to trust it.

    `days` overrides the stored cursor to re-read a window already polled, the
    way `jobstream --since` does. Replay is safe: every write is an idempotent
    upsert and the cursor only ever moves forward to today.
    """
    days = days or cursor(connection)
    rows, pages, advertised = walk(days)

    seen: set[str] = set()
    fresh: list[tuple[str | None, Job]] = []
    repeats = 0
    for row in rows:
        ad = row.get("jobAdvertisement") or {}
        if not ad.get("id"):
            continue
        if ad["id"] in seen:
            # The two ends overlap in the middle of any slice under `REACH`,
            # and the index moves under a walk besides. Both are ordinary.
            repeats += 1
            continue
        seen.add(ad["id"])
        fresh.append((_domain(ad.get("jobContent") or {}), _job(ad)))

    written = 0
    for domain, job in fresh:
        # One at a time because the domain differs per row here, unlike an ATS
        # board where every posting shares the firm's.
        written += db.upsert_jobs(connection, domain, [job])

    swept = Sweep(
        days=days,
        pages=pages,
        seen=len(seen),
        written=written,
        advertised=advertised,
        repeats=repeats,
    )
    # The cursor moves only on a sound poll. A truncated one that saved its
    # cursor would leave the unread remainder permanently behind the window.
    if swept.problem is None:
        save_cursor(connection)
    return swept
