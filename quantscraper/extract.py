"""Layer 3 -- pulling postings out of the applicant tracking systems.

Stage 5 resolved firms to `(ats, token)`. Each ATS publishes one endpoint shape,
so this is one small function per format rather than one scraper per firm. That
is the whole reason the employer-first architecture is worth its setup cost.

**Workday gets special handling, and the plan's note about it is half right.**
The documented trap is that `limit` above 20 returns an empty `jobPostings`
array with HTTP 200 -- indistinguishable from "no jobs". Against the tenants
here it actually returns **HTTP 400**, which is loud rather than silent. Both
failures have the same cure and it is not optional:

  * never ask for more than 20 -- `_WORKDAY_MAX` is asserted, not just used;
  * page with `offset` and stop when a page comes back short;
  * do not trust `total` after the first page -- Workday reports `total: 0` on
    subsequent pages, so believing it truncates every board at 20 postings.

The last one is the trap that would actually have bitten us: it is silent, it
looks like a complete result, and every large bank publishes through Workday.

`tests/test_workday.py` fails if the cap is removed.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import urllib.error
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable

from . import db, http, parsing
from .models import Job

# Workday rejects anything larger, and on some tenants does so silently.
_WORKDAY_MAX = 20
# A last-ditch bound on a tenant that never returns a short page, not a limit
# on how big a board may be. It was 40 pages, and LSEG and State Street both
# came back at exactly 800 postings -- the guard against silent truncation was
# silently truncating. Paging stops on a short page or a page that repeats the
# previous one; this only catches a server doing neither.
_WORKDAY_PAGES = 1_000

_TAGS = re.compile(r"<[^>]+>")


# One definition, in `parsing`, which owns reading markup. Kept under the old
# name here because `sites.py` and a dozen readers below call it by that name.
_text = parsing.text
_soup = parsing.soup


def _json(url: str, **kwargs) -> object:
    return json.loads(http.get_text(url, timeout=25, retries=2, **kwargs))


def greenhouse(token: str) -> list[Job]:
    payload = _json(
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    )
    return [
        Job(
            ats="greenhouse",
            token=token,
            job_id=str(job["id"]),
            title=job.get("title") or "",
            url=job.get("absolute_url"),
            location=(job.get("location") or {}).get("name"),
            department=", ".join(
                d.get("name", "") for d in (job.get("departments") or [])
            )
            or None,
            posted_at=job.get("updated_at"),
            description=_text(job.get("content")),
        )
        for job in payload.get("jobs", [])
    ]


def lever(token: str) -> list[Job]:
    payload = _json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    return [
        Job(
            ats="lever",
            token=token,
            job_id=str(job["id"]),
            title=job.get("text") or "",
            url=job.get("hostedUrl"),
            location=(job.get("categories") or {}).get("location"),
            department=(job.get("categories") or {}).get("team"),
            posted_at=str(job.get("createdAt") or "") or None,
            description=_text(job.get("descriptionPlain") or job.get("description")),
        )
        for job in payload
    ]


def ashby(token: str) -> list[Job]:
    payload = _json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    return [
        Job(
            ats="ashby",
            token=token,
            job_id=str(job.get("id") or job.get("jobId")),
            title=job.get("title") or "",
            url=job.get("jobUrl"),
            location=job.get("location"),
            department=job.get("department") or job.get("team"),
            posted_at=job.get("publishedAt"),
            description=_text(job.get("descriptionPlain")),
        )
        for job in payload.get("jobs", [])
    ]


def smartrecruiters(token: str) -> list[Job]:
    payload = _json(
        f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100"
    )
    jobs = []
    for job in payload.get("content", []):
        location = job.get("location") or {}
        if not isinstance(location, dict):
            location = {}
        # `ref` is a dict of links on most boards and a bare string on some.
        ref = job.get("ref")
        ref = ref if isinstance(ref, dict) else {}
        # **And where it is a string, both link fields are empty -- which was
        # every live SmartRecruiters row we hold.** All 1,507 of them across 12
        # boards had `url` NULL: `ref` is the API's own self-link and
        # `applyUrl` is `null`, so the two fallbacks above resolved to nothing
        # and the board rendered cards nobody could open. The code already knew
        # `ref` came in two shapes and simply gave up on the second.
        #
        # The public ad is `jobs.smartrecruiters.com/{company}/{id}` -- verified
        # against the live board rather than guessed, and the title slug some
        # boards append is optional. `company.identifier` is preferred over
        # `token` because it is the payload's own answer to the same question.
        company = job.get("company")
        company = company.get("identifier") if isinstance(company, dict) else None
        posting_id = str(job["id"])
        jobs.append(
            Job(
                ats="smartrecruiters",
                token=token,
                job_id=posting_id,
                title=job.get("name") or "",
                url=ref.get("jobAd")
                or job.get("applyUrl")
                or f"https://jobs.smartrecruiters.com/{company or token}/{posting_id}",
                location=", ".join(
                    p for p in (location.get("city"), location.get("country")) if p
                )
                or None,
                department=(job.get("department") or {}).get("label"),
                posted_at=job.get("releasedDate"),
            )
        )
    return jobs


def workable(token: str) -> list[Job]:
    payload = _json(
        f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true"
    )
    return [
        Job(
            ats="workable",
            token=token,
            job_id=str(job.get("shortcode") or job.get("id")),
            title=job.get("title") or "",
            url=job.get("url") or job.get("shortlink"),
            location=job.get("location")
            if isinstance(job.get("location"), str)
            else ", ".join(
                p
                for p in (
                    (job.get("location") or {}).get("city"),
                    (job.get("location") or {}).get("country"),
                )
                if p
            )
            or None,
            department=job.get("department"),
            posted_at=job.get("published_on"),
            description=_text(job.get("description")),
        )
        for job in payload.get("jobs", [])
    ]


def recruitee(token: str) -> list[Job]:
    payload = _json(f"https://{token}.recruitee.com/api/offers/")
    return [
        Job(
            ats="recruitee",
            token=token,
            job_id=str(job["id"]),
            title=job.get("title") or job.get("position") or "",
            url=job.get("careers_url") or job.get("careers_apply_url"),
            location=", ".join(
                p for p in (job.get("city"), job.get("country")) if p
            )
            or None,
            department=job.get("department"),
            posted_at=job.get("published_at") or job.get("created_at"),
            description=_text(job.get("description")),
        )
        for job in payload.get("offers", [])
    ]


def bamboohr(token: str) -> list[Job]:
    """BambooHR. `token` is the subdomain the customer's board is served from.

    **A retired subdomain 302s to the vendor's marketing site**, so the JSON
    endpoint answers HTTP 200 with a page of HTML and the reader failed with
    `JSONDecodeError: Expecting value: line 1 column 1` -- four boards saying
    "this customer is gone" in the least readable way available. It is the same
    signal as iCIMS' redirect stub, and it is caught the same way: the answer
    came from somewhere else.
    """
    origin = f"https://{token}.bamboohr.com"
    body, answered = http.get_with_url(f"{origin}/careers/list", timeout=25, retries=2)
    if not answered.startswith(origin):
        raise ValueError(
            f"bamboohr/{token}: board redirects to {answered} -- "
            "the subdomain is no longer a customer, so re-walk the domain"
        )
    payload = json.loads(body.decode("utf-8", errors="replace"))
    return [
        Job(
            ats="bamboohr",
            token=token,
            job_id=str(job["id"]),
            title=job.get("jobOpeningName") or "",
            url=f"{origin}/careers/{job['id']}",
            location=_text(
                (job.get("location") or {}).get("city")
                if isinstance(job.get("location"), dict)
                else job.get("atsLocation")
            ),
            department=job.get("departmentLabel"),
            posted_at=job.get("datePosted"),
        )
        for job in (payload.get("result") or [])
    ]


def breezy(token: str) -> list[Job]:
    payload = _json(f"https://{token}.breezy.hr/json")
    jobs = []
    for job in payload:
        location = job.get("location") or {}
        city = (location.get("city") or "") if isinstance(location, dict) else ""
        country = (
            ((location.get("country") or {}) or {}).get("name", "")
            if isinstance(location, dict)
            else ""
        )
        jobs.append(
            Job(
                ats="breezy",
                token=token,
                job_id=str(job.get("id") or job.get("friendly_id")),
                title=job.get("name") or "",
                url=job.get("url"),
                location=", ".join(p for p in (city, country) if p) or None,
                department=(job.get("department") or {}).get("name")
                if isinstance(job.get("department"), dict)
                else job.get("department"),
                posted_at=job.get("published_date"),
                description=_text(job.get("description")),
            )
        )
    return jobs


def personio(token: str) -> list[Job]:
    """Personio, from the XML feed rather than `search.json`.

    **`search.json` publishes `"description": ""` on every posting**, which is
    how this source sat at **0% in `bodies.coverage`** with 149 postings and no
    fetcher -- a board answering 200 with a field that is present and empty,
    which reads as "this employer wrote nothing" rather than as a gap.

    The XML feed is the same board, **the same ids** (26 of 26 overlap, checked
    against `search.json` before this was switched, because a new id space
    would have orphaned every stored row) and carries what the JSON does not:
    the prose, split across named sections, plus `createdAt`,
    `yearsOfExperience` and `occupationCategory` -- Personio's own occupation
    taxonomy, which is the field `Job.category` exists for.

    One request per board either way, so this costs nothing.

    **The feed is a fallback and not a replacement, which was measured rather
    than assumed.** Of the 25 boards held here, **four answer HTTP 404 on
    `/xml` while serving `search.json` normally** -- `7orca`, `cflox-gmbh`,
    `real-garant-versicherung-ag` and `rudolf`, 22 postings between them. A
    tenant can switch the feed off. Reading only the XML would have taken those
    boards silently to zero, which is "this vendor is closed" written as a
    reader instead of as a note.
    """
    try:
        body = http.get_text(
            f"https://{token}.jobs.personio.de/xml", timeout=25, retries=2
        )
        root = ElementTree.fromstring(body)
    except (urllib.error.HTTPError, ElementTree.ParseError):
        return _personio_json(token)

    jobs: list[Job] = []
    for position in root.iter("position"):
        job_id = (position.findtext("id") or "").strip()
        if not job_id:
            continue
        # Sections joined rather than picked: `Your Responsibilities` is where
        # the years figure and the degree requirement live, and the first
        # section is usually the firm describing itself.
        prose = " ".join(
            value.text or ""
            for value in position.iterfind("jobDescriptions/jobDescription/value")
        )
        jobs.append(
            Job(
                ats="personio",
                token=token,
                job_id=job_id,
                title=_text(position.findtext("name")) or "",
                url=f"https://{token}.jobs.personio.de/job/{job_id}",
                location=_text(position.findtext("office")),
                department=_text(position.findtext("department")),
                category=_text(position.findtext("occupationCategory")),
                posted_at=(position.findtext("createdAt") or "").strip() or None,
                description=_text(prose),
            )
        )
    return jobs or _personio_json(token)


def _personio_json(token: str) -> list[Job]:
    """The list `search.json` publishes, for a tenant with no XML feed.

    Every field the XML has except the one that matters: `description` is
    present on every row and empty on every row. Kept because a posting with
    no body is still a posting, and `bodies` has nowhere to fetch one from
    here -- the job page is a client-side app.
    """
    payload = _json(f"https://{token}.jobs.personio.de/search.json")
    return [
        Job(
            ats="personio",
            token=token,
            job_id=str(job["id"]),
            title=job.get("name") or "",
            url=f"https://{token}.jobs.personio.de/job/{job['id']}",
            location=job.get("office"),
            department=job.get("department"),
            posted_at=job.get("createdAt") or job.get("created_at"),
            description=_text(job.get("description")),
        )
        for job in (payload if isinstance(payload, list) else payload.get("jobs", []))
    ]


# iCIMS publishes no feed of any kind -- the `format=rss` the vendor once
# offered now 302s to a staff login page -- so the portal's own HTML is the
# only public surface. Job links have a fixed shape, which is what makes this
# parseable at all: `/jobs/{id}/{slug}/job`.
#
# Both halves are length-bounded, for the reason the whole of `ats.py` is: an
# unbounded run inside a quoted attribute over 100 KB of markup is where two
# runs of this pipeline previously sat at full CPU for two and a half hours.
_ICIMS_JOB = re.compile(
    r"https://[a-z0-9.\-]{1,80}\.icims\.com/jobs/(\d{1,12})/([^/\"']{1,120})/job",
    re.I,
)

# The portal serves 50 per page and answers `pr` as the page number. The bound
# is a guard against a portal that never runs out, not a limit on board size:
# paging stops when a page adds no new posting, which is the same rule Workday
# needs for a tenant that ignores `offset`.
_ICIMS_PAGES = 60


def _icims_title(slug: str) -> str:
    """A readable title from the URL slug, which is all the list page gives.

    **The list page carries no anchor text**, so the slug is the only title
    available without fetching all 50 job pages per page of results -- which
    for 38 boards is thousands of extra requests for a field the tagger
    lowercases anyway.

    It is lossy and the losses are worth naming: `c++` survives a slug as `c`,
    and original casing is gone, so `EMEA` comes back as `Emea`. `fold` maps
    both sides to lowercase tokens before any needle runs, so the tagger is
    unaffected; what suffers is only how the card reads on the board.
    """
    words = urllib.parse.unquote(slug).replace("-", " ").split()
    return " ".join(word[:1].upper() + word[1:] for word in words)


# **A migrated iCIMS board answers HTTP 200 with a 150-byte script and no
# postings**, which is principle 2's failure exactly: a scraper that breaks and
# returns zero rows with HTTP 200 is more dangerous than one that crashes,
# because nothing announces it. Twelve of 36 boards here were in that state,
# Principal, AXA and SiriusXM among them, every one reported as "an empty
# board" by a reader that had no way to tell the difference.
#
# The stub names where the board went, and that splits in two. A target still
# on `icims.com` is the same portal under a different prefix -- iCIMS hosts are
# `{prefix}-{token}.icims.com` and the prefix is not always `careers`
# (`allcareers-frankrimerman`, `uscareers-siriusxmradio`) -- so it is followed.
# Anything else is the firm moving to the vendor's newer career-site product on
# its own hostname, which this reader cannot read, and that is raised with the
# target in the message so the next walk has somewhere to start.
_ICIMS_STUB = re.compile(r"window\.top\.location\.href\s*=\s*'([^']+)'")


def _icims_page(origin: str, page: int) -> str:
    return http.get_text(
        f"{origin}/jobs/search?ss=1&in_iframe=1&pr={page}", timeout=25, retries=2
    )


def _icims_origin(token: str) -> tuple[str, str]:
    """The portal host actually serving this board, and its first page."""
    origin = f"https://careers-{token}.icims.com"
    for _ in range(2):
        body = _icims_page(origin, 0)
        stub = _ICIMS_STUB.search(body)
        if not stub or _ICIMS_JOB.search(body):
            return origin, body
        target = stub.group(1).replace("\\", "")
        host = urllib.parse.urlsplit(target).netloc
        if not host.endswith(".icims.com"):
            raise ValueError(
                f"icims/{token}: board has moved to {target} -- "
                "not an iCIMS portal, so re-walk the domain"
            )
        origin = f"https://{host}"
    raise ValueError(f"icims/{token}: portal redirects in a loop")


def icims(token: str) -> list[Job]:
    """iCIMS, by reading the careers portal. SIG is on this.

    38 boards resolved to iCIMS and none of them were ever polled, because
    `ats.py` recognises the host and `extract.py` had no reader -- tier A, a
    token, and silence. It is the largest single block of that kind.

    **Titles and links only.** There is no location, department or description
    on the list page, so postings from here reach the tagger with a title and
    nothing else. That is thin, and it is still worth having: `judge` already
    refuses to reject on a title alone, so these land in `unknown` rather than
    being wrongly excluded, and every one carries a URL that opens.
    """
    jobs: list[Job] = []
    seen: set[str] = set()
    origin, first = _icims_origin(token)
    for page in range(_ICIMS_PAGES):
        if page == 0:
            body = first
        else:
            try:
                body = _icims_page(origin, page)
            except urllib.error.HTTPError:
                # A board that has ended answers 404 on the first page, which
                # `_icims_origin` has already let through. Anything after that
                # is a paging edge, not a failure worth losing the postings
                # already read for.
                break
        fresh = 0
        for match in _ICIMS_JOB.finditer(body):
            job_id, slug = match.group(1), match.group(2)
            if job_id in seen:
                continue
            seen.add(job_id)
            fresh += 1
            jobs.append(
                Job(
                    ats="icims",
                    token=token,
                    job_id=job_id,
                    title=_icims_title(slug),
                    url=f"{origin}/jobs/{job_id}/{slug}/job",
                )
            )
        # Stop when a page adds nothing. A portal that ignores `pr` serves page
        # one forever, and the empty-page test alone would never catch it.
        if not fresh:
            break
    return jobs


# Jobvite publishes no feed either -- `?format=rss` serves the careersite HTML
# and the v2 API wants a key -- but its careersite carries the whole list in
# the markup, which is more than iCIMS gives.
#
# **It ships two layouts and a firm may run either**, which is the
# SuccessFactors lesson one vendor over. A *table*, where `jv-job-list-name`
# labels the cell containing the anchor:
#
#   <td class="jv-job-list-name"><a href="/{token}/job/{id}">Title</a></td>
#   <td class="jv-job-list-location"> London, England </td>
#
# and a *card list*, where the anchor comes first and the two fields are
# `<div>`s inside it. They agree on the class names and on nothing else, so
# each layout needed its own pattern -- and the table pattern read a card board
# as **nought** until the second was written: `addendacapital` advertised
# `1-3 of 3` and `mercycorps` 32, and both came back empty.
#
# One selector reads both, because to a parser the difference is only where the
# anchor sits relative to the name, and `find_parent` answers that in either
# direction. **And `class="jv-job-list-location ml-auto"` cannot cost the
# location again**: a second class beside the one being matched is a fact about
# a list here, not a character the pattern was not expecting -- that spelling
# cost every location on the boards that use it, because the pattern wanted a
# quote where the markup has a space.
_JOBVITE_NAME = ".jv-job-list-name"
_JOBVITE_PLACE = ".jv-job-list-location"


def _jobvite_rows(body: str) -> list[tuple[str, str, str | None]]:
    """`(job_id, title, location)` for every posting on one careersite page.

    The row is the nearest `<tr>` where there is one and the anchor itself
    otherwise, which is exactly the difference between the two layouts.
    """
    rows: list[tuple[str, str, str | None]] = []
    for name in _soup(body).select(_JOBVITE_NAME):
        link = name if name.name == "a" else name.find("a", href=True)
        if link is None:
            link = name.find_parent("a", href=True)
        href = link["href"].split("?")[0]
        if "/job/" not in href:
            continue
        # The segment straight after `/job/`, not the last one: the old pattern
        # anchored on `/job/([A-Za-z0-9]{1,24})` and a board linking
        # `/job/{id}/apply` would otherwise hand back `apply` as the id.
        job_id = href.split("/job/", 1)[1].split("/")[0]
        if not job_id:
            continue
        row = name.find_parent("tr") or link
        place = row.select_one(_JOBVITE_PLACE)
        rows.append(
            (
                job_id,
                " ".join(name.get_text(" ").split()),
                " ".join(place.get_text(" ").split()) or None if place else None,
            )
        )
    return rows


_JOBVITE_TOTAL = re.compile(r"\d{1,6}\s*-\s*\d{1,6}\s+of\s+(\d{1,6})", re.I)

# A backstop against a careersite that never runs out, not a limit on board
# size: at 50 a page this is 5,000 postings, and paging stops when a page adds
# nothing long before that.
_JOBVITE_PAGES = 100


def jobvite(token: str) -> list[Job]:
    """Jobvite, by reading the careersite table. Quantlab is on this.

    **50 per page, and the trailing slash is load-bearing.** The board first
    came back at exactly 50 postings, which is what a cap looks like from the
    outside -- and it was one: Sikich advertises `1-50 of 73`. The next link is
    `/{token}/search/?p=1`, with a slash before the query that
    `/{token}/search?p=1` does not have, and without it the server answers the
    first page while looking like it paged. `p` is zero-based, so page one is
    the bare URL and `p=1` is the second.

    Unlike iCIMS this carries the real title as anchor text, so no casing is
    lost, and a location column besides. There is still no description.

    **And the board states its own size, which is the check.** `1-50 of 73` is
    what found the missing slash in the first place, and the total was being
    parsed and then never compared to anything -- so the guard the plan
    describes as running on every board was not running at all. A shortfall
    raises now, the same way `oracle_hcm` does.
    """
    jobs: list[Job] = []
    seen: set[str] = set()
    advertised = 0
    for page in range(_JOBVITE_PAGES):
        url = f"https://jobs.jobvite.com/{token}/search/"
        if page:
            url += f"?p={page}"
        body = http.get_text(url, timeout=25, retries=2)

        if not advertised:
            total = _JOBVITE_TOTAL.search(body)
            advertised = int(total.group(1)) if total else 0

        # One pass over both layouts. This used to be two findall passes zipped
        # by position, with a length check to throw every location away when
        # they disagreed -- because pairing a location with the wrong posting
        # sends the geography *gate* an answer about somewhere else, which
        # deletes a posting rather than mis-ranking it. Reading each row's own
        # location out of the row makes the pairing structural, so there is
        # nothing left to check.
        entries = _jobvite_rows(body)

        fresh = 0
        for job_id, title, place in entries:
            if job_id in seen:
                continue
            seen.add(job_id)
            fresh += 1
            jobs.append(
                Job(
                    ats="jobvite",
                    token=token,
                    job_id=job_id,
                    title=title,
                    url=f"https://jobs.jobvite.com/{token}/job/{job_id}",
                    location=place or None,
                )
            )
        # Stop when a page adds nothing -- the same rule iCIMS and Workday
        # need, and for the same reason: a server ignoring the page parameter
        # serves page one forever and never returns an empty page.
        if not fresh:
            break
    if advertised > len(jobs):
        raise ValueError(
            f"jobvite/{token}: board advertises {advertised} postings, read {len(jobs)}"
        )
    return jobs


# Varbi puts the posting id in the link and nowhere else. Bounded, like every
# pattern here that runs over fetched bytes.
_VARBI_ID = re.compile(r"jobID:(\d{1,12})", re.I)


def varbi(token: str) -> list[Job]:
    """Varbi's RSS. Swedish public-sector and mid-market hiring runs on this.

    The board's own pages are `/{lang}/what:list/`, which 404s as
    "Unallowed call" for every language tried -- the listing is reachable only
    from the site root, and even there a firm with no openings shows nothing
    but a spontaneous-application link. `/what:rssfeed/` is the stable surface
    and it carries the description, which the root page does not.

    An empty channel is a real answer, the same as Teamtailor: three of the
    five boards here have no openings today.
    """
    body = http.get(f"https://{token}.varbi.com/what:rssfeed/", timeout=25, retries=2)
    channel = ElementTree.fromstring(body).find("channel")
    if channel is None:
        raise ValueError(f"varbi board {token!r} served no channel")

    jobs: list[Job] = []
    for item in channel.iterfind("item"):
        link = (item.findtext("link") or "").strip()
        found = _VARBI_ID.search(link)
        if not found and not link:
            continue
        jobs.append(
            Job(
                ats="varbi",
                token=token,
                job_id=found.group(1) if found else link,
                title=(item.findtext("title") or "").strip(),
                url=link or None,
                posted_at=(item.findtext("pubDate") or "").strip() or None,
                description=_text(item.findtext("description")),
            )
        )
    return jobs


_ATOM = "{http://www.w3.org/2005/Atom}"


def homerun(token: str) -> list[Job]:
    """Homerun's Atom feed. Dutch mid-market, so it reaches the Amsterdam hub.

    The board itself is a script-rendered page that links out to the firm's own
    careers host -- Tiqets serves its postings from `jobs.tiqets.work` -- so
    the feed is the only reliable surface, and `feed.homerun.co/{token}` is it.
    The `<link rel="alternate">` href follows the firm to whatever host it uses,
    which is what makes these postings openable.
    """
    body = http.get(f"https://feed.homerun.co/{token}", timeout=25, retries=2)
    feed = ElementTree.fromstring(body)

    jobs: list[Job] = []
    for entry in feed.iterfind(f"{_ATOM}entry"):
        link = entry.find(f"{_ATOM}link")
        url = link.get("href") if link is not None else None
        job_id = (entry.findtext(f"{_ATOM}id") or url or "").strip()
        if not job_id:
            continue
        jobs.append(
            Job(
                ats="homerun",
                token=token,
                job_id=job_id,
                title=(entry.findtext(f"{_ATOM}title") or "").strip(),
                url=url,
                posted_at=(entry.findtext(f"{_ATOM}updated") or "").strip() or None,
                description=_text(
                    entry.findtext(f"{_ATOM}content")
                    or entry.findtext(f"{_ATOM}summary")
                ),
            )
        )
    return jobs


# Hailey HR renders its board server-side, so the cards are in the markup --
# but as Tailwind-classed divs with no ids or data attributes, which means the
# only stable handles are the anchor's href shape and the tag types inside it.
# Bounded like every pattern here that runs over fetched bytes.
#
# The href is `/{lang}/job/{company}/{job}/{posting}`, three UUIDs. All three
# are needed to address the posting, and the middle one alone is the job -- a
# posting is a job published to one board, so the same job can appear twice.
# **The href shape is the anchor, and it stays a pattern for that reason.**
# The card markup carries no ids and the classes are Tailwind, so the URL is
# the part the vendor cannot change without breaking its own links -- three
# UUIDs, company/job/posting, of which the middle one is the job.
_HAILEY_HREF = re.compile(
    r"^/[a-z]{2}-[A-Z]{2}/job/[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}$", re.I
)
# Read *inside* the card the href identifies, so a heading or a chip cannot be
# taken from the card next door. The location chip is Hailey's "workplace",
# and it is the only text in this wrapper.
_HAILEY_TITLE = "h3"
_HAILEY_PLACE = "div.flex.items-center.justify-between.gap-1"
_HAILEY_SUMMARY = "p"


def hailey(token: str) -> list[Job]:
    """Hailey HR. Coeli is on this, with eight openings and no way to see them.

    A Nordic ATS that no generic scraper covers, which is exactly the class
    `ats.py`'s header says Stockholm and Copenhagen cannot be exhaustive
    without. The board is at `{token}.careers.haileyhr.app` and is rendered
    server-side, so one request is the whole thing -- no paging, no key, and no
    JSON endpoint either (`/api/jobs` and the two obvious variants all 404).

    **The card markup carries no ids, so the href shape is the anchor.** Three
    UUIDs -- company, job, posting -- and the job id is the middle one. Matching
    on Tailwind class strings would break on the vendor's next redesign; the
    URL shape is the part they cannot change without breaking their own links.

    The summary is the card's teaser rather than the full description. That is
    still worth taking: `tagging.py` grades a body-only match `weak`, and a
    teaser is the firm's own one-line statement of what the job is.
    """
    body = http.get_text(f"https://{token}.careers.haileyhr.app/", timeout=25, retries=2)
    jobs: list[Job] = []
    seen: set[str] = set()
    for card in _soup(body).find_all("a", href=_HAILEY_HREF):
        title = card.select_one(_HAILEY_TITLE)
        if title is None:
            # No heading means this is not a job card -- Hailey uses the same
            # anchor shape for the "read more" tile at the foot of the board.
            continue
        href = card["href"]
        job_id = href.split("/")[4]
        if job_id in seen:
            continue
        seen.add(job_id)
        place = card.select_one(_HAILEY_PLACE)
        summary = card.select_one(_HAILEY_SUMMARY)
        jobs.append(
            Job(
                ats="hailey",
                token=token,
                job_id=job_id,
                title=_text(title.decode_contents()) or "",
                url=f"https://{token}.careers.haileyhr.app{href}",
                location=_text(place.decode_contents()) if place else None,
                description=_text(summary.decode_contents()) if summary else None,
            )
        )
    return jobs


def pinpoint(token: str) -> list[Job]:
    """Pinpoint. Systematica is on this, and it was tier A polling nothing.

    `/postings.json` is the whole board in one request -- no paging, no key.
    There is also a `/jobs.rss`, which is how the board was fingerprinted in
    the first place; the JSON carries the description and the RSS does not.

    **`deadline_at` is a published field, so it is mapped** even though every
    board sampled leaves it null. That is the rule this project already
    follows: a closing date is taken when the source states one and never
    mined out of prose. A field that is always empty costs nothing; a date
    guessed from a description pins the wrong card to the top of the board.
    """
    payload = _json(f"https://{token}.pinpointhq.com/postings.json")
    jobs = []
    for job in payload.get("data") or []:
        # `location` is an object, and which key carries the readable form
        # varies: `name` is "Manchester, UK" on one board and absent on
        # another, where only `city` is set.
        location = job.get("location")
        if isinstance(location, dict):
            place = location.get("name") or location.get("city")
        else:
            place = location if isinstance(location, str) else None
        jobs.append(
            Job(
                ats="pinpoint",
                token=token,
                job_id=str(job["id"]),
                title=job.get("title") or "",
                url=job.get("url"),
                location=place,
                department=job.get("department"),
                deadline=job.get("deadline_at"),
                description=_text(job.get("description")),
            )
        )
    return jobs


# Avature, which serves each customer a career portal on the customer's own
# hostname -- `careers.twosigma.com` -- so there is no `{board}.avature.com`
# for a host pattern to match. The board *is* the host, the same shape as a
# Teamtailor customer fronting its board on `careers.lynxhedge.se`, and the
# giveaway in the markup is the vendor's asset CDN, `avacdn.net`.
#
# Two Sigma is the reason this exists: a roster firm in two focus hubs whose
# careers page nothing recognised, and one of the firms `UNDERGROUND.md` holds
# up as unreachable. The portal is plain server-rendered HTML with no feed and
# no API.
#
# **The list page is named per tenant**, which is why this is a list rather
# than a constant. Two Sigma calls it `OpenRoles` and Avature's own default is
# `SearchJobs`; asking for the wrong one gets a 404, not an empty board, so
# trying each in turn costs one request and mistakes nothing for silence.
AVATURE_LIST_PATHS = (
    "/careers/OpenRoles",
    "/careers/SearchJobs",
    "/careers/JobSearch",
    "/careers/Jobs",
)
# The portal pages ten at a time and ignores every page-size parameter tried,
# the same as MAS. `jobOffset` is the cursor.
_AVATURE_PAGE = 10
_AVATURE_PAGES = 300

# One result card. The chunk is split on the opening tag rather than matched as
# a whole, for the reason `jobvite` gives one screen up: a single pattern
# reaching from the title anchor down to the location spans has to cross
# arbitrary nested markup, and that is where a regex over fetched markup turns
# quadratic.
_AVATURE_CARD = "article--result"
_AVATURE_JOB = re.compile(
    r'href="([^"]*?/careers/JobDetail/[^"/]*/(\d+))"[^>]*>\s*(.*?)\s*</a>',
    re.I | re.S,
)
_AVATURE_SPAN = re.compile(
    r'<span[^>]*class="[^"]*paragraph_inner-span[^"]*"[^>]*>(.*?)</span>',
    re.I | re.S,
)


def _avature_cards(markup: str) -> list[str]:
    return [chunk for chunk in markup.split("<article")[1:] if _AVATURE_CARD in chunk]


def avature(token: str) -> list[Job]:
    """Avature. `token` is the portal host -- see `ats.py` for why.

    **Paging stops on a page that adds no new posting id**, not on a short one.
    Ten is both the page size and, on a one-page board, the whole board, so a
    short page is the ordinary last page here; and a portal that ignores
    `jobOffset` serves page one forever without ever returning an empty one.
    That is the iCIMS rule, and it is the one that catches both.
    """
    base = f"https://{token}"
    markup, path = None, None
    for candidate in AVATURE_LIST_PATHS:
        try:
            markup = http.get_text(f"{base}{candidate}", timeout=25, retries=2)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        if _avature_cards(markup):
            path = candidate
            break
    if path is None:
        # No list page under any known name. Raised rather than returned empty
        # for the `sites.py` reason: a renamed portal and a firm that is not
        # hiring are opposite facts that must not look alike.
        raise ValueError(f"no Avature job list at {token}")

    jobs: list[Job] = []
    seen: set[str] = set()
    for page in range(_AVATURE_PAGES):
        if page:
            markup = http.get_text(
                f"{base}{path}?jobOffset={page * _AVATURE_PAGE}", timeout=25, retries=2
            )
        fresh = 0
        for chunk in _avature_cards(markup):
            match = _AVATURE_JOB.search(chunk)
            if match is None:
                continue
            href, job_id, title = match.group(1), match.group(2), _text(match.group(3))
            if job_id in seen or not title:
                continue
            seen.add(job_id)
            fresh += 1
            # The first span is the place; the ones after it are the tenant's
            # own facets -- function, then experience level for this tenant.
            # Only the first two are read, and neither is invented: a card
            # carrying one span has a location and no department.
            spans = [_text(s) for s in _AVATURE_SPAN.findall(chunk)]
            spans = [s for s in spans if s]
            jobs.append(
                Job(
                    ats="avature",
                    token=token,
                    job_id=job_id,
                    title=title,
                    url=urllib.parse.urljoin(base, html.unescape(href)),
                    location=spans[0] if spans else None,
                    department=spans[1] if len(spans) > 1 else None,
                )
            )
        if not fresh:
            break
    return jobs


# Oracle asks for the page size inside a `finder` expression rather than as a
# query parameter, so the whole thing is one opaque-looking string. 200 is
# comfortably served -- a request for 500 came back with the board's true 139
# rather than an error -- but it is kept at 200 because a page size a vendor
# merely tolerates is the kind of thing that starts returning an empty array
# with HTTP 200 one day, which is the Workday trap two hundred lines up.
_ORACLE_PAGE = 200
_ORACLE_PAGES = 1_000
# How much of a board one walk may lose to postings closing while it runs,
# before the shortfall stops reading as churn and starts reading as truncation.
_ORACLE_CHURN = 0.02


def oracle_hcm(token: str) -> list[Job]:
    """Oracle Fusion Recruiting. `token` is `podhost|siteNumber` -- see `ats.py`.

    Danske Bank is here, with 139 live postings, and it was tier B: nothing in
    this project recognised Oracle at all until a roster measurement asked why
    a Copenhagen bank produced no jobs.

    **`TotalJobsCount` is trustworthy here, and is still not the stop
    condition.** Oracle reports the true total on every page including one past
    the end, so it does not have Workday's `total: 0` trap -- but the rule this
    project settled on after that trap is to page until a short page and treat
    the advertised total as a *check* rather than a bound, which is also what
    `jobvite` does with its "1-50 of 73" line. So the total is compared against
    what arrived and a mismatch is raised, which is the loud failure; the
    silent one would be believing it.

    **`PostingEndDate` is a published closing date**, so it is mapped. Danske's
    tenant leaves it null on every row, which costs nothing -- the rule is that
    a deadline is taken when a source states one as a field and is never mined
    out of a description.
    """
    host, _, site = token.partition("|")
    if not host or not site:
        raise ValueError(
            f"oracle_hcm token {token!r} is not podhost|siteNumber -- re-run `ats`"
        )
    origin = f"https://{host}"
    jobs: list[Job] = []
    advertised: int | None = None
    seen_page: str | None = None
    for page in range(_ORACLE_PAGES):
        finder = (
            f"findReqs;siteNumber={site},limit={_ORACLE_PAGE},"
            f"offset={page * _ORACLE_PAGE},sortBy=POSTING_DATES_DESC"
        )
        payload = _json(
            f"{origin}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            "?onlyData=true&expand=requisitionList.secondaryLocations"
            f"&finder={urllib.parse.quote(finder, safe=';,=')}"
        )
        items = payload.get("items") or []
        if not items:
            break
        block = items[0]
        if advertised is None:
            advertised = block.get("TotalJobsCount")
        postings = block.get("requisitionList") or []
        # **Stop on an empty page, never on a short one.** Oracle serves the
        # occasional 199-row page in the middle of a board -- measured on
        # Kotak's tenant, where offset 3,000 hands back 199 and offset 3,200
        # hands back a full 200 -- so a short-page stop ends the walk wherever
        # one lands. That truncated Kotak at 3,199 of 9,959 and Tata Capital at
        # 1,599 of 5,542, and both counts are the round number a cap leaves
        # behind. This is the Jobbsafari lesson in a second format: the real
        # last page is the empty one, and past the end Oracle answers with a
        # block whose `requisitionList` is empty and whose total reads 0.
        if not postings:
            break
        # With the short-page stop gone, a tenant that ignores `offset` would
        # serve page one until the page bound -- 1,000 requests and 200,000
        # duplicate rows. Workday needed the same guard for the same reason.
        this_page = "|".join(str(job.get("Id") or "") for job in postings)
        if this_page == seen_page:
            break
        seen_page = this_page
        for job in postings:
            job_id = str(job.get("Id") or "")
            if not job_id:
                continue
            jobs.append(
                Job(
                    ats="oracle_hcm",
                    token=token,
                    job_id=job_id,
                    title=job.get("Title") or "",
                    url=f"{origin}/hcmUI/CandidateExperience/en/sites/{site}/job/{job_id}",
                    location=job.get("PrimaryLocation"),
                    department=job.get("Department") or job.get("JobFamily"),
                    posted_at=job.get("PostedDate"),
                    deadline=job.get("PostingEndDate"),
                    description=_text(job.get("ShortDescriptionStr")),
                )
            )
    # The board states its own size. A board that says 1,295 and hands over 800
    # is what a page cap looks like from the outside, and nothing else would
    # say so -- this is the check that caught Jobvite's missing slash.
    #
    # **It is a shortfall check and not an equality check, because a large
    # board changes underneath a walk that takes minutes.** BNY advertises
    # 1,390 and hands over 1,387: three requisitions closed between the first
    # page and the last, and raising on that threw away 1,387 real postings --
    # the guard against silent truncation deleting a board outright, which is
    # the failure it exists to prevent, one direction over. `_ORACLE_CHURN` is
    # what one walk can lose to that; anything wider is our paging.
    if advertised is not None and len(jobs) < advertised * (1 - _ORACLE_CHURN):
        raise ValueError(
            f"oracle_hcm/{token}: board advertises {advertised} postings, read {len(jobs)}"
        )
    return jobs


# ADP serves 20 requisitions per request and caps it there: `$top` is accepted
# and ignored, so the only way through a board is `$skip`. `meta.totalNumber`
# states the true size on every page, and it is the check rather than the stop
# condition -- which is how the truncation was caught in the first place. Five
# boards raised "advertises 174, read 20" on the first run of this reader,
# which is exactly the round-number shape a cap leaves behind.
_ADP_PAGE = 20
_ADP_PAGES = 500
def _adp_place(requisition: dict) -> str | None:
    """The most specific location ADP's list endpoint states for a posting.

    City, region and country where they are filled in; on most boards only
    `nameCode.shortName` is, and it arrives space-padded (" US").
    """
    for place in requisition.get("requisitionLocations") or []:
        if not isinstance(place, dict):
            continue
        address = place.get("address") or {}
        region = (address.get("countrySubdivisionLevel1") or {}).get("codeValue")
        parts = [
            (address.get("cityName") or "").strip(),
            (region or "").strip(),
            ((place.get("nameCode") or {}).get("shortName") or "").strip(),
        ]
        readable = ", ".join(dict.fromkeys(p for p in parts if p))
        if readable:
            return readable
    return None


def adp(token: str) -> list[Job]:
    """ADP Workforce Now recruitment. 19 domains in a tier-B sample carried it.

    The public endpoint is
    `/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions?cid={guid}`
    and the `cid` is the whole token -- it is what the careers page embeds and
    the only identifier the API accepts.

    **`meta.links` looks like a location map and is not one.** It carries a
    `LOCATION` schema whose `payLoadArguments` pair an id with a readable place
    -- "Hong Kong - Hong Kong, Wanchai, Hong Kong Island, HK" -- and joining it
    to `itemID` produces a location for every posting. The ids are *location*
    ids and the join matches nothing: it is the board's filter facet, the list
    of places you may search by, not where any particular job is. A wrong
    location is worse than none here, because the board gates on geography.

    So the location is read from the requisition, where it is real but coarse:
    `nameCode.shortName` is often just a country, and `address.cityName` is
    empty on every board sampled. A country is enough for the gate to place a
    posting in the semi-target US or reject it as off-location; `unknown`
    survives the gate anyway, so the failure direction is safe.
    """
    jobs: list[Job] = []
    seen: set[str] = set()
    advertised: int | None = None
    for page in range(_ADP_PAGES):
        # `$skip=0` is not the same request as sending no `$skip` at all -- it
        # returns 19 rows where the bare URL returns 20, which is enough to
        # make a short-page stop rule end the walk on the first page.
        skip = f"&$skip={page * _ADP_PAGE}" if page else ""
        payload = _json(
            "https://workforcenow.adp.com/mascsr/default/careercenter/public/events"
            f"/staffing/v1/job-requisitions?cid={urllib.parse.quote(token)}{skip}"
        )
        requisitions = payload.get("jobRequisitions") or []
        if advertised is None:
            advertised = (payload.get("meta") or {}).get("totalNumber")
        fresh = 0
        for requisition in requisitions:
            job_id = str(requisition.get("itemID") or "")
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            fresh += 1
            jobs.append(
                Job(
                    ats="adp",
                    token=token,
                    job_id=job_id,
                    title=_text(requisition.get("requisitionTitle")) or "",
                    url=(
                        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment"
                        f"/recruitment.html?cid={token}&jobId={job_id}"
                    ),
                    location=_adp_place(requisition),
                    posted_at=requisition.get("postDate"),
                    description=_text(requisition.get("requisitionDescription")),
                )
            )
        # Stop when a page adds nothing new, not when it comes back short.
        # ADP's page size is not stable -- 20 without `$skip`, 19 with -- so a
        # short-page rule ends the walk one page in. "Adds nothing new" also
        # catches a tenant that ignores `$skip` and serves page one forever,
        # which is the rule Workday and iCIMS each needed.
        if not requisitions or not fresh:
            break
    if isinstance(advertised, int) and advertised > len(jobs):
        raise ValueError(
            f"adp/{token}: board advertises {advertised} postings, read {len(jobs)}"
        )
    return jobs


_UKG_PAGE = 100
_UKG_PAGES = 200

# UKG serves its tenants from two hosts and a tenant lives on exactly one of
# them -- `recruiting2` answers 404 for a `recruiting` board and the reverse.
# The same two-host trap as Workday's `myworkdayjobs.com`/`myworkdaysite.com`,
# and it silently emptied eight boards: every failing token's own evidence said
# `recruiting2` while this reader addressed `recruiting` unconditionally.
# Which host a tenant is on is not derivable from the code, so it is asked.
_UKG_HOSTS = ("recruiting.ultipro.com", "recruiting2.ultipro.com")


def _ukg_origin(code: str, board: str) -> str:
    """Which of UKG's two hosts this tenant is on, asked rather than guessed.

    A 404 here is the host being wrong, not the board being gone: the pool is
    disjoint, so the second host is tried and the first HTTP error that is not
    a 404 is raised as itself. If neither answers, the last failure stands --
    a board that has really gone must still be loud.
    """
    failure: urllib.error.HTTPError | None = None
    for host in _UKG_HOSTS:
        origin = f"https://{host}/{code}/JobBoard/{board}"
        try:
            http.get(f"{origin}/", timeout=25, retries=1)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            failure = exc
            continue
        return origin
    raise failure if failure else ValueError(f"ukg/{code}: no host answered")


def ukg(token: str) -> list[Job]:
    """UKG Pro Recruiting, formerly UltiPro. `token` is `code|boardGuid`.

    Both halves are needed and neither works alone: the code is the customer's
    short name in the path (`FIN1008FICT`) and the GUID names one job board on
    it, the same shape as Oracle's `podhost|siteNumber`.

    A JSON POST to `JobBoardView/LoadSearchResults`, which is the only public
    surface -- the board page itself is 443 KB of Knockout templates carrying
    no posting. `totalCount` is honest and is used as the check.
    """
    code, _, board = token.partition("|")
    if not code or not board:
        raise ValueError(f"ukg token {token!r} is not code|boardGuid -- re-run `ats`")
    origin = _ukg_origin(code, board)
    jobs: list[Job] = []
    advertised: int | None = None
    for page in range(_UKG_PAGES):
        body = json.dumps(
            {
                "opportunitySearch": {
                    "Top": _UKG_PAGE,
                    "Skip": page * _UKG_PAGE,
                    "QueryString": "",
                    "OrderBy": [],
                }
            }
        ).encode()
        payload = json.loads(
            http.post_json(
                f"{origin}/JobBoardView/LoadSearchResults", body, timeout=25, retries=2
            ).decode("utf-8")
        )
        if advertised is None:
            advertised = payload.get("totalCount")
        opportunities = payload.get("opportunities") or []
        for opportunity in opportunities:
            job_id = str(opportunity.get("Id") or "")
            if not job_id:
                continue
            # `Locations` is a list of objects and the readable form is
            # `LocalizedDescription`; a board with two sites lists both.
            places = [
                place.get("LocalizedDescription")
                for place in (opportunity.get("Locations") or [])
                if isinstance(place, dict) and place.get("LocalizedDescription")
            ]
            jobs.append(
                Job(
                    ats="ukg",
                    token=token,
                    job_id=job_id,
                    title=_text(opportunity.get("Title")) or "",
                    url=f"{origin}/OpportunityDetail?opportunityId={job_id}",
                    location=", ".join(dict.fromkeys(places)) or None,
                    department=_text(opportunity.get("JobCategoryName")),
                    posted_at=opportunity.get("PostedDate"),
                    description=_text(opportunity.get("BriefDescription")),
                )
            )
        if len(opportunities) < _UKG_PAGE:
            break
    if isinstance(advertised, int) and advertised > len(jobs):
        raise ValueError(
            f"ukg/{token}: board advertises {advertised} postings, read {len(jobs)}"
        )
    return jobs


# Teamtailor's own RSS extension. The plain JSON feed at `/jobs.json` is
# tidier, but it carries no location and no department, and this project ranks
# on geography -- so the feed with the extra fields is the one worth parsing.
_TT = "{https://teamtailor.com/locations}"


def _tt_location(item: ElementTree.Element) -> str | None:
    """City and country from a `tt:locations` block, which is often empty."""
    parts: list[str] = []
    for location in item.iterfind(f"{_TT}locations/{_TT}location"):
        for tag in ("name", "city", "country"):
            value = (location.findtext(f"{_TT}{tag}") or "").strip()
            if value and value not in parts:
                parts.append(value)
    return ", ".join(parts) or None


def teamtailor(token: str) -> list[Job]:
    """Teamtailor's public RSS.

    Teamtailor is why the Nordic group was fingerprinted in the first place:
    it is what Stockholm and Copenhagen mid-market firms hire through, and no
    generic scraper covers it. An empty `<channel>` is a real answer here --
    a firm with no openings -- so zero items is not treated as a failure.
    """
    # A token carrying a dot is already a hostname: the board is served from
    # the firm's own domain, `careers.lynxhedge.se`, and `{token}.teamtailor
    # .com` would be nonsense. See `_VENDOR_ASSETS` in `ats.py`.
    host = token if "." in token else f"{token}.teamtailor.com"
    body = http.get(f"https://{host}/jobs.rss", timeout=25, retries=2)
    channel = ElementTree.fromstring(body).find("channel")
    if channel is None:
        raise ValueError(f"teamtailor board {token!r} served no channel")

    jobs: list[Job] = []
    for item in channel.iterfind("item"):
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or "").strip()
        if not guid and not link:
            continue
        jobs.append(
            Job(
                ats="teamtailor",
                token=token,
                job_id=guid or link,
                title=(item.findtext("title") or "").strip(),
                url=link or None,
                location=_tt_location(item),
                department=(item.findtext(f"{_TT}department") or "").strip() or None,
                posted_at=(item.findtext("pubDate") or "").strip() or None,
                description=_text(item.findtext("description")),
            )
        )
    return jobs


# Join. Its public API answers 422 to every `page`/`pageSize` combination
# tried, which is what closed it -- and the company page carries the whole
# list as a JSON island, `"jobs":{"items":[...]}`, unescaped and beside its own
# pagination block. The same shape as DRW's `__NEXT_DATA__` and Jobylon's
# widget: **when a vendor's API refuses, read the page the customer publishes.**
_JOIN_ISLAND = '"jobs":'
_JOIN_PAGES = 400


def join(token: str) -> list[Job]:
    """Join. `token` is the company slug in `join.com/companies/{token}`.

    Paged with `?page=N`, five at a time, and the island states both
    `pageCount` and `total`. The walk runs to `pageCount`, which is the
    vendor's own statement of how many pages exist.

    **`total` is checked with one page of slack, and that is measured rather
    than generous.** Wallee's island reports `total: 4` with `pageCount: 1` and
    lists three -- a posting the vendor counts and does not publish -- while
    Carhartt's 47 arrive exactly. A truncation is short by pages, not by one.
    """
    jobs: list[Job] = []
    seen: set[str] = set()
    advertised: int | None = None
    per_page = 5
    pages = 1
    page = 1
    while page <= min(pages, _JOIN_PAGES):
        body = http.get_text(
            f"https://join.com/companies/{token}?page={page}", timeout=25, retries=2
        )
        at = body.find(_JOIN_ISLAND)
        if at < 0:
            raise ValueError(f"join board {token!r} carries no job list")
        island, _ = json.JSONDecoder().raw_decode(body, at + len(_JOIN_ISLAND))
        pagination = island.get("pagination") or {}
        if advertised is None:
            advertised = pagination.get("total")
            pages = pagination.get("pageCount") or 1
            per_page = pagination.get("perPage") or per_page
        items = island.get("items") or []
        if not items:
            break
        for item in items:
            job_id = str(item.get("id") or "")
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            slug = item.get("idParam")
            city = item.get("city") or {}
            place = [city.get("cityName"), city.get("countryName")]
            jobs.append(
                Job(
                    ats="join",
                    token=token,
                    job_id=job_id,
                    title=_text(item.get("title")) or "",
                    url=f"https://join.com/companies/{token}/{slug}" if slug else None,
                    location=", ".join(p for p in place if p) or None,
                    department=_text((item.get("category") or {}).get("name")),
                    posted_at=item.get("createdAt"),
                )
            )
        page += 1
    if isinstance(advertised, int) and advertised - len(jobs) > per_page:
        raise ValueError(
            f"join/{token}: board advertises {advertised} postings, read {len(jobs)}"
        )
    return jobs


# Eightfold. **It was recorded as closed and the truth is per tenant**: the
# note says `/api/apply/v2/jobs` answers 403, which it does on Morgan Stanley's
# tenant and on NAB's -- and Vale's answers 200 with 193 positions. A vendor
# refusing one customer's board is not the vendor being shut, and writing it
# down as "closed" stopped anyone asking a second tenant.
#
# `count` is the board's own size and is the check. The `domain=` parameter the
# vendor's own page sends is **not** required -- measured against Millennium's
# tenant with it, with it empty and without it, and all three answer 219 -- so
# the token stays the tenant label the host pattern already captures rather
# than becoming a compound nothing has to keep in step.
# **Eightfold ignores `num` and serves ten**, whatever is asked for -- the
# same trap MAS's register sets one country over. Paging with a stride the
# server does not honour skipped forty postings in every fifty, and the
# advertised-total check is what said so rather than anything in the response.
_EIGHTFOLD_PAGE = 10
_EIGHTFOLD_PAGES = 1_000


def eightfold(token: str) -> list[Job]:
    """Eightfold. `token` is the tenant, which is the subdomain of its board.

    **Millennium is here**, as `mlp` -- 219 postings, 70 in New York, 31 in
    Hong Kong and 15 in Singapore, and `Quantitative Researcher`,
    `Portfolio Researcher` and `Deep Learning Quantitative Researcher` among
    them. It sat behind the note calling this vendor closed.
    """
    jobs: list[Job] = []
    advertised: int | None = None
    seen: set[str] = set()
    for page in range(_EIGHTFOLD_PAGES):
        payload = _json(
            f"https://{token}.eightfold.ai/api/apply/v2/jobs"
            f"?start={page * _EIGHTFOLD_PAGE}"
            f"&num={_EIGHTFOLD_PAGE}&query=&sort_by=relevance"
        )
        positions = payload.get("positions") or []
        if advertised is None:
            advertised = payload.get("count")
        if not positions:
            break
        fresh = 0
        for position in positions:
            job_id = str(position.get("id") or "")
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            fresh += 1
            # `locations` is the full list and `location` the summary. The
            # list is preferred and joined, because the board's geography
            # dimension is multi-valued and a summary of "Brazil" loses the
            # city that was also published.
            places = [p for p in (position.get("locations") or []) if isinstance(p, str)]
            jobs.append(
                Job(
                    ats="eightfold",
                    token=token,
                    job_id=job_id,
                    title=_text(position.get("name")) or "",
                    url=position.get("canonicalPositionUrl"),
                    location=", ".join(dict.fromkeys(places))
                    or _text(position.get("location")),
                    department=_text(position.get("department")),
                    description=_text(position.get("job_description")),
                )
            )
        if not fresh:
            break
    if isinstance(advertised, int) and advertised > len(jobs):
        raise ValueError(
            f"eightfold/{token}: board advertises {advertised} postings, read {len(jobs)}"
        )
    return jobs


# Jobylon, the Nordic ATS. Its board is an AngularJS widget, which is why it
# was recorded as unreadable -- and the widget page it embeds carries the whole
# list as a JavaScript array literal, `JBL.embed_v2['jobs']`, rendered
# server-side. Read the page the embed loads, not the page that embeds it.
#
# **The token is the customer's numeric id**, which is the only thing the embed
# URL carries: `jobylon.com/jobs/companies/2551/embed/v2/`. That is why
# `fingerprint`'s "a purely numeric token is not a board" rule has an exemption
# for this vendor -- the rule exists because `jobs.lever.co/500` on an error
# page produced the board "500", and here the digits are the board.
#
# Parsed field by field rather than as JSON, because it is not JSON: single
# quotes, trailing commas and unquoted keys. Each field is read within one
# record's span, so a missing one cannot borrow its neighbour's value.
# **A record ends where the next one begins, not at the next `}`.** Two of the
# fields are nested objects -- `klass` and `layers` -- so a non-greedy run to
# the first closing brace stops inside the record, and everything after it
# reads as absent. `locations_text` and `function` are both past that point,
# which is every place name on the board.
_JOBYLON_RECORD = re.compile(r"\n\s+id: '(\d+)',")
_JOBYLON_FIELD = "\n\\s+{name}: '((?:[^'\\\\]|\\\\.)*)'"


def _jobylon_field(name: str, block: str) -> str | None:
    found = re.search(_JOBYLON_FIELD.format(name=name), block)
    return _text(found.group(1).replace("\\'", "'")) if found else None


def jobylon(token: str) -> list[Job]:
    """Jobylon. `token` is the customer's numeric company id.

    **The published dates are deliberately not mapped.** `published_date` and
    `to_date` are real fields, and the widget renders them in the tenant's own
    language -- `13. syyskuuta 2026` on a Finnish board. Turning localised
    month names into a date to hand a deadline-ordered board is the shape of
    mistake this project refuses everywhere else: a wrong closing date nails
    the wrong card to the top of the page for weeks. The place is what matters
    here and it arrives as plain text.
    """
    body = http.get_text(
        f"https://cdn.jobylon.com/jobs/companies/{token}/embed/v2/", timeout=25, retries=2
    )
    start = body.find("JBL.embed_v2['jobs']")
    if start < 0:
        raise ValueError(f"jobylon board {token!r} served no job list")

    listing = body[start:]
    found = list(_JOBYLON_RECORD.finditer(listing))
    jobs: list[Job] = []
    for index, match in enumerate(found):
        job_id = match.group(1)
        end = found[index + 1].start() if index + 1 < len(found) else len(listing)
        block = listing[match.end() : end]
        path = _jobylon_field("url", block)
        jobs.append(
            Job(
                ats="jobylon",
                token=token,
                job_id=job_id,
                title=_jobylon_field("title", block) or "",
                url=f"https://jobylon.com{path}" if path else None,
                location=_jobylon_field("locations_text", block),
                department=_jobylon_field("function", block),
                employer=_jobylon_field("company", block),
            )
        )
    return jobs


# SAP SuccessFactors' RMK career site, served from the firm's own hostname --
# the `careers.lynxhedge.se` shape a third time, and the reason the token is a
# host rather than a label.
#
# **This was recorded as closed and the note was about a different surface.**
# What was tested is the `?company=pfapensionP` form, which really does answer
# 206 KB of shell with no job id. The firms here run RMK on their own host and
# it renders its list server-side: an ordinary table of `<tr class="data-row">`
# with the title, the place and the requisition id in it. Janus Henderson,
# Carnegie, Fitch, Clearstream, Eurex, Hang Seng and Nomura's Instinet were
# all behind that note.
#
# Parsed as blocks rather than one regex over the page, because every row is
# rendered twice -- once for desktop and once for phones -- so a global scan
# for `jobLocation` finds 51 places for 25 postings and pairs them wrongly.
#
# **RMK ships two list layouts and a firm may run either**: a table of
# `<tr class="data-row">`, which Janus Henderson serves, and a list of
# `<li class="job-tile job-id-N">`, which Carnegie serves. They agree on the
# anchor -- `jobTitle-link`, carrying `/job/{slug}/{id}/` -- and on nothing
# else, so the row split and the place take one alternation each. Reading only
# the table found 81 postings at one firm and none at the other, which is what
# a layout gap looks like from outside: a board that answers 200 and is empty.
# **One row selector for both layouts**, where there used to be an alternation
# written after a card board read as empty: RMK ships a table of
# `<tr class="data-row">`, which Janus Henderson and Nomura serve, and a list of
# `<li class="job-tile job-id-N">`, which Carnegie and Scania serve. To a
# pattern those agree on nothing; to a selector they are two names for a row.
_SF_ROW = "tr.data-row, li.job-tile"
# The anchor, which both layouts do agree on. Three things the pattern this
# replaced had to spell out and a selector gets for nothing: the class may
# carry a second name beside it (`jobTitle-link fontcolor70e5...` at Scania),
# the attribute order varies between tenants and so needed the whole pattern
# written twice, and the `href` arrives **decoded** -- Nomura publishes
# `Risk-&amp;-Control-Specialist` and the regex stored the escape verbatim into
# 849 live URLs.
_SF_LINK = "a.jobTitle-link[href]"
# The place. Tenants render it two ways and repeat it for responsive layouts --
# `jobLocation`, `jobLocation sort`, `jobLocation visible-phone`, all three
# carrying the same string on every one of Nomura's 100 rows, measured. The
# old pattern wanted `<span class="jobLocation">` exactly and so read only the
# middle one; a class is a member of a list here.
_SF_PLACE = '.jobLocation, [id$="-desktop-section-city-value"]'
_SF_DEPARTMENT = "span.jobDepartment"
# The page states its own size, and the two layouts word it differently --
# `Results 1 - 25 of <b>81</b>` and `Showing 1 to 15 of 764 Jobs`. This is the
# check every reader here is held to, and the one that caught Jobvite's slash.
#
# **Read off the page's text rather than its markup, because on one layout the
# markup interrupts the sentence.** The pattern this replaced required the
# words and the number to be separated by whitespace only, and Nomura splits
# them across three elements -- `Results </span>1 &#8211; 100<span> ... of
# <b>513</b>` -- so it matched nothing, `advertised` stayed None, and **a
# 513-posting board ran with no shortfall guard at all**. That is the shape of
# silence this project is least able to see: not a failure, an absent check.
# Stripping tags first makes both layouts one sentence and one pattern, which
# is the same "strip tags, then read" rule `parsing.text` exists for.
_SF_TOTAL = re.compile(
    r"(?:Results?|Showing)\s+[\d,]+\s*(?:to|through|[–—-])\s*[\d,]+"
    r"\s+of\s+([\d,]+)",
    re.I,
)
# **The stride is what the server returned, not a number we chose.** RMK's page
# size is per tenant -- Janus Henderson serves 25 and Scania 15 -- so stepping
# `startrow` by a constant skipped ten postings in every twenty-five of
# Scania's 758. That is the Eightfold trap in a third format: paging with a
# stride the server does not honour, caught by the advertised total and by
# nothing else. `_SF_PAGE` is only the first guess, and a wrong one costs one
# duplicate page rather than a truncation.
_SF_PAGE = 25
_SF_PAGES = 400


def _sf_field(block, selector: str) -> str | None:
    """The text of the first node in `block` matching `selector`, or None."""
    found = block.select_one(selector)
    return _text(found.decode_contents()) if found is not None else None


def _sf_job_id(href: str) -> str | None:
    """The requisition id out of a posting path, or None if it is not one.

    `/job/{slug}/{id}/`, optionally under a tenant prefix -- Clarksons serves
    its board from `/Clarksons/job/...`, and reading only the bare form found 0
    of the 33 postings that page advertises. The id is the last numeric segment
    rather than a position, so a prefix cannot shift it.
    """
    if "/job/" not in href:
        return None
    digits = [part for part in href.split("?")[0].split("/") if part.isdigit()]
    return digits[-1] if digits else None


def successfactors(token: str) -> list[Job]:
    """SuccessFactors RMK. `token` is the host the firm serves the board from.

    Paging is `startrow`, 25 at a time, which the site's own pagination links
    spell out. Stops on a page that adds no new requisition id: a site
    ignoring `startrow` serves page one forever, and no empty-page test catches
    that -- the rule Workday, ADP and both iCIMS readers each needed.
    """
    jobs: list[Job] = []
    seen: set[str] = set()
    advertised: int | None = None
    startrow = 0
    for _ in range(_SF_PAGES):
        body = http.get_text(
            f"https://{token}/search/?q=&startrow={startrow}", timeout=25, retries=2
        )
        if advertised is None:
            total = _SF_TOTAL.search(_text(body) or "")
            advertised = int(total.group(1).replace(",", "")) if total else None
        fresh = 0
        blocks = _soup(body).select(_SF_ROW)
        startrow += len(blocks) or _SF_PAGE
        for block in blocks:
            link = block.select_one(_SF_LINK)
            if link is None:
                continue
            job_id = _sf_job_id(link["href"])
            if job_id is None or job_id in seen:
                continue
            seen.add(job_id)
            fresh += 1
            jobs.append(
                Job(
                    ats="successfactors",
                    token=token,
                    job_id=job_id,
                    title=_text(link.decode_contents()) or "",
                    url=f"https://{token}{link['href']}",
                    location=_sf_field(block, _SF_PLACE),
                    department=_sf_field(block, _SF_DEPARTMENT),
                )
            )
        if not fresh:
            break
    if isinstance(advertised, int) and advertised > len(jobs):
        raise ValueError(
            f"successfactors/{token}: board advertises {advertised} postings,"
            f" read {len(jobs)}"
        )
    return jobs


# iCIMS' newer career-site product, formerly Jibe, and a wholly different
# surface from the classic portal above: the firm fronts it on its own
# hostname and the postings come from a plain JSON API rather than list HTML.
# It is where the classic portals have been going -- twelve of 36 iCIMS boards
# here had already migrated, Principal, AXA and SiriusXM among them, and each
# left behind the 150-byte redirect stub `_icims_origin` now refuses.
#
# **The token is the host**, the `careers.lynxhedge.se` shape, because there is
# no vendor hostname to take a label from. `/api/jobs` sits at the host root
# even where the board itself is under a path (`careers.bayview.com/bam/jobs`,
# `www.related.jobs/careers-home/jobs`), so the path is not part of the token.
#
# The endpoint was read off the site's own `featured-jobs.js` rather than
# guessed, which is the rule job-room.ch's 401 established: `/api/jobs?limit=100`,
# verbatim, is what the page asks for.
_ICIMS_CS_PAGE = 100
_ICIMS_CS_PAGES = 200


def icims_cs(token: str) -> list[Job]:
    """iCIMS career sites. `token` is the host the firm serves the board from.

    `totalCount` is the board's own size and is honest -- 117 for Principal,
    1,508 for AXA -- so it is the check rather than the stop condition, the
    same contract Oracle and Jobvite are held to. Note `count` is a different
    number and is not it: Principal reports `count: 72` against 117 postings.

    Paging is `page=N`, one-based. `limit` above 100 is refused outright, which
    is loud rather than silent and so needs no assertion of its own.
    """
    jobs: list[Job] = []
    advertised: int | None = None
    seen: set[str] = set()
    for page in range(1, _ICIMS_CS_PAGES + 1):
        payload = _json(
            f"https://{token}/api/jobs?limit={_ICIMS_CS_PAGE}&page={page}"
        )
        listed = payload.get("jobs") or []
        if advertised is None:
            advertised = payload.get("totalCount")
        if not listed:
            break
        fresh = 0
        for entry in listed:
            job = entry.get("data") or {}
            job_id = str(job.get("req_id") or job.get("slug") or "")
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            fresh += 1
            slug = job.get("slug")
            jobs.append(
                Job(
                    ats="icims_cs",
                    token=token,
                    job_id=job_id,
                    title=_text(job.get("title")) or "",
                    # `apply_url` is the vendor's login page for the
                    # requisition; the readable ad is the career site's own
                    # job path. Neither is invented: a posting missing both
                    # gets no URL rather than a link to the board's front door.
                    url=f"https://{token}/careers-home/jobs/{slug}"
                    if slug
                    else job.get("apply_url"),
                    location=_text(job.get("full_location"))
                    or _text(job.get("location_name")),
                    department=_text(job.get("category_name"))
                    or _text((job.get("categories") or [{}])[0].get("name")),
                    posted_at=job.get("posted_date") or job.get("create_date"),
                    description=_text(job.get("description")),
                )
            )
        # A site ignoring `page` serves page one forever, which no empty-page
        # test catches -- the rule Workday, ADP and iCIMS each needed.
        if not fresh:
            break
    if isinstance(advertised, int) and advertised > len(jobs):
        raise ValueError(
            f"icims_cs/{token}: board advertises {advertised} postings, read {len(jobs)}"
        )
    return jobs


# Emply's board is server-rendered chrome around a client-side list, which is
# why it was recorded as unreadable: the page is 209 KB carrying no job id and
# every guessed feed path serves the same shell. The list is one POST, and the
# page names it -- `/api/integration/vacancy/get-page`, in an inline script,
# beside the exact request body it sends. **Read the page's own call rather
# than guessing paths**, which is the lesson job-room.ch's 401 taught.
#
# The one per-tenant value is `sectionId`, a GUID naming the vacancy list
# section of that career site. It is in the same script, so it is taken from
# there rather than guessed; a career site has several sections and only this
# one answers with `vacancies`.
_EMPLY_SECTION = re.compile(r"sectionId:\s*'([0-9a-f-]{36})'")
_EMPLY_LANG = re.compile(r"languageKey\s*=\s*'([a-zA-Z-]{2,7})'")
_EMPLY_PAGE = 100
_EMPLY_PAGES = 100


def emply(token: str) -> list[Job]:
    """Emply, the Danish ATS. `token` is the customer label before `.career`.

    `deadline` is mapped, and it was checked before it was: across the six
    boards here 54 of 95 postings carry one and the gaps from publication run
    14 to 45 days with no value repeating more than six times. That is an
    employer typing a date, not job-room.ch's dropdown -- where 81% sat exactly
    30 days out, which is what a default looks like and why that field is
    refused.
    """
    origin = f"https://{token}.career.emply.com"
    page = http.get_text(f"{origin}/open-positions", timeout=25, retries=2)
    section = _EMPLY_SECTION.search(page)
    if not section:
        raise ValueError(f"emply board {token!r} names no vacancy section")
    language = _EMPLY_LANG.search(page)

    jobs: list[Job] = []
    advertised: int | None = None
    for offset in range(0, _EMPLY_PAGE * _EMPLY_PAGES, _EMPLY_PAGE):
        body = json.dumps(
            {
                "count": _EMPLY_PAGE,
                "filters": [],
                "langCode": language.group(1) if language else "en-GB",
                "offset": offset,
                "searchText": "",
                "sectionId": section.group(1),
                "sortByProjectDataId": "",
                "sortAscending": False,
                "light": False,
                "isJobAgent": False,
                "siteId": None,
            }
        ).encode()
        payload = json.loads(
            http.post_json(
                f"{origin}/api/integration/vacancy/get-page", body, timeout=25, retries=2
            ).decode("utf-8")
        )
        vacancies = payload.get("vacancies") or []
        if advertised is None:
            advertised = payload.get("count")
        if not vacancies:
            break
        for vacancy in vacancies:
            job_id = str(vacancy.get("id") or "")
            if not job_id:
                continue
            # The description is in the translation rather than on the record,
            # and a board with no English translation still has exactly one.
            translations = vacancy.get("translations") or []
            content = translations[0].get("content") if translations else None
            slug, short = vacancy.get("titleAsUrl"), vacancy.get("shortId")
            jobs.append(
                Job(
                    ats="emply",
                    token=token,
                    job_id=job_id,
                    title=_text(vacancy.get("title")) or "",
                    # The page builds this as `/ad/{titleAsUrl}/{shortId}`. A
                    # posting missing either piece gets no URL rather than a
                    # link to the board's front door -- the Workday `N
                    # Locations` rule, which is why 42 boards held one card
                    # each that opened a vendor's landing page.
                    url=f"{origin}/ad/{slug}/{short}" if slug and short else None,
                    location=_text(vacancy.get("location")),
                    department=_text(vacancy.get("department")),
                    posted_at=vacancy.get("published") or vacancy.get("created"),
                    deadline=vacancy.get("deadline"),
                    description=_text(content),
                )
            )
    # The board states its own size on every page, the same check Oracle and
    # Jobvite get. Emply's boards are small enough that a walk cannot lose a
    # posting to churn, so this is an equality-shaped check rather than a
    # tolerance.
    if isinstance(advertised, int) and advertised > len(jobs):
        raise ValueError(
            f"emply/{token}: board advertises {advertised} postings, read {len(jobs)}"
        )
    return jobs


def workday(token: str) -> list[Job]:
    """Workday CXS. `token` is `tenant|wdN|site[|host]` -- see `ats.py`.

    Two hosts serve the same CXS endpoint and address it differently. On
    `myworkdayjobs.com` the tenant is the subdomain; on `myworkdaysite.com` the
    subdomain is a bare `wdN` and the tenant appears only in the path. The
    optional fourth part names the second case, so every token written before
    it existed still means what it meant.
    """
    parts = token.split("|")
    if len(parts) not in (3, 4):
        raise ValueError(
            f"workday token {token!r} is not tenant|wdN|site[|host] -- re-run `ats`"
        )
    tenant, wd, site = parts[:3]
    host = parts[3] if len(parts) == 4 else "myworkdayjobs.com"

    # Asserted, not merely used. Raising the cap silently truncates every board
    # on some tenants and 400s on others; the regression test pins it here.
    assert _WORKDAY_MAX <= 20, "Workday rejects limit > 20"

    origin = (
        f"https://{wd}.{host}"
        if host == "myworkdaysite.com"
        else f"https://{tenant}.{wd}.{host}"
    )
    url = f"{origin}/wday/cxs/{tenant}/{site}/jobs"
    jobs: list[Job] = []
    seen_page: str | None = None
    for page in range(_WORKDAY_PAGES):
        body = json.dumps(
            {"limit": _WORKDAY_MAX, "offset": page * _WORKDAY_MAX, "searchText": ""}
        ).encode()
        payload = json.loads(
            http.post_json(url, body, timeout=25, retries=2).decode("utf-8")
        )
        postings = payload.get("jobPostings") or []
        # A tenant that ignores `offset` serves page one forever, which the
        # short-page rule never catches. Comparing against the previous page
        # stops it; upserts would dedupe the rows anyway, but the polling would
        # not stop until the page bound, and that is the run's whole budget.
        this_page = "|".join(job.get("externalPath", "") for job in postings)
        if postings and this_page == seen_page:
            break
        seen_page = this_page
        for job in postings:
            path = job.get("externalPath") or ""
            title = job.get("title") or ""
            # **A missing `externalPath` used to become a link to the whole
            # careers site, which is worse than no link at all.** The URL was
            # built unconditionally, so an entry without one produced
            # `{origin}/en-US/{site}` -- the board's own landing page, under
            # whatever title the entry carried. The reader found two on the
            # live board, at Nasdaq and Sun Life, and 42 boards held one each:
            # `job_id` empty, `title` empty, and a card that opens the
            # recruiting page instead of an advertisement.
            #
            # Neither half is dropped silently. **A posting with a title and no
            # path is kept with no URL** -- principle 4 says classification is a
            # read-time job and this is a posting, however badly Workday
            # published it. **An entry with neither is not a posting at all**
            # and inventing a row for it is the write-time mistake in its purest
            # form: nothing about it can ever be read, and it cannot be
            # re-fetched because there is no id to ask for.
            if not path and not title:
                continue
            jobs.append(
                Job(
                    ats="workday",
                    token=token,
                    job_id=path or title,
                    title=title,
                    url=f"{origin}/en-US/{site}{path}" if path else None,
                    location=job.get("locationsText"),
                    posted_at=job.get("postedOn"),
                )
            )
        # Stop on a short page. `total` is not usable: Workday reports 0 for it
        # on every page after the first, so trusting it caps each board at 20.
        if len(postings) < _WORKDAY_MAX:
            break
    return jobs


def _site(token: str) -> list[Job]:
    """Dispatch to `sites.py`. Imported late: `sites` imports `_text` from here."""
    from . import sites

    return sites.read(token)


EXTRACTORS: dict[str, Callable[[str], list[Job]]] = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workable": workable,
    "recruitee": recruitee,
    "bamboohr": bamboohr,
    "breezy": breezy,
    "icims": icims,
    "jobvite": jobvite,
    "varbi": varbi,
    "homerun": homerun,
    "personio": personio,
    "pinpoint": pinpoint,
    "hailey": hailey,
    "teamtailor": teamtailor,
    "workday": workday,
    "oracle_hcm": oracle_hcm,
    "adp": adp,
    "ukg": ukg,
    "avature": avature,
    "emply": emply,
    "icims_cs": icims_cs,
    "successfactors": successfactors,
    "jobylon": jobylon,
    "eightfold": eightfold,
    "join": join,
    # Layer 3C: firms with no ATS at all, read from their own website. One
    # entry here, dispatched by token -- see `sites.py` for why the list is
    # deliberately short.
    "site": _site,
}


def targets(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    placeholders = ",".join("?" * len(EXTRACTORS))
    return connection.execute(
        f"""
        SELECT domain, ats, token FROM ats_resolution
        WHERE tier = 'A' AND ats IN ({placeholders}) AND token IS NOT NULL
        ORDER BY ats, domain
        LIMIT ?
        """,
        (*EXTRACTORS, limit),
    ).fetchall()


def _poll(row) -> tuple[object, list, str | None]:
    """Fetch one board. Returns (row, postings, failure) -- never raises.

    Runs on a worker thread, so it touches the network and nothing else. The
    `sqlite3` connection stays on the calling thread: a connection is not
    shared safely across threads, and the writes are fast next to the fetches.
    """
    try:
        return row, EXTRACTORS[row["ats"]](row["token"]), None
    # One board with an unexpected payload must not abandon the rest -- the
    # same rule `fetch` follows for registries. Failures are returned and
    # printed rather than swallowed, so a broken format is still loud.
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError,
            AttributeError, TypeError, IndexError, TimeoutError, OSError) as exc:
        return row, [], f"{row['ats']}/{row['token']}: {type(exc).__name__} {exc}"


def run(
    connection: sqlite3.Connection, limit: int, workers: int = 12,
) -> tuple[int, int, list[str]]:
    """Pull postings for resolved boards. Returns (boards, jobs, failures).

    **Polled in parallel, and this is the one command that was not.** Every
    other network module here -- `ats`, `domains`, `pages`, `discover`,
    `bodies` -- has run on a thread pool for exactly this reason, and Layer 3
    was a plain serial loop over every resolved board. It is the slowest thing
    in the pipeline by a wide margin: a Workday board pages twenty postings at
    a time behind a one-second-per-host throttle, so State Street's 1,295
    openings alone are sixty-five sequential seconds, and there are hundreds of
    boards.

    Politeness is unchanged, which is what makes this safe rather than merely
    faster. `http._throttle` books its interval **per host** under a lock, so
    two workers on two different boards never share a slot, and two workers on
    the same host still queue one second apart. The comment on `_last_hit`
    already made this argument for `domains`; nothing about it was specific to
    domain probing.
    """
    rows = targets(connection, limit)
    total = 0
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for row, jobs, failure in pool.map(_poll, rows):
            if failure:
                failures.append(failure)
                continue
            if jobs:
                total += db.upsert_jobs(connection, row["domain"], jobs)
    return len(rows), total, failures
