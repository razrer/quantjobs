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
from .resolve import domain_of, is_platform_domain, normalize_name

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


def fold_text(text: str) -> str:
    """Fold arbitrary text the way firm names are normalized.

    Both sides have to be folded the same way or nothing matches: the register
    says "J.P. Morgan SE", which normalizes to "jp morgan", and the raw page
    says "J.P. Morgan". Folding only one side compares two different alphabets.

    Public because `discover.py` matches firm names against *board* text rather
    than page text, and a second fold written to look the same is how the two
    sides quietly diverge -- `lexicon.fold` cost 1,013 postings that way.
    """
    folded = text.casefold().replace(".", "").replace("/", "")
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split()) + " "


def _page_text(body: bytes) -> str:
    """Visible page text, folded for name matching."""
    return fold_text(_TAG.sub(" ", body.decode("utf-8", errors="replace")))


def _needles(normalized: str, min_len: int = 4) -> list[tuple[str, str]]:
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
    # `min_len` is 4 for registry names, where "ii" or "abc" is chance. A
    # curated spelling may lower it to 3: the roster says
    # "UBS", and no rule that reads only register names should decide that a
    # three-letter bank cannot be found.
    return [(needle, strength) for needle, strength in needles if len(needle) >= min_len]


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


# Public homepage checked 2026-09-12: an author's site, not the HKEX participant.
# Keep the rejection scoped to this name; a rejected guess is not a rejected firm.
REJECTED_MATCHES = {("starfish bay", "starfishbay.com")}


def verify(
    candidate: str, normalized: str, min_len: int = 4
) -> tuple[str, str, str] | None:
    """Fetch `candidate` and decide whether it belongs to this firm.

    Returns (domain, strength, evidence) or None. The bar is that the page names
    the firm -- a live host alone proves only that somebody owns the name.
    """

    name = normalize_name(normalized)
    if (name, domain_of(candidate)) in REJECTED_MATCHES:
        return None
    for url in (f"https://{candidate}/", f"https://www.{candidate}/"):
        try:
            body, landed = http.get_with_url(url, timeout=8, retries=1)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            continue
        except Exception:  # noqa: BLE001 -- a hostile host must not stop the run
            continue

        if (name, domain_of(landed)) in REJECTED_MATCHES:
            continue
        # A redirect onto a site builder or a social profile proves somebody
        # made a page, not that the host is the firm's. The Bank of East Asia
        # "resolved" to `eastasiachristmas.wixsite.com` this way.
        if is_platform_domain(domain_of(landed)):
            continue
        text = _page_text(body)
        if not text or _PARKED.search(text):
            continue

        for needle, strength in _needles(normalized, min_len):
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


def curated_candidates(normalized: str, country: str | None) -> list[str]:
    """`candidates`, for a spelling a human wrote rather than a register.

    The whole name run together comes first even at three letters, and the
    country's own TLD before `.com`: the roster's "UBS" is `ubs.com` and its
    "SEK" `sek.se`, and `_labels` drops both for being too short to be
    evidence when they come from a register.
    """
    joined = "".join(normalized.split())
    tlds = (*COUNTRY_TLDS.get((country or "").upper(), ()), "com")
    found = [f"{joined}.{tld}" for tld in tlds] if len(joined) == 3 else []
    for candidate in [*found, *candidates(normalized, country)]:
        if candidate not in found:
            found.append(candidate)
    return found


