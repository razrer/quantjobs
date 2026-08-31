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

import csv
import html
import json
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from quantscraper import (  # noqa: E402
    ats as ats_mod,
    dedup,
    extract,
    labels as labels_mod,
    lexicon,
    tagging,
)

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

# The value each dimension takes when nothing was decided. Omitted from the
# payload; the board reads a missing key as this.
# `none` is `spoken_language`'s default -- nothing beyond English and Swedish
# is demanded -- and no dimension uses the word to mean something, so omitting
# it is safe.
_NOTHING_KNOWN = {"unknown", "unstated", "other", "none", ""}

# **The sources where every poll reads the whole board**, which is what makes
# "absent from the latest read" mean "withdrawn". Derived from the reader table
# rather than restated, the same way `_HUB_ORDER` is derived from `_HUBS`.
#
# The national boards are deliberately outside it, and the reason is the whole
# safety argument: `jobtech` is a *delta* feed, and `jobindex --since` tops up
# from where the data already reaches. A poll of either refreshes only what
# changed, so "not in the latest poll" there is the overwhelming majority of a
# live board. Applying this rule to them would empty Sweden and Denmark on the
# next build. They manage withdrawal themselves -- `jobstream` writes
# `removed_at` on the ad the feed retires, and Singapore's `last_seen` question
# is answered by a completed sweep rather than by a query.
LAYER_THREE = frozenset(extract.EXTRACTORS)

# Defined in `tagging` so the labelling sheet gates on exactly the same list --
# a fixture that offers rows the board refuses to show is measuring a
# classifier nobody reads. Ordered, because a posting can carry more than one
# reason and the count attributes it to the first that would have caught it.
GATES = {
    # **The two that are not classifications at all, and they come first.**
    # Every other gate on this page answers "is this posting wanted"; these two
    # answer "is it still on offer", which is prior to it. Ordering them first
    # is what makes the others' counts readable: a posting the employer took
    # down is not a posting the tagger rejected, and attributing 30,522 of them
    # to `rejected` would overstate the one gate this file already says to
    # watch most carefully.
    #
    # Neither belongs in `tagging.GATES`, and that is not an oversight.
    # Everything there is a fact about the *posting*, which is why
    # `labels._candidates` can build a labelling frame from it. These are facts
    # about our *reading* -- they would tell a labeller nothing, and they
    # change without the posting changing.
    "withdrawn": "the board was read again and no longer lists it",
    "retired_board": "we no longer read the board this came from",
    **tagging.GATES,
    # Not an `exclusion_reason` like the other three -- it is the `relevance`
    # verdict itself, matched separately below. It lives in this table so the
    # per-reason counts printed on every build cover all four.
    "rejected": "read, and not this line of work",
    # **The sixth, and the only one whose evidence is about the employer rather
    # than the posting.** Added at the reader's instruction after it was
    # measured and left to them. It is deliberately *last* in this table,
    # because `hit` takes the first reason that matches and this is the weakest
    # claim of the six: a posting removed by any of the others should be
    # attributed to that one.
    "non_markets_board": "a board that publishes no markets work, and a title nothing could read",
    # **The same evidence one level down, for the sources whose board is not
    # one firm's own.** MyCareersFuture publishes ~95,000 postings under a
    # single token, so `(ats, token)` profiling cannot see the employer at all
    # -- and Singapore's noise is employer-shaped: `RECRUIT EXPRESS`, `THE
    # SUPREME HR ADVISORY`, `ANRADUS`, agencies posting thousands of ads of
    # which the tagger reads none as markets work. Profiled on `jobs.employer`
    # instead, 3,234 of them come out `non_markets`.
    #
    # It fires on evidence twice over exactly as the board version does: the
    # employer has shown us `MIN_BOARD` postings and none read as markets, and
    # *this* posting is one the tagger could not place. `RECRUIT EXPRESS` has
    # nine postings rated positively and all nine survive, because they are
    # rated rather than `unknown`.
    "non_markets_employer": "an employer that publishes no markets work, and a title nothing could read",
    # **The seventh, and the only one whose evidence is the reader's own
    # click.** A Reject on the board posts to `functions/correction_writer`,
    # `python -m quantscraper corrections` pulls it into `labels.csv`, and
    # until now nothing read it back: the card was hidden in that one browser's
    # `localStorage` and returned on the next build, in a new browser, or on
    # another machine. It fires on the strongest evidence this project has --
    # the reader read the posting and said no.
    "hand_rejected": "you rejected this on the board",
}

