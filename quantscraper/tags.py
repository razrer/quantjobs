"""Layer 5 -- turn a posting in `jobs` into tags you can filter and rank on.

`TAGGING.md` is the design. This is the half of it that can be built today,
which is the half that does not need a description: 81% of the corpus is
title, location and date only, and a classifier that waits for bodies
classifies nothing.

## The asymmetry this module is built on

`CLAUDE.md` says never to filter on a job title alone. That rule is about
*inclusion* and it is right: Goldman says "Strat", Jane Street says "Trader",
Stockholm says "kvantitativ analytiker", so a title that fails to look
quantitative proves nothing.

Exclusion is not the mirror image of that. Some titles name the entire
occupation, and no body text turns a *Receptionist* into a quant role. So:

- **a title can never prove a posting is relevant** -- inclusion needs the body,
  or a word specific enough to stand alone;
- **a title can prove a posting is a different job** -- a named occupation is
  decidable on the title, with the word that decided it recorded as evidence.

That is what makes the corpus tractable. It is also the sharpest place to be
wrong, so every rejection stores the phrase that caused it and the whole table
rebuilds from `jobs` on demand.

## Three verdicts, not two

`keep` · `reject` · `undecided`.

`undecided` is not a failure state, it is the **backfill queue**. A posting
whose title is ambiguous and whose body we never fetched is exactly the posting
worth fetching a body for, and there are far fewer of those than there are
postings -- which turns "92% have no description" from a blocker into a
prioritized list. A two-verdict classifier has to guess on those, and guessing
in this project means either a false rejection or a useless board.

## Two-sided rules for the two hard cases

A one-sided word list gets *receptionist* right and the two cases that actually
matter wrong:

- **Pure programming.** `Software Engineer` is in scope at Optiver and out of
  scope at a retail bank's payments team, so an engineering title rejects only
  when **no markets anchor appears anywhere in the posting**. The tag records
  which anchor rescued it, or that none did.
- **Non-quantitative finance.** `Economist`, `Financial Analyst` and `Credit
  Analyst` are quantitative at one firm and commentary at the next. These are
  never rejected on a title. They go to `undecided`, and the body settles it.

Firm boilerplate is deliberately not allowed to answer either question about
the *role*: a quant fund's description says "we are a systematic trading firm"
on its office-manager posting too. Anchors found in the title and department
decide the role; anchors found in the body only ever support or rescue.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass

from . import lexicon
from .db import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS job_tags (
    ats         TEXT NOT NULL,
    token       TEXT NOT NULL,
    job_id      TEXT NOT NULL,
    dimension   TEXT NOT NULL,
    value       TEXT NOT NULL,
    confidence  TEXT NOT NULL,   -- strong | weak
    evidence    TEXT,            -- the phrase that decided it
    tagger      INTEGER NOT NULL,
    tagged_at   TEXT NOT NULL,
    PRIMARY KEY (ats, token, job_id, dimension, value)
);

CREATE INDEX IF NOT EXISTS job_tags_by_dimension ON job_tags (dimension, value);
"""


@dataclass(frozen=True)
class Tag:
    dimension: str
    value: str
    confidence: str = "strong"
    evidence: str | None = None


# --------------------------------------------------------------------------
# The rules
# --------------------------------------------------------------------------


def classify(
    title: str,
    department: str | None = None,
    location: str | None = None,
    description: str | None = None,
    firm_type: str | None = None,
) -> list[Tag]:
    """Every tag for one posting, verdict first.

    `role` is the title and department -- what the posting is *for*. `body` is
    the description -- what the firm is *like*. Keeping them apart is what stops
    a quant fund's boilerplate from making its receptionist look relevant.
    """
    role = lexicon.normalize(f"{title or ''} {department or ''}")
    body = lexicon.normalize(description)
    has_body = len(body) > 200  # a stub is not a description
    full = role + body

    quant_role = lexicon.first(role, lexicon.QUANT)
    quant_body = lexicon.first(body, lexicon.QUANT)
    markets = lexicon.first(full, lexicon.MARKETS)

    tags: list[Tag] = []
    verdict, reason, evidence, confidence = _verdict(
        role, body, full, has_body, quant_role, quant_body, markets
    )
    tags.append(Tag("verdict", verdict, confidence, evidence))
    if reason:
        tags.append(Tag("reject_reason", reason, confidence, evidence))

    # Dimensions worth carrying whatever the verdict was: a rejection you
    # cannot slice by is a rejection you cannot audit.
    seniority, seniority_hit = _seniority(role, body)
    tags.append(Tag("seniority", seniority, "strong" if seniority_hit else "weak", seniority_hit))

    hub = _hub(location)
    if hub:
        tags.append(Tag("hub", hub[0], "strong", hub[1]))

    for family, hit in _multi(role, lexicon.ROLE_FAMILIES):
        tags.append(Tag("role_family", family, "strong", hit))
    for asset, hit in _multi(full, lexicon.ASSET_CLASSES):
        tags.append(Tag("asset_class", asset, "strong" if has_body else "weak", hit))
    for language, hit in _multi(full, lexicon.LANGUAGES):
        tags.append(Tag("language", language, "strong", hit))

    if firm_type:
        tags.append(Tag("firm_type", firm_type, "strong", "registry category"))

    return tags


