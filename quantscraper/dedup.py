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

## The second kind of duplicate, which `fingerprint` cannot see

The rule above folds one advertisement reposted on **one** source. The other
kind arrives on two: an employer posts an opening on its own careers page and a
national board carries it too, because that is what a national board is for.
Barclays' `Quantitative Analytics Associate Off Cycle Internship 2027
Singapore` is on its Workday board and on MyCareersFuture, and **all three
parts of the fingerprint differ**:

- firm -- the portal knows `BARCLAYS BANK PLC` and no domain, the Workday board
  knows a domain and no name, so `firm_key` makes them two firms;
- location -- `Singapore, Marina Bay Financial Tower 2` against `Singapore, D01
  Marina, Raffles Place, People's Park, Cecil`;
- description -- 7,875 characters on the portal, none at all on Workday.

So no widening of that key reaches it, and `collapse_across_sources` is a
separate pass with a separate rule: **same folded title, same hub, and a firm
test strong enough to carry the whole thing.**

**The firm test is what makes it safe, and it was measured rather than
assumed.** 39 (title, hub) groups on the board hold both a portal row and a
firm-board row. They split cleanly in two. Thirteen hold three or more firms
and every one is a generic title -- `trader`, `quantitative researcher`,
`software engineer`, `senior ai engineer` -- different openings at different
employers, and folding them would delete real jobs, which is the failure this
project calls the expensive one. The rest hold two, and there the names decide:
`Squarepoint Services Singapore` ~ `Squarepoint Ops` is one firm,
`Blockchain Capital` ~ `Chevron Singapore` is not. Every false pair in the
corpus -- `Cumberland SG` ~ `DRW`, `DRW` ~ `Fragment Works`, `Amendo` ~ `AP4`,
`Danica Pension` ~ `Danske Bank` -- shares no leading word at all.

**Restricted to cross-source pairs on purpose.** Within one source a repeated
title is either a repost, which the description rule already folds, or two
genuine seats -- Jane Street really does advertise two `Software Engineer`
openings in one office. The justification for this pass is that a portal
republishes somebody else's advertisement, so it applies only where one side
is a portal and the other is not.
"""

from __future__ import annotations

import hashlib

from .tagging import fold

# Below this a description is boilerplate rather than a document, and two
# postings sharing it are not thereby the same posting. Set from the corpus:
# the short bodies on this board are apply-here stubs.
MIN_BODY = 400


# The sources that publish other people's advertisements rather than their
# own. A national board is a republisher, which is the whole reason the same
# opening arrives twice under two identities -- the portal holds the employer's
# *name* and no domain, the firm's own board the reverse.
PORTALS = frozenset({"mycareersfuture", "jobbsafari", "jobroom", "jobindex", "jobtech"})

# The tail of a company name that says what kind of company it is rather than
# which one. A portal prints the legal name and a firm's own board prints the
# brand, so these have to come off before the two can be compared at all.
_LEGAL = frozenset("""
    ab ag aps as asa bv co company corp corporation gmbh group holding holdings
    inc incorporated kk limited llc llp lp ltd nv oy oyj plc pte pty publ pvt
    sa sarl spa srl
""".split())

# A single shared word is an identity only when the word is somebody's name.
# This is `discover._reads_as_another_industry`'s lesson in a second place:
# `bamboohr/blackrock` is BlackRock **Asphalt** of Tampa, and no text rule
# separates a one-word match from the firm it is not. Narrowed here to the
# words that make two unrelated finance firms look like one.
_GENERIC_NAME = frozenset("""
    advisors advisory alpha america american asia asset assets bank banking
    capital city commercial credit energy equity europe european finance
    financial first fund funds general global group insurance international
    investment investments life management markets national nordic north
    pacific partners prime research resources securities services solutions
    standard systems technologies technology trading union united universal
    ventures wealth