# Below this a board has too few postings for its profile to mean anything, and
# `lexicon.board_profile` returns None. Kept as a name here because the gate
# has to fail towards keeping when it cannot judge -- an unprofiled board is
# not a non-markets one.
def employer_profiles(connection, tagger: int) -> dict[str, str]:
    """`employer -> profile`, for the sources that publish under one token.

    `board_profiles` reads `(ats, token)` and that is right for a firm's own
    board. It is useless for a national portal: every MyCareersFuture posting
    shares one token, so the profile is of the portal rather than of anyone
    hiring. The employer string is the unit there, and `lexicon.board_profile`
    does not care which it is handed -- it takes three counts.
    """
    counts: dict[str, list[int]] = {}
    for employer, value in connection.execute(
        "SELECT j.employer, t.value FROM jobs j"
        " JOIN job_tags t ON t.ats = j.ats AND t.token = j.token"
        "   AND t.job_id = j.job_id AND t.dimension = 'relevance' AND t.tagger = ?"
        " WHERE j.removed_at IS NULL AND TRIM(COALESCE(j.employer, '')) <> ''",
        (tagger,),
    ):
        bucket = counts.setdefault(employer.strip(), [0, 0, 0])
        if value in ("relevant", "less_relevant", "adjacent"):
            bucket[0] += 1
        elif value == "unknown":
            bucket[1] += 1
        else:
            bucket[2] += 1
    profiles = {}
    for employer, (keep, undecided, rejected) in counts.items():
        read = lexicon.board_profile(keep, undecided, rejected)
        if read:
            profiles[employer] = read[0]
    return profiles


def hand_rejections(connection, one_domain=None) -> tuple[set[tuple[str, str, str]], set[str]]:
    """What the reader rejected, by key *and* by fingerprint.

    Returns `(keys, fingerprints)`. The keys are exact -- the three columns a
    correction carries -- and the fingerprints are what make the rejection
    stick to a **reposted** copy of the same advertisement, which is the whole
    reason this is not just a key lookup. Anradus reposts `Quant Researcher
    #77900` every five days under a new MyCareersFuture id and a byte-identical
    description; rejecting the 11 August one has to reject the 27 August one.

    **Only `labels.csv` is read, and that is deliberate.** It is the hand sheet
    -- the reader's own clicks, pulled off the live board by `corrections`, and
    their own labelling. `agent_labels.csv` and `board_triage.csv` are model
    output and gate nothing; a gate that removed 1,318 cards because a Haiku
    labeller called them noise would be the thing `TAGGING.md` warns about,
    wired straight into the page.
    """
    keys: set[tuple[str, str, str]] = set()
    for label in labels_mod.load(labels_mod.PATH):
        if label.relevance == "rejected":
            keys.add((label.ats, label.token, label.job_id))
    return keys, _fingerprints(connection, keys, one_domain or {})


def _fingerprints(connection, keys, one_domain) -> set[str]:
    """The fingerprint of every posting in `keys`, so a rejection survives a
    repost -- see `dedup`."""
    prints: set[str] = set()
    for ats, token, job_id in keys:
        row = connection.execute(
            "SELECT domain, employer, title, location, description FROM jobs"
            " WHERE ats = ? AND token = ? AND job_id = ?", (ats, token, job_id),
        ).fetchone()
        if row is None:
            continue
        prints.add(dedup.fingerprint(
            firm_key(one_domain.get((ats, token), row["domain"]), row["employer"]),
            row["location"], row["title"], row["description"],
        ))
    return prints


