"""SEC Form ADV -- every investment adviser registered with the SEC.

Published as a monthly bulk CSV, no auth, no rate limit. Two files: registered
advisers, and exempt reporting advisers (the private-fund managers below the
registration threshold, where a lot of small quant shops sit).

Known gap: this file contains SEC registrants only -- `Firm Type` is uniformly
"Registered". Advisers under roughly $110M AUM register with their *state*, not
the SEC, and are absent here. The SEC's own page links out to separate state
sources. Covering that tail needs another source; see README.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime

from .. import http
from ..models import Employer

NAME = "sec_adv"
JURISDICTION = "US"
MIN_EXPECTED = 10_000

INDEX_URL = "https://www.sec.gov/help/foiadocsinvafoiahtm.html"

# The files are dated ia<MMDDYY>.zip, and the directory they live in has moved
# more than once -- so we read the link off the index page rather than
# constructing a URL and hoping.
_FILE_LINK = re.compile(r'href="(/files/[^"]*/ia(\d{6})(-exempt)?\.zip)"', re.IGNORECASE)


def _latest_files() -> dict[str, str]:
    """Newest registered and exempt-reporting file URLs, keyed by category."""
    page = http.get_text(INDEX_URL)
    newest: dict[str, tuple[datetime, str]] = {}

    for path, date_text, exempt in _FILE_LINK.findall(page):
        category = "Exempt reporting adviser" if exempt else "Registered adviser"
        published = datetime.strptime(date_text, "%m%d%y")
        if category not in newest or published > newest[category][0]:
            newest[category] = (published, f"https://www.sec.gov{path}")

    if not newest:
        raise ValueError("no ADV bulk files found -- SEC index page probably changed")
    return {category: url for category, (_, url) in newest.items()}


def _read_csv(url: str) -> list[dict[str, str]]:
    archive = zipfile.ZipFile(io.BytesIO(http.get(url, timeout=180)))
    # Each archive holds exactly one CSV, latin-1 encoded.
    text = archive.read(archive.namelist()[0]).decode("latin-1")
    return list(csv.DictReader(io.StringIO(text)))


def _to_employer(row: dict[str, str], category: str) -> Employer | None:
    crd = (row.get("Organization CRD#") or "").strip()
    name = (row.get("Primary Business Name") or row.get("Legal Name") or "").strip()
    if not crd or not name:
        return None
    return Employer(
        source_id=crd,
        name=name,
        category=category,
        city=(row.get("Main Office City") or "").strip() or None,
        country=(row.get("Main Office Country") or "").strip() or None,
        website=(row.get("Website Address") or "").strip() or None,
    )


def fetch() -> list[Employer]:
    employers: dict[str, Employer] = {}
    for category, url in _latest_files().items():
        for row in _read_csv(url):
            employer = _to_employer(row, category)
            if employer:
                employers.setdefault(employer.source_id, employer)
    return list(employers.values())
