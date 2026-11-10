"""LinkedIn's public guest job search, read per hub by keyword.

Why it is here: small and niche firms with no careers page advertise on
LinkedIn and nowhere this pipeline otherwise reads. Measured 10 November 2026:
the guest endpoint answers without an account, ten cards a page, and the first
page for Hong Kong carried a Junior Quantitative Analyst at Polymer Capital, a
roster firm with no pollable board.

This is a search, not a census: it returns what the keywords ask for, and the
endpoint stops serving at about a thousand rows a query. Both limits are
reported per query rather than hidden. `KEYWORDS` is deliberately broad; the
classifier decides relevance afterwards, as for every other source.

One token per hub. No login, no cookies, one connection under the shared
per-host throttle; a refusal (HTTP 999, or a 429 past its backoff) ends that
hub and is reported, never worked around. Descriptions are fetched by `bodies`
for the postings whose title alone could not be placed.
"""

from __future__ import annotations

import re
import sqlite3
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import db, http, parsing, sweep
from .models import Job

NAME = "linkedin"
HOST = "www.linkedin.com"
SEARCH_URL = f"https://{HOST}/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = f"https://{HOST}/jobs-guest/jobs/api/jobPosting/"
PAGE_SIZE = 10
# The endpoint serves nothing past this offset whatever the query matched.
WINDOW = 1_000

# token -> (LinkedIn geoId, a pattern most returned locations must match).
# The pattern is the guard on the id: an id LinkedIn no longer recognises
# falls back to a worldwide search that answers 200 with well-formed cards.
HUBS: dict[str, tuple[str, str]] = {
    "hong-kong": ("103291313", r"hong kong"),
    "singapore": ("102454443", r"singapore"),
    "sweden": ("105117694", r"sweden|sverige"),
    "denmark": ("104514075", r"denmark|danmark"),
    "netherlands": ("102890719", r"netherlands|nederland"),
    "switzerland": ("106693272", r"switzerland|schweiz|suisse"),
    "new-york": ("90000070", r"\b(NY|NJ|CT|PA)\b|new york"),
    "chicago": ("90000014", r"\b(IL|IN|WI)\b|chicago"),
    "boston": ("90000007", r"\b(MA|NH)\b|boston"),
}

# Broad on purpose. A keyword search cannot return what was not asked for, so
# these name the field and its neighbours rather than job titles.
KEYWORDS = (
    "quantitative",
    "quant",
    "trader",
    "systematic trading",
    "algorithmic trading",
    "derivatives pricing",
    "hedge fund",
    "proprietary trading",
)

# A posting from a windowed query that a sound sweep no longer returns is
# withdrawn only after this long unseen; absence from a truncated list proves
# nothing on its own.
STALE_AFTER = timedelta(days=28)

_ID = re.compile(r"urn:li:jobPosting:(\d+)")


# These hosts are sent a client name only, never a contact address.
HEADERS = {"User-Agent": "quant-scraper/0.1"}


class Blocked(RuntimeError):
    """LinkedIn answered with something that is not a result list."""


@dataclass(slots=True)
class Hub:
    token: str
    pages: int = 0
    seen: int = 0
    written: int = 0
    withdrawn: int = 0
    windowed: list[str] = field(default_factory=list)  # keywords that hit WINDOW
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
        return "; ".join(failed) or None


def parse(markup: str, token: str) -> list[Job]:
    """The cards on one page of results. An empty list is the end of a query."""
    jobs = []
    for card in parsing.soup(markup).select("[data-entity-urn]"):
        found = _ID.search(card.get("data-entity-urn") or "")
        title = card.select_one(".base-search-card__title")
        if not found or not title:
            continue

        def read(selector: str) -> str | None:
            node = card.select_one(selector)
            return (node.get_text(" ", strip=True) or None) if node else None

        link = card.select_one("a.base-card__full-link")
        when = card.select_one("time[datetime]")
        jobs.append(Job(
            ats=NAME,
            token=token,
            job_id=found.group(1),
            title=title.get_text(" ", strip=True),
            employer=read(".base-search-card__subtitle"),
            # The tracking query is per request; the path is the posting.
            url=(link.get("href") or "").split("?")[0] or None if link else None,
            location=read(".job-search-card__location"),
            posted_at=when.get("datetime") if when else None,
        ))
    if not jobs and markup.strip() and "<li" not in markup:
        raise Blocked("the response is neither result cards nor an empty list")
    return jobs


