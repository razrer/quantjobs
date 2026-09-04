"""Layer 4 -- the Interactive Employment Service, Hong Kong's statutory portal.

The Labour Department's board, and the answer to the question this project had
been asking since Singapore landed: *where is Hong Kong's MyCareersFuture?*
It is here, at `www2.jobs.gov.hk`, and it is the same kind of institution --
a government portal carrying every job an employer chose to advertise through
the territory's public employment service.

**It disallows crawling and this reads it anyway, at the reader's instruction.**
`robots.txt` ends `Disallow: /` above an allow-list of about forty corporate
and sector pages, none of them finance, and names `/0/api/*` separately. There
is no reading on which the job pages are meant to be open and only the URL
shapes closed. The decision is recorded in `ACTION-REQUIRED.md`; what this
module owes in return is **restraint**, which is the four-second interval in
`http.HOST_INTERVAL_S` -- a full sweep is about 750 requests and 50 minutes,
one reader, once a week. Nothing here changes the user agent, retries a
refusal, or rotates anything: the one thing altered is which paths are read,
and the one thing offered back is a rate far below what the portal serves the
public at.

**It enumerates, which is the property that matters.** The job list pages
cleanly to the end -- no result window, unlike Jobindex's 1,000 and
job-room.ch's 10,000 -- so nothing here is *forced* to partition. Measured live
on the unfiltered list: 14,287 postings over 715 pages of 20, page 715 short at
7 rows, page 716 empty. `pageSize` is ignored, so 20 is the page and 715 is the
price.

**It is walked as its own job-type partition, and that was measured rather
than assumed.** The portal publishes two facets and only one of them
partitions:

* **27 industries -- a cover, refused.** Their hitcounts sum to **15,175
  against 14,287**, so a posting can carry several and one classified under
  none would be absent from every slice while the arithmetic still looked
  right. (`Finance` is 137, `Insurance` 112, `Business Services` 1,659.)
* **29 job types -- an exact partition, used.** They sum to **14,287, delta
  zero**. That is the employer's own occupation for every posting, which is
  the signal `jobs.category` exists for and which `_MCF_OFF_INDUSTRY` and
  JobStream's `occupation_field` both prove is worth more than any word list
  written from memory. Nineteen of the twenty-nine can never hold a quant job
  -- `Cleaner` 1,084, `Security Guard` 1,382, `Driver` 806, `Cook / Waiter`
  933 -- which is 8,329 postings gated on the advertiser's own word.

The cost is ~4%: 715 pages of postings either way, plus one first page per
slice. **The gain is not only the label, it is a stronger check.** An
unfiltered walk has one published total to audit itself against; this one has
**thirty** -- each slice against its own hitcount, and the union against the
unfiltered total, which is also what re-proves the partition on every sweep. A
posting appearing in two slices shows up as a repeat and a posting in none
shows up as a shortfall, so nothing here has to be trusted between runs.

**The board publishes its own hitcount on every page** -- `Results 1 to 20 of
14,287` -- which is what the shortfall checks read. A round number in the
output is what a cap looks like from outside, and this is the only thing that
would say so.

**Two surfaces, and the list is the one to walk.** `quickview` carries a title,
a salary and a district; `joblist` carries those plus the posted date, the
required experience and the education level, in a server-rendered table. The
**employer name and the description are on neither** -- they are on the job
card, one request per posting, which is 14,287 requests where listing the whole
board is 715. So this module writes what the list carries and `bodies.py`
fetches the card for the postings whose verdict one could change, which is the
same split Workday, iCIMS and Oracle already use. The card carries the employer,
the industry, the responsibilities, the requirements and the employment terms.

**The card token expires, and believing otherwise cost a day.** A job card is
addressed by `?order=<base64>`, an encoding of the order number that the portal
mints per render -- the trailing block differs between two fetches of the same
list -- and there is no GET form that takes the order number instead
(`?ordno=`, `/ordno/`, `?searchKeyword=` and `?criteria.searchField=` were all
tried; the last is the real field name and a GET ignores it, returning the
whole board while looking like a match).

The first version of this module stored the token and used it, on the evidence
that a twenty-minute-old one still worked. **That evidence was too short a
window.** Tokens a couple of hours old return the vacancy-search page: 53 KB of
valid HTML, **HTTP 200**, and no card in it. The backfill filled 968 rows and
then silently filled nothing while still spending a request per row. Isolating
the cause matters, because the two candidates have opposite fixes: a
seconds-old token works in a **brand-new process with a fresh cookie jar**, so
it is *time* and not the session.

So nothing perishable is stored:

* **`jobs.url` is NULL.** A card whose "open" button lands on a search box is
  `CLAUDE.md`'s *worse than no link*; a card with no button is merely quiet,
  and the order number is the `job_id`, which the portal finds.
* **`bodies.iesjobs_body` mints a fresh token per posting**, with a POST to
  `/0/en/jobseeker/jobsearch/simple/` carrying `criteria.searchField`. That
  costs a second request per body -- about eight seconds a posting at this
  host's rate -- and it is the only form that works.
* **The link on that one-result page is a `data-jobcard` attribute, not an
  `href`.** The search answers in the *quickview* layout, whose only `<a>` is
  the clip button, so href scanning finds nothing while the search plainly
  succeeded. That is the Bridgewater lesson in a second place, and it is the
  half that took longest to see, because the failure is silent at every step.
* **A posting the search cannot find is off the board**, and the portal says
  so in words: *No jobs matching your search criteria*. That is a fact about
  the board rather than a fault.

**The order number is the identity and it is stable.** `22-26-0017657` is the
portal's own key, printed on the list and on the card, and it is what
`data-ordno` carries for the site's own clipping feature.

**A district is not a city, and this is the third country to teach it.**
Jobindex writes a postcode and a town, job-room.ch a town and a canton code,
and this board writes `Tsing Yi`, `Kwai Hing`, `Mong Kok` -- neighbourhoods
finer than its own 21-district taxonomy, matching no needle in
`tagging._HUBS`, so every one of them would read `other` and be **gated off the
board**. The handle is MyCareersFuture's: the territory leads and the districts
follow it.

**But not unconditionally, because 741 of these postings are somewhere else.**
The portal has an `Outside HK` location bucket, and sweeping it is what turned
that from a guess into a list: 461 of the 741 name *only* a place outside the
territory, and the whole vocabulary is nine words -- Shenzhen 303, Guangzhou
56, Dongguan 42, Mainland China 17, Zhuhai 14, Zhongshan 13, Foshan 11,
Huizhou 3, Jiangmen 2. The other 280 name a Hong Kong district *as well*, and
they are Hong Kong jobs with mainland travel, so they keep both. Hence the rule
below: the territory is claimed unless **every** place named is outside it.
"""

