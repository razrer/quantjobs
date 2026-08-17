"""Layer 2, part two -- turning a domain into an applicant tracking system.

A domain is not a job feed. Almost every firm outsources hiring to an ATS, and
each ATS has one public endpoint shape, so `(ats, token)` is what Layer 3 needs:
`greenhouse` + `optiver` is a feed, `optiver.com` is a homepage.

**Fingerprinting, not guessing.** The careers page links to, or loads script
from, whichever ATS it uses -- that outbound host is the evidence, and the board
token falls out of the same URL. Nothing here is inferred from the firm's name.

**Every domain gets a tier, because "no ATS found" is a real answer and has to
be actionable rather than silent:**

  A  an ATS and token were fingerprinted -- Layer 3 polls the feed directly
  B  a careers page exists but runs on nothing we recognise -- Layer 3B watches
     it for changes instead, which works on any page structure
  C  no careers page could be found at all -- needs a human or a better crawl

Untiered is the one state that must not exist: a domain nobody looked at is
indistinguishable from a firm that is not hiring, and that is the silent
coverage loss this project keeps designing against.

**Cached on the domain**, not the firm id, for the same reason `domains.py` is:
`firms` is rebuilt from scratch on demand. Re-verification matters here more
than anywhere else -- a firm migrating ATS is invisible unless something checks,
and its feed simply goes quiet.
"""

from __future__ import annotations

import re
import sqlite3
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import db, http

SCHEMA = """
CREATE TABLE IF NOT EXISTS ats_resolution (
    domain      TEXT PRIMARY KEY,
    careers_url TEXT,
    ats         TEXT,      -- NULL for tier B and C
    token       TEXT,      -- the board identifier, where the ATS uses one
    tier        TEXT NOT NULL,
    evidence    TEXT,
    checked_at  TEXT NOT NULL
);
"""

# Two bounds, and the host patterns need both.
#
# `([a-z0-9-]+)\.host\.com` looks harmless and is quadratic: over a long run
# with no dot in it the capture swallows everything, backtracks one character
# at a time, fails, and then the engine restarts the whole exercise one
# position along. An inline base64 data URI is exactly such a run. A 40 KB
# image stalled one pattern for minutes; a page carrying a few hung two runs
# for hours at full CPU, writing nothing and reporting nothing.
#
# A DNS label is at most 63 characters, which caps the backtracking. That alone
# still leaves 63 attempts at every one of two million positions, so the
# lookbehind does the real work: a label cannot begin mid-label, so inside a
# base64 blob every position fails on the first check instead of the 63rd. It
# excludes only the label characters, so `board.host.com` still matches when it
# appears as `foo.board.host.com`.
_LABEL = r"([a-z0-9-]{1,63})"
_HOST_LABEL = r"(?<![a-z0-9-])" + _LABEL

