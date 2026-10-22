"""Stage 8 -- noticing when a source breaks quietly.

`MIN_EXPECTED` is a fixed floor per registry and it only catches catastrophe.
A source that normally returns 26,495 rows and starts returning 400 sails past
a floor of 15,000 while having lost 98% of its coverage. Nothing announces
that, which is the whole failure mode this project is built against.

This makes the check **distributional**: compare a run against what that source
has historically returned, not against a number written once by hand.

**Deliberately not a mean and a standard deviation.** Volumes here are small
samples, and one bad run poisons both -- a source that returns 0 today drags its
own baseline down and looks healthy tomorrow. The median is unmoved by a single
outlier, so a breakage does not quietly become the new normal.

Four things are checked, and each corresponds to a real way a source has failed
or plausibly could:

  fail       the fetch raised -- already loud, repeated here so one report
             covers everything
  empty      zero rows with no error, the classic silent breakage
  shrank     materially below the historical median for that source
  stale      no successful run for a long time, which is how a source that
             was quietly dropped from a schedule looks
  lexicon    the classifier was edited without `tagging.TAGGER` being bumped,
             so `tag` visits nothing and every summary keeps serving the
             previous answers -- see `tagging.fingerprint`
  unpollable a tier-A row addresses nothing -- no board token, or an ATS with
             no extractor -- so it counts as resolved everywhere and is polled
             nowhere. See `_unreachable_boards`.
  layer2     a Layer 2 cache has not been written to in a month, so new
             employers are arriving and never reaching a pollable board --
             see `_layer2_alerts`, which is the one check here that asks when
             a step last worked rather than how much it returned

A source with no history is not judged. One run is not a baseline, and inventing
one would produce noise on exactly the sources that are newest and least
verified.

**It can only see what writes to `runs`, and for a long time that was the
registries alone.** job-room.ch was built, guarded and proved against a live
portal while `jobs` held not one Swiss row -- and nothing here said so, because
a source that collected nothing is indistinguishable from a source nobody asked
about. The Layer 4 pollers (`sweden`, `denmark`, `singapore`, `switzerland`,
`jobstream`) record a run now; `cli._record_poll` is where, and it deliberately
skips a `--since` top-up or a `--pages` probe so a baseline is never built from
a deliberate subset.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import tagging

# Below this share of the historical median, a run is treated as broken. Set
# loosely on purpose: registries genuinely move by a few per cent between runs,
# and an alert that cries wolf gets ignored, which is worse than not having one.
SHRANK_TO = 0.70

# Runs needed before a median means anything.
MIN_HISTORY = 2

# A source not seen for this long is presumed forgotten rather than stable.
STALE_AFTER = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class Alert:
    source: str
    kind: str  # fail | empty | shrank | stale | lexicon | layer2 | unpollable | board
    detail: str

    def __str__(self) -> str:
        return f"{self.kind:8s} {self.source:20s} {self.detail}"


def _median(values: list[int]) -> float:
    """`statistics.median`, kept behind a name because the *choice* is the
    point. See the module docstring: a mean lets one broken run pull the
    baseline down, so this is a median and must stay one."""
    return float(statistics.median(values))


def _parse(moment: str | None) -> datetime | None:
    if not moment:
        return None
    try:
        parsed = datetime.fromisoformat(moment)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def check(connection: sqlite3.Connection, now: datetime | None = None) -> list[Alert]:
    """Every source's latest run, judged against its own history."""
    now = now or datetime.now(timezone.utc)
    sources = [
        row["source"]
        for row in connection.execute("SELECT DISTINCT source FROM runs ORDER BY source")
    ]

    alerts: list[Alert] = []
    for source in sources:
        runs = connection.execute(
            # `id` breaks the tie: `started_at` has one-second resolution, and
            # two runs inside the same second order arbitrarily without it --
            # which silently picks the wrong run as "latest" and reports the
            # broken one as history.
            "SELECT started_at, row_count, ok, error FROM runs"
            " WHERE source = ? ORDER BY started_at DESC, id DESC",
            (source,),
        ).fetchall()
        latest = runs[0]

        if not latest["ok"]:
            alerts.append(Alert(source, "fail", latest["error"] or "no error recorded"))
            continue

        if latest["row_count"] == 0:
            alerts.append(Alert(source, "empty", "returned zero rows without failing"))
            continue

        # Baseline from earlier *successful* runs only. Including the run under
        # test would let a breakage vote on its own normality.
        #
        # **And a delta source has no baseline to build.** Its row count is the
        # gap since the last poll, so a median over its history averages polls
        # taken at different intervals and means nothing: a `daily` run five
        # hours after the last one returns a few hundred rows against a median
        # of twenty thousand, and `shrank` fired on both Swedish and Swiss
        # sources on essentially every close-spaced run. `jobroom_ch.Sweep`
        # already refuses an absolute floor for this exact reason and explains
        # why; this is the same floor taken from a median rather than from a
        # constant, and it is wrong for the same reason. The other three checks
        # still apply -- they ask whether the source answered at all.
        history = [row["row_count"] for row in runs[1:] if row["ok"] and row["row_count"]]
        if source not in _deltas() and len(history) >= MIN_HISTORY:
            median = _median(history)
            if latest["row_count"] < median * SHRANK_TO:
                alerts.append(
                    Alert(
                        source,
                        "shrank",
                        f"{latest['row_count']:,d} rows against a median of "
                        f"{median:,.0f} ({latest['row_count'] / median:.0%})",
                    )
                )
                continue

        started = _parse(latest["started_at"])
        if started and now - started > STALE_AFTER:
            alerts.append(
                Alert(source, "stale", f"last successful run {(now - started).days} days ago")
            )

    # **The one check here that is not about a source.** Every alert above asks
    # whether a *fetch* went quiet; this asks whether the *classifier* did, and
    # it is the same failure shape one layer along -- `tag` visits only
    # postings with no row at the current `TAGGER`, so a lexicon edited without
    # a bump reports `tagged 0 postings` and every summary below it keeps
    # serving the previous version's answers. Loud here rather than nowhere.
    if tagging.drifted(connection):
        alerts.append(Alert(
            f"tagger {tagging.TAGGER}", "lexicon",
            "the needle lists have changed since these tags were written --"
            " bump tagging.TAGGER and re-run `tag`, or the board is serving"
            " the previous classifier's answers",
        ))
    alerts.extend(_layer2_alerts(connection, now))
    alerts.extend(_unreachable_boards(connection))
    alerts.extend(_board_alerts(connection))
    return alerts


