"""Eurex exchange participants.

Exchange membership is the backstop for the hole every licence register has:
a firm dealing only on its own account can be exempt from investment-firm
licensing (MiFID II Art. 2(1)(d)) and so appear in no regulator's register --
but it cannot trade on Eurex without being an admitted participant.

This is where firms like Radix Trading Europe, Headlands Technologies Europe
and Eagle Seven Europe enter the universe; they are in none of the registries.

Eurex publishes the whole participant list as a single CSV.
"""

from __future__ import annotations

import csv
import io

from .. import http
from ..models import Employer

NAME = "eurex"
JURISDICTION = "EU"
MIN_EXPECTED = 300

URL = "https://www.eurex.com/resource/blob/5168/33e7894a407b0d0b0f8a4b20aed19623/data/memberdb.csv"


def fetch() -> list[Employer]:
    text = http.get(URL).decode("utf-8-sig")
    rows = csv.DictReader(io.StringIO(text))

    employers: dict[str, Employer] = {}
    for row in rows:
        name = (row.get("company") or "").strip()
        if not name:
            continue
        # A firm holds one member ID per role it trades in, so companies repeat.
        # The LEI is the better key anyway: it is a global identifier, so storing
        # it here is what will let entity resolution match this firm against the
        # other registries later.
        lei = (row.get("lei") or "").strip()
        employers.setdefault(
            lei or name.casefold(),
            Employer(
                source_id=lei or name.casefold(),
                name=name,
                category="Exchange participant",
                city=(row.get("city") or "").strip() or None,
                country=(row.get("country") or "").strip() or None,
            ),
        )
    return list(employers.values())
