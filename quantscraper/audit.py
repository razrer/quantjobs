"""Coverage audit -- does the universe contain the firms we already know exist?

Coverage was previously checked with `grep`s typed fresh each time, which is not
repeatable and is the direct cause of at least one overstated claim about what
was missing. This replaces that with a checked-in fixture (`roster.csv`) and a
command that answers the same question the same way every time.

**The roster measures coverage; it never defines it.** A firm's absence from
`roster.csv` says nothing about whether it belongs in the universe. Nothing here
reads or writes `employers`.

Two numbers per hub, because one of them is easy to overstate:

*present* -- the firm is in the universe under some name.
*local*   -- some row places the firm in that hub's country.

The gap between them is the interesting part. Nearly every Hong Kong roster firm
is "present" purely because it holds a US registration, and only one is "local",
because no HK register has been ingested. Reporting the first number alone would
claim Hong Kong is solved.

**A false hit is the failure mode to guard against**, because it hides a miss.
So the report prints the employer names each entry actually matched: a bare
"Grasshopper" matching `GRASSHOPPER ESCAPEMENT, LLC` is only visible if the
matched name is shown, and that one reported Singapore as covered when it was
not. Roster names are kept specific for the same reason.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .resolve import country_code as _iso_country
from .resolve import normalize_name

ROSTER_PATH = Path(__file__).with_name("roster.csv")

FOCUS = "focus"

# Where each hub is, so "did a registry covering this hub see the firm?" has an
# answer. Hubs are offices; countries are what registries are organised by.
HUB_COUNTRY = {
    "Stockholm": "SE",
    "Copenhagen": "DK",
    "Amsterdam": "NL",
    "Switzerland": "CH",
    "Dubai": "AE",
    "Hong Kong": "HK",
    "Singapore": "SG",
    "London": "GB",
    "Frankfurt": "DE",
    "Shanghai": "CN",
    "US centers": "US",
}



@dataclass(frozen=True, slots=True)
class Entry:
    """One roster line: a firm we assert should be findable."""

    hub: str
    priority: str
    name: str
    aliases: tuple[str, ...]
    status: str  # active | stale | absent
    note: str

    @property
    def expected_absent(self) -> bool:
        """Stale and never-existed entries are not misses."""
        return self.status != "active"

    @property
    def candidates(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(slots=True)
class Result:
    entry: Entry
    # firm_id -> the employer name that matched. Keyed on the firm so an entry
    # matching six rows of one firm counts once, but showing the raw name,
    # because that is what makes a wrong match visible on sight.
    firms: dict[str, str] = field(default_factory=dict)
    sources: set[str] = field(default_factory=set)
    local: bool = False

    @property
    def present(self) -> bool:
        return bool(self.firms)


def load_roster(path: Path = ROSTER_PATH) -> list[Entry]:
    with path.open(encoding="utf-8", newline="") as handle:
        # `note` is last and is prose, so an unquoted comma in it would silently
        # truncate the reason a firm is missing. Rejoining the overflow makes
        # quoting optional rather than a trap for whoever edits this file.
        reader = csv.DictReader(
            (line for line in handle if not line.lstrip().startswith("#")),
            restkey="_overflow",
            restval="",
        )
        return [
            Entry(
                hub=row["hub"].strip(),
                priority=row["priority"].strip(),
                name=row["name"].strip(),
                aliases=tuple(
                    alias.strip()
                    for alias in (row["aliases"] or "").split("|")
                    if alias.strip()
                ),
                status=(row["status"] or "active").strip() or "active",
                note=",".join(
                    [row["note"] or "", *(row.get("_overflow") or [])]
                ).strip(","),
            )
            for row in reader
            if row["name"].strip()
        ]


def country_code(row: sqlite3.Row) -> str | None:
    """ISO country of an employer row, or None if it doesn't assert one.

    Falls back to the registry's jurisdiction, which is a country for national
    regulators and "EU"/"manual" for the exchange lists and the seed file --
    neither of which localises a firm to a hub.
    """
    for value in (row["country"], row["jurisdiction"]):
        code = _iso_country(value)
        if code:
            return code
    return None


def _index(rows: list[sqlite3.Row]) -> dict[str, list[tuple[str, sqlite3.Row]]]:
    """Employer rows bucketed by each token of their normalized name.

    Matching has to scan candidates, and bucketing keeps that scan to the rows
    that could possibly match rather than all 58,000. A row appears under every
    one of its tokens because a roster name can start at any of them.
    """
    buckets: dict[str, list[tuple[str, sqlite3.Row]]] = {}
    for row in rows:
        normalized = normalize_name(row["name"])
        for token in set(normalized.split()):
            buckets.setdefault(token, []).append((normalized, row))
    return buckets


def _matches(
    candidate: str, buckets: dict[str, list[tuple[str, sqlite3.Row]]]
) -> list[sqlite3.Row]:
    """Rows whose name contains `candidate` as a whole run of tokens.

    Not anchored to the start, because registries prepend qualifiers to legal
    names and anchoring silently loses them: `Bank Julius Bär & Co. AG` was in
    the universe from the day Eurex was added, and an anchored match reported
    Julius Baer missing for all of it. Same for `Fondsmæglerselskabet Maj
    Invest A/S`.

    Token alignment is what keeps this honest -- "Jump" finds "Jump Trading"
    but not "Jumpstart Capital".
    """
    normalized = normalize_name(candidate)
    if not normalized:  # a name that survives no ASCII, e.g. the Chinese aliases
        return []
    tokens = normalized.split()
    needle = f" {normalized} "
    return [
        row
        for name, row in buckets.get(tokens[0], ())
        if needle in f" {name} "
    ]


def run(connection: sqlite3.Connection, roster: list[Entry]) -> list[Result]:
    rows = connection.execute(
        "SELECT e.source, e.name, e.country, e.jurisdiction, m.firm_id"
        " FROM employers e"
        " LEFT JOIN firm_members m"
        "   ON m.source = e.source AND m.source_id = e.source_id"
    ).fetchall()

    buckets = _index(rows)
    results = []
    for entry in roster:
        result = Result(entry)
        wanted = HUB_COUNTRY.get(entry.hub)
        for candidate in entry.candidates:
            for row in _matches(candidate, buckets):
                result.firms.setdefault(row["firm_id"] or row["name"], row["name"])
                result.sources.add(row["source"])
                if wanted and country_code(row) == wanted:
                    result.local = True
        results.append(result)
    return results


def _hubs(results: list[Result], priority: str) -> list[str]:
    """Hubs of the given priority, in roster order."""
    return list(
        dict.fromkeys(r.entry.hub for r in results if r.entry.priority == priority)
    )


def format_report(results: list[Result], verbose: bool = False) -> str:
    lines = [
        f"coverage audit -- {len(results)} roster entries, "
        f"{len({r.entry.hub for r in results})} hubs",
        "",
        "present = the firm is in the universe under some name",
        "local   = some row places the firm in that hub's country",
        "",
    ]

    for priority in (FOCUS, "deprioritized"):
        hubs = _hubs(results, priority)
        if not hubs:
            continue
        lines.append(f"{priority} hubs")
        for hub in hubs:
            audited = [
                r
                for r in results
                if r.entry.hub == hub and not r.entry.expected_absent
            ]
            present = [r for r in audited if r.present]
            local = [r for r in present if r.local]
            rate = 100 * len(present) / len(audited) if audited else 0.0
            lines.append(
                f"  {hub:<12s} present {len(present):3d}/{len(audited):<3d}"
                f" ({rate:3.0f}%)   local {len(local):3d}"
            )
            for result in audited:
                if not result.present:
                    reason = result.entry.note or "no reason recorded -- investigate"
                    lines.append(f"    miss  {result.entry.name:<24s} {reason}")
            if verbose:
                for result in sorted(present, key=lambda r: r.entry.name):
                    # Shortest first, not alphabetical. A big group's matches are
                    # mostly funds carrying the house name ("AMUNDI ETF
                    # NASDAQ-100"), and the shortest name is almost always the
                    # operating entity -- which is the one worth eyeballing.
                    names = ", ".join(
                        sorted(set(result.firms.values()), key=lambda n: (len(n), n))[:3]
                    )
                    # A high entity count is usually correct, not a false split:
                    # Stage 1 deliberately keeps UBS's 44 legal entities apart.
                    entities = f"  [{len(result.firms)} entities]" if len(result.firms) > 1 else ""
                    lines.append(
                        f"    {' ' if result.local else '~'} {result.entry.name:<24s}"
                        f" {names}  ({', '.join(sorted(result.sources))}){entities}"
                    )
        lines.append("")

    expected = [r for r in results if r.entry.expected_absent]
    if expected:
        lines.append("expected absent (excluded from the rates above)")
        for result in expected:
            state = "still present" if result.present else result.entry.status
            lines.append(
                f"  {result.entry.hub:<12s}{result.entry.name:<10s}"
                f" {state:<13s} {result.entry.note}"
            )
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# The other coverage question: is the firm *polled*, not merely *present*?
#
# `run` above measures the employer universe. That is not the same property as
# being in the job pipeline, and the two had drifted completely apart without
# anything saying so: every focus hub reported 100% present while 147 of the
# 163 roster firms produced no postings at all. Being in `employers` and having
# a board somebody reads are different facts, and only the first was checked.
#
# Stage 13 fixed a large part of that and the number was quoted from a
# throwaway script, which is the same "typed fresh each time" problem this
# module was written to end. It is a command now.




@dataclass(slots=True)
class PipelineResult:
    """One roster *line*, and how many postings the firm behind it contributes.

    Per line, not per firm, and that is deliberate: Jane Street occupies four
    roster lines because it hires in four hubs, and "is Hong Kong covered?" has
    to count it in Hong Kong. `discover.roster_targets` dedupes -- correctly,
    since probing one firm four times is waste -- so the two views are rejoined
    here. The headline count dedupes again; only the per-hub rates do not.
    """

    entry: Entry
    domain: str | None
    postings: int
    # How the postings were found. `domain` is the normal path -- the board was
    # reached from the firm's own host. `employer` is the path for the sources
    # whose board is not one firm's own (JobStream, MyCareersFuture), where the
    # advertiser's name is the only handle there is.
    via: str | None = None
    # Whether a board exists that Layer 3 can actually poll. This is a
    # different question from `postings` and the gap between them is the whole
    # point: Captor's careers page says "For tillfallet har vi inga lediga
    # tjanster", so it is read, understood and empty. Reporting that as a
    # coverage miss would send someone to build a reader that already exists,
    # and no amount of engineering makes a firm advertise a job it does not
    # have.
    board: bool = False

    @property
    def polled(self) -> bool:
        return self.postings > 0


def pipeline(
    connection: sqlite3.Connection, targets, roster: list[Entry]
) -> list[PipelineResult]:
    """Postings per roster line, given `discover.roster_targets`.

    `targets` is passed in rather than built here so this module keeps its one
    promise: it reads, and it imports nothing that writes.

    **Both tables are read once and matched in memory.** The obvious shape is a
    `LIKE '%name%'` per firm per spelling, which is a full scan of 157,000
    postings several hundred times over and takes minutes. The distinct
    employer names are a few thousand rows; scanning those is instant, and the
    answer is identical.
    """
    by_domain = {
        row["domain"]: row["n"]
        for row in connection.execute(
            "SELECT domain, COUNT(*) AS n FROM jobs"
            " WHERE domain IS NOT NULL GROUP BY domain"
        )
    }
    by_employer = [
        (row["employer"].casefold(), row["n"])
        for row in connection.execute(
            "SELECT employer, COUNT(*) AS n FROM jobs"
            " WHERE employer IS NOT NULL GROUP BY employer"
        )
    ]
    # Domains with a board Layer 3 can address. Guarded because this module is
    # also used before any fingerprinting has run, and a missing table is not
    # an error -- it means nothing has been resolved yet.
    pollable: set[str] = set()
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ats_resolution'"
    ).fetchone():
        pollable = {
            row["domain"]
            for row in connection.execute(
                "SELECT domain FROM ats_resolution"
                " WHERE tier = 'A' AND token IS NOT NULL"
            )
        }

    counted = {}
    for target in targets:
        postings, via = by_domain.get(target.domain or "", 0), None
        if postings:
            via = "domain"
        else:
            # Best spelling first, and the first that hits wins -- the same
            # order `discover` builds tokens in, so a firm reported as reached
            # by name was reached under a name it actually publishes.
            for name in target.names:
                folded = name.casefold()
                hits = sum(n for employer, n in by_employer if folded in employer)
                if hits:
                    postings, via = hits, "employer"
                    break
        counted[normalize_name(target.label) or target.label] = (
            target.domain,
            postings,
            via,
            target.domain in pollable,
        )

    results = []
    for entry in roster:
        if entry.expected_absent:
            continue
        domain, postings, via, board = counted.get(
            normalize_name(entry.name) or entry.name, (None, 0, None, False)
        )
        results.append(PipelineResult(entry, domain, postings, via, board))
    return results


def format_pipeline(results: list[PipelineResult]) -> str:
    """The report, focus hubs first and the misses named.

    Naming them is the whole value. A rate says how much is missing; only the
    list says *what*, and every firm on it is a specific piece of work --
    Danske Bank was on it, tier B with 139 Oracle postings behind it.
    """
    firms = {normalize_name(r.entry.name) or r.entry.name: r for r in results}
    producing = [r for r in firms.values() if r.polled]
    reached = [r for r in firms.values() if r.polled or r.board]
    lines = [
        f"job pipeline -- {len(reached)}/{len(firms)} roster firms are reached,"
        f" {len(producing)} produce postings today",
        "",
        "present (the universe) and polled (the pipeline) are different",
        "properties. `audit` alone measures the first, and every focus hub",
        "reported 100% present while the second was 16/163.",
        "",
        "  reached   = a board Layer 3 can poll, or postings already in hand",
        "  producing = that board has an opening on it right now",
        "",
        "The gap between them is not a gap in coverage. Captor's careers page",
        "says it has no vacancies -- read, understood, and empty. No amount of",
        "engineering makes a firm advertise a job it does not have; a reader",
        "buys that the day it does, the posting arrives unasked.",
        "",
        "Hub rates count roster lines, so a firm hiring in four hubs is",
        "counted in four -- the question is whether the hub is covered.",
        "",
    ]

    hubs: dict[tuple[str, str], list[PipelineResult]] = {}
    for result in results:
        hubs.setdefault((result.entry.priority, result.entry.hub), []).append(result)

    for priority in (FOCUS, "deprioritized"):
        chosen = {h: rs for (p, h), rs in hubs.items() if p == priority}
        if not chosen:
            continue
        lines.append(f"{priority} hubs")
        lines.append(f"  {'':14s}{'reached':^13s}{'producing':^13s} postings")
        for hub, rows in sorted(chosen.items(), key=lambda kv: -len(kv[1])):
            got = [r for r in rows if r.polled]
            have = [r for r in rows if r.polled or r.board]
            lines.append(
                f"  {hub:<14s}"
                f"{len(have):3d}/{len(rows):<3d}({100 * len(have) / len(rows):4.0f}%)"
                f"  {len(got):3d}/{len(rows):<3d}({100 * len(got) / len(rows):4.0f}%)"
                f"  {sum(r.postings for r in got):7,d}"
            )
        lines.append("")

    # Only firms with *no board at all* are work. A firm with a reader and no
    # openings is finished, and listing it as a miss is how a work queue fills
    # with things nobody can fix.
    missing = {
        (r.entry.hub, r.entry.name): r
        for r in results
        if not r.polled and not r.board and r.entry.priority == FOCUS
    }
    if missing:
        lines.append("focus-hub firms with no pollable board -- each is a piece of work")
        for (hub, name), result in sorted(missing.items()):
            lines.append(
                f"  {hub:<14s}{name:<32s} {result.domain or '(no domain)'}"
            )
        lines.append("")

    quiet = sorted(
        (r.entry.hub, r.entry.name)
        for r in results
        if r.board and not r.polled and r.entry.priority == FOCUS
    )
    if quiet:
        lines.append("focus-hub firms reached, with nothing posted today")
        for hub, name in quiet:
            lines.append(f"  {hub:<14s}{name}")
        lines.append("")

    return "\n".join(lines)
