"""Dump `jobs` to `data.js` for the board in `index.html`.

The board is a static file -- it is opened from disk, not served -- so the
data arrives as a plain script that assigns `window.BOARD`, not as `fetch`,
which a `file://` page is not allowed to make.

Everything interesting here is date handling. Ten applicant tracking systems
publish ten different things, and one of them publishes a sentence:

    workday          "Posted 30+ Days Ago"     -- relative, and a bucket
    lever            "1782419562496"           -- epoch milliseconds
    recruitee        "2026-05-13 10:57:22 UTC"
    workable         "2026-07-30"
    bamboohr         nothing at all

So the sort key carries its own precision, and the board says which it has
rather than rendering a guess as a date. `first_seen` is the floor: whatever
else is unknown, we know when we first saw the posting.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "employers.sqlite3"
OUT = Path(__file__).resolve().parent / "data.js"

TODAY = datetime.now(timezone.utc).date()

# Legal forms, stripped only to make a display name readable. This is cosmetic
# and deliberately separate from `resolve.py`'s normalizer, which decides
# identity and must not be loosened for the sake of a nicer label.
_SUFFIX = re.compile(
    r"[\s,]+(?:llc|l\.l\.c\.|inc\.?|ltd\.?|limited|plc|ab|a/s|aps|as|asa|nv|n\.v\.|bv|b\.v\."
    r"|gmbh|mbh|ug|ag|sa|s\.a\.?|sas|sarl|s\.a\.r\.l\.|sca|sicav|icav|oyj|oy|kb|kg"
    r"|srl|spa|pte|pty|lp|llp|co\.?|corp\.?|corporation"
    r"|holdings?|group|international|europe|\(uk\)|\(europe\))\.?$",
    re.I,
)

_HUBS = (
    ("stockholm", ("stockholm", "sverige", "sweden")),
    ("copenhagen", ("copenhagen", "københavn", "kobenhavn", "denmark", "danmark")),
    ("amsterdam", ("amsterdam", "netherlands", "nederland", "rotterdam", "utrecht")),
    ("switzerland", ("zurich", "zürich", "geneva", "genève", "zug", "basel",
                     "lugano", "switzerland", "schweiz", "suisse")),
    ("hong kong", ("hong kong", "hongkong", "kowloon")),
    ("singapore", ("singapore",)),
)


def display_name(names: list[str], domain: str) -> str:
    """The shortest registry name, cleaned -- else the domain's own label.

    Registry names are legal names and several map to one domain: State Street
    alone arrives as five. The shortest is the least encumbered by branch and
    subsidiary wording, which is what makes it the best label.
    """
    candidates = [n for n in names if n and len(n) < 60]
    if not candidates:
        return domain.split(".")[0].replace("-", " ").title()

    best = min(candidates, key=len)
    # Strip the legal form first, so `DPE INVESTMENT GESELLSCHAFT MBH` does not
    # come out of the case fixer as "Mbh". Only fully-cased names are touched at
    # all -- anything already mixed case is the firm's own styling.
    for _ in range(3):  # "... GmbH & Co. KG" is three suffixes deep
        shorter = _SUFFIX.sub("", best).strip(" ,.&")
        if shorter == best or not shorter:
            break
        best = shorter

    if best.isupper() or best.islower():
        parts = [_recase(w) for w in best.split()]
        if parts and parts[0].islower():  # a name does not open on "of"
            parts[0] = parts[0].title()
        best = " ".join(parts)
    return best


_CONNECTORS = {"of", "and", "the", "for", "van", "de", "der", "den", "och"}


def _recase(word: str) -> str:
    """Title-case a word from an all-caps name, unless it is an initialism.

    Very short, or vowel-less, are the two signals available without a
    dictionary: `AI`, `XTX` and `GPSC` keep their capitals, `BANK`, `OWL` and
    `ROSS` do not. It gets `CLSA` and `UCITS` wrong, which is a legible kind of
    wrong -- unlike "Mbh", which reads as a bug.
    """
    lowered = word.casefold()
    if lowered in _CONNECTORS:
        return lowered
    if len(word) <= 2 or not any(v in lowered for v in "aeiouyäöå"):
        return word.upper()
    return word.title()


def hub(location: str | None) -> str | None:
    if not location:
        return None
    low = location.casefold()
    for name, needles in _HUBS:
        if any(n in low for n in needles):
            return name
    return None


def posted(raw: str | None, first_seen: str) -> tuple[str, str]:
    """(ISO date, precision). Precision is shown, never quietly discarded.

    exact   -- the ATS published a timestamp
    approx  -- a relative count of days, so the date is right to within one
    atleast -- "30+ days", which is a floor and not a date at all
    seen    -- nothing published; the day we first saw it, an upper bound
    """
    seen = first_seen[:10]
    if not raw:
        return seen, "seen"

    text = raw.strip()

    if text.isdigit() and len(text) >= 12:  # lever, epoch milliseconds
        return datetime.fromtimestamp(int(text) / 1000, timezone.utc).date().isoformat(), "exact"

    iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        return date(*map(int, iso.groups())).isoformat(), "exact"

    low = text.casefold()
    if "today" in low or "just posted" in low:
        return TODAY.isoformat(), "exact"
    if "yesterday" in low:
        return (TODAY - timedelta(days=1)).isoformat(), "exact"
    days = re.search(r"(\d+)\+?\s*day", low)
    if days:
        n = int(days.group(1))
        precision = "atleast" if "+" in text else "approx"
        return (TODAY - timedelta(days=n)).isoformat(), precision
    months = re.search(r"(\d+)\+?\s*month", low)
    if months:
        return (TODAY - timedelta(days=30 * int(months.group(1)))).isoformat(), "atleast"

    return seen, "seen"


def main() -> None:
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row

    names: dict[str, list[str]] = {}
    for row in connection.execute("SELECT domain, query FROM domain_lookups WHERE domain IS NOT NULL"):
        names.setdefault(row["domain"], []).append(row["query"])

    firms: dict[str, dict] = {}
    jobs = []
    for row in connection.execute(
        "SELECT ats, token, job_id, domain, title, url, location, department,"
        " posted_at, first_seen FROM jobs"
    ):
        domain = row["domain"] or "unknown"
        if domain not in firms:
            firms[domain] = {
                "domain": domain,
                "name": display_name(names.get(domain, []), domain),
                "ats": row["ats"],
            }
        when, precision = posted(row["posted_at"], row["first_seen"])
        jobs.append(
            {
                "id": f"{row['ats']}:{row['token']}:{row['job_id']}",
                "firm": domain,
                "title": (row["title"] or "").strip(),
                "url": row["url"],
                "location": (row["location"] or "").strip() or None,
                "hub": hub(row["location"]),
                "team": (row["department"] or "").strip() or None,
                "posted": when,
                "precision": precision,
            }
        )

    jobs.sort(key=lambda j: (j["posted"], j["title"]), reverse=True)
    payload = {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "firms": firms,
        "jobs": jobs,
    }
    OUT.write_text(
        "window.BOARD = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(f"{len(jobs):,d} postings from {len(firms):,d} firms -> {OUT.name}")


if __name__ == "__main__":
    main()
