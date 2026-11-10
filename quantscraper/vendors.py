"""Vendor-first reading: the ATS vendors' own cross-tenant search.

Why it is here: the employer-first pipeline reaches a board only through a
domain it resolved and a careers page it could fingerprint, and Stage 69
measured what that loses -- known firms behind wrong domains, 403s and pages
that name no vendor. Two vendors answer a search across all their tenants with
no account or key, which turns the question round: read who is hiring on the
vendor, then attach it to an employer.

**Workable is a census.** `jobs.workable.com/api/v1/jobs` lists every published
Workable posting in a location, 20 a page with a `pageToken` cursor and an
advertised `totalSize`. Measured 10 November 2026: Sweden 510 advertised, 510
served over 26 pages, 510 distinct. Each row carries the tenant's own name and
the website it gave Workable. It never carries the tenant's account slug, so
the rows are read as a portal (`workable_jobs`, one token per hub, the
`efinancial` discipline) rather than turned into tenant boards. The website is
the tenant's statement of its domain, so a tenant with a markets title has it
cached as a lead, and `ats` walks it on its next pass.

**SmartRecruiters is a lead list, not a census.** `sr-jobs/search` matches a
keyword against title and place, ORs multi-word keywords, ignores every paging
parameter tried (`offset`, `page`, `start`) and returns the top 100. A hub
city's name as the keyword gives up to 100 of that hub's postings, and the top
100 rotates, so the tenants found accumulate week on week. Each row carries the
tenant identifier the `smartrecruiters` reader takes, so a lead becomes a board
once it has a domain: the universe's, else a guess `domains.verify` accepts.

Both hosts receive a client name only, never a contact address.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field

from . import db, domains, extract, http, lexicon, parsing, sweep
from .models import Job
from .resolve import domain_of, is_platform_domain, normalize_name

NAME = "workable_jobs"
SEARCH_URL = "https://jobs.workable.com/api/v1/jobs"
MAX_PAGES = 400  # New York held 4,718 when measured: 236 pages

# token -> (the location asked for, the country every row must be in, a floor
# about a third of what the hub held when measured).
HUBS: dict[str, tuple[str, str, int]] = {
    "sweden": ("Sweden", "Sweden", 150),
    "denmark": ("Denmark", "Denmark", 300),
    "netherlands": ("Netherlands", "Netherlands", 450),
    "switzerland": ("Switzerland", "Switzerland", 150),
    "hong-kong": ("Hong Kong", "Hong Kong", 150),
    "singapore": ("Singapore", "Singapore", 1_000),
    "new-york": ("New York", "United States", 1_500),
    "chicago": ("Chicago", "United States", 400),
    "boston": ("Boston", "United States", 400),
}
MIN_EXPECTED = 5_000
# The host answers a sustained one-a-second walk with 429, so it is read at
# `http.HOST_INTERVAL_S` (four seconds): about 1,200 pages, 80 minutes a week.
HOST = "jobs.workable.com"

# A row elsewhere is the geocoder reading the name as another place. A few are
# remote postings listed under the hub; a majority means the answer is about
# the wrong place.
_FOREIGN_SHARE = 0.25

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
    foreign: int = 0
    problem: str | None = None


@dataclass(slots=True)
class Sweep:
    hubs: list[Hub] = field(default_factory=list)
    leads: int = 0
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


def fetch_page(location: str, cursor: str | None) -> dict:
    query = {"query": "", "location": location}
    if cursor:
        query["pageToken"] = cursor
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(query)}"
    try:
        payload = json.loads(http.get_text(url, timeout=60, headers=HEADERS))
    except ValueError as exc:
        raise Blocked(f"{location} did not parse: {exc}") from None
    if not isinstance(payload.get("jobs"), list) or "totalSize" not in payload:
        raise Blocked(f"{location} carries no jobs/totalSize")
    return payload


def _place(row: dict) -> str | None:
    places = [p for p in row.get("locations") or [] if isinstance(p, str) and p]
    if places:
        return " | ".join(places)
    where = row.get("location") or {}
    return ", ".join(p for p in (where.get("city"), where.get("countryName")) if p) or None


def _job(token: str, row: dict) -> Job:
    company = row.get("company") or {}
    body = " ".join(
        part for part in (
            row.get("description"), row.get("requirementsSection"),
            row.get("benefitsSection"),
        ) if part
    )
    return Job(
        ats=NAME,
        token=token,
        job_id=str(row["id"]),
        title=(row.get("title") or "").strip(),
        employer=(company.get("title") or "").strip() or None,
        url=row.get("url"),
        location=_place(row),
        department=(row.get("department") or "").strip() or None,
        posted_at=(row.get("created") or "")[:10] or None,
        description=parsing.text(body, limit=60_000),
    )


def tenant_domain(row: dict) -> str | None:
    """The domain a tenant gave Workable, unless it is a platform page."""
    domain = domain_of((row.get("company") or {}).get("website"))
    return None if not domain or is_platform_domain(domain) else domain


def walk(token: str, *, pages: int | None = None) -> tuple[Hub, dict[str, tuple[Job, str | None]]]:
    """Read one hub. The hub's `problem` says whether the result may be written."""
    location, country, floor = HUBS[token]
    hub = Hub(token)
    jobs: dict[str, tuple[Job, str | None]] = {}
    limit = MAX_PAGES if pages is None else min(pages, MAX_PAGES)
    cursor: str | None = None
    exhausted = False
    for _ in range(limit):
        payload = fetch_page(location, cursor)
        hub.pages += 1
        if hub.pages == 1:
            hub.advertised = int(payload.get("totalSize") or 0)
        rows = [row for row in payload["jobs"] if row.get("id")]
        hub.served += len(rows)
        for row in rows:
            if (row.get("location") or {}).get("countryName") != country:
                hub.foreign += 1
            jobs[str(row["id"])] = (_job(token, row), tenant_domain(row))
        cursor = payload.get("nextPageToken")
        if not cursor or not rows:
            exhausted = True
            break
    hub.seen = len(jobs)
    if hub.served and hub.foreign > _FOREIGN_SHARE * hub.served:
        raise Blocked(
            f"{hub.foreign} of {hub.served} rows are outside {country}:"
            f" {location!r} resolved somewhere else"
        )
    if pages is None:
        hub.problem = (
            None if exhausted
            else f"stopped at the {MAX_PAGES}-page bound with rows still arriving"
        ) or sweep.problem(hub.seen, hub.advertised, floor, served=hub.served, noun="hub")
    return hub, jobs