from __future__ import annotations

import html
import re
import sqlite3
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass

from . import db, http, parsing, sweep
from .models import Job

NAME = "iesjobs"
TOKEN = "hongkong"  # one national portal, so the board identifier is constant

ORIGIN = "https://www2.jobs.gov.hk"

# The list, newest first. `quickview` is the same result set with fewer
# columns; `joblist` is the one that carries the posted date. With no path
# suffix it is the whole board; `jobtype/{id}/` is one slice of the partition.
LIST_URL = ORIGIN + "/0/en/jobseeker/jobsearch/joblist/"

# **The portal's own occupation taxonomy, and it is an exact partition.** The
# 29 hitcounts sum to 14,287 against an unfiltered total of 14,287 -- delta
# zero -- so every posting carries exactly one of these and the union is the
# whole board. That is what makes it safe to walk the slices instead of the
# list: the alternative facet, 27 industries, sums to 15,175 and merely
# *covers*, where a posting classified under none would be missing and the
# arithmetic would still look right.
#
# `Tour Guide` (28) advertised zero on the day this was measured, which is why
# a slice with no hitcount and no rows is a legitimate answer here and a slice
# with a hitcount and no rows is not -- see `Slice.problem`.
JOB_TYPES = (
    (1, "Accounting"),
    (2, "Cashier"),
    (3, "Clerk"),
    (4, "Cleaner"),
    (5, "Computer and Information Technology"),
    (6, "Construction/Survey"),
    (7, "Customer Service"),
    (8, "Cook / Waiter"),
    (9, "Design / Draftsworker"),
    (10, "Delivery Worker"),
    (11, "Driver"),
    (12, "Domestic Helper"),
    (13, "Engineering"),
    (14, "Labourer"),
    (15, "Management / Administration"),
    (16, "Merchandiser"),
    (17, "Others"),
    (18, "Other Professional/Associate Professional"),
    (19, "Office Assistant"),
    (20, "Production / Factory"),
    (21, "Receptionist"),
    (22, "Marketing Representative / Sales"),
    (23, "Stockkeeper"),
    (25, "Secretary"),
    (26, "Teacher / Tutor"),
    (27, "Technician"),
    (28, "Tour Guide"),
    (30, "Typist"),
    (31, "Security Guard"),
)

