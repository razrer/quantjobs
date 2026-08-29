"""Layer 3C -- named firms whose board is their own website.

**Why this exists, and why it is deliberately a short list.** `audit --pipeline`
asked which roster firms actually produce postings and Stockholm answered 7/20.
Probing the thirteen misses by hand found that most of them run no applicant
tracking system at all: AP4 publishes five openings as ordinary links under
`/karriar/lediga-tjanster/`, Brummer & Partners publishes one as a paragraph on
its careers page, and Nordea serves 110 through a JSON endpoint on its own
domain. There is no vendor to fingerprint and no feed to guess, so the answer
is a per-firm reader -- opened by a measurement rather than by enthusiasm.

**A firm earns a reader here only by being on the roster and having no ATS.**
The moment a firm migrates to a vendor `ats.py` recognises, its `ats_resolution`
row should go back to that vendor and its entry here should be deleted -- a
hand-written scraper is a liability with a maintenance cost, not an asset. The
list is short on purpose and the docstrings say what each one is reading, so a
broken one can be diagnosed without re-doing the reconnaissance.

**They ride Layer 3 rather than replacing it.** Each site is registered in
`ats_resolution` as `ats='site'`, `token=<key>`, tier A, so `extract.run` polls
it on the same thread pool, under the same per-host throttle, into the same
`jobs` table, and `alerts.py` watches its volume like any other source. The
dispatch is `extract.EXTRACTORS['site']`, which is this module's `read`.

**The failure mode to design against is the one `heyrowan` taught**: a scraper
that keeps returning something after the page it reads has been redesigned. So
every reader here raises rather than returning an empty list when the *anchor*
it keys on is missing -- a heading, a JSON key, a link shape. An empty board is
an answer; a missing anchor is a broken reader, and the two must not look alike.
`alerts.py` cannot tell them apart from volume alone.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass

from . import db, http
from .models import Job


def _text(value: str | None) -> str | None:
    from .extract import _text as shared  # one definition, in the module that owns it

    return shared(value)


class SiteChanged(ValueError):
    """The page no longer has the anchor this reader keys on.

    Raised rather than returning `[]`, because `extract._poll` turns an
    exception into a printed failure and a zero into "this firm is not hiring".
    Those are opposite facts and only one of them needs a human.
    """


# --------------------------------------------------------------------------
# Nordea -- Stockholm and Copenhagen, one board


_NORDEA_PAGE = 50
_NORDEA_PAGES = 200


def nordea() -> list[Job]:
    """Nordea, from the JSON endpoint behind its own "Open jobs" page.

    The page itself is 385 KB of shell naming no vendor, which is why the firm
    sat in tier B; the endpoint is `/en/api/jobs-list` and was found in the
    site's own JavaScript bundle rather than guessed.

    Three things worth knowing about the payload:

      * `count` is the true total on every page, so it is used as the check
        the same way `oracle_hcm` and `jobvite` use theirs;
      * `field_apply_due` is a **published closing date**, which makes Nordea
        one of the few sources that states one as a field;
      * `field_ad_url` points at `careers.nordea.com`, a SuccessFactors career
        site. That is the vendor, and it is unreadable -- 206 KB of shell with
        no job id. Nordea's own API is the way in, which is the general lesson:
        a firm's website sometimes exposes what its ATS does not.

    One reader covers two roster lines. Nordea and Nordea DK are the same
    board, and the postings carry their own country in `location_name`.
    """
    jobs: list[Job] = []
    advertised: int | None = None
    for page in range(_NORDEA_PAGES):
        payload = json.loads(
            http.get_text(
                "https://www.nordea.com/en/api/jobs-list"
                f"?page={page}&items_per_page={_NORDEA_PAGE}",
                timeout=25,
                retries=2,
            )
        )
        if "results" not in payload:
            raise SiteChanged("nordea: no 'results' key in /en/api/jobs-list")
        if advertised is None:
            # Serialised as a string on this endpoint, and comparing it to a
            # length raises rather than silently doing nothing -- which is the
            # good direction, but only because it was caught in a dry-run.
            try:
                advertised = int(payload.get("count"))
            except (TypeError, ValueError):
                advertised = None
        rows = payload["results"]
        for row in rows:
            # `nid` is the node id on Nordea's own site and is the only stable
            # key: `url` is a slug that changes when a title is edited.
            job_id = str(row.get("nid") or "")
            if not job_id:
                continue
            jobs.append(
                Job(
                    ats="site",
                    token="nordea",
                    job_id=job_id,
                    title=_text(row.get("title")) or "",
                    url=row.get("url") or row.get("field_ad_url"),
                    location=_text(row.get("location_name")),
                    department=_text(row.get("category_name")),
                    posted_at=row.get("created"),
                    deadline=row.get("field_apply_due"),
                )
            )
        if len(rows) < _NORDEA_PAGE:
            break
    if advertised is not None and advertised > len(jobs):
        raise SiteChanged(
            f"nordea: board advertises {advertised} postings, read {len(jobs)}"
        )
    return jobs


# --------------------------------------------------------------------------
# AP4 -- Fjarde AP-fonden


_AP4_JOB = re.compile(
    r'<a[^>]{0,200}href="(/karriar/lediga-tjanster/([a-z0-9-]{3,120})/)"[^>]{0,200}>'
    r"([^<]{3,200})</a>",
    re.I,
)


def ap4() -> list[Job]:
    """AP4, whose openings are ordinary links on its own site.

    `/karriar/lediga-tjanster/{slug}/` with the title as anchor text. There is
    no ATS anywhere in the markup and no feed; the fund is small enough that
    its five openings are hand-written pages.

    **The slug is the id, not the title.** A title gets edited; the URL is what
    the fund links to from elsewhere. The index page links to itself with the
    same prefix, so a link with no slug after it is skipped -- otherwise the
    listing page would be recorded as a posting called "Lediga tjänster".

    The same markup appears in the mobile menu, so every posting is listed
    twice and the second is dropped.
    """
    body = http.get_text(
        "https://ap4.se/karriar/lediga-tjanster/", timeout=25, retries=2
    )
    if "lediga-tjanster" not in body:
        raise SiteChanged("ap4: /karriar/lediga-tjanster/ no longer names itself")
    jobs: list[Job] = []
    seen: set[str] = set()
    for href, slug, title in _AP4_JOB.findall(body):
        if slug in seen:
            continue
        seen.add(slug)
        jobs.append(
            Job(
                ats="site",
                token="ap4",
                job_id=slug,
                title=_text(title) or "",
                url=urllib.parse.urljoin("https://ap4.se/", href),
                location="Stockholm, Sweden",
            )
        )
    return jobs


# --------------------------------------------------------------------------
# Brummer & Partners


# The whole careers page is one free-text block, so the heading is the anchor
# and each posting is a bolded title inside it. Bounded, like every pattern in
# this project that runs over fetched markup.
_BRUMMER_BLOCK = re.compile(
    r"<h2>\s*Lediga\s*tj(?:&#xE4;|ä)nster\s*</h2>([\s\S]{0,20000}?)</div>", re.I
)
_BRUMMER_JOB = re.compile(
    r"<p><strong>([^<]{3,160})</strong></p>\s*(?:<p>([\s\S]{0,2000}?)</p>)?", re.I
)
_BRUMMER_APPLY = re.compile(r'<a[^>]{0,200}href="(https?://[^"]{10,300})"', re.I)


def brummer() -> list[Job]:
    """Brummer & Partners, whose openings are paragraphs under a heading.

    Sweden's largest hedge fund group, and its careers page is prose: a
    `Lediga tjänster` heading, then a bolded title, a paragraph, and an
    "Ansök här" link out to whichever recruiter is handling it -- Recruto and
    Sharp Recruitment both appear, which is why no ATS fingerprint exists and
    why guessing one would be wrong.

    **The heading is the anchor and its absence is an error.** A redesign that
    renames it would otherwise turn into "Brummer is not hiring" forever, which
    is precisely the silent failure this project keeps designing against. An
    empty block is fine -- that is a real answer, and the firm posts rarely.
    """
    body = http.get_text(
        "https://www.brummer.se/sv/om-oss/karriar/", timeout=25, retries=2
    )
    found = _BRUMMER_BLOCK.search(body)
    if not found:
        raise SiteChanged("brummer: no 'Lediga tjänster' heading on the careers page")
    block = found.group(1)
    jobs: list[Job] = []
    seen: set[str] = set()
    # Each posting owns the markup from its own title up to the next one. The
    # obvious version searched the whole block for the apply link, which is
    # invisible while the firm has one opening and gives every posting the
    # first firm's link the moment it has two.
    titles = list(_BRUMMER_JOB.finditer(block))
    for index, match in enumerate(titles):
        end = titles[index + 1].start() if index + 1 < len(titles) else len(block)
        segment = block[match.start():end]
        name, summary = _text(match.group(1)), match.group(2)
        if not name:
            continue
        # The apply link is the only per-posting URL, and it is off-site --
        # Recruto for one opening, Sharp Recruitment for another.
        apply = _BRUMMER_APPLY.search(segment)
        job_id = name.casefold().replace(" ", "-")[:80]
        if job_id in seen:
            continue
        seen.add(job_id)
        jobs.append(
            Job(
                ats="site",
                token="brummer",
                job_id=job_id,
                title=name,
                url=apply.group(1) if apply else "https://www.brummer.se/sv/om-oss/karriar/",
                location="Stockholm, Sweden",
                description=_text(summary),
            )
        )
    return jobs


# --------------------------------------------------------------------------
# AP7, Captor and Norron -- three more prose careers pages


# **A firm that advertises nothing says so, and that sentence is the anchor.**
# Captor and Norron have no board at all: both print one line saying there are
# no vacancies and give an email address. A reader that simply returned `[]`
# for them would be indistinguishable from a reader whose page had been
# redesigned underneath it, and the firm would be reported as quiet forever.
# Finding either a posting *or* this sentence proves the page was understood.
_NO_VACANCIES = re.compile(
    r"inga\s+(?:aktuella\s+)?lediga\s+tj|har\s+vi\s+inga\s+lediga"
    r"|f(?:&#xF6;|ö)r\s+n(?:&#xE4;|ä)rvarande\s+inga|no\s+(?:current\s+)?vacanc"
    r"|no\s+open\s+positions",
    re.I,
)

# `<p>...<a href="...">?<strong>Title</strong></a>?...</p>` -- AP7 wraps the
# bold title in the recruiter's link, Brummer puts the link in a later
# paragraph, and the anchor is optional because a posting with no link yet is
# still a posting.
#
# **Both nestings occur on the same page**, which cost a posting before it was
# noticed: AP7 writes three of its four as `<a><strong>Title</strong></a>` and
# the fourth as `<strong><a>Title</a></strong>` -- the Senior Portfolio Manager,
# Asset Allocation seat, which is the single most relevant row on the page. A
# hand-edited page has no house style, so the parser cannot assume one.
_PROSE_JOB = re.compile(
    r"<p[^>]{0,200}>\s*(?:"
    r"<a[^>]{0,300}href=\"(?P<href1>https?://[^\"]{10,300})\"[^>]{0,120}>\s*"
    r"<strong>(?P<title1>[^<]{3,200})</strong>"
    r"|<strong>\s*(?:<a[^>]{0,300}href=\"(?P<href2>https?://[^\"]{10,300})\"[^>]{0,120}>)?"
    r"\s*(?P<title2>[^<]{3,200})<"
    r")",
    re.I,
)


def _prose_board(token: str, url: str, city: str) -> list[Job]:
    """Postings from a careers page written as prose rather than a board.

    Three Stockholm roster firms publish this way and none of them runs an
    ATS, so there is nothing to fingerprint and nothing to guess. The postings
    are bolded titles, usually wrapped in a link out to whichever recruiter is
    handling the search -- AP7 uses Amendo and SJR, Brummer uses Recruto and
    Sharp Recruitment. The recruiter is not the board: the same firm uses two
    at once, so the firm's own page is the only complete list.

    **Silence has to be proved, not assumed.** If the page yields no postings
    *and* does not say it has none, this raises: an empty result and a broken
    parser look identical from the outside, and only one of them is news.
    """
    body = http.get_text(url, timeout=25, retries=2)
    jobs: list[Job] = []
    seen: set[str] = set()
    for match in _PROSE_JOB.finditer(body):
        apply_url = match.group("href1") or match.group("href2")
        name = _text(match.group("title1") or match.group("title2"))
        if not name:
            continue
        job_id = name.casefold().replace(" ", "-")[:80]
        if job_id in seen:
            continue
        seen.add(job_id)
        jobs.append(
            Job(
                ats="site",
                token=token,
                job_id=job_id,
                title=name,
                url=apply_url or url,
                location=city,
            )
        )
    if not jobs and not _NO_VACANCIES.search(body):
        raise SiteChanged(
            f"{token}: no postings found and the page does not say it has none"
        )
    return jobs


def ap7() -> list[Job]:
    """AP7, the state default fund in the Swedish premium pension system.

    **The roster's domain for this firm was wrong, and the wrong one resolved.**
    `sjunde.se` is *Sjunde Konsultbolaget*, a Stockholm IT consultancy -- a
    plausible-looking match on the fund's Swedish name, and exactly the failure
    `domains.py` grades against: a wrong domain is a silently empty feed rather
    than an obvious error. The fund is `ap7.se`, and its openings sit at
    `/kontakt/lediga-tjanster/` -- four of them, including two portfolio
    manager seats, none of which anything here could see.
    """
    return _prose_board(
        "ap7", "https://www.ap7.se/kontakt/lediga-tjanster/", "Stockholm, Sweden"
    )


def captor() -> list[Job]:
    """Captor Fund Management. No board -- applications go to an inbox.

    The page currently reads *"För tillfället har vi inga lediga tjänster"* and
    gives an address to send a speculative application to. That is a real
    answer about a small manager, and the reader exists so that the day it
    changes, the posting is picked up rather than waiting for someone to check.
    """
    return _prose_board("captor", "https://captor.se/om-oss/karriar/", "Stockholm, Sweden")


def norron() -> list[Job]:
    """Norron Asset Management. No board -- applications go to the CEO.

    Same shape as Captor. The roster notes Norron's fund business is being sold
    to Simplicity AB, so this one may become stale rather than merely quiet;
    the reader will keep saying "nothing" either way, and the distinction is
    the roster's job rather than this module's.
    """
    return _prose_board("norron", "https://norron.com/sv/karriar/", "Stockholm, Sweden")


# --------------------------------------------------------------------------
# 323 Trading


_323_TITLE = re.compile(r"<h1>([\s\S]{3,160}?)</h1>", re.I)


def trading_323() -> list[Job]:
    """323 Trading, an Amsterdam prop shop whose careers page is one opening.

    A hand-written static page: the `<h1>` is the job title and the paragraphs
    under it are the description. There is no ATS, no feed, and no list -- the
    firm advertises one seat at a time, the way Brummer does.

    **The title is the anchor and its absence is an error**, because a page
    edited by hand is the one most likely to be redesigned without warning, and
    a firm that has filled the seat is a different fact from a parser that has
    stopped working.

    The known weakness is staleness rather than breakage: a static page carries
    no date and says nothing when the seat is filled, so this reader cannot
    tell a live opening from one left up. Every hand-written board shares that;
    what makes it worth having anyway is that Amsterdam is a focus hub with
    thirteen roster firms in it and this is one of them.
    """
    url = "https://323trading.nl/careers.html"
    body = http.get_text(url, timeout=25, retries=2)
    match = _323_TITLE.search(body)
    title = _text(match.group(1)) if match else None
    if not title:
        raise SiteChanged("323trading: careers.html carries no <h1> title")
    return [
        Job(
            ats="site",
            token="323trading",
            job_id=title.casefold().replace(" ", "-")[:80],
            title=title,
            url=url,
            location="Amsterdam, Netherlands",
        )
    ]


# --------------------------------------------------------------------------
# Citadel and Citadel Securities -- the sitemap is the only surface


def _slug_title(slug: str) -> str:
    from .extract import _icims_title as shared  # one definition, see `_text`

    return shared(slug)


# `<loc>` entries under `/careers/details/`, which is the only shape the
# careers sitemap carries. Bounded, like every pattern in this project that
# runs over fetched markup.
_CITADEL_JOB = re.compile(
    r"<loc>\s*(https://[^<\s]{10,300}/careers/details/([a-z0-9][a-z0-9-]{2,120})/?)\s*</loc>",
    re.I,
)


def _citadel_board(token: str, host: str) -> list[Job]:
    """Citadel's openings, read from the sitemap it publishes for crawlers.

    **Every HTML page and the WordPress REST API answer 403; robots.txt and
    the sitemaps answer 200.** That is not a wall to be worked around -- it is
    the site saying which door is the crawler's. `robots.txt` reads `Allow: /`
    with `Crawl-delay: 10` and names two sitemap indexes, and the
    `career-sitemap.xml` inside them is regenerated the same day: 51 postings
    for Citadel and 85 for Citadel Securities, which is the whole board.

    **The slug is the title, and it is lossy in the way iCIMS already is** --
    `c-software-engineer` is *C++ Software Engineer*, and casing is gone.
    `fold` lowercases both sides before any needle runs, so the tagger reads
    these like any other posting; only the card is poorer.

    **`<lastmod>` is deliberately not read as a posting date.** Every entry in
    the file carries the same timestamp to within seconds, so it dates the
    sitemap's regeneration and not the opening -- the `publication.endDate`
    mistake from job-room.ch, one field over.

    Location is left unset rather than mined out of the slug. A few end in
    `-asia` or `-us` and most end in nothing, and the board *gates* on
    geography: `unknown` survives that gate and a wrong city does not.
    """
    body = http.get_text(f"https://{host}/career-sitemap.xml", timeout=25, retries=2)
    if "<loc>" not in body:
        raise SiteChanged(f"{token}: {host}/career-sitemap.xml has no <loc> entries")
    jobs: list[Job] = []
    seen: set[str] = set()
    for url, slug in _CITADEL_JOB.findall(body):
        if slug in seen:
            continue
        seen.add(slug)
        jobs.append(
            Job(ats="site", token=token, job_id=slug, title=_slug_title(slug), url=url)
        )
    if not jobs:
        raise SiteChanged(f"{token}: sitemap carries no /careers/details/ entries")
    return jobs


def citadel() -> list[Job]:
    """Citadel, the hedge fund."""
    return _citadel_board("citadel", "www.citadel.com")


def citadel_securities() -> list[Job]:
    """Citadel Securities, a different employer with its own board.

    Two roster lines, two sitemaps, and the campus pipelines are advertised on
    both. They are kept apart because `domains.py` already learned this one
    expensively: `citadel.com` "verified" itself against Citadel Securities,
    and a firm that shares a founder is still a different careers page.
    """
    return _citadel_board("citadel_securities", "www.citadelsecurities.com")


# --------------------------------------------------------------------------
# DRW


_DRW_LISTINGS = "https://drw.com/work-at-drw/listings"
_NEXT_DATA = re.compile(
    r'<script[^>]{0,200}id="__NEXT_DATA__"[^>]{0,200}>([\s\S]{0,4000000}?)</script>',
    re.I,
)


def drw() -> list[Job]:
    """DRW, from the job array its own listings page ships inside the markup.

    **DRW's stored careers URL was a Cloudinary image**, which is what the
    careers walk settled on and is `discover.py`'s standing example of why no
    regex over the page we did fetch can reach these firms. The board is not an
    ATS at all: `/work-at-drw/listings` is a Next.js page carrying every
    posting in `__NEXT_DATA__` -- 160 of them, with title, id and locations.

    **Only `en` is read.** The payload also holds an `fr` array and all 17 of
    its ids are already in `en`: they are French renderings of the Montreal
    postings, not extra openings. Reading both double-counts an office.

    Locations arrive as a list and are joined the way a Greenhouse board
    already publishes a multi-site posting, because `hub` is multi-valued end
    to end -- "Amsterdam; Chicago; London" is read as three places rather than
    as one unknown.
    """
    body = http.get_text(_DRW_LISTINGS, timeout=30, retries=2)
    match = _NEXT_DATA.search(body)
    if match is None:
        raise SiteChanged("drw: /work-at-drw/listings no longer ships __NEXT_DATA__")
    try:
        listings = json.loads(match.group(1))["props"]["pageProps"]["jobData"]["en"]
    except (KeyError, TypeError, ValueError) as exc:
        raise SiteChanged(f"drw: jobData.en is gone from __NEXT_DATA__ ({exc})") from exc
    jobs: list[Job] = []
    seen: set[str] = set()
    for listing in listings:
        job_id = str(listing.get("id") or "")
        title = _text(listing.get("job_title") or listing.get("title"))
        if not job_id or not title or job_id in seen:
            continue
        seen.add(job_id)
        slug = listing.get("slug")
        jobs.append(
            Job(
                ats="site",
                token="drw",
                job_id=job_id,
                title=title,
                url=f"{_DRW_LISTINGS}/{slug}" if slug else _DRW_LISTINGS,
                location="; ".join(p for p in listing.get("locations") or [] if p)
                or None,
                department="; ".join(
                    c for c in listing.get("career_categories") or [] if c
                )
                or None,
            )
        )
    if not jobs:
        raise SiteChanged("drw: jobData.en is present and empty")
    return jobs


# --------------------------------------------------------------------------
# The D. E. Shaw group


# One card per posting. Split on the id attribute rather than matched whole,
# for the reason `extract.jobvite` gives: a single pattern reaching from the id
# across the nested SVG markup to the title is where a regex over a 900 KB page
# turns quadratic.
_DESHAW_ID = re.compile(r'<div class="job" data-job-id="(\d+)"', re.I)
_DESHAW_TITLE = re.compile(r'class="job-display-name">([\s\S]{0,300}?)</span>', re.I)
_DESHAW_LOCATION = re.compile(r'class="location">([\s\S]{0,200}?)</span>', re.I)
_DESHAW_CATEGORY = re.compile(r'class="category">([\s\S]{0,200}?)</p>', re.I)
_DESHAW_HREF = re.compile(r'href="(/careers/[a-z0-9][a-z0-9-]{2,140})"', re.I)


def deshaw() -> list[Job]:
    """The D. E. Shaw group, whose whole board is one server-rendered page.

    86 postings, each a `<div class="job" data-job-id="...">` carrying the
    title, the office and the group's own category -- more than several ATSes
    give. There is no vendor here to fingerprint and no feed to guess.

    The page is ~900 KB because every card also carries the first sentence of
    its description. That snippet is deliberately not stored: `bodies.py`
    fetches the real page for postings whose verdict it could change, and a
    truncated opening line would satisfy its "has a body" test without carrying
    the evidence.
    """
    body = http.get_text("https://www.deshaw.com/careers", timeout=40, retries=2)
    chunks = _DESHAW_ID.split(body)
    if len(chunks) < 3:
        raise SiteChanged("deshaw: /careers has no data-job-id cards")
    jobs: list[Job] = []
    seen: set[str] = set()
    # `split` on a capturing pattern yields [before, id, chunk, id, chunk, ...].
    for job_id, chunk in zip(chunks[1::2], chunks[2::2]):
        if job_id in seen:
            continue
        seen.add(job_id)
        title = _DESHAW_TITLE.search(chunk)
        if title is None:
            continue
        href = _DESHAW_HREF.search(chunk)
        location = _DESHAW_LOCATION.search(chunk)
        category = _DESHAW_CATEGORY.search(chunk)
        jobs.append(
            Job(
                ats="site",
                token="deshaw",
                job_id=job_id,
                title=_text(title.group(1)) or "",
                url=urllib.parse.urljoin(
                    "https://www.deshaw.com/", href.group(1) if href else "/careers"
                ),
                location=_text(location.group(1)) if location else None,
                department=_text(category.group(1)) if category else None,
            )
        )
    if not jobs:
        raise SiteChanged("deshaw: cards found but none carried a job-display-name")
    return jobs


# --------------------------------------------------------------------------
# Renaissance Technologies


# Each opening is a link carrying its own position key, followed by a plain
# `<div>` holding the office. The department is the `<h2>` above the group.
_RENTEC_GROUP = re.compile(
    r'<h2 class="Subhead_heading[^"]{0,80}">([\s\S]{0,120}?)</h2>', re.I
)
_RENTEC_JOB = re.compile(
    r'href="([^"]{0,200}selectedPosition=([A-Za-z0-9_]{2,60}))"[^>]{0,200}>'
    r"([\s\S]{0,200}?)</a>[\s\S]{0,400}?<div>([\s\S]{0,160}?)</div>",
    re.I,
)


def rentec() -> list[Job]:
    """Renaissance Technologies, whose openings are anchors on one page.

    A dozen postings, all East Setauket or New York, published as
    `Careers.action?jobs=true&selectedPosition={key}` links grouped under a
    heading per department. `selectedPosition` is the id: it is what the firm
    links to, and unlike the anchor text it is not rewritten when a title is
    reworded.
    """
    url = "https://www.rentec.com/Careers.action?jobs=true"
    body = http.get_text(url, timeout=25, retries=2)
    if "selectedPosition" not in body:
        raise SiteChanged("rentec: Careers.action lists no selectedPosition links")
    headings = [(m.end(), _text(m.group(1))) for m in _RENTEC_GROUP.finditer(body)]
    jobs: list[Job] = []
    seen: set[str] = set()
    for match in _RENTEC_JOB.finditer(body):
        href, key, title, place = match.groups()
        if key in seen:
            continue
        seen.add(key)
        name = _text(title)
        if not name:
            continue
        # The department is the last group heading before this link.
        department = next(
            (name_ for end, name_ in reversed(headings) if end < match.start()), None
        )
        jobs.append(
            Job(
                ats="site",
                token="rentec",
                job_id=key,
                title=name,
                url=urllib.parse.urljoin(url, html.unescape(href)),
                location=_text(place),
                department=department,
            )
        )
    if not jobs:
        raise SiteChanged("rentec: selectedPosition links found but none parsed")
    return jobs


# --------------------------------------------------------------------------
# Hong Kong -- three employers whose whole board is a list on their own page.
#
# Both were found by hand after `audit --pipeline` reported Hong Kong at
# 21/51, the worst of the focus hubs. Neither runs an ATS, neither is
# reachable by a name guess, and the hub has no national board to fall back
# on: Hong Kong's statutory portal, the Labour Department's Interactive
# Employment Service, ends its `robots.txt` with `Disallow: /` and names
# `/0/api/*` explicitly. That is the exact inverse of Singapore, whose
# `robots.txt` reads `Disallow:` with a sitemap -- so where Singapore is a
# 95,000-posting sweep, Hong Kong is per-firm work like this.


_PANDTONG_JOB = re.compile(
    r"""onclick="window\.location\s*=\s*'/joblistEn\?name=(\d{1,4})[^']{0,40}'"""
    r"[\s\S]{0,300}?"
    r'<p class="job-title"[^>]{0,200}>([\s\S]{0,160}?)</p>',
    re.I,
)


