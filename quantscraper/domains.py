"""Layer 2, part one -- turning a firm name into the domain it hires from.

Stage 1 gave us 58,638 firms. Almost none of them carry a website: the SEC
publishes one for 92% of its filers, and every focus-region registry publishes
none at all. Across the 34,047 firms a focus-region registry reported, 2.3% had
a domain, and 95% of even those came from a US registration rather than a local
one. So this is where the domains have to come from.

**Guessed, then verified.** A candidate domain is derived from the firm's name,
fetched, and accepted only if the page that answers actually names the firm. An
unverified guess is worse than no domain at all: it sends Layer 3 to someone
else's careers page, and the result is a silently empty job feed rather than a
visible error -- failure mode #2 in the plan, and the one this project is built
to refuse.

**The cache is keyed on the firm's name, not its id.** `firms` is rebuilt from
scratch on demand, so firm ids are not a durable handle -- keying on the name
means a rebuild costs nothing and the network work survives it. Misses are
cached too, with `domain` NULL; otherwise every run re-probes every unresolvable
firm, and most firms are unresolvable.
"""

from __future__ import annotations

import re
import sqlite3
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import db, http
from .resolve import country_code as _country_code
from .resolve import domain_of, normalize_name

SCHEMA = """
CREATE TABLE IF NOT EXISTS domain_lookups (
    query       TEXT PRIMARY KEY,  -- normalized firm name
    domain      TEXT,              -- NULL means looked and found nothing
    method      TEXT NOT NULL,
    evidence    TEXT,              -- what convinced us, for auditing a wrong one
    checked_at  TEXT NOT NULL
);
"""

# Country of the firm -> the TLDs worth trying beyond .com, in priority order.
COUNTRY_TLDS = {
    "SE": ("se",),
    "DK": ("dk",),
    "NL": ("nl",),
    "CH": ("ch",),
    "HK": ("com.hk", "hk"),
    "SG": ("com.sg", "sg"),
    "GB": ("co.uk",),
    "US": (),
}

# Words that carry no identity. A domain built from these alone would be a
# coin flip -- "assetmanagement.com" is somebody, but not the firm we asked for.
_GENERIC = {
    "aktiebolag", "advisors", "advisory", "asset", "assets", "bank", "capital",
    "company", "ec", "equity", "finance", "financial", "fund", "funds", "global",
    "group", "holding", "holdings", "international", "invest", "investment",
    "investments", "limited", "management", "markets", "partners", "pension",
    "private", "securities", "services", "trading", "ventures", "wealth",
}

# Grammar, not identity. Without these "Australia and New Zealand Banking Group"
# takes "australia and" as its distinguishing phrase, which australia.com --
# the tourism board -- naturally contains.
_STOPWORDS = {
    "and", "of", "the", "for", "in", "on", "at", "og", "och", "en", "et",
    "de", "der", "den", "des", "du", "la", "le", "les", "van", "von",
}

# Hosts that answer for anything and mean nothing.
_PARKED = re.compile(
    r"domain (is )?(for sale|parking)|buy this domain|godaddy|sedo\.com"
    r"|this domain (may be|is) for sale|under construction",
    re.IGNORECASE,
)

_TAG = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Lookup:
    query: str
    domain: str | None
    method: str
    evidence: str | None


