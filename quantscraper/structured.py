"""Layer 3B, read: tier-B careers pages that publish schema.org `JobPosting`.

Tier B is a careers page running on no vendor anyone recognised, and `pages.py`
only watches it for change, for a reason worth keeping: a link extractor over
such a page emits the firm's own navigation as postings. Two structured
sources cannot make that mistake, because neither is a guess about what a link
means:

  * **`JobPosting` JSON-LD on the careers page.** Google for Jobs made it
    common on pages whose postings are rendered by script, which is exactly
    the tier-B failure. A navigation link is not a `JobPosting` object.
  * **The site's sitemap.** `robots.txt` names it, or `/sitemap.xml` is it.
    It lists posting URLs, and a URL only counts once its own page carries a
    `JobPosting`, so the sitemap proposes and the page proves.

A tier-B domain that yields a posting either way is promoted to tier A under
`ats = 'jsonld'`, its careers URL the token. That provenance is distinct so
the whole route can be counted, audited or withdrawn at once.
"""

from __future__ import annotations

import gzip
import json
import re
import sqlite3
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import db, http, parsing
from .models import Job
from .resolve import domain_of, is_platform_domain

NAME = "jsonld"

SCHEMA = """
CREATE TABLE IF NOT EXISTS structured_attempts (
    domain      TEXT PRIMARY KEY,
    careers_url TEXT,
    route       TEXT,             -- page | sitemap | NULL when nothing was found
    postings    INTEGER NOT NULL,
    evidence    TEXT,
    polled_at   TEXT NOT NULL
);
"""

_LD = 'script[type="application/ld+json"]'
_MAX_MARKUP = 3_000_000
_MAX_SITEMAP = 10_000_000
_MAX_CHILD_SITEMAPS = 6
# A probe proves the route on a few URLs; a poll reads the board, bounded.
PROBE_DETAILS = 3
MAX_DETAILS = 500

# The path of a posting page, in the languages of the hubs: a job word, then at
# least one more segment, since `/careers` alone is the index, not a posting.
_POSTING_PATH = re.compile(
    r"/(?:jobs?|careers?|vacanc(?:y|ies)|positions?|openings?|opportunit(?:y|ies)"
    r"|stellen(?:angebote)?|jobb|lediga-jobb|karriar|karriere|vacatures?|vacature"
    r"|offres?(?:-d-emploi)?|emplois?|ledige-stillinger|stillinger)/[^/?#]+",
    re.IGNORECASE,
)
# A sitemap whose own name says it lists postings is read before the rest.
_POSTING_SITEMAP = re.compile(r"job|career|vacanc|position|stellen|jobb|karri|vacature", re.I)
_LOC = re.compile(r"<loc>\s*([^<\s]{1,2000})\s*</loc>", re.IGNORECASE)
_SITEMAP_LINE = re.compile(r"^\s*sitemap:\s*(\S+)", re.IGNORECASE | re.MULTILINE)


