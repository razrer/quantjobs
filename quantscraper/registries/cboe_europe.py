"""Cboe Europe Equities trading participants.

Catches the same licence-exempt principal-trader gap as the Eurex module but
for Cboe's European venues (UK CXE and NL DXE). A firm must be an admitted
participant to trade on Cboe regardless of its MiFID licensing status, so this
is an independent backstop for sponsored-access firms and others that hold no
investment-firm authorisation.

The page renders each firm as a logo link whose title attribute reads:
    title="Visit {Name}'s website"
MIN_EXPECTED guards against a silent layout change that returns 0 matches.
"""

from __future__ import annotations

import re

from .. import http
from ..models import Employer

NAME = "cboe_europe"
JURISDICTION = "EU"
MIN_EXPECTED = 40

URL = "https://www.cboe.com/europe/equities/participation/trading_firms/"

_TITLE = re.compile(r"""title="Visit ([^"]+?)'s website\"""", re.IGNORECASE)


def fetch() -> list[Employer]:
    page = http.get_text(URL)
    names = _TITLE.findall(page)
    if not names:
        raise ValueError(
            "Cboe Europe trading firms list not found -- page layout probably changed"
        )
    return [
        Employer(
            source_id=name.casefold(),
            name=name,
            category="Exchange participant",
        )
        for name in dict.fromkeys(names)
    ]
