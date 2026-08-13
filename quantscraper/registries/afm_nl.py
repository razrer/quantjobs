"""AFM -- the Dutch financial markets authority.

Covers the Amsterdam market-making cluster: Optiver, IMC, Flow Traders,
Da Vinci, Webb Traders, All Options, 323 Trading.

AFM offers each licence register as a CSV export, which means we get the whole
register in one request rather than paging a search UI. DNB's public register
defers to these same AFM registers for investment firms, so AFM alone is enough.
"""

from __future__ import annotations

import csv
import io

from .. import http
from ..models import Employer

NAME = "afm_nl"
JURISDICTION = "NL"
MIN_EXPECTED = 1_200

_EXPORT_URL = "https://www.afm.nl/export.aspx?type={register_id}&format=csv"

# The GUIDs are AFM's own register identifiers, read off the export links on
# each register page. Funds themselves are excluded -- a fund is a product,
# not an employer; its manager is in `beleggingsinstellingen`.
REGISTERS = {
    "Beleggingsonderneming": "8f59acf7-047b-4009-9fa7-90a264e6f3ef",
    "Beleggingsinstelling": "883bcff1-0f26-442f-9faf-a39ff911b109",
}


def _fetch_register(label: str, register_id: str) -> list[Employer]:
    # Semicolon-delimited and cp1252-encoded, both of which AFM leaves undeclared.
    text = http.get(_EXPORT_URL.format(register_id=register_id)).decode("cp1252")
    rows = csv.DictReader(io.StringIO(text), delimiter=";")

    employers = []
    for row in rows:
        name = (row.get("Statutaire naam") or "").strip()
        if not name:
            continue
        employers.append(
            Employer(
                # AFM's export carries no stable identifier, so the statutory
                # name is the key. Good enough: it is the legal name, and
                # Layer 2 will re-key on domain anyway.
                source_id=name.casefold(),
                name=name,
                category=label,
                city=(row.get("Plaats") or "").strip() or None,
                country=(row.get("Land") or "").strip() or None,
            )
        )
    return employers


def fetch() -> list[Employer]:
    employers: dict[str, Employer] = {}
    for label, register_id in REGISTERS.items():
        for employer in _fetch_register(label, register_id):
            employers.setdefault(employer.source_id, employer)
    return list(employers.values())