def pandtong() -> list[Job]:
    """Pandtong Quantitative Research, from its own English careers page.

    A Hong Kong quant shop, and one of only two firms in the hub's unreached
    list that publish openings on their own host rather than serving a page
    with nothing on it. Thirteen of them, applied for by email; there is no
    vendor to fingerprint and no feed to guess.

    **The English page is read rather than the Chinese one, and `name` is why
    that is safe.** `/careers` and `/careersEn` are the same board under two
    renderings and the `name=N` key is shared between them -- `name=1` is
    `Quantitative researcher` and `量化研究员`, `name=4` is `C++ Developer`
    and `C++开发工程师`. Reading the Chinese titles would put them in front of
    a lexicon that is English, Swedish and Danish and would match none of it,
    which is the `sygeplejerske` problem in a script with no word boundaries
    at all. Taking the English rendering is not a filter: the id is the same
    row either way.

    No location is written. Every posting is Hong Kong, but the page does not
    say so, and `unknown` survives the board's geography gate while a guess
    that turns out wrong does not.
    """
    url = "https://pandtong.com/careersEn"
    body = http.get_text(url, timeout=25, retries=2)
    if "job-title" not in body:
        raise SiteChanged("pandtong: careersEn carries no job-title element")
    jobs: list[Job] = []
    seen: set[str] = set()
    for match in _PANDTONG_JOB.finditer(body):
        job_id, title = match.groups()
        name = _text(title)
        if not name or job_id in seen:
            continue
        seen.add(job_id)
        jobs.append(
            Job(
                ats="site",
                token="pandtong",
                job_id=job_id,
                title=name,
                url=f"https://pandtong.com/joblistEn?name={job_id}&lan=En",
                location=None,
                department=None,
            )
        )
    if not jobs:
        raise SiteChanged("pandtong: job-title elements found but none parsed")
    return jobs


