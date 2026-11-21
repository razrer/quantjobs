"""Conservative display-only duplicate folding; source rows are never deleted.

Exact fingerprints use firm, place, and a substantial body (or a short title).
Cross-source folding also requires employer corroboration and a shared hub;
two portals fold only as two different sources sharing a city.
Near-duplicate folding compares substantial bodies within firm/place/title.
Counts and available deadlines survive. Incident evidence: docs/history/engineering.md."""

from __future__ import annotations

import difflib
import hashlib
import re

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
    "iesjobs", "efinancial", "linkedin", "workable_jobs",
})


# How each hub city is written by the sources that write it out in full:
# LinkedIn's "Hong Kong, Hong Kong SAR", Workday's "New York, NY, United States",
# Jobtech's "Stockholm, Stockholms lan". A comma part after the city may be
# dropped only when it is one of that city's own region or country names, so
# "Solna, Stockholm County" and "London; Dubai" keep their own key.
_CITY_ALIASES = {
    "kobenhavn": "copenhagen", "geneve": "geneva", "zuerich": "zurich",
    "hong kong sar": "hong kong", "new york city": "new york", "nyc": "new york",
    "new york city metropolitan area": "new york",
    "greater chicago area": "chicago", "greater boston": "boston",
}
_US = {"united states", "united states of america", "usa", "us"}
_CITY_QUALIFIERS = {
    "hong kong": {"hong kong", "hong kong sar", "hksar", "hong kong s a r", "china"},
    "singapore": {"singapore"},
    "new york": {"ny", "new york"} | _US,
    "chicago": {"il", "illinois"} | _US,
    "boston": {"ma", "massachusetts"} | _US,
    "stockholm": {"stockholm", "stockholm county", "stockholms lan", "sweden", "sverige"},
    "copenhagen": {"capital region of denmark", "region hovedstaden", "hovedstaden",
                   "denmark", "danmark"},
    "amsterdam": {"north holland", "noord holland", "netherlands", "the netherlands",
                  "nederland"},
    "zurich": {"zh", "zurich", "switzerland", "schweiz"},
    "geneva": {"ge", "geneva", "geneve", "switzerland", "suisse"},
    "london": {"london", "greater london", "england", "united kingdom", "uk"},
}


def bundle_place(location: str) -> str:
    """Normalize documented place variants for reversible visual stacks only."""
    raw = location or ""
    place = fold(raw).strip()
    if place in {"stockholm", "stockholm stockholms lan", "stockholm sverige",
                 "stockholm sweden"}:
        return "stockholm"
    if place in {"geneva ge", "geneve ge"}:
        return "geneva"
    if place == "singapore" or re.fullmatch(r"singapore d\d\d .+", place):
        return "singapore"
    if not re.search(r"[;|/]", raw):
        parts = [fold(part).strip() for part in raw.split(",")]
        parts = [part for part in parts if part and not part.isdigit()]
        # Two city-states: a district before the name is still the one city,
        # "Central & Western District, Hong Kong SAR" or "Hong Kong, Mong Kok".
        if parts and (parts[-1] in _CITY_QUALIFIERS["hong kong"] - {"china"}
                      or parts[0] in {"hong kong", "hong kong sar"}):
            return "hong kong"
        if parts and parts[-1] == "singapore":
            return "singapore"
        if parts:
            city = _CITY_ALIASES.get(parts[0], parts[0])
            allowed = _CITY_QUALIFIERS.get(city)
            if allowed is not None and all(part in allowed for part in parts[1:]):
                return city
    return place


def mark_similar(cards: list[dict], firms: dict) -> None:
    """Mark visual bundles without removing cards or changing firm identities.

    Require the same complete title and place, then corroborate employer names.
    Every member must match every other member; aliases cannot form a chain
    joining two employers that do not match directly. Missing places stay split.
    """
    groups: dict[tuple[str, str], list[list[dict]]] = {}
    for card in cards:
        card.pop("similar", None)
        place = bundle_place(card.get("loc", ""))
        title = fold(card.get("title", "")).strip()
        if not place or not title or not card.get("firm"):
            continue
        clusters = groups.setdefault((title, place), [])
        names = [firms.get(card["firm"], {}).get("name")]
        for cluster in clusters:
            if all(card["firm"] == other["firm"] or same_company(
                names, [firms.get(other["firm"], {}).get("name")])
                for other in cluster):
                cluster.append(card)
                break
        else:
            clusters.append([card])
    for clusters in groups.values():
        for cluster in clusters:
            if len(cluster) > 1:
                key = min(card["id"] for card in cluster)
                for card in cluster:
                    card["similar"] = key

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

