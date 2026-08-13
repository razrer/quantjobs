"""Employer identity -- collapsing registry rows into real-world firms.

One company occupies several rows: Jane Street appears in four registries, and
Tower Research trades as "LATOUR TRADING LLC". Left alone that multiplies every
downstream step -- resolving one domain four times, polling one careers feed
four times, emitting one job four times.

Rows are grouped by deterministic keys. Two rows sharing *any* key are the same
firm, so agreement on a strong identifier (LEI, CRD) merges names that look
nothing alike, and identical names merge sources that share no identifier.

`employers` is never modified. `firms` is rebuilt from scratch each run, so this
logic can be improved and re-run without re-scraping anything.

**Bias to false splits.** A duplicate firm costs a second of reading; a wrong
merge silently deletes an employer, which is the most expensive mistake here.
So normalization strips legal forms and nothing else -- "Capital Fund
Management" must not become "Fund Management".
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter

SCHEMA = """
DROP TABLE IF EXISTS firms;
DROP TABLE IF EXISTS firm_members;

CREATE TABLE firms (
    firm_id       TEXT PRIMARY KEY,  -- strongest key the group agreed on
    name          TEXT NOT NULL,
    city          TEXT,
    country       TEXT,
    website       TEXT,
    source_count  INTEGER NOT NULL,  -- registries that saw this firm
    row_count     INTEGER NOT NULL
);

