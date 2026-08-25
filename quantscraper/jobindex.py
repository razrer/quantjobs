"""Layer 4 -- Jobindex, Denmark's largest job board.

**This is a fallback, and what it replaces matters.** Sweden has JobStream and
Singapore has MyCareersFuture, both substantially complete *by law*. Denmark's
equivalent is STAR's `jobnet.dk`, which redirects to NemLog-in and needs a
Danish MitID the user does not have. Jobindex is private and publishing to it
is voluntary, so this is a **wide net and never a census** -- the same standing
correction `jobstream.py` carries about Platsbanken. Nothing downstream may
treat Denmark as covered because this module runs.

No key, no quota, no session cookie.

**The surface is the search page's own JSON island, not its markup.** Every
result page ships `var Stash = {...}` holding the search response as structured
records. The RSS feed is cleaner XML and was rejected: it carries neither the
employer's website nor a closing date, and runs the headline and company
together.

**The board states its own size and its own ceiling, and both are used.**
`hitcount` is how many postings a query matches and `max_page` is 50, so no
query yields more than 1,000 postings and page 51 answers HTTP 404 -- loud
rather than silent, which is the only reason it was cheap to find.

**So the board is enumerated by partitioning it under that window**, along the
site's own 81-subcategory taxonomy: an enumeration the employer picked from
rather than a word list we invented, which is what `jobs.category` exists for.
Measured, because the claim is cheap to test: **200 of 200 postings sampled
from the unfiltered feed carry at least one category.**

**Four subcategories are bigger than the window, and they are not dropped.**
Retail, childcare, care and hospitality each exceed 1,000, and it is tempting
to shrug -- the tagger gates all four as another profession. That is exactly
the write-time filtering principle 4 forbids: a posting dropped at ingest
cannot be recovered by re-running a classifier. An overflowing slice is
**split again** along `SPLIT_DIMENSIONS`, and reported short only if it still
will not fit.

**Each splitting dimension is a cover only because the site publishes an
"unspecified" bucket for it** -- without one, every ad that left the field
blank is dropped and nothing says so. Measured on all four overflowing slices,
the parts sum to at least the whole every time. The order below is fixed for
that reason, with `employment_place` -- whose parts sum *exactly* to the whole
-- last rather than first.

**The archive is not available and was not assumed to be.** `jobage=archive`
answers HTTP 401 anonymously, so slicing by publication date -- the obvious
partition, needing no "unspecified" bucket at all -- is closed.

**`deadline` is `apply_deadline` and never `lastdate`.** Both are dates on
every result and only the first is a closing date; `lastdate` is when the
*advertisement* comes down. Writing it would hand the board 17,000 confident
dates nobody promised, and the board pins an approaching deadline above
everything else. The two are distinguishable because the site says so: an ad
carries either `apply_deadline` or `apply_deadline_asap`.

**`domain` is the employer's own website, which neither sibling source has.**
`company.homeurl` resolves on 486 of 561 postings in a two-category sample and
is the firm's real host rather than a profile page -- a live bridge into
`firms`, so it goes through `resolve.is_platform_domain` like every other
domain here.

**robots.txt disallows the paging parameter, and this module uses it anyway.**
`Disallow: /jobsoegning*page=` covers the HTML search and the RSS feed alike,
while the site itself publishes `link_rss` URLs carrying `subid=` on every
result page. The rules read as written for search-engine crawlers rather than
for one reader polling one country once a day at one request per second. It is
recorded in `ACTION-REQUIRED.md` as a decision the user can reverse; reversing
it costs the sweep, because without `page` no query returns more than its
newest 20 postings.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass, field

from . import db, http
from .models import Job
from .resolve import domain_of, is_platform_domain

NAME = "jobindex"
TOKEN = "denmark"  # one national board, so the identifier is constant

SEARCH_URL = "https://www.jobindex.dk/jobsoegning"

# What the board serves per page and how many pages it serves for one query.
# Both are published in every response and both are *checked* against it rather
# than trusted -- see `parse`. 50 x 20 = 1,000, and page 51 is a 404.
PAGE_SIZE = 20
WINDOW_PAGES = 50

# A backstop against a server that never returns a short page, not a limit on
# how big a slice may be. The published window above is the real bound.
MAX_PAGES = 200

# An implausibly small result is a failure. The board held 17,534 postings when
# this was written and the four largest subcategories alone are 5,500 of them;
# it would have to lose two thirds before this stayed quiet. The sharper check
# is the per-slice shortfall against the board's own `hitcount`.
MIN_EXPECTED = 5_000

# The index moves while a sweep runs -- an ad posted between page 3 and page 4
# slides a row across the boundary -- so a few postings arrive twice or not at
# all. Anything past this is truncation, not turbulence.
SHORTFALL_TOLERANCE = 0.02

# How a slice that will not fit the window is cut further, in order. Each value
# list ends with the site's own "not stated" bucket, which is what makes the
# split a cover rather than a filter: without it, every ad that left the field
# blank would be dropped and nothing would say so. `employment_place` is last
# because its parts sum *exactly* to the whole -- it is the narrowest cut, so
# it is the one to reach for only when the wider ones have not been enough.
SPLIT_DIMENSIONS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("workinghours_type", (1, 2, -1)),
    ("employment_type", (1, 2, 3, 10, 4, 5, 6, 8, 9, 11, 12, -1)),
    ("employment_place", (3, 1, 2, 4)),
)

# The board's own taxonomy as it stood when this was written, id -> label.
# **It is a snapshot, not the source of truth.** `taxonomy()` reads the live
# list out of any result page, so a subcategory Jobindex adds is swept without
# an edit here; this exists so a sweep can name one that appeared, and so the
# read-time gate in `tagging.py` can be tested against labels the board really
# publishes. MyCareersFuture had to hard-code its equivalent and nearly missed
# a category worth 66 postings; here the board hands the list over.
SUBCATEGORIES: dict[int, str] = {
    1: "Systemudvikling og programmering",
    2: "Økonomi- og virksomhedssystemer",
    3: "IT-ledelse",
    4: "IT-drift og support",
    6: "Internet og WWW",
    7: "Tele- og datakommunikation",
    8: "Bygge- og anlægsteknik",
    10: "Medicinal og levnedsmiddel",
    11: "Elektroteknik",
    12: "Personale og HR",
    13: "Topledelse og bestyrelse",
    14: "Ledelse",
    15: "Øvrige",
    16: "Læge",
    17: "Sygeplejerske og jordemoder",
    18: "Kontor",
    21: "Sekretær og reception",
    23: "Børnepasning",
    24: "Bygge og anlæg",
    25: "Landbrug, skov og fiskeri",
    27: "Pædagog",
    28: "Lærer",
    33: "Økonomi og regnskab",
    35: "Finans og forsikring",
    36: "Nærings- og nydelsesmiddel",
    37: "Bibliotek",
    38: "Offentlig administration",
    40: "Tømrer og snedker",
    41: "Terapi og genoptræning",
    44: "Industriel produktion",
    45: "Forskning",
    47: "Pleje og omsorg",
    49: "Kommunikation og journalistik",
    51: "Tandlæge og klinikpersonale",
    52: "Jura",
    53: "Indkøb",
    54: "Logistik og spedition",
    55: "Marketing",
    56: "Frisør og personlig pleje",
    57: "Telemarketing",
    58: "Salg",
    60: "Ejendomsmægler",
    61: "Projektledelse",
    63: "Lægesekretær",
    65: "Kultur og kirke",
    67: "Hotel, restaurant og køkken",
    70: "Detailhandel",
    71: "Service",
    73: "Rengøring",
    74: "Lager",
    75: "Salgsledelse",
    77: "Socialrådgivning",
    79: "Institutions- og skoleledelse",
    80: "Elektriker",
    81: "Økonomiledelse",
    83: "Transport",
    85: "Maskinteknik",
    89: "Grafisk",
    90: "Jern og metal",
    91: "Psykologi og psykiatri",
    92: "Tekstil og kunsthåndværk",
    93: "Database",
    94: "Kemi og bioteknik",
    95: "Mekanik og auto",
    96: "Blik og rør",
    97: "Maling og overfladebehandling",
    98: "Ejendomsservice",
    99: "Bud og udbringning",
    100: "Teknisk sundhedsarbejde",
    103: "Voksenuddannelse",
    104: "Træ- og møbelindustri",
    106: "Oversættelse og sprog",
    110: "Design og formgivning",
    112: "Sikkerhed",
    120: "Selvstændig virksomhedsdrift",
    121: "Ledelse inden for ingeniør og teknik",
    122: "Produktions- og procesteknik",
    124: "Detailledelse",
    125: "Virksomhedsudvikling",
    126: "Akademisk og politisk arbejde",
    127: "Forsvar og efterretning",
}

_STASH = "var Stash = "
_TAGS = re.compile(r"<[^>]+>")

# What joins the categories a posting is filed under. **Not a comma**, which is
# what MyCareersFuture uses and what the labels here contain: "Hotel, restaurant
# og køkken" and "Landbrug, skov og fiskeri" would each split into two names
# that match nothing, so the read-time gate would silently stop firing on the
# two biggest trades on the board.
CATEGORY_SEPARATOR = " | "


class Blocked(RuntimeError):
    """The page answered but carried no search response.

    Raised rather than returning an empty page, because an empty page is how a
    walk terminates: a login wall or a redesigned island would otherwise read
    as "this slice is finished" and the sweep would report a clean, wrong
    number. Same rule every reader in `sites.py` follows.
    """


@dataclass(frozen=True, slots=True)
class Page:
    """One page of results, plus what the board said about the whole query."""

    rows: list[dict]
    hitcount: int
    max_page: int
    page_size: int
    taxonomy: dict[int, str]

    @property
    def window(self) -> int:
        """How many postings this query can yield before the ceiling."""
        return self.max_page * self.page_size


@dataclass(frozen=True, slots=True)
class Slice:
    """One query the sweep walks, as `(parameter, value)` pairs."""

    params: tuple[tuple[str, int], ...]

    def with_(self, name: str, value: int) -> "Slice":
        return Slice(self.params + ((name, value),))

    @property
    def query(self) -> dict[str, int]:
        return dict(self.params)

    def __str__(self) -> str:
        subid = self.query.get("subid")
        label = SUBCATEGORIES.get(subid, str(subid)) if subid else "all"
        rest = [f"{name}={value}" for name, value in self.params if name != "subid"]
        return label + (" [" + ", ".join(rest) + "]" if rest else "")


@dataclass(slots=True)
class Sweep:
    """What one sweep did, and whether to believe it."""

    slices: int = 0
    pages: int = 0
    seen: int = 0  # distinct postings collected
    written: int = 0
    repeats: int = 0  # rows already collected by an earlier slice or page
    advertised: int = 0  # what the board said the unfiltered total was
    # The sweep was not asked to read the whole board -- a `since` top-up or a
    # named subset of categories -- so the board's own total is not the target
    # and falling short of `MIN_EXPECTED` is the request, not a failure.
    partial: bool = False
    stale: bool = False  # a top-up hit the window before reaching `since`
    truncated: list[tuple[str, int, int]] = field(default_factory=list)
    unknown_subcategories: dict[int, str] = field(default_factory=dict)

    @property
    def unread(self) -> int:
        """Postings a slice advertised that the window would not let us reach."""
        return sum(hits - window for _, hits, window in self.truncated)

    @property
    def problem(self) -> str | None:
        """The one thing a caller has to check. None means the sweep is sound."""
        if self.stale:
            return (
                "the top-up reached the 1,000-posting window before it reached "
                "the cutoff date, so postings between them were never read -- "
                "run a full sweep"
            )
        if self.truncated:
            worst = ", ".join(
                f"{name} ({hits:,d} advertised, {window:,d} reachable)"
                for name, hits, window in sorted(
                    self.truncated, key=lambda item: -item[1]
                )[:4]
            )
            return (
                f"{len(self.truncated)} slice(s) would not fit the window even "
                f"after splitting, so {self.unread:,d} posting(s) were never "
                f"reached: {worst}"
            )
        if self.partial:
            return None
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


def parse(markup: str) -> Page:
    """The search response out of the page's own JSON island.

    Read with `raw_decode` from the assignment onwards rather than by taking the
    rest of the line: the island is one line today, and a pretty-printer at
    their end would otherwise silently halve every page.
    """
    start = markup.find(_STASH)
    if start < 0:
        raise Blocked("no Stash island in the page")
    try:
        stash, _ = json.JSONDecoder().raw_decode(markup, start + len(_STASH))
    except ValueError as exc:
        raise Blocked(f"unreadable Stash island: {exc}") from exc

    store = (stash.get("jobsearch/result_app") or {}).get("storeData") or {}
    response = store.get("searchResponse")
    if not response:
        raise Blocked("the Stash island carries no search response")

    return Page(
        rows=response.get("results") or [],
        hitcount=int(response.get("hitcount") or 0),
        # Defaulted to the constants only if the board stops publishing them.
        # It publishes both today, and preferring our own number over theirs is
        # how a page-count guard becomes a silent cap.
        max_page=int(response.get("max_page") or WINDOW_PAGES),
        page_size=int(response.get("page_size") or PAGE_SIZE),
        taxonomy={
            int(subid): label
            for _, subs in store.get("subjobcategory_list") or []
            for label, subid in subs
        },
    )


def fetch_page(query: dict[str, int], page: int) -> Page:
    """One page of one query."""
    params = {**query, "page": page} if page > 1 else dict(query)
    url = SEARCH_URL
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return parse(http.get_text(url, timeout=90, retries=3))


def taxonomy() -> dict[int, str]:
    """The board's live subcategory list, id -> label.

    Read rather than hard-coded, so a category Jobindex adds is swept without an
    edit. `SUBCATEGORIES` is the snapshot this is compared against.
    """
    return fetch_page({}, 1).taxonomy


def walk(
    query: dict[str, int], *, since: str | None = None, first: Page | None = None
) -> Iterator[Page]:
    """Page one query, yielding pages until the slice or the window ends.

    Stops on a short page, on a page repeating the previous one -- a server
    ignoring `page` serves page one forever and never returns an empty page --
    at the board's own `max_page`, or at `MAX_PAGES`, which is a backstop
    against a server doing none of those.

    `since` is an ISO date and stops the walk once an entire page is older than
    it. Whole page rather than whole row: postings sharing a day are in no
    guaranteed order among themselves, so stopping mid-page would cut the day.

    `first` is page one already in hand. The sweep has to read it before it can
    know whether the slice fits the window, and fetching it a second time here
    would be one wasted request per slice against a board with eighty of them.
    """
    previous: set[str] = set()
    for page in range(1, MAX_PAGES + 1):
        current = first if page == 1 and first is not None else fetch_page(query, page)
        if not current.rows:
            return

        ids = {row.get("tid") for row in current.rows}
        if ids == previous:
            return
        previous = ids

        yield current

        if len(current.rows) < current.page_size:
            return
        if page >= current.max_page:
            return
        if since and max((row.get("firstdate") or "") for row in current.rows) < since:
            return


def slices(known: dict[int, str] | None = None) -> Iterator[Slice]:
    """One slice per subcategory, which is the partition the sweep walks."""
    for subid in sorted(SUBCATEGORIES if known is None else known):
        yield Slice((("subid", subid),))


def _text(value: str | None) -> str | None:
    """Plain text out of the rendered advertisement teaser.

    Tags are stripped before entities are decoded, never after: an employer who
    writes a literal `&lt;p&gt;` would otherwise have it turned into a tag and
    then eaten. Same order as `mycareersfuture._text`, for the same reason.
    """
    if not value:
        return None
    return " ".join(html.unescape(_TAGS.sub(" ", value)).split()) or None


def _location(row: dict) -> str | None:
    """Where the job is, in words the geography lexicon can read.

    `area` is the board's own phrasing and is what a reader sees -- "Koebenhavn
    OE og mulighed for hjemmearbejde". It is blank on a minority of rows and the
    structured address is the fallback: a gate makes every gap in a place list a
    deleted posting, so a town name that is merely inelegant beats none at all.
    """
    if area := (row.get("area") or "").strip():
        return area
    towns = [
        town
        for entry in row.get("addresses") or []
        if (town := (entry.get("city") or "").strip())
    ]
    # Deduplicated in first-seen order: a firm advertising one seat across three
    # of its own offices lists the same city as often as not.
    return ", ".join(dict.fromkeys(towns)) or None


def _deadline(row: dict) -> str | None:
    """The published application deadline, or nothing.

    **Never `lastdate`.** That is the day the advertisement stops being shown,
    it is set on every row, and an ad carrying it instead of `apply_deadline` is
    one whose employer said *snarest muligt* -- as soon as possible. Reading it
    as a closing date would pin thousands of Danish cards to the top of a board
    that sorts deadline-first, on dates nobody stated.
    """
    if row.get("apply_deadline_asap"):
        return None
    return row.get("apply_deadline") or None


def _domain(row: dict) -> str | None:
    """The employer's own host, if the board published a real one.

    A firm advertising through an agency, or one with no site of its own, gives
    a platform page instead -- and a domain thousands of firms share is not an
    identity. The fifth layer `is_platform_domain` has had to guard.
    """
    company = row.get("company") or {}
    domain = domain_of(company.get("homeurl"))
    return None if is_platform_domain(domain) else domain


def _job(row: dict, category: str | None) -> Job:
    return Job(
        ats=NAME,
        token=TOKEN,
        # The board's own key and the tail of every share URL. `h1690894` and
        # `r13949465` are the two prefixes -- a paid advertisement and a robot
        # one -- and the letter is part of the id rather than decoration.
        job_id=str(row["tid"]),
        title=row.get("headline") or "",
        # A national board advertises for everyone, so the advertiser's name is
        # the only thing naming the firm on rows where no domain resolves.
        employer=(row.get("companytext") or "").strip() or None,
        # The board's own taxonomy, not a guess read off the title. It is not on
        # the posting -- it is the slice the posting arrived in -- which is why
        # it is passed in rather than read out of `row`.
        category=category,
        # Never the `/c?t=...` link on the row: that is a click tracker, it is
        # disallowed in robots.txt, and it carries the search session it was
        # minted in. `share_url` is the stable public address.
        url=row.get("share_url"),
        location=_location(row),
        # No department field exists, and a `positionLevels`-shaped field is not
        # smuggled into one: `tagging.py` folds `department` into the title, so
        # anything parked here becomes a covert third door to seniority.
        department=None,
        posted_at=row.get("firstdate"),
        deadline=_deadline(row),
        # The rendered teaser: the first paragraph or two of the ad plus the
        # board's own chrome. The full text lives on `/vis-job/{tid}` and is
        # `bodies.py`'s job, not this module's.
        description=_text(row.get("html")),
    )


def _write(connection: sqlite3.Connection, rows: list[tuple[str | None, Job]]) -> int:
    """Upsert a page, grouped by domain.

    `db.upsert_jobs` takes one domain for a whole batch because every other
    source's board *is* one firm's. Here each row carries its own, so they are
    grouped rather than written a row at a time.
    """
    batches: dict[str | None, list[Job]] = {}
    for domain, job in rows:
        batches.setdefault(domain, []).append(job)
    return sum(
        db.upsert_jobs(connection, domain, jobs) for domain, jobs in batches.items()
    )


def _recategorise(
    connection: sqlite3.Connection, held: dict[str, set[str]], ids: list[str]
) -> None:
    """Widen the category of postings a later slice also matched.

    A posting is filed under more than one category about a quarter of the
    time, and the sweep meets it again in the second category's slice. Skipping
    it there entirely would leave `jobs.category` holding whichever slice
    happened to reach it first -- so `Rengøring | Finans og forsikring` would be
    a cleaning job or a finance job depending on sweep order, and the read-time
    gate would drop it half the time. Only the category is rewritten; every
    other field was already correct on the first pass.
    """
    with connection:
        connection.executemany(
            "UPDATE jobs SET category = ? WHERE ats = ? AND token = ? AND job_id = ?",
            [
                (CATEGORY_SEPARATOR.join(sorted(held[tid])), NAME, TOKEN, tid)
                for tid in ids
            ],
        )


def _collect(
    connection: sqlite3.Connection,
    query: dict[str, int],
    label: str | None,
    sweep: Sweep,
    seen: dict[str, set[str]],
    *,
    since: str | None = None,
    first: Page | None = None,
) -> int:
    """Walk one query into `jobs`. Returns the hitcount it advertised."""
    hitcount = 0
    for page in walk(query, since=since, first=first):
        sweep.pages += 1
        hitcount = hitcount or page.hitcount
        fresh: list[tuple[str | None, Job]] = []
        widened: list[str] = []
        for row in page.rows:
            tid = row.get("tid")
            if not tid:
                continue
            if tid in seen:
                # Counted, not silenced: overlap is normal here -- between
                # category slices because a posting carries two categories, and
                # within a split because an ad offered as full *or* part time
                # is in both halves. The count is what distinguishes either
                # from a walk being served the same page twice.
                sweep.repeats += 1
                if label and label not in seen[tid]:
                    seen[tid].add(label)
                    widened.append(tid)
                continue
            seen[tid] = {label} if label else set()
            fresh.append((_domain(row), _job(row, label)))
        sweep.written += _write(connection, fresh)
        if widened:
            _recategorise(connection, seen, widened)
    return hitcount


def _sweep_slice(
    connection: sqlite3.Connection,
    which: Slice,
    label: str | None,
    sweep: Sweep,
    seen: dict[str, set[str]],
    depth: int = 0,
) -> None:
    """Walk one slice, splitting it further if it will not fit the window.

    The split is what keeps this an enumeration. A slice bigger than the ceiling
    is not "mostly read" -- it is a slice whose oldest postings no query can
    reach, and the alternative to splitting is deciding at ingest that those
    postings did not matter.
    """
    first = fetch_page(which.query, 1)

    if first.hitcount <= first.window or depth >= len(SPLIT_DIMENSIONS):
        # Only a slice that is actually walked is counted, so the number reads
        # as "queries this sweep enumerated" rather than counting the interior
        # nodes of the split tree, which enumerate nothing.
        sweep.slices += 1
        got = _collect(connection, which.query, label, sweep, seen, first=first)
        if got > first.window:
            sweep.truncated.append((str(which), got, first.window))
        return

    name, values = SPLIT_DIMENSIONS[depth]
    for value in values:
        _sweep_slice(connection, which.with_(name, value), label, sweep, seen, depth + 1)


def run(
    connection: sqlite3.Connection,
    *,
    since: str | None = None,
    only: list[int] | None = None,
) -> Sweep:
    """Sweep the board into `jobs`. Returns what happened and whether to trust it.

    **No durable cursor, unlike JobStream.** A full sweep is roughly 1,300
    requests, and running it refreshes `last_seen` on every posting still live,
    which is how a listing goes missing here. `since` walks the *unfiltered*
    board instead -- newest-first, 0 inversions measured over 140 rows -- which
    is a cheap daily top-up and needs no assumption about the ordering inside a
    category slice. If that top-up reaches the 1,000-posting window before it
    reaches the cutoff it says so rather than reporting a clean number: more was
    posted since than one query can serve, and only a full sweep closes it.
    """
    sweep = Sweep(partial=since is not None or bool(only))
    # tid -> every category slice that matched it, so a posting filed under two
    # keeps both rather than whichever slice reached it first.
    seen: dict[str, set[str]] = {}

    board = fetch_page({}, 1)
    sweep.advertised = board.hitcount
    live = board.taxonomy or SUBCATEGORIES
    # A category the board grew since this file was written is swept anyway --
    # `live` is what drives the partition. Naming it is so a reader knows the
    # gate in `tagging.py` has not been asked about it yet.
    sweep.unknown_subcategories = {
        subid: label for subid, label in live.items() if subid not in SUBCATEGORIES
    }

    if since is not None:
        sweep.slices = 1
        # No category: the unfiltered board says which postings exist, not
        # which slice they belong to. `db.upsert_jobs` coalesces, so this never
        # erases a category a full sweep established -- a posting *first* seen
        # by a top-up simply carries none until the next one, and a NULL
        # category passes the read-time gate, which is the safe direction.
        _collect(connection, {}, None, sweep, seen, since=since, first=board)
        sweep.seen = len(seen)
        # The window is a ceiling on the top-up, not on the board: reaching it
        # means the cutoff was never reached, so the days in between were read
        # by nobody.
        sweep.stale = sweep.seen >= board.window
        return sweep

    # The live list drives the partition so a new category is swept; the
    # snapshot backs it up so a category the board drops from its menu can
    # still be named to `only`. An id in neither is a typo, and a typo that
    # quietly sweeps nothing is the failure mode this project refuses.
    known = {**SUBCATEGORIES, **live}
    if only and (unknown := [subid for subid in only if subid not in known]):
        raise ValueError(
            "no such subcategory: " + ", ".join(str(subid) for subid in unknown)
        )
    wanted = {subid: known[subid] for subid in (only or live)}
    for which in slices(wanted):
        _sweep_slice(connection, which, wanted[which.query["subid"]], sweep, seen)

    sweep.seen = len(seen)
    return sweep
