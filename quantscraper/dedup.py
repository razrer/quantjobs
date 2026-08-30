"""One key that identical postings share and separate openings do not.

Two jobs on this board, and they turn out to be the same job.

**The board repeats itself, and most of it is one recruiter refreshing an
advertisement.** `Quant Researcher #77900` from Anradus appears four times in
Singapore -- 11, 17, 22 and 27 August, four different MyCareersFuture ids, and
a **byte-identical 2,737-character description** each time. Apex Group posts
`Senior Associate Level 3` eleven times. Measured over the whole board, 299
cards are repeats of another card, 103 of them in Singapore, which is the hub
the reader asked to be able to scan in five minutes.

**And the reason a rejection does not stick is the same fact.** A posting
rejected on the board is rejected by `(ats, token, job_id)`, so the reposted
copy arrives with a new id and is a stranger again. Keying the rejection on
this fingerprint instead is what makes "no, and stop showing me this" hold.

## Why the location is in the key

The obvious fingerprint is the description, and on its own it is wrong.
**Jane Street writes one description per role and posts it in every office**,
so hashing the body alone merges its Hong Kong `Software Engineer` with its
London one and the London opening disappears -- a real job hidden by a
de-duplicator, which is worse than seeing the same advertisement twice. With
the location in the key that pair stays apart and only the two Hong Kong
`Quantitative Researcher` postings with the same text collapse, which is a
duplicate from the reader's seat whatever the requisition numbers say.

## Why the description, when there is one

`(title, firm, location)` alone is too blunt in the other direction: Workday
writes `2 Locations` as a location for multi-site requisitions, so several
genuinely different Apex openings share one string. The description separates
them when it exists and the title is the fallback when it does not -- 3,651 of
the board's 6,106 cards carry one long enough to hash.

**A short description is not evidence of sameness.** `MIN_BODY` exists because
a two-line "we are hiring, apply within" is identical across postings that have
nothing else in common, and hashing it would merge them.
"""

from __future__ import annotations

import hashlib

from .tagging import fold

# Below this a description is boilerplate rather than a document, and two
# postings sharing it are not thereby the same posting. Set from the corpus:
# the short bodies on this board are apply-here stubs.
MIN_BODY = 400


def fingerprint(
    firm: str | None,
    location: str | None,
    title: str | None,
    description: str | None = None,
) -> str:
    """A stable key for "this is the same advertisement".

    Same firm, same stated location, and either the same description or -- when
    there is no usable description -- the same title. Folded on both sides, so
    casing, punctuation and accents do not split a cluster.
    """
    body = fold(description or "")
    if len(body) >= MIN_BODY:
        core = "d:" + hashlib.sha1(body.encode("utf-8")).hexdigest()
    else:
        core = "t:" + fold(title or "").strip()
    parts = (
        (firm or "").strip().lower(),
        (location or "").strip().lower(),
        core,
    )
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def collapse(cards: list[dict], key: str = "fp", newest=None) -> list[dict]:
    """Keep one card per fingerprint and record how many it stands for.

    **The survivor is the newest**, because the reader is going to click it and
    a recruiter's oldest repost is the one most likely to have been filled. The
    others are dropped from the page and the count goes on the card that
    remains, so the board still says the repetition happened -- nothing here
    removes silently.

    `newest` sorts a card; the default keeps the order the caller supplied,
    which for `build_data` is the database's own.
    """
    best: dict[str, dict] = {}
    order: list[str] = []
    for card in cards:
        fp = card.get(key)
        if not fp:                      # no fingerprint: never collapsed
            order.append(id(card))
            best[id(card)] = card
            continue
        if fp not in best:
            best[fp] = card
            order.append(fp)
            card["dup"] = 1
        else:
            kept = best[fp]
            kept["dup"] = kept.get("dup", 1) + 1
            if newest is not None and newest(card) > newest(kept):
                # Carry the count onto the replacement, then swap.
                card["dup"] = kept["dup"]
                best[fp] = card
    out = [best[k] for k in order]
    for card in out:
        if card.get("dup", 1) <= 1:
            card.pop("dup", None)
        card.pop(key, None)
    return out