def _token_sets(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Two views of a firm name.

    `identity` drops only grammar, so "Citadel Securities" keeps the word that
    distinguishes it from "Citadel". `distinctive` also drops the words shared
    by half the industry, which is what makes a usable one-word brand guess.
    """
    identity = [token for token in tokens if token not in _STOPWORDS]
    distinctive = [token for token in identity if token not in _GENERIC]
    return identity, distinctive


def _labels(normalized: str) -> list[str]:
    """Domain labels worth trying for a normalized firm name, best first."""
    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return []

    identity, distinctive = _token_sets(tokens)
    labels: list[str] = []

    def add(label: str) -> None:
        if 3 < len(label) <= 40 and label not in labels:
            labels.append(label)

    # Most specific first, and the bare first word *last*. Trying it earlier
    # resolved "Citadel Securities GCS (Ireland) Limited" to citadel.com --
    # a different employer with a different careers page, and exactly the merge
    # the roster keeps apart -- before citadelsecurities.com was ever tried.
    add("".join(tokens))
    # The first two words *as written*. "Securities" is a generic word, so the
    # distinctive-token forms below skip it -- and skipping it is what loses
    # citadelsecurities.com, the one domain that tells the two Citadels apart.
    if len(identity) > 2:
        add("".join(identity[:2]))
    if distinctive:
        add("".join(distinctive))
        if len(distinctive) > 1:
            add("".join(distinctive[:2]))
            add("-".join(distinctive[:2]))
        add(distinctive[0])
    return labels[:5]


def candidates(normalized: str, country: str | None) -> list[str]:
    tlds = ("com", *COUNTRY_TLDS.get((country or "").upper(), ()))
    return [f"{label}.{tld}" for label in _labels(normalized) for tld in tlds]


def _page_text(body: bytes) -> str:
    """Visible page text, folded exactly the way firm names are.

    Both sides have to be folded the same way or nothing matches: the register
    says "J.P. Morgan SE", which normalizes to "jp morgan", and the raw page
    says "J.P. Morgan". Folding only one side compares two different alphabets.
    """
    text = _TAG.sub(" ", body.decode("utf-8", errors="replace"))
    folded = text.casefold().replace(".", "").replace("/", "")
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split()) + " "


def _needles(normalized: str) -> list[tuple[str, str]]:
    """Phrases that would convince us, as (needle, strength).

    A single word is only convincing when it is the firm's whole name. Accepting
    one word out of several is what produced australia.com for "Australia and
    New Zealand Banking Group", societe.com for "Societe Generale" and
    marketfrance.com for "Market Securities France": the page contains the word,
    and the word means nothing on its own.

    Multi-word firms can still match one word, but the result is recorded as
    *weak* rather than counted as resolved -- nomura.com really is the right
    domain for "Nomura Financial Products Europe GmbH", and throwing that away
    would be its own kind of loss.
    """
    tokens = [token for token in normalized.split() if token]
    identity, distinctive = _token_sets(tokens)
    identity = identity or tokens
    distinctive = distinctive or identity

    # Spaced phrases only. A run-together needle matches the page printing its
    # own address, and the address is the thing we guessed -- marketfrance.com
    # "proved" itself that way for "Market Securities France SA".
    needles = [(" ".join(tokens), "strong")]
    if len(identity) > 1:
        needles.append((" ".join(identity[:2]), "strong"))
    if len(distinctive) > 1:
        needles.append((" ".join(distinctive[:2]), "strong"))
    needles.append((distinctive[0], "strong" if len(tokens) == 1 else "weak"))
    return [(needle, strength) for needle, strength in needles if len(needle) > 3]


def _corroborators(normalized: str, needle: str) -> list[str]:
    """Identity tokens the needle leaves out.

    A two-word fragment is 74% of every strong match, and it is where the
    grade fails: *brown brothers*, *nova scotia* and *four seasons* are
    ordinary English, so a page containing one proves nothing. `_GENERIC`
    only ever asked whether a word is generic to the *industry*, never
    whether it is generic to the *language*, and no list of finance words
    can answer the second question.

    What the fragment discards is the answer. "Brown Brothers Harriman"
    throws away the word that identifies it, and the paint distributor's page
    that owns *brown brothers* has no reason to say *harriman*.

    Only *distinctive* leftovers count. Demanding an industry word back --
    "Partners Group Life II (EUR) S.C.A., SICAV" wanting *life* on
    `partnersgroup.com` -- downgrades correct matches wholesale, because a
    fund vehicle's structure words appear nowhere on its manager's site.
    Short tokens are skipped too: a page matching "ii" or "sa" is chance.
    """
    tokens = [token for token in normalized.split() if token]
    _, distinctive = _token_sets(tokens)
    used = set(needle.split())
    return [t for t in distinctive if t not in used and len(t) > 2]


def verify(candidate: str, normalized: str) -> tuple[str, str, str] | None:
    """Fetch `candidate` and decide whether it belongs to this firm.

    Returns (domain, strength, evidence) or None. The bar is that the page names
    the firm -- a live host alone proves only that somebody owns the name.
    """

    for url in (f"https://{candidate}/", f"https://www.{candidate}/"):
        try:
            body, landed = http.get_with_url(url, timeout=8, retries=1)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            continue
        except Exception:  # noqa: BLE001 -- a hostile host must not stop the run
            continue

        text = _page_text(body)
        if not text or _PARKED.search(text):
            continue

        for needle, strength in _needles(normalized):
            # Padded, so "marex" does not match "marexpo".
            if f" {needle} " not in text:
                continue

            # A fragment needs a second, independent word from the name
            # somewhere on the page. Without one the grade is weak: held with
            # its evidence, not counted, and not handed to Layer 3.
            note = ""
            rest = _corroborators(normalized, needle)
            if strength == "strong" and rest:
                found = next((t for t in rest if f" {t} " in text), None)
                if found is None:
                    strength = "weak"
                    note = f", but no {'/'.join(rest[:3])}"
                else:
                    note = f" and {found!r}"

            # Record where we landed, not where we knocked.
            return (
                domain_of(landed) or candidate,
                strength,
                f"{landed} names {needle!r}{note}",
            )
    return None


def resolve_name(normalized: str, country: str | None) -> Lookup:
    """Best candidate for a name. A strong match wins immediately; a weak one
    is held in case nothing better turns up."""
    weak: Lookup | None = None
    for candidate in candidates(normalized, country):
        hit = verify(candidate, normalized)
        if not hit:
            continue
        domain, strength, evidence = hit
        if strength == "strong":
            return Lookup(normalized, domain, "name-strong", evidence)
        weak = weak or Lookup(normalized, domain, "name-weak", evidence)
    return weak or Lookup(normalized, None, "unresolved", "no candidate verified")


def targets(connection: sqlite3.Connection, sources: tuple[str, ...], limit: int):
    """Firms worth resolving next, most promising first.

    Ordered by how many registries saw the firm, then how many rows it has.
    That is a priority, never a filter: a firm several registries report is far
    more likely to be an operating company than a fund share class, and the
    Danish register alone contributes 25,549 rows that are mostly vehicles.
    """
    placeholders = ",".join("?" * len(sources))
    return connection.execute(
        f"""
        SELECT f.firm_id, f.name, f.country, f.website
        FROM firms f
        WHERE f.website IS NULL
          AND EXISTS (
              SELECT 1 FROM firm_members m
              WHERE m.firm_id = f.firm_id AND m.source IN ({placeholders})
          )
          AND NOT EXISTS (
              SELECT 1 FROM domain_lookups d
              WHERE d.query = f.name
          )
        ORDER BY f.source_count DESC, f.row_count DESC, f.name
        LIMIT ?
        """,
        (*sources, limit),
    ).fetchall()


def record(connection: sqlite3.Connection, lookups: list[Lookup]) -> None:
    timestamp = db.now()
    with connection:
        connection.executemany(
            "INSERT OR REPLACE INTO domain_lookups"
            " (query, domain, method, evidence, checked_at) VALUES (?, ?, ?, ?, ?)",
            [(l.query, l.domain, l.method, l.evidence, timestamp) for l in lookups],
        )


def harvest_registry_domains(connection: sqlite3.Connection) -> int:
    """Seed the cache from websites the registries already published.

    Free, and it means the guesser never spends a request on a firm whose
    domain we were handed.
    """
    rows = connection.execute(
        "SELECT name, website FROM firms WHERE website IS NOT NULL"
    ).fetchall()
    lookups = []
    for row in rows:
        domain = domain_of(row["website"])
        if domain:
            # Keyed on the firm's stored name, the same key `targets` and
            # `coverage` join on. Normalizing here instead would make the cache
            # unjoinable from SQL, which is where it is read.
            lookups.append(Lookup(row["name"], domain, "registry", row["website"]))
    record(connection, lookups)
    return len(lookups)


def regrade_targets(connection: sqlite3.Connection, limit: int):
    """Strong matches graded before the corroboration rule existed.

    Ordered oldest first, so an interrupted pass resumes where it stopped
    rather than re-reading the rows it just refreshed.
    """
    return connection.execute(
        "SELECT query, domain FROM domain_lookups"
        " WHERE method = 'name-strong' AND evidence NOT LIKE '%, but no %'"
        "   AND evidence NOT LIKE '% and ''%'"
        " ORDER BY checked_at LIMIT ?",
        (limit,),
    ).fetchall()


def regrade(
    connection: sqlite3.Connection, limit: int, workers: int = 12
) -> tuple[int, int]:
    """Re-check recorded strong matches against the current rule.

    Corroboration needs the page text and the page text is not stored, so a
    grade can only be revised by asking the host again. Returns
    (checked, demoted).

    Only the *grade* moves. The domain stays whatever it was even when the
    host has since gone quiet, because Stage 5 tiers every domain regardless
    of grade -- dropping one here would cost a board, which is the trade this
    project never makes.
    """
    connection.executescript(SCHEMA)
    rows = regrade_targets(connection, limit)
    if not rows:
        return 0, 0

    def work(row: sqlite3.Row) -> Lookup | None:
        normalized = normalize_name(row["query"])
        if not normalized:
            return None
        try:
            hit = verify(row["domain"], normalized)
        except Exception:  # noqa: BLE001 -- one hostile host must not stop the pass
            return None
        if hit is None:
            return None  # unreachable today says nothing about the old grade
        _, strength, evidence = hit
        method = "name-strong" if strength == "strong" else "name-weak"
        return Lookup(row["query"], row["domain"], method, evidence)

    checked = demoted = 0
    batch: list[Lookup] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for lookup in pool.map(work, rows):
            checked += 1
            if lookup is None:
                continue
            demoted += lookup.method == "name-weak"
            batch.append(lookup)
            if len(batch) >= 100:
                record(connection, batch)
                batch.clear()
    record(connection, batch)
    return checked, demoted


def run(
    connection: sqlite3.Connection,
    sources: tuple[str, ...],
    limit: int,
    workers: int = 12,
) -> tuple[int, int]:
    """Resolve up to `limit` firms. Returns (attempted, resolved)."""
    connection.executescript(SCHEMA)
    rows = targets(connection, sources, limit)
    if not rows:
        return 0, 0

    def work(row: sqlite3.Row) -> Lookup:
        normalized = normalize_name(row["name"])
        if not normalized:
            return Lookup(row["name"], None, "unresolved", "name normalizes to nothing")
        found = resolve_name(normalized, _country_code(row["country"]))
        # Cache under the firm's stored name so `targets` can exclude it, and
        # under the normalized form so sibling firms reuse the work.
        return Lookup(row["name"], found.domain, found.method, found.evidence)

    attempted = resolved = 0
    batch: list[Lookup] = []
    # Written in batches rather than once at the end: a run over thousands of
    # firms is minutes of network work, and losing all of it to one exception
    # would mean re-probing hosts we already asked. The cache is the product
    # here, not the return value.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for lookup in pool.map(work, rows):
            batch.append(lookup)
            attempted += 1
            resolved += lookup.method == "name-strong"
            if len(batch) >= 100:
                record(connection, batch)
                batch.clear()
    record(connection, batch)
    return attempted, resolved


def coverage(connection: sqlite3.Connection, sources: tuple[str, ...]):
    """Per-source domain coverage: how many of its firms have one, and whence."""
    connection.executescript(SCHEMA)
    for source in sources:
        row = connection.execute(
            """
            SELECT COUNT(*) AS firms,
                   SUM(f.website IS NOT NULL) AS registry,
                   -- FCA domains are published by the regulator, so they rank
                   -- with the registry ones rather than with the guesses.
                   SUM(f.website IS NULL AND d.method = 'fca') AS fca,
                   SUM(f.website IS NULL AND d.method = 'name-strong') AS strong,
                   SUM(f.website IS NULL AND d.method = 'name-weak') AS weak,
                   SUM(f.website IS NULL
                       AND d.method IN ('unresolved', 'fca-miss')) AS unresolvable
            FROM firms f
            LEFT JOIN domain_lookups d ON d.query = f.name
            WHERE EXISTS (
                SELECT 1 FROM firm_members m
                WHERE m.firm_id = f.firm_id AND m.source = ?
            )
            """,
            (source,),
        ).fetchone()
        yield source, row
