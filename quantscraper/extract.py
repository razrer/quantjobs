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
    if not value:
        return None
    return " ".join(_TAGS.sub(" ", value).split()) or None


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
    "teamtailor": teamtailor,
    "workday": workday,
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