def _is_posting(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    kind = entry.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return "JobPosting" in kinds


def _walk(node: object, found: list[dict], depth: int = 0) -> None:
    """Every `JobPosting` in an island: top level, `@graph`, lists, `ItemList`."""
    if depth > 6:
        return
    if isinstance(node, list):
        for item in node:
            _walk(item, found, depth + 1)
        return
    if not isinstance(node, dict):
        return
    if _is_posting(node):
        found.append(node)
        return
    for key in ("@graph", "itemListElement", "item", "mainEntity"):
        if key in node:
            _walk(node[key], found, depth + 1)


def postings_in(markup: str) -> list[dict]:
    """The `JobPosting` objects a page publishes, in page order.

    A malformed island is skipped, not raised on, for the reason
    `bodies._ld_job_posting` gives: one stray comma must not cost the others.
    """
    if not markup or len(markup) > _MAX_MARKUP or "ld+json" not in markup:
        return []
    found: list[dict] = []
    for island in parsing.soup(markup).select(_LD):
        try:
            payload = json.loads(island.string or island.get_text(), strict=False)
        except ValueError:
            continue
        _walk(payload, found)
    return found


def _text(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("name") or value.get("value")
    if isinstance(value, (int, float)):
        value = str(value)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _place(posting: dict) -> str | None:
    from .bodies import _ld_place  # the one reader of `jobLocation` there is

    place = _ld_place(posting)
    if place:
        return place
    if str(posting.get("jobLocationType") or "").upper() == "TELECOMMUTE":
        return "Remote"
    return None


def job_from(
    token: str, posting: dict, page_url: str, *, listing: bool = True
) -> Job | None:
    """One `JobPosting` as a `Job`, or None when it has no title.

    `listing` says whether `page_url` lists postings (the careers page) or is
    one (a sitemap's posting page), which decides what a bare posting's
    identity is.
    """
    title = _text(posting.get("title")) or _text(posting.get("name"))
    if not title:
        return None
    url = _text(posting.get("url"))
    url = urllib.parse.urljoin(page_url, url) if url else page_url
    # A `PropertyValue` identifier names its issuer in `name` -- usually the
    # employer, the same on every posting -- and the id itself in `value`.
    # Reading `name` first collapsed Alter Domus' 208 postings into one.
    identifier = posting.get("identifier")
    if isinstance(identifier, dict):
        identifier = identifier.get("value")
    job_id = _text(identifier)
    # An identifier is only an identity if it is the posting's own. Without
    # one, the posting's URL is; and a listing page holding several postings
    # at its own URL keys each by its title, which is what tells them apart.
    if not job_id:
        job_id = url if url != page_url or not listing else f"{page_url}#{title.casefold()}"
    return Job(
        ats=NAME,
        token=token,
        job_id=job_id[:500],
        title=title[:500],
        url=url,
        location=_place(posting),
        department=_text(posting.get("occupationalCategory")),
        posted_at=(_text(posting.get("datePosted")) or "")[:10] or None,
        deadline=(_text(posting.get("validThrough")) or "")[:10] or None,
        description=parsing.text(_text(posting.get("description")), limit=60_000),
    )


def _fetch(url: str) -> str | None:
    try:
        body = http.get(url, timeout=25, retries=1)
    except Exception:  # noqa: BLE001 -- a 404, a timeout, a WAF challenge
        return None
    if url.casefold().endswith(".gz"):
        try:
            body = gzip.decompress(body[:_MAX_SITEMAP])
        except OSError:
            return None
    return body[:_MAX_SITEMAP].decode("utf-8", errors="replace")


def sitemap_postings(careers_url: str) -> list[str]:
    """Posting URLs the careers host's sitemap lists, posting sitemaps first.

    Only URLs on the careers page's own host, with a posting-shaped path. The
    host is the careers page's rather than the firm's apex: a firm whose
    careers live on `careers.firm.se` publishes their sitemap there.
    """
    parts = urllib.parse.urlsplit(careers_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    host = parts.netloc.casefold().removeprefix("www.")
    robots = _fetch(f"{origin}/robots.txt") or ""
    queue = _SITEMAP_LINE.findall(robots)[:_MAX_CHILD_SITEMAPS] or [f"{origin}/sitemap.xml"]
    seen: set[str] = set()
    urls: list[str] = []
    reads = 0
    while queue and reads < 1 + _MAX_CHILD_SITEMAPS:
        sitemap = queue.pop(0)
        if sitemap in seen:
            continue
        seen.add(sitemap)
        reads += 1
        xml = _fetch(sitemap)
        if not xml:
            continue
        locs = _LOC.findall(xml)
        if "<sitemapindex" in xml[:2000].casefold():
            children = sorted(locs, key=lambda loc: not _POSTING_SITEMAP.search(loc))
            queue.extend(child for child in children if child not in seen)
            continue
        for loc in locs:
            target = urllib.parse.urlsplit(loc)
            if target.netloc.casefold().removeprefix("www.") != host:
                continue
            if _POSTING_PATH.search(target.path) and loc not in urls:
                urls.append(loc)
    return urls


@dataclass(slots=True)
class Read:
    route: str | None = None
    jobs: list[Job] = field(default_factory=list)
    evidence: str | None = None


def read_board(careers_url: str, *, details: int = MAX_DETAILS) -> Read:
    """Postings from the careers page's JSON-LD, else from its sitemap."""
    token = careers_url
    markup = _fetch(careers_url)
    if markup:
        postings = postings_in(markup)
        if not one_employer(postings):
            return Read(evidence=f"page postings name {len(_employers(postings))} employers")
        jobs = [job for posting in postings
                if (job := job_from(token, posting, careers_url))]
        if jobs:
            return Read("page", _unique(jobs), f"{len(jobs)} JobPosting on the careers page")
    candidates = sitemap_postings(careers_url)
    if not candidates:
        return Read(evidence="no JobPosting on the page and no posting URLs in a sitemap")
    jobs: list[Job] = []
    seen_postings: list[dict] = []
    proved = 0
    for url in sample(candidates, details):
        page = _fetch(url)
        postings = postings_in(page or "")
        seen_postings.extend(postings)
        found = [job for posting in postings
                 if (job := job_from(token, posting, url, listing=False))]
        proved += bool(found)
        jobs.extend(found)
    if not one_employer(seen_postings):
        return Read(evidence=f"sitemap postings name {len(_employers(seen_postings))} employers")
    if not jobs:
        return Read(evidence=f"{len(candidates)} sitemap URLs, none carrying a JobPosting")
    return Read(
        "sitemap", _unique(jobs),
        f"{proved} of {min(len(candidates), details)} sitemap URLs carry a JobPosting"
        f" ({len(candidates)} listed)",
    )


def sample(urls: list[str], size: int) -> list[str]:
    """`size` URLs spread evenly over `urls`, first and last included.

    A sitemap is often grouped by company, so the first few URLs of a venture
    firm's portfolio board are all one portfolio company and pass the
    one-employer test that the whole list fails -- `jobs.25madison.com` did.
    """
    if len(urls) <= size:
        return list(urls)
    if size == 1:
        return urls[:1]
    step = (len(urls) - 1) / (size - 1)
    return [urls[round(index * step)] for index in range(size)]


def _unique(jobs: list[Job]) -> list[Job]:
    return list({job.job_id: job for job in jobs}.values())


def read(token: str) -> list[Job]:
    """`extract.EXTRACTORS['jsonld']`: the board behind one careers URL.

    A board found on a sample can fail the screens on the whole list. That
    raises, so `extract.run` reports it as a failed board rather than as one
    that went quiet.
    """
    found = read_board(token)
    if found.route is None and "employers" in (found.evidence or ""):
        raise ValueError(f"jsonld board {token} is an aggregator: {found.evidence}")
    return found.jobs


# ---- promoting tier B -----------------------------------------------------


def targets(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Tier-B careers pages, never-tried first, then oldest attempt."""
    connection.executescript(SCHEMA)
    return connection.execute(
        """
        SELECT a.domain, a.careers_url FROM ats_resolution a
        LEFT JOIN structured_attempts s ON s.domain = a.domain
        WHERE a.tier = 'B' AND a.careers_url IS NOT NULL
        ORDER BY s.polled_at IS NOT NULL, s.polled_at, a.domain
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def eligible(careers_url: str, domain: str | None = None) -> bool:
    """Whether a careers URL is the firm's own page.

    Not a platform, and on the firm's own site when the firm's domain is
    known. The first probe promoted `careers.allianz.com` for Allianz Capital
    Partners and `jobs.cvshealth.com` for Aetna: a parent group's whole board,
    which would file every group posting under the subsidiary.
    """
    host = domain_of(careers_url)
    if not careers_url or not host or is_platform_domain(host):
        return False
    return domain is None or host == domain or host.endswith(f".{domain}")


def _employers(postings: list[dict]) -> set[str]:
    names = set()
    for posting in postings:
        org = posting.get("hiringOrganization")
        name = _text(org) if org is not None else None
        if name:
            names.add(" ".join(name.casefold().split()))
    return names


def one_employer(postings: list[dict]) -> bool:
    """A board naming several hiring organisations is an aggregator.

    Venture firms publish their portfolio's jobs this way -- `jobs.accel.com`
    lists 20,000 -- and every one belongs to another employer.
    """
    return len(_employers(postings)) <= 1


def run(connection: sqlite3.Connection, limit: int, workers: int = 12) -> dict[str, int]:
    """Probe tier B for structured postings; promote what answers. Counts by route."""
    rows = [row for row in targets(connection, limit)]
    counts = {"probed": 0, "page": 0, "sitemap": 0, "postings": 0}

    def work(row) -> tuple[sqlite3.Row, Read]:
        if not eligible(row["careers_url"], row["domain"]):
            return row, Read(evidence="careers URL is a platform page or another site")
        try:
            return row, read_board(row["careers_url"], details=PROBE_DETAILS)
        except Exception as exc:  # noqa: BLE001 -- a hostile host must not stop the pass
            return row, Read(evidence=f"{type(exc).__name__}: {exc}")

    timestamp = db.now()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(work, rows))
    with connection:
        for row, found in results:
            counts["probed"] += 1
            connection.execute(
                "INSERT OR REPLACE INTO structured_attempts"
                " (domain, careers_url, route, postings, evidence, polled_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (row["domain"], row["careers_url"], found.route, len(found.jobs),
                 found.evidence, timestamp),
            )
            if not found.route:
                continue
            counts[found.route] += 1
            counts["postings"] += len(found.jobs)
            # Only from tier B, so a board another layer resolved meanwhile
            # is never replaced by this one.
            connection.execute(
                "UPDATE ats_resolution SET tier = 'A', ats = ?, token = ?,"
                " evidence = ?, checked_at = ? WHERE domain = ? AND tier = 'B'",
                (NAME, row["careers_url"], f"structured data: {found.evidence}",
                 timestamp, row["domain"]),
            )
    return counts