# Anatole publishes each opening as a PDF job description under one heading.
# The heading is the anchor; the link text is the title.
_ANATOLE_BLOCK = re.compile(
    r"Current Opportunities([\s\S]{0,4000}?)</div>", re.I
)
_ANATOLE_JOB = re.compile(
    r'href="(/uploads/[^"]{0,200}\.pdf)"[^>]{0,120}>([\s\S]{0,160}?)</a>', re.I
)


def anatole() -> list[Job]:
    """Anatole Investment Management, whose openings are PDF links.

    Two of them, both internships, which is worth stating because the board
    will rank them low and should: this user has already graduated. They are
    read anyway for the same reason nothing else here is filtered at ingest --
    principle 4 -- and because the *anchor* is what this reader is really
    buying. When Anatole advertises an analyst seat it will appear under the
    same heading and arrive unasked.

    The PDF itself is never fetched. The link text is the title, and the
    filename repeats it; there is no description to gain and a PDF reader is
    a dependency this project does not have.
    """
    url = "https://anatole-inv.com/careers"
    body = http.get_text(url, timeout=25, retries=2)
    block = _ANATOLE_BLOCK.search(body)
    if block is None:
        raise SiteChanged("anatole: careers page has no Current Opportunities block")
    jobs: list[Job] = []
    seen: set[str] = set()
    for match in _ANATOLE_JOB.finditer(block.group(1)):
        href, title = match.groups()
        name = _text(title)
        if not name or href in seen:
            continue
        seen.add(href)
        jobs.append(
            Job(
                ats="site",
                token="anatole",
                job_id=href.rsplit("/", 1)[-1].removesuffix(".pdf"),
                title=name,
                url=urllib.parse.urljoin(url, href),
                location=None,
                department=None,
            )
        )
    if not jobs:
        raise SiteChanged("anatole: Current Opportunities block lists no PDF link")
    return jobs


