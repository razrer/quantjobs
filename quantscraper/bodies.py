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

**And there were four more sources with the same shape, which is the largest
single thing wrong with the tagger.** Measured over the whole live corpus: a
posting with a body stays `relevance: unknown` **1.0%** of the time and one
without a body **9.3%** -- so the classifier's biggest bucket is a data gap
rather than a lexicon gap. On the board itself, **2,298 of the 3,635 unread
cards (63%) had no body at all**, and their sources were SuccessFactors 991,
Oracle 430, Workday 282 and iCIMS 230. Only Workday had a fetcher.

Every one of the four publishes the description on a per-posting resource:
SuccessFactors as microdata on its detail page, iCIMS as a schema.org island
inside the frame it already serves the list from, Oracle through
`recruitingCEJobRequisitionDetails`, SmartRecruiters through the same public
API its list comes from. Three of them publish the **place** there too, which
matters as much: 747 of the board's 941 placeless cards simply had NULL in that
column, so they passed the geography gate -- correctly -- and could be ranked by
nothing.

**A widened word list cannot substitute and the corpus says so twice.** The
non-English titles in that bucket are a European truck-dealership network's
mechanics and apprentices, and the German trade vocabulary was dry-run against
them: `-installateur` reaches 3,517 live postings and **one** board card,
because the rest are already rejected on evidence somewhere else. The bodies
are what is missing, not the needles.
"""

from __future__ import annotations

import html
import json
import queue
import re
import sqlite3
import threading
import urllib.error
import urllib.parse
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

from . import parsing, db, http, iesjobs, jobbsafari, tagging
from .iesjobs import ORIGIN


class Fetched(NamedTuple):
    """What a detail page yielded. Any part may be missing.

    `location` exists because Workday's detail endpoint answers two questions
    at once and the second one was being thrown away -- see `workday_body`. A
    fetcher with nothing to add there returns None and nothing is written.

    `employer` is the third and it exists for one source. Hong Kong's statutory
    portal publishes the employer's name on the **job card** and nowhere on the
    list, so a board fed by it would otherwise show 14,287 postings from
    nobody -- the JobStream failure, where 1,737 cards named no advertiser.
    Every other fetcher returns None here, because everywhere else the domain
    the board was reached from *is* the employer and a second name for it would
    be a second identity to keep in step.
    """

    description: str | None
    location: str | None
    employer: str | None = None


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


def _clean(markup: str | None) -> str | None:
    """Plain text out of a fetched fragment, capped. See `parsing.text`."""
    return parsing.text(markup, limit=_MAX_BODY)


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


# SuccessFactors RMK renders the description server-side into a microdata span
# on the detail page. There is no JSON island and no API: the span is the
# whole surface, and it closes at the `</div>` that ends the `job` block.
# The detail page is schema.org **microdata**, so both fields are read by the
# attribute the standard names rather than by the markup the tenant wrapped it
# in. That is the whole reason these are selectors: the description pattern
# had to assert the `</span></div>` closing the block, and the location
# pattern had to bound its own search to 600 characters, because a `.{0,600}?`
# over an unbounded page is the shape that stalled this project twice. A
# parser has neither problem -- the block is a node, and what is inside it is
# inside it.
_SF_DESCRIPTION = '[itemprop="description"]'
# Tenants disagree about which address fields they fill -- AkzoNobel and
# Scania write a single `streetAddress` ("Mora, SE, 792 50"), DekaBank and
# NordLB write `addressLocality` + `addressRegion` + `addressCountry` -- so
# the block is found first and the fields are read out of it in a fixed order.
_SF_LOCATION = '[itemprop="jobLocation"]'
_SF_ADDRESS = ("streetAddress", "addressLocality", "addressRegion", "addressCountry")


def _sf_place(page) -> str | None:
    """The posting's place from the SuccessFactors microdata, or None.

    Seven boards -- Scania, DekaBank, NordLB, BayernLB and three others --
    publish no location on the list page at all, so 314 of their postings
    reach the board with `hub: unknown`: past the geography gate, which is
    right, and unrankable, which is not. The detail page has known it all
    along.
    """
    block = page.select_one(_SF_LOCATION)
    if block is None:
        return None
    fields = {
        node["itemprop"]: node.get("content", "")
        for node in block.select("[itemprop][content]")
        if node["itemprop"] in _SF_ADDRESS
    }
    if street := (fields.get("streetAddress") or "").strip():
        return street
    parts = [
        value.strip()
        for key in _SF_ADDRESS[1:]
        if (value := fields.get(key, "")).strip()
    ]
    return ", ".join(parts) or None


def successfactors_body(row) -> Fetched:
    """The description for one SuccessFactors RMK posting.

    **991 of the board's 2,298 body-less unread cards are this source**, more
    than any other, and `extract.successfactors` never had a chance at them:
    its list page carries a title, a place and a department and no prose at
    all. The postings therefore arrive as a six-word title, which is precisely
    the shape `lexicon.judge` refuses to reject -- so they land in `unknown`
    and stay there. Measured across the corpus, a posting with a body stays
    `unknown` 1.0% of the time and one without 9.3%, which is what makes this
    a classifier fix rather than a cosmetic one.

    Addressed by `jobs.url` rather than by `token` and `job_id`, for the
    Jobbsafari reason: the detail path carries a title slug the id cannot
    reconstruct (`/job/Sassenheim-Allround-Service-Technician-.../1228943501/`).
    """
    url = row["url"]
    if not url or "/job/" not in url:
        return Fetched(None, None)
    try:
        page = http.get_text(url, timeout=25, retries=1)
    except Exception:  # noqa: BLE001 -- a 404, a timeout, a hostile page
        return Fetched(None, None)
    tree = parsing.soup(page)
    found = tree.select_one(_SF_DESCRIPTION)
    return Fetched(
        _clean(found.decode_contents()) if found else None, _sf_place(tree)
    )


# iCIMS' classic portal serves the job page as a frame and the frame carries a
# schema.org `JobPosting` island. `_ICIMS_LD` finds the island; the shape of
# what is inside it is JSON, so nothing else here is a pattern.
_ICIMS_LD = 'script[type="application/ld+json"]'


def _ld_job_posting(page: str) -> dict | None:
    """The `JobPosting` object out of a page's JSON-LD, or None.

    A page may carry several islands -- a breadcrumb, an organisation -- so
    every one is parsed and the first `JobPosting` wins. A malformed island is
    skipped rather than raised on: the others may still be good, and one
    vendor's stray comma must not cost the description.
    """
    for island in parsing.soup(page).select(_ICIMS_LD):
        try:
            payload = json.loads(island.string or island.get_text())
        except ValueError:
            continue
        for entry in payload if isinstance(payload, list) else [payload]:
            if isinstance(entry, dict) and entry.get("@type") == "JobPosting":
                return entry
    return None


def _ld_place(posting: dict) -> str | None:
    """`jobLocation` as one `; `-joined string, in published order.

    schema.org nests the place two deep and permits a list, so a posting open
    in three offices arrives as three `Place` objects. Read the same way
    `_workday_places` reads `additionalLocations`, and joined with the
    separator the hub reader already treats as a list.
    """
    places: list[str] = []
    where = posting.get("jobLocation")
    for entry in where if isinstance(where, list) else [where]:
        address = (entry or {}).get("address") if isinstance(entry, dict) else None
        if not isinstance(address, dict):
            continue
        parts = [
            str(address.get(field)).strip()
            for field in ("addressLocality", "addressRegion", "addressCountry")
            if isinstance(address.get(field), str) and address.get(field).strip()
        ]
        if parts and (name := ", ".join(parts)) not in places:
            places.append(name)
    return "; ".join(places) or None


def icims_body(row) -> Fetched:
    """The description *and the place* for one classic-portal iCIMS posting.

    **This source publishes nothing but a title and a link**, and both are
    thinner than they look: `extract._icims_title` reconstructs the title from
    the URL slug, so casing is gone and `c++` survives as `c`, and there is no
    location at all -- so 1,824 postings reach the board with `hub: unknown`,
    which the geography gate lets through and nothing can rank.

    The frame the portal renders for a job (`?in_iframe=1`, the same parameter
    `extract._icims_page` already passes for the list) carries a schema.org
    `JobPosting` island with the description and the address. So the location
    is written too, and the guard in `run` had to learn that **a posting with
    no location at all is the purest placeholder there is** -- `_UNRESOLVED`
    was written against Workday's `N Locations` and protects a *stated* place
    from being overwritten, which is a thing an absent one does not have.
    """
    url = row["url"]
    if not url or "/jobs/" not in url:
        return Fetched(None, None)
    frame = url + ("&" if "?" in url else "?") + "in_iframe=1"
    try:
        page = http.get_text(frame, timeout=25, retries=1)
    except Exception:  # noqa: BLE001 -- a 404, a timeout, a WAF challenge
        return Fetched(None, None)
    posting = _ld_job_posting(page)
    if posting is None:
        return Fetched(None, None)
    return Fetched(_clean(posting.get("description")), _ld_place(posting))


# Oracle splits one posting's prose across three fields and a tenant may leave
# any of them empty -- Corsair writes everything into the first, Kotak spreads
# it. Joined rather than picked, because the qualifications block is where the
# years figure and the degree requirement usually live.
_ORACLE_PROSE = (
    "ExternalDescriptionStr",
    "ExternalResponsibilitiesStr",
    "ExternalQualificationsStr",
)


def oracle_hcm_body(row) -> Fetched:
    """The description and the primary location for one Oracle Fusion posting.

    `token` is `podhost|siteNumber`, the same both-halves shape
    `extract.oracle_hcm` needs, and `job_id` is the requisition id. The detail
    resource is `recruitingCEJobRequisitionDetails` with an `ById` finder --
    **the site number is required there as well as the id**, for the reason
    `ats.py` records about the token: `CX_1001` is Oracle's default and most
    tenants keep it, so an id alone is ambiguous across sites on one pod.

    The rendered page is not an option: it is a 6.5 KB shell that names one
    bundle and fetches this same resource itself.
    """
    token, job_id = row["token"], row["job_id"]
    host, _, site = str(token).partition("|")
    if not host or not site or not job_id:
        return Fetched(None, None)
    finder = urllib.parse.quote(
        f'ById;Id="{job_id}",siteNumber={site}', safe=';,="'
    )
    url = (
        f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
        f"?expand=all&onlyData=true&finder={finder}"
    )
    try:
        payload = json.loads(http.get_text(url, timeout=25, retries=1))
    except Exception:  # noqa: BLE001 -- a 404, a timeout, a hostile tenant
        return Fetched(None, None)
    # **The shape check is not optional and not decoration.** This runs inside
    # a twelve-thread `pool.map`, and an `AttributeError` raised here does not
    # cost one posting -- it ends the loop, discards the batch of up to a
    # hundred rows already fetched and not yet written, and skips the trailing
    # `_write`. Batching exists precisely so tens of minutes of network work
    # survives one bad answer, and a `.get()` on something that is not a dict
    # is the way to undo that.
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return Fetched(None, None)
    detail = items[0]
    prose = " ".join(
        str(detail.get(field)) for field in _ORACLE_PROSE if detail.get(field)
    )
    where = detail.get("PrimaryLocation")
    return Fetched(
        _clean(prose),
        where.strip() if isinstance(where, str) and where.strip() else None,
    )


# SmartRecruiters splits one advertisement into named sections and a tenant
# fills whichever it likes. `videos` is a section too and its `text` is the
# string "None" on the boards here, so the wanted ones are named rather than
# the unwanted ones excluded.
_SR_SECTIONS = ("jobDescription", "qualifications", "additionalInformation")


def smartrecruiters_body(row) -> Fetched:
    """The description for one SmartRecruiters posting.

    **Zero of 1,757 live rows held a body**, because the list endpoint
    (`/postings?limit=100`) returns the card and not the advertisement. The
    per-posting resource on the same public API returns `jobAd.sections`, and
    it is the same host, so it costs nothing new in politeness terms.

    `companyDescription` is deliberately not read: it is the firm describing
    itself, which is the one kind of text `lexicon.judge` is built to keep out
    of a decision about the role.
    """
    token, job_id = row["token"], row["job_id"]
    if not token or not job_id:
        return Fetched(None, None)
    url = f"https://api.smartrecruiters.com/v1/companies/{token}/postings/{job_id}"
    try:
        payload = json.loads(http.get_text(url, timeout=25, retries=1))
    except Exception:  # noqa: BLE001 -- a 404, a timeout, a hostile payload
        return Fetched(None, None)
    # Every level is shape-checked, for the reason `oracle_hcm_body` records:
    # an `AttributeError` inside the pool ends the whole pass, not the posting.
    ad = payload.get("jobAd") if isinstance(payload, dict) else None
    sections = ad.get("sections") if isinstance(ad, dict) else None
    if not isinstance(sections, dict):
        return Fetched(None, None)
    prose = " ".join(
        text
        for name in _SR_SECTIONS
        if isinstance(block := sections.get(name), dict)
        and isinstance(text := block.get("text"), str)
    )
    return Fetched(_clean(prose), None)


# The Hong Kong card's own marker: the element carrying both `id="ordNo"` and
# the order number the card is *for*. Written to tolerate either attribute
# order, because the alternative fails **closed** -- an attribute swap would
# silently return nothing for every posting rather than raising, and the only
# thing that would say so is a `0%` row in `bodies.coverage`.
_IES_CARD = re.compile(
    r'<[^>]*\bid="ordNo"[^>]*\bdata-ordno="([^"]*)"'
    r'|<[^>]*\bdata-ordno="([^"]*)"[^>]*\bid="ordNo"'
)

# The card's fields, each on an `id` the portal has given it. `jobRemark` is
# the responsibilities and `eduRemark` the requirements; both describe the job.
#
# **`empTerm`, `openupRemark` and `propRemark` are deliberately left out.**
# They are the contract, the application instructions and a free-text note --
# hours, leave days, a recruiter's mailbox -- and none of them is about what
# the work is. That is the same line `smartrecruiters_body` draws at
# `companyDescription`: the tagger reads this string for what the role *is*,
# and prose about anything else is the boilerplate every body-matched rule in
# this project has been caught by.
_IES_FIELDS = ("jobRemark", "eduRemark")


def _ies_field(page: str, name: str) -> str | None:
    match = re.search(rf'id="{name}"[^>]*>([\s\S]*?)</span>', page)
    return _clean(match.group(1)) if match else None


# Where a fresh card token is minted from an order number. The portal's search
# is POST-only -- `criteria.searchField` is ignored on a GET, which returns the
# whole board and looks like a match until you read the count.
_IES_SEARCH = ORIGIN + "/0/en/jobseeker/jobsearch/simple/"

# The card link on that one-result page. Its token is minted by *this* request,
# which is the whole point of making it.
#
# **It is a `data-` attribute, not an `href`, and scanning for the href finds
# nothing.** The search answers in the *quickview* layout, where the row is a
# `<div>` carrying `data-jobcard="/0/en/jobseeker/jobCard/?order=..."` and the
# only `<a>` on it is the clip button. That is `CLAUDE.md`'s Bridgewater
# lesson in a second place -- read the `data-*` attributes when href scanning
# turns up nothing -- and it cost an hour here because the failure is silent:
# the search succeeds, the page contains the posting, and the token extraction
# quietly returns None.
_IES_FRESH = re.compile(
    r'(?:href|data-jobcard)="(/0/[a-z]{2}/jobseeker/jobCard/\?order=[^"]+)"'
)


def _ies_card_url(job_id: str) -> str | None:
    """A card URL for `job_id` that is valid right now.

    **The stored one is not, and that was measured the expensive way.** The
    portal mints `?order=<base64>` per render and the token **expires with
    time** -- verified by isolating the two candidate causes: a token seconds
    old works in a brand-new process with a fresh cookie jar, so it is not
    session-bound, while tokens a couple of hours old return the vacancy-search
    page. A stale one answers **HTTP 200** with 53 KB of valid HTML and no card
    in it, so nothing about the response says "expired" except the absence of
    the marker.

    The first version of this fetcher stored the token and used it, on the
    strength of one twenty-minute-old token still working. That is the
    `"this vendor is closed"` mistake in a new shape: a durability claim from a
    single short observation. It filled 968 rows and then silently filled
    nothing, while still spending one request per row.

    So the token is re-minted per posting: one POST to search by order number,
    which returns a one-result page carrying a link the portal has just issued.
    It costs a second request per body and it is the only form that works.
    """
    try:
        body = http.post_form(
            _IES_SEARCH, {"criteria.searchField": job_id}, timeout=45, retries=1
        )
    except Exception:  # noqa: BLE001 -- a timeout, a redirect, a hostile payload
        return None
    page = body.decode("utf-8", "replace")
    # The search matched exactly this posting, or it matched something else and
    # is not ours to read. `data-ordno` is the portal's own answer to which.
    if job_id not in re.findall(r'data-ordno="([^"]*)"', page):
        return None
    match = _IES_FRESH.search(page)
    return urllib.parse.urljoin(ORIGIN, html.unescape(match.group(1))) if match else None


def iesjobs_body(row) -> Fetched:
    """The employer and the description for one Hong Kong job card.

    The list this posting came from carries a title, a district and a date and
    **no employer and no prose at all** -- that is the whole reason this
    fetcher exists, and it is why `iesjobs` writes a NULL employer rather than
    inventing one.

    **Two requests, because the card is addressed by a perishable token.** See
    `_ies_card_url`: the stored one is dead within a couple of hours and says
    so only by omitting the card. This mints a fresh one and then reads it.

    **The marker is also the identity check.** `data-ordno` is the order number
    the card is *for*, so a search that matched the wrong posting is caught
    here rather than writing one firm's description onto another's row. That is
    the `palmersquare.com` failure, and it costs one comparison.

    The card also carries `indsDesc`, the portal's own industry -- and it is
    not read, because `iesjobs` already writes that column for every posting
    from the job-type slice it was walked in. A category held for the few
    hundred postings that reached this queue would be worse than none.
    """
    job_id = str(row["job_id"] or "").strip()
    if not job_id:
        return Fetched(None, None)
    url = _ies_card_url(job_id)
    if not url:
        return Fetched(None, None)
    return _ies_read_card(url, job_id)


def _ies_read_card(url: str, job_id: str) -> Fetched:
    """Read one Hong Kong job card, whoever minted its token.

    Split out because there are now two ways to reach a card and only one way
    to read it: `iesjobs_body` searches for a token one posting at a time, and
    `_iesjobs_pass` harvests them twenty to a page. **The identity check has to
    live with the reading rather than with the minting** -- it is the guard
    against writing one firm's description onto another's row, and a second
    copy of it would be free to drift from this one.
    """
    try:
        page = http.get_text(url, timeout=45, retries=1)
    except Exception:  # noqa: BLE001 -- a timeout, a redirect, a hostile payload
        return Fetched(None, None)
    marker = _IES_CARD.search(page)
    found = (marker.group(1) or marker.group(2) or "").strip() if marker else None
    if not found or found != job_id:
        # An expired token answers HTTP 200 with the vacancy-search page and no
        # card in it, so this is the expiry check too -- and it fails *closed*:
        # nothing is written and the posting stays in the queue. That is what
        # makes a harvested token cheap to attempt.
        return Fetched(None, None)
    prose = " ".join(
        text for name in _IES_FIELDS if (text := _ies_field(page, name))
    )
    employer = _ies_field(page, "empName")
    # `-` is what the portal prints in a field the employer left blank, and it
    # is a name for nobody.
    if employer in ("", "-"):
        employer = None
    return Fetched(_clean(prose), None, employer)


# How many pages a slice may be walked before its own postings have justified
# it. See `_iesjobs_pass`: harvesting pays while the pages spent stay below the
# postings found, and no slice can show a posting until its first page has been
# fetched -- so without a head start the rule refuses every slice on page one.
_IES_HARVEST_GRACE = 10


def _iesjobs_pass(
    rows: list[sqlite3.Row], stats: dict[str, int] | None = None
) -> Iterator[tuple[sqlite3.Row, Fetched]]:
    """Hong Kong, minting card tokens twenty to a page rather than one at a time.

    **This is the most expensive queue in the pipeline and the reason is
    arithmetic, not code.** `www2.jobs.gov.hk` runs at four seconds a request
    (`http.HOST_INTERVAL_S`) -- the whole of what this project offers in
    exchange for reading a board whose `robots.txt` says no -- and
    `iesjobs_body` spends *two* requests on every posting: a POST to search for
    the order number, because the card's `?order=` token expires, then a GET for
    the card. Eight seconds a posting, single file, while the other eleven
    threads of `run`'s pool wait on nothing. Measured on a live queue of 864
    postings: **115 minutes, about three quarters of a `daily --full`.**

    **The rate is not the lever and must not be. The request count is.** The
    portal's own list prints a freshly minted card link beside every row it
    renders, twenty to a page (`iesjobs.card_links`), so a slice can be walked
    for tokens at one request per twenty postings instead of one per posting.
    The search cannot be batched: a space-separated list of order numbers
    matches nothing, a comma-separated one matches nothing, and so does a
    prefix -- all three measured against the live portal.

    **Tokens are spent as they are minted.** A page's cards are fetched before
    the next page is asked for, so nothing here is more than about a minute old
    -- well inside the window the `iesjobs` docstring proved, where a
    seconds-old token works and a couple of hours does not. Harvesting the whole
    board first and reading it afterwards would rebuild the exact bug that cost
    a day.

    **Harvesting is not always cheaper, so the pass decides per slice.** For a
    slice holding W wanted postings, searching costs 2W while paging costs P
    pages plus W cards, so paging wins exactly when P < W -- and that turns on
    how thinly the wanted postings are spread, which is not known in advance.
    Measured over the live queue: `Others` wants 331 postings and reaches all of
    them within 80 pages (411 requests against 662), while
    `Management / Administration` wants 23 spread over 41 pages and would cost
    64 against 46. So the loop keeps paging only while the pages it has spent
    stay below the postings it has found, and hands the remainder back to the
    search. Whole-queue effect: **1,085 requests against 1,728, 72 minutes
    against 115.**

    Anything a slice does not yield -- a posting withdrawn since the walk, a
    category the portal has renamed, a page that failed -- falls through to
    `iesjobs_body` unchanged. So the worst case is the behaviour this replaced
    plus the pages it spent, and the best case is a little over half of it.
    """
    # **The two routes are counted, because falling back to the slow one is
    # silent.** If the portal reorders its list markup, `card_links` returns an
    # empty page, every slice is abandoned on its first page and every posting
    # goes to the search -- which is the behaviour this replaced, at the cost of
    # the pages it spent, and nothing else about the run would look different.
    # `cli._bodies` prints the split, so a collapse reads as a number rather
    # than as "Hong Kong is slow again".
    if stats is None:
        stats = {}
    stats.setdefault("harvested", 0)
    stats.setdefault("searched", 0)

    outstanding: dict[str | None, dict[str, sqlite3.Row]] = {}
    for row in rows:
        job_id = str(row["job_id"] or "").strip()
        if job_id:
            outstanding.setdefault(row["category"], {})[job_id] = row

    slices = {name: ident for ident, name in iesjobs.JOB_TYPES}
    for category, pending in outstanding.items():
        jobtype = slices.get(category or "")
        if jobtype is None:
            # No slice to walk -- an uncategorised posting, or a facet the
            # portal has renamed since the walk. The search still finds it.
            continue
        pages = found = 0
        while pending and pages <= found + _IES_HARVEST_GRACE:
            pages += 1
            try:
                links = iesjobs.card_links(pages, jobtype=jobtype)
            except Exception:  # noqa: BLE001 -- fall back rather than lose the slice
                break
            if not links:
                # The end of the slice. Stop on an *empty* page and never a
                # short one -- the rule the walk itself follows.
                break
            for job_id in [j for j in links if j in pending]:
                row = pending.pop(job_id)
                found += 1
                stats["harvested"] += 1
                yield row, _ies_read_card(links[job_id], job_id)

    for pending in outstanding.values():
        for row in pending.values():
            stats["searched"] += 1
            yield row, iesjobs_body(row)


# Keyed on `jobs.ats`, and each fetcher takes the whole row: a posting is
# addressed by `token` and `job_id` on Workday, Oracle and SmartRecruiters and
# by `url` on Jobbsafari, SuccessFactors, iCIMS and the Hong Kong portal, and
# there is no third thing they all have in common.
def _ld_body(url: str | None) -> Fetched:
    """Description and place from a page's schema.org `JobPosting` island.

    **Three vendors publish exactly the same thing and none of them was being
    read.** `icims_body` has parsed this island since it was written; Jobvite
    and Breezy publish it too, on the posting page whose URL the list already
    stores, and both had `bodies.coverage` at **0%** -- 378 and 197 postings
    reaching the tagger as a title and a date. The island carries the location
    as well, which is the second thing `Fetched` exists to fill.

    Written once rather than three times, because a vendor-shaped copy of this
    is what let the entity-decoding bug live in three modules at once.
    """
    if not url:
        return Fetched(None, None)
    try:
        page = http.get_text(url, timeout=25, retries=1)
    except Exception:  # noqa: BLE001 -- a 404, a timeout, a WAF challenge
        return Fetched(None, None)
    posting = _ld_job_posting(page)
    if posting is None:
        return Fetched(None, None)
    return Fetched(_clean(posting.get("description")), _ld_place(posting))


def jobvite_body(row) -> Fetched:
    """Jobvite's posting page. `jobs.jobvite.com/{token}/job/{id}`, stored."""
    return _ld_body(row["url"])