def _verdict(
    role: str,
    body: str,
    full: str,
    has_body: bool,
    quant_role: str | None,
    quant_body: str | None,
    markets: str | None,
) -> tuple[str, str | None, str | None, str]:
    """(verdict, reject reason, evidence, confidence) for one posting.

    Ordered, and the order is the argument. Occupation runs first because it is
    the only test whose evidence is conclusive; anchors run before the
    ambiguous-title tests because a posting that says *quantitative* has
    answered the question the ambiguous tests would be guessing at.
    """
    # 1. A named occupation. Decidable on the title, and the strongest evidence
    #    in the module -- but a quantitative word *in the title itself* means
    #    the title is doing something else ("Recruiter, Quant Engineering"), so
    #    it downgrades the rejection to a read rather than overriding it.
    for terms, reason in (
        (lexicon.UNRELATED, "unrelated_occupation"),
        (lexicon.CORPORATE, "corporate_function"),
    ):
        hit = lexicon.first(role, terms)
        if hit:
            if quant_role:
                return "undecided", None, f"{hit} + {quant_role}", "weak"
            return "reject", reason, hit, "strong"

    # 2. Too senior to be worth reading: a year of experience does not reach a
    #    desk head. `vice president` is deliberately not in this list -- at a
    #    bank it is a mid-career grade, not an officer.
    if not lexicon.first(role, lexicon.NOT_HEAD):
        hit = lexicon.first(role, lexicon.HEAD_OR_MD)
        if hit:
            return "reject", "too_senior", hit, "strong"

    # 3. Crypto and web3 are an exclusion in their own right, per the role
    #    scope, and the word is unambiguous where most exclusions are not.
    hit = lexicon.first(role, lexicon.CRYPTO)
    if hit:
        return "reject", "crypto_web3", hit, "strong"

    # 4. The title says quantitative. Nothing further to decide.
    if quant_role:
        return "keep", None, quant_role, "strong"

    # 5. A body that demands a future graduation date. Titles never announce
    #    this and it is the one gate a graduate cannot pass.
    hit = lexicon.first(body, lexicon.STUDENT_ONLY)
    if hit:
        return "reject", "student_only", hit, "strong"

    # 6. Finance, but the relationship-and-processing part of it.
    hit = lexicon.first(role, lexicon.NON_QUANT_FINANCE)
    if hit:
        if quant_body:
            return "undecided", None, f"{hit} + {quant_body}", "weak"
        return "reject", "non_quant_finance", hit, "strong"

    # 7. Engineering, two-sided: rejected only for the absence of markets.
    #    Absence is weaker evidence than presence, and weaker still when there
    #    is no body to have been absent from -- the grade says so.
    hit = lexicon.first(role, lexicon.ENGINEERING)
    if hit:
        if quant_body:
            return "keep", None, f"{hit} + {quant_body}", "strong"
        if markets:
            return "keep", None, f"{hit} + {markets}", "weak"
        return "reject", "pure_engineering", hit, "strong" if has_body else "weak"

    # 8. The ambiguous middle -- analysts, economists, strategists. Never
    #    rejected on a title. Without a body this is the backfill queue.
    hit = lexicon.first(role, lexicon.AMBIGUOUS_FINANCE)
    if hit:
        if quant_body:
            return "keep", None, f"{hit} + {quant_body}", "strong"
        if markets:
            return "undecided", None, f"{hit} + {markets}", "weak"
        if has_body:
            return "reject", "non_quant_finance", f"{hit}, no markets language", "weak"
        return "undecided", None, hit, "weak"

    # 9. No rule fired. A full body with no markets word anywhere in it is
    #    real evidence; a bare unrecognised title is not, and says so.
    if quant_body:
        return "keep", None, quant_body, "weak"
    if has_body and not markets:
        return "reject", "no_markets_signal", None, "weak"
    if has_body:
        return "undecided", None, markets, "weak"
    return "undecided", None, None, "weak"