def _unreachable_boards(connection: sqlite3.Connection) -> list[Alert]:
    """Tier-A rows that no poller can reach, which every report called healthy.

    **Tier A means "an ATS and token were fingerprinted, so Layer 3 polls the
    feed".** Two states satisfy the tier and not the sentence, and
    `extract.targets` filters both out of its queue -- so they are counted as
    resolved everywhere, polled nowhere, and yield nothing forever. That is the
    silent coverage loss `ats.py`'s docstring is written against, reached from
    the other direction: not an untiered domain, a tiered one addressing
    nothing.

      * **no token.** 36 rows, and 16 of them were one bug: `_custom_host`
        skipped its own vendor rule whenever the host patterns had named the
        vendor, including when they had named it and captured nothing, so
        `careerN.successfactors.eu` -- SAP's datacentre, naming no tenant --
        held Eurex, Hang Seng, PFA and thirteen others off the board.
      * **an `ats` with no extractor.** 10 Taleo rows, which no reader exists
        for; `taleo` is simply absent from `EXTRACTORS`, so the `IN` clause in
        `extract.targets` drops them without a word.

    Grouped by vendor rather than listed per row, because the useful fact is
    which *reader or pattern* is missing. Reported and never acted on: the
    answer to a tokenless row is a fix here, not a demotion that would discard
    a verified careers URL `pages.py` has been diffing for months.
    """
    from . import extract

    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ats_resolution'"
    ).fetchone():
        return []

    found: list[Alert] = []
    for row in connection.execute(
        "SELECT ats, COUNT(*) AS n FROM ats_resolution"
        " WHERE tier = 'A' AND (token IS NULL OR token = '')"
        " GROUP BY ats ORDER BY n DESC, ats"
    ):
        found.append(Alert(
            row["ats"] or "(no ats)", "unpollable",
            f"{row['n']:,d} tier-A row(s) carry no board token, so nothing"
            " polls them -- the pattern captured the vendor and not the tenant",
        ))

    placeholders = ",".join("?" * len(extract.EXTRACTORS))
    for row in connection.execute(
        f"SELECT ats, COUNT(*) AS n FROM ats_resolution WHERE tier = 'A'"
        f" AND ats NOT IN ({placeholders}) GROUP BY ats ORDER BY n DESC, ats",
        tuple(extract.EXTRACTORS),
    ):
        found.append(Alert(
            row["ats"] or "(no ats)", "unpollable",
            f"{row['n']:,d} tier-A row(s) resolved to '{row['ats']}', which has"
            " no extractor -- `extract.targets` drops them silently",
        ))
    return found