CREATE TABLE firm_members (
    firm_id    TEXT NOT NULL,
    source     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

-- The primary key answers "which firm is this row in?"; this answers "which
-- rows is this firm made of?", which is the direction every question about
-- coverage per source asks, and it is a self-join without the index.
CREATE INDEX firm_members_by_firm ON firm_members (firm_id);
"""

# Trailing legal-form tokens. Only these are stripped -- anything that
# distinguishes one firm from another has to survive normalization.
_LEGAL_FORMS = {
    "ab", "ag", "aps", "as", "bv", "co", "corp", "corporation", "gmbh", "inc",
    "incorporated", "kb", "kg", "llc", "llp", "lp", "ltd", "limited", "nv",
    "oy", "oyj", "plc", "pte", "pty", "sa", "sarl", "sas", "se", "spa", "srl",
    "vof",
}

# A LEI is 18 alphanumerics plus 2 check digits. `eurex` keys on it.
_LEI = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")

_SEC_SOURCES = {"sec_adv", "sec_bd"}  # both key on Organization CRD#

# Domains that identify a *platform*, not a firm. Over 4,000 Form ADV filers
# give a LinkedIn page as their "Website Address", so treating these as identity
# keys merges most of the long tail into a single firm.
_PLATFORM_DOMAINS = {
    "facebook.com", "instagram.com", "linkedin.com", "medium.com",
    "spotify.com", "tiktok.com", "twitter.com", "vimeo.com", "x.com",
    "youtube.com",
}

# Backstop for platforms not listed above. A domain shared by more than this
# many distinct firm names is a host, not an identifier. Set generously: real
# corporate groups share a domain across a dozen or so entities (Man Group's
# man.com covers 13) and those merges are correct.
_MAX_FIRMS_PER_DOMAIN = 25

# Corporate groups whose entities no deterministic key connects, because the
# legal names diverge and the registries carry no website for them. Each entry
# is one real employer: a canonical name and the normalized name-prefixes that
# belong to it.
#
# Hand-curated and expected to grow. Keep prefixes specific -- a short prefix
# will over-merge. Note Citadel is deliberately absent: Citadel and Citadel
# Securities are separate employers with separate careers pages.
CORPORATE_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Hudson River Trading", ("hudson river trading", "hrt financial", "hrt execution")),
    ("Tower Research Capital", ("tower research capital", "latour trading")),
    ("Jane Street", ("jane street",)),
    ("Optiver", ("optiver",)),
    ("IMC Trading", ("imc trading", "imc securities", "imc execution", "imc financial")),
    ("Flow Traders", ("flow traders",)),
    ("DRW", ("drw ",)),
    ("Jump Trading", ("jump trading",)),
    ("XTX Markets", ("xtx ",)),
    ("Susquehanna", ("susquehanna", "sig brokerage")),
    ("Radix Trading", ("radix trading",)),
    ("Headlands Technologies", ("headlands technologies",)),
    ("Eagle Seven", ("eagle seven",)),
    # Not a bare "maven " prefix: Maven Capital Partners is an unrelated UK
    # private-equity firm, and a short prefix silently absorbed it.
    (
        "Maven Securities",
        ("maven securities", "maven derivatives", "maven global markets", "maven europe"),
    ),
    ("Mako", ("mako ",)),
    ("Webb Traders", ("webb traders",)),
    ("All Options", ("all options",)),
    ("Virtu Financial", ("virtu ",)),
    ("Two Sigma", ("two sigma",)),
    ("Lynx Asset Management", ("lynx asset management",)),
]


def normalize_name(name: str) -> str:
    """Lowercase, punctuation-free, with trailing legal forms removed."""
    # Fold "B.V." and "A/S" into single tokens before splitting on punctuation,
    # so they are recognised as legal forms rather than stray letters.
    folded = name.casefold().replace(".", "").replace("/", "")
    tokens = re.sub(r"[^a-z0-9]+", " ", folded).split()
    while tokens and tokens[-1] in _LEGAL_FORMS:
        tokens.pop()
    return " ".join(tokens)


# Registries report country in their own language and format: AFM says
# "Nederland", the SEC "United States", Eurex "DE". Only the countries something
# downstream keys on need translating -- everything else stays as reported.
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


def country_code(value: str | None) -> str | None:
    """ISO code for a registry's country string, or None if unrecognised."""
    if not value:
        return None
    return _COUNTRY_CODES.get(value.strip().casefold())


def domain_of(website: str | None) -> str | None:
    """Registrable host of `website`, or None if there isn't one."""
    if not website:
        return None
    host = re.sub(r"^\w+://", "", website.strip().casefold()).split("/")[0]
    host = host.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host if "." in host else None


def _group_for(normalized: str) -> str | None:
    for canonical, prefixes in CORPORATE_GROUPS:
        if any(normalized.startswith(prefix) for prefix in prefixes):
            return canonical
    return None


def non_identifying_domains(rows: list[sqlite3.Row]) -> set[str]:
    """Domains that must not be used as identity keys."""
    names_by_domain: dict[str, set[str]] = {}
    for row in rows:
        domain = domain_of(row["website"])
        if domain:
            names_by_domain.setdefault(domain, set()).add(normalize_name(row["name"]))

    def is_platform(domain: str) -> bool:
        return any(
            domain == known or domain.endswith(f".{known}")
            for known in _PLATFORM_DOMAINS
        )

    return {
        domain
        for domain, names in names_by_domain.items()
        if is_platform(domain) or len(names) > _MAX_FIRMS_PER_DOMAIN
    }


def identity_keys(row: sqlite3.Row, blocked_domains: set[str] = frozenset()) -> list[str]:
    """Every identifier this row asserts, strongest first.

    Rows sharing any one of these are treated as the same firm.
    """
    keys = []
    normalized = normalize_name(row["name"])

    group = _group_for(normalized)
    if group:
        keys.append(f"group:{group}")
    if _LEI.match(row["source_id"].upper()):
        keys.append(f"lei:{row['source_id'].upper()}")
    if row["source"] in _SEC_SOURCES and row["source_id"].isdigit():
        keys.append(f"crd:{int(row['source_id'])}")
    domain = domain_of(row["website"])
    if domain and domain not in blocked_domains:
        keys.append(f"domain:{domain}")
    if normalized:
        keys.append(f"name:{normalized}")
    return keys


class _Groups:
    """Union-find over identity keys."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, key: str) -> str:
        self._parent.setdefault(key, key)
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[key] != root:  # path compression
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, keys: list[str]) -> None:
        roots = [self.find(key) for key in keys]
        for root in roots[1:]:
            self._parent[root] = roots[0]


def _best(values: list[str | None]) -> str | None:
    """Most common non-empty value, ties broken by taking the shortest."""
    present = [value for value in values if value]
    if not present:
        return None
    counts = Counter(present)
    return min(counts, key=lambda value: (-counts[value], len(value), value))


def _firm_id(keys: set[str]) -> str:
    """The strongest key in a group, so the id is stable and meaningful."""
    for prefix in ("group:", "lei:", "crd:", "domain:", "name:"):
        matching = sorted(key for key in keys if key.startswith(prefix))
        if matching:
            return matching[0]
    raise AssertionError("a firm always has at least one key")


def build_firms(connection: sqlite3.Connection) -> tuple[int, int]:
    """Rebuild `firms` and `firm_members`. Returns (firms, employer rows)."""
    rows = connection.execute(
        "SELECT source, source_id, name, city, country, website FROM employers"
    ).fetchall()

    blocked = non_identifying_domains(rows)

    groups = _Groups()
    row_keys = []
    for row in rows:
        keys = identity_keys(row, blocked)
        groups.union(keys)
        row_keys.append((row, keys))

    members: dict[str, list[sqlite3.Row]] = {}
    keys_by_root: dict[str, set[str]] = {}
    for row, keys in row_keys:
        root = groups.find(keys[0])
        members.setdefault(root, []).append(row)
        keys_by_root.setdefault(root, set()).update(keys)

    firm_rows = []
    member_rows = []
    for root, grouped in members.items():
        firm_id = _firm_id(keys_by_root[root])
        canonical = _group_for(normalize_name(grouped[0]["name"]))
        firm_rows.append(
            (
                firm_id,
                canonical or _best([row["name"] for row in grouped]),
                _best([row["city"] for row in grouped]),
                _best([row["country"] for row in grouped]),
                _best([row["website"] for row in grouped]),
                len({row["source"] for row in grouped}),
                len(grouped),
            )
        )
        member_rows.extend(
            (firm_id, row["source"], row["source_id"]) for row in grouped
        )

    # One transaction for the whole rebuild -- committing per firm means tens of
    # thousands of fsyncs and takes minutes instead of seconds.
    connection.executescript(SCHEMA)
    with connection:
        connection.executemany(
            "INSERT INTO firms (firm_id, name, city, country, website,"
            " source_count, row_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
            firm_rows,
        )
        connection.executemany(
            "INSERT INTO firm_members (firm_id, source, source_id) VALUES (?, ?, ?)",
            member_rows,
        )

    return len(members), len(rows)
