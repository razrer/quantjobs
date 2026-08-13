"""Euronext trading members (Amsterdam, Brussels, Dublin, Lisbon, Milan, Oslo, Paris).

The same exchange-membership backstop as `eurex`, over the other main European
venue. Worth having both: membership differs per venue, and Amsterdam prop
shops are exactly the firms the licence registers miss.

The list is served from an iframe on Euronext's Connect portal. It reads as
though it needs a login -- it does not; the frame is public. It is paginated
with no total count and no "last page" link, so we walk pages until one yields
no members.
"""

from __future__ import annotations

import re

from .. import http
from ..models import Employer
from ..parsing import table_rows

NAME = "euronext"
JURISDICTION = "EU"
MIN_EXPECTED = 250

URL = "https://connect2.euronext.com/en/intframe/trade/member-list?page={page}"

# Stops a layout change from turning pagination into an unbounded crawl.
# There are ~15 pages of ~23; this is comfortable headroom.
MAX_PAGES = 60

# Each member renders a detail cell that flattens to a single run of text:
#   "Name 323 TRADING Type Trading Member (T) Address ... Website: www.323trading.nl"
_DETAIL = re.compile(r"^Name (?P<name>.+?) Type (?P<type>.+?) Address (?P<rest>.*)$")
_WEBSITE = re.compile(r"Website:\s*(\S+)")


def _members_on_page(page: int) -> list[Employer]:
    html = http.get_text(URL.format(page=page))

    employers = []
    for row in table_rows(html):
        if len(row) != 1:
            continue
        detail = _DETAIL.match(row[0])
        if not detail:
            continue
        website = _WEBSITE.search(detail["rest"])
        employers.append(
            Employer(
                source_id=detail["name"].casefold(),
                name=detail["name"],
                category=detail["type"],
                website=website.group(1) if website else None,
            )
        )
    return employers


def fetch() -> list[Employer]:
    employers: dict[str, Employer] = {}
    for page in range(MAX_PAGES):
        found = _members_on_page(page)
        if not found:  # empty page means we walked off the end
            break
        for employer in found:
            employers.setdefault(employer.source_id, employer)
    return list(employers.values())