def breezy_body(row) -> Fetched:
    """Breezy's posting page. `{token}.breezy.hr/p/{id}`, stored."""
    return _ld_body(row["url"])


FETCHERS = {
    "workday": workday_body,
    "jobbsafari": jobbsafari_body,
    "successfactors": successfactors_body,
    "icims": icims_body,
    "oracle_hcm": oracle_hcm_body,
    "smartrecruiters": smartrecruiters_body,
    "iesjobs": iesjobs_body,
    "jobvite": jobvite_body,
    "breezy": breezy_body,
}

# The fetchers that can answer *where*, which is a strict subset: Jobbsafari
# and SmartRecruiters return `Fetched(body, None)` and always will, because
# their detail payloads carry no place their list payloads did not. Queue two
# in `targets` exists to fix a location, so only these belong in it -- naming
# them is what stops that arm from being a claim about today's data.
# Jobvite and Breezy join it: their JSON-LD carries `jobLocation`, and both
# list endpoints publish a place already -- so this arm only ever fills the
# rows where the list left it empty.
PLACES = frozenset({"workday", "successfactors", "icims", "oracle_hcm",
                    "jobvite", "breezy"})


# The three arms of the queue below are a `UNION`, so they must select the same
# columns in the same order -- a coupling SQL states only by failing at run
# time. Named once here, with the two joins they share: whether the tagger
# could read the posting (`_RATED`) and whether the board has already dropped
# it for being another profession or somewhere else (`_UNGATED`, which is a
# `LEFT JOIN` because the wanted rows are the ones it does *not* match).
_QUEUE = """SELECT j.ats, j.token, j.job_id, j.url, j.location,
                   j.category, j.first_seen
            FROM jobs j"""