# The Layer 2 caches, and the column that says when each last did any work.
# Derived from the modules' own schemas rather than restated as SQL here would
# be better still; three table names is the smallest thing that can drift, and
# a wrong one reads as "healthy" -- so `tests/test_alerts.py` asserts each
# table exists.
#
# **`domains` excludes `method = 'registry'` and that clause is the whole
# check.** `harvest_registry_domains` re-seeds every firm whose registry row
# published a website -- 19,997 rows, `INSERT OR REPLACE`, no network -- so it
# rewrites `checked_at` on a fifth of the table every time `domains` is
# invoked, whether or not one firm was actually probed. A plain `MAX` over the
# table therefore reads fresh on a step that resolved nothing, which is the
# precise shape of false health this module exists to refuse.
_LAYER_TWO = (
    ("domains", "domain_lookups", "resolve a firm name to a domain",
     "method <> 'registry'"),
    ("ats", "ats_resolution", "fingerprint a domain to a board", "1"),
    ("discover", "board_lookups", "guess a board a careers page never named", "1"),
)


def _layer2_alerts(connection: sqlite3.Connection, now: datetime) -> list[Alert]:
    """Layer 2 going quiet, which is invisible to every check above.

    **This is the failure it was written for, found two months late.** The
    weekly sequence polls the boards it already knows and refreshes the
    registries that supply new employers -- and nothing between the two ran at
    all. `domain_lookups` had 53,742 of 53,789 rows last checked in August and
    `ats_resolution` 19,839 of 20,033, while every registry reported healthy
    every week. So the universe kept growing and the pollable board set stayed
    frozen at its August state: a firm registered since then had no domain, and
    a firm that changed ATS since then was simply quiet.

    `check` above cannot see this and it is not an oversight it can fix. It
    walks `SELECT DISTINCT source FROM runs`, and these three steps write no
    run -- deliberately, because their row count is a *budget* and not a
    volume: a queue that returns 500 because that was the limit, then 0 because
    it is exhausted, would read as `shrank` and then `empty` on a healthy
    pipeline. The honest question for a cache is not how much it wrote but when
    it last wrote anything, so that is what this asks.

    One alert per step rather than one for the layer, because they fail
    separately: `ats` cannot work on domains `domains` has not resolved, so the
    first of them to go quiet is the one worth naming.
    """
    found: list[Alert] = []
    for step, table, what, worked in _LAYER_TWO:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            # A fresh install has no cache yet, which is not the same fact as a
            # scheduled step that stopped running. `coverage` is where "never
            # ran at all" belongs.
            continue
        row = connection.execute(
            f"SELECT MAX(checked_at) AS last, COUNT(*) AS n FROM {table}"
            f" WHERE {worked}"
        ).fetchone()
        last = _parse(row["last"] if row else None)
        if last is None:
            # No row this step put there. An empty table is a fresh install and
            # `coverage` owns "never ran at all"; a table holding *only* free
            # re-seeds is this check's own answer, because then nothing has
            # ever probed and the board set cannot grow.
            if connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                found.append(Alert(
                    step, "layer2",
                    f"nothing here has ever tried to {what}",
                ))
            continue
        age = now - last
        if age > STALE_AFTER:
            found.append(Alert(
                step, "layer2",
                f"nothing has tried to {what} for {age.days} days -- new"
                f" employers are not reaching a pollable board",
            ))
    return found