def board_profiles(tags: dict) -> dict[tuple[str, str], str]:
    """`(ats, token) -> profile`, measured from what each board publishes.

    **The one gate whose evidence is a property of the board, not the row.**
    That is why it is computed here rather than in `tagging.run`: `run` is
    incremental and visits only untagged postings, so a profile taken there
    would be drawn from whichever handful arrived this morning. This function
    sees every tag at the current version, which is the whole board.

    `jobtech` and the other national feeds are excluded by
    `lexicon.NOT_A_BOARD`: Sweden's feed is not a firm's board, and profiling
    it would return "non_markets", which is true and useless -- it carries
    every job in the country by design.
    """
    counts: dict[tuple[str, str], list[int]] = {}
    for (ats, token, _job), dimensions in tags.items():
        if ats in lexicon.NOT_A_BOARD:
            continue
        verdict = (dimensions.get("relevance") or ["unknown"])[0]
        bucket = counts.setdefault((ats, token), [0, 0, 0])
        if verdict in ("relevant", "less_relevant", "adjacent"):
            bucket[0] += 1
        elif verdict == "unknown":
            bucket[1] += 1
        else:
            bucket[2] += 1
    profiles = {}
    for board, (keep, undecided, rejected) in counts.items():
        read = lexicon.board_profile(keep, undecided, rejected)
        if read:
            profiles[board] = read[0]
    return profiles

# Dimensions a posting can hold several of at once -- a multi-asset desk, two
# languages -- shipped as lists. The rest are one verdict and ship as a scalar.
# `hub` is multi-valued too and is deliberately not here: these ship sorted,
# and a hub list carries the lexicon's priority order instead -- see where it
# is built.
_MULTI = {
    "asset_class": "asset",
    "language": "lang",
    "spoken_language": "speaks",
    "hard_gates": "gates",
    "exclusion_reason": "excl",
    "horizon": "hz",
}
_SINGLE = {
    "fit": "fit",
    "relevance": "rel",
    # One value since lexicon 12. It was multi-valued and shipped seven
    # families for a single posting, which is a word count rather than a
    # classification.
    "role_class": "role",
    "desk": "desk",
    "posting_language": "wrote",
    "seniority": "sen",
    # `pure` vs `quant`, and only for postings whose title names a seat on a
    # desk. Most postings with "Trader" in the title are the first kind.
    "trading_style": "tstyle",
    "experience_floor": "yrs",
    "code_depth": "cd",
    "contract": "ct",
}

TEASER = 260

# Words that mark a *vehicle* rather than the firm that runs it. Matched as
# whole words so "Fundamental" and "Trustee Services" are untouched, and kept
# to markers that no operating company puts in its own name -- `Capital` and
# `Investment` are firm words, not fund words, however often funds use them.
_VEHICLE = re.compile(
    r"\b(ucits|sicav|sicaf|icav|oeic|ccf|sif|raif|etfs?|fcp|fonds|fond"
    r"|sub-?fund|fund|funds|compartment|feeder|umbrella|trust|plc\s+fund)\b",
    re.IGNORECASE,
)


# Public suffixes that are two labels deep. Without these `gresearch.co.uk`
# reads as the firm "Co", which is the same mistake as taking the leftmost
# label and reading `cards.barclaycardus.com` as "Cards".
_TWO_LABEL_TLDS = (
    "co.uk", "org.uk", "ac.uk", "com.hk", "com.sg", "com.au", "co.jp",
    "com.br", "co.za", "co.nz", "com.cn", "co.in",
)


def _domain_label(domain: str) -> str:
    """The registrable label of a domain, title-cased for a card.

    Neither end of the host is the answer on its own: the leftmost label is
    `cards` or `careers`, and the rightmost is the TLD.
    """
    host = domain.casefold().strip(".")
    for suffix in _TWO_LABEL_TLDS:
        if host.endswith(f".{suffix}"):
            host = host[: -(len(suffix) + 1)]
            break
    else:
        host = host.rsplit(".", 1)[0]
    return host.rsplit(".", 1)[-1].replace("-", " ").title()


