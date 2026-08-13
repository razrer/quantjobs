"""MAS -- the Monetary Authority of Singapore.

Singapore read 9/10 present but only 4 local: nearly every roster firm was
visible through a US or Dutch registration rather than a Singaporean one, which
is a coverage claim resting on the wrong evidence.

MAS publishes its Financial Institutions Directory as **category listings**,
which is the shape worth having: walking a category returns everything in it,
where a search only returns what you thought to ask for. 48 categories are
offered; the ones below are the sectors that employ people in markets roles.

Left out, on the same rule the Swedish and Dutch modules use, and reversible by
adding a line: insurance in all its forms (direct, re-, captive, broker,
Lloyd's Asia Scheme), payments, money-changing, credit cards, credit bureaux and
trust companies. Insurance is out of role scope rather than merely low-signal;
the rest are not markets businesses at all.

Paging is fixed at ten rows and the page size cannot be overridden -- every
`size`/`limit`/`pageSize` spelling is ignored. So the walk is roughly 280
requests. An out-of-range page returns zero rows rather than wrapping to the
first, which is what makes the loop terminate honestly.
"""

from __future__ import annotations

import html as html_lib
import re
import urllib.parse

from .. import http
from ..models import Employer

NAME = "mas_sg"
JURISDICTION = "SG"
# About 2,700 institutions across the categories below when this was written.
MIN_EXPECTED = 1_500

URL = "https://eservices.mas.gov.sg/fid/institution?category={category}&page={page}"

# Guards against a change in the stop condition turning into an endless walk.
_MAX_PAGES = 400

CATEGORIES = (
    "Capital Markets Services Licensee",
    "Exempt Capital Markets Services Entity",
    "Licensed Financial Adviser",
    "Exempt Financial Adviser",
    "Approved Exchange",
    "Recognised Market Operator",
    "Approved Clearing House",
    "Recognised Clearing House",
    "Central Depository System",
    "Licensed Trade Repository",
    "Full Bank",
    "Local Bank",
    "Qualifying Full Bank",
    "Wholesale Bank",
    "Merchant Bank",
    "Finance Company",
    "Financial Holding Company (Banking)",
    "Approved Holding Company",
    "Approved CIS Trustee",
    "SGS Primary Dealer",
    "Representative Office (Banking)",
)

# The listing renders each institution as a link whose slug carries MAS's own
# id, which is what makes a stable source_id available without a detail fetch.
_ENTRY = re.compile(
    r'href="/fid/institution/detail/([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)


def _page(category: str, page: int) -> list[tuple[str, str]]:
    body = http.get_text(
        URL.format(category=urllib.parse.quote(category), page=page)
    )
    entries = []
    for slug, label in _ENTRY.findall(body):
        name = html_lib.unescape(re.sub(r"<[^>]+>", "", label))
        name = " ".join(name.split())
        if name:
            entries.append((slug, name))
    return entries


def _fetch_category(category: str) -> list[Employer]:
    found: dict[str, str] = {}
    for page in range(1, _MAX_PAGES + 1):
        entries = _page(category, page)
        if not entries:
            break
        found.update(entries)
    return [
        Employer(
            source_id=slug,
            name=name,
            category=category,
            country="Singapore",
        )
        for slug, name in found.items()
    ]


def fetch() -> list[Employer]:
    employers: dict[str, Employer] = {}
    for category in CATEGORIES:
        for employer in _fetch_category(category):
            # A firm can hold several licences; first category wins, same as
            # Sweden, because category only ever sets polling priority.
            employers.setdefault(employer.source_id, employer)
    return list(employers.values())