# The one exception to `_MIN_LONE_NAME`: the whole name, spelled the same on
# both sides, is an identity however short -- `UBS` and `UBS`, `SEB` and `SEB`.
# Not when the name is no name at all.
_NO_NAME = frozenset("""
    anonymous confidential company employer private recruiter undisclosed
    unknown
""".split())


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
            if a == b and not set(a) <= _GENERIC_NAME | _NO_NAME:
                return True
            run = 0
            for x, y in zip(a, b):
                if x != y:
                    break
                run += 1
            if run >= 2:
                return True
            if (run == 1 and len(a[0]) >= _MIN_LONE_NAME
                    and a[0] not in _GENERIC_NAME and a[0] not in _NO_NAME):
                return True
            if _joined(a, b):
                return True
    return False


# A brand written as one word on one side and two on the other: LinkedIn's
# `JPMorganChase` against the registry's `JPMorgan Chase & Co.`. The one word
# has to equal a whole leading run of the other side and be long enough to be
# a name -- the two-word rule with the space removed.
_MIN_JOINED_NAME = 8


def _joined(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    for one, many in ((a, b), (b, a)):
        if not one or len(many) < 2:
            continue
        head = one[0]
        if len(head) < _MIN_JOINED_NAME or head in _GENERIC_NAME:
            continue
        built = many[0]
        for word in many[1:]:
            built += word
            if built == head:
                return True
            if not head.startswith(built):
                break
    return False


# --- one firm under several keys --------------------------------------------
#
# A card's firm is its board's domain, or `~` and the employer name a portal
# printed. So SEB is `sebgroup.com` on its own board and `~seb` on Jobbsafari
# and LinkedIn, and grouping "by firm" shows it twice. `firm_groups` joins the
# keys for display. It is stricter than `same_company`, which only ever decides
# with a title and a hub already agreeing: here nothing else agrees, so a lone
# shared word is not enough and two firms' domains never join on a name alone.

_SECOND_LEVEL = frozenset({"com", "co", "org", "net", "gov", "edu", "ac"})


def _domain_label(domain: str) -> str:
    """`nordea` for `careers.nordea.com`, `dbs` for `dbs.com.sg`."""
    parts = domain.lower().split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else parts[0]


def _a_name(tokens: tuple[str, ...]) -> bool:
    return bool(tokens) and not set(tokens) <= _GENERIC_NAME | _NO_NAME


def _acronym(short: tuple[str, ...], long: tuple[str, ...]) -> bool:
    """`SEB` for `Skandinaviska Enskilda Banken`: three or more words, each a
    word rather than a particle, whose initials are the whole short name."""
    return (len(short) == 1 and 3 <= len(short[0]) <= 4 and len(long) == len(short[0])
            and all(len(word) >= 4 for word in long)
            and "".join(word[0] for word in long) == short[0])


def _names_one_firm(a: tuple[str, ...], b: tuple[str, ...], prefix: bool) -> bool:
    if not (_a_name(a) and _a_name(b)):
        return False
    if a == b or _joined(a, b) or _acronym(a, b) or _acronym(b, a):
        return True
    if prefix:
        short, long = (a, b) if len(a) <= len(b) else (b, a)
        return (long[:len(short)] == short and len(short[0]) >= _MIN_LONE_NAME
                and short[0] not in _GENERIC_NAME)
    return False


def firm_groups(firms: dict, employers: dict | None = None) -> dict[str, str]:
    """Map each firm key that is another key's firm onto one key.

    Three joins, in order of how much they can be trusted:
    - two domains with the same registrable label whose names agree
      (`careers.nordea.com` and `nordea.com`, `handelsbanken.se` and `.nl`);
    - a portal name onto the one domain cluster it names -- the same name, a
      leading run (`Nordea` of `Nordea Bank Abp, filial i Sverige`), one word
      (`JPMorganChase`) or initials (`SEB`). Naming two clusters joins neither;
      an exact name wins over a leading run;
    - portal names left over onto each other when the names are the same.
    The kept key is the cluster's domain with the most cards.
    """
    employers = employers or {}

    def tokens_of(key: str) -> set[tuple[str, ...]]:
        names = {firms[key].get("name")} | set(employers.get(key, ()))
        return {company_tokens(name) for name in names if name} - {()}

    parent = {key: key for key in firms}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    domains = [k for k in firms if not k.startswith("~")]
    portals = [k for k in firms if k.startswith("~")]
    tokens = {k: tokens_of(k) for k in firms}

    by_label: dict[str, list[str]] = {}
    for key in domains:
        by_label.setdefault(_domain_label(firms[key].get("domain") or key), []).append(key)
    for keys in by_label.values():
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if find(a) != find(b) and any(
                        _names_one_firm(x, y, prefix=True)
                        for x in tokens[a] for y in tokens[b]):
                    parent[find(a)] = find(b)

    # Candidates by first word, and by every initialism a domain name spells.
    index: dict[str, set[str]] = {}
    for key in domains:
        for t in tokens[key]:
            index.setdefault(t[0], set()).add(key)
            if len(t) >= 3:
                index.setdefault("".join(w[0] for w in t), set()).add(key)
    for key in portals:
        candidates = set()
        for t in tokens[key]:
            candidates |= index.get(t[0], set())
            if len(t) >= 3:
                candidates |= index.get("".join(w[0] for w in t), set())
            for word in (t[0][:n] for n in range(_MIN_JOINED_NAME, len(t[0]))):
                candidates |= index.get(word, set())
        exact, loose = set(), set()
        for other in candidates:
            for x in tokens[key]:
                for y in tokens[other]:
                    if _names_one_firm(x, y, prefix=False):
                        exact.add(find(other))
                    elif _names_one_firm(x, y, prefix=True):
                        loose.add(find(other))
        chosen = exact if exact else loose
        if len(chosen) == 1:
            parent[find(key)] = chosen.pop()

    left: dict[tuple[str, ...], str] = {}
    for key in portals:
        if find(key) != key:
            continue
        for t in tokens[key]:
            if not _a_name(t):
                continue
            if t in left and find(left[t]) != find(key):
                parent[find(key)] = find(left[t])
            left.setdefault(t, key)

    clusters: dict[str, list[str]] = {}
    for key in firms:
        clusters.setdefault(find(key), []).append(key)
    out: dict[str, str] = {}
    for members in clusters.values():
        if len(members) < 2:
            continue
        kept = max(members, key=lambda k: (not k.startswith("~"), firms[k].get("n", 0), k))
        for key in members:
            if key != kept:
                out[key] = kept
    return out


def _collapse_groups(cards, groups, key, rank, matches, later=None):
    """Shared clustering, winner selection, counts, deadlines, and cleanup.

    `later`, when given, is a second match applied after `matches` has formed
    its clusters. It may join two clusters only when no source has a card in
    both, so one copy cannot chain two of a source's own openings together."""
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

        if later is not None:
            sources: dict[int, set] = {}
            for i in range(len(group)):
                sources.setdefault(find(i), set()).add(group[i][key].get("src"))
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = find(i), find(j)
                    if a == b or sources[a] & sources[b]:
                        continue
                    if later(group[i][key], group[j][key]):
                        parent[a] = b
                        sources[b] |= sources.pop(a)

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
        later=_two_portals,
    )