def _seniority(role: str, body: str) -> tuple[str, str | None]:
    for terms, value in (
        (lexicon.INTERN, "intern"),
        (lexicon.NEW_GRAD, "new_grad"),
        (lexicon.LEAD, "lead"),
        (lexicon.SENIOR, "senior"),
    ):
        hit = lexicon.first(role, terms)
        if hit:
            return value, hit
    if not lexicon.first(role, lexicon.NOT_HEAD):
        hit = lexicon.first(role, lexicon.HEAD_OR_MD)
        if hit:
            return "head_or_md", hit
    hit = lexicon.first(body, lexicon.STUDENT_ONLY)
    if hit:
        return "student_only", hit
    return "unknown", None


def _hub(location: str | None) -> tuple[str, str] | None:
    text = lexicon.normalize(location)
    for name, terms in lexicon.HUBS:
        hit = lexicon.first(text, terms)
        if hit:
            return name, hit
    return None


def _multi(text: str, groups: dict[str, tuple[str, ...]]) -> list[tuple[str, str]]:
    found = []
    for value, terms in groups.items():
        hit = lexicon.first(text, terms)
        if hit:
            found.append((value, hit))
    return found


# --------------------------------------------------------------------------
# Board profile -- the firm-level signal, measured rather than asserted
# --------------------------------------------------------------------------
#
# `TAGGING.md` proposes deriving `firm_type` from `employers.category`, on the
# grounds that a regulator's classification beats a firm's own marketing. It
# does -- but it classifies the *licensed entity*, and the board belongs to the
# *group*. LaSalle Investment Management is a Singapore Capital Markets
# Services Licensee, and the board its domain resolves to is `jll.com`: 2,021
# property-management postings. `airbus.com` arrived the same way, through
# Airbus Aeroassurances. The category says markets; the board says aircraft.
#
# So the honest firm signal is measured from what the board actually publishes.
# It also generalises the failure PLAN.md recorded and left open -- Palmer
# Square's careers page linking to a jewellery retailer's Lever board -- which
# this catches as a board whose postings are almost entirely unrelated.

MIN_BOARD = 10  # below this, a share is noise rather than a profile

# Sweden's national feed is not a firm's board. Profiling it would say
# "non-markets", which is true and useless: it carries every job in the country
# by design, and rejecting the feed would reject the hub it exists to cover.
NOT_A_BOARD = ("jobtech",)


def board_profiles(verdicts: dict[tuple[str, str], Counter]) -> dict[tuple[str, str], tuple[str, str]]:
    """(ats, token) -> (profile, evidence), from the verdicts of its postings."""
    profiles = {}
    for board, tally in verdicts.items():
        if board[0] in NOT_A_BOARD:
            continue
        total = sum(tally.values())
        if total < MIN_BOARD:
            continue
        relevant = tally["keep"] + tally["undecided"]
        share = relevant / total
        if share >= 0.40:
            profile = "markets"
        elif share >= 0.05:
            profile = "mixed"
        else:
            profile = "non_markets"
        profiles[board] = (profile, f"{relevant}/{total} not rejected")
    return profiles


# --------------------------------------------------------------------------
# Running it over the corpus
# --------------------------------------------------------------------------


def firm_types(connection: sqlite3.Connection) -> dict[str, str]:
    """domain -> firm type, via the name each domain was resolved from.

    Advisory only. It is the regulator's classification of one legal entity,
    and `board_profiles` above is why that is not the same thing as the board.
    """
    categories: dict[str, str] = {}
    for row in connection.execute(
        "SELECT name, category FROM employers WHERE category IS NOT NULL"
    ):
        categories.setdefault(row["name"].casefold().strip(), row["category"])

    types: dict[str, str] = {}
    for row in connection.execute(
        "SELECT query, domain FROM domain_lookups WHERE domain IS NOT NULL"
    ):
        domain = row["domain"]
        if domain in types:
            continue
        category = categories.get(row["query"].casefold().strip())
        if not category:
            continue
        low = category.casefold()
        for value, needles in lexicon.FIRM_TYPES:
            if any(needle in low for needle in needles):
                types[domain] = value
                break
    return types


