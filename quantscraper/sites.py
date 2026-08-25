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
