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
    """Workday CXS. `token` is `tenant|wdN|site` -- see `ats.py`."""
    parts = token.split("|")
    if len(parts) != 3:
        raise ValueError(
            f"workday token {token!r} is not tenant|wdN|site -- re-run `ats`"
        )
    tenant, wd, site = parts

    # Asserted, not merely used. Raising the cap silently truncates every board
    # on some tenants and 400s on others; the regression test pins it here.
    assert _WORKDAY_MAX <= 20, "Workday rejects limit > 20"

    url = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
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
                    url=f"https://{tenant}.{wd}.myworkdayjobs.com/en-US/{site}{path}",
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
    "personio": personio,
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


def run(connection: sqlite3.Connection, limit: int) -> tuple[int, int, list[str]]:
    """Pull postings for resolved boards. Returns (boards, jobs, failures)."""
    rows = targets(connection, limit)
    total = 0
    failures: list[str] = []
    for row in rows:
        extractor = EXTRACTORS[row["ats"]]
        try:
            jobs = extractor(row["token"])
        # One board with an unexpected payload must not abandon the rest --
        # the same rule `fetch` follows for registries. Failures are returned
        # and printed rather than swallowed, so a broken format is still loud.
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError,
                AttributeError, TypeError, IndexError, TimeoutError, OSError) as exc:
            failures.append(f"{row['ats']}/{row['token']}: {type(exc).__name__} {exc}")
            continue
        if jobs:
            total += db.upsert_jobs(connection, row["domain"], jobs)
    return len(rows), total, failures
