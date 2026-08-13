"""Hand-curated seed list of firms that appear in no public registry.

Covers three categories:
  - Sponsored-access / MiFID II Art. 2(1)(d) exempt firms (Amsterdam prop shops
    that trade through another member's exchange membership)
  - Firms governed by their own legislation rather than FI (AP1-AP4, AP6)
  - Sovereign wealth funds (ADIA, ADQ, Mubadala, GIC, Temasek), which are state
    entities rather than licensed firms and so appear in no register anywhere

Edit seed_firms.csv to add or remove entries. Lines beginning with '#' and
blank lines are silently skipped.

This module exposes the same interface as every other registry so it slots into
the REGISTRIES dict without any special handling.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..models import Employer

NAME = "seed"
JURISDICTION = "manual"
MIN_EXPECTED = 1

_CSV = Path(__file__).with_name("seed_firms.csv")


def fetch() -> list[Employer]:
    employers: list[Employer] = []
    with _CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(
            (line for line in fh if not line.lstrip().startswith("#")),
        ):
            name = row.get("name", "").strip()
            if not name:
                continue
            employers.append(
                Employer(
                    source_id=f"seed:{name.casefold()}",
                    name=name,
                    city=row.get("city", "").strip() or None,
                    country=row.get("country", "").strip() or None,
                    category=row.get("category", "").strip() or None,
                    website=row.get("website", "").strip() or None,
                )
            )
    return employers
