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

from . import db, http
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


def _text(value: str | None) -> str | None:
    """Readable text from a fragment of markup.

    **Entities are decoded, and they were not.** The formats that hand over
    HTML rather than JSON hand over its escaping too, so Coeli's
    `Operativ chef för Business &amp; Risk Operations` arrived with the `&amp;`
    intact and folded to the token `amp` -- a word in no lexicon, sitting in
    the middle of a title, and `tagging.py` reads the title before anything
    else. Swedish is worse than the ampersand: this markup spells `ä` as
    `&#xE4;`, so a title could fold to something no needle matches at all,
    which is the same shape as the `fold` bug that silently disabled every
    Swedish rule in the file.
    """
    if not value:
        return None
    return " ".join(html.unescape(_TAGS.sub(" ", value)).split()) or None


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
        jobs.append(
            Job(
                ats="smartrecruiters",
                token=token,
                job_id=str(job["id"]),
                title=job.get("name") or "",
                url=ref.get("jobAd") or job.get("applyUrl"),
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
    payload = _json(f"https://{token}.bamboohr.com/careers/list")
    return [
        Job(
            ats="bamboohr",
            token=token,
            job_id=str(job["id"]),
            title=job.get("jobOpeningName") or "",
            url=f"https://{token}.bamboohr.com/careers/{job['id']}",
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
    for page in range(_ICIMS_PAGES):
        url = (
            f"https://careers-{token}.icims.com/jobs/search"
            f"?ss=1&in_iframe=1&pr={page}"
        )
        try:
            body = http.get_text(url, timeout=25, retries=2)
        except urllib.error.HTTPError as exc:
            # A board that has ended answers 404 on the first page. Anything
            # after that is a paging edge, not a failure worth losing the
            # postings already read for.
            if page == 0:
                raise
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
                    url=f"https://careers-{token}.icims.com/jobs/{job_id}/{slug}/job",
                )
            )
        # Stop when a page adds nothing. A portal that ignores `pr` serves page
        # one forever, and the empty-page test alone would never catch it.
        if not fresh:
            break
    return jobs


# Jobvite publishes no feed either -- `?format=rss` serves the careersite HTML
# and the v2 API wants a key -- but its careersite is a plain table, which is
# more than iCIMS gives. One row is a name cell and a location cell:
#
#   <td class="jv-job-list-name"><a href="/{token}/job/{id}">Title</a></td>
#   <td class="jv-job-list-location"> London, England </td>
#
# Parsed as two passes rather than one regex spanning both cells: a single
# pattern reaching from the anchor across to the location has to cross
# unbounded markup, which is the shape that stalled this project twice.
_JOBVITE_NAME = re.compile(
    r'jv-job-list-name["\'>][\s\S]{0,300}?/job/([A-Za-z0-9]{1,24})["\'][^>]{0,120}>'
    r'([^<]{1,200})</a>',
    re.I,
)
_JOBVITE_PLACE = re.compile(
    r'jv-job-list-location["\'][^>]{0,80}>([\s\S]{0,300}?)</td>', re.I
)
# "1-50 of 73". The board states its own size, which is the cheapest possible
# check that paging reached the end.
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

        names = _JOBVITE_NAME.findall(body)
        places = [
            " ".join(_TAGS.sub(" ", p).split()) for p in _JOBVITE_PLACE.findall(body)
        ]
        # Zipped only when the table is well formed. A mismatch means the
        # markup is not the shape assumed here, and a location silently paired
        # with the wrong posting sends the geography gate the wrong answer --
        # which deletes a posting rather than mis-ranking it.
        if len(places) != len(names):
            places = [None] * len(names)

        fresh = 0
        for (job_id, title), place in zip(names, places):
            if job_id in seen:
                continue
            seen.add(job_id)
            fresh += 1
            jobs.append(
                Job(
                    ats="jobvite",
                    token=token,
                    job_id=job_id,
                    title=" ".join(title.split()),
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
_HAILEY_CARD = re.compile(
    r'<a href="(/[a-z]{2}-[A-Z]{2}/job/[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36})"'
    r"([\s\S]{0,4000}?)</a>",
    re.I,
)
_HAILEY_TITLE = re.compile(r"<h3[^>]{0,200}>([^<]{2,200})</h3>", re.I)
# The location chip. Hailey calls it a "workplace" and it is the only text in
# this exact wrapper, which is why the class is matched rather than a position.
_HAILEY_PLACE = re.compile(
    r'<div class="flex items-center justify-between gap-1">([^<]{1,120})</div>', re.I
)
_HAILEY_SUMMARY = re.compile(r"<p[^>]{0,300}>([^<]{2,600})</p>", re.I)


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
    for match in _HAILEY_CARD.finditer(body):
        href, card = match.group(1), match.group(2)
        title = _HAILEY_TITLE.search(card)
        if not title:
            # No heading means this is not a job card -- Hailey uses the same
            # anchor shape for the "read more" tile at the foot of the board.
            continue
        job_id = href.split("/")[4]
        if job_id in seen:
            continue
        seen.add(job_id)
        place = _HAILEY_PLACE.search(card)
        summary = _HAILEY_SUMMARY.search(card)
        jobs.append(
            Job(
                ats="hailey",
                token=token,
                job_id=job_id,
                title=_text(title.group(1)) or "",
                url=f"https://{token}.careers.haileyhr.app{href}",
                location=_text(place.group(1)) if place else None,
                description=_text(summary.group(1)) if summary else None,
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


# Oracle asks for the page size inside a `finder` expression rather than as a
# query parameter, so the whole thing is one opaque-looking string. 200 is
# comfortably served -- a request for 500 came back with the board's true 139
# rather than an error -- but it is kept at 200 because a page size a vendor
# merely tolerates is the kind of thing that starts returning an empty array
# with HTTP 200 one day, which is the Workday trap two hundred lines up.
_ORACLE_PAGE = 200
_ORACLE_PAGES = 1_000


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
        if len(postings) < _ORACLE_PAGE:
            break
    # The board states its own size. A board that says 1,295 and hands over 800
    # is what a page cap looks like from the outside, and nothing else would
    # say so -- this is the check that caught Jobvite's missing slash.
    if advertised is not None and advertised > len(jobs):
        raise ValueError(
            f"oracle_hcm/{token}: board advertises {advertised} postings, read {len(jobs)}"
        )
    return jobs


# ADP asks for the board by its `cid` GUID and answers with the whole thing --
# no paging parameter is honoured and `meta.totalNumber` states the size, so
# that is the check rather than the stop condition, as everywhere else here.
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
    payload = _json(
        "https://workforcenow.adp.com/mascsr/default/careercenter/public/events"
        f"/staffing/v1/job-requisitions?cid={urllib.parse.quote(token)}"
    )
    requisitions = payload.get("jobRequisitions") or []
    meta = payload.get("meta") or {}
    jobs: list[Job] = []
    for requisition in requisitions:
        job_id = str(requisition.get("itemID") or "")
        if not job_id:
            continue
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
    advertised = meta.get("totalNumber")
    if isinstance(advertised, int) and advertised > len(jobs):
        raise ValueError(
            f"adp/{token}: board advertises {advertised} postings, read {len(jobs)}"
        )
    return jobs


_UKG_PAGE = 100
_UKG_PAGES = 200


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
    origin = f"https://recruiting.ultipro.com/{code}/JobBoard/{board}"
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
            jobs.append(
                Job(
                    ats="workday",
                    token=token,
                    job_id=path or job.get("title", ""),
                    title=job.get("title") or "",
                    url=f"{origin}/en-US/{site}{path}",
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