# --------------------------------------------------------------------------
# The Hong Kong Monetary Authority
#
# The vacancies table: one row per opening, the title in an anchor whose href
# carries the recruitment reference, and the employer's own stated closing date
# in the cell beside it.
_HKMA_ROW = re.compile(
    r'<td[^>]{0,120}>\s*<a href="([^"]{0,200}/recruit-([0-9a-z-]{4,40})/)"[^>]{0,120}>'
    r"([\s\S]{0,200}?)</a>\s*</td>\s*<td[^>]{0,120}>([\s\S]{0,80}?)</td>",
    re.I,
)
_HKMA_DATE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})$")
_HKMA_MONTHS = {
    m: i
    for i, m in enumerate(
        "jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1
    )
}


def _hkma_deadline(cell: str) -> str | None:
    """`3 October 2026` -> `2026-10-03`, and anything else -> None.

    The table prints `-` where a posting has no closing date, and that is the
    majority of the reason this parses strictly rather than reaching for a
    date library. A deadline the board cannot trust is worse than none: it
    sorts an approaching date above everything else.
    """
    match = _HKMA_DATE.match((_text(cell) or "").strip())
    if match is None:
        return None
    day, month, year = match.groups()
    number = _HKMA_MONTHS.get(month[:3].lower())
    if number is None:
        return None
    return f"{year}-{number:02d}-{int(day):02d}"