def leads(connection: sqlite3.Connection, found: dict[str, tuple[Job, str | None]]) -> int:
    """Cache tenants with a markets title under the domain they stated.

    Keyed on the tenant's name, the way `domain_lookups` is keyed on a firm's,
    and never over an existing row: a registry website or a verified guess
    outranks what a tenant typed into its vendor profile. A cached domain with
    no tier is what `ats.targets` walks first. Returns the rows written.
    """
    wanted: dict[str, tuple[str, str]] = {}
    for job, domain in found.values():
        if not domain or not job.employer or job.employer in wanted:
            continue
        if lexicon.judge(job.title, job.department).verdict == "keep":
            wanted[job.employer] = (domain, job.title)
    if not wanted:
        return 0
    connection.executescript(domains.SCHEMA)
    timestamp = db.now()
    with connection:
        return sum(
            connection.execute(
                "INSERT OR IGNORE INTO domain_lookups"
                " (query, domain, method, evidence, checked_at)"
                " VALUES (?, ?, 'vendor', ?, ?)",
                (name, domain, f"workable search: tenant website, hiring {title!r}",
                 timestamp),
            ).rowcount
            for name, (domain, title) in wanted.items()
        )


def run(connection: sqlite3.Connection, *, only: list[str] | None = None,
        pages: int | None = None) -> Sweep:
    """Sweep every hub into `jobs`. One hub failing does not stop the others."""
    result = Sweep(partial=pages is not None or bool(only))
    for token in only or HUBS:
        started = db.now()
        try:
            hub, found = walk(token, pages=pages)
        except Exception as exc:  # noqa: BLE001 -- recorded, and the next hub is read
            hub, found = Hub(token, problem=str(exc)), {}
        result.hubs.append(hub)
        if hub.problem or not found:
            continue
        # `upsert_jobs` takes one domain a batch, and every row here names
        # its own tenant's.
        batches: dict[str | None, list[Job]] = defaultdict(list)
        for job, domain in found.values():
            batches[domain].append(job)
        hub.written = sum(
            db.upsert_jobs(connection, domain, jobs) for domain, jobs in batches.items()
        )
        result.leads += leads(connection, found)
        if pages is None:
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