# Hubs that are one city. `switzerland`, `us other` and `deprioritized` are
# whole territories, and one firm's title in Zurich and in Geneva is two
# openings, so there two portals' places have to agree as well.
CITY_HUBS = frozenset({
    "stockholm", "copenhagen", "amsterdam", "hong kong", "singapore",
    "new york", "chicago", "boston",
})


def _two_portals(a: dict, b: dict) -> bool:
    """Two different portals carrying one opening: eFinancialCareers and
    LinkedIn both list most Hong Kong recruiters' adverts. A source's own
    reposts are `collapse`'s question, so the two sources must differ."""
    if not (a["portal"] and b["portal"]):
        return False
    if not a.get("src") or not b.get("src") or a["src"] == b["src"]:
        return False
    shared = a["hubs"] & b["hubs"]
    if not shared:
        return False
    if not shared & CITY_HUBS and (not a.get("place") or a.get("place") != b.get("place")):
        return False
    return same_company(a["names"], b["names"])


class Scores:
    """`ratio()` results kept between builds, keyed on both texts in order.

    **A cache of the exact answer, not an approximation of it.** The full
    comparison is quadratic without autojunk and the bodies that reach it are
    the long, nearly identical ones: 65 of them cost 57 of a build's 584
    seconds, and they are the same pairs every week. The key hashes both texts
    in call order, because `SequenceMatcher` is not symmetric, so a changed
    body is a new key and is compared afresh. `used` is what the build keeps,
    so pairs that have left the board fall out of the file.
    """

    def __init__(self, known: dict[str, float] | None = None):
        self.known = known or {}
        self.used: dict[str, float] = {}

    def ratio(self, left: str, right: str, matcher) -> float:
        digest = hashlib.blake2b(digest_size=16)
        digest.update(left.encode())
        digest.update(b"\0")
        digest.update(right.encode())
        key = digest.hexdigest()
        score = self.known.get(key)
        if score is None:
            score = matcher.ratio()
        self.used[key] = score
        return score


def near(left: str, right: str, scores: Scores | None = None) -> float:
    """SequenceMatcher similarity, with cheap upper-bound rejection below NEAR.

    Disable autojunk: frequent characters are meaningful in near-identical prose."""
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    if matcher.real_quick_ratio() < NEAR:
        return 0.0
    if matcher.quick_ratio() < NEAR:
        return 0.0
    return scores.ratio(left, right, matcher) if scores else matcher.ratio()


def collapse_near_duplicates(cards: list[dict], key: str = "nd",
                             rank=None, scores: Scores | None = None) -> list[dict]:
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
                            lambda a, b: near(a["b"], b["b"], scores) >= NEAR)


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
