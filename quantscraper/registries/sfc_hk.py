"""SFC -- the Securities and Futures Commission of Hong Kong.

Hong Kong was the clearest case the coverage audit made: nine of nine roster
firms present, exactly one of them local. Optiver, Jane Street, Jump, Tower,
Millennium, Point72 and Citadel Securities were all visible only through US
registrations. Reporting that as full coverage would have been wrong, and this
module is what makes it true.

**The register needs a session and a first letter.** `searchByRaJson` returns
`totalCount: 0` -- not an error -- if either the session cookie from the search
page or the `nameStartLetter` field is missing. A silent empty result set is
exactly the failure this project refuses to be fooled by, so both are asserted:
the walk raises if it finds nothing at all.

**Why this enumerates rather than searches.** A-Z is a partition of the register
by first letter, not a set of guessed keywords -- every licensed corporation
falls in exactly one bucket, so the union is the whole register. Crossed with
the thirteen regulated-activity types that is 338 requests, and `limit` is
honoured up to at least 500, so each combination comes back in one page.

**Known edge.** The letter buckets are A-Z, so a corporation whose English name
begins with a digit would be unreachable. The register showed none when this was
written; `MIN_EXPECTED` will not catch it if that changes, which is why it is
written down here.
"""

from __future__ import annotations

import json
import string

from .. import http
from ..models import Employer

NAME = "sfc_hk"
JURISDICTION = "HK"
# Roughly 3,300 licensed corporations across the thirteen activity types.
MIN_EXPECTED = 1_500

SEARCH_PAGE = "https://apps.sfc.hk/publicregWeb/searchByRa?locale=en"
SEARCH_URL = "https://apps.sfc.hk/publicregWeb/searchByRaJson"

# The thirteen regulated activities under the Securities and Futures Ordinance.
# All of them are walked: the cost is linear and small, and deciding which
# licence implies a quant desk is a read-time judgement, not an ingest-time one.
ACTIVITIES = {
    "1": "Type 1: Dealing in securities",
    "2": "Type 2: Dealing in futures contracts",
    "3": "Type 3: Leveraged foreign exchange trading",
    "4": "Type 4: Advising on securities",
    "5": "Type 5: Advising on futures contracts",
    "6": "Type 6: Advising on corporate finance",
    "7": "Type 7: Providing automated trading services",
    "8": "Type 8: Securities margin financing",
    "9": "Type 9: Asset management",
    "10": "Type 10: Providing credit rating services",
    "11": "Type 11: Dealing in OTC derivatives",
    "12": "Type 12: Clearing services for OTC derivatives",
    "13": "Type 13: Providing depositary services",
}

# Generous: the largest observed bucket held 223 corporations.
_PAGE_SIZE = 500


def _search(activity: str, letter: str) -> list[dict]:
    body = http.post_form(
        SEARCH_URL,
        {
            "ratype": activity,
            "roleType": "corporation",
            "licstatus": "active",
            "nameStartLetter": letter,
            "page": "1",
            "start": "0",
            "limit": str(_PAGE_SIZE),
        },
    )
    payload = json.loads(body.decode("utf-8"))
    items = payload.get("items") or []
    if payload.get("totalCount", 0) > len(items):
        raise ValueError(
            f"activity {activity} letter {letter}: {payload['totalCount']} rows "
            f"but only {len(items)} returned -- page size is no longer honoured"
        )
    return items


def fetch() -> list[Employer]:
    # Establishes the session cookie; without it every search returns nothing.
    http.get(SEARCH_PAGE)

    found: dict[str, Employer] = {}
    for activity, label in ACTIVITIES.items():
        for letter in string.ascii_uppercase:
            for item in _search(activity, letter):
                name = (item.get("name") or "").strip()
                reference = (item.get("ceref") or "").strip()
                if not name or not reference:
                    continue
                # A corporation holds several licence types; first wins, as
                # elsewhere, because category only sets polling priority.
                found.setdefault(
                    reference,
                    Employer(
                        source_id=reference,
                        name=name,
                        category=label,
                        country="Hong Kong",
                    ),
                )

    if not found:
        raise ValueError(
            "SFC returned no corporations at all -- the session or the "
            "nameStartLetter field is no longer being accepted"
        )
    return list(found.values())
