"""FCA register -- enrichment, not a registry.

**This is deliberately not in `registries/`.** A registry enumerates: you ask it
for everything it has and it tells you. The FCA cannot do that, and the evidence
is now concrete rather than assumed:

- there is no bulk download, and no listing endpoint of any kind;
- `Search` refuses a query whose result set is too large -- "trading" and
  "capital" both come back `Request Entity Too Large`, so the trick that works
  for Denmark (sweep single letters, union the results) is unavailable;
- queries under three characters are rejected outright;
- the only other handle is the FRN, and enumerating those means walking a
  numeric space of roughly a million.

Treating it as a registry would therefore be a lie about coverage: whatever it
returned would be whatever we thought to ask for.

**What it is genuinely good for is websites.** `Firm/{FRN}/Address` publishes a
`Website Address`, and websites are the scarce resource -- no focus-region
registry publishes a single one. So this module enriches firms the universe
already has: look the firm up by name, and if the register agrees it is the same
firm, take the domain. Results land in `domain_lookups` alongside the guessed
ones, so Layer 2 reads them the same way.

The address record also carries `Country`, which is how an FCA-authorised firm
headquartered outside the UK shows up as such.

**Matching is strict.** FCA search is fuzzy -- a query for "barclays" returns
`PEAC Business Finance Limited` in first place -- so a result is accepted only
when its name matches the firm's on the same token-aligned rule the coverage
audit uses. A wrong match here would write a wrong domain into the cache, and a
wrong domain is worse than none.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
from pathlib import Path

from . import http
from .domains import Lookup, record
from .resolve import domain_of, normalize_name

BASE = "https://register.fca.org.uk/services/V0.1/"
ENV_PATH = Path(".env")

# Cloudflare answers 403 "error 1010" to requests without a User-Agent, which
# looks exactly like a bad API key. http.py sends one; this is the note that
# stops the next person debugging their credentials for an hour.
_ACCEPT = {"Accept": "application/json"}

# The register appends a postcode to search-result names.
_POSTCODE_SUFFIX = " (postcode:"


class MissingCredentials(RuntimeError):
    pass


def credentials(path: Path = ENV_PATH) -> dict[str, str]:
    """Read FCA_EMAIL and FCA_KEY from `.env`.

    Kept out of the repo and out of chat: `.env` is in `.gitignore`.
    """
    if not path.exists():
        raise MissingCredentials(f"{path} not found -- see ACTION-REQUIRED.md")
    values = dict(
        line.strip().split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    try:
        return {
            "X-Auth-Email": values["FCA_EMAIL"].strip(),
            "X-Auth-Key": values["FCA_KEY"].strip(),
            **_ACCEPT,
        }
    except KeyError as exc:
        raise MissingCredentials(f"{path} has no {exc.args[0]}") from exc


def _call(path: str, headers: dict[str, str]) -> dict:
    try:
        body = http.get(BASE + path, headers=headers, timeout=45, retries=2)
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 403, 404, 413):
            return {}
        raise
    try:
        return json.loads(body.decode("utf-8"))
    except ValueError:
        return {}


def search(name: str, headers: dict[str, str]) -> list[tuple[str, str]]:
    """(FRN, name) for firms the register offers against `name`."""
    if len(name.strip()) < 3:  # the API rejects shorter queries
        return []
    payload = _call(
        f"Search?q={urllib.parse.quote(name)}&type=firm", headers
    )
    results = []
    for row in payload.get("Data") or []:
        frn = (row.get("Reference Number") or "").strip()
        label = (row.get("Name") or "").strip()
        # Trim the "(Postcode: E14 5HP)" the register appends.
        cut = label.casefold().find(_POSTCODE_SUFFIX)
        if cut > 0:
            label = label[:cut].strip()
        if frn and label:
            results.append((frn, label))
    return results


def address(frn: str, headers: dict[str, str]) -> dict[str, str]:
    payload = _call(f"Firm/{frn}/Address?Type=PPOB", headers)
    data = payload.get("Data") or []
    return data[0] if data else {}


def _same_firm(wanted: str, offered: str) -> bool:
    """Token-aligned containment, the rule the coverage audit uses.

    Either name may carry the extra words: the register says "Optiver UK
    Limited" where we hold "Optiver", and "Jane Street" where we hold "Jane
    Street Netherlands B.V.".
    """
    left, right = normalize_name(wanted), normalize_name(offered)
    if not left or not right:
        return False
    return f" {left} " in f" {right} " or f" {right} " in f" {left} "


def targets(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Firms with no domain yet, most-corroborated first."""
    return connection.execute(
        """
        SELECT f.firm_id, f.name
        FROM firms f
        LEFT JOIN domain_lookups d ON d.query = f.name
        WHERE f.website IS NULL AND d.query IS NULL
        ORDER BY f.source_count DESC, f.row_count DESC, f.name
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def enrich(connection: sqlite3.Connection, limit: int) -> tuple[int, int]:
    """Look firms up in the FCA register. Returns (looked up, domains found)."""
    headers = credentials()
    connection.executescript(
        "CREATE TABLE IF NOT EXISTS domain_lookups ("
        " query TEXT PRIMARY KEY, domain TEXT, method TEXT NOT NULL,"
        " evidence TEXT, checked_at TEXT NOT NULL);"
    )

    rows = targets(connection, limit)
    found = 0
    batch: list[Lookup] = []
    for row in rows:
        lookup = Lookup(row["name"], None, "fca-miss", "no FCA firm matched")
        for frn, offered in search(row["name"], headers):
            if not _same_firm(row["name"], offered):
                continue
            details = address(frn, headers)
            domain = domain_of(details.get("Website Address"))
            if domain:
                lookup = Lookup(
                    row["name"],
                    domain,
                    "fca",
                    f"FRN {frn} ({offered}) in {details.get('Country') or '?'}",
                )
                found += 1
            break
        batch.append(lookup)
        if len(batch) >= 50:
            record(connection, batch)
            batch.clear()
    record(connection, batch)
    return len(rows), found


def summary(connection: sqlite3.Connection):
    return connection.execute(
        "SELECT method, COUNT(*) AS n FROM domain_lookups"
        " WHERE method LIKE 'fca%' GROUP BY method"
    ).fetchall()