# A board is allowed a bad morning before it is worth reporting: a vendor
# outage looks exactly like a dead board from here, and Workday's own status
# page said so while Topdanmark's tenant answered 422 on every pod. Two
# consecutive failures is a fortnight at this project's cadence.
BOARD_FAILURES = 2


def _board_alerts(connection: sqlite3.Connection) -> list[Alert]:
    """Layer 3 boards that have stopped answering and were holding postings.

    **`check` above cannot see Layer 3 at all**, and that is not an oversight
    it can fix: it walks `SELECT DISTINCT source FROM runs`, and a thousand
    boards poll under no source name. So a board that had 404'd every week for
    months was invisible to the one report whose entire job is noticing
    silence -- the job-room.ch failure, a layer down and a thousand times over.

    **Reported only when the board was holding postings**, which is the whole
    finding from the sweep that prompted this: of 42 failing boards, 27 are
    404s holding nothing -- stale embeds and other firms' boards, correctly
    dead -- and alerting on those would bury the fifteen that cost 2,265
    postings. An alert that cries wolf gets ignored, which `SHRANK_TO` already
    says one constant up.
    """
    # Imported inside the function, like `REGISTRIES` below, so this module
    # keeps its one promise: it reads, and it depends on nothing that writes.
    # The query lives in `db` rather than being restated here, because two
    # copies of "which boards are failing" is the `feed_state` mistake.
    from . import db

    rows = db.failing_boards(connection, minimum=BOARD_FAILURES)
    return [
        Alert(
            f"{row['ats']}/{row['token']}"[:20],
            "board",
            f"{row['failures']} consecutive failures, last held"
            f" {row['postings']:,d} postings -- {(row['error'] or '')[:90]}",
        )
        for row in rows
        if row["postings"]
    ]


def _deltas() -> frozenset[str]:
    """Sources whose row count measures elapsed time rather than health.

    Read off the modules rather than listed here, so a source cannot be a delta
    in one file and a full sweep in another -- the `feed_state` argument, and
    the reason `_HUB_ORDER` is derived rather than restated. A source that
    declares nothing is judged, which is the failing-towards-noticing
    direction this module always picks.
    """
    from . import jobroom_ch, jobstream

    return frozenset(
        module.NAME
        for module in (jobstream, jobroom_ch)
        if getattr(module, "DELTA", False)
    )


def _expected() -> set[str]:
    """Every source that is supposed to appear in `runs`.

    **The registries are only half of it, and the missing half cost Singapore
    ten days.** `check` walks `SELECT DISTINCT source FROM runs`, so a source
    with no rows is not judged; `coverage` is the backstop for exactly that,
    and it read `REGISTRIES` alone. The national boards are not registries --
    they live in the package root, not in `registries/` -- so MyCareersFuture
    was missing from **both** lists at once and `alerts` printed `all sources
    healthy` while it had not run since the 17th. Layer 1 and Layer 4 are the
    same question here: was this source asked, and did it answer.

    Imported inside the function, like `REGISTRIES`, so this module keeps its
    one promise -- it reads, and it depends on nothing that writes.
    """
    from . import (
        iesjobs, jobbsafari, jobindex, jobroom_ch, jobstream, mycareersfuture,
    )
    from .registries import REGISTRIES

    return set(REGISTRIES) | {
        module.NAME for module in
        (jobstream, jobroom_ch, jobindex, jobbsafari, mycareersfuture, iesjobs)
    }


def coverage(connection: sqlite3.Connection) -> list[str]:
    """Sources that have never recorded a run at all.

    A source that was added and never wired into a schedule looks identical to
    a healthy one from inside `runs`, because it has no rows to be wrong.
    """
    seen = {
        row["source"]
        for row in connection.execute("SELECT DISTINCT source FROM runs")
    }
    return sorted(_expected() - seen)
