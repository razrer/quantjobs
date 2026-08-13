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

# Registries report country in their own language and format: AFM says
# "Nederland", the SEC says "United States", Eurex says "DE". Only the countries
# a hub maps to need translating -- everything else is irrelevant here.
_COUNTRY_CODES = {
    "se": "SE", "sweden": "SE", "sverige": "SE", "zweden": "SE",
    "dk": "DK", "denmark": "DK", "danmark": "DK", "denemarken": "DK",
    "nl": "NL", "netherlands": "NL", "the netherlands": "NL", "nederland": "NL",
    "ch": "CH", "switzerland": "CH", "schweiz": "CH", "zwitserland": "CH",
    "ae": "AE", "united arab emirates": "AE",
    "verenigde arabische emiraten": "AE",
    "hk": "HK", "hong kong": "HK", "hongkong": "HK",
    "sg": "SG", "singapore": "SG",
    "gb": "GB", "uk": "GB", "united kingdom": "GB", "great britain": "GB",
    "verenigd koninkrijk": "GB", "groot brittannie": "GB",
    "de": "DE", "germany": "DE", "deutschland": "DE", "duitsland": "DE",
    "cn": "CN", "china": "CN", "people's republic of china": "CN",
    "us": "US", "usa": "US", "united states": "US",
    "united states of america": "US", "verenigde staten": "US",
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
        if value:
            code = _COUNTRY_CODES.get(value.strip().casefold())
            if code:
                return code
    return None


def _index(rows: list[sqlite3.Row]) -> dict[str, list[tuple[str, sqlite3.Row]]]:
    """Employer rows bucketed by the first token of their normalized name.

    Prefix matching has to scan candidates, and bucketing keeps that scan to the
    handful of rows that could possibly match rather than all 30,000.
    """
    buckets: dict[str, list[tuple[str, sqlite3.Row]]] = {}
    for row in rows:
        normalized = normalize_name(row["name"])
        if normalized:
            buckets.setdefault(normalized.split(" ", 1)[0], []).append((normalized, row))
    return buckets


def _matches(
    candidate: str, buckets: dict[str, list[tuple[str, sqlite3.Row]]]
) -> list[sqlite3.Row]:
    """Rows whose name is, or begins with, `candidate` at a token boundary.

    "Captor" must find "Captor Fund Management AB", but the boundary is what
    keeps "Jump" off "Jumpstart Capital".
    """
    normalized = normalize_name(candidate)
    if not normalized:  # a name that survives no ASCII, e.g. the Chinese aliases
        return []
    bucket = buckets.get(normalized.split(" ", 1)[0], ())
    return [
        row
        for name, row in bucket
        if name == normalized or name.startswith(f"{normalized} ")
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
                    names = ", ".join(sorted(set(result.firms.values()))[:3])
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