_RATED = """JOIN job_tags r ON r.ats = j.ats AND r.token = j.token
                           AND r.job_id = j.job_id
                           AND r.dimension = 'relevance' AND r.tagger = ?"""

_UNGATED = """LEFT JOIN job_tags x ON x.ats = j.ats AND x.token = j.token
                                AND x.job_id = j.job_id
                                AND x.dimension = 'exclusion_reason'
                                AND x.tagger = ?"""


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
    placers = ",".join("?" * len(PLACES))
    return connection.execute(
        f"""
        SELECT * FROM (
            -- Queue one: the tagger could not place it and has no text to
            -- place it with.
            {_QUEUE}
            {_RATED}
            {_UNGATED}
            WHERE j.ats IN ({boards})
              -- **Hong Kong is the exception and it has its own arm below.**
              -- Everywhere else a body resolves an `unknown`; there it does
              -- not, because the prose is largely not in a language this
              -- lexicon reads. See the third arm.
              AND j.ats <> 'iesjobs'
              AND j.removed_at IS NULL
              AND (j.description IS NULL OR j.description = '')
              AND r.value = 'unknown'
              -- Not already gated off the board for being somewhere else or
              -- something else. Those are 50,000 postings and none of them
              -- becomes a quant job by acquiring a description.
              AND x.value IS NULL

            UNION

            -- Queue two: the list endpoint did not say where the job is.
            -- Not filtered on relevance, and no `r` join for the same reason:
            -- how well a posting reads has nothing to do with whether we know
            -- where it is. Still filtered on the gates, since a posting
            -- already off the board for being another profession does not come
            -- back by acquiring an address.
            --
            -- **Two shapes of missing, and the second was added later.**
            -- Workday summarises a multi-site requisition as `N Locations`;
            -- iCIMS' classic portal and seven SuccessFactors boards -- Scania,
            -- DekaBank, NordLB, BayernLB among them -- publish no location
            -- column at all, so 747 of the board's 941 placeless cards simply
            -- have NULL there. Both detail pages carry the address.
            --
            -- **Restricted to `PLACES` rather than to every fetcher.**
            -- Relying on "Jobbsafari always publishes a location" would make
            -- this arm's scope an empirical claim about today's data, and
            -- `tests/test_bodies.py` caught exactly that: a Jobbsafari row with
            -- a NULL location and a perfectly good verdict was queued for a
            -- fetcher that returns None for the question. The set is the
            -- honest bound.
            {_QUEUE}
            {_UNGATED}
            WHERE j.ats IN ({placers})
              AND j.removed_at IS NULL
              AND x.value IS NULL
              AND (j.location IS NULL
                   OR TRIM(j.location) = ''
                   OR j.location GLOB '[0-9]* Location'
                   OR j.location GLOB '[0-9]* Locations')

            UNION

            -- Queue three: Hong Kong, where the first arm's rule is inverted.
            --
            -- **Everywhere else a body resolves an `unknown`. Here it does
            -- not, and that is measured rather than assumed.** Of 1,028
            -- iesjobs postings whose description had been fetched, exactly
            -- **one** came out rated above `unknown` and **718 were still
            -- `unknown` afterwards** -- against a corpus where a posting with
            -- a body stays unreadable 1.0% of the time. The cause is not the
            -- lexicon missing a word: **44% of those descriptions are
            -- majority-Chinese**, and `posting_language` already labels 437 of
            -- them `cjk`. This lexicon is English, Swedish and Danish. So the
            -- old queue spent about 72 minutes a week -- three quarters of a
            -- `daily --full` at four seconds a request -- fetching prose
            -- nothing downstream can read.
            --
            -- What the card *is* still needed for is the employer, which the
            -- portal publishes nowhere on either list view. So the queue keeps
            -- exactly the postings where a name is worth a request: the ones
            -- the tagger has already rated. **Five of the six positives this
            -- source has ever produced were found from the title alone**, with
            -- no body at all, so nothing is being asked of the description
            -- that it was doing.
            {_QUEUE}
            {_RATED}
            {_UNGATED}
            WHERE j.ats = 'iesjobs'
              AND j.removed_at IS NULL
              AND (j.description IS NULL OR j.description = ''
                   OR j.employer IS NULL OR TRIM(j.employer) = '')
              AND r.value IN ('relevant', 'less_relevant', 'adjacent')
              AND x.value IS NULL
        )
        ORDER BY first_seen DESC
        LIMIT ?
        """,
        (tagging.TAGGER, tagging.TAGGER, *FETCHERS,
         tagging.TAGGER, *PLACES,
         tagging.TAGGER, tagging.TAGGER, limit),
    ).fetchall()


