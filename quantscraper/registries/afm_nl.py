"""AFM -- the Dutch financial markets authority.

Covers the Amsterdam market-making cluster: Optiver, IMC, Flow Traders,
Da Vinci, Webb Traders, All Options, 323 Trading.

AFM offers each licence register as a CSV export, which means we get the whole
register in one request rather than paging a search UI.

**The CSV exports are not the whole register.** The AIFM manager registers are
published as spreadsheets further down the same page, and only as spreadsheets.
That is easy to miss, because the CSV export link sits at the top and looks
complete -- and missing them cost us PGGM Vermogensbeheer and APG Asset
Management, two of the largest asset managers in the Netherlands, which appear
in neither CSV export and are not in DNB's register either. Found by the
coverage audit.
"""

from __future__ import annotations

import csv
import io

from .. import http
from ..models import Employer
from ..parsing import xlsx_rows

NAME = "afm_nl"
JURISDICTION = "NL"
MIN_EXPECTED = 2_500

_EXPORT_URL = "https://www.afm.nl/export.aspx?type={register_id}&format=csv"
_FILE_URL = "https://www.afm.nl/~/profmedia/files/registers/{filename}"

# The GUIDs are AFM's own register identifiers, read off the export links on
# each register page. Funds themselves are excluded -- a fund is a product,
# not an employer; its manager is in the AIFM registers below.
REGISTERS = {
    "Beleggingsonderneming": "8f59acf7-047b-4009-9fa7-90a264e6f3ef",
    "Beleggingsinstelling": "883bcff1-0f26-442f-9faf-a39ff911b109",
}

# Spreadsheet registers, as (filename, manager-name column heading). Each row is
# one (manager, fund) pair, so a manager repeats once per fund it runs; we keep
# the manager and drop the fund, same rule as above.
SPREADSHEET_REGISTERS = {
    "AIFM-beheerder": ("register-aifm.xlsx", "Naam Beheerder"),
    "AIFMD-light beheerder": ("register-aifmd-light.xlsx", "Naam beheerder"),
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


def _fetch_spreadsheet(label: str, filename: str, heading: str) -> list[Employer]:
    rows = xlsx_rows(http.get(_FILE_URL.format(filename=filename)))

    # The sheet opens with a title block, so the header is several rows down and
    # its position moves. Find it by its heading rather than by row number.
    header = next(
        (row for row in rows if heading in row),
        None,
    )
    if header is None:
        raise ValueError(f"{filename}: no {heading!r} column -- layout changed")
    column = header.index(heading)

    names = {
        row[column].strip()
        for row in rows[rows.index(header) + 1 :]
        if len(row) > column and row[column].strip()
    }
    return [
        Employer(source_id=name.casefold(), name=name, category=label)
        for name in sorted(names)
    ]


def fetch() -> list[Employer]:
    employers: dict[str, Employer] = {}
    for label, register_id in REGISTERS.items():
        for employer in _fetch_register(label, register_id):
            employers.setdefault(employer.source_id, employer)
    for label, (filename, heading) in SPREADSHEET_REGISTERS.items():
        for employer in _fetch_spreadsheet(label, filename, heading):
            employers.setdefault(employer.source_id, employer)
    return list(employers.values())