# Fixed by the server. `pageSize=100` is accepted and ignored, which is the
# MAS trap one territory over -- so this is a fact about the portal rather
# than a parameter, and it is asserted rather than merely used.
PAGE_SIZE = 20

# A backstop against a server that never returns an empty page, not a limit on
# how big the portal may be -- see the Workday 40-page cap, which put LSEG and
# State Street at exactly 800 postings each. It bounds one *slice*, and the
# largest slice is `Security Guard` at 1,382 postings, so the real walk ends
# around page 70 of the longest one and 715 pages across all twenty-nine.
MAX_PAGES = 5_000

# An implausibly small result is a failure. The board holds ~14,000 postings;
# the sharper check is the shortfall against the hitcount the portal prints on
# every page, and this only catches the case where the page changed shape.
MIN_EXPECTED = 5_000

# One definition, in `sweep`. A posting re-filed from one job type to another
# mid-walk lands in two slices or none, which is the same turbulence one
# partition down.
SHORTFALL_TOLERANCE = sweep.SHORTFALL_TOLERANCE

# Everything the portal's own `Outside HK` bucket names as the sole place of a
# posting, plus the two markers that appear beside a district rather than
# alone. Measured over all 741 rows in that bucket -- see the module docstring.
# A name here does not remove a posting from anything; it only stops this
# module claiming Hong Kong on that posting's behalf.
_OUTSIDE_HK = frozenset({
    "mainland china", "macao", "macau", "overseas", "taiwan",
    "shenzhen", "guangzhou", "dongguan", "zhuhai", "zhongshan", "foshan",
    "huizhou", "jiangmen",
})

# One row of the list table. The board wraps every posting in this exact
# element and nothing else on the page uses it.
_ROW = re.compile(r'<tr class="bg-white">([\s\S]*?)</tr>')

# The order number and the card link. `id="{n}_orderNo_hyper"` is the portal's
# own per-row anchor, so this is the row's identity and its URL in one match.
_ORDER = re.compile(
    r'<a\s[^>]*id="\d+_orderNo_hyper"[^>]*href="([^"]+)"[^>]*>\s*([^<\s][^<]*?)\s*</a>'
)

# The title is the first `<span>` of the row's first column, immediately above
# the `Job Order No.` label. Anchored on that label rather than on position,
# because a column reordering must break loudly rather than silently swap two
# fields -- the `ADP meta.links` failure, where a confident wrong answer is
# worse than none.
_TITLE = re.compile(
    r'<span class="d-flex flex-column">\s*<span>([\s\S]*?)</span>'
)

# The remaining columns are marked by the icon the portal puts in front of
# each, which is the only per-field label in the row -- the header carries the
# words and the cells carry the pictures. Keying on the icon rather than on
# position is deliberate for the same reason `_TITLE` is anchored.
_FIELD = {
    "posted": re.compile(r'ies_job_icon1\.svg"[^>]*/?>\s*<span>([\s\S]*?)</span>'),
    "location": re.compile(r'ies_job_fill_but3\.svg"[^>]*/?>\s*<span>([\s\S]*?)</span>'),
}

# `Results <strong>1</strong> to <strong>20</strong> of <strong>14,287</strong>`
_HITCOUNT = re.compile(
    r"of\s*<strong>\s*([\d,]+)\s*</strong>", re.IGNORECASE
)

# `01/09/2026` -- day first, which is the one thing that must not be guessed:
# read as month-first it would file a September posting in January and the
# board sorts on dates.
_POSTED = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


# The portal footnotes a title with `**`, and its own legend at the foot of the
# list says what that means: *the employer is interested in employing eligible
# job seekers of the Employment Programme for the Elderly and Middle-aged*.
# That is a fact about the employer's hiring scheme, not part of the job's
# name, and it belongs in the title no more than `EA` -- the other marker on
# that legend -- would. Stripped so `Financial Planner**` reads as the job it
# is; `fold` would drop it from the *tagger's* view either way, but the board
# shows the title verbatim on the card.
_TITLE_MARKER = re.compile(r"\s*\*+\s*$")