# ---- SmartRecruiters: tenants as leads -------------------------------------

SR_SEARCH_URL = "https://jobs.smartrecruiters.com/sr-jobs/search"
SR_WINDOW = 100  # every query answers its top 100 and no more

# keyword -> the country code its rows must carry to count. A hub with two
# cities is asked twice.
SR_KEYWORDS: dict[str, tuple[str, str]] = {
    "Stockholm": ("se", "SE"),
    "Copenhagen": ("dk", "DK"),
    "Amsterdam": ("nl", "NL"),
    "Zurich": ("ch", "CH"),
    "Geneva": ("ch", "CH"),
    "Hong Kong": ("hk", "HK"),
    "Singapore": ("sg", "SG"),
    "New York": ("us", "US"),
    "Chicago": ("us", "US"),
    "Boston": ("us", "US"),
}

# Asked again after this long when it was not relevant, since a tenant hiring
# no markets role today may next month.
SR_RECHECK_DAYS = 28

SR_SCHEMA = """
CREATE TABLE IF NOT EXISTS vendor_tenants (
    ats         TEXT NOT NULL,
    token       TEXT NOT NULL,
    name        TEXT,
    domain      TEXT,
    outcome     TEXT NOT NULL,  -- board | domain-taken | stranded | not-relevant | unreadable
    evidence    TEXT,
    checked_at  TEXT NOT NULL,
    PRIMARY KEY (ats, token)
);
"""


@dataclass(slots=True)
class Tenant:
    token: str
    name: str
    country: str
    titles: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LeadSweep:
    asked: int = 0
    windowed: list[str] = field(default_factory=list)
    tenants: int = 0
    new: int = 0
    boards: list[tuple[str, str, str]] = field(default_factory=list)  # token, domain, name
    stranded: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def sr_search(keyword: str) -> dict:
    url = f"{SR_SEARCH_URL}?{urllib.parse.urlencode({'keyword': keyword, 'limit': SR_WINDOW})}"
    try:
        payload = json.loads(http.get_text(url, timeout=60, headers=HEADERS))
    except ValueError as exc:
        raise Blocked(f"{keyword!r} did not parse: {exc}") from None
    if not isinstance(payload.get("content"), list) or "totalFound" not in payload:
        raise Blocked(f"{keyword!r} carries no content/totalFound")
    return payload


def sr_tenants(result: LeadSweep) -> dict[str, Tenant]:
    """Tenants with a posting in a hub, from every hub keyword."""
    tenants: dict[str, Tenant] = {}
    for keyword, (code, country) in SR_KEYWORDS.items():
        try:
            payload = sr_search(keyword)
        except Exception as exc:  # noqa: BLE001 -- one keyword must not stop the rest
            result.problems.append(f"{keyword}: {exc}")
            continue
        result.asked += 1
        if int(payload.get("totalFound") or 0) > len(payload["content"]):
            result.windowed.append(keyword)
        for row in payload["content"]:
            company = row.get("company") or {}
            token = company.get("identifier")
            if not token or (row.get("location") or {}).get("country") != code:
                continue
            tenant = tenants.setdefault(
                token, Tenant(token, (company.get("name") or token).strip(), country)
            )
            tenant.titles.append(row.get("name") or "")
    result.tenants = len(tenants)
    return tenants


def universe_domains(connection: sqlite3.Connection) -> dict[str, str]:
    """Normalized firm name -> a domain the universe holds for it.

    Exact normalized names only, and only rows that are not weak and not a
    platform: an employer merge on a shared word is the error this project
    prefers to avoid (principle 4).
    """
    found: dict[str, str] = {}
    for row in connection.execute(
        "SELECT query, domain FROM domain_lookups WHERE domain IS NOT NULL"
        " AND method NOT LIKE '%weak%' ORDER BY method = 'registry' DESC"
    ):
        key = normalize_name(row["query"])
        if key and key not in found and not is_platform_domain(row["domain"]):
            found[key] = row["domain"]
    return found