def _host_of(row: sqlite3.Row) -> str:
    """Which host this row's fetch will hit, for `_spread`.

    `http._throttle` books its interval per host, so this is the resource the
    pool is actually contending for. Jobbsafari is one site, so every row of it
    shares a key -- correctly: they genuinely cannot be spread.

    **The other three sources are per-tenant hosts and returning the bare
    `ats` name for them would undo `_spread` entirely.** SuccessFactors serves
    every board from the firm's own hostname, iCIMS from
    `careers-{token}.icims.com`, Oracle from a pod -- so one key for all of
    them would put 991 SuccessFactors rows behind a single throttle slot,
    which is the 335-consecutive-`usbank` failure this function was written to
    stop, in a new source.
    """
    if row["ats"] == "workday":
        return _workday_origin(row["token"]) or "workday:malformed"
    if row["ats"] == "successfactors":
        # The token *is* the host -- see `extract.successfactors`.
        return f"successfactors:{row['token']}"
    if row["ats"] == "oracle_hcm":
        return f"oracle:{str(row['token']).partition('|')[0]}"
    if row["ats"] == "icims":
        return f"icims:{urllib.parse.urlsplit(row['url'] or '').netloc}"
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
) -> tuple[int, int, int, int, dict[str, int]]:
    """Fill in missing descriptions, unresolved places and absent employers.

    Returns (attempted, filled, placed, named, hong_kong). The middle three are
    counted separately because they are separate faults with separate cures,
    and one total would hide a pass that fetched five thousand pages and
    resolved no location. The last is `_iesjobs_pass`'s split between the cheap
    route and the fallback -- see there for why it has to be visible.
    """
    queued = targets(connection, limit)
    # **Hong Kong is walked, not mapped, and it is separated here rather than
    # inside the pool.** Every one of its rows is the same host at four seconds
    # a request, so `_spread` can do nothing with them and twelve threads are
    # eleven threads waiting -- measured, the tell is one established TCP
    # connection and flat CPU. `_iesjobs_pass` reads them in one sequential
    # walk that mints tokens twenty to a page; taking them out of `rest` also
    # lets `_spread` interleave the hosts that are genuinely spreadable.
    hong_kong = [row for row in queued if row["ats"] == "iesjobs"]
    rest = _spread([row for row in queued if row["ats"] != "iesjobs"])
    routes: dict[str, int] = {"harvested": 0, "searched": 0}
    if not hong_kong and not rest:
        return 0, 0, 0, 0, routes

    def work(row: sqlite3.Row) -> tuple[sqlite3.Row, Fetched]:
        return row, FETCHERS[row["ats"]](row)

    # **Two producers, one writer.** `db.connect` hands out a connection bound
    # to the thread that made it, so the writing stays where it has always
    # been -- here -- and the two fetch strategies feed it through a queue.
    # They run at once because they contend for nothing: Hong Kong is one host
    # and `rest` is every other, and `http._throttle` books per host anyway.
    done: queue.Queue = queue.Queue()
    finished = object()
    failures: list[BaseException] = []

    def feed(source) -> None:
        try:
            for pair in source:
                done.put(pair)
        except BaseException as exc:  # noqa: BLE001 -- re-raised by the consumer
            # **Not swallowed.** A fetcher meeting a shape it does not expect
            # must still end the pass loudly, or a schema change reads as a
            # zero-filled run -- see `TargetsTest`. It is carried across the
            # thread boundary and raised below, after the rows already fetched
            # have been committed, which is what batching is for.
            failures.append(exc)
        finally:
            done.put(finished)

    attempted = filled = placed = named = 0
    batch: list[tuple[str | None, str | None, str | None, str, str, str]] = []
    # Written in batches, like every other long pass here: this is tens of
    # minutes of network work and losing it to one exception means fetching
    # bodies we already have.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        producers = 0
        for source in (pool.map(work, rest) if rest else None,
                       _iesjobs_pass(hong_kong, routes) if hong_kong else None):
            if source is not None:
                threading.Thread(target=feed, args=(source,), daemon=True).start()
                producers += 1
        while producers:
            item = done.get()
            if item is finished:
                producers -= 1
                continue
            row, got = item
            attempted += 1
            body = got.description or None
            # **Only ever over a placeholder**, and there are two of them. A
            # posting that published a real place keeps it: the detail
            # endpoint is a second opinion, not a better one, and overwriting a
            # good location with it would be a write nobody asked for on the
            # strength of nothing. But a posting that published *no* place has
            # nothing to protect -- iCIMS' classic portal names one nowhere, so
            # its 1,824 postings sit at `hub: unknown`, which the geography
            # gate lets through and nothing can rank. An absent location is the
            # purest placeholder there is.
            stated = (row["location"] or "").strip()
            where = got.location if not stated or _UNRESOLVED.match(stated) else None
            # The employer needs no placeholder rule: `_write` COALESCEs, so a
            # name already held is never overwritten, and the only source that
            # returns one publishes it nowhere else.
            who = got.employer or None
            if not body and not where and not who:
                continue
            filled += bool(body)
            placed += bool(where)
            named += bool(who)
            batch.append(
                (body, where, who, row["ats"], row["token"], row["job_id"])
            )
            if len(batch) >= 100:
                _write(connection, batch)
                batch.clear()
    _write(connection, batch)
    if failures:
        raise failures[0]
    return attempted, filled, placed, named, routes


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
        # `COALESCE` because any part may be missing: a row fetched for its
        # body must not blank a location, a row fetched for its location must
        # not blank a body it already had, and a walk that re-lists the posting
        # tomorrow must not blank the employer this pass just learned.
        connection.executemany(
            "UPDATE jobs SET description = COALESCE(?, description),"
            "                location = COALESCE(?, location),"
            "                employer = COALESCE(?, employer)"
            " WHERE ats = ? AND token = ? AND job_id = ?",
            batch,
        )
        connection.executemany(
            "DELETE FROM job_tags"
            " WHERE ats = ? AND token = ? AND job_id = ? AND tagger = ?",
            [(ats, token, job_id, tagging.TAGGER) for *_, ats, token, job_id in batch],
        )


def coverage(connection: sqlite3.Connection):
    """Bodies held per source -- the number this stage exists to move.

    **`iesjobs` is the one row here that is deliberately low and must not be
    read as a missing fetcher.** Its queue is inverted -- see `targets`' third
    arm -- because a Hong Kong description resolves an `unknown` at 0.1% and
    44% of them are majority-Chinese, which this lexicon does not read. A `0%`
    row is still the tell for every *other* source.
    """
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
