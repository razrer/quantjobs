"""Dump `jobs` to `data.js` for the board in `index.html`.

The board is a static file -- it is opened from disk, not served -- so the
data arrives as a plain script that assigns `window.BOARD`, not as `fetch`,
which a `file://` page is not allowed to make.

Two things here are worth reading before changing anything.

**Dates.** Ten applicant tracking systems publish ten different things, and one
of them publishes a sentence:

    workday          "Posted 30+ Days Ago"     -- relative, and a bucket
    lever            "1782419562496"           -- epoch milliseconds
    recruitee        "2026-05-13 10:57:22 UTC"
    workable         "2026-07-30"
    bamboohr         nothing at all

So the sort key carries its own precision, and the board says which it has
rather than rendering a guess as a date. `first_seen` is the floor: whatever
else is unknown, we know when we first saw the posting.

**Deadlines are read, never inferred.** `jobs.deadline` is set only where the
source published a closing date as a *field* -- today that is JobStream, which
sets one on every ad. It is deliberately not mined out of descriptions: "tjänsten
kan tillsättas innan sista ansökningsdag" appears on hundreds of Swedish ads and
carries no date at all, and Ashby prints "unless a specific application deadline
is stated" on every posting it has. Since the board pins an approaching deadline
above everything else, a false positive would nail the wrong card to the top of
the page for weeks -- the same asymmetry as the roster's `GRASSHOPPER
ESCAPEMENT, LLC`, one layer up.

**Defaults are omitted, not written.** A dimension whose value is the "nothing
known" bucket (`unknown`, `unstated`) is left off the record entirely and the
board reads a missing key as exactly that. Most postings are unknown in most
dimensions, so this is the difference between a 30 MB file and a 50 MB one.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from quantscraper import tagging  # noqa: E402

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

# The value each dimension takes when nothing was decided. Omitted from the
# payload; the board reads a missing key as this.
_NOTHING_KNOWN = {"unknown", "unstated", "other", ""}

# Dimensions a posting can hold several of at once -- a multi-asset desk, two
# languages -- shipped as lists. The rest are one verdict and ship as a scalar.
_MULTI = {
    "role_class": "role",
    "asset_class": "asset",
    "language": "lang",
    "hard_gates": "gates",
    "exclusion_reason": "excl",
    "horizon": "hz",
}
_SINGLE = {
    "fit": "fit",
    "relevance": "rel",
    "seniority": "sen",
    "code_depth": "cd",
    "contract": "ct",
}

TEASER = 260


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


_TAG = re.compile(r"<[^>]{0,200}>")
_SPACE = re.compile(r"\s+")


def teaser(description: str | None) -> str | None:
    """A first sentence or two for the hover panel, markup stripped.

    Half the corpus stores HTML and half stores plain text, and neither is
    labelled. Stripping at read time keeps `jobs.description` verbatim, which
    is what lets the tagger be re-run over it.
    """
    if not description:
        return None
    text = _SPACE.sub(" ", html.unescape(_TAG.sub(" ", description))).strip()
    if len(text) <= TEASER:
        return text or None
    cut = text[:TEASER]
    stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: stop + 1] if stop > TEASER // 2 else cut.rsplit(" ", 1)[0] + "…") or None


def firm_key(domain: str | None, employer: str | None) -> str:
    """What the board groups a posting under.

    The domain wherever we have one, because that is the identity every other
    layer agrees on. JobStream advertises for the whole country and only half of
    its ads carry a resolvable employer URL, so the rest group on the name the
    feed printed -- prefixed, so a name can never collide with a domain.
    """
    if domain:
        return domain
    return "~" + (employer or "unknown").casefold()


def main() -> None:
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row

    names: dict[str, list[str]] = {}
    for row in connection.execute("SELECT domain, query FROM domain_lookups WHERE domain IS NOT NULL"):
        names.setdefault(row["domain"], []).append(row["query"])

    # Layer 5's tags, keyed on the posting. The board used to carry its own
    # `hub()` over the raw location string -- a second implementation of a
    # rule that already exists in `tagging.py`, free to drift from it, and
    # blind to every other dimension. The lexicon version is pinned for the
    # same reason `coverage.py` pins it: `job_tags` keeps retired versions so
    # two can be diffed, and an unpinned read sums them.
    tags: dict[tuple[str, str, str], dict[str, list[str]]] = {}
    for row in connection.execute(
        "SELECT ats, token, job_id, dimension, value FROM job_tags WHERE tagger = ?",
        (tagging.TAGGER,),
    ):
        if row["value"] in _NOTHING_KNOWN and row["dimension"] != "hub":
            continue
        key = (row["ats"], row["token"], row["job_id"])
        tags.setdefault(key, {}).setdefault(row["dimension"], []).append(row["value"])

    firms: dict[str, dict] = {}
    jobs = []
    for row in connection.execute(
        "SELECT ats, token, job_id, domain, employer, title, url, location,"
        # Withdrawn postings keep their row and stop being offered. The board
        # was showing them: `removed_at` was in the schema and not in this
        # query, so every ad JobStream had already retired still listed.
        " department, posted_at, deadline, description, first_seen"
        " FROM jobs WHERE removed_at IS NULL"
    ):
        key = firm_key(row["domain"], row["employer"])
        if key not in firms:
            firms[key] = {
                "name": row["employer"] or display_name(names.get(row["domain"], []), key),
                "domain": row["domain"],
                "ats": row["ats"],
                "n": 0,
            }
        firms[key]["n"] += 1

        when, precision = posted(row["posted_at"], row["first_seen"])
        mine = tags.get((row["ats"], row["token"], row["job_id"]), {})
        tagged_hub = (mine.get("hub") or [None])[0]

        job = {
            "id": f"{row['ats']}:{row['token']}:{row['job_id']}",
            "firm": key,
            "title": (row["title"] or "").strip(),
            "posted": when,
            "ats": row["ats"],
        }
        if row["url"]:
            job["url"] = row["url"]
        if precision != "exact":
            job["prec"] = precision
        if row["deadline"]:
            job["due"] = row["deadline"][:10]
        if (row["location"] or "").strip():
            job["loc"] = row["location"].strip()
        if (row["department"] or "").strip():
            job["team"] = row["department"].strip()

        # The tagger's hub, falling back to the local reading only for a
        # posting it has not seen yet -- an untagged posting must still be
        # findable.
        where = tagged_hub if tagged_hub not in (None, "other", "unknown") else hub(row["location"])
        if where:
            job["hub"] = where.replace("_", " ")

        for dimension, short in _SINGLE.items():
            value = (mine.get(dimension) or [None])[0]
            if value:
                job[short] = value
        for dimension, short in _MULTI.items():
            values = mine.get(dimension)
            if values:
                job[short] = sorted(values)

        snippet = teaser(row["description"])
        if snippet:
            job["about"] = snippet

        jobs.append(job)

    # A stable base order. The board re-sorts on every render -- deadline
    # first, then whichever spine is selected -- so this only decides ties.
    jobs.sort(key=lambda j: (j["posted"], j["title"]), reverse=True)
    payload = {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tagger": tagging.TAGGER,
        "firms": firms,
        "jobs": jobs,
    }
    OUT.write_text(
        "window.BOARD = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    shortlist = sum(1 for j in jobs if j.get("fit") in ("apply_now", "strong"))
    dated = sum(1 for j in jobs if "due" in j)
    print(
        f"{len(jobs):,d} postings from {len(firms):,d} firms -> {OUT.name}"
        f"  ({shortlist:,d} worth reading, {dated:,d} with a closing date,"
        f" {OUT.stat().st_size / 1e6:.1f} MB)"
    )


if __name__ == "__main__":
    main()
