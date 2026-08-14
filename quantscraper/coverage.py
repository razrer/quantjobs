"""Stage 10 -- measuring how much of the market we actually see.

Every earlier stage reports what it *found*. None of them can say what it
missed, and "exhaustiveness is the hard requirement" is not a claim any of
those numbers support: a pipeline that polls 800 boards perfectly and is blind
to 8,000 others reports the same 800 either way.

**Capture-recapture is the standard answer and it needs an honest guard.**
Two independent samples of the same population overlap in proportion to how
much of it each one catches: with `a` employers seen by us, `b` seen by a
second source and `m` by both, the population is about `a*b/m`. The Chapman
correction used here is the small-sample version, which is the only responsible
choice at this scale.

**The estimator is refused rather than reported when the overlap is too
small.** Right now `m` is *zero* for Sweden -- JobStream is advertising for 582
employers and two of them are in our universe -- and Chapman would cheerfully
return 110 from that. A number computed from no overlap is not a measurement,
and printing one would be the same failure the rest of this project keeps
designing against: a confident answer where the honest one is "not yet".

**What is measurable today is the miss list**, and it is worth more than the
estimate anyway. An employer advertising in the second source that our pipeline
does not poll is not a statistic, it is a named gap with a domain attached.

**The second source exists for exactly one hub.** Sweden has JobStream, a
national feed that reaches every employer. Copenhagen, Amsterdam, Switzerland,
Hong Kong and Singapore have nothing comparable, so their coverage is
unmeasured -- and reported as unmeasured, not as complete.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import tagging

# Below this, the estimator is noise. With an overlap of one, moving a single
# employer between samples moves the estimate by a factor of two.
MIN_OVERLAP = 5

# The second source, and the hub it can speak for.
SECOND_SOURCE = "jobtech"
SECOND_SOURCE_HUB = "stockholm"


@dataclass(frozen=True, slots=True)
class Estimate:
    hub: str
    ours: int
    theirs: int
    overlap: int
    population: int | None
    reason: str

    @property
    def share(self) -> float | None:
        """Fraction of the estimated population our pipeline polls."""
        if not self.population:
            return None
        return self.ours / self.population


def _chapman(a: int, b: int, m: int) -> int:
    """Chapman's bias-corrected Lincoln-Petersen estimate.

    Plain `a*b/m` is biased upward at small samples and undefined at `m = 0`.
    Chapman is defined everywhere, which is exactly why the caller has to
    refuse it rather than trust it -- see `MIN_OVERLAP`.
    """
    return int((a + 1) * (b + 1) / (m + 1) - 1)


def _domains(connection: sqlite3.Connection, sql: str, *params) -> set[str]:
    return {row[0] for row in connection.execute(sql, params)}


def estimate(connection: sqlite3.Connection) -> Estimate:
    """Capture-recapture for the one hub that has a second source.

    Both samples are restricted to employers already in our universe. A
    national feed carries waiting staff and care homes; our pipeline is
    employer-first over financial registers. Estimating one population from
    two differently scoped frames is not a measurement of either.
    """
    universe = _domains(
        connection,
        "SELECT DISTINCT domain FROM domain_lookups WHERE domain IS NOT NULL",
    )
    ours = _domains(
        connection,
        """
        SELECT DISTINCT j.domain FROM jobs j
        JOIN job_tags t ON t.ats = j.ats AND t.token = j.token
                       AND t.job_id = j.job_id
        WHERE t.dimension = 'hub' AND t.value = ? AND t.tagger = ?
          AND j.ats != ? AND j.removed_at IS NULL AND j.domain IS NOT NULL
        """,
        SECOND_SOURCE_HUB,
        tagging.TAGGER,
        SECOND_SOURCE,
    )
    theirs = _domains(
        connection,
        "SELECT DISTINCT domain FROM jobs WHERE ats = ?"
        " AND removed_at IS NULL AND domain IS NOT NULL",
        SECOND_SOURCE,
    ) & universe

    overlap = len(ours & theirs)
    if overlap < MIN_OVERLAP:
        return Estimate(
            SECOND_SOURCE_HUB, len(ours), len(theirs), overlap, None,
            f"overlap {overlap} is below {MIN_OVERLAP}: not a measurement yet."
            " JobStream is a delta feed, so its census builds up over days of"
            " polling rather than arriving in one run.",
        )
    return Estimate(
        SECOND_SOURCE_HUB, len(ours), len(theirs), overlap,
        _chapman(len(ours), len(theirs), overlap),
        "Chapman estimate. Independence is imperfect -- both samples favour"
        " employers with a web presence -- so this is a floor on the"
        " population and a ceiling on our share.",
    )


def missed(connection: sqlite3.Connection, limit: int = 40):
    """Employers advertising in the second source that we do not poll.

    The actionable half of this stage. Each row is a firm we know exists, that
    is demonstrably hiring, and whose postings reach us through the national
    feed only -- so its own board is either untiered, tier C, or resolved to
    an ATS with no extractor.
    """
    return connection.execute(
        """
        SELECT j.domain, COUNT(*) AS ads, a.tier, a.ats
        FROM jobs j
        LEFT JOIN ats_resolution a ON a.domain = j.domain
        WHERE j.ats = ? AND j.removed_at IS NULL AND j.domain IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM jobs ours
              WHERE ours.domain = j.domain AND ours.ats != ?
          )
          -- Restricted to firms the registers already gave us. Without this
          -- the list is staffing agencies and municipalities -- Adecco,
          -- Region Stockholm, Malmö stad -- which are hiring, are not
          -- financial employers, and drown the firms that are.
          AND EXISTS (
              SELECT 1 FROM domain_lookups d WHERE d.domain = j.domain
          )
        GROUP BY j.domain
        ORDER BY ads DESC, j.domain
        LIMIT ?
        """,
        (SECOND_SOURCE, SECOND_SOURCE, limit),
    ).fetchall()


def by_hub(connection: sqlite3.Connection):
    """What the pipeline actually holds per hub, and from how many employers.

    Not a coverage number -- there is no denominator here. It is the thing a
    coverage number would be divided into, and it is worth reading on its own:
    a hub with 3 employers behind 200 postings is one board away from zero.
    """
    return connection.execute(
        """
        SELECT t.value AS hub,
               COUNT(*) AS postings,
               COUNT(DISTINCT j.domain) AS employers,
               SUM(f.value IN ('apply_now', 'strong')) AS worth_reading
        FROM job_tags t
        JOIN jobs j ON j.ats = t.ats AND j.token = t.token AND j.job_id = t.job_id
        LEFT JOIN job_tags f ON f.ats = j.ats AND f.token = j.token
                            AND f.job_id = j.job_id AND f.dimension = 'fit'
                            AND f.tagger = t.tagger
        -- Pinned to one lexicon version. `job_tags` keeps every version so two
        -- can be diffed, which means an unpinned count sums them: the hub
        -- table read 49,808 postings in `unknown` after `unknown` had already
        -- been split into `other`, because six retired taggers still said so.
        WHERE t.dimension = 'hub' AND t.tagger = ? AND j.removed_at IS NULL
        GROUP BY t.value
        ORDER BY postings DESC
        """,
        (tagging.TAGGER,),
    ).fetchall()


def unmeasured_hubs(connection: sqlite3.Connection) -> list[str]:
    """Focus hubs with no second source, so no coverage claim is possible."""
    return ["copenhagen", "amsterdam", "switzerland", "hong_kong", "singapore"]
