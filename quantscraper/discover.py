"""Layer 2C -- finding the board when the careers page never names it.

Stage 5 fingerprints a domain by reading its careers page: whatever ATS host
the markup points at is the evidence, and the token falls out of the same URL.
That is the right default and it has one blind spot, which turns out to cover
most of the firms this project exists to find.

**The marquee quant firms are all tier B.** Jane Street, Optiver, Jump, DRW,
SIG, D. E. Shaw, Squarepoint, Qube, Tower Research, ExodusPoint and Man Group
were every one of them "a careers page running on nothing we recognise" -- and
every one of them has a live, public, pollable board. Three separate reasons,
none of them fixable by a better regex over the page we fetched:

  * the board is loaded by script, so no ATS host appears in the markup at all;
  * the walk settled on the wrong page -- Jane Street's stored careers URL is
    `/join-jane-street/overview/`, DRW's is a **Cloudinary image** and Man
    Group's is a **PDF**, so the roles page was never fetched;
  * the firm proxies the board through its own API host, as XTX does with
    `api.xtxcareers.com`, which is a Greenhouse board wearing a different name.

**So guess the token from the firm's name, then prove it.** This is
`domains.py` one layer down and the discipline is identical: a guess is
worthless, a guess that survives verification is evidence. It found 1,630
postings across 23 firms that were contributing nothing, including Da Vinci
Derivatives -- the firm `UNDERGROUND.md` holds up as the standing example of an
employer no public source reaches.

**Verification runs the real extractor.** Not a HEAD request, not a status
code: `extract.EXTRACTORS[ats](token)` is called and has to come back with
postings. A board this cannot read is not a board Layer 3 could have polled
either, so discovery can never record one.

**Then the postings have to name the firm**, and that is the part that carries
the weight. Two false hits inside the first sixty candidates prove why:
`greenhouse/cfm` is a live board of 9 postings whose first three are
*Account Executive - Air Distribution* -- an HVAC company, not Capital Fund
Management -- and `recruitee/radix` is somebody else's Radix entirely. Real
ATS, live feed, wrong company. That is the `heyrowan` failure from Stage 5,
which put 90 jewellery-retail postings under a credit manager's domain, and the
cure is the same one: read the postings, not just the token.

**The needle is a spaced phrase, so the token cannot prove itself.** `akuna
capital` matches the employer writing its own name in a job title; the token
`akunacapital` never matches, because folding leaves no space in it. Same guard
as `marketfrance.com`, which "verified" itself by printing the domain we had
just guessed.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import ats, db, extract, http
# Reused rather than reimplemented, deliberately. `_labels` already turns a
# firm name into the run-together and hyphenated forms a board token takes --
# "Qube Research and Technologies" gives exactly
# `quberesearchandtechnologies` -- and `_needles` already knows that one word
# out of several proves nothing. A second copy of either would drift, and the
# whole failure mode here is two sides of a comparison drifting apart.
from .domains import _labels, _needles, _token_sets, fold_text
from .models import Job
from .resolve import is_platform_domain, normalize_name

SCHEMA = """
CREATE TABLE IF NOT EXISTS board_lookups (
    query       TEXT PRIMARY KEY,  -- normalized firm name
    domain      TEXT,
    ats         TEXT,              -- NULL means looked and found nothing
    token       TEXT,
    evidence    TEXT,
    checked_at  TEXT NOT NULL
);
"""

# The ATSes whose board is addressed by a single guessable token, in the order
# they are worth trying. Greenhouse is first because it is where this industry
# actually hires: 15 of the 23 firms found on the first sweep were on it.
#
# Teamtailor and Workday are absent on purpose. A Teamtailor token is a
# hostname and a Workday token is `tenant|wdN|site`, so neither is a name you
# can guess -- and guessing a three-part compound would multiply the request
# budget by the number of site names in the world.
DISCOVERABLE: tuple[str, ...] = (
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workable",
    "recruitee",
    "personio",
    "bamboohr",
    "breezy",
)

# Descriptions are where a firm names itself -- "At Jane Street, we..." -- but
# they are also the bulk of the payload. Enough postings to be representative,
# capped so one verbose board cannot dominate the fold.
_CORROBORATION_POSTINGS = 25
_CORROBORATION_CHARS = 4_000

# Three, not four, and the difference is 165 postings. A four-character floor
# was written here on the reasoning that `_needles` will not build a needle
# shorter than four -- but that governs the *needle*, not the token, and the
# two are different strings. IMC's board is `imc` and its needle is
# `imc trading`, which is eleven characters and perfectly checkable. What
# actually stops a short token claiming a board is corroboration, not length.
#
# A single-word firm whose whole name is three characters still cannot be
# verified, because then the needle is three characters too and `_needles`
# drops it. That case fails closed, which is the right direction.
_MIN_TOKEN = 3

# Distinct tokens tried per firm, and requests across all of them.
#
# `http.py` throttles to one request per host per second and Greenhouse is a
# single host, so this is the sweep's wall clock far more than it is anyone's
# rate limit. The same kind of budget as `ats._MAX_FETCHES`, for the same
# reason -- the queue is longer than the patience available.
_MAX_TOKENS = 6
_MAX_PROBES = _MAX_TOKENS * len(DISCOVERABLE)


@dataclass(frozen=True, slots=True)
class Discovery:
    query: str
    domain: str | None
    ats: str | None
    token: str | None
    evidence: str | None

    @property
    def found(self) -> bool:
        return self.ats is not None


@dataclass(frozen=True, slots=True)
class Target:
    """One firm to search for, under every name we hold for it.

    **A firm's board is named after its full legal or brand name, and the
    roster is written in trading names.** The roster says `Akuna`, `Qube`,
    `Da Vinci`, `Old Mission` and `Squarepoint`; the boards are
    `akunacapital`, `quberesearchandtechnologies`, `davinciderivatives`,
    `oldmissioncapital` and `squarepointcapital`. Searching the short name
    alone found none of them, and the full names were sitting in `employers`
    the whole time -- `audit.py` matches roster entries to those rows already.

    `label` is what to report. `names` is every spelling worth turning into a
    token, best first, and corroboration is always checked against the *same*
    name the token came from, so a wider search does not become a looser test.
    """

    label: str
    names: tuple[str, ...]
    domain: str | None = None


def token_candidates(normalized: str) -> list[str]:
    """Board tokens worth trying for a normalized firm name, best first."""
    candidates: list[str] = []

    def add(label: str) -> None:
        if _MIN_TOKEN <= len(label) <= 40 and label not in candidates:
            candidates.append(label)

    for label in _labels(normalized):
        add(label)

    # `_labels` refuses any label of three characters or fewer, and for a
    # *domain* that is right -- a three-letter guess is overwhelmingly somebody
    # else's company, and `domains.py` has to be careful because a wrong domain
    # is a silently empty feed. A three-letter *board token* is a different
    # bet: it is only ever accepted if the postings behind it name the firm,
    # and IMC's board is `imc`, worth 165 postings.
    #
    # Only a *distinctive* word earns this. Without that guard "Capital Fund
    # Management" would offer the token `capital`, which is not a guess about
    # any particular firm.
    _, distinctive = _token_sets([token for token in normalized.split() if token])
    if distinctive:
        add("".join(distinctive))
        add(distinctive[0])

    return candidates[:_MAX_TOKENS]


def board_name(ats: str, token: str) -> str | None:
    """The name the ATS itself prints for this board, where it publishes one.

    Greenhouse is the only one of the nine that does, and it is the cleanest
    corroboration available: `/boards/janestreet` answers `{"name": "Jane
    Street"}`, which is the firm naming itself in a field we did not supply.
    """
    if ats != "greenhouse":
        return None
    try:
        payload = json.loads(
            http.get_text(f"https://boards-api.greenhouse.io/v1/boards/{token}")
        )
    except Exception:  # noqa: BLE001 -- corroboration is a bonus, never a gate
        return None
    name = payload.get("name") if isinstance(payload, dict) else None
    return name if isinstance(name, str) else None


def corroboration_text(jobs: list[Job], name: str | None) -> str:
    """Everything about a board that could name its owner, folded for matching.

    Titles, departments and descriptions only. **Never the URL**: every posting
    on a guessed board carries the guessed token in its link, so matching on
    that would be the board agreeing with the question it was asked.
    """
    parts: list[str] = [name] if name else []
    for job in jobs[:_CORROBORATION_POSTINGS]:
        parts.append(job.title or "")
        parts.append(job.department or "")
        parts.append((job.description or "")[:_CORROBORATION_CHARS])
    return fold_text(" ".join(parts))


def corroborate(normalized: str, jobs: list[Job], name: str | None) -> str | None:
    """Evidence that this board belongs to this firm, or None.

    Only *strong* needles count -- the whole name, or a two-word phrase from
    it. `_needles` grades a lone word weak whenever the firm has more than one,
    and a lone word is precisely what lets an HVAC company answer to `cfm`.
    """
    text = corroboration_text(jobs, name)
    for needle, strength in _needles(normalized):
        if strength == "strong" and f" {needle} " in text:
            where = "board is named" if name and needle in fold_text(name) else "postings name"
            return f"{len(jobs)} postings, {where} {needle!r}"
    return None


def probe(ats: str, token: str) -> list[Job] | None:
    """Postings from `(ats, token)`, or None if there is no board there.

    Runs the Layer 3 extractor rather than testing for a 200. An empty board
    is indistinguishable from an absent one for our purposes and is treated as
    absent: a token yielding nothing today would be recorded as resolved and
    then poll silence forever, which is the failure this project keeps meeting.
    """
    extractor = extract.EXTRACTORS.get(ats)
    if extractor is None:
        return None
    try:
        jobs = extractor(token)
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, KeyError,
            AttributeError, TypeError, IndexError, TimeoutError, OSError):
        return None
    except Exception:  # noqa: BLE001 -- one hostile board must not stop the run
        return None
    return jobs or None


def probe_plan(names: tuple[str, ...]) -> list[tuple[str, str]]:
    """(normalized name, token) pairs to try, best first, deduped by token.

    Names contribute in the order given, so the firm's own trading name is
    tried before a registry's rendering of it. A token reached from two names
    is probed once, under the first -- `Akuna` and `AKUNA CAPITAL LLC` both
    offer `akuna`, and probing it twice buys nothing.
    """
    plan: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in names:
        normalized = normalize_name(name)
        if not normalized:
            continue
        for token in token_candidates(normalized):
            if token in seen:
                continue
            seen.add(token)
            plan.append((normalized, token))
    return plan[:_MAX_TOKENS]


def discover_names(
    label: str, names: tuple[str, ...], domain: str | None = None
) -> Discovery:
    """Search every discoverable ATS for this firm's board. First proof wins.

    Tokens are tried outermost, so the whole ATS set is swept with the best
    guess before a worse guess is tried anywhere. The alternative -- Greenhouse
    against every token first -- spends the budget proving that a firm's least
    likely name is not on the most likely ATS.
    """
    plan = probe_plan(names)
    if not plan:
        return Discovery(label, domain, None, None, "no name normalizes to a token")

    probed = rejected = 0
    for normalized, token in plan:
        for ats in DISCOVERABLE:
            jobs = probe(ats, token)
            probed += 1
            if not jobs:
                continue
            evidence = corroborate(normalized, jobs, board_name(ats, token))
            if evidence:
                return Discovery(label, domain, ats, token, evidence)
            # A live board that does not name this firm is somebody else's.
            # Counting it is worth more than staying silent: it is how the next
            # reader finds out that `cfm` is a heating company.
            rejected += 1

    detail = f"{probed} probed over {len(plan)} token(s)"
    if rejected:
        detail += f", {rejected} live board(s) named another firm"
    return Discovery(label, domain, None, None, f"no board verified -- {detail}")


def discover_name(name: str, domain: str | None = None) -> Discovery:
    """Search for one firm under one name."""
    return discover_names(name, (name,), domain)


def record(connection: sqlite3.Connection, found: list[Discovery]) -> None:
    """Cache the lookup, and hand any board straight to Layer 3.

    Two tables because they answer different questions. `board_lookups` is
    keyed on the firm name and remembers the misses, so a second run does not
    re-probe every unresolvable firm. `ats_resolution` is keyed on the domain
    and is what `extract.targets` reads -- a discovery that never reached it
    would be a board nobody polls.
    """
    timestamp = db.now()
    with connection:
        connection.executemany(
            "INSERT OR REPLACE INTO board_lookups"
            " (query, domain, ats, token, evidence, checked_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [(d.query, d.domain, d.ats, d.token, d.evidence, timestamp) for d in found],
        )
        # **Never overwrite a board that already works.** The domain attached
        # to a discovery comes from matching a roster name against the firm
        # universe, and that match is fuzzy by design -- "Millennium" finds
        # *Millennium New Horizons Management*, a different firm with a
        # different domain. A wrong domain here would mis-attribute the
        # postings, which is cheap; replacing a live tier-A board with them
        # would lose a feed, which is not. The `WHERE` is the difference, and
        # it is the same bias as principle 3: a false split over a false merge.
        connection.executemany(
            "INSERT INTO ats_resolution"
            " (domain, careers_url, ats, token, tier, evidence, checked_at)"
            " VALUES (?, NULL, ?, ?, 'A', ?, ?)"
            " ON CONFLICT (domain) DO UPDATE SET"
            "     ats = excluded.ats,"
            "     token = excluded.token,"
            "     tier = 'A',"
            "     evidence = excluded.evidence,"
            "     checked_at = excluded.checked_at"
            " WHERE ats_resolution.tier <> 'A' OR ats_resolution.token IS NULL",
            [
                (d.domain, d.ats, d.token, f"discovered: {d.evidence}", timestamp)
                for d in found
                if d.found and d.domain
            ],
        )


def targets(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Firms with a domain and no board worth polling, most promising first.

    Three states qualify, and the third is the one that hides. Tier B and C are
    the visible queue. **Tier A with a NULL token** is a board nobody can poll
    -- it reads as a successful classification in every summary and yields
    nothing forever, and AQR sat in it with 48 live postings.
    """
    return connection.execute(
        """
        SELECT f.name, d.domain
        FROM firms f
        JOIN domain_lookups d ON d.query = f.name
        LEFT JOIN ats_resolution a ON a.domain = d.domain
        WHERE d.domain IS NOT NULL
          AND (a.domain IS NULL OR a.tier IN ('B', 'C')
               OR (a.tier = 'A' AND a.token IS NULL))
          AND NOT EXISTS (
              SELECT 1 FROM board_lookups b WHERE b.query = f.name
          )
          AND NOT EXISTS (
              SELECT 1 FROM jobs j WHERE j.domain = d.domain
          )
        ORDER BY f.source_count DESC, f.row_count DESC, f.name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def roster_targets(connection: sqlite3.Connection, roster) -> list[Target]:
    """The audit roster, under every name and domain the universe holds for it.

    The roster is the right frame to sweep first for the same reason `audit.py`
    exists: it is the only list that says what coverage was supposed to look
    like, and 147 of its 163 firms were producing no postings at all.

    **The matching is `audit.run`'s, not a second one written here.** Looking
    the domain up by `domain_lookups.query = entry.name` seemed obvious and was
    wrong twice over: that column holds the *registry's* name for a firm, so an
    exact match on the roster's trading name found a domain for 40 of 161
    entries and reported the other 121 as having none. The same join also
    supplies the full legal names, which are what the board tokens are actually
    built from.

    **Deduped, because one firm occupies several roster lines.** Jane Street is
    a line in Hong Kong, Singapore, Amsterdam and US centers; without this it
    was probed four times and printed four times.
    """
    from . import audit  # local: `audit` imports nothing from here, but this
                         # keeps the module graph one-directional on paper too

    results = audit.run(connection, [e for e in roster if not e.expected_absent])
    targets_by_key: dict[str, Target] = {}
    for result in results:
        # The roster's own spellings first -- a trading name is what a firm
        # calls its board -- then the registry renderings behind them.
        names = tuple(
            dict.fromkeys([*result.entry.candidates, *result.firms.values()])
        )
        key = normalize_name(result.entry.name) or result.entry.name
        if key in targets_by_key:
            continue
        targets_by_key[key] = Target(
            result.entry.name, names, _domain_for(connection, result)
        )
    return list(targets_by_key.values())


def _domain_for(connection: sqlite3.Connection, result) -> str | None:
    """The domain to attach a discovery to, preferring the least fuzzy source.

    The roster's own spellings are asked first because they name the firm we
    actually mean. Only if none of them resolves does this fall back to the
    firms `audit` matched, and that fallback is genuinely fuzzy: "Millennium"
    matches *Millennium New Horizons Management*, whose domain is `mnh.vc` and
    whose business is venture capital.

    The fallback is kept anyway, because a firm with no domain is a board
    nobody polls, and `record` carries the guard that makes it safe -- a
    discovery can fill an empty or tier-B slot but can never displace a board
    that already works.

    **A platform is never an answer.** Over 4,000 Form ADV filers publish a
    LinkedIn page as their website, which is why `resolve.py` keeps
    `_PLATFORM_DOMAINS` and refuses to treat one as an identity key. The same
    list is required here for a sharper reason: attaching Point72's 229
    postings to `linkedin.com` files them under a domain thousands of unrelated
    firms also claim, and the *next* discovery to land there would be blocked
    by the no-clobber guard -- so the first firm to arrive would quietly own a
    host belonging to everybody. Better no domain than that one.
    """
    for source in (result.entry.candidates, tuple(result.firms.values())):
        for name in source:
            row = connection.execute(
                "SELECT domain FROM domain_lookups"
                " WHERE query = ? AND domain IS NOT NULL",
                (name,),
            ).fetchone()
            if row and not is_platform_domain(row["domain"]):
                return row["domain"]
    return None


def run(
    connection: sqlite3.Connection,
    wanted: list[Target],
    workers: int = 6,
) -> tuple[int, int, list[Discovery]]:
    """Discover boards for `wanted`. Returns (attempted, found, what landed)."""
    connection.executescript(SCHEMA)
    # `record` writes into `ats_resolution` as well, and that table belongs to
    # `ats.py`. Discovery can legitimately run before any fingerprinting has,
    # so it must not depend on `ats` having created it first.
    connection.executescript(ats.SCHEMA)
    if not wanted:
        return 0, 0, []

    def work(target: Target) -> Discovery:
        return discover_names(target.label, target.names, target.domain)

    attempted = 0
    hits: list[Discovery] = []
    batch: list[Discovery] = []
    # Written in batches for the same reason `domains.run` is: a sweep is
    # minutes of network work and the cache is the product, not the return
    # value. Losing it to one exception means re-probing boards we already
    # asked.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for found in pool.map(work, wanted):
            attempted += 1
            batch.append(found)
            if found.found:
                hits.append(found)
            if len(batch) >= 25:
                record(connection, batch)
                batch.clear()
    record(connection, batch)
    return attempted, len(hits), hits
