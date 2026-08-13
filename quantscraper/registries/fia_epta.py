"""FIA EPTA -- the European Principal Traders Association.

Small (about 20 firms) but high-signal: these are the European prop shops,
several of which hold no asset-management licence and so appear in no fund
register. Cheap insurance against the registries missing them.
"""

from __future__ import annotations

import html as html_lib
import re

from .. import http
from ..models import Employer

NAME = "fia_epta"
JURISDICTION = "EU"
MIN_EXPECTED = 15

URL = "https://www.fia.org/epta/articles/epta-membership"

# The member list is a single <p> of <br>-separated names. Fragile by nature;
# MIN_EXPECTED is what turns a silent breakage into a loud one.
_MEMBER_BLOCK = re.compile(r"EPTA members:\s*</p>\s*<p>(.*?)</p>", re.IGNORECASE | re.DOTALL)


def fetch() -> list[Employer]:
    page = http.get_text(URL)
    match = _MEMBER_BLOCK.search(page)
    if not match:
        raise ValueError("EPTA member list not found -- page layout probably changed")

    names = (
        html_lib.unescape(re.sub(r"<[^>]+>", "", part)).replace("\xa0", " ").strip()
        for part in re.split(r"<br\s*/?>", match.group(1))
    )
    return [
        Employer(source_id=name.casefold(), name=name, category="Principal trading firm")
        for name in names
        if name
    ]