# Each pattern pulls the board token straight out of the ATS's own URL. The
# Nordic group (Teamtailor, Varbi, Jobylon, Emply, Talentech) is here because
# without it Stockholm and Copenhagen are not exhaustive -- generic scrapers
# cover none of them, and they dominate Nordic mid-market hiring.
ATS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # boards-api URLs carry an API version before the board, so the token is
    # after /boards/, not after the host. Matching the host alone extracts "v1"
    # for every Greenhouse user on earth.
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v\d+/boards/([a-z0-9_-]+)", re.I)),
    ("greenhouse", re.compile(r"(?:job-)?boards\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)", re.I)),
    # Workday needs three things to be pollable -- tenant, data-centre number
    # and site -- so the token is compound. Capturing the tenant alone reads
    # like success and leaves the board unreachable.
    # Both Workday hosts, and they order the same three parts differently -- so
    # these capture by *name*. Joining by position silently built
    # `wd3|brevanhoward|BH_ExternalCareers` for the second one, which is a
    # well-formed token addressing nothing.
    (
        "workday",
        re.compile(
            r"(?<![a-z0-9-])(?P<tenant>[a-z0-9-]{1,63})"
            r"\.(?P<wd>wd\d+)\.myworkdayjobs\.com"
            r"(?:/wday/cxs/[^/\"']+)?(?:/[a-z]{2}-[A-Z]{2})?/(?P<site>[A-Za-z0-9_-]+)",
            re.I,
        ),
    ),
    # Workday's *other* host, which inverts the URL. On `myworkdayjobs.com` the
    # tenant is the subdomain; on `myworkdaysite.com` the subdomain is a bare
    # `wdN` and the tenant moves into the path:
    # `wd3.myworkdaysite.com/recruiting/brevanhoward/BH_ExternalCareers`.
    # The pattern above cannot match that shape at all, so every firm on this
    # host tiered B with a live feed behind it -- Brevan Howard among them, 15
    # postings including an execution trader seat.
    (
        "workday",
        re.compile(
            r"(?P<wd>wd\d+)\.(?P<host>myworkdaysite\.com)/(?:wday/cxs|recruiting)"
            r"/(?P<tenant>[A-Za-z0-9_-]+)(?:/[a-z]{2}-[A-Z]{2})?"
            r"/(?P<site>[A-Za-z0-9_-]+)",
            re.I,
        ),
    ),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)", re.I)),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([a-z0-9_-]+)", re.I)),
    ("workable", re.compile(r"(?:apply|jobs)\.workable\.com/([a-z0-9_-]+)", re.I)),
    ("teamtailor", re.compile(_HOST_LABEL + r"\.teamtailor\.com", re.I)),
    ("varbi", re.compile(_HOST_LABEL + r"\.varbi\.com", re.I)),
    ("jobylon", re.compile(_HOST_LABEL + r"\.jobylon\.com|jobylon\.com/jobs/([a-z0-9-]+)", re.I)),
    ("emply", re.compile(_HOST_LABEL + r"\.emply\.(?:com|net)", re.I)),
    ("recruitee", re.compile(_HOST_LABEL + r"\.recruitee\.com", re.I)),
    ("personio", re.compile(_HOST_LABEL + r"\.jobs\.personio\.(?:de|com)", re.I)),
    ("bamboohr", re.compile(_HOST_LABEL + r"\.bamboohr\.com", re.I)),
    ("icims", re.compile(r"careers-" + _LABEL + r"\.icims\.com", re.I)),
    ("taleo", re.compile(_HOST_LABEL + r"\.taleo\.net", re.I)),
    ("successfactors", re.compile(_HOST_LABEL + r"\.jobs\.sap\.com|career\d*\.successfactors\.(?:eu|com)", re.I)),
    ("eightfold", re.compile(_HOST_LABEL + r"\.eightfold\.ai", re.I)),
    ("pinpoint", re.compile(_HOST_LABEL + r"\.pinpointhq\.com", re.I)),
    ("jobvite", re.compile(r"jobs\.jobvite\.com/([a-z0-9_-]+)", re.I)),
    ("breezy", re.compile(_HOST_LABEL + r"\.breezy\.hr", re.I)),
    ("join", re.compile(r"join\.com/companies/([a-z0-9_-]+)", re.I)),
    ("homerun", re.compile(_HOST_LABEL + r"\.homerun\.co", re.I)),
)

# Careers links in the languages of the focus hubs. Missing the Swedish or
# Dutch word for "jobs" would silently tier those firms C.
_CAREERS_WORDS = (
    "career", "careers", "jobs", "job", "vacancy", "vacancies", "join-us",
    "join", "work-with-us", "working", "recruit", "hiring", "opportunities",
    "lediga", "ledigajobb", "jobb", "karriar", "karriar", "vacature",
    "vacatures", "werken", "werkenbij", "stillinger", "karriere", "ansatte",
    "stellen", "emploi", "empleo", "lavora",
)
# Hrefs are extracted first and matched against the word list in Python. The
# obvious single regex -- `[^"']*(?:career|jobs|...)[^"']*` -- backtracks
# catastrophically on real markup: an unterminated quote inside inline script
# leaves the two unbounded runs competing for the same characters, once per
# word occurrence, and a 500 KB homepage then takes hours at full CPU with no
# output. Two runs stalled on exactly that. The length bound keeps the failure
# local even so: an href that never closes costs 2,000 steps, not the page.
_HREF = re.compile(r'href=["\']([^"\']{0,2000})["\']', re.I)

