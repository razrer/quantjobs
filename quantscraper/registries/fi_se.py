"""Finansinspektionen -- the Swedish financial supervisory authority.

FI's company register is complete by law: a firm cannot do financial business
in Sweden without appearing in it. We enumerate it by regulatory category
rather than by search term, so the result does not depend on us guessing the
right keyword -- that guessing game is exactly what makes aggregators lossy.
"""

from __future__ import annotations

import re
import urllib.parse

from .. import http
from ..models import Employer
from ..parsing import table_rows

NAME = "fi_se"
JURISDICTION = "SE"
MIN_EXPECTED = 400

URL = "https://www.fi.se/sv/vara-register/foretagsregistret/index"

_ORG_NUMBER = re.compile(r"^\d{6}-\d{4}$")

# FI publishes 139 categories. These are the ones whose members are *firms
# that employ people in markets roles*.
#
# Two kinds of category are deliberately left out, and both are reversible by
# adding a line here:
#   - funds and sub-funds (Fond, Specialfond, delfonder) -- a fund is a
#     product, not an employer; its manager is already listed separately.
#   - payments, consumer credit, crypto, insurance distribution -- these are
#     out of the role scope rather than merely low-signal.
# Everything that survives stays in the universe permanently; category only
# ever sets polling frequency later, never membership.
CATEGORIES = {
    "VÄRD": "Värdepappersbolag",
    "AIFFÖR": "Auktoriserad AIF-förvaltare",
    "AIFFÖI": "Auktoriserad AIF-förvaltare (intern)",
    "AIFREG": "Registrerad AIF-förvaltare",
    "AIFREI": "Registrerad AIF-förvaltare (intern)",
    "FONDBO": "Fondbolag",
    "BANK": "Bankaktiebolag",
    "SPAR": "Sparbank",
    "MBANK": "Medlemsbank",
    "APFOND": "AP-fond",
    "TJPAB": "Tjänstepensionsaktiebolag",
    "BÖRS": "Börs",
    "CLEAR": "Clearingorganisation",
    "CCP": "Central motpart",
    "VPC": "Värdepapperscentral",
    # Foreign firms with a Swedish presence -- they hire in Stockholm too.
    "UTLFIL": "Utländsk bank, svensk filial",
    "VPFIL": "Utländskt värdepappersföretag, svensk filial",
    "MIFFIL": "Utländskt vp-bolag i EES, svensk filial",
    "UTFIL3": "Utländskt vp-bolag utanför EES, svensk filial",
    "UTAIFF": "Utländsk AIF-förvaltare, svensk filial",
}


def _fetch_category(code: str, label: str) -> list[Employer]:
    query = urllib.parse.urlencode({"cat": code})
    html = http.get_text(f"{URL}?{query}")
    return [
        Employer(source_id=org_number, name=name, category=label, country="Sweden")
        for name, org_number in (
            row for row in table_rows(html) if len(row) == 2 and _ORG_NUMBER.match(row[1])
        )
    ]


def fetch() -> list[Employer]:
    employers: dict[str, Employer] = {}
    for code, label in CATEGORIES.items():
        for employer in _fetch_category(code, label):
            # A firm can hold several licences; first category wins, which is
            # fine because we only use it to prioritise polling.
            employers.setdefault(employer.source_id, employer)
    return list(employers.values())
