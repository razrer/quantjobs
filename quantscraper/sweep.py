"""What every national-board walk has to check about itself.

The four portal readers -- Singapore, Hong Kong, Denmark and Sweden -- each
walk a board that publishes its own total, and each ends by asking the same two
questions of what came back. They were four copies of the same arithmetic and
four copies of the same paragraph explaining it, which is one bug fixed in one
place and three left standing.

**The questions are not interchangeable and both are here.** A walk that comes
back implausibly *small* has found a redesign, which is principle 2 -- a
scraper returning nothing with HTTP 200 is more dangerous than one that
crashes. A walk that comes back *nearly* complete has usually hit a result
window, a short page or a page bound, and the tell is a round number nobody
would otherwise look at. Neither is visible without the board's own count to
compare against, which is why every reader here collects one.

What stays per source is the *floor*: `MIN_EXPECTED` is a claim about how big
one particular board is, and Singapore's 20,000 says nothing about Denmark.
"""

from __future__ import annotations

# How far short of the advertised total a complete walk may land. The index
# moves while the walk runs -- ads are published and withdrawn under it, and on
# a partitioned board a posting re-filed mid-sweep lands in two slices or none
# -- so a small gap is the board breathing. Measured on the longest walk here:
# 6 duplicates in the first 10,094 MyCareersFuture rows. Anything wider is
# truncation rather than turbulence.
SHORTFALL_TOLERANCE = 0.02


def problem(
    seen: int, advertised: int, minimum: int,
    *, noun: str = "board", or_else: str = "",
) -> str | None:
    """The two checks every completed walk owes its caller, or None if sound.

    Callers run their own source-specific checks first -- a refusal, a page
    bound, a slice that would not fit its window -- because those name a cause
    and these two only name a symptom. `or_else` names the *other* cause a
    shortfall can have on this particular source, which is worth saying in the
    message rather than in a comment: on a partitioned board it is at least as
    likely to be a facet the walk does not know about as a truncated page.
    """
    if seen < minimum:
        return (
            f"collected {seen:,d} postings, expected at least "
            f"{minimum:,d} -- treating as a broken source"
        )
    short = advertised - seen
    if advertised and short > advertised * SHORTFALL_TOLERANCE:
        return (
            f"collected {seen:,d} of the {advertised:,d} the {noun} advertised"
            f" -- {short:,d} short, which is truncation"
            f"{or_else or ' rather than a moving index'}"
        )
    return None
