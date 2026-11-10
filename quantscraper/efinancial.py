"""eFinancialCareers, read as a finance-only census of each hub.

Why it is here: the employer-first pipeline cannot reach a firm with no
careers page, and those firms (most Hong Kong hedge funds, and everything a
recruiter fills) advertise here. Measured 10 November 2026: the public search
API answers without an account or key, returns 100 rows a page with the full
description, and an empty query for a location lists that location's whole
board -- Hong Kong 2,542, Singapore 2,151 -- so nothing depends on a keyword
we thought to ask.

One token per hub, so each hub is judged, written and withdrawn on its own.
A hub is written only after its walk is proven complete: `removed_at` is set
from "absent from a sound walk", and a partial walk must not say that.

Recruiter adverts name the agency as the employer. They are kept as published;
whether to show them is a board question, not an ingestion one.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
from dataclasses import dataclass, field

from . import db, http, parsing, sweep
from .models import Job

NAME = "efinancial"
SITE = "https://www.efinancialcareers.com"
SEARCH_URL = "https://job-search-api.efinancialcareers.com/v1/efc/jobs/search"
PAGE_SIZE = 100
MAX_PAGES = 200

# token -> (the location the API is asked for, the country it must resolve to,
# the floor below which the answer is a broken source). The country check is
# the guard against the API's geocoder reading a name as somewhere else and
# answering, well-formed, about the wrong place. Floors are about a third of
# what each hub held when measured; Sweden and Denmark hold under ten adverts,
# so their floor is zero and the total floor below is what protects them.
HUBS: dict[str, tuple[str, str, int]] = {
    "hong-kong": ("Hong Kong", "HK", 800),
    "singapore": ("Singapore", "SG", 700),
    "sweden": ("Sweden", "SE", 0),
    "denmark": ("Denmark", "DK", 0),
    "netherlands": ("Netherlands", "NL", 300),
    "switzerland": ("Switzerland", "CH", 400),
    "new-york": ("New York", "US", 1_500),
    "chicago": ("Chicago", "US", 400),
    "boston": ("Boston", "US", 250),
}
MIN_EXPECTED = 5_000


# These hosts are sent a client name only, never a contact address.
HEADERS = {"User-Agent": "quant-scraper/0.1"}


class Blocked(RuntimeError):
    """The API answered with something that is not a search result."""


@dataclass(slots=True)
class Hub:
    token: str
    pages: int = 0
    seen: int = 0
    served: int = 0
    advertised: int = 0
    written: int = 0
    withdrawn: int = 0
    problem: str | None = None


@dataclass(slots=True)
class Sweep:
    hubs: list[Hub] = field(default_factory=list)
    partial: bool = False

    @property
    def pages(self) -> int:
        return sum(hub.pages for hub in self.hubs)

    @property
    def seen(self) -> int:
        return sum(hub.seen for hub in self.hubs)

    @property
    def written(self) -> int:
        return sum(hub.written for hub in self.hubs)

    @property
    def problem(self) -> str | None:
        failed = [f"{hub.token}: {hub.problem}" for hub in self.hubs if hub.problem]
        if failed:
            return "; ".join(failed)
        if self.partial:
            return None
        return sweep.problem(self.seen, 0, MIN_EXPECTED)


def fetch_page(location: str, page: int) -> dict:
    query = urllib.parse.urlencode(
        {"q": "", "location": location, "page": page,
         "pageSize": PAGE_SIZE, "sortBy": "date"}
    )
    try:
        payload = json.loads(http.get_text(f"{SEARCH_URL}?{query}", timeout=90, headers=HEADERS))
    except ValueError as exc:
        raise Blocked(f"page {page} for {location} did not parse: {exc}") from None
    if not isinstance(payload.get("data"), list) or not isinstance(payload.get("meta"), dict):
        raise Blocked(f"page {page} for {location} carries no data/meta")
    return payload


def _job(token: str, row: dict) -> Job:
    place = row.get("jobLocation") or {}
    path = row.get("detailsPageUrl")
    return Job(
        ats=NAME,
        token=token,
        # `jobId` is the number in the public URL; `id` is an opaque search key.
        job_id=str(row["jobId"]),
        title=(row.get("title") or "").strip(),
        employer=(row.get("companyName") or "").strip() or None,
        category=" | ".join(row.get("sectors") or []) or None,
        url=f"{SITE}{path}" if path else None,
        location=(place.get("displayName") or "").strip() or None,
        posted_at=(row.get("postedDate") or "")[:10] or None,
        # `expirationDate` is when the advert's inventory slot ends, not when
        # applications close, so no deadline is written.
        description=parsing.text(row.get("description"), limit=60_000),
    )


def walk(token: str, *, pages: int | None = None) -> tuple[Hub, dict[str, Job]]:
    """Read one hub. The hub's `problem` says whether the result may be written."""
    location, country, floor = HUBS[token]
    hub = Hub(token)
    jobs: dict[str, Job] = {}
    limit = MAX_PAGES if pages is None else min(pages, MAX_PAGES)
    exhausted = False
    for page in range(1, limit + 1):
        payload = fetch_page(location, page)
        hub.pages += 1
        meta = payload["meta"]
        if page == 1:
            hub.advertised = int(meta.get("totalResults") or 0)
            resolved = (meta.get("searchedLocation") or {}).get("countryCode2")
            if resolved != country:
                raise Blocked(f"{location!r} resolved to {resolved!r}, expected {country}")
        rows = [row for row in payload["data"] if row.get("jobId")]
        hub.served += len(rows)
        for row in rows:
            jobs[str(row["jobId"])] = _job(token, row)
        if not payload["data"] or page >= int(meta.get("pageCount") or 0):
            exhausted = True
            break
    hub.seen = len(jobs)
    if pages is None:
        hub.problem = (
            None if exhausted
            else f"stopped at the {MAX_PAGES}-page bound with rows still arriving"
        ) or sweep.problem(hub.seen, hub.advertised, floor, served=hub.served, noun="hub")
    return hub, jobs


def run(connection: sqlite3.Connection, *, only: list[str] | None = None,
        pages: int | None = None) -> Sweep:
    """Sweep every hub into `jobs`. One hub failing does not stop the others."""
    result = Sweep(partial=pages is not None or bool(only))
    for token in only or HUBS:
        started = db.now()
        try:
            hub, jobs = walk(token, pages=pages)
        except Exception as exc:  # noqa: BLE001 -- recorded, and the next hub is read
            hub, jobs = Hub(token, problem=str(exc)), {}
        result.hubs.append(hub)
        if hub.problem or not jobs:
            continue
        hub.written = db.upsert_jobs(connection, None, jobs.values())
        if pages is None:
            # Complete and sound, so absence means the advert came down; an
            # advert that came back is live again.
            with connection:
                hub.withdrawn = connection.execute(
                    "UPDATE jobs SET removed_at = ? WHERE ats = ? AND token = ?"
                    " AND last_seen < ? AND removed_at IS NULL",
                    (started, NAME, token, started),
                ).rowcount
                connection.execute(
                    "UPDATE jobs SET removed_at = NULL WHERE ats = ? AND token = ?"
                    " AND last_seen >= ? AND removed_at IS NOT NULL",
                    (NAME, token, started),
                )
    return result