@dataclass(frozen=True, slots=True)
class Slice:
    """One job-type slice, and whether that slice can be believed on its own.

    The partition gives thirty checks where an unfiltered walk gives one, and
    a slice is the unit each of the twenty-nine is made at.
    """

    key: int
    name: str
    pages: int
    seen: int
    advertised: int

    @property
    def problem(self) -> str | None:
        # **A slice may legitimately be empty and may not legitimately be
        # short.** `Tour Guide` advertised zero on the day this was measured,
        # and a facet with no vacancies is a fact rather than a fault. A slice
        # that *advertises* postings and hands over none is the failure this
        # project cares most about not being fooled by: HTTP 200 with an empty
        # board.
        if not self.advertised:
            return None if not self.seen else (
                f"{self.name}: {self.seen:,d} postings arrived under no "
                "hitcount -- the list page has changed shape"
            )
        short = self.advertised - self.seen
        if short > max(self.advertised * SHORTFALL_TOLERANCE, 2):
            return (
                f"{self.name}: collected {self.seen:,d} of {self.advertised:,d}"
                f" -- {short:,d} short"
            )
        return None


@dataclass(frozen=True, slots=True)
class Sweep:
    """What one walk of the portal did, and whether to believe it.

    The same shape `mycareersfuture.Sweep` has, deliberately: both are a
    national board with a published total, and a caller checking one should
    not have to learn a second vocabulary to check the other. What this one
    adds is `slices`, because the walk is a partition and **the partition is
    re-proved on every sweep rather than trusted between them**: a posting in
    two slices arrives as a repeat, and a posting in none arrives as a
    shortfall against `advertised`, which is the *unfiltered* total.
    """

    pages: int
    seen: int  # distinct postings collected across every slice
    written: int
    advertised: int  # the hitcount on the unfiltered list, i.e. the whole board
    repeats: int  # postings served by more than one slice, or by a moving index
    partial: bool  # a bounded run, so `advertised` is not the target
    slices: tuple[Slice, ...] = ()

    @property
    def shortfall(self) -> int:
        return 0 if self.partial else max(self.advertised - self.seen, 0)

    @property
    def problem(self) -> str | None:
        """The one thing a caller has to check. None means the sweep is sound."""
        if self.partial:
            return None
        if not self.advertised:
            return (
                "the portal printed no hitcount -- the list page has changed "
                "shape, so nothing here can be checked against anything"
            )
        # The shortfall is also the partition failing: a posting the employer
        # filed under no job type is in no slice, and it shows up here and
        # nowhere else -- so the message names that cause too.
        if wrong := sweep.problem(
            self.seen, self.advertised, MIN_EXPECTED, noun="portal",
            or_else=", or a job type this walk does not know about",
        ):
            return wrong
        broken = [s.problem for s in self.slices if s.problem]
        if broken:
            return f"{len(broken)} slice(s) short: " + "; ".join(broken[:3])
        return None


_text = parsing.text  # one definition, in `parsing`


def _posted(value: str | None) -> str | None:
    """`01/09/2026` as an ISO date, or None if it is not one.

    Returns None rather than guessing: a posting whose date cannot be read is
    a posting with no date, and the board treats that as unknown. Inventing
    one would put it in the wrong place in a deadline-ordered list.
    """
    match = _POSTED.match((value or "").strip())
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def _location(value: str | None) -> str | None:
    """Where the job is, in words `tagging._HUBS` can read.

    The portal writes a comma-separated list of districts -- `Mong Kok`,
    `Kwun Tong,Mainland China`, `Anywhere in H.K.` -- and a district matches no
    needle, so the territory has to lead. It is *not* claimed when every place
    named is outside it; see `_OUTSIDE_HK`, which is the portal's own bucket
    rather than a guess.
    """
    named = [part for raw in (value or "").split(",") if (part := raw.strip())]
    if not named:
        return None
    if all(part.casefold() in _OUTSIDE_HK for part in named):
        return ", ".join(named)
    return ", ".join(["Hong Kong", *named])