""".split())

# One shared word has to be at least this long before it can identify a firm.
# `tp`, `sg` and `ap4` are not names; `barclays`, `swedbank` and `airwallex`
# are. It costs the occasional duplicate on a short name, which is the
# direction to fail in -- a false split is a second of reading and a false
# merge deletes an employer.
_MIN_LONE_NAME = 5


def company_tokens(name: str | None) -> tuple[str, ...]:
    """A company name cut down to the words that say *which* company it is."""
    words = [w for w in fold(name or "").split() if len(w) > 1]
    return tuple(w for w in words if w not in _LEGAL)


def same_company(left, right) -> bool:
    """Whether two sets of names plausibly name one employer.

    Each side is every name held for it -- the portal prints one legal name, a
    firm's own board has its display name and whatever the registries called
    the domain -- and a match on any pair is a match.

    **The test is a shared *leading* run**, because a company name reads
    outside in: the distinguishing word comes first and the descriptive ones
    follow. That is exactly what separates the true pairs from the false ones
    in this corpus -- `Squarepoint Services Singapore` ~ `Squarepoint Ops` and
    `State Street Fund Services (Singapore)` ~ `State Street Liquidity` share a
    leading run, while `Blockchain Capital` ~ `Chevron Singapore` shares
    nothing and `Danica Pension` ~ `Danske Bank` shares nothing either.

    Two shared words are always enough. One is enough only when it is a name
    rather than a word half of finance carries.
    """
    lefts = {company_tokens(name) for name in left if name}
    rights = {company_tokens(name) for name in right if name}
    for a in lefts:
        if not a:
            continue
        for b in rights:
            if not b:
                continue
            run = 0
            for x, y in zip(a, b):
                if x != y:
                    break
                run += 1
            if run >= 2:
                return True
            if run == 1 and len(a[0]) >= _MIN_LONE_NAME and a[0] not in _GENERIC_NAME:
                return True
    return False


def collapse_across_sources(cards: list[dict], key: str = "xs", rank=None) -> list[dict]:
    """Fold one opening that a firm's own board and a national board both carry.

    `card[key]` is `{"t": folded title, "hubs": set, "names": tuple, "portal":
    bool}`; a card without it is never folded. Two cards join when exactly one
    of them is a portal row, they share a hub, and `same_company` holds.

    **The survivor is the card the board rates highest, not the newest.** The
    two copies are read by the tagger separately and do not agree: Barclays'
    internship is `apply_now` on Workday, which publishes no description for
    it, and `strong` on MyCareersFuture, which publishes 7,875 characters. A
    rule that picked a side by source would bury one of those, and burying a
    card this board rates highly is the one outcome worth avoiding here. Ties
    go to the firm's own board, because an aggregator is a discovery net and
    never the primary content source.

    **The closing date crosses over.** MyCareersFuture publishes one on every
    row and a firm's ATS almost never does, so keeping the ATS card would
    otherwise throw away a real deadline for the same opening -- and this board
    orders on deadlines. It is carried, not invented: it is the date the portal
    published for the job that is being folded.
    """
    groups: dict[str, list[dict]] = {}
    for card in cards:
        meta = card.get(key)
        if meta:
            groups.setdefault(meta["t"], []).append(card)

    dropped: set[int] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        # Union-find over a handful of cards sharing one title. The groups are
        # tiny -- the largest in the corpus is seven -- so the quadratic pass
        # is cheaper than any index over it would be.
        parent = list(range(len(group)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i][key], group[j][key]
                if a["portal"] == b["portal"]:
                    continue
                if not (a["hubs"] & b["hubs"]):
                    continue
                if not same_company(a["names"], b["names"]):
                    continue
                parent[find(i)] = find(j)

        clusters: dict[int, list[int]] = {}
        for i in range(len(group)):
            clusters.setdefault(find(i), []).append(i)

        for members in clusters.values():
            if len(members) < 2:
                continue
            cluster = [group[i] for i in members]
            winner = max(cluster, key=rank) if rank else cluster[0]
            winner["dup"] = sum(c.get("dup", 1) for c in cluster)
            if "due" not in winner:
                for other in cluster:
                    if "due" in other:
                        winner["due"] = other["due"]
                        break
            for other in cluster:
                if other is not winner:
                    dropped.add(id(other))

    out = [c for c in cards if id(c) not in dropped]
    for card in cards:
        card.pop(key, None)
    for card in out:
        if card.get("dup", 1) <= 1:
            card.pop("dup", None)
    return out


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