def _due(connection: sqlite3.Connection, ats: str, tokens: list[str]) -> set[str]:
    """Tokens neither polled already nor settled recently."""
    polled = {
        row[0] for row in connection.execute(
            "SELECT token FROM ats_resolution WHERE ats = ? AND tier = 'A'", (ats,))
    }
    settled = {
        row[0] for row in connection.execute(
            "SELECT token FROM vendor_tenants WHERE ats = ?"
            " AND (outcome = 'board' OR checked_at >= datetime('now', ?))",
            (ats, f"-{SR_RECHECK_DAYS} days"),
        )
    }
    return {token for token in tokens if token not in polled and token not in settled}


def _settle(tenant: Tenant, known: dict[str, str]) -> tuple[str, str | None, str]:
    """(outcome, domain, evidence) for one new tenant. Network work only."""
    keep = next(
        (title for title in tenant.titles
         if lexicon.judge(title).verdict == "keep"), None)
    normalized = normalize_name(tenant.name)
    domain = known.get(normalized)
    if keep is None and domain is None:
        return "not-relevant", None, "no markets title and no universe firm of that name"
    # Verification runs the real extractor, as `discover` does: a board it
    # cannot read is not a board Layer 3 could poll.
    try:
        postings = extract.EXTRACTORS["smartrecruiters"](tenant.token)
    except Exception as exc:  # noqa: BLE001 -- recorded and moved past
        return "unreadable", domain, f"{type(exc).__name__}: {exc}"
    if not postings:
        return "unreadable", domain, "the board answered empty"
    why = f"smartrecruiters search, {len(postings)} postings" + (
        f", hiring {keep!r}" if keep else ", a universe firm")
    if domain is None and normalized:
        guessed = domains.resolve_name(normalized, tenant.country)
        if guessed.method == "name-strong":
            domain = guessed.domain
            why += f"; domain {guessed.evidence}"
    return ("board" if domain else "stranded"), domain, why


def sr_leads(connection: sqlite3.Connection, workers: int = 6) -> LeadSweep:
    """Find SmartRecruiters tenants hiring in a hub and hand them to Layer 3."""
    from concurrent.futures import ThreadPoolExecutor

    from . import ats as ats_module
    from . import discover

    connection.executescript(SR_SCHEMA)
    connection.executescript(ats_module.SCHEMA)
    connection.executescript(discover.SCHEMA)
    result = LeadSweep()
    tenants = sr_tenants(result)
    due = _due(connection, "smartrecruiters", list(tenants))
    result.new = len(due)
    if not due:
        return result
    known = universe_domains(connection)
    chosen = [tenants[token] for token in sorted(due)]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        settled = list(pool.map(lambda t: _settle(t, known), chosen))

    timestamp = db.now()
    found = []
    for tenant, (outcome, domain, evidence) in zip(chosen, settled):
        if outcome == "board":
            result.boards.append((tenant.token, domain, tenant.name))
            found.append(discover.Discovery(
                tenant.name, domain, "smartrecruiters", tenant.token, evidence))
        elif outcome == "stranded":
            result.stranded.append(tenant.name)
    discover.record(connection, found)
    # `record` never replaces a working board, and `ats_resolution` holds one
    # board a domain. A tenant whose domain already polls another board is
    # named for what happened to it rather than counted as a board.
    for index, (tenant, (outcome, domain, evidence)) in enumerate(zip(chosen, settled)):
        if outcome != "board":
            continue
        row = connection.execute(
            "SELECT ats, token FROM ats_resolution WHERE domain = ?", (domain,)
        ).fetchone()
        if not row or (row[0], row[1]) != ("smartrecruiters", tenant.token):
            held = f"{row[0]}/{row[1]}" if row else "nothing"
            settled[index] = ("domain-taken", domain, f"{evidence}; {domain} polls {held}")
            result.boards.remove((tenant.token, domain, tenant.name))
    with connection:
        connection.executemany(
            "INSERT OR REPLACE INTO vendor_tenants"
            " (ats, token, name, domain, outcome, evidence, checked_at)"
            " VALUES ('smartrecruiters', ?, ?, ?, ?, ?, ?)",
            [
                (tenant.token, tenant.name, domain, outcome, evidence, timestamp)
                for tenant, (outcome, domain, evidence) in zip(chosen, settled)
            ],
        )
    return result