def run(connection: sqlite3.Connection, limit: int | None = None) -> Counter:
    """Rebuild `job_tags` from `jobs`. Returns a tally of verdicts.

    Derived and rebuilt whole, the same contract `firms` has: the point of
    read-time classification is that a lexicon bug costs one re-run and never a
    re-scrape.
    """
    connection.executescript(SCHEMA)
    types = firm_types(connection)

    query = (
        "SELECT ats, token, job_id, domain, title, department, location, description"
        " FROM jobs WHERE removed_at IS NULL"
    )
    if limit:
        query += f" LIMIT {int(limit)}"

    tally: Counter = Counter()
    reasons: Counter = Counter()
    per_board: dict[tuple[str, str], Counter] = defaultdict(Counter)
    rows: list[tuple] = []
    stamp = now()

    for job in connection.execute(query):
        key = (job["ats"], job["token"], job["job_id"])
        tags = classify(
            job["title"],
            job["department"],
            job["location"],
            job["description"],
            types.get(job["domain"]),
        )
        for tag in tags:
            rows.append((*key, tag.dimension, tag.value, tag.confidence,
                         tag.evidence, lexicon.VERSION, stamp))
            if tag.dimension == "verdict":
                tally[tag.value] += 1
                per_board[(job["ats"], job["token"])][tag.value] += 1
            elif tag.dimension == "reject_reason":
                reasons[tag.value] += 1

    profiles = board_profiles(per_board)
    for (ats, token), (profile, evidence) in profiles.items():
        for job_id in _board_jobs(connection, ats, token, limit):
            rows.append((ats, token, job_id, "board_profile", profile,
                         "strong", evidence, lexicon.VERSION, stamp))

    with connection:
        connection.execute("DELETE FROM job_tags")
        connection.executemany(
            "INSERT OR REPLACE INTO job_tags (ats, token, job_id, dimension, value,"
            " confidence, evidence, tagger, tagged_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    tally.update({f"reason:{reason}": n for reason, n in reasons.items()})
    tally.update({f"board:{profile}": 1 for profile, _ in profiles.values()})
    return tally


def _board_jobs(connection, ats: str, token: str, limit: int | None) -> list[str]:
    query = ("SELECT job_id FROM jobs WHERE ats = ? AND token = ?"
             " AND removed_at IS NULL")
    return [row["job_id"] for row in connection.execute(query, (ats, token))]


def summary(connection: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    return {
        dimension: list(
            connection.execute(
                "SELECT value, COUNT(*) AS n, SUM(confidence = 'strong') AS strong"
                " FROM job_tags WHERE dimension = ? GROUP BY value ORDER BY n DESC",
                (dimension,),
            )
        )
        for dimension in ("verdict", "reject_reason", "board_profile", "role_family")
    }


def sample(connection: sqlite3.Connection, verdict: str, n: int,
           reason: str | None = None) -> list[sqlite3.Row]:
    """A random read of one verdict. The exit criterion is a manual read, and
    this is what it reads."""
    query = (
        "SELECT j.title, j.location, j.domain, j.ats, t.evidence,"
        "       (SELECT value FROM job_tags r WHERE r.ats = t.ats AND r.token = t.token"
        "        AND r.job_id = t.job_id AND r.dimension = 'reject_reason') AS reason"
        "  FROM job_tags t JOIN jobs j"
        "    ON j.ats = t.ats AND j.token = t.token AND j.job_id = t.job_id"
        " WHERE t.dimension = 'verdict' AND t.value = ?"
    )
    params: list[object] = [verdict]
    if reason:
        query += (" AND EXISTS (SELECT 1 FROM job_tags r WHERE r.ats = t.ats"
                  " AND r.token = t.token AND r.job_id = t.job_id"
                  " AND r.dimension = 'reject_reason' AND r.value = ?)")
        params.append(reason)
    query += " ORDER BY RANDOM() LIMIT ?"
    params.append(n)
    return list(connection.execute(query, params))
