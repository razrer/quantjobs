"""Conservative display-only duplicate folding; source rows are never deleted.

Exact fingerprints use firm, place, and a substantial body (or a short title).
Cross-source folding also requires employer corroboration and a shared hub.
Near-duplicate folding compares substantial bodies within firm/place/title.
Counts and available deadlines survive. Incident evidence: docs/history/engineering.md."""

from __future__ import annotations

import difflib
import hashlib

from .tagging import fold

# Below this a description is boilerplate rather than a document, and two
# postings sharing it are not thereby the same posting. Set from the corpus:
# the short bodies on this board are apply-here stubs.
MIN_BODY = 400

# Corpus-reviewed boundary: rejected pairs <=0.8970; accepted >=0.9377.
# Keep autojunk disabled and preserve this threshold until new cases justify it.
# Known limitation: missing location fields can hide city differences in prose.
NEAR = 0.93


# The sources that publish other people's advertisements rather than their
# own. A national board is a republisher, which is the whole reason the same
# opening arrives twice under two identities -- the portal holds the employer's
# *name* and no domain, the firm's own board the reverse.
PORTALS = frozenset({
    "mycareersfuture", "jobbsafari", "jobroom", "jobindex", "jobtech",
    "iesjobs",
})

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
    """Match names by a shared leading token run.

    Two shared words suffice; one must be a distinctive word of at least five
    characters. Generic finance words and legal suffixes cannot identify a firm."""
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


def _collapse_groups(cards, groups, key, rank, matches):
    """Shared clustering, winner selection, counts, deadlines, and cleanup."""
    dropped: set[int] = set()
    for group in groups.values():
        if len(group) < 2:
            continue
        parent = list(range(len(group)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if find(i) == find(j):
                    continue
                if matches(group[i][key], group[j][key]):
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


def collapse_across_sources(cards: list[dict], key: str = "xs", rank=None) -> list[dict]:
    """Fold corroborated portal/direct copies with the same title and a shared hub.

    card[key] holds t, hubs, names, and portal. Pick the highest-ranked card
    (or the first); retain counts and a missing deadline. Remove working metadata."""
    groups: dict[str, list[dict]] = {}
    for card in cards:
        meta = card.get(key)
        if meta:
            groups.setdefault(meta["t"], []).append(card)

    return _collapse_groups(
        cards, groups, key, rank,
        lambda a, b: a["portal"] != b["portal"]
        and bool(a["hubs"] & b["hubs"])
        and same_company(a["names"], b["names"]),
    )


def near(left: str, right: str) -> float:
    """SequenceMatcher similarity, with cheap upper-bound rejection below NEAR.

    Disable autojunk: frequent characters are meaningful in near-identical prose."""
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    if matcher.real_quick_ratio() < NEAR:
        return 0.0
    if matcher.quick_ratio() < NEAR:
        return 0.0
    return matcher.ratio()


def collapse_near_duplicates(cards: list[dict], key: str = "nd",
                             rank=None) -> list[dict]:
    """Fold similar substantial bodies within the same firm, location, and title.

    card[key] holds g=(firm, location, folded title) and b=folded body.
    Bodies below MIN_BODY are never compared. Matching and clustering are
    separate from fingerprint(), whose stable key makes human rejections stick."""
    groups: dict[tuple, list[dict]] = {}
    for card in cards:
        meta = card.get(key)
        if meta and len(meta["b"]) >= MIN_BODY:
            groups.setdefault(meta["g"], []).append(card)

    return _collapse_groups(cards, groups, key, rank,
                            lambda a, b: near(a["b"], b["b"]) >= NEAR)


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
    """Keep one card per fingerprint, using newest(card) to select a survivor.

    Default: first card wins. Retain the count; missing fingerprints never fold."""
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