def hkma() -> list[Job]:
    """The Hong Kong Monetary Authority, from its own vacancies table.

    **In no register, which is why it is seeded rather than discovered.** The
    HKMA is Hong Kong's central bank and a genuine quant employer -- it runs
    the Exchange Fund -- but it is a statutory body rather than an SFC
    licensed corporation, so `sfc_hk` cannot see it and nor can anything else
    in `registries/`. The same is true of HKEX beside it.

    It publishes a small HTML table, one row per opening, and the second
    column is headed *Closing Date(s)* and holds the employer's own stated
    date. That is the field JobStream sets and almost nothing else does, so it
    is written -- parsed strictly, because half the rows print `-` instead and
    a guessed deadline pins the wrong card to the top of the board.
    """
    url = "https://www.hkma.gov.hk/eng/about-us/join-us/current-vacancies/"
    body = http.get_text(url, timeout=25, retries=2)
    if "current-vacancies/recruit-" not in body:
        raise SiteChanged("hkma: vacancies page lists no recruit- link")
    jobs: list[Job] = []
    seen: set[str] = set()
    for match in _HKMA_ROW.finditer(body):
        href, reference, title, closing = match.groups()
        name = _text(title)
        if not name or reference in seen:
            continue
        seen.add(reference)
        jobs.append(
            Job(
                ats="site",
                token="hkma",
                job_id=reference,
                title=name,
                url=urllib.parse.urljoin(url, href),
                # Written rather than left None: every seat here is in Hong
                # Kong, the authority has one office, and `_HUBS` reads the
                # words. Unlike HKEX's site codes there is nothing to decode.
                location="Hong Kong",
                department=None,
                deadline=_hkma_deadline(closing),
            )
        )
    if not jobs:
        raise SiteChanged("hkma: recruit- links found but no table row parsed")
    return jobs


# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Site:
    """One hand-written reader, and the domain its postings belong to.

    `domain` is what `extract.run` files the postings under, so it has to be
    the firm's real domain -- that is the join `audit --pipeline`, the board
    and `coverage` all use to answer "does this firm produce postings".
    """

    token: str
    domain: str
    # The name `roster.csv` uses. `register` writes it into `domain_lookups`,
    # so the roster's own spelling resolves to the domain a human verified --
    # otherwise `audit --pipeline` credits the postings to nobody. "Nordea"
    # was resolving to `nordeamarkets.com` on a fuzzy match while its 112
    # postings were being filed under `nordea.com`.
    label: str
    # A hand-written reader, or None when `ats` names an extractor that already
    # exists. The second case is for a firm whose *marketing site* blocks us
    # while its board does not: `nasdaq.com` times out on every request, and
    # `nasdaq.wd1.myworkdayjobs.com/Global_External_Site` answers with 183
    # postings. Nothing needs writing there -- only a fingerprint the careers
    # walk could never reach, recorded by hand.
    read: Callable[[], list[Job]] | None = None
    ats: str = "site"


SITES: tuple[Site, ...] = (
    Site("nordea", "nordea.com", "Nordea", nordea),
    Site("ap4", "ap4.se", "AP4", ap4),
    Site("ap7", "ap7.se", "AP7", ap7),
    Site("brummer", "brummer.se", "Brummer & Partners", brummer),
    Site("captor", "captor.se", "Captor", captor),
    Site("norron", "norron.com", "Norron", norron),
    # No reader: Workday already reads this board. Only the *fingerprint* was
    # missing, because `nasdaq.com` never answers us and the careers walk
    # starts there. `curl` with a browser user agent reaches it, which is how
    # the site id was read off the page -- `Global_External_Site`, which no
    # guess would have produced.
    Site(
        "nasdaq|wd1|Global_External_Site",
        "nasdaq.com",
        "Nasdaq Stockholm",
        None,
        ats="workday",
    ),
    # ---- the marquee firms, read from their own sites ---------------------
    Site("citadel", "citadel.com", "Citadel", citadel),
    Site(
        "citadel_securities",
        "citadelsecurities.com",
        "Citadel Securities",
        citadel_securities,
    ),
    Site("drw", "drw.com", "DRW", drw),
    Site("deshaw", "deshaw.com", "DE Shaw", deshaw),
    Site("rentec", "rentec.com", "Renaissance Technologies", rentec),
    # ---- boards on an ATS we already read, that no walk could reach --------
    #
    # Every one of these was found by hand, and each was hidden by a different
    # thing the careers walk cannot do. Two Sigma fronts an Avature portal on
    # its own hostname; Bridgewater proxies its Greenhouse board through
    # `/jobboard` on its own domain and names Greenhouse nowhere else; Northern
    # Trust's `careers.` host *redirects* to Workday, so nothing is left in the
    # markup to fingerprint; Wolverine's board is a hop past `/careers` on
    # `/open-positions`; Five Rings, Headlands, Garda, Acadian and Teza all
    # spell their token in a way no name guess produces --
    # `headlandstechnologiesllc` from "Headlands Technologies", `gardacp` from
    # "Garda Capital Partners".
    #
    # Six of the nine also had the **wrong domain** in `domain_lookups`, which
    # is why they are `Site` rows rather than `discover` results: `twosigma.cn`
    # for Two Sigma, `bwasc.com` for Bridgewater, `acadian.com` for Acadian
    # (which is Acadian *Ambulance*, and its ADP board was recorded against the
    # asset manager), `headlands.com`, `gardacp.dk` and `teza.com`. `register`
    # writes `domain_lookups` too, so the roster's own spelling resolves to the
    # domain a human verified.
    Site("careers.twosigma.com", "twosigma.com", "Two Sigma", None, ats="avature"),
    Site("bridgewater89", "bridgewater.com", "Bridgewater Associates", None, ats="greenhouse"),
    Site("ntrs|wd1|northerntrust", "northerntrust.com", "Northern Trust", None, ats="workday"),
    Site("wolve", "wolve.com", "Wolverine", None, ats="pinpoint"),
    Site("fiveringsllc", "fiverings.com", "Five Rings", None, ats="greenhouse"),
    Site(
        "headlandstechnologiesllc",
        "headlandstech.com",
        "Headlands Technologies",
        None,
        ats="greenhouse",
    ),
    Site("gardacp", "gardacp.com", "Garda Capital", None, ats="greenhouse"),
    Site(
        "acadianassetmanagementllc",
        "acadian-asset.com",
        "Acadian Asset Management",
        None,
        ats="greenhouse",
    ),
    Site("teza-technologies", "teza.com", "Teza Technologies", None, ats="ashby"),
    Site("magnetar", "magnetar.com", "Magnetar Capital", None, ats="greenhouse"),
    # Amsterdam. Robeco's board is one hop past the careers page the walk
    # settled on -- `/careers` links to `/careers/job-openings`, and only the
    # second one carries the Workday host. VivCourt is here for the domain
    # rather than the board: the roster says "Vivienne", `domains` resolved it
    # to `viviennecourt.com`, and the firm publishes on `vivcourt.com`.
    Site("robeco|wd3|robecoexternalcareers", "robeco.com", "Robeco", None, ats="workday"),
    Site("vivcourt", "vivcourt.com", "Vivienne", None, ats="greenhouse"),
    Site("323trading", "323trading.nl", "323 Trading", trading_323),
    # ---- Hong Kong --------------------------------------------------------
    #
    # Capula is here for the **domain**, and it is the `acadian.com` mistake
    # exactly: `domains` resolved "Capula Investment Management" to
    # `capula.com`, which is a Staffordshire *engineering* contractor working
    # on nuclear and power-generation sites, and that firm has a live careers
    # page. A wrong domain here is not an empty feed, it is somebody else's
    # feed. The hedge fund is `capulaglobal.com`, whose careers page names
    # `capula-investment-management-ltd.workable.com` -- a board the Workable
    # extractor already reads, so no reader is needed.
    Site(
        "capula-investment-management-ltd",
        "capulaglobal.com",
        "Capula Investment Management",
        None,
        ats="workable",
    ),
    Site("pandtong", "pandtong.com", "Pandtong Quantitative Research", pandtong),
    Site("anatole", "anatole-inv.com", "Anatole Investment Management", anatole),
    # HKEX and the HKMA are in **no register this project reads**, and that is
    # the structural point rather than an oversight: `sfc_hk` enumerates
    # licensed *corporations*, and an exchange controller and a central bank
    # are neither. Both are real Hong Kong markets employers and between them
    # they are worth more postings than the hub's entire hedge-fund long tail.
    #
    # HKEX needs no reader -- it runs Workday. What hid it is that its careers
    # page is on `hkexgroup.com` while the firm's site is `hkex.com.hk`, so a
    # walk that starts at the domain never reaches the hop that names the
    # board. `_HK_SITE` in `tagging.py` is the other half: HKEX writes the
    # office rather than the city, `HK-TWO ES 11/F`, and without it all 164
    # postings read as `other` and the board gates them.
    Site(
        "hkex|wd3|HKEXCareerPage",
        "hkexgroup.com",
        "Hong Kong Exchanges and Clearing",
        None,
        ats="workday",
    ),
    Site("hkma", "hkma.gov.hk", "Hong Kong Monetary Authority", hkma),
)

