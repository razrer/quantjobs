"""ESMA -- the EEA-wide register of investment firms and fund managers.

Every national regulator notifies ESMA, so this one source covers Amsterdam,
Stockholm and Copenhagen at once, plus the twenty-odd member states we have no
adapter for. 13,930 entities: investment firms, AIFMs, UCITS management
companies, MTFs, systematic internalisers and regulated markets.

**Why it earns its place even though the national registers overlap it.** Three
quarters of these records carry an **LEI**, and none of `fi_se`, `afm_nl` or
`finanstilsynet_dk` publishes one. LEI is the strongest key entity resolution
has -- `eurex` already keys on it -- so this does not merely add firms, it
welds together firms we already hold under names that match nothing. A domain
found for one of them then covers all of them.

**It is a real enumeration, not a search.** The register is Solr-backed and the
query endpoint is open, so `q=entity_type:ae` returns the whole set, paged.
That is the shape this project prefers, and the reason this was worth chasing
where the FCA was not.

Set expectations on websites: only 383 of the 13,930 publish one, so this is an
identity source rather than a domain source.

Child documents (`aeActivity`, `aeActivityHistory`) are the per-permission rows
and are deliberately skipped -- 87,000 of them, one firm many times over.
"""

from __future__ import annotations

import json
import re
import urllib.parse

from .. import http
from ..models import Employer

NAME = "esma_eea"
JURISDICTION = "EU"
MIN_EXPECTED = 8_000

URL = "https://registers.esma.europa.eu/solr/esma_registers_upreg/select?"

# Solr honours large page sizes here; 2,000 keeps it to seven requests.
_PAGE = 2_000

# An LEI is 18 alphanumerics plus 2 check digits. Using it as `source_id` is
# what lets `resolve.py` pick it up as an identity key without special-casing
# this module -- the same trick `eurex` uses.
_LEI = re.compile(r"^[A-Z0-9]{18}[0-9]{2}$")


def _page(start: int) -> tuple[list[dict], int]:
    query = urllib.parse.urlencode(
        {
            "q": "entity_type:ae",
            "wt": "json",
            "rows": str(_PAGE),
            "start": str(start),
            # Without a stable sort, deep paging can repeat and skip rows.
            "sort": "id asc",
        }
    )
    payload = json.loads(http.get_text(URL + query))
    response = payload.get("response") or {}
    return response.get("docs") or [], int(response.get("numFound") or 0)


def fetch() -> list[Employer]:
    employers: dict[str, Employer] = {}
    start = 0
    total = None

    while total is None or start < total:
        docs, total = _page(start)
        if not docs:
            break
        for doc in docs:
            name = (doc.get("ae_entityName") or "").strip()
            if not name:
                continue
            lei = (doc.get("ae_lei") or "").strip().upper()
            country = (doc.get("ae_homeMemberState") or "").strip()
            employers.setdefault(
                lei if _LEI.match(lei) else str(doc.get("id")),
                Employer(
                    source_id=lei if _LEI.match(lei) else str(doc.get("id")),
                    name=name,
                    category=(doc.get("ae_entityTypeLabel") or "").strip() or None,
                    # ESMA writes member states in lower case.
                    country=country.title() or None,
                    website=(doc.get("ae_website") or "").strip() or None,
                ),
            )
        start += len(docs)

    return list(employers.values())