def fetch_page(geo: str, keyword: str, start: int) -> str:
    query = urllib.parse.urlencode(
        {"keywords": keyword, "geoId": geo, "start": start, "sortBy": "DD"}
    )
    return http.get_text(f"{SEARCH_URL}?{query}", timeout=60, headers=HEADERS)


def walk(token: str, *, keywords=KEYWORDS, pages: int | None = None) -> tuple[Hub, dict[str, Job]]:
    """Every keyword for one hub, newest first, each until an empty page."""
    geo, place = HUBS[token]
    hub = Hub(token)
    jobs: dict[str, Job] = {}
    checked = False
    for keyword in keywords:
        for start in range(0, WINDOW, PAGE_SIZE):
            if pages is not None and start >= pages * PAGE_SIZE:
                break
            rows = parse(fetch_page(geo, keyword, start), token)
            hub.pages += 1
            if not rows:
                break
            if not checked:
                local = sum(bool(re.search(place, row.location or "", re.I)) for row in rows)
                if local * 2 < len(rows):
                    raise Blocked(
                        f"geoId {geo} returned {len(rows) - local} of {len(rows)} "
                        f"cards outside {token} -- the id no longer names this hub"
                    )
                checked = True
            for row in rows:
                jobs.setdefault(row.job_id, row)
        else:
            hub.windowed.append(keyword)
    hub.seen = len(jobs)
    return hub, jobs


def run(connection: sqlite3.Connection, *, only: list[str] | None = None,
        pages: int | None = None) -> Sweep:
    """Sweep every hub into `jobs`. One hub failing does not stop the others."""
    result = Sweep(partial=pages is not None or bool(only))
    for token in only or HUBS:
        started = db.now()
        try:
            hub, jobs = walk(token, pages=pages)
            if pages is None and not jobs:
                hub.problem = "no postings for any keyword -- treating as a broken source"
        except Exception as exc:  # noqa: BLE001 -- recorded, and the next hub is read
            hub, jobs = Hub(token, problem=str(exc)), {}
        result.hubs.append(hub)
        if hub.problem or not jobs:
            continue
        hub.written = db.upsert_jobs(connection, None, jobs.values())
        if pages is None:
            # With no query windowed the sweep saw everything the keywords
            # match, so absence is withdrawal. Otherwise wait `STALE_AFTER`.
            cutoff = started if not hub.windowed else (
                datetime.fromisoformat(started) - STALE_AFTER
            ).astimezone(timezone.utc).isoformat(timespec="seconds")
            with connection:
                hub.withdrawn = connection.execute(
                    "UPDATE jobs SET removed_at = ? WHERE ats = ? AND token = ?"
                    " AND last_seen < ? AND removed_at IS NULL",
                    (started, NAME, token, cutoff),
                ).rowcount
                connection.execute(
                    "UPDATE jobs SET removed_at = NULL WHERE ats = ? AND token = ?"
                    " AND last_seen >= ? AND removed_at IS NOT NULL",
                    (NAME, token, started),
                )
    return result


def body(job_id: str) -> tuple[str | None, str | None]:
    """(description, location) from the public posting fragment."""
    page = parsing.soup(http.get_text(f"{DETAIL_URL}{job_id}", timeout=60, retries=2, headers=HEADERS))
    text = page.select_one(".show-more-less-html__markup")
    place = page.select_one(".topcard__flavor--bullet")
    return (
        parsing.text(str(text), limit=60_000) if text else None,
        (place.get_text(" ", strip=True) or None) if place else None,
    )
