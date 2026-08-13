"""SEC register of active broker-dealers.

This is what closes the proprietary-trading gap in Form ADV. Prop firms trade
their own capital, so they are not investment advisers and appear nowhere in
`sec_adv` -- but they cannot trade US securities without registering as a
broker-dealer, so they all appear here: Jane Street, Citadel Securities, Jump,
DRW, Optiver, SIG, XTX, Virtu, Two Sigma Securities.

Published monthly as a UTF-16, tab-separated file with no usable header row.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime

from .. import http
from ..models import Employer

NAME = "sec_bd"
JURISDICTION = "US"
# There are ~3,300 active US broker-dealers in total, and the number has been
# declining for years, so this floor is deliberately well below current volume.
MIN_EXPECTED = 2_500

INDEX_URL = "https://www.sec.gov/help/foiadocsbdfoiahtm.html"

# Filenames are inconsistent across years -- bd-070124.txt, bd080126.txt and
# bd080122_1_0.txt are all real. Requiring the six date digits to be followed
# immediately by "_" or ".txt" rejects the malformed seven-digit ones
# (bd0120321.txt) that would otherwise parse as a plausible date.
_FILE_LINK = re.compile(
    r'href="(/files/data/broker-dealers/[^"]*/bd-?(\d{6})(?:_[\d_]+)?\.txt)"',
    re.IGNORECASE,
)

# Column positions; the file ships no header.
_CRD, _NAME, _CITY, _STATE = 0, 1, 5, 6


def _latest_file() -> str:
    page = http.get_text(INDEX_URL)
    today = datetime.today()
    dated: list[tuple[datetime, str]] = []

    for path, date_text in _FILE_LINK.findall(page):
        try:
            published = datetime.strptime(date_text, "%m%d%y")
        except ValueError:
            continue
        if published <= today:  # guards against typo'd future dates
            dated.append((published, f"https://www.sec.gov{path}"))

    if not dated:
        raise ValueError("no broker-dealer files found -- SEC index page probably changed")
    return max(dated)[1]


def fetch() -> list[Employer]:
    text = http.get(_latest_file(), timeout=180).decode("utf-16")
    rows = csv.reader(io.StringIO(text), delimiter="\t")

    employers: dict[str, Employer] = {}
    for row in rows:
        # The file separates every record with a blank line, so roughly half
        # the parsed rows are empty by design. Don't "fix" this skip.
        if len(row) <= _STATE:
            continue
        crd, name = row[_CRD].strip(), row[_NAME].strip()
        if not crd.isdigit() or not name:
            continue
        employers.setdefault(
            crd,
            Employer(
                source_id=crd,
                name=name,
                category="Broker-dealer",
                city=row[_CITY].strip() or None,
                country="United States",
            ),
        )
    return list(employers.values())