def display_name(names: list[str], domain: str) -> str:
    """The shortest registry name, cleaned -- else the domain's own label.

    Registry names are legal names and several map to one domain: State Street
    alone arrives as five. The shortest is the least encumbered by branch and
    subsidiary wording, which is what makes it the best label.

    **A fund is not its manager, and "shortest" reaches for one.** `pimco.com`
    carries 42 names, of which the shortest is *PIMCO ETFs* -- a product range,
    not the employer, and the card then advertises a job at a fund. A manager's
    own name is never the one carrying `UCITS` or `SICAV`, so vehicles are set
    aside when anything else is available. When a domain has nothing *but*
    fund names, the shortest of those is still better than the bare domain.
    """
    candidates = [n for n in names if n and len(n) < 60]
    operating = [n for n in candidates if not _VEHICLE.search(n)]
    # When a domain resolves to nothing *but* vehicles, the domain's own label
    # is the better card. `cards.barclaycardus.com` carries one name and it is
    # "Barclays US Equities Volatility Premium Fund" -- a card headed that way
    # reads as a job at a fund, which is a claim; "Barclaycardus" reads as a
    # domain we have not put a name to, which is the truth.
    if not operating:
        return _domain_label(domain)
    candidates = operating

    best = min(candidates, key=len)
    # Strip the legal form first, so `DPE INVESTMENT GESELLSCHAFT MBH` does not
    # come out of the case fixer as "Mbh". Only fully-cased names are touched at
    # all -- anything already mixed case is the firm's own styling.
    for _ in range(3):  # "... GmbH & Co. KG" is three suffixes deep
        shorter = _SUFFIX.sub("", best).strip(" ,.&")
        if shorter == best or not shorter:
            break
        best = shorter

    # Stripping can leave the name hanging on a connector. `_SUFFIX` carries
    # both `europe` and `nv`, so "Cigna Life Insurance Company of Europe NV"
    # came out as "Cigna Life Insurance Company of" -- which reads as a
    # truncation bug rather than a name.
    words = best.split()
    while len(words) > 1 and words[-1].casefold() in _CONNECTORS:
        words.pop()
    best = " ".join(words) or best

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


# The lexicon's own priority order, so a Stockholm-and-Frankfurt posting leads
# with Stockholm. Sorting the values instead would lead with `deprioritized`.
_HUB_ORDER = tuple(tagging._HUBS)


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


# How highly the board rates a card, for choosing between two copies of one
# opening. `unknown` and `out_of_scope` sit together at the bottom, which is
# what the board's own rail does with them.
_FIT_RANK = {"apply_now": 4, "strong": 3, "plausible": 2, "stretch": 1}


def still_listed(row, last_read: dict, live_boards: set) -> str | None:
    """The gate name if this posting is no longer on offer, else None.

    Two questions, both about our reading rather than about the posting, and
    both answered from facts rather than from a clock. **Nothing here reads
    "how old is this row"** -- an age threshold would fire on the absence of
    evidence, emptying the board whenever a run was simply not made, which is
    the one thing every gate on this page is forbidden to do.

    `last_read[board]` is the newest `last_seen` on that board, and it is exact
    rather than approximate because `db.upsert_jobs` stamps one timestamp per
    call and `extract.run` calls it once per board: every row a board writes in
    a poll shares a `last_seen`, so the newest one *is* that board's last
    complete read. A poll that fails or returns nothing writes nothing and
    moves nothing, so the cards stay -- the failure-safe direction.

    Restricted to `LAYER_THREE`, and that restriction is the whole safety
    argument rather than a tidiness: `jobtech` is a delta feed and
    `jobindex --since` tops up from where the data reaches, so on those sources
    "absent from the latest poll" describes most of a perfectly live board.
    """
    board = (row["ats"], row["token"])
    if row["ats"] not in LAYER_THREE:
        return None
    if board not in live_boards:
        return "retired_board"
    if row["last_seen"] < last_read.get(board, ""):
        return "withdrawn"
    return None


