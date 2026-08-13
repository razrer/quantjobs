"""FINMA -- the Swiss Financial Market Supervisory Authority.

Switzerland was the weakest focus hub: 11/11 roster firms present but only 6
*local*, the rest visible only through Dutch, Danish and US registrations. FINMA
publishes its authorised institutions as bulk spreadsheets, one per licence
category, which is the enumerable shape this project prefers.

**A note on the certificate error, because it cost an hour and the first
diagnosis was wrong.** Every request to finma.ch used to fail with
`CERTIFICATE_VERIFY_FAILED`, and that was read as "FINMA serves an incomplete
chain". It does not. Windows populates its root store lazily, so a fresh Python
process trusted only the 38 roots that happened to be cached, and FINMA's was
not among them. `curl` -- which ships its own 152-certificate bundle -- reached
the site fine, which is what gave it away. `http.py` now loads a full bundle.

Collective investment schemes (`afch`, `afetr`) are excluded on the rule used
everywhere else: a fund is a product, not an employer, and its manager is in
`flvervt`. Insurance, SROs, supervisory organisations, prospectus reviewers and
registration bodies are out of role scope rather than merely low signal.
"""

from __future__ import annotations

from .. import http
from ..models import Employer
from ..parsing import xlsx_rows

NAME = "finma_ch"
JURISDICTION = "CH"
MIN_EXPECTED = 1_500

URL = (
    "https://www.finma.ch/en/~/media/finma/dokumente/"
    "bewilligungstraeger/xlsx/{filename}?sc_lang=en"
)

# One spreadsheet per licence category. The representative-office lists are
# worth having precisely because they are foreign firms with a Swiss presence,
# which is the population the national registers miss.
FILES = {
    "beh.xlsx": "Bank or securities firm",
    "flvervt.xlsx": "Fund management company or manager of collective assets",
    "grfinig.xlsx": "Portfolio manager or trustee (FINMA-supervised)",
    "vvtr.xlsx": "Portfolio manager or trustee (SO-monitored)",
    "bourses.xlsx": "Market infrastructure or authorised foreign participant",
    "repbeh.xlsx": "Representative office of a foreign bank or securities firm",
    "repvkv.xlsx": "Representative office of a foreign manager of collective assets",
    "repvvtr.xlsx": "Representative office of a foreign portfolio manager",
    "fintech.xlsx": "FinTech licence",
    "raiff.xlsx": "Raiffeisen bank",
}


def _column(header: list[str], *wanted: str) -> int | None:
    for index, cell in enumerate(header):
        if cell.strip().casefold() in wanted:
            return index
    return None


def _fetch_file(filename: str, label: str) -> list[Employer]:
    rows = xlsx_rows(http.get(URL.format(filename=filename)))

    # Each sheet opens with a title block of a different height, so the header
    # is found by its content rather than by row number.
    header_at = next(
        (i for i, row in enumerate(rows) if _column(row, "name") is not None), None
    )
    if header_at is None:
        raise ValueError(f"{filename}: no 'Name' column -- layout changed")

    header = rows[header_at]
    name_at = _column(header, "name")
    city_at = _column(header, "city")

    employers = []
    for row in rows[header_at + 1 :]:
        if len(row) <= name_at:
            continue
        name = row[name_at].strip()
        if not name:
            continue
        city = row[city_at].strip() if city_at is not None and len(row) > city_at else ""
        employers.append(
            Employer(
                source_id=name.casefold(),
                name=name,
                category=label,
                city=city or None,
                country="Switzerland",
            )
        )
    return employers


def fetch() -> list[Employer]:
    employers: dict[str, Employer] = {}
    for filename, label in FILES.items():
        for employer in _fetch_file(filename, label):
            # A firm can hold several licences; first category wins, as
            # elsewhere, because category only ever sets polling priority.
            employers.setdefault(employer.source_id, employer)
    return list(employers.values())