def _job(row: str, category: str | None = None) -> Job | None:
    """One posting out of one `<tr>`, or None if the row carries no anchor.

    `category` is the job-type slice this row was fetched from -- the portal's
    own occupation for the posting. It comes from the URL rather than from the
    row because the list prints the facet nowhere in the markup, which is also
    why the walk is a partition: each posting is read exactly once, under
    exactly one label.

    **A row with an order number and no title is a layout change**, and
    `fetch_page` is where that is caught rather than here -- see the raise
    there. One blank row is skipped and a whole page of them raises, which is
    the split that matters: a freak posting must not end a fifty-minute sweep,
    and the first column moving must not quietly halve the board. A row skipped
    for either reason is still counted by the slice's own shortfall check, so
    nothing is lost silently in between.
    """
    order = _ORDER.search(row)
    if not order:
        return None
    # `href` is captured and deliberately unused -- see `url=None` below.
    job_id = _text(order.group(2))
    title = _text(match.group(1) if (match := _TITLE.search(row)) else None)
    title = _TITLE_MARKER.sub("", title) if title else None
    if not job_id or not title:
        return None
    return Job(
        ats=NAME,
        token=TOKEN,
        job_id=job_id,
        title=title,
        # The list names no employer; `bodies.iesjobs_body` reads it off the
        # card. NULL rather than the portal's name, so a posting from nobody
        # stays visibly from nobody.
        employer=None,
        # **The portal's own occupation**, taken from the slice this row was
        # walked in. Verbatim, the same contract `Employer.category` and
        # JobStream's `occupation_field` follow: it sets how a posting ranks
        # and what gates it, never whether it is kept.
        category=category,
        # **No URL, and that is the project's own rule applied.** The portal
        # addresses a card by `?order=<base64>` and the token **expires with
        # time** -- see the module docstring. A stored one answers HTTP 200
        # with the vacancy-search page, which is exactly the shape `CLAUDE.md`
        # calls *worse than no link*: a card whose "open" button lands on a
        # search box is a lie, where a card with no button is merely quiet.
        # The order number is the `job_id` and the portal finds it, so nothing
        # is lost that a reader cannot recover.
        #
        # To reverse: `url=urllib.parse.urljoin(ORIGIN, html.unescape(href))`.
        # The links then work for a few hours after each sweep and not after.
        url=None,
        location=_location(
            _text(match.group(1)) if (match := _FIELD["location"].search(row)) else None
        ),
        # The portal has no department field, and parking anything else here
        # would be read as the job's name -- see `mycareersfuture`.
        department=None,
        posted_at=_posted(
            _text(match.group(1)) if (match := _FIELD["posted"].search(row)) else None
        ),
        # The portal publishes no closing date on the list, and the card's
        # "Employment Terms" prose is not one. Mining it would be the
        # `publication.endDate` mistake.
        deadline=None,
        description=None,
    )


def fetch_page(
    number: int, *, jobtype: int | None = None, category: str | None = None
) -> tuple[list[Job], int]:
    """One page of the list. Returns its postings and the hitcount it prints.

    `jobtype` selects one slice of the partition and `category` is that
    slice's own label, written onto every posting it yields -- the portal
    prints the occupation on the facet and not in the row, so the only place
    it can come from is the URL that asked for it. Without either, this is the
    whole board, which is what the union is audited against.
    """
    assert PAGE_SIZE == 20, "the portal ignores every page-size parameter"
    url = LIST_URL if jobtype is None else f"{LIST_URL}jobtype/{jobtype}/"
    if number > 1:
        url += f"?page={number}"
    page = http.get_text(url, timeout=90, retries=3)
    total = _HITCOUNT.search(page)
    rows = _ROW.findall(page)
    jobs = [job for row in rows if (job := _job(row, category))]
    # **A page of rows that yields no postings is a layout change**, and it is
    # the one thing here that must be loud: a board answering HTTP 200 and
    # coming back empty is principle 2 exactly, and the shortfall check alone
    # would report it as "truncation", which reads as our paging being wrong.
    # One row failing to parse is not this -- it is skipped above and shows up
    # in the slice's arithmetic.
    if rows and not jobs:
        raise ValueError(
            f"iesjobs: {len(rows)} row(s) on {url} and not one carries a title"
            " and an order number -- the list layout has changed"
        )
    return jobs, int(total.group(1).replace(",", "")) if total else 0