_MAX_CAREERS_PAGES = 3

# Careers pages fetched per domain across both hops. The queue is 19,000
# domains long, so this is a budget, not a preference.
_MAX_FETCHES = 6

# A careers page is HTML, not a media file. Fingerprinting runs 23 patterns
# over the body twice, so an unbounded one stalls the whole pool -- the GIL
# means one thread scanning a huge string blocks the other fifteen.
_MAX_MARKUP = 2_000_000

# Subdomains and path segments that are infrastructure, not a board. Every ATS
# serves its own assets from hosts that match the same shape, so without this
# Lynx resolves to Teamtailor board "www" and half of Greenhouse to "v1".
_NOT_A_TOKEN = {
    "www", "api", "app", "apps", "assets", "cdn", "static", "js", "css",
    "embed", "media", "images", "img", "help", "support", "status", "docs",
    "blog", "developers", "developer", "partners", "resources", "my", "secure",
    # The ATS's own shared hosts. `career.emply.com` was claimed by five
    # unrelated Danish firms at once, `careers-analytics.recruitee.com` by
    # three, `staticfe.bamboohr.com` by one -- a token several unrelated
    # domains agree on is the vendor's infrastructure, not anyone's board.
    "career", "careers", "jobs", "job", "analytics", "staticfe", "portal",
    "login", "account", "accounts",
    *(f"v{n}" for n in range(1, 10)),
}


def _is_infrastructure(token: str) -> bool:
    """True when `token` names the vendor's own host rather than a board.

    Only the first component is tested. For Workday that is the tenant, and
    the *site* after it is very often called exactly "Careers" -- LSEG,
    Fortress, PJT Partners and Motorola all publish through
    `tenant|wdN|Careers`, so testing every component throws them away.

    Within that component, a piece counts only if *every* hyphenated part of
    it is infrastructure: `assets-cdn.breezy.hr` polled as the board
    "assets-cdn" and returned HTML, while `jane-street` must survive.
    """
    head = token.split("|")[0].casefold()
    return all(piece in _NOT_A_TOKEN for piece in head.split("-"))


@dataclass(frozen=True, slots=True)
class Resolution:
    domain: str
    careers_url: str | None
    ats: str | None
    token: str | None
    tier: str
    evidence: str | None


# An ATS serving a customer's board from the customer's *own* hostname. The
# board never appears as `{board}.vendor.com`, so every host pattern misses it
# and the firm is tiered B -- a careers page running on nothing recognisable.
# The vendor's asset CDN is still in the markup, and the board is reachable at
# the custom host, so that host is the token.
#
# This is not a corner case. `careers.lynxhedge.se` is Lynx Asset Management,
# which is the Stockholm quant firm this project exists to find, and it sat in
# tier B with a live feed behind it.
# (ats, asset host, feed path, marker the feed must contain)
_VENDOR_ASSETS: tuple[tuple[str, str, str, str], ...] = (
    ("teamtailor", "teamtailor-cdn.com", "/jobs.rss", "<channel"),
)


def _serves_feed(host: str, path: str, marker: str) -> bool:
    """Whether `host` actually answers with the vendor's feed.

    The guess on its own is wrong more often than right: embedding a vendor's
    widget puts its CDN in the markup of pages that serve no feed at all, and
    the first three domains this rule matched -- 3stepit, Enfuce, Infovista --
    all returned 404. Recording an unverified host is the failure mode this
    project keeps meeting: a board that looks resolved and yields nothing
    forever. One request settles it.
    """
    try:
        body, _ = http.get_with_url(f"https://{host}{path}", timeout=10, retries=1)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return False
    except Exception:  # noqa: BLE001 -- one hostile host must not stop the run
        return False
    return marker.encode() in body[:100_000]