def board_domains(connection) -> dict[tuple[str, str], str]:
    """The one domain each firm board belongs to.

    `jobs` upserts on `(ats, token, job_id)` and never moves `domain`, so
    whichever domain reached a board first keeps the rows it brought and a
    second domain resolving to the same board files the rest under itself.
    **Barclays is the case that shows what it costs**: 1,557 postings under
    `cards.barclaycardus.com` -- a US card brand -- and 3 under `home.barclays`,
    both from `barclays|wd3|External_Career_Site_Barclays`, one board. So the
    board is two firms on the page, the big half is named `Barclaycardus`, and
    no cross-source fold can ever see that `BARCLAYS BANK PLC` is the same
    employer, because the name it would have to match is not there.

    **The token names the tenant, so let the token pick the domain.** Workday's
    is `tenant|wdN|site` and Greenhouse's is the board itself; the domain whose
    registrable label is one of those pieces is the firm whose board this is.
    Measured over the 24 firm boards this happens to, the rule is right or
    harmless on all 24 and beats "whichever brought the most rows" on nine --
    Barclays, Chicago Trading (`ctceurope.com` held 23 rows to
    `chicagotrading.com`'s 2), Piper Sandler, Bain Capital, Quilter, Toyota,
    ORIX, Mariner and Corebridge. Where no domain matches the tenant the
    majority keeps it, which is the behaviour today.

    `ats._NOT_A_TOKEN` supplies the pieces that are the vendor's furniture
    rather than anyone's name -- `careers`, `jobs`, `external` -- because
    `careers.sig.com` would otherwise be picked by any token containing
    `careers`. It is imported rather than restated: two copies of that list are
    two sides of a comparison free to drift.

    The national boards are excluded. One token there is a whole country and
    the domain is the individual employer's, which is the point of it.
    """
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for row in connection.execute(
        "SELECT ats, token, domain, COUNT(*) AS n FROM jobs"
        " WHERE removed_at IS NULL AND domain IS NOT NULL AND token IS NOT NULL"
        " GROUP BY ats, token, domain"
    ):
        if row["ats"] in dedup.PORTALS:
            continue
        counts.setdefault((row["ats"], row["token"]), {})[row["domain"]] = row["n"]

    chosen: dict[tuple[str, str], str] = {}
    for board, domains in counts.items():
        if len(domains) < 2:
            continue
        pieces = {
            piece for piece in re.split(r"[|_-]+", board[1].casefold())
            if piece and piece not in ats_mod._NOT_A_TOKEN
        }
        named = [d for d in domains if pieces & set(d.casefold().split("."))]
        if len(named) == 1:
            chosen[board] = named[0]
        else:
            chosen[board] = _parent(domains) or max(domains, key=lambda d: (domains[d], d))
    return chosen