def card_links(number: int, *, jobtype: int | None = None) -> dict[str, str]:
    """One list page as `{order number: a card URL minted by *this* request}`.

    **The token is perishable and this is the cheap way to mint twenty of
    them.** `bodies._ies_card_url` mints one at a time, with a POST that
    searches for a single order number -- two requests per posting, about eight
    seconds each at this host's rate, and the search is exact-match only
    (a space- or comma-separated list of order numbers matches nothing, and a
    prefix matches nothing; both were measured). The list, meanwhile, prints a
    fresh card link beside every row it renders, twenty to a page. So a slice
    walked for its links costs one request per twenty postings where the search
    costs one per posting.

    That is the whole of the saving, and it is only a saving if the token is
    *used* promptly -- see `bodies._iesjobs_pass`, which fetches a page's cards
    before asking for the next page, so nothing here is ever more than about a
    minute old. Harvesting the whole board first and reading it afterwards
    would rebuild the expiry bug the module docstring is about.

    `_job` captures this same `href` and deliberately throws it away, because
    `jobs.url` must not hold a link that dies in a couple of hours. This
    returns it to a caller that spends it immediately and stores none of it,
    which is the one use the expiry permits.
    """
    url = LIST_URL if jobtype is None else f"{LIST_URL}jobtype/{jobtype}/"
    if number > 1:
        url += f"?page={number}"
    page = http.get_text(url, timeout=90, retries=3)
    links: dict[str, str] = {}
    for row in _ROW.findall(page):
        order = _ORDER.search(row)
        if not order:
            continue
        job_id = _text(order.group(2))
        if job_id:
            links[job_id] = urllib.parse.urljoin(
                ORIGIN, html.unescape(order.group(1))
            )
    return links


def walk(
    *,
    jobtype: int | None = None,
    category: str | None = None,
    max_pages: int = MAX_PAGES,
) -> Iterator[tuple[list[Job], int]]:
    """Page one slice newest-first, yielding (postings, advertised total).

    **Stops on an empty page, never on a short one.** Jobbsafari reported 5,421
    postings of 48,000 because page 11 came back 499 rows instead of 500, and
    Oracle truncated Kotak at 3,199 of 9,959 the same way. Page 715 of the
    unfiltered board is 7 rows and page 716 is empty, so the empty page is the
    real terminator and one extra request is the whole cost of using it.

    The repeat guard is what makes that safe: a server ignoring `page` serves
    page one forever and never returns an empty page.
    """
    previous: list[str] = []
    for number in range(1, max_pages + 1):
        jobs, advertised = fetch_page(number, jobtype=jobtype, category=category)
        if not jobs:
            return
        current = [job.job_id for job in jobs]
        if current == previous:
            return
        previous = current
        yield jobs, advertised


def run(connection: sqlite3.Connection, *, max_pages: int = MAX_PAGES) -> Sweep:
    """Sweep the portal into `jobs`. Returns what happened and whether to trust it.

    **Walks the job-type partition, and audits the union against the
    unfiltered total.** That last check is one request and it is what re-proves
    the partition every time: a posting the employer filed under a job type
    this module does not know about is in no slice, and it appears as a
    shortfall there and nowhere else.

    **No cursor and no incremental form.** The list is newest-first and a
    `since` top-up would be cheap, and it would also be the thing that silently
    loses a posting: only a completed walk refreshes `last_seen` on every live
    row, which is the sole way a withdrawal is ever noticed here. That argument
    is MyCareersFuture's and it applies harder at this size.

    `max_pages` below `MAX_PAGES` marks the sweep `partial`, so a bounded run
    for testing can never be reported as a complete one.
    """
    seen: set[str] = set()
    written = repeats = pages = 0
    slices: list[Slice] = []
    partial = max_pages < MAX_PAGES

    for key, name in JOB_TYPES:
        slice_pages = slice_seen = slice_total = 0
        for jobs, total in walk(jobtype=key, category=name, max_pages=max_pages):
            pages += 1
            slice_pages += 1
            slice_total = slice_total or total
            fresh = []
            for job in jobs:
                slice_seen += 1
                if job.job_id in seen:
                    repeats += 1
                    continue
                seen.add(job.job_id)
                fresh.append(job)
            # The portal publishes no employer website, so there is no domain
            # to bridge to `firms` -- the same contract MyCareersFuture has.
            written += db.upsert_jobs(connection, None, fresh)
        slices.append(Slice(key, name, slice_pages, slice_seen, slice_total))

    # The whole board, for the union check. One page, and it is the only thing
    # that can tell a complete partition from a partition missing a facet.
    advertised = 0 if partial else fetch_page(1)[1]

    return Sweep(
        pages=pages,
        seen=len(seen),
        written=written,
        advertised=advertised,
        repeats=repeats,
        partial=partial,
        slices=tuple(slices),
    )