def _workday_token(match: re.Match[str]) -> str | None:
    """`tenant|wdN|site`, plus the host when it is not the usual one.

    A three-part token means `myworkdayjobs.com`, which is what every existing
    row in `ats_resolution` already means, so nothing has to be re-resolved.
    The fourth part names the other host, and only `extract.workday` reads it.
    """
    parts = match.groupdict()
    tenant, wd, site = parts.get("tenant"), parts.get("wd"), parts.get("site")
    if not (tenant and wd and site):
        return None
    token = f"{tenant}|{wd}|{site}"
    return f"{token}|{parts['host']}" if parts.get("host") else token


def fingerprint(markup: str, url: str | None = None) -> tuple[str, str | None, str] | None:
    """(ats, token, evidence) for the first ATS the markup points at.

    A recognised ATS with an unusable token is still a useful answer -- it says
    which feed shape to use -- so the token is dropped rather than the match.

    `url` is where the markup came from, and it is only needed for the
    custom-domain case below, where the page's own host *is* the board.
    """
    for name, pattern in ATS_PATTERNS:
        for match in pattern.finditer(markup):
            groups = [g for g in match.groups() if g]
            # Workday's parts are all needed and the two hosts order them
            # differently, so they are assembled by name. Everything else takes
            # the first non-empty group as its board token.
            token = _workday_token(match) if name == "workday" else (
                groups[0] if groups else None
            )
            if token is None:
                continue  # tenant without a site is not pollable
            if _is_infrastructure(token):
                continue  # infrastructure host; keep looking for a real board
            # A purely numeric token is not a board name. `jobs.lever.co/500`
            # on an error page produced board "500", which then 404s on every
            # poll -- a firm that looks resolved and yields nothing forever.
            if name != "workday" and token.isdigit():
                continue
            return name, token, match.group(0)[:120]
    # Second pass: a vendor's assets on a page served from the firm's own
    # host. Checked before the infrastructure fallback, because it yields a
    # usable token where that one yields none.
    if url:
        host = urllib.parse.urlsplit(url).netloc.casefold()
        for name, asset_host, path, marker in _VENDOR_ASSETS:
            if asset_host in markup and host and _serves_feed(host, path, marker):
                return name, host, f"{asset_host}, feed verified at {host}"

    # Third pass: the ATS is present but every match was infrastructure.
    for name, pattern in ATS_PATTERNS:
        match = pattern.search(markup)
        if match:
            return name, None, match.group(0)[:120]
    return None


def careers_candidates(markup: str, domain: str) -> list[str]:
    """Careers URLs linked from a homepage, most promising first."""
    found: list[str] = []
    for href in _HREF.findall(markup):
        low = href.casefold()
        if not any(word in low for word in _CAREERS_WORDS):
            continue
        url = urllib.parse.urljoin(f"https://{domain}/", href.strip())
        if not url.startswith("http"):
            continue
        # An off-site careers link is usually the ATS itself, which is exactly
        # what we are looking for, so those are kept and ranked first.
        offsite = urllib.parse.urlsplit(url).netloc.casefold().endswith(domain) is False
        if url not in found:
            found.append(url)
        if len(found) > 40:
            break
    found.sort(key=lambda u: (urllib.parse.urlsplit(u).netloc.casefold().endswith(domain), len(u)))
    return found[:_MAX_CAREERS_PAGES]


def _fetch(url: str) -> str | None:
    try:
        body, _ = http.get_with_url(url, timeout=10, retries=1)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    except Exception:  # noqa: BLE001 -- one hostile host must not stop the run
        return None
    return body.decode("utf-8", errors="replace")[:_MAX_MARKUP]


