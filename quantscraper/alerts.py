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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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
    kind: str  # fail | empty | shrank | stale
    detail: str

    def __str__(self) -> str:
        return f"{self.kind:8s} {self.source:20s} {self.detail}"


def _median(values: list[int]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


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
        history = [row["row_count"] for row in runs[1:] if row["ok"] and row["row_count"]]
        if len(history) >= MIN_HISTORY:
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

    return alerts


def coverage(connection: sqlite3.Connection) -> list[str]:
    """Registries that have never recorded a run at all.

    A source that was added and never wired into a schedule looks identical to
    a healthy one from inside `runs`, because it has no rows to be wrong.
    """
    from .registries import REGISTRIES

    seen = {
        row["source"]
        for row in connection.execute("SELECT DISTINCT source FROM runs")
    }
    return sorted(set(REGISTRIES) - seen)