def _parent(domains: dict[str, int]) -> str | None:
    """The one domain every other is a longer form of, if there is one.

    The fallback where the token names no domain, and it exists because the
    majority is not always the parent: Marsh's board is `mmc|wd1|MMC`, which
    matches neither `marsh.com` (15 cards) nor `marshmma.com` (62), so the
    majority rule alone renamed fifteen `Marsh` cards `Mma Asset Management`.
    A label the others start with is the brand they are extensions of.

    Dry-run over all 24 boards claimed by more than one domain: this fires on
    exactly one of them, Marsh, and never disagrees with the token rule -- the
    only other prefix pair is `icapital` inside `icapitalnetwork`, where the
    token already names the answer and this is not reached.
    """
    labels = {d: d.casefold().split(".")[-2] if d.count(".") else d.casefold() for d in domains}
    for candidate, short in labels.items():
        if all(other == short or other.startswith(short) for other in labels.values()):
            return candidate
    return None


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

    # Measured before the loop, because it needs every board whole -- see
    # `board_profiles`. Nothing else on this page reads across postings.
    profiles = board_profiles(tags)
    # The reader's own rejections, by key and by fingerprint. Read once: the
    # fingerprint of a rejected posting costs a row lookup each and there are
    # a few hundred of them at most.
    by_employer = employer_profiles(connection, tagging.TAGGER)
    # One firm per board, before anything reads `domain` -- `firm_key`, the
    # firm tile, the display name and the cross-source fold all hang off it.
    one_domain = board_domains(connection)
    # **Read after `one_domain`, and given it.** A fingerprint is keyed on the
    # firm, so the rejection side has to compute it from the same domain the
    # card does or the two stop meeting and a rejection quietly stops sticking
    # to a repost -- for exactly the 1,668 postings the remapping moves.
    rejected_keys, rejected_prints = hand_rejections(connection, one_domain)
    # **When each board was last read whole, and whether it is still read.**
    # See `LAYER_THREE` for why both are restricted to it.
    last_read = {
        (row["ats"], row["token"]): row["read_at"]
        for row in connection.execute(
            "SELECT ats, token, MAX(last_seen) AS read_at FROM jobs GROUP BY ats, token"
        )
    }
    live_boards = {
        (row["ats"], row["token"])
        for row in connection.execute(
            "SELECT ats, token FROM ats_resolution"
            " WHERE tier = 'A' AND token IS NOT NULL AND token <> ''"
        )
    }
    firms: dict[str, dict] = {}
    jobs = []
    gated: dict[str, int] = {reason: 0 for reason in GATES}
    # What the board-profile gate removed, by employer. It is the only gate
    # whose evidence lives outside `job_tags`, so `list --exclude` cannot show
    # what it ate and this is the substitute: every build says which boards it
    # emptied, which is the check you would actually run.
    by_board: dict[str, int] = {}
    untagged = 0
    untitled = 0
    for row in connection.execute(
        "SELECT ats, token, job_id, domain, employer, title, url, location,"
        # Withdrawn postings keep their row and stop being offered. The board
        # was showing them: `removed_at` was in the schema and not in this
        # query, so every ad JobStream had already retired still listed.
        " department, posted_at, deadline, description, first_seen, last_seen"
        " FROM jobs WHERE removed_at IS NULL"
    ):
        mine = tags.get((row["ats"], row["token"], row["job_id"]))

        # **A posting the tagger has not read is not a posting with no verdict,
        # and the difference is every gate on this page.** `unknown` means the
        # tagger looked and could not say, and is kept; *no row at all* means
        # nothing looked, and reading that as an empty tag set walks the
        # posting past all six gates at once. Reachable whenever `bodies` runs
        # without a re-tag, and whenever a `tag` is interrupted.
        if mine is None:
            untagged += 1
            continue

        # **A card with no title is not a posting, whatever the row says.** Not
        # a gate and not a classifier -- a gate removes a posting the reader
        # would not want, and this removes a record with nothing on it to read.
        # It printed as a blank card whose link went to the employer's whole
        # recruiting site, which is how the reader found it at Nasdaq and Sun
        # Life; `extract.workday` no longer creates them, and this is the guard
        # for the next source that does. Counted separately so it can never
        # grow quietly -- a rising number here is an extractor breaking.
        if not (row["title"] or "").strip():
            untitled += 1
            continue

        # **Two facts about our reading, checked before any judgement about the
        # posting.** A card only means something while the board it came from
        # still offers it, and until now nothing on this page asked: `jobs`
        # rows are never deleted and `removed_at` is written by `jobstream`
        # alone, so a posting whose board stopped listing it stayed on the page
        # for as long as the database did. Measured when this went in: **30,522
        # of 138,961 live Layer 3 postings** were absent from the most recent
        # read of their own board -- JLL, Citi, TD and US Bank each turning
        # over 40-50% of a three-thousand-posting board across three weeks.
        #
        # `last_read` is exact rather than a heuristic, and one line in `db.py`
        # is why: `upsert_jobs` stamps one timestamp per call and `extract.run`
        # calls it once per board, so every row a board writes in a poll shares
        # a `last_seen` and the newest one *is* that board's last complete
        # read. A poll that fails or comes back empty writes nothing and moves
        # nothing, which is the failure-safe direction: the cards stay.
        #
        # **`retired_board` is the other half and it is what makes a board
        # switch safe.** A posting can also stop being read because *we* moved:
        # when SIG's board went from the classic iCIMS portal to its career
        # site, the 269 rows under the old token would otherwise have sat
        # beside the new ones forever, since a board nobody polls never reports
        # a withdrawal. The evidence is that `(ats, token)` is no longer a
        # pollable target.
        unlisted = still_listed(row, last_read, live_boards)
        if unlisted:
            gated[unlisted] += 1
            continue

        # **Stage one, and the only filters on this page that remove rather
        # than rank.** Everything else in the rail is a knob the reader turns.
        #
        # It is safe to be this blunt here precisely because it is not blunt
        # anywhere else: the row stays in `jobs`, the reason stays in
        # `job_tags` with its evidence, and re-running the tagger rebuilds the
        # verdict. `list --exclude <reason>` audits what a gate ate.
        #
        # `rejected` is the widest and the one to watch: it is the only gate
        # whose evidence is a *judgement* rather than a named fact, and it went
        # in on a 1,000-posting machine-labelled sample that found no false
        # rejection. That is real evidence and not proof -- a model grading a
        # model shares the grader's blind spots -- which is why it is one line
        # to delete.
        #
        # Each is counted separately because a gate that removes silently is
        # how a widened lexicon quietly eats a hub, and one total would hide
        # which of them did it.
        reasons = mine.get("exclusion_reason", ())
        hit = next((reason for reason in GATES if reason in reasons), None)
        relevance = (mine.get("relevance") or ("unknown",))[0]
        if hit is None and relevance == "rejected":
            hit = "rejected"
        # **The sixth gate, and the only one that judges the employer.** A
        # posting the tagger could not read, on a board it has read hundreds of
        # times and found no markets work on -- Greystar apartments, Europcar,
        # a row of Singapore recruitment agencies.
        #
        # **Both halves are load-bearing, and the second keeps it safe.** A
        # `non_markets` board still carried 27 postings rated `relevant` and
        # 254 `adjacent`, and those stay: this removes only rows where the
        # tagger *also* had nothing to say, so it fires on evidence twice over.
        # An unprofiled board -- under `lexicon.MIN_BOARD` postings -- passes,
        # because failing towards keeping is the direction this project picks.
        #
        # **This page and `labels.py` gate alike by construction rather than by
        # sharing a list.** The reason is not an `exclusion_reason`, so it
        # cannot live in `tagging.GATES` where `labels._candidates` reads --
        # exactly as `rejected` cannot -- and it needs no entry there: the
        # sheet's frame requires `labels.anchored`, and the markets-title
        # branch in `tagging.py` runs last and converts any anchored posting
        # out of `unknown`. A row still at `unknown` therefore has neither.
        # **If that branch is ever moved, this stops being true.**
        if hit is None and relevance == "unknown" and (
            profiles.get((row["ats"], row["token"])) == "non_markets"
        ):
            hit = "non_markets_board"
            label = (row["employer"] or one_domain.get((row["ats"], row["token"]))
                     or row["domain"] or f"{row['ats']}/{row['token']}")
            by_board[label] = by_board.get(label, 0) + 1
        elif hit is None and relevance == "unknown" and (
            by_employer.get((row["employer"] or "").strip()) == "non_markets"
        ):
            hit = "non_markets_employer"
            label = (row["employer"] or "").strip()
            by_board[label] = by_board.get(label, 0) + 1
        domain = one_domain.get((row["ats"], row["token"]), row["domain"])
        key = firm_key(domain, row["employer"])

        # **The reader's own click, and the copy that came back wearing a new
        # id.** Checked after the tagger's gates so a posting removed for a
        # readable reason is still attributed to that reason -- the same
        # ordering argument `non_markets_board` makes above.
        fingerprint = dedup.fingerprint(
            key, row["location"], row["title"], row["description"])
        posting_key = (row["ats"], row["token"], row["job_id"])
        if hit is None and (
            posting_key in rejected_keys or fingerprint in rejected_prints
        ):
            hit = "hand_rejected"

        if hit:
            gated[hit] += 1
            continue

        if key not in firms:
            firms[key] = {
                "name": row["employer"] or display_name(names.get(domain, []), key),
                "domain": domain,
                "ats": row["ats"],
                "n": 0,
            }
        firms[key]["n"] += 1

        when, precision = posted(row["posted_at"], row["first_seen"])

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

        # **Every place the posting names**, so a seat open in Amsterdam and
        # London is counted under both and found under either. Ordered by
        # `tagging._HUBS`, the lexicon's own priority: the board leads a card
        # with `hub[0]`, so sorting alphabetically would lead with
        # `deprioritized`.
        #
        # `_HUB_ORDER` holds only the named places, so filtering through it
        # drops `other` and `unknown` and sorts the rest in one step. Both are
        # right to drop: anything genuinely elsewhere has already been gated,
        # so what is left named no place at all, and the rail says `unstated`.
        where = [h for h in _HUB_ORDER if h in (mine.get("hub") or ())]
        if where:
            job["hub"] = [h.replace("_", " ") for h in where]

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

        # Stripped again by `dedup.collapse`; it never reaches `data.js`.
        job["fp"] = fingerprint
        # **And what the cross-source fold needs**, which is a different
        # question and so a different key -- see `dedup`'s docstring. Every
        # name we hold for this employer goes in, because the two sides know
        # it by different ones: a portal prints the legal name it was given
        # and a firm's own board is known by whatever the registries called
        # its domain.
        job["xs"] = {
            "t": tagging.fold(job["title"]).strip(),
            "hubs": frozenset(job.get("hub") or ("unstated",)),
            "names": (row["employer"], firms[key]["name"], *names.get(domain, ())),
            "portal": row["ats"] in dedup.PORTALS,
        }
        jobs.append(job)

    # A stable base order. The board re-sorts on every render -- deadline
    # first, then whichever spine is selected -- so this only decides ties.
    jobs.sort(key=lambda j: (j["posted"], j["title"]), reverse=True)

    # **One card per advertisement.** Sorted newest-first above, so the first
    # card of a cluster is the freshest and `collapse` keeps it; the count
    # rides on it as `dup` and the card says so, because a board that removes
    # silently is the thing this file is most careful about. `firms[].n` is
    # left alone deliberately: it counts what the firm advertised, and a
    # recruiter posting one job eleven times has still advertised once.
    before = len(jobs)
    jobs = dedup.collapse(jobs)
    collapsed = before - len(jobs)

    # **One card per opening, which is not the same question as one card per
    # advertisement.** The pass above folds a repost within one source; this
    # one folds the copy a national board carries of a job the firm also
    # advertises itself. Run second, so it compares one surviving card per
    # source rather than a firm's board against a recruiter's eleven reposts.
    across = len(jobs)
    jobs = dedup.collapse_across_sources(
        jobs, rank=lambda card: (
            _FIT_RANK.get(card.get("fit"), 0),
            0 if card["ats"] in dedup.PORTALS else 1,
            card["posted"],
        ))
    folded_across = across - len(jobs)
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
    if collapsed:
        print(f"{collapsed:>7,d} folded into a card already shown"
              f"  (same firm, same place, same text)")
    if folded_across:
        print(f"{folded_across:>7,d} folded across sources"
              f"  (a national board's copy of a job the firm advertises itself)")
    # Said out loud on every run. A gate that removes postings silently is how
    # a widened lexicon quietly eats a hub, and this is the only number that
    # would show it.
    for reason, count in gated.items():
        print(f"{count:>7,d} gated  {reason:<13} {GATES[reason]}")
    if by_board:
        top = sorted(by_board.items(), key=lambda kv: -kv[1])[:8]
        print(
            "        of which, the boards it emptied: "
            + ", ".join(f"{name} {count:,d}" for name, count in top)
        )
    if untitled:
        # Also not a gate. A record with no title on it cannot be read by the
        # reader or by the tagger, and the only honest thing to do with one is
        # not to render it.
        print(f"{untitled:>7,d} held   untitled      (no title -- an extractor "
              f"wrote a record with nothing on it)")
    if untagged:
        # Not a gate: these were never read. It is a queue depth, and the
        # answer is to run `tag`, which is why it prints separately.
        print(
            f"{untagged:>7,d} held   untagged      (no verdict at lexicon "
            f"{tagging.TAGGER} -- run `tag`)"
        )
    print(f"{sum(gated.values()):>7,d} gated  total         (kept in the database; `list --exclude <reason>` shows them)")


if __name__ == "__main__":
    main()