def resolve_domain(domain: str) -> Resolution:
    home = _fetch(f"https://{domain}/") or _fetch(f"https://www.{domain}/")
    if home is None:
        return Resolution(domain, None, None, None, "C", "homepage unreachable")

    # The homepage itself often embeds the ATS widget, which saves a request.
    hit = fingerprint(home)
    if hit:
        return Resolution(domain, f"https://{domain}/", hit[0], hit[1], "A", hit[2])

    candidates = careers_candidates(home, domain)
    if not candidates:
        return Resolution(domain, None, None, None, "C", "no careers link on homepage")

    # Two hops, and both halves of that matter.
    #
    # The loop used to `return` tier B on the *first* readable careers page,
    # so candidates two and three were fetched by nobody -- the ranking that
    # put the most promising link first was the only one that ever counted.
    #
    # And the board is often a hop further in than the careers landing page.
    # `swedbank.com` links to a careers page that links to `jobs.swedbank.com`,
    # a Teamtailor board on their own domain, and one hop finds neither. Six
    # fetches is the ceiling: this runs over 19,000 domains, and an unbounded
    # crawl is a different program.
    seen: set[str] = set()
    first_ok: str | None = None
    queue, fetches = candidates, 0

    for depth in (0, 1):
        deeper: list[str] = []
        for url in queue:
            if url in seen or fetches >= _MAX_FETCHES:
                continue
            seen.add(url)
            fetches += 1
            markup = _fetch(url)
            if markup is None:
                continue
            # The careers URL, not the firm's domain: an ATS on a custom host
            # serves the board from `careers.firm.se`, and that host is the
            # token.
            hit = fingerprint(markup, url)
            if hit:
                return Resolution(domain, url, hit[0], hit[1], "A", hit[2])
            first_ok = first_ok or url
            if depth == 0:
                deeper.extend(careers_candidates(markup, domain))
        queue = deeper

    # A careers page we can read but not fingerprint is tier B, not a failure:
    # Layer 3B diffs it, which works on any page structure.
    if first_ok:
        return Resolution(domain, first_ok, None, None, "B", "careers page, no ATS fingerprint")
    return Resolution(domain, None, None, None, "C", "careers links unreachable")


def targets(connection: sqlite3.Connection, limit: int) -> list[str]:
    """Domains with no tier yet, most-corroborated firm first."""
    rows = connection.execute(
        """
        SELECT DISTINCT d.domain
        FROM domain_lookups d
        JOIN firms f ON f.name = d.query
        LEFT JOIN ats_resolution a ON a.domain = d.domain
        WHERE d.domain IS NOT NULL AND a.domain IS NULL
        ORDER BY f.source_count DESC, f.row_count DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [row["domain"] for row in rows]


def record(connection: sqlite3.Connection, results: list[Resolution]) -> None:
    timestamp = db.now()
    with connection:
        connection.executemany(
            "INSERT OR REPLACE INTO ats_resolution"
            " (domain, careers_url, ats, token, tier, evidence, checked_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (r.domain, r.careers_url, r.ats, r.token, r.tier, r.evidence, timestamp)
                for r in results
            ],
        )


def run(connection: sqlite3.Connection, limit: int, workers: int = 12) -> dict[str, int]:
    connection.executescript(SCHEMA)
    domains = targets(connection, limit)
    if not domains:
        return {}

    tally: dict[str, int] = {}
    batch: list[Resolution] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(resolve_domain, domains):
            batch.append(result)
            tally[result.tier] = tally.get(result.tier, 0) + 1
            if len(batch) >= 100:
                record(connection, batch)
                batch.clear()
    record(connection, batch)
    return tally


def summary(connection: sqlite3.Connection):
    connection.executescript(SCHEMA)
    return connection.execute(
        "SELECT tier, COUNT(*) AS n FROM ats_resolution GROUP BY tier ORDER BY tier"
    ).fetchall()


def by_ats(connection: sqlite3.Connection):
    return connection.execute(
        "SELECT ats, COUNT(*) AS n FROM ats_resolution"
        " WHERE ats IS NOT NULL GROUP BY ats ORDER BY n DESC"
    ).fetchall()