def resolve_name(
    normalized: str, country: str | None, curated: bool = False
) -> Lookup:
    """Best candidate for a name. A strong match wins immediately; a weak one
    is held in case nothing better turns up.

    `curated` is for the audit roster's own spellings: three-letter names are
    tried and accepted as needles, which a register name never earns.
    """
    weak: Lookup | None = None
    plan = (curated_candidates if curated else candidates)(normalized, country)
    for candidate in plan:
        hit = verify(candidate, normalized, 3 if curated else 4)
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
        -- Deliberately *not* filtered on `f.website IS NULL`. It was, and a
        -- firm whose published website failed to parse was excluded here for
        -- having one while `harvest_registry_domains` skipped it for having
        -- none -- so it was never probed and never seeded. Optiver and IMC
        -- Trading were lost that way. A firm with a usable website already
        -- has a `domain_lookups` row, so the clause below excludes it anyway;
        -- this one only ever excluded the failures.
        WHERE EXISTS (
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


# Methods whose rows a person wrote. Nothing automatic removes them.
_HAND_METHODS = ("site", "hand-verified")


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
        # A social profile is where the firm posts, not a domain it hires
        # from. Seeding one also took the firm out of the guessing queue for
        # good, since `targets` skips any name with a row: 6,700 firms sat
        # behind `linkedin.com`, `facebook.com` and `instragram.com` that way.
        if domain and not is_platform_domain(domain):
            # Keyed on the firm's stored name, the same key `targets` and
            # `coverage` join on. Normalizing here instead would make the cache
            # unjoinable from SQL, which is where it is read.
            lookups.append(Lookup(row["name"], domain, "registry", row["website"]))
    # **Never over a row a person wrote.** "Two Sigma" and "HSBC" are both a
    # registry firm's name and a `sites.py` label, and `INSERT OR REPLACE`
    # put `twosigma.cn` and `hsbc.com` back over the verified boards until
    # the next `sites.register` -- so a `domains` run on its own took 1,841
    # Hong Kong postings off the audit.
    hand = {
        query for (query,) in connection.execute(
            "SELECT query FROM domain_lookups"
            f" WHERE method IN ({','.join('?' * len(_HAND_METHODS))})",
            _HAND_METHODS,
        )
    }
    lookups = [lookup for lookup in lookups if lookup.query not in hand]
    record(connection, lookups)
    return len(lookups)


def purge_platform_rows(connection: sqlite3.Connection) -> int:
    """Remove cached domains that name a platform rather than a firm.

    Each removal puts the firm back in `targets`, so the guesser tries the
    firm's own name next. The registry's website stays in `firms.website`
    untouched; only the derived cache entry goes. Rows a person wrote stay.
    """
    rows = connection.execute(
        "SELECT query, domain FROM domain_lookups WHERE domain IS NOT NULL"
        f" AND method NOT IN ({','.join('?' * len(_HAND_METHODS))})",
        _HAND_METHODS,
    ).fetchall()
    stale = [(row["query"],) for row in rows if is_platform_domain(row["domain"])]
    with connection:
        connection.executemany("DELETE FROM domain_lookups WHERE query = ?", stale)
    return len(stale)


def regrade_targets(connection: sqlite3.Connection, limit: int):
    """Strong matches graded before the corroboration rule existed.

    Ordered oldest first, so an interrupted pass resumes where it stopped
    rather than re-reading the rows it just refreshed.

    **`evidence` is selected because `regrade` writes it back**, and leaving it
    out did not read as a missing column -- it read as a crash on the first
    unreachable host. `row['evidence']` is built outside the `try` that guards
    `verify`, so the `IndexError` escaped `work`, came back out of
    `pool.map` and killed the pass. The marker that branch exists to write has
    therefore never been written once: 0 rows carry it, against a queue 3,502
    deep. Pinned by `tests/test_domains.RegradeConvergesTest`.
    """
    return connection.execute(
        "SELECT query, domain, evidence FROM domain_lookups"
        " WHERE method = 'name-strong' AND evidence NOT LIKE '%, but no %'"
        "   AND evidence NOT LIKE '% and ''%'"
        "   AND evidence NOT LIKE '%[unreachable at regrade]'"
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

    def unreachable(row: sqlite3.Row) -> Lookup:
        """Record the attempt without touching the grade or the domain.

        Unreachable today says nothing about yesterday's evidence, so the grade
        and the domain both stand. The attempt is still recorded: without it
        the row keeps matching `regrade_targets` and the pass re-fetches the
        same dead hosts on every run instead of converging. 3,422 rows sat in
        exactly that loop.
        """
        return Lookup(
            row["query"], row["domain"], "name-strong",
            f"{row['evidence']} [unreachable at regrade]",
        )

    def work(row: sqlite3.Row) -> Lookup:
        normalized = normalize_name(row["query"])
        # **Recorded rather than skipped, both here and on the exception
        # below.** `regrade_targets` orders by `checked_at`, so a row nothing
        # writes keeps the oldest timestamp, keeps sorting first, and is
        # re-fetched by every budgeted pass -- the loop the `hit is None`
        # branch below was already written to break, left open for the two
        # cases that return early. A pass that cannot finish the queue must at
        # least advance through it.
        if not normalized:
            return unreachable(row)
        try:
            hit = verify(row["domain"], normalized)
        except Exception:  # noqa: BLE001 -- one hostile host must not stop the pass
            return unreachable(row)
        if hit is None:
            return unreachable(row)
        _, strength, evidence = hit
        method = "name-strong" if strength == "strong" else "name-weak"
        return Lookup(row["query"], row["domain"], method, evidence)

    checked = demoted = 0
    batch: list[Lookup] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for lookup in pool.map(work, rows):
            checked += 1
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
            -- By the cache's method, not by `f.website`: a website that is
            -- a LinkedIn profile is in `firms` but is no domain, and counting
            -- it as known hid 6,700 firms that had none.
            SELECT COUNT(*) AS firms,
                   SUM(d.method = 'registry') AS registry,
                   -- FCA domains are published by the regulator, so they rank
                   -- with the registry ones rather than with the guesses.
                   SUM(d.method = 'fca') AS fca,
                   SUM(d.method = 'name-strong') AS strong,
                   SUM(d.method = 'name-weak') AS weak,
                   SUM(d.method IN ('unresolved', 'fca-miss')) AS unresolvable
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