BY_TOKEN = {site.token: site for site in SITES}


def read(token: str) -> list[Job]:
    """`extract.EXTRACTORS['site']` -- dispatch to the named firm's reader."""
    site = BY_TOKEN.get(token)
    if site is None or site.read is None:
        raise ValueError(f"no site reader registered for {token!r}")
    return site.read()


def register(connection: sqlite3.Connection) -> int:
    """Give every site an `ats_resolution` row so Layer 3 polls it.

    Written as tier A with `ats='site'`, which keeps these out of the way of
    every other sweep: `ats.targets` only visits untiered domains and
    `ats.reprobe_targets` only visits tier B and tokenless tier A, so neither
    can overwrite a row here. Re-registering is idempotent.
    """
    from . import ats as ats_module

    from . import domains as domains_module

    connection.executescript(ats_module.SCHEMA)
    connection.executescript(domains_module.SCHEMA)
    timestamp = db.now()
    with connection:
        # The domain a human verified, under the roster's own name for the
        # firm. Without this `discover._domain_for` falls back to a fuzzy name
        # match -- "Nordea" found `nordeamarkets.com`, a different entity --
        # and `audit --pipeline` then looks for the postings under a domain
        # nothing writes to. `method='site'` is not "weak", so it is preferred.
        connection.executemany(
            "INSERT OR REPLACE INTO domain_lookups"
            " (query, domain, method, evidence, checked_at)"
            " VALUES (?, ?, 'site', ?, ?)",
            [
                (site.label, site.domain, f"hand-written reader in sites.py", timestamp)
                for site in SITES
            ],
        )
        connection.executemany(
            "INSERT OR REPLACE INTO ats_resolution"
            " (domain, careers_url, ats, token, tier, evidence, checked_at)"
            " VALUES (?, ?, ?, ?, 'A', ?, ?)",
            [
                (
                    site.domain,
                    f"https://{site.domain}/",
                    site.ats,
                    site.token,
                    (
                        f"hand-written reader in sites.py ({site.label})"
                        if site.read
                        else f"hand-verified board in sites.py ({site.label})"
                    ),
                    timestamp,
                )
                for site in SITES
            ],
        )
    return len(SITES)
