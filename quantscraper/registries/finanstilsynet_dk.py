"""Finanstilsynet -- the Danish financial supervisory authority.

Copenhagen was the largest uncovered focus hub: ATP and PFA, two of the biggest
asset owners in the Nordics, were in no source we had.

**Why this one sweeps instead of enumerating.** Every other registry here reads
a bulk file or walks a category listing, because a search endpoint only returns
what you thought to ask for. Denmark offers neither. The register's service
exposes exactly six operations -- two taxonomies, two tooltip blobs, one
per-company detail lookup, and a free-text search -- and the site's own "list
extract" and "explore data" pages render empty shells that call nothing. There
is no bulk download on finanstilsynet.dk either.

So the search is swept rather than queried. `searchVUT` matches a **substring**
anywhere in the name, so a query of "a" returns every company whose name
contains an "a" -- 23,957 of them. Union the 26 letters and any name containing
a single ASCII letter is returned, which is every name in the register.

That the union saturates is the evidence it is complete: it stops growing part
way through the alphabet, and the digits and the Danish letters that follow add
nothing at all. Were the service silently capping results, adding probes would
keep adding rows. `MIN_EXPECTED` catches the cap appearing later.

**What this does not collect.** The search returns a name and a GUID, nothing
else. Company type, city and CVR number need `hentVirksomhedsinformation?v=GUID`
-- one request per company, so 26,000 requests for a register we can enumerate
in 39. Deliberately deferred rather than forgotten: the endpoint is recorded
below, and `category` stays NULL for Denmark until something needs it. Under the
read-time-classification rule that is the right trade -- the rows are in the
universe, and a missing attribute can be backfilled without re-scraping.
"""

from __future__ import annotations

import json
import string
import urllib.parse

from .. import http
from ..models import Employer

NAME = "finanstilsynet_dk"
JURISDICTION = "DK"
# The register held 26,495 entries when this was written. A floor well below
# that catches both a broken sweep and the search growing a result cap.
MIN_EXPECTED = 15_000

_SERVICE = (
    "https://virksomhedsregister.finanstilsynet.dk"
    "/VUTService/VirksomhederUnderTilsynService.svc/"
)
SEARCH_URL = _SERVICE + "searchVUT?v={query}"

# Per-company detail, kept here because it is the documented way to get type
# and city and will be wanted eventually. Not called: one request per company.
DETAIL_URL = _SERVICE + "hentVirksomhedsinformation?v={guid}"

# Latin letters do the work; the digits and Danish letters are there to prove
# the union has saturated, and are expected to add nothing.
PROBES = string.ascii_lowercase + string.digits + "æøå"


def _search(query: str) -> list[dict]:
    body = http.get_text(SEARCH_URL.format(query=urllib.parse.quote(query)))
    # The service double-encodes: a JSON object whose single value is itself a
    # JSON string. Not a quirk worth hiding -- it is how the response arrives.
    return json.loads(json.loads(body)["SearchVUTResult"])


def fetch() -> list[Employer]:
    found: dict[str, str] = {}
    for probe in PROBES:
        for row in _search(probe):
            # A handful of rows come back with a null GUID. They carry no key
            # to dedupe or re-find them by, so the name has to serve as one.
            name = (row.get("Firmanavn") or "").strip()
            guid = (row.get("GUID") or "").strip() or f"name:{name.casefold()}"
            if name:
                found.setdefault(guid, name)

    return [
        Employer(
            source_id=guid,
            name=name,
            # Type and city are one request each; see the module docstring.
            # The register covers firms passported into Denmark as well as
            # Danish ones, so country is not assumed either.
        )
        for guid, name in sorted(found.items(), key=lambda item: item[1])
    ]
