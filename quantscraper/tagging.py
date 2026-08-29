"""Layer 5 -- turning a corpus of ~295,000 postings into something rankable.

A deterministic lexicon: no model, no spend, and re-runnable over the whole
corpus, which is what makes a lexicon bug cheap to fix rather than expensive to
discover. `lexicon.py` holds the vocabulary shared with the other layers; this
file holds the dimensions and the rules that combine them.

**Tags rank, they never delete.** A posting the lexicon rejects keeps its row
and gets `relevance: rejected` with the span that said so. Every dimension has
an explicit `unknown`, so a posting nothing decided stays distinguishable from
one nothing looked at. The board is the only thing that removes, and it does so
by not rendering -- see `GATES`.

**Many postings are a title and a location, and that is workable.** Workday,
BambooHR, Personio, Breezy and SmartRecruiters publish list endpoints carrying
title, location and date only. Tags read from a body are graded **strong** and
the rest **weak**, so the difference is visible at read time rather than
averaged away.

**Token boundaries, never substrings.** This corpus contains `Corporate
Administrator` -- admini*strat*or -- and `Alpha Account Services Data Analyst`,
because State Street's custody platform is called Alpha. A naive `in` scores
both as quant roles. Text is folded to spaced tokens and every needle matched
with its padding, the same trick `domains.py` uses on firm names.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass

from . import db, lexicon

# Bump on every lexicon change: the diff between two versions over the same
# corpus is a free regression test, and it is the only way to tell "the
# classifier improved" from "the market moved".
TAGGER = 52

SCHEMA = """
CREATE TABLE IF NOT EXISTS job_tags (
    ats        TEXT NOT NULL,
    token      TEXT NOT NULL,
    job_id     TEXT NOT NULL,
    dimension  TEXT NOT NULL,
    value      TEXT NOT NULL,
    confidence TEXT NOT NULL,   -- strong (read from a body) | weak (title only)
    evidence   TEXT,
    tagger     INTEGER NOT NULL,
    tagged_at  TEXT NOT NULL,
    PRIMARY KEY (ats, token, job_id, dimension, value)
);

CREATE INDEX IF NOT EXISTS job_tags_by_value ON job_tags (dimension, value);
-- `postings()` asks "is this posting tagged at the current version" as a
-- correlated NOT EXISTS on (ats, token, job_id, tagger). The primary key stops
-- after the first three, so without this SQLite walked every row for the
-- posting -- one per dimension per version still in the table -- to test
-- `tagger`. Measured: 18 seconds to return 50,529 rows, against a seek.
CREATE INDEX IF NOT EXISTS job_tags_by_tagger ON job_tags (ats, token, job_id, tagger);
"""

_TAGS = re.compile(r"<[^>]+>")

# Folded before the text is, so the punctuation that carries the meaning
# survives it. "c++" would otherwise become "c", which matches everything.
_SYMBOLS = (
    ("c++", " cplusplus "),
    ("c#", " csharp "),
    (".net", " dotnet "),
    ("f#", " fsharp "),
    ("q/kdb", " kdb "),
    ("kdb+", " kdb "),
    # `Ph.D.` folds to the two tokens "ph d", so every needle spelled `phd`
    # silently missed the postings that punctuate it -- which is most of them.
    # Folded here so both spellings reach the lexicon as one word.
    ("ph.d", " phd "),
    ("ph. d", " phd "),
    ("d.phil", " phd "),
)


# **Transliterated, not deleted, and this was silently breaking every Swedish
# rule in the file.** The strip below keeps `a-z0-9+#` only, so `ö` became a
# *space*: "Sjuksköterska" folded to "sjuksk terska" and "Göteborg" to
# "g teborg". Every needle here is written in ASCII -- `sjukskoterska`,
# `lastbilsforare`, `goteborg` -- so none of them could ever match the text
# they were written for, and a rule that never fires looks exactly like a rule
# with nothing to catch.
#
# `_terms` folds needles the same way and its docstring calls that "folding
# both sides", which is the right discipline and does not work when the fold is
# lossy in different directions: the needle `francais` folds to `francais` and
# the text `français` folded to `fran ais`. Mapping to the ASCII letter is what
# actually makes the two sides converge, and it means a needle may now be
# written either way.
#
# `posting_language` still must not use `fold` at all -- it counts function
# words and `är` is not `ar` -- and it does not. See its own note.
_ACCENTS = str.maketrans({
    "å": "a", "ä": "a", "á": "a", "à": "a", "â": "a", "ã": "a",
    "ö": "o", "ø": "o", "ó": "o", "ò": "o", "ô": "o", "õ": "o",
    "é": "e", "è": "e", "ê": "e", "ë": "e",
    "í": "i", "ì": "i", "î": "i", "ï": "i",
    "ú": "u", "ù": "u", "û": "u", "ü": "u",
    "ý": "y", "ÿ": "y", "ñ": "n", "ç": "c",
    "æ": "ae", "œ": "oe", "ß": "ss", "đ": "d", "ł": "l",
})


# **Letters that are not Latin but are drawn like it.** Jane Street publishes
# `ꓟachine ꓡearning ꓣesearcher` -- M, L and R written as Lisu MA, LA and ZHA --
# and one board spells `Linguist - Lаtvian` with a Cyrillic *а* inside an
# otherwise Latin word. The strip in `fold` keeps `a-z0-9+#`, so each of these
# becomes a *space*: the title arrives as "achine earning esearcher" and every
# needle in this file walks straight past a machine-learning research seat at
# the one firm this project most wants to see. Exactly the failure `_ACCENTS`
# documents one comment up, arriving through a different door.
#
# **Measured before it was written, because the obvious map is too wide.** All
# 69,961 titles were scanned for Latin-lookalike codepoints: 75 distinct
# characters, and the overwhelming majority are genuine Chinese, Japanese and
# Greek titles that mean what they say. Those are left alone -- a title that is
# really CJK is not helped by mangling it into Latin. Only the letters that
# impersonate an ASCII one are mapped, which is a short list.
_CONFUSABLES = str.maketrans({
    # Lisu, as used above.
    "ꓐ": "b", "ꓑ": "p", "ꓒ": "p", "ꓓ": "d", "ꓔ": "t", "ꓕ": "t", "ꓖ": "g",
    "ꓗ": "k", "ꓘ": "k", "ꓙ": "j", "ꓚ": "c", "ꓛ": "c", "ꓜ": "z", "ꓝ": "f",
    "ꓞ": "f", "ꓟ": "m", "ꓠ": "n", "ꓡ": "l", "ꓢ": "s", "ꓣ": "r", "ꓤ": "v",
    "ꓥ": "n", "ꓦ": "h", "ꓧ": "h", "ꓨ": "g", "ꓩ": "j", "ꓪ": "w", "ꓫ": "x",
    "ꓬ": "y", "ꓮ": "a", "ꓯ": "a", "ꓰ": "e", "ꓱ": "e", "ꓲ": "i", "ꓳ": "o",
    "ꓴ": "u", "ꓵ": "u", "ꓶ": "u", "ꓸ": ".", "ꓹ": ",",
    # Cyrillic letters that are drawn exactly like a Latin one.
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o",
    "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "і": "i", "ј": "j",
    "ѕ": "s", "ԁ": "d", "һ": "h", "ԛ": "q", "ԝ": "w",
    # Greek, same test. Only the unambiguous ones -- `π` and `λ` are left as
    # themselves, because a posting using them means them.
    "α": "a", "ο": "o", "ρ": "p", "ε": "e", "ν": "v", "τ": "t", "υ": "u",
    "ι": "i", "κ": "k", "χ": "x", "ϲ": "c",
    # Fullwidth ASCII. `Ｄａｔａ Ｓｃｉｅｎｔｉｓｔ` is a Latin title typed on a
    # CJK keyboard, and the words are ordinary English underneath.
    **{chr(cp): chr(cp - 0xFEE0) for cp in range(0xFF01, 0xFF5F)},
})

# Applied as one pass. The two tables share no key and neither maps onto the
# other's input, so merging them is exactly the two `translate` calls it
# replaces -- and folding is on the hot path of every re-tag.
_ASCII = {**_CONFUSABLES, **_ACCENTS}


_STRIP = re.compile(r"[^a-z0-9+#]+")


def fold(*parts: str | None) -> str:
    """Everything folded to lowercase ASCII tokens, padded so needles can be too."""
    text = " ".join(part for part in parts if part)
    text = _TAGS.sub(" ", text).casefold().translate(_ASCII)
    for symbol, replacement in _SYMBOLS:
        text = text.replace(symbol, replacement)
    return " " + " ".join(_STRIP.sub(" ", text).split()) + " "


def _joined(*folded: str) -> str:
    """Two already-folded strings as one. Exactly `fold` of the same parts:
    the join puts a space between them, and no symbol in `_SYMBOLS` spans one."""
    parts = [part.strip() for part in folded]
    return " " + " ".join(part for part in parts if part) + " "


def _terms(*phrases: str) -> tuple[str, ...]:
    """Fold needles the same way the text is folded, once, at import.

    A needle carrying punctuation or a diacritic cannot otherwise match the
    text it was written for. Same discipline as `domains.py` comparing a
    normalized firm name against page text.
    """
    return tuple(fold(phrase).strip() for phrase in phrases)


# Matching is `lexicon`'s, so there is one implementation of it rather than
# two. The *folds* stay separate -- `fold` transliterates to ASCII while
# `lexicon.normalize` keeps accented Latin -- but a needle list is a needle
# list, and `lexicon.first` indexes one by first word to skip what cannot match.
_hit = lexicon.first
_hits = lexicon.every


# --------------------------------------------------------------------------
# The lexicon. Multilingual where the focus hubs need it: a Stockholm posting
# says "kvantitativ analytiker" and a Dutch one says "handelaar", and a word
# list that only speaks English quietly reports those hubs as empty.
# --------------------------------------------------------------------------

# Two lists, because *where* a word appears decides whether it means
# anything. These are unambiguous wherever they occur -- no bank writes
# "statistical arbitrage" in its boilerplate.
_QUANT_CORE = (
    "quant", "quants", "quantitative", "kvantitativ", "kvantitative",
    "systematic trading", "algorithmic trading", "algo trading",
    # The noun forms too: `Algorithmic Trader` is not "algorithmic trading".
    "algorithmic trader", "algo trader", "systematic trader",
    "statistical arbitrage", "stat arb", "alpha research", "signal research",
    "alpha generation", "execution research", "model validation",
    "risk quant", "kwantitatief", "quantitatif",
    # The valuation-adjustment family. Dry-run over every live title and body:
    # 27 matches, every one a bank markets-quant seat, no false positive --
    # which is what earns them a place here rather than in the title-only list.
    "xva", "counterparty credit risk", "credit valuation adjustment",
    "wrong way risk", "potential future exposure",
    # Swedish and Danish. `kvantitativ` was already here and carries most of
    # the weight; these are the phrases that name the work without it.
    "algoritmisk handel", "systematisk handel", "statistisk arbitrage",
    "kvantitativ analys", "kvantitativ analyse", "kvantanalytiker",
    "modellvalidering", "modelvalidering",
)

# The same list without the bare adjectives, for the one branch that reads a
# body *alone*. "Strong quantitative skills" is in half the job specs ever
# written, so `quantitative` decides nothing about a document it appears in
# once -- it made `Cloud Engineer` a quant role. In a *title* the same word is
# the whole job, which is why this is a second list and not an edit above.
_QUANT_CORE_BODY = tuple(
    needle for needle in _QUANT_CORE if needle not in lexicon.GENERIC_IN_BODY
)

# These name the role in a title and are boilerplate in a body: every finance
# firm's about-us mentions market and credit risk, which made an insurance
# accounting job a core quant role.
#
# `research analyst` is deliberately absent -- it is sell-side equity research
# at one firm and quant work at the next, so it is a weak positive that a body
# can rescue rather than a title that decides alone.
_QUANT_CORE_TITLE = (
    "trader", "trading strategist", "strat", "strats",
    "market risk", "credit risk", "derivatives pricing",
    "portfolio construction", "handelaar", "handlare", "systematisk",
    # Title-only, and the body is why: in a title these are the
    # valuation-adjustment desk, in a body they are somebody else's
    # initialism -- `ccr` is mostly "Channel and Customer Research" and `dva`
    # matched a *Köksmästare*. An abbreviation is evidence where the whole
    # string is a job title and noise where it is a paragraph. `xva` is in
    # `_QUANT_CORE` instead: it means nothing else anywhere.
    "cva", "ccr",
    # The Nordic domain words, same grade as `market risk` and `credit risk`
    # above and for the same reason: they name the desk, and a qualifier
    # decides whether the seat on it is quantitative.
    "marknadsrisk", "markedsrisiko", "kreditrisk", "kreditrisiko",
    "modellrisk", "modelrisiko", "derivatprissattning", "portfoljkonstruktion",
    # A latency budget is a markets fact here: all 23 live titles carrying it
    # are markets firms. Elsewhere the phrase belongs to networking and gaming,
    # and this corpus has none of that.
    "low latency",
)

# Roles that live *next to* a trading desk without being one. Bare "trading"
# used to be a core needle and pulled all of these in -- the desk's name is
# not the role's name.
_DESK_ADJACENT = (
    "trading operations", "trading services", "trading support",
    "middle office", "back office", "settlements", "reconciliation",
    "trade support", "operations analyst", "operations", "recruiter",
    "recruitment", "sales trader", "client service", "compliance",
    "debt collections", "collections", "underwriting",
)

# A seat on a desk, as opposed to the desk's name. `trading_style` splits
# these into quant and pure, which is the difference between the job the user
# wants and the job most postings with "Trader" in the title actually are.
_TRADER_SEAT = _terms(
    "trader", "traders", "market maker", "market making",
    "handlare", "handelaar", "haendler",
)

# Titles announcing that the job is running the work rather than doing it. The
# reader has under a year of experience and no interest in management, so these
# reject outright rather than merely ranking down -- but only where no
# unambiguous quant word appears, which is what keeps `Head of Quantitative
# Research` readable.
_MANAGEMENT = _terms(
    "head of", "global head", "regional head", "group head", "department head",
    "managing director", "executive director", "director of", "director",
    "chief", "partner", "svp", "evp", "vp of", "vice president of",
    "product manager", "product owner", "programme manager", "program manager",
    "engineering manager", "delivery manager", "people manager", "leader",
    "ceo", "cfo", "coo", "cto", "cio",
    # Bare `manager` is in deliberately: it held the line between `Product
    # Manager` and `Manager, Data Science`, and there is no version of the
    # second that is a first job.
    "manager", "senior manager", "associate manager", "project manager",
    "project leader", "project lead", "team leader", "team lead",
    "scrum master", "agile coach", "chapter lead", "tribe lead",
    "vice president", "vp", "avp", "svp", "president",
    "supervisor", "foreman", "principal consultant",
    # **The English plural, which a token-matched needle cannot see.** `Delivery
    # Managers - Tieto Banktech` escaped `delivery manager` and reached the
    # board -- the Swedish inflection lesson in the language the list is
    # written in. Dry-run over 382,034 live titles: 146 hits, one of them rated
    # positively, and it reads correctly by hand -- Oliver Wyman's
    # `Associates/Engagement Managers/Principals - Banking`, a consulting grade
    # ladder advertised as one posting.
    #
    # **Four more plurals were measured and dropped, three of them on the
    # reason rather than the count.** `partners` is 84 titles whose two
    # positives are `Associate, Private Equity, CLSA Capital Partners` -- the
    # *firm's name*, where the applicant is an associate; `principals` is
    # sixteen preschool principals, an occupation and not a rank; `presidents`
    # and `heads of` reach only an *assistant to* one, so the word describes
    # somebody the applicant works for. A gate whose reason is wrong is wrong
    # even where its verdict is right.
    "managers", "directors", "leaders", "supervisors",
    # Nordic. `projektledare` and `gruppchef` are the same job as the two
    # above, and the compound rule below catches the rest of the family.
    "projektledare", "teamledare", "gruppledare", "verksamhetsledare",
    "gruppchef", "enhetschef", "avdelningschef", "ekonomichef", "platschef",
    "regionchef", "kontorschef", "verkstallande direktor",
    # Danish, where the manager word is `leder` and the officer word is
    # `direktor`. Dry-run: no hit touches a positively-rated posting.
    "direktor", "leder", "vd", "koncernchef", "forman",
)

# Swedish and Danish build a manager's title by compounding and a word list
# cannot see inside one: `ekonomichef` is above but `inköpschef` and
# `hållbarhetschef` are not, and there is no end to that list. The rank is the
# last element, so it is matched as a token suffix -- the trick
# `lexicon.SWEDISH_HEADS` uses one module over. Safe because the heads are long
# and no English title ends in one meaning something else. Dry-run: none of the
# compounds caught is rated positively.
_MANAGER_HEADS = ("chef", "ledare", "leder", "direktor")

# The same trick for occupations rather than ranks: `Elsäljare` is one token,
# so the needle `saljare` cannot see it.
#
# Two obvious heads were dropped after the dry-run. `-arbetare` catches
# *medarbetare*, Swedish for "employee"; `-assistent` catches
# *Forskningsassistent*, a research assistant this project might want.
_TRADE_HEADS = (
    "saljare", "skoterska", "larare", "mekaniker", "elektriker",
    "handlaggare", "sekreterare", "tekniker", "montor", "stadare",
    "vaktmastare", "bagare", "chauffor", "forare",
    # The plurals, and the Danish heads. Swedish pluralises the head itself,
    # so `underskoterskor` ends in nothing the singular list can see.
    "skoterskor", "montorer", "chaufforer", "operatorer", "vaktare",
    "laerer", "laerere", "sygeplejerske", "sygeplejersker", "smed", "terapeut",
    # A head is worth more than the words it replaces, because it also catches
    # the next compound nobody has seen -- which on a board carrying every job
    # in Sweden is the whole problem. Dry-run: none touches a positively-rated
    # posting. **`konsulent` was dropped despite a clean run** -- it is the
    # ordinary Danish word for a consultant, so it reads as a trade only in
    # Swedish and gating it would delete Danish technology work.
    "kock", "barare", "putsare", "skottare", "mastare", "psykolog",
    "maskinist", "utdelare", "byggare", "tranare",
)

# Five candidate heads dropped after the dry-run, each the `-arbetare` mistake
# in a new language: `-arbejder` is *medarbejder* ("employee"), `-medhjaelper`
# and `-hjaelper` are *studentermedhjælper* and half of those are IT and data
# work, `-vagt` is *aftenvagt* -- a shift, not a security guard -- and
# `-assistenter` is *Forskningsassistenter*. The occupations they were meant to
# reach are whole words in `_OFF_INDUSTRY` instead.
_NOT_A_TRADE_HEAD = (
    "arbejder", "medhjaelper", "hjaelper", "vagt", "assistenter",
)

# Swedish marks the definite by suffixing the head too, so `Taxiföraren`
# escaped the needle `taxiforare`. Inflected here rather than spelled out, so
# the next definite form nobody has seen is caught as well: `-n` singular,
# `-na` and `-rna` plural. Worth seven postings, none rated positively -- the
# argument is that it is a rule rather than a list.
_TRADE_HEADS_INFLECTED = _TRADE_HEADS + tuple(
    head + suffix for head in _TRADE_HEADS for suffix in ("n", "na", "rna")
)

# A one-character prefix is a coincidence rather than a compound, so a match
# needs two, and the whole token has to be long enough to be one: `elsaljare`
# is exactly nine and is the shortest real example in the corpus.
_MIN_COMPOUND = 9


def _compound(title: str, heads: tuple[str, ...]) -> str | None:
    """The first token of a title that ends in one of `heads` as a compound.

    Swedish builds an occupation by compounding and token matching cannot see
    inside one, so the occupational *head* -- the last element, the part that
    names the job -- is matched as a suffix. `lexicon.compound` does the same
    thing one module over, for the same reason.

    Wrong in English, where a compound is two tokens and a suffix test would
    fire on any word with the same ending. Safe here because the heads are long
    and Swedish is agglutinative.
    """
    for token in title.split():
        if len(token) < _MIN_COMPOUND:
            continue
        for head in heads:
            if len(token) >= len(head) + 2 and token.endswith(head):
                return token
    return None


def _compound_manager(title: str) -> str | None:
    """The first token of a title that is a compounded Nordic manager word."""
    return _compound(title, _MANAGER_HEADS)

# Checked first and they win -- but only for the titles where `director` means
# something other than a rank.
#
# `associate director`, `assistant director` and `deputy director` used to be
# here, on the grounds that a bank stamps them on a five-year hire. The user has
# since asked for director titles to go outright, and the two readings agree for
# this reader: a bank's five-year Associate Director is as unreachable from under
# a year as a real one. They count as management now.
#
# It was not academic. Three such postings reached the labelling sheet after the
# gate was added, because the protection here sent them to `seniority`, where a
# body asking for three years read `mid_3_5` and cleared the bar.
_NOT_MANAGEMENT = _terms(
    "art director", "creative director", "director of photography",
    "funeral director", "board of directors",
)

# The software specialties, treated harder than the rest of engineering.
#
# `lexicon.ENGINEERING` is two-sided on purpose -- `Software Engineer, Trading
# Systems` at Optiver is in scope and `Senior Backend Engineer, Payments
# Platform` is not. These titles are the subset where that ambiguity does not
# exist: the specialty *is* the job, and no markets context around it makes it
# quant work. Six hand-labelled rejections had all reached `adjacent` on the
# bare word *trading* -- the platform the engineer maintains, not the work.
#
# **Bare `software engineer` and `developer` are deliberately absent**, because
# a quant-dev role calls itself one and heavy systems engineering is a
# down-rank rather than a hard drop. `principal engineer` and `staff engineer`
# are in: they name the software IC ladder, which no quant title does. An
# unambiguous quant word still wins, as it does over a management title.
_SOFTWARE_SPECIALTY = _terms(
    "frontend", "front end", "web developer", "mobile developer", "android",
    "ios developer", "react", "angular", "ui engineer", "ux engineer",
    "devops", "sre", "site reliability", "cloud engineer", "cloud architect",
    "infrastructure engineer", "network engineer", "systems administrator",
    "system administrator", "database administrator", "principal engineer",
    "staff engineer", "software architect", "solution architect",
    "security engineer", "cyber security", "cybersecurity",
    "information security", "penetration testing",
    "qa engineer", "quality engineer", "test engineer", "automation engineer",
    "release engineer", "build engineer",
    # `qe` is two characters and earns its place by measurement rather than
    # length: eight titles carry it and the only positively-rated one is
    # `Staff QE`, a hand rejection. In a body it would be quantitative easing;
    # this list is read from the title only.
    "qe",
    "it support", "help desk", "helpdesk", "service desk", "desktop support",
    "application support", "technical support",
    "salesforce", "servicenow", "sharepoint",
    # The Swedish forms, one token each, so no English needle above sees them.
    "frontendutvecklare", "webbutvecklare", "systemadministrator",
    "supporttekniker", "driftstekniker", "testautomatiserare", "testare",
    "informationssakerhet", "sakerhetsspecialist", "it tekniker",
)

_QUANT_ADJACENT = (
    "trading", "researcher", "research analyst",
    "data scientist", "data science", "machine learning", "deep learning",
    "statistician", "statistics", "econometrics", "financial engineering",
    "pricing analyst", "portfolio analyst", "investment analyst",
    "risk analyst", "analytics", "research engineer", "datavetenskap",
    "dataanalytiker", "riskanalytiker", "risikoanalytiker", "maskininlarning",
    "maskinlaering", "ekonometri", "ekonometriker",
)

# What kind of job this is, as **one** value rather than a set. A multi-valued
# version said almost nothing: one Schonfeld posting came back as research and
# trading and quant_dev and risk and portfolio_construction at once, because
# every one of those words appears somewhere in a long body. Seven values is a
# word count, not a classification.
#
# Order is the priority and carries three deliberate decisions:
#
# - `quant_dev` runs first so a title naming both halves -- and `Quantitative
#   Research / Developer` is a real posting, folding to "research developer" --
#   lands on the building half. A title that says only *researcher* falls
#   through to `quant_research` on the next line.
# - `quant_research` runs before `operations`, because a quant word in a title
#   outranks the name of the desk it sits on. `Quantitative Researcher, Trading
#   Operations` is a researcher in the ops org, not an ops hire -- the same
#   rule that keeps a quant title from being rejected by a desk word.
# - `operations` still runs before `trading`, so `Trading Operations Analyst`
#   is operations. The desk's name is not the role's name.
_ROLE_CLASS = {
    "quant_dev": _terms(
        "quant developer", "quantitative developer", "quant dev",
        "research developer", "research engineer", "quantitative engineer",
        "quant engineer", "strat", "strats", "trading systems",
        "trading technology", "low latency engineer", "forward deployed",
    ),
    "quant_research": _terms(
        "quantitative research", "quantitative researcher", "quantitative analyst",
        "quant researcher", "quant research", "quant analyst",
        "alpha research", "signal research", "alpha generation",
        "model validation", "model risk", "derivatives pricing",
        "pricing models", "quantitative strategies", "financial engineering",
        "econometrics", "econometrician", "statistician",
        # A *risk quant* is a modelling role; a *risk analyst* is not
        # necessarily one and stays in `risk` below. The qualifier is the whole
        # difference, as it is for `Credit Risk Operations`.
        "risk quant", "quant risk", "credit risk quant", "market risk quant",
        "market risk models", "quantitative risk",
        # Same argument pointing the other way: *counterparty* credit risk has
        # no retail-collections reading, and all 16 titles carrying it are bank
        # quant seats. Bare `credit risk` still lands in `risk` below.
        "counterparty credit risk", "xva",
        "researcher", "research analyst", "kvantitativ analytiker",
        "kvantitativ", "forskning", "onderzoek", "recherche",
        "kvantitativ analys", "kvantitativ analyse", "modellvalidering",
        "modelvalidering", "riskkvant",
    ),
    "operations": _terms(
        "trading operations", "trade operations", "trading services",
        "trade support", "trading support", "middle office", "back office",
        "settlements", "reconciliation", "reconciliations", "trade lifecycle",
        "operations analyst", "operations associate", "trade capture",
        "corporate actions", "post trade", "handelsstod",
    ),
    "trading": _terms(
        "trader", "trading", "market making", "market maker",
        "handelaar", "handlare", "haendler", "portfolio trading",
        # The compounds only: bare `handel` is Swedish and Danish for
        # *commerce*, so it names a shop as often as a desk.
        "aktiehandel", "vardepappershandel", "borshandel", "valutahandel",
        "derivathandel", "algoritmehandel",
    ),
    "portfolio_management": _terms(
        "portfolio manager", "portfolio management", "portfolio construction",
        "asset allocation", "investment manager", "fund manager",
        "portfolio analyst",
        "portfoljforvaltare", "portfoljforvaltning", "kapitalforvaltare",
        "fondforvaltare", "portefoljeforvalter", "portefoljeforvaltning",
        "portefoljeleder", "kapitalforvaltning",
    ),
    "risk": _terms(
        "market risk", "credit risk", "risk analyst", "risk manager",
        "risk management", "counterparty risk", "risk analytics",
        "riskhantering", "risico", "risiko",
        "riskanalytiker", "risikoanalytiker", "riskkontroll",
        "marknadsrisk", "markedsrisiko", "kreditrisk", "kreditrisiko",
    ),
    "data_science": _terms(
        "data scientist", "data science", "machine learning", "deep learning",
        "datavetenskap", "dataanalytiker", "maskininlarning", "maskinlaering",
    ),
    "engineering": _terms(
        "software engineer", "software developer", "developer", "programmer",
        "platform engineer", "infrastructure engineer", "data engineer",
        "devops", "site reliability", "utvecklare", "ontwikkelaar",
        "systemutvecklare", "engineer",
        "udvikler", "programmerare", "mjukvaruutvecklare", "softwareudvikler",
    ),
}

# Where the role sits, which the title almost never says and the body almost
# always does: `Quantitative Trading Associate` reads like a desk seat and its
# body is runbooks and position reconciliation -- middle office in a quant
# title.
#
# `front_office` is checked **first**. A front-office posting names
# middle-office machinery all the time and the reverse is rare, so the specific
# claim ("you will sit on the trading floor") wins over the incidental mention.
_DESK = {
    "front_office": _terms(
        "front office", "trading floor", "trading desk", "on the desk",
        "revenue generating", "sit with the traders", "sit on the desk",
        "sits with the portfolio managers", "risk taking", "own a book",
        "market facing", "handelsgolv",
    ),
    "middle_office": _terms(
        "middle office", "trade support", "trading support", "trade lifecycle",
        "reconciliation", "reconciliations", "position reconciliation",
        "incident response", "runbook", "runbooks", "trade capture",
        "collateral management", "operational oversight", "control thresholds",
        "trading operations", "operational runbooks", "p l production",
        "break resolution", "trade breaks",
    ),
    "back_office": _terms(
        "back office", "settlements", "settlement processing", "custody",
        "clearing operations", "corporate actions", "fund accounting",
        "transfer agency", "post trade processing", "static data",
    ),
}

# The rank the title states, and neither `intern` nor `student_intern` is one.
# Schonfeld's `Quantitative Research / Developer - Intern` demands "2-3 years":
# an internship *contract* around a mid-level *bar*, and the two facts are
# stored separately -- `contract: internship` for the first, this for the
# second. Being a student is likewise an eligibility fact, carried by
# `_HARD_GATES["student_only"]` and by `contract`, not a rung.
#
# **`vp` and bare `director` sit on `head_or_md`**, against four hand-labelled
# rows reading *"filter out becuase VP role"*. At a bank VP is a mid-career
# grade, which is true and no longer decides anything: `_MANAGEMENT` has gated
# these titles since the user asked for director roles to go, so the ladder
# calling them mid-career was one word with two answers.
#
# `associate director` and `executive director` stay `senior_6_10`, which bare
# `director` would swallow -- `_first` takes the first bucket that hits, so
# order cannot express it and `_NOT_HEAD_GRADE` below is the guard. `md` was
# held back as the postal code for Maryland and the dry-run cleared it: 78
# titles carry it and the one rated positively is an officer seat. The state
# code lives in `location`, which this never reads.
_SENIORITY = {
    "head_or_md": _terms(
        "head of", "managing director", "chief", "partner", "global head",
        "director of", "director", "md", "vp", "vice president", "president",
        "direktor", "vd", "koncernchef",
    ),
    # `leader` as well as `lead`, or `Data Science Leader` carries no grade
    # word and a body asking for three years reads it as `mid_3_5`.
    "lead": _terms("lead", "leader", "principal", "staff engineer", "team lead"),
    "senior_6_10": _terms(
        "senior", "erfaren", "erfarne", "avp", "associate director",
        "executive director",
    ),
    # `graduate` is `new_grad`, not `junior_0_2`: in a title it names the
    # intake, and a graduate scheme is a different prospect from a job wanting
    # two years -- the distinction the ladder exists to draw.
    "new_grad": _terms(
        "graduate programme", "graduate program", "new grad", "campus hire",
        "traineeprogram", "trainee", "graduate", "graduates", "nyexaminerad",
        "nyutexaminerad", "nyuddannet",
    ),
    "junior_0_2": _terms("junior", "associate", "entry level"),
    "mid_3_5": _terms("mid level", "experienced hire"),
}

# Titles where `director` is not an officer grade, and bare `director` needs
# both kinds: where the word means something else (`Art Director`), and the
# bank grades stamped on a five-year hire (`Associate Director, EQD Quant`).
# Both are pinned by tests and both broke when bare `director` went in above.
_NOT_HEAD_GRADE = _terms(
    "art director", "creative director", "director of photography",
    "funeral director", "board of directors",
    "associate director", "assistant director", "deputy director",
    "executive director",
)

# The ladder with the officer rung removed, for re-reading a title whose
# `director` turned out not to be one.
_BELOW_HEAD = {
    value: needles for value, needles in _SENIORITY.items()
    if value != "head_or_md"
}

# A years figure is the one carve-out from "the rank is in the title". That
# rule guards against *stray words* -- a body saying "you report to the Head of
# Trading" made `Graduate Trader` an officer posting. A years figure is not
# that: it is the posting stating its own bar, and `Quantitative Trading
# Associate` demanding "3+ years" is mid however the title grades itself.
_YEARS = (
    # "3+ years". `+` survives folding precisely so this can be read.
    re.compile(r" (\d{1,2}) *\+ *(?:years|yrs|year) "),
    re.compile(r" (?:at least|minimum|minimum of|min|over) (\d{1,2}) (?:years|yrs) "),
    # "2-3 years" and "2 to 3 years": the floor is the smaller number.
    re.compile(r" (\d{1,2}) (?:to|or) (\d{1,2}) (?:years|yrs) "),
    re.compile(r" (\d{1,2}) (\d{1,2}) (?:years|yrs) "),
    re.compile(
        r" (\d{1,2}) (?:years|yrs)(?: of)?"
        r"(?: relevant| professional| work| industry| prior)? experience "
    ),
)
MAX_YEARS = 30  # above this it is a date, a salary band or a typo


def experience_floor(text: str) -> int | None:
    """The smallest number of years the text demands, or None.

    Smallest, because a posting saying "3+ years, 5+ preferred" has a floor of
    three and the preference is not a bar. Same asymmetry as everywhere else
    here: over-stating what a posting requires costs a real opening.
    """
    found = [
        int(group)
        for pattern in _YEARS
        for match in pattern.finditer(text)
        for group in match.groups()
        if group and int(group) <= MAX_YEARS
    ]
    return min(found) if found else None


# Where a stated floor puts the posting on the ladder. Only ever consulted for
# the grades a number can actually settle -- a floor never turns a posting into
# `head_or_md` or `lead`, because those are structural facts about the role
# rather than a length of service.
_FLOOR_RANK = ((6, "senior_6_10"), (3, "mid_3_5"), (0, "junior_0_2"))
# `new_grad` is left out with the structural grades. A graduate scheme is a
# graduate scheme whatever stray number its body carries, and the asymmetry
# points one way: preserving it costs a few seconds of reading, overriding it
# to `senior_6_10` drops the posting out of the shortlist entirely.
_FLOOR_DECIDES = frozenset({"junior_0_2", "mid_3_5", "senior_6_10", "unknown"})

# **A years figure may raise a rank and must never lower one the title stated.**
# The rule it carves out of "the rank is in the title" was always about a title
# under-selling itself -- `Quantitative Trading Associate` says associate and
# demands "3+ years", so the bar is the fact. Read in the other direction it
# does real damage: `Senior Software Engineer` whose body mentions three years
# came out `mid_3_5`, and a body's smallest number is routinely the *entry* bar
# on a senior posting ("3+ years required, 8+ preferred" floors at three).
#
# Measured on the machine sheet: leadership recall was 46.1%, and every miss
# was a title saying senior whose body demoted it out of `out_of_reach`.
_LADDER = ("junior_0_2", "mid_3_5", "senior_6_10")

# The ladder the user actually cares about. 4 and 5 down-rank, never drop:
# `CLAUDE.md` is explicit that many quant-dev roles list C++ second and fit.
_CODE_DEPTH = {
    "hardware": ("fpga", "verilog", "kernel bypass", "colocation", "asic"),
    "systems": (
        "cplusplus", "rust", "low latency", "ultra low latency", "hft systems",
        "distributed systems", "kernel", "concurrency",
    ),
    "python_production": (
        "ci cd", "docker", "kubernetes", "microservices", "production code",
        "software engineering best practices", "unit tests",
    ),
    "python_analytical": (
        "python", "pandas", "numpy", "scipy", "jupyter", "backtest",
        "backtesting", "scikit", "pytorch", "tensorflow",
    ),
    "spreadsheet_sql": ("excel", "vba", "sql", "power bi", "tableau"),
}

_LANGUAGES = (
    "python", "cplusplus", "rust", "java", "kdb", "matlab", "sql", "scala",
    "csharp", "julia", "javascript", "typescript", "dotnet", "fsharp",
)

# Needles are written pre-folded: this table is a plain tuple, not `_terms`.
#
# **`ravaror` is deliberately absent, and it is the warning for this table.**
# *Råvaror* is Swedish for commodities and for raw ingredients: it matches 49
# bodies and every one is a kitchen. The Nordic markets words that survive are
# the ones that cannot mean anything else, which means the compounds.
_ASSET_CLASS = {
    "equities": ("equity", "equities", "cash equities", "aktier", "aandelen",
                 "aktiehandel"),
    "futures": ("futures", "term determineerbaar"),
    "fx": ("fx", "foreign exchange", "currencies", "valuta", "valutahandel",
           "valutamarknad", "valutamarked"),
    "rates": ("rates", "fixed income", "government bonds", "swaps", "rante",
              "obligationer", "statsobligationer", "renteprodukter",
              "rantebarande"),
    "credit": ("credit", "corporate bonds", "cds", "kredit",
               "foretagsobligationer", "virksomhedsobligationer"),
    "commodities": ("commodities", "commodity", "energy trading", "power gas",
                    "energihandel", "elhandel"),
    "options_vol": ("options", "volatility", "vol trading", "derivatives",
                    "optioner", "optionshandel", "volatilitet",
                    "derivathandel", "derivatinstrument"),
    "crypto": ("crypto", "cryptocurrency", "digital assets", "defi", "web3",
               "blockchain", "kryptovaluta"),
    "multi_asset": ("multi asset", "cross asset", "multi strategy"),
}

_HORIZON = {
    "hft": ("high frequency", "hft", "tick to trade", "microsecond", "nanosecond"),
    "mid_frequency": ("mid frequency", "intraday"),
    "stat_arb": ("statistical arbitrage", "stat arb", "market neutral"),
    "long_horizon": ("long horizon", "long term", "fundamental"),
}

# Kept as tags rather than a filter, so it is possible to see how much of the
# market each gate costs. "Half of Amsterdam wants no sponsorship" is worth
# knowing as a number, not as an empty result list.
_HARD_GATES = {
    # Only a *compulsory* doctorate. "PhD preferred" is how every quantitative
    # posting on earth is written, so tagging it would fire on the whole corpus
    # and separate nothing. Read from title and body alike: one hand-labelled
    # row announces it as `PhD+`, which survives folding as one token.
    #
    # **Bare `phd` is deliberately absent.** 220 titles carry it and 29 are
    # rated positively, `Campus Quantitative Researcher, PhD` among them: the
    # word names the audience a posting is open to, not a bar it sets.
    "phd_required": _terms(
        "phd required", "phd is required", "phd is a requirement",
        "must hold a phd", "must have a phd", "requires a phd",
        "phd mandatory", "phd degree required", "doctorate required",
        "doctorate is required", "phd essential", "phd+", "phd only",
        "phd candidates only", "phd holders only", "phd degree is required",
        "doktorsexamen kravs", "krav pa doktorsexamen", "doktorgrad kraeves",
        "ph d er et krav", "phd er et krav",
    ),
    "visa_sponsorship_none": _terms(
        "no visa sponsorship", "not able to sponsor", "unable to sponsor",
        "without sponsorship", "must have the right to work",
    ),
    # A posting demanding a *future* graduation date is one this reader cannot
    # pass, which is what a hard gate is -- not a rank. Specific phrases only:
    # a bare "student" fires on any body that merely welcomes them, and marked
    # a full-time research role at Radix Trading as student-only.
    "student_only": _terms(
        "currently enrolled", "must be enrolled", "final year student",
        "final year students", "penultimate year", "still studying",
        "graduating in 2027", "graduating in 2028", "graduating in 2029",
        "expected graduation", "pursuing a degree", "studerande vid",
        # Same specific-phrasing rule: bare `studerande` and `studerende` are
        # as unsafe as bare "student".
        "du studerar vid", "pagaende studier", "du er studerende",
        "skal vaere studerende", "igangvaerende uddannelse",
    ),
    "security_clearance": _terms("security clearance", "clearance required"),
    "onsite_only": _terms(
        "onsite only", "fully onsite", "in office five days", "no remote"),
}

# Checked before the gate above, and it has to be: matching is on token runs,
# so " no phd required " *contains* " phd required " and a posting saying the
# opposite of the gate would otherwise trip it.
_PHD_NOT_REQUIRED = _terms(
    "no phd required", "phd not required", "phd is not required",
    "phd is not a requirement", "without a phd", "phd or equivalent experience",
)

# A soft filter, not a gate. English and Swedish are deliberately absent: the
# reader has both, so demanding them is no obstacle -- the old gate flagged
# "flytande svenska" on Stockholm postings, the hub that matters most.
# Multi-valued, because Hong Kong asks for two.
#
# **Built from frames rather than hand-written**, because three phrasings per
# language caught 151 postings out of 69,961 -- advertisements also say
# "proficiency in", "good command of", "C1", "i tal och skrift". Requirement
# phrasings only: `{L} a plus` and bare `{L}` are deliberately not frames. A
# generous frame costs a notch of rank; a missing one costs a surprise at
# interview.
_FLUENCY_FRAMES = (
    "fluent in {}", "fluency in {}", "fluent {}", "native {}",
    "native level {}", "{} native", "{} is required", "{} required",
    "{} is essential", "{} essential", "{} is a must", "must speak {}",
    "proficiency in {}", "proficient in {}", "proficiency of {}",
    "{} proficiency", "{} language skills", "{} speaking", "{} speaker",
    "excellent {}", "strong {}", "good command of {}", "command of {}",
    "written and spoken {}", "spoken and written {}", "{} in speech and writing",
    "business level {}", "business fluent {}", "{} c1", "{} c2", "{} b2",
    "verbal and written {}", "solid {}", "very good {}", "advanced {}",
)

# The names a posting actually uses, including in its own language. `_terms`
# folds these the same way the text is folded, so a diacritic is safe to write
# now that `fold` transliterates rather than deletes.
_LANGUAGE_NAMES = {
    "dutch": ("dutch", "nederlands", "niederländisch", "néerlandais"),
    "german": ("german", "deutsch", "allemand", "duits"),
    "danish": ("danish", "dansk", "deens"),
    "norwegian": ("norwegian", "norsk", "noors"),
    "finnish": ("finnish", "suomi", "finska", "finnisch"),
    "french": ("french", "français", "francais", "französisch", "frans"),
    "mandarin": ("mandarin", "chinese", "putonghua", "mandarin chinese"),
    "cantonese": ("cantonese",),
    "japanese": ("japanese", "nihongo", "japanisch"),
    "spanish": ("spanish", "español", "espanol", "castellano", "spanisch"),
    "italian": ("italian", "italiano", "italienisch"),
    "portuguese": ("portuguese", "português", "portugues"),
}

# Phrasings that name the requirement without naming it in a frame. These are
# idioms rather than templates, so they stay hand-written.
_FLUENCY_IDIOMS = {
    "german": ("verhandlungssicher", "verhandlungssicheres deutsch",
               "gute deutschkenntnisse", "sehr gute deutschkenntnisse",
               "deutschkenntnisse", "deutsch erforderlich", "fliessend deutsch"),
    "dutch": ("vloeiend nederlands", "nederlands is vereist",
              "goede beheersing van het nederlands", "nederlandse taal"),
    "danish": ("dansk på modersmålsniveau", "flydende dansk",
               "dansk i skrift og tale"),
    "norwegian": ("flytende norsk", "norsk i skrift og tale"),
    "french": ("français courant", "maîtrise du français",
               "parfaite maîtrise du français"),
    "finnish": ("sujuva suomi", "suomen kieli"),
}


def _fluency(names: tuple[str, ...], idioms: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Every requirement phrasing for one language, folded once at import."""
    phrases = [frame.format(name) for name in names for frame in _FLUENCY_FRAMES]
    # Deduplicated because two names can fold to the same token -- `français`
    # and `francais` both become `francais` now that `fold` transliterates.
    return tuple(dict.fromkeys(_terms(*phrases, *idioms)))


_SPOKEN_REQUIRED = {
    language: _fluency(names, _FLUENCY_IDIOMS.get(language, ()))
    for language, names in _LANGUAGE_NAMES.items()
}

# **This is where `vikarie` belongs, and the dry-run is why.** A *vikarie* is
# somebody covering an absence -- a contract length, not a profession -- so
# gating it as another trade would delete a temporary quant seat on evidence
# about its duration. It reaches 126 titles and `timvikarie`, `sommarvikarie`
# and `barselsvikariat` another 700 between them, almost all care and school
# work, which the occupation words in `_OFF_INDUSTRY` catch on their own terms.
_CONTRACT = {
    "internship": ("intern", "internship", "praktik", "praktikant",
                   "praktikplats", "studiejob", "studentjobb",
                   "studentmedhjaelper", "studentermedhjaelper",
                   "studentmedarbetare"),
    "fixed_term": ("fixed term", "temporary", "vikariat", "tijdelijk",
                   "befristet", "vikarie", "vikarier", "timvikarie",
                   "timvikarier", "sommarvikarie", "sommarvikarier",
                   "barselsvikariat", "visstidsanstallning", "tidsbegransad",
                   "tidsbegraenset", "provanstallning"),
    "contractor": ("contractor", "freelance", "consultant", "konsult",
                   "konsulent", "frilans"),
    "part_time": ("part time", "deltid", "parttime", "teilzeit",
                  "deltidsjobb", "deltidsstilling", "timanstallning",
                  "extrajobb"),
    "permanent": ("permanent", "full time", "tillsvidare", "heltid",
                  "vast contract", "tillsvidareanstallning", "fast stilling",
                  "fastansaettelse", "fast ansaettelse"),
}

# The exclude list, one tag each, so it is auditable by category. `crypto` and
# `heavy_systems` down-rank; the rest reject.
_EXCLUSION = {
    "actuarial": ("actuary", "actuarial", "aktuarie", "actuaris", "aktuar"),
    "insurance_pricing": ("insurance pricing", "skadereglering"),
    # Its own category because it must be title-only. `insurance_pricing` is
    # `_BODY_SAFE`, and in a body these are ordinary banking words -- debt
    # underwriting is securities issuance, not insurance. It rejected 1,834
    # postings on a clean title, `Associate, FICC Structuring` among them.
    "insurance_underwriting": ("underwriting", "claims", "claims handler"),
    "non_markets_fintech": ("payments", "kyc", "aml", "fraud detection",
                            "lending platform", "penningtvatt", "hvidvask",
                            "betalningar", "betalinger"),
    # Lending is not markets. `lexicon.NON_QUANT_FINANCE` carries these too
    # and that is not enough on its own: `judge` runs last, so `Senior Lending
    # Analyst - Portfolio & Risk Analytics` had already reached `adjacent` on
    # *risk analytics*. An exclusion outranks a weak positive; that ordering
    # is what makes this fire.
    "lending": _terms(
        "loan analyst", "lending analyst", "distressed loan", "loan servicing",
        "loan officer", "mortgage analyst",
        "laneradgivare", "bolanehandlaggare", "boligradgiver",
        "lanehandlaggare",
    ),
    "insurance_ops": (
        "insurance accounting", "insurance reporting", "policy administration",
        "skadeforsikring", "forsikring",
        # Occupations rather than the bare noun: this category is `_BODY_SAFE`,
        # and `forsakring` is a word every Nordic bank writes in passing.
        "skadereglerare", "forsakringsradgivare", "skadehandlaggare",
    ),
    "support_function": (
        "recruiter", "recruitment", "talent acquisition", "human resources",
        "marketing", "communications", "office manager", "receptionist",
        "accounting", "bookkeeping", "payroll",
        "rekryterare", "rekrutterer", "marknadsforing", "markedsforing",
        "personaladministrator",
        # The Nordic half. A corporate function is the same job in any
        # language, and the English words said nothing about `HR-ansvarig` or
        # `Lönekonsult`. They belong here rather than in `_OFF_INDUSTRY`
        # because HR, marketing and payroll are functions every firm has,
        # including a trading firm -- not another profession. This category is
        # not `_BODY_SAFE`, so these are title-only, which is what they need.
        # Dry-run: none touches a positively-rated posting.
        "hr ansvarig", "hr specialist", "hr konsult", "hr assistent",
        "hr partner", "rekryteringskonsult", "personalkonsulent",
        "lonekonsult", "loneassistent", "redovisningsassistent", "bogholder",
        "kommunikator", "marknadskoordinator", "marknadsassistent",
        "markedskoordinator", "kampanjkoordinator", "kampanjplanerare",
        "eventkoordinator", "sociala medier", "paid social",
        "seo specialist", "sem specialist", "copywriter", "grafisk designer",
        "fotograf",
    ),
    "crypto_web3": ("crypto", "web3", "defi", "blockchain", "nft"),
    "heavy_systems": ("fpga", "verilog", "kernel bypass", "embedded systems"),
    # Investing by judgement rather than by model. The hand-labelled sheet
    # rejected nine of these in a row while the lexicon had `investment
    # analyst` and `portfolio analyst` filed as weak *positives*.
    #
    # Title only, and read after the core check, so `Quantitative Analyst,
    # Private Equity` keeps its quant reading. It ranks rather than rejects --
    # see `SOFT` in `tag_posting`.
    "discretionary_investing": _terms(
        "private equity", "venture capital", "investment banking",
        "mergers and acquisitions", "equity research", "fundamental research",
        "asset management", "asset management analyst", "wealth advisory",
        "investment analyst", "portfolio associate",
        "wealth management", "investor relations", "equity investments",
        "fund analyst", "investment associate", "corporate development",
    ),
}

# --------------------------------------------------------------------------
# Stage one: another profession entirely.
#
# Every other exclusion here *ranks*. This one is different in kind -- a nurse
# and a welder are not distant quant roles, they are other jobs, and the board
# drops them. It is the only place in the pipeline where a classifier removes
# rather than reorders, so it is deliberately the narrowest rule in the file.
#
# It never touches the database: `jobs` keeps the row, the tag records why, and
# re-running the tagger rebuilds the verdict, so a wrong term costs one
# `build_data.py` run rather than a re-scrape.
#
# Two signals, and the first is much the stronger:
#
# 1. **The source's own taxonomy** -- an enumeration the employer picked from,
#    not a guess read off a title. This is why `jobs.category` exists.
# 2. **Unambiguous occupation words in the title**, only for the ATS boards,
#    which publish no taxonomy at all. Every needle was dry-run over the whole
#    corpus first and hit nothing in finance.
_OFF_INDUSTRY_FIELDS = frozenset({
    "Hälso- och sjukvård", "Pedagogik", "Yrken med social inriktning",
    "Transport, distribution, lager", "Hotell, restaurang, storhushåll",
    "Sanering och renhållning", "Industriell tillverkning",
    "Bygg och anläggning", "Installation, drift, underhåll",
    "Säkerhet och bevakning", "Kultur, media, design", "Naturbruk",
    "Kropps- och skönhetsvård", "Hantverk", "Militära yrken",
})

# Kept deliberately: "Administration, ekonomi, juridik", "Data/IT",
# "Chefer och verksamhetsledare", "Yrken med teknisk inriktning",
# "Naturvetenskap" -- and "Försäljning, inköp, marknadsföring", which is the
# ambiguous one. A commodity or sales trader files there, so it stays and the
# read-time filters handle it. An unrecognised field passes too: a drop list
# fails towards keeping, which is the direction this project always picks.

# MyCareersFuture's taxonomy, same argument. Its own set because the portal
# files a posting under *several* categories at once, so this is a subset test
# rather than equality.
#
# Dry-run over the 37,000 postings swept, and the first attempt was wrong: a
# loose probe put `Building and Construction` top of the "carries quant titles"
# list, because construction has risk managers and BIM modellers. Tightened to
# unambiguous markets words, what stays out is below and everything else --
# Banking and Finance, IT, Engineering, Risk Management, Sciences, Insurance,
# Consulting, Accounting, Manufacturing, Healthcare, Public Service, General
# Management, Others, Telecommunications -- was found to carry real quant work.
_MCF_OFF_INDUSTRY = frozenset({
    "Admin / Secretarial", "Advertising / Media",
    "Architecture / Interior Design", "Building and Construction",
    "Customer Service", "Design", "Education and Training", "Entertainment",
    "Environment / Health", "Events / Promotions", "F&B", "General Work",
    "Hospitality", "Human Resources", "Legal", "Logistics / Supply Chain",
    "Marketing / Public Relations", "Medical / Therapy Services",
    "Personal Care / Beauty", "Precision Engineering",
    "Purchasing / Merchandising", "Real Estate / Property Management",
    "Repair and Maintenance", "Sales / Retail", "Security and Investigation",
    "Social Services", "Travel / Tourism",
})


# Jobindex's own taxonomy, and Denmark needs it more than the other two hubs
# do. The occupation needles below are English and Swedish, and Danish is close
# enough to look covered and far enough not to be: `Sygeplejerske`, `Pædagog`,
# `Lærer` and `Rengøringsassistent` match nothing in `_OFF_INDUSTRY`, so
# without this list the whole Danish care, teaching and cleaning workforce
# reaches the board. Writing Danish needles instead was the alternative and it
# is strictly worse -- the board publishes an enumeration the employer picked
# from, which is the same argument `_OFF_INDUSTRY_FIELDS` makes one comment up.
#
# A posting carries more than one about a quarter of the time, so this is a
# subset test rather than equality, like the Singaporean list.
#
# **Dry-run over the swept corpus, and the borderline calls are recorded.**
# `Salg` stays, because the Swedish drop list already decided that a commodity
# or sales trader files under selling and the read-time filters handle it.
# `Forsvar og efterretning` stays: intelligence services hire analysts, and
# Denmark's money-laundering secretariat advertises there. `Øvrige` stays for
# the reason MyCareersFuture keeps `Others` -- a catch-all is where a posting
# nobody classified lands, which is the opposite of evidence. Engineering,
# science and pharma stay, because MyCareersFuture's dry-run found real quant
# work in every one of those and there is no reason Denmark differs.
_JOBINDEX_OFF_INDUSTRY = frozenset({
    # care, health and social work
    "Læge", "Lægesekretær", "Pleje og omsorg", "Psykologi og psykiatri",
    "Socialrådgivning", "Sygeplejerske og jordemoder",
    "Tandlæge og klinikpersonale", "Teknisk sundhedsarbejde",
    "Terapi og genoptræning",
    # teaching and childcare
    "Børnepasning", "Institutions- og skoleledelse", "Lærer", "Pædagog",
    "Voksenuddannelse",
    # trades, industry and transport
    "Blik og rør", "Bygge og anlæg", "Elektriker", "Jern og metal", "Lager",
    "Landbrug, skov og fiskeri", "Maling og overfladebehandling",
    "Mekanik og auto", "Tekstil og kunsthåndværk", "Transport",
    "Træ- og møbelindustri", "Tømrer og snedker",
    # retail, hospitality and personal service
    "Bud og udbringning", "Detailhandel", "Detailledelse", "Ejendomsservice",
    "Frisør og personlig pleje", "Hotel, restaurant og køkken", "Rengøring",
    "Service", "Sikkerhed",
    # other named professions
    "Bibliotek", "Ejendomsmægler", "Kultur og kirke", "Telemarketing",
})


def _jobindex_off_industry(category: str | None) -> str | None:
    """Whether every category this Danish posting carries is off-industry.

    A subset test, never equality: one kept category keeps the posting, and an
    unrecognised label passes.

    **Split on the pipe, not the comma.** `Hotel, restaurant og køkken` and
    `Landbrug, skov og fiskeri` both contain commas, so splitting on one would
    cut two of the board's biggest trades into halves matching nothing.
    `jobindex.py` joins with `CATEGORY_SEPARATOR` for this reason.
    """
    if not category:
        return None
    carried = {part.strip() for part in category.split("|") if part.strip()}
    if carried and carried <= _JOBINDEX_OFF_INDUSTRY:
        return f"field {', '.join(sorted(carried))!r}"
    return None


def _mcf_off_industry(category: str | None) -> str | None:
    """Whether every category this posting carries is off-industry.

    A subset test, never equality: the portal files most postings under several
    categories and one kept category keeps the posting. An unrecognised field
    passes too -- a drop list fails towards keeping.
    """
    if not category:
        return None
    carried = {part.strip() for part in category.split(",") if part.strip()}
    if carried and carried <= _MCF_OFF_INDUSTRY:
        return f"field {', '.join(sorted(carried))!r}"
    return None


# Title-only, and never read from a body. `chef` is absent on purpose -- it is
# Swedish for *manager*, so it would drop `Ekonomichef`, a CFO. So is `driver`,
# which cost one true positive in the whole corpus and would eventually catch
# something like `Value Driver Analyst`.
_OFF_INDUSTRY = _terms(
    # care
    "nurse", "sjukskoterska", "underskoterska", "lakare", "physician", "doctor",
    "dentist", "tandlakare", "veterinar", "veterinary", "physiotherapist",
    "sjukgymnast", "barnmorska", "midwife", "psykolog", "psychologist",
    "medical", "clinical", "patient", "vardbitrade", "personlig assistent",
    "pharmacist", "apotekare", "sjukhus", "vardcentral",
    # teaching and childcare
    "teacher", "larare", "forskollarare", "pedagog", "rektor", "barnskotare",
    "fritidsledare",
    # food, hospitality, cleaning
    "kock", "cook", "kitchen", "koksbitrade", "servitor", "servitris",
    "waiter", "waitress", "bartender", "barista", "stadare", "lokalvardare",
    "cleaner",
    # trades and manual work
    "snickare", "carpenter", "elektriker", "electrician", "rormokare",
    "plumber", "svetsare", "welder", "montor", "truckforare", "forklift",
    "lagerarbetare", "chauffor", "lastbilsforare", "malare", "painter",
    "mekaniker", "mechanic", "maskinforare",
    # retail floor, personal services, uniformed
    "butikssaljare", "frisor", "hairdresser", "massor", "vaktare",
    "security guard", "brandman", "firefighter", "polis", "florist",
    "personal trainer", "flight attendant",
    # front of house and building services
    "receptionist", "receptioniste", "telefonist", "concierge", "front desk",
    "housekeeping", "janitor", "caretaker", "vaktmastare",
    # driving, which the Swedish and French words name unambiguously where the
    # bare English "driver" does not
    "chauffeur", "bus driver",
    # ----------------------------------------------------------------------
    # **Five obvious-looking candidates were dropped after the dry-run**, each
    # of which would have eaten markets work: `salesperson` is *Rates
    # Salesperson*, `sales associate` and `sales representative` are equity and
    # fixed-income sales, `controller` is *Hedge Fund Controller*, and
    # `administrator` is *Database Administrator*. All are the wrong *job*
    # rather than the wrong industry, so they stay rejected on relevance --
    # still on the board, one click away.
    "accountant", "accounting clerk", "bookkeeper",
    # The Swedish `-er` plural of the two entries below it, which the singular
    # needle cannot see -- the `undersköterskor` gap on a list that is matched
    # whole rather than by suffix. `Två kundansvariga redovisningskonsulter
    # till affärsområde Värdepapper` reached the board as `adjacent` on
    # *värdepapper*, a markets word sitting in the name of the department the
    # accountants serve. Nine titles between them, none rated positively.
    # `-er` is spelled out per entry rather than made a rule: as a compound
    # suffix it would fire on `researcher` and `developer`.
    "redovisningsekonom", "redovisningskonsult", "redovisningskonsulter",
    "ekonomiassistent", "ekonomiassistenter",
    # Bare `redovisning` -- the activity rather than the job title, which is
    # how a Swedish advertisement often heads an accounting seat: the reader
    # rejected one titled simply `Redovisning`, and it carries 102 characters
    # of body, too few for the absence test to read. 19 live titles, none
    # rated positively, all of them accounting.
    "redovisning",
    "loneadministrator", "lonespecialist", "ekonomiadministrator",
    # sales, Swedish. The English sales words are all too close to markets
    # sales to gate on; the Swedish ones name shop and telephone work only.
    "saljare", "innesaljare", "utesaljare", "telefonforsaljare", "forsaljare",
    "bilsaljare", "kundtjanstmedarbetare", "kundservicemedarbetare",
    "sales assistant", "field sales", "car sales",
    # administration and supervision
    "administrativ assistent", "handlaggare", "sekreterare", "arbetsledare",
    "produktionsledare", "butikschef",
    # trades and plant
    "anlaggare", "betongarbetare", "stallningsbyggare", "sotare",
    "glasmastare", "dackmontor", "fordonstekniker", "servicetekniker",
    "processoperator", "produktionsoperator", "maskinoperator",
    # care, social work, schools
    "stodassistent", "boendestodjare", "socialsekreterare",
    "behandlingsassistent", "elevassistent", "fritidspedagog",
    "aktivitetsledare",
    # hospitality
    "hotellreceptionist", "pizzabagare", "bagare", "cafebitrade",
    "restaurangbitrade", "diskare", "hovmastare",
    # ----------------------------------------------------------------------
    # Venue, events and front-of-house. Live Nation and student-housing
    # operators publish through the same ATS platforms as the trading firms,
    # so they arrive mixed in.
    #
    # **The safety check is not the head count but whether a needle touches a
    # positively-rated posting.** None of these does. `landscape` was dropped
    # for failing it -- it caught `Managing Technical Consultant, Landscape
    # Architecture`, and a *data* landscape is one usage away.
    "retail associate", "ticket taker", "usher", "box office", "music hall",
    "production runner", "venue", "greeter", "host", "workplace ambassador",
    "student living", "environmental inspector", "auto appraiser",
    "rental service agent",
    # French and German field sales, which arrive through the same tenants
    "conseiller commercial", "aussendienst",
    # **`environmental inspector` did not match `Environmental Inspectors
    # (Field Based)`**: token matching is exact and the corpus advertises the
    # plural. Write the needle against real titles, not the dictionary form.
    "inspector", "inspectors", "project engineer", "design engineer",
    "events support", "promotions", "property associate",
    # Ten rows of the hand-labelled sheet in one title, all Greystar. A
    # *make-ready* is apartment turnover between tenancies: 60 titles, none
    # rated positively, and the other three came off the same boards.
    "make ready", "leasing consultant", "property manager",
    "maintenance supervisor",
    # ----------------------------------------------------------------------
    # **Swedish and Danish, because the corpus stopped being mostly English.**
    # Jobbsafari publishes no taxonomy, so unlike Jobindex and MyCareersFuture
    # there is no enumeration to gate on and these words carry all of it.
    # Danish is here in reverse: `jobindex` *is* gated by its taxonomy, but a
    # `--since` top-up writes a NULL category and a NULL category passes.
    #
    # Three shapes leak that a plain occupation list does not cover:
    #
    # - **The plural** -- `Undersköterskor` past the needle `underskoterska`,
    #   269 times, the same exactness `Environmental Inspectors` showed.
    # - **The workplace, where it is the only thing naming the profession** --
    #   `äldreboende`, `hemtjänsten`, `förskola`.
    # - **The assignment** -- 33 postings headed *Veteraner till städuppdrag!*
    #   name no occupation at all.
    #
    # **Three were dropped after the dry-run.** A *vikarie* is a fixed-term
    # contract rather than a profession, so gating it would delete a temporary
    # quant role on evidence about its length -- it is in `_CONTRACT`. A
    # *souschef* is a deputy manager in Danish as often as a sous-chef in
    # Swedish. And `städ` (cleaning) folds to `stad` (city), which would gate
    # every posting at *Stockholms stad*.
    "personliga assistenter", "underskoterskor", "sjukskoterskor",
    "tandskoterskor", "frisorer", "herrfrisor", "barberare", "hushallerska",
    "hemstadning", "staduppdrag", "stadning", "tradgardsuppdrag", "hemtjanst",
    "hemtjansten", "vardpersonal", "aldreboende", "ungdomsboende",
    "gruppboende", "forskolor", "forskola", "lararvikarie", "forskolevikarie",
    "dackskiftare", "biltestare", "bilplatslagare", "platslagare",
    "bilrekonditionerare", "bilrangerare", "lackerare",
    "lackeringsforberedare", "motesbokare", "telemarketing", "rivare",
    "taxiforare", "trafikvakt", "trafikvakter", "ordningsvakt",
    "ordningsvakter", "parkeringsvakt", "kokschef", "kallskanka", "konditor",
    "slaktare", "maskinoperatorer", "processoperatorer", "elektronikmontorer",
    "montorer", "chaufforer", "lastbilschauffor", "budbilsforare", "optiker",
    "tandhygienist", "apotekstekniker", "ambulanssjukvardare",
    "fastighetsskotare", "fastighetstekniker", "kalkylator", "besiktningsman",
    "tradgardsarbetare", "skogsarbetare", "lantarbetare", "djurskotare",
    "plattsattare", "golvlaggare", "taklaggare", "murare", "isolerare",
    "ventilationsmontor", "kylmontor", "vvs montor", "vvs montorer",
    "elmontor", "falttekniker", "natverkstekniker", "verkstadstekniker",
    "industrielektriker", "cnc operator", "nc operator", "larling",
    "personlig tranare", "massageterapeut", "hudterapeut", "nagelterapeut",
    "fotvardare", "kassabitrade", "butiksbitrade", "butikspersonal",
    "lagermedarbetare", "plockare", "sygeplejerske", "sygeplejersker",
    "social og sundhedsassistent", "sosu assistent", "sosu hjaelper",
    "paedagog", "paedagoger", "paedagogmedhjaelper", "laerer", "laerere",
    "skolelaerer", "tandlaege", "tandplejer", "rengoring",
    "rengoringsassistent", "rengoringshjaelp", "kok", "kokkeelev", "tjener",
    "opvasker", "bagerelev", "lastbilchauffor", "lagermedarbejder",
    "lagerarbejder", "tomrer", "murer", "maler", "smed", "salgsassistent",
    "butiksassistent", "butiksmedarbejder", "kosmetolog", "sikkerhedsvagt",
    "vaegter", "plejehjem", "hjemmeplejen", "sosu", "handvaerker",
    "elevassistenter", "stodassistenter", "behandlingsassistenter",
    "ekonomiassistenter", "vardbitraden",
    # ----------------------------------------------------------------------
    # **Read off the board itself, which is the frame that matters.** A fresh
    # Jobbsafari sweep put 585 Swedish postings in front of the reader and they
    # were babysitters, taxi drivers, postmen and pizza chefs -- a national
    # board advertises jobs no ATS here has ever carried, so the occupation
    # vocabulary had been written against the wrong corpus.
    #
    # **Three were kept *because* they touch a positively-rated posting**, each
    # confirmed by hand as a tagger false keep: `postdoktor` reaches two
    # biophysics postdocs rated `relevant` on the word *kvantitativ*, and
    # `okonomimedarbejder` a municipal accounts clerk.
    #
    # **`handlare` was dropped.** Its one hit is a village shopkeeper, but a
    # Swedish markets posting could reasonably be titled *Handlare*, and one
    # row on the board is cheaper than a rule that could delete a trader.
    # `taxi` was kept only after checking it cannot reach `robotaxi`.
    "barnvakt", "barnvakter", "babysitter", "babysitters", "barnflicka",
    "barnpassning", "laxhjalp", "ledsagare", "anestesiolog", "gynekolog",
    "urolog", "farmaceut", "farmaceuter", "receptarie", "skolpsykolog",
    "specialistpsykolog", "allmanmedicin", "hemtjanstpersonal",
    "familjebehandlare", "terapeuter", "massorer", "omsorgspersonal",
    "kockar", "sushikock", "servis", "serveringspersonal",
    "restaurangpersonal", "kottmastare", "matsal", "flyttstadning",
    "lokalstadning", "fonsterputsare", "fonsterputsning", "sanerare",
    "snoskottare", "skogsrojning", "taxi", "forare", "brevbarare",
    "paketbud", "kurir", "reklamutdelare", "medakare", "paketsortering",
    "gravmaskinist", "materialhanterare", "armerare", "rorlaggare",
    "batbyggare", "arborist", "maleri", "malning", "folierare", "asbest",
    "plattlaggare", "butiksansvarig", "telefonforsaljning", "kundbokare",
    "expeditor", "delikatessansvarig",
    # Schools, universities and public administration. A university chair is
    # not industry quant work and the reader has already graduated, so
    # `adjunkt`, `lektor`, `postdoktor` and `doktorand` are occupations here
    # rather than seniorities.
    "timvikarie", "timvikarier", "timvikariat", "skoladministrator",
    "skolbibliotekarie", "adjunkt", "lektor", "postdoktor", "doktorand",
    "utbildare", "registrator", "arbetsformedlare", "gruppadministrator",
    "forradsadministrator", "utbildningsadministrator", "nattreceptionist",
    "husfru", "skola", "skolan", "grundskola", "gymnasiet", "elevhalsa",
    "aldreomsorg", "fritidshem", "forskoleklass",
    # Danish, from the same reading. Jobindex is gated by its own taxonomy and
    # leaks little, but a `--since` top-up writes a NULL category and a NULL
    # category passes the gate, so these are what stands behind it.
    "sagsbehandler", "ejendomsadministrator", "okonomimedarbejder",
    "studiejob", "kontorelev", "salgselev", "serviceassistent",
    # A second reading, of what the *re-tag* left rated positively rather than
    # of what reached the board. A different frame finds different things, and
    # the first three each remove a posting the tagger had rated positively --
    # the strongest evidence a needle can have:
    #
    # - **`tekniker` was a compound head and never a word**, so
    #   `servicetekniker` gated and a bare `Tekniker` did not: `_compound`
    #   wants nine characters and the word is eight. Its positively-rated hit
    #   is `Tekniker till Quant Service i Ludvika`, an electrical contractor
    #   called Quant. `citadel.com` all over again.
    # - **`bilbranschen` and `bilindustrin` are car sales wearing a markets
    #   word** -- `Trader till växande företag inom bilindustrin`, pinned near
    #   the top because *Trader* is the strongest title word there is.
    "tekniker", "bilbranschen", "bilindustrin", "biltvatt", "bilrekondare",
    "fordonssaljare", "montage", "lagerarbete",
    # The last of the residual, read off the rebuilt board. **`kassa` was
    # dropped**: it is the cash desk in a shop and the cash position in a
    # treasury, so it is the `handel` trap in a new word -- 108 clean hits
    # today and a Swedish liquidity role would be the first thing it ate.
    "diskaren", "servicepersonal", "hotellreceptionister", "postanstalld",
    "fardtjanst", "sjukresor", "forestry", "turism", "fastighetsformedling",
    "baka pizza", "farskvaror",
    # ----------------------------------------------------------------------
    # **Switzerland, the third focus hub with a national board.** Of 22,903
    # Swiss postings only 50 reach the board -- `lexicon.UNRELATED`'s German
    # and French words do most of it -- and those 50 are `Zimmerreinigung`,
    # `Masseurin` and `Dachdecker`, so the gap is a dozen trades.
    #
    # job-room.ch publishes its own taxonomy and it cannot be used: the
    # occupation object carries bare AVAM codes with no labels, and the
    # reference service that would name them is not open. That is why
    # Switzerland is gated by words where Denmark and Singapore are gated by an
    # enumeration.
    #
    # `macon` was read by hand and kept: a French mason fifteen times and
    # Macon, Georgia never -- and safe twice over, since this list is matched
    # against the title and never the location.
    #
    # **`gartner` was dropped even though its dry-run was clean.** All 155
    # Danish gardeners arrive through Jobindex and are already gated by its
    # taxonomy, so the needle buys nothing -- while `Gartner Research Analyst`
    # is a title that exists and would be removed as landscaping. Nothing to
    # gain and something to lose is the whole test.
    "zimmerreinigung", "masseurin", "masseur", "kosmetikerin", "kosmetiker",
    "dachdecker", "parqueteur", "verkauferin", "tankstellenshop",
    "produktionsmitarbeiter", "pflegefachfrau", "pflegefachmann",
    "pflegefachperson", "fachfrau gesundheit", "fachmann gesundheit",
    "ricezionista", "centralinista", "fachmonteur", "zimmermann",
    "polymechaniker", "netzelektriker", "schlosser", "metallbauer",
    "sanitarinstallateur", "gipser", "maurer", "schreiner",
    "maler und gipser", "lagermitarbeiter", "kuchenhilfe",
    "serviceangestellte", "serviceangestellter", "raumpflegerin",
    "reinigungskraft", "hauswart", "chauffeur cat c", "lastwagenchauffeur",
    "detailhandelsfachfrau", "detailhandelsfachmann", "pflegehelferin",
    "betreuerin", "kinderbetreuerin", "kita", "logopadin", "podologin",
    "coiffeuse", "coiffeur", "aide soignante", "infirmiere", "infirmier",
    "cuisiniere", "serveuse", "femme de chambre", "agent de proprete",
    "magasinier", "menuisier", "macon", "electricien", "plombier",
    "ferblantier", "carreleur", "peintre en batiment", "mecanicien",
    "chauffeur poids lourds", "vendeuse", "educatrice", "enseignante",
    "assistante dentaire", "operatore socio sanitario", "infermiere", "cuoco",
    "cameriere", "muratore", "elettricista", "idraulico", "magazziniere",
    # ----------------------------------------------------------------------
    # **Read off the Swedish and Danish board.** The complaint was "too much
    # junk, e.g. inköpare, and too little jobs", and both halves were one
    # fault: 176 of the 199 Nordic cards were `relevance: unknown`, the bucket
    # holding the purchasers *and* the real markets seats, so they sorted
    # together. This is the half that empties it from below.
    #
    # One needle touches a positively-rated posting and is kept after reading
    # it: `indkøber` reaches `Indkøber - Trading` at a firm called Kompetent,
    # rated `adjacent` on *trading*, which there means commerce. A purchaser at
    # a trading company is a purchaser.
    #
    # **`förvaltare` is deliberately not here and must not be added.** It is a
    # property caretaker in `Teknisk förvaltare` and a portfolio manager in
    # `Ränteförvaltare till Swedbank Robur` -- the qualified compounds go on
    # `lexicon.MARKETS` and only the property ones are gated here.
    # `controller`, `analytiker` and `specialist` are absent for the reason
    # above: the wrong *job* rather than the wrong industry, so they rank.
    #
    # purchasing and procurement, which is what the reader pointed at
    "inkopare", "inkop", "inkopsansvarig", "inkopsassistent", "inkopschef",
    "operativ inkopare", "strategisk inkopare", "sortimentsansvarig",
    "upphandlare", "upphandling", "upphandlingskonsult", "kategoriansvarig",
    "indkober", "indkob",
    # property, facilities and building services -- the `förvaltare` reading
    # that is not a portfolio
    "fastighetsingenjor", "fastighetsforvaltare", "fastighetsforvaltning",
    "teknisk forvaltare", "fastighetschef", "driftstekniker",
    "ejendomsadministrator", "ejendomsservice",
    # environment, logistics and the remaining Nordic field professions
    "miljokonsult", "miljosamordnare", "miljoingenjor",
    "logistikkoordinator", "transportledare", "speditor", "lagerchef",
    "servicekoordinator", "kundeservicemedarbejder", "forsikringsradgiver",
    "skaderadgiver",
    # Town planning and landscape, whole words so they gate as the profession
    # they are. `lexicon.ENGINEERING_HEADS` reaches them through `-arkitekt`
    # as well and would reject them as engineering, which is the right verdict
    # under the wrong name; this list runs first and names them correctly.
    "landskapsarkitekt", "planarkitekt", "stadsarkitekt", "byplanarkitekt",
    "planeringsarkitekt", "indretningsarkitekt",
    # **A hotel's front office is a reception desk**, and `front office` is one
    # of the strongest words on `lexicon.MARKETS`. Removing it is not the
    # answer -- 209 titles carry it and all but these are genuine desks. The
    # *shift* word is the discriminator and it is clean: `shift leader` is 72
    # baristas and data centre crews, `receptionschef` 18 hotels, none of them
    # near finance.
    "shiftleader", "shift leader", "receptionschef", "hotel front office",
    # **The second pass, and the residue is shaped `Erfaren <trade>`.** With
    # the purchasers gone the largest remaining family was Swedish postings the
    # lists had no word for -- `Erfaren Guldsmed`, `Erfaren Kantpressare`,
    # `Erfaren växeltelefonist`.
    #
    # **The `-ingenjör` compounds are named individually and the suffix is
    # still refused**: the head would reach `Softwareingeniør`, and bare
    # `software engineer` is deliberately absent from `_SOFTWARE_SPECIALTY`
    # because a quant-dev posting calls itself one. `automationsingenjör`
    # cannot reach anything of the sort.
    "entreprenadingenjor", "processingenjor", "projektingenjor",
    "matningsingenjor", "byggnadsingenjor", "automationsingenjor",
    "elingenjor", "produktionsingenjor", "kvalitetsingenjor",
    "guldsmed", "kantpressare", "bilskadereparator", "cafepersonal",
    "vaxeltelefonist", "butiksetablerare", "energikartlaggare",
    "geokonstruktor", "beredare", "ledningssamordnare", "byggnadsantikvarie",
    "arkivarie", "projektor", "lokalvard", "kundvard",
    "beredskapssamordnare", "informationssakerhetssamordnare",
    "molekylarbiolog", "cellbiolog", "biomedicinsk analytiker", "logoped",
    "dietist",
    # Law, in the Nordic spelling. **The compounds are what escaped**: bare
    # `jurist` is on `lexicon.CORPORATE`, but it is not a `SWEDISH_HEADS` head,
    # so `Bolagsjurist` was one token nothing could see inside. The bare noun
    # is repeated so a lawyer and a lawyer's compound record the same reason.
    "jurist", "bolagsjurist", "dataskyddsjurist", "myndighetsjurist",
    "affarsjurist", "skatteradgivare",
    # ----------------------------------------------------------------------
    # **Switzerland, read off its own board the way Sweden's was.** Switzerland
    # is the hub with the widest gap between what arrives and what shows -- 28k
    # postings, 182 cards -- and unlike Denmark and Singapore it is gated by
    # *words* rather than by a taxonomy, because job-room.ch publishes bare
    # AVAM occupation codes and no labels. So the German and French occupation
    # vocabulary carries all of it, and it was a dozen trades deep.
    #
    # The residue that reached the board was `Bäcker`, `Müller`,
    # `Speditionskauffrau Seefracht`, `Responsable de Caisse`, `Agent de
    # comptoir`, `immobilienbewirtschafter:in` and `Apparel Merchandising
    # Coordinator`. Dry-run over all 295,347 live titles.
    #
    # **`Anlage` is the trap this hub hides, and it is `handel` in German.**
    # It means both *investment* and *industrial plant*, and in this corpus it
    # is overwhelmingly the second: `anlagenführer` is 212 titles and every one
    # is a machine operator, with `Toranlagen`, `Aufzugsanlagen`,
    # `Krananlagen` and `Photovoltaikanlagen` behind it. Translating
    # "investment" into German and adding the stem would have put 212 plant
    # operators on a markets list. The operator forms are gated here; nothing
    # from that family goes anywhere near `MARKETS`.
    #
    # **`sachbearbeiter` is kept despite one positive**, read by hand as the
    # rule requires: its one positively-rated hit is a permits clerk that
    # reached `adjacent` on *front office* -- the Scandic collision in German.
    "backer", "muller", "speditionskauffrau", "speditionskaufmann",
    "immobilienbewirtschafter", "immobilienbewirtschafterin",
    "immobilienbewirtschaftung", "bauleiter", "baufuhrer", "polier",
    "sachbearbeiter", "sachbearbeiterin", "kreditorensachbearbeiter",
    "kaufmann", "kauffrau", "hauswartin", "servicetechniker",
    "maschinenfuhrer", "anlagenfuhrer", "anlagefuhrer",
    "mitarbeiter verkauf", "verkaufsberater", "filialleiter",
    "merchandising", "merchandiser",
    # French-speaking Switzerland and Romandy, same reading
    "responsable de caisse", "charge de clientele", "agent de comptoir",
    "responsable qualite", "gerant", "vendeur", "caissier", "caissiere",
    "serveur", "cuisinier", "aide de cuisine", "agent de securite",
    "chauffeur livreur", "educateur", "assistant medical",
    # ----------------------------------------------------------------------
    # **Read off the Swiss board *after* the markets vocabulary went in**, the
    # only frame that could find these. `asset management` and `front office`
    # name something ordinary in German: the Federal Roads Office, a waste
    # incineration plant, property, and the Walliserhof Grand-Hotel. Ten of
    # Switzerland's 39 ranked cards. The `Shiftleader Front Office` collision
    # one language over, with the same answer -- the phrase stays on `MARKETS`
    # and the noun beside it discriminates.
    #
    # **Note what "clean" means for this batch.** The standing check asks
    # whether a needle touches a positively-rated posting, assuming those
    # ratings are right. Here they are the bug, and every needle was *chosen*
    # because it touches one. When fixing a false keep, a dry-run flagging hits
    # is the confirmation rather than the objection -- read them, do not count
    # them.
    "immobilien", "immobilier", "immobiliare", "liegenschaften",
    "nationalstrassen", "kehrichtverwertungsanlage", "entsorgung",
    "recycling", "bauprozess", "einrichter", "wohnen",
    "facility management", "gebaudetechnik", "hausdienst",
    "hotellerie", "empfang", "rezeption", "telefonie",
    # ----------------------------------------------------------------------
    # **American English, because the United States became a target geography
    # and this list had never been written against it.** The diagnosis is the
    # one the Nordics gave: 3,385 American postings sat at `relevance:
    # unknown`, the bucket that holds both the unread junk and the real desks,
    # and they sorted together. This is the half that empties it from below.
    #
    # The vocabulary is genuinely different rather than merely absent. `nurse`,
    # `medical` and `clinical` were already here and caught none of `LPN/MA/EMT`,
    # `Cardiac Sonographer`, `Clinic Assistant`, `Dietary Aide` or `Health Unit
    # Coordinator`; `janitor` caught no `Custodial Worker I`; and an American
    # television group publishes through the same ATS platforms as the trading
    # firms, so `WSMV-Station-Nashville` arrives mixed in with anchors,
    # meteorologists and multimedia journalists.
    #
    # Dry-run over all 296,096 live postings. **Exactly one candidate touched a
    # positively-rated posting and it is out**: `environmental services` reaches
    # `Equity Research Associate - Environmental Services`, an equity research
    # seat covering the sector. The aide's own title goes in instead.
    #
    # **Three more were dropped on the principle rather than the count**, all
    # three clean on the numbers today:
    #
    # - `sales lead` is the `salesperson` argument again -- the English sales
    #   words are too close to markets sales to gate on, and this list has
    #   refused `sales associate` and `sales representative` for years.
    # - `security officer` reaches `Chief Information Security Officer` seven
    #   times. A CISO is not another profession, it is a corporate function, so
    #   the reason would have been wrong even where the verdict was not.
    #   `security guard` above already covers the doorman.
    # - bare `advanced practice` reaches `Advanced Practice Wealth Banker`. The
    #   two clinical compounds are exact and reach only clinicians.
    "lpn", "emt", "cna", "sonographer", "phlebotomist", "phlebotomy",
    "radiologic", "nurse practitioner", "registered nurse", "certified nursing",
    "medical assistant", "medical technologist", "clinic assistant",
    "dietary aide", "health unit coordinator", "respiratory therapist",
    "occupational therapist", "surgical technologist", "hospitalist",
    "advanced practice provider", "advanced practice clinician", "orthopedic",
    "dental hygienist", "behavioral health", "pharmacy technician",
    "patient care", "caregiver", "case manager", "paramedic",
    # janitorial, grounds and building services
    "custodial", "custodian", "environmental services aide", "groundskeeper",
    "housekeeper", "facilities technician", "maintenance technician",
    "building engineer", "hvac",
    # broadcast newsrooms and in-house creative, which arrive through the same
    # tenants as everything else
    "art director", "creative director", "photojournalist", "meteorologist",
    "news anchor", "multimedia journalist", "news producer", "reporter",
    # retail floor, food service and residential leasing
    "cashier", "store manager", "shift supervisor", "line cook", "food service",
    "banquet", "barback", "valet", "leasing agent", "lifestyle coordinator",
    "workplace experience",
    # plant, trades and the dealership service bay
    "controls engineer", "material handler", "machine operator", "millwright",
    "tool and die", "cnc machinist", "assembler", "production supervisor",
    "welder", "service technician", "automotive technician",
    "diesel technician", "warehouse associate", "quality inspector",
    "plant manager", "field technician", "police officer",
    # campus jobs and the university's own administration
    "federal work study", "admissions representative", "adjunct faculty",
)

# Deliberately absent, each after matching something real in the corpus:
# `coach` is *Portfolio Manager/Agile Coach* and *Financial Coach*; `pilot` is
# *Paint Pilot Projects*; `librarian` is *ECAD Librarian*; `translator` is
# DBS's *Data Translator*; `interpreter` is *Parts Interpreter*. Every one of
# them is a job this project might want, under a word that looks like a trade.

# A location field that names no place, which is `unknown` and never `other`.
# Workday publishes `2 Locations` on 6,281 multi-site postings and Jobbsafari
# files 1,392 under *De nordiska länderna* -- which contains two focus hubs.
# Reading either as `other` claims we looked and found somewhere else, and the
# board then deletes it; `unknown` survives the gate, so this fails towards
# keeping.
_NO_PLACE = re.compile(
    r"^\s*(\d+\s+locations?|remote|multiple locations|various"
    r"|de nordiska l(ä|a)nderna|norden|nordics|the nordics"
    r"|europe|europa|eu|emea|global|worldwide)\s*$",
    re.IGNORECASE)

# **A national board writes the *administrative* place, and each country picks
# a different one** -- Jobindex a postcode, Jobbsafari a municipality,
# job-room.ch a town and a canton code (`Wallisellen, ZH`). 18,562 Swiss
# postings in a focus hub read as `other` before this, and 5,987 US ones read
# as elsewhere.
#
# **Neither can go in `_HUBS`**, which matches `fold(location, title)`: `IN`,
# `OR` and `DE` are English words as well as states, and `SO`, `BE` and `GE`
# are ordinary words in a title. Matched here against the **location alone**,
# anchored to the `, XX` shape an address takes.
#
# **`AR` and `NE` moved from the states to the cantons when the US became a
# focus geography, and the measurement is what moved them.** They were left off
# this list while only Switzerland was focus, on the rule that a false hit in a
# focus hub is worse than a false miss -- with both sides focus that tie-break
# is void, so the question became simply which reading is right. Counted over
# the corpus: `, AR` is 235 postings and every one is Appenzell Ausserrhoden
# (Herisau, Teufen, Walzenhausen); `, NE` is 419, of which 380 are the canton
# of Neuchâtel and 39 are Nebraska. `omaha` sits in `_HUBS` and `_HUBS` is read
# first, so the Nebraska head count survives the move.
#
# `FL` stays a state: 980 postings, of which 938 are Florida. The 42 that are
# not are Vaduz and Schaan, and those are named in the Swiss hub for the reason
# job-room.ch files them there.
_CH_CANTON = re.compile(
    r",\s*(AG|AI|AR|BL|BS|BE|FR|GE|GL|GR|JU|LU|NE|NW|OW|SG|SH|SO|SZ|TG|TI|UR|VD|VS|ZG|ZH)"
    r"\s*$"
)

# **Uppercase only, and `IN` and `DE` are deliberately absent.** Case-folding
# this pattern cost more than it bought: an ATS writes the *country* code in
# lowercase, so `, in` claimed Bengaluru for Indiana, `, de` Berlin and Mainz
# for Delaware, `, ma` Casablanca for Massachusetts and `, ar` Buenos Aires for
# Arkansas. `\b` cost the same way one step further out -- it lets a full stop
# close the match, so `Dublin, Co. Dublin, Ireland` read as Colorado 37 times.
#
# The two codes that are still wrong more often than right in *upper* case are
# out: `, IN` is 279 postings and more than half are Bangalore and Pune, `, DE`
# is 190 and more than half are Glatten, Meerane and Stuttgart. Their American
# half is reached by name instead -- `indianapolis`, `indiana`, `wilmington de`,
# `dover de`, `delaware` are all in `_HUBS`, which is read first.
_US_STATE = re.compile(
    r",\s*(A[LKZ]|C[AOT]|FL|GA|HI|I[ADL]|K[SY]|LA|M[ADEINOST]|"
    r"N[CDHJMVY]|OH|OK|OR|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY]|DC)(?![.\w])")

# **An employer's own site codes are an administrative unit too, and HKEX's
# are the whole Hong Kong Exchange.** Its Workday board writes the office, not
# the city -- `HK-CMP 6/F`, `HK-TWO ES 11/F`, `HK-TKO 5/F`, `HK-ONE ES 30/F`
# -- so all 164 postings matched no needle in `_HUBS` and fell through to
# `other`, which the board gates. That is the `Wallisellen, ZH` failure at one
# employer's scale: the place was written down and we could not read it.
#
# Matched against the **raw location** and anchored, for the same reason the
# canton and state patterns are: `hk` is two letters and `_HUBS` is matched
# against the title as well, where it would eventually catch something. The
# prefix is HKEX's own country code -- it writes `CN-Shenzhen-HyQ` and
# `UK-London` the same way, and both of those already resolve through `_HUBS`
# on the city name, so only the Hong Kong half needs this.
#
# Dry-run before it went in: **not one live posting in the corpus writes a
# location beginning `HK-`**, so the pattern can claim nothing that is already
# being read correctly.
_HK_SITE = re.compile(r"^HK-")

# **City before country.** `sweden` used to sit in the `stockholm` tuple, so
# every Swedish advertisement read Stockholm -- Kiruna and Visby included.
# Survivable while geography only ranked; not once the board drops what is out
# of area, since the label would then delete postings for being somewhere they
# are not.
#
# So a focus hub is the city plus a real commuting belt, and the rest of the
# country gets its own value, gated by default and one line in
# `web/build_data.py` from coming back. Switzerland stays national on purpose:
# the roster is national and no Swiss city dominates it the way Stockholm does.
_HUBS = {
    # The belt: municipalities of Stockholms län within about forty kilometres.
    # Södertälje (35 km, on the commuter rail) is in by the same rule that puts
    # Køge in Copenhagen's; Norrtälje (70), Nynäshamn (58) and Nykvarn (50) are
    # out. `salem` is in neither list -- 22 of its 38 postings are Salem,
    # Oregon and Winston-Salem, North Carolina.
    "stockholm": (
        "stockholm", "stockholms lan", "solna", "sundbyberg", "kista",
        "bromma", "nacka", "danderyd", "sollentuna", "taby", "huddinge",
        "jarfalla", "lidingo", "sigtuna", "arlanda", "kungsholmen",
        "sodermalm", "upplands vasby", "tyreso", "botkyrka", "haninge",
        "sodertalje", "upplands bro", "kungsangen", "varmdo", "vallentuna",
        "osteraker", "ekero", "vaxholm",
    ),
    # The belt, not the municipality. Jobindex writes a *postcode and town* --
    # `2650 Hvidovre` -- and never the word København, so 1,444 Greater
    # Copenhagen postings read as `other` and were gated off the board. These
    # are the towns that actually appeared, each dry-run: every one matches
    # Danish rows only. Same forty-kilometre rule, so Køge (39) is in and
    # Helsingør (45) is `denmark_other`.
    "copenhagen": (
        "copenhagen", "kobenhavn", "kobenhavns", "kbh", "storkobenhavn",
        "frederiksberg", "gentofte", "lyngby", "glostrup", "soborg",
        "hellerup", "ballerup", "herlev", "taastrup", "hilleroed", "hillerod",
        "roskilde", "amager",
        # inner suburbs and the S-train belt, postcodes 2000-2999
        "hvidovre", "brondby", "kastrup", "rodovre", "valby", "greve",
        "albertslund", "nordhavn", "ishoj", "horsholm", "bronshoj",
        "charlottenlund", "karlslunde", "hedehusene", "solrod", "skovlunde",
        "vanlose", "virum", "dragor", "bagsvaerd", "holte", "kokkedal",
        "vedbaek", "smorum", "naerum", "vallensbaek", "malov", "rungsted",
        "niva", "klampenborg", "skodsborg", "dyssegard", "gladsaxe",
        # North Zealand and the Køge line, still a daily commute
        "birkerod", "farum", "vaerlose", "allerod", "olstykke",
        "frederikssund", "koge",
    ),
    "amsterdam": (
        "amsterdam", "amstelveen", "schiphol", "hoofddorp", "diemen",
        "zaandam", "haarlem", "almere", "randstad",
    ),
    "switzerland": (
        "zurich", "zuerich", "geneva", "geneve", "genf", "zug", "basel",
        "bern", "berne", "lausanne", "lugano", "winterthur", "st gallen",
        "switzerland", "schweiz", "suisse", "svizzera",
        # Liechtenstein, which is not Switzerland and is filed with it here for
        # the same reason job-room.ch files it there: it is a 27th code on that
        # board, inside the customs and currency union, and a commute from
        # Sargans. Named because `FL` stays a US state code -- see `_US_STATE`.
        "vaduz", "schaan", "liechtenstein",
    ),
    "hong_kong": (
        "hong kong", "hongkong", "kowloon", "central hong kong", "quarry bay",
        "tsim sha tsui", "admiralty", "causeway bay", "wan chai",
        # Office towers the tenant names instead of the city. `One Island East`
        # is Swire's Quarry Bay tower and 190 postings give it as the whole
        # location, which read as `other` and would now be deleted.
        "one island east", "two ifc", "one ifc", "icc tower", "cheung kong",
    ),
    "singapore": ("singapore", "marina bay", "raffles place", "changi"),
    # ----------------------------------------------------------------------
    # **The United States, promoted out of `deprioritized` at the reader's
    # instruction.** It is the largest thing on this board by a distance: 876
    # postings rated `adjacent` or better against 887 for all six of the older
    # focus hubs put together, and New York alone carries 468 -- more than Hong
    # Kong, Stockholm, Amsterdam, Switzerland and Copenhagen combined.
    #
    # **It is three metros and a residual rather than one country**, which is
    # the rule the rest of this table already follows: a focus hub is a city
    # plus a real commuting belt, and the rest of the country gets its own
    # value. A single national hub would have been the `sweden` mistake at
    # continental scale -- every insurance clerk in Omaha ranking level with a
    # Jane Street desk. Measured over the corpus, the three metros hold 74% of
    # the American postings this board rates positively in 27% of its volume:
    # New York 468, Chicago 107, Boston 75, and the whole of the rest 148.
    #
    # Boston is in on that number and on what the postings *are* -- State
    # Street's model risk and quant research seats. The Bay Area (31), Texas
    # (31) and Miami (15) are not, and reading their positives is why: wealth
    # advisers, tax principals and real-estate capital markets. They sit in
    # `us_other`, which is on the board and ranks below.
    #
    # **No state name appears in a metro list.** `illinois` in the Chicago
    # tuple would file Springfield as Chicago, exactly the way `sweden` in the
    # Stockholm tuple once filed Kiruna as Stockholm. The states live in
    # `us_other` and `_residual` drops the duplicate, so `Chicago, Illinois`
    # comes out `chicago` alone. Every name below was dry-run over all 296,096
    # live postings; `manhattan` was dropped by it, matching the *Manhattan Bar*
    # at a Singapore hotel and nothing in New York the word `new york` misses.
    "new_york": (
        "new york", "nyc", "brooklyn", "bronx", "staten island", "queens ny",
        "long island", "white plains", "yonkers", "new rochelle",
        # New Jersey and lower Connecticut, named as towns for the reason
        # above: the state of New Jersey reaches Vineland and Mount Laurel,
        # which commute to Philadelphia.
        "jersey city", "newark", "hoboken", "hackensack", "short hills",
        "morris plains", "stamford", "greenwich ct",
    ),
    "chicago": (
        "chicago", "rosemont", "schaumburg", "naperville", "evanston",
        "northbrook", "skokie", "downers grove", "tinley park", "orland park",
        "buffalo grove", "oak brook", "des plaines",
    ),
    "boston": (
        "boston", "waltham", "somerville", "quincy", "brookline", "dorchester",
        "braintree", "dedham",
    ),
    # The rest of the United States: on the board and ranked below the metros,
    # which is what makes it unlike `sweden_other` and `denmark_other`. Those
    # are gated; this is not, because the country is a target now.
    #
    # **The state names carry most of it and the `, XX` codes do not reach
    # them.** 2,017 postings spell the state out -- `O'Fallon, Missouri`,
    # `Nashville, Tennessee` -- and read as `other`, which the board deletes.
    # A further 374 say only that the job is American: `Remote US`, `Remote -
    # US` and `Remote (US)` all fold to the same three tokens.
    #
    # **`georgia` was dropped after the dry-run** and it is the `Åre` lesson in
    # a new alphabet: it reaches Tbilisi and Vancouver's Georgia Street, and
    # buys nothing, because `atlanta` and `, GA` already hold the state's head
    # count. `washington` was kept -- every one of its hits is the state or the
    # District, `Conshohocken - Washington` included.
    "us_other": (
        "united states", "usa", "us remote", "remote us", "forenta staterna",
        # Every state spelled out. The focus metros' own states are here too,
        # so `Chicago, Illinois` names its state once; `_COUNTRY_WORDS` is what
        # stops that from counting as a second place.
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
        "connecticut", "delaware", "florida", "hawaii", "idaho", "illinois",
        "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
        "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
        "missouri", "montana", "nebraska", "nevada", "ohio", "oklahoma",
        "oregon", "pennsylvania", "tennessee", "texas", "utah", "vermont",
        "virginia", "washington", "wisconsin", "wyoming", "new hampshire",
        "new jersey", "new mexico", "new york", "north carolina",
        "north dakota", "rhode island", "south carolina", "south dakota",
        "west virginia", "district of columbia",
        # The cities that carry a head count of their own, plus the two that
        # `_US_STATE` stopped reaching when `, IN` and `, DE` came off it.
        "san francisco", "seattle", "austin", "dallas", "houston", "atlanta",
        "denver", "los angeles", "miami", "philadelphia", "washington dc",
        "charlotte", "phoenix", "san diego", "san jose", "minneapolis",
        "detroit", "portland", "salt lake city", "las vegas", "nashville",
        "tampa", "orlando", "jacksonville", "st louis", "kansas city",
        "cincinnati", "cleveland", "pittsburgh", "baltimore", "milwaukee",
        "indianapolis", "raleigh", "newport beach", "irvine", "san antonio",
        "sacramento", "omaha", "louisville", "memphis", "oklahoma city",
        "albuquerque", "fort worth", "des moines", "boise", "tucson",
        "bethesda", "charlottesville", "wilmington de", "dover de",
        # **Some tenants put the state *before* the city** -- `CT - Hartford`,
        # `MN - St. Paul`, `TX - Richardson` -- which no `, XX` pattern reaches,
        # so 267 postings sat unplaced and were gated as `other`.
        #
        # **A prefix pattern is not the answer and the corpus says why.** The
        # same two-letter collision is worse in that position, because `XX -
        # City` is also how those tenants write *country* - city: `IN -
        # Bengaluru`, `CO - Bogota`, `DE - Frankfurt`, `CA - Toronto`. Even
        # restricting it to codes that are not ISO country codes leaks -- `ID -
        # Jakarta` is Indonesia and `IL - Tel Aviv` is Israel. So the cities are
        # named instead, which is the `georgia` decision again: take the
        # specific handle, refuse the ambiguous rule.
        #
        # Every one dry-run over the corpus and every hit American.
        "hartford", "st paul", "saint paul", "richardson", "alpharetta",
        "spokane", "pensacola", "melville", "bellevue", "knoxville",
        "syracuse", "coral gables", "fort lauderdale", "overland park",
        "tallahassee", "west palm beach", "chanhassen", "hamden",
    ),
    # ----------------------------------------------------------------------
    # Semi-target: kept on the board, ranked below the focus hubs. The list was
    # eleven names and that was a ranking list. As a *gate* it has to be a
    # geography, so the country names and the cities that carry the head count
    # are all here.
    #
    # **`u s a` was removed with the American names**: it matched nothing, in
    # any of 296,096 postings. `U.S.A.` folds to `usa`, not to three letters.
    "deprioritized": (
        "london", "united kingdom", "uk", "england", "scotland", "edinburgh",
        "manchester", "glasgow", "birmingham", "leeds", "bristol", "cambridge",
        "germany", "deutschland", "frankfurt", "munich", "muenchen", "berlin",
        "hamburg", "dusseldorf", "stuttgart", "cologne", "koeln",
        "dubai", "abu dhabi", "united arab emirates", "uae", "difc",
        "shanghai", "beijing", "shenzhen", "hangzhou", "guangzhou", "china",
    ),
    # The right country, the wrong city. Named rather than lumped into `other`
    # so the board can say what it dropped and why, and so turning Gothenburg
    # or Aarhus back on is a one-line change rather than a lexicon edit.
    # **Sweden arrived and 16,153 of its postings read `other`**, because 28
    # names covered a country of 290 municipalities. `other` means "we read the
    # place and it was Bangalore", so under a gate it deletes them.
    #
    # The list is **Jobbsafari's own area taxonomy** -- an enumeration the
    # board publishes rather than a word list written from memory, the same
    # argument `jobs.category` exists for. Seven names were thrown out because
    # the fold makes them somebody else's word: **`Åre` folds to `are`, the ISO
    # code for the UAE, and reaches 83 Workday postings in Dubai**; `Eda` is
    # electronic design automation, `Vara` is Dubai's virtual-asset regulator,
    # `Sala` is a Venetian waiter, `Malå` is Sichuan food, `Mark` is
    # Singapore's Green Mark, `Salem` is Oregon. Anything the taxonomy does not
    # carry is not Sweden -- which is what kept `Island`, `Bangalore` and
    # `Paris` out, all three places this board advertises.
    "sweden_other": (
        "sweden", "sverige", "goteborg", "gothenburg", "malmo", "lund",
        "uppsala", "linkoping", "vasteras", "orebro", "helsingborg",
        "norrkoping", "jonkoping", "umea", "lulea", "kiruna", "kalmar",
        "boras", "visby", "sundsvall", "gavle", "vaxjo", "karlstad",
        "ostersund", "skelleftea", "halmstad", "eskilstuna",
        "aitik", "ale", "alingsas", "alvesta", "aneby", "arboga", "arjeplog",
        "arvidsjaur", "arvika", "askersund", "avesta", "bengtsfors", "berg",
        "bjurholm", "bjuv", "blekinge lan", "boden", "boliden", "bollebygd",
        "bollnas", "borgholm", "borlange", "boxholm", "bromolla", "bracke",
        "burlov", "bastad", "dalarnas lan", "dals ed", "degerfors", "dorotea",
        "eksjo", "emmaboda", "enkoping", "eslov", "essunga", "fagersta",
        "falkenberg", "falkoping", "falun", "filipstad", "finspang", "flen",
        "forshaga", "forsmark", "fargelanda", "gagnef", "garpenberg",
        "gislaved", "gnesta", "gnosjo", "gotland", "gotlands lan",
        "gringelstad", "grum", "grastorp", "gullspang", "gallivare",
        "gavleborgs lan", "gotene", "habo", "hagfors", "hallands lan",
        "hallsberg", "hallstahammar", "hammaro", "haparanda", "heby",
        "hedemora", "herrljunga", "hjo", "hofors", "holmsund", "hudiksvall",
        "hultsfred", "hylte", "hallefors", "harjedalen", "harnosand",
        "harryda", "hassleholm", "hoganas", "hogsby", "hokerum", "horby",
        "hoor", "jokkmokk", "jamtlands lan", "jonkopings lan", "jorslanda",
        "kalix", "kalmar lan", "kankberg", "karlsborg", "karlshamn",
        "karlskoga", "karlskrona", "katrineholm", "kil", "kinda", "klippan",
        "knivsta", "kramfors", "kristianstad", "kristineberglycksele",
        "kristinehamn", "krokom", "kronobergs lan", "kumla", "kungsbacka",
        "kungshamn", "kungsor", "kungalv", "kavlinge", "koping", "laholm",
        "landskrona", "laxa", "lekeberg", "leksand", "lerum", "lessebo",
        "lidkoping", "lilla edet", "lindesberg", "ljungby", "ljusdal",
        "ljusnarsberg", "lomma", "ludvika", "lycksele", "lysekil",
        "malung salen", "mariestad", "markaryd", "mellerud", "mjolby", "mora",
        "motala", "mullsjo", "munkedal", "munkfors", "malardalen", "molndal",
        "molnlycke", "monsteras", "morbylanga", "nora", "norberg",
        "nordanstig", "nordmaling", "norrbottens lan", "norrtalje", "norsjo",
        "nybro", "nykvarn", "nykoping", "nynashamn", "nassjo", "ockelbo",
        "olofstrom", "orsa", "orust", "osby", "oskarshamn", "ovanaker",
        "oxelosund", "pajala", "partille", "pello", "perstorp", "pitea",
        "ragunda", "renstrom", "robertsfors", "ronneby", "rattvik",
        "ronnskar", "sandviken", "simrishamn", "sjobo", "skara",
        "skinnskatteberg", "skoghall", "skurup", "skane lan", "skovde",
        "smedjebacken", "solleftea", "sorsele", "sotenas", "staffanstorp",
        "stenungsund", "storfors", "storuman", "strangnas", "stromstad",
        "stromsund", "sunne", "surahammar", "svalov", "svedala", "svenljunga",
        "saffle", "sater", "savsjo", "soderhamn", "soderkoping",
        "sodermanlands lan", "solvesborg", "taberg", "tanum", "tibro",
        "tidaholm", "tierp", "timmersdala", "timra", "tingsryd", "tjorn",
        "tomelilla", "torsby", "torsa", "tranemo", "tranas", "trelleborg",
        "trollhattan", "trosa", "toreboda", "uddevalla", "ulricehamn",
        "uppsala lan", "uppvidinge", "vadstena", "vaggeryd", "valdemarsvik",
        "vansbro", "varberg", "vattholma", "vellinge", "vetlanda",
        "vilhelmina", "vimmerby", "vindeln", "vingaker", "vanersborg",
        "vannas", "varmlands lan", "varnamo", "vasterbottens lan",
        "vasternorrlands lan", "vastervik", "vastmanlands lan",
        "vastra gotalands lan", "vargarda", "vaxtorp", "ydre", "ystad",
        "almhult", "alvdalen", "alvkarleby", "alvsbyn", "angelholm", "amal",
        "ange", "arjang", "asele", "astorp", "atvidaberg", "ockero",
        "odeshog", "oland", "orebro lan", "orkelljunga", "ornskoldsvik",
        "ostergotlands lan", "osthammar", "ostra goinge", "overkalix",
        "overtornea",
    ),
    # Eleven names covered a country of hundreds of towns, so **7,399 Danish
    # postings read as `other`** -- the same gate either way, but `other` means
    # "we read it and it was Bangalore", and answering "where did Denmark go?"
    # with that is a lie the board would have told on every build. Ranked by
    # volume out of the swept corpus and dry-run like the belt above; `nuuk`
    # is deliberately absent, because Greenland is not somewhere this reader
    # commutes and `other` is the honest answer for it.
    "denmark_other": (
        "denmark", "danmark", "aarhus", "arhus", "odense", "aalborg",
        "esbjerg", "kolding", "vejle", "horsens", "randers",
        "herning", "silkeborg", "slagelse", "naestved", "holbaek", "nykobing",
        "fredericia", "viborg", "svendborg", "hjorring", "frederikshavn",
        "holstebro", "ikast", "viby", "skive", "skanderborg", "hobro",
        "sonderborg", "norresundby", "brabrand", "ringsted", "thisted",
        "ringkobing", "varde", "ribe", "hedensted", "ronne", "risskov",
        "aars", "tilst", "bronderslev", "middelfart", "helsingor",
        "haderslev", "grindsted", "tonder", "hojbjerg", "grenaa", "lystrup",
        "korsor", "hammel", "abyhoj", "ebeltoft", "hasselager", "nordborg",
        "aabenraa", "stovring", "soro", "nyborg", "juelsminde", "faaborg",
        "brande", "hadsten", "karup",
    ),
    "netherlands_other": (
        "netherlands", "nederland", "the hague", "den haag", "rotterdam",
        "utrecht", "eindhoven", "groningen", "tilburg", "breda", "nijmegen",
        "arnhem", "maastricht", "leiden", "delft", "apeldoorn", "landgraaf",
        "cuijk",
    ),
}


_FOCUS_HUBS = frozenset(
    {"stockholm", "copenhagen", "amsterdam", "switzerland", "hong_kong",
     "singapore", "new_york", "chicago", "boston"}
)

# A country bucket is the *complement* of its focus hub, not a second place:
# `sweden_other` means "in Sweden and not Stockholm", so "Stockholm, Sverige"
# matching both is a contradiction.
#
# **The word that causes it is the containing region's own name, and only that
# word.** Collapsing on the bucket instead would throw away a real second city
# -- "Copenhagen, Aarhus" belongs in both -- which is the multi-location bug
# this change exists to fix, arriving by the back door. So a residual is
# dropped only when every needle it matched was the region that contains it.
#
# **The value is a set because the United States has three focus metros.**
# `us_other` is the complement of all of them at once, so `Chicago, Illinois`
# and `Boston, Massachusetts` both have to collapse -- which also means the
# region words for the US are the country's names *and* the three states, since
# a state is what contains its metro. `New York, New York` collapses the same
# way, and `Albany, New York` does not collapse but does read `new_york`; that
# over-claim is between two hubs the board both shows, where the Swedish one
# was between a hub and the gate.
#
# `deprioritized` is deliberately absent: it spans four countries and is
# nobody's complement, so a posting in Amsterdam and Frankfurt keeps both.
_RESIDUAL_OF = {
    "sweden_other": frozenset({"stockholm"}),
    "denmark_other": frozenset({"copenhagen"}),
    "netherlands_other": frozenset({"amsterdam"}),
    "us_other": frozenset({"new_york", "chicago", "boston"}),
}

_COUNTRY_WORDS = {
    "sweden_other": frozenset({"sweden", "sverige"}),
    "denmark_other": frozenset({"denmark", "danmark"}),
    "netherlands_other": frozenset({"netherlands", "nederland"}),
    "us_other": frozenset({
        "united states", "usa", "us remote", "remote us", "forenta staterna",
        "new york", "new jersey", "connecticut", "illinois", "massachusetts",
    }),
}


# Kept in step at import rather than at runtime: a residual with no country
# words would raise a KeyError on one posting in the middle of a re-tag, which
# is the worst place to find out.
assert _RESIDUAL_OF.keys() == _COUNTRY_WORDS.keys()


def _residual(found: list[tuple[str, str]], where: str) -> list[tuple[str, str]]:
    """Drop a country bucket that names nothing but the region it contains."""
    names = {value for value, _ in found}
    kept = []
    for value, evidence in found:
        if _RESIDUAL_OF.get(value, frozenset()) & names:
            towns = [
                needle
                for needle in _hits(where, _HUBS[value])
                if needle not in _COUNTRY_WORDS[value]
            ]
            if not towns:
                continue
            # `_hit` returns the first needle in the tuple's order, which is
            # the country name here; the town is what makes the bucket true.
            evidence = towns[0]
        kept.append((value, evidence))
    return kept

# Ranks the reader cannot reach from under a year of experience. `mid_3_5` is
# deliberately absent -- a three-year bar is a stretch rather than a wall, and
# `experience_floor` carries the number for anyone filtering harder. So is
# `unknown`, which is the point: the gate fires on a rank that was read, never
# on one that was missing.
#
# **`senior_6_10` came out at the reader's decision, and the Nordics are why.**
# It gated 9,914 postings, 947 in Stockholm and Copenhagen, and what it removed
# there was not leadership -- `Senior quantitative analyst within credit risk`
# at Swedbank, `Senior Engineer - Systematic Equity` at Lynx. A Nordic bank
# stamps *Senior* on a three-to-five-year grade, the argument `_NOT_HEAD_GRADE`
# already makes about `Associate Director`.
#
# The word still sets `seniority`, so it still ranks last; it no longer
# *removes*. Real leadership is untouched -- `_MANAGEMENT` catches Head of,
# Chief, Director, Manager and Team Lead by title.
_OUT_OF_REACH = frozenset({"lead", "head_or_md"})

# What the board will show. Everything else is gated -- see `_off_location` and
# the note in `web/build_data.py`. `unknown` is deliberately in: a posting that
# never stated a place is not a posting somewhere else.
BOARD_HUBS = _FOCUS_HUBS | {"us_other", "deprioritized", "unknown"}

# The exclusion reasons that *remove* a posting rather than ranking it.
# Everything else in `job_tags` ranks.
#
# **One definition, because two consumers.** `web/build_data.py` decides what
# reaches the board with it and `labels.py` decides what is worth a person's
# hour, and those must agree -- the sheet went on offering VP roles in Kiruna
# after the board had stopped showing them.
#
# Deleting a line here puts those postings back on the next build with no
# re-tag: the tags are written either way.
GATES = {
    "off_industry": "another profession entirely",
    "off_location": "outside the target and semi-target geography",
    "out_of_reach": "a rank unreachable from under a year of experience",
    # The only gate that removes a posting whose *relevance* is `relevant`.
    # A compulsory doctorate cannot be acquired between now and the
    # application, so the fit does not matter -- see where it is set, for why
    # this is a gate rather than a rejection.
    "phd_required": "a doctorate the reader does not have",
}

# --------------------------------------------------------------------------
# What language the advertisement is written in
# --------------------------------------------------------------------------
#
# It earns its place twice: it routes the lexicon, and it is itself a signal --
# a Swedish-language posting at a Stockholm firm is a local hire and an English
# one at the same firm is often the international desk. It is also what keeps a
# French production-line advertisement off a hand-labelling sheet.
#
# **This cannot use `fold`.** `fold` strips every character outside `a-z0-9+#`,
# so "är" becomes "r" and "och" survives but "från" does not -- and the whole
# method rests on those function words. Tokens keep their diacritics here.
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# Function words, which is what makes this work on a job advertisement: the
# content words are loan words and product names in every language, and
# "Python" and "SQL" are not evidence of anything.
_STOPWORDS = {
    "en": frozenset("the and of to in for with you we will are that this our your"
                    " have as be on at is or from by an".split()),
    "sv": frozenset("och att för med som är vi du det en ett på av till har inte"
                    " om dig vår våra eller från hos samt kommer arbeta".split()),
    "da": frozenset("og at for med som er vi du det en et på af til har ikke om"
                    " dig vores eller fra hos samt".split()),
    "no": frozenset("og for med som er vi du det en et på av til har ikke om deg"
                    " vår eller fra hos".split()),
    "de": frozenset("und der die das für mit als sie wir ein eine ist zu im von"
                    " den dem auf bei nicht oder auch werden".split()),
    "fr": frozenset("et le la les des pour avec vous nous un une est de du dans"
                    " sur au aux par ou qui que".split()),
    "nl": frozenset("en de het een voor met als je we is van op aan bij niet of"
                    " ook worden onze zijn".split()),
    "es": frozenset("y el la los las para con usted nosotros un una es de del en"
                    " por que su como".split()),
    "it": frozenset("e il la i le per con noi un una è di del in su che come"
                    " sono".split()),
    "pt": frozenset("e o a os as para com um uma é de do da em por que ou como"
                    " são".split()),
    "fi": frozenset("ja on ei että sekä kanssa me sinä tai kuin voit työ".split()),
}

# Inverted, so scoring is one pass over the tokens rather than one per language.
def _stopword_languages() -> dict[str, tuple[str, ...]]:
    index: dict[str, tuple[str, ...]] = {}
    for code, words in _STOPWORDS.items():
        for word in words:
            index[word] = index.get(word, ()) + (code,)
    return index


_STOPWORD_LANGUAGES = _stopword_languages()

# Han, kana and Hangul. A script is decisive where a stopword list is not.
_CJK = re.compile(r"[぀-ヿ一-鿿가-힯]")

# Below this the answer is `unknown`, not a guess. 81% of this corpus is a
# title and a location -- six words, often none of them function words -- and
# `unknown` is the honest reading of six words. Guessing instead would put a
# confident wrong language on four postings in five.
MIN_STOPWORDS = 4


def posting_language(*parts: str | None) -> tuple[str, str | None]:
    """(language, evidence) for one advertisement.

    Scored by how many of each language's function words appear, because
    `unknown` has to stay reachable: the alternative is picking whichever
    language scored one, which on a six-word title is noise.
    """
    text = " ".join(part for part in parts if part)
    if not text:
        return "unknown", None
    text = _TAGS.sub(" ", text)[:20_000]

    # A script beats a word list, but only when it is carrying the sentence --
    # `Land Acquisition Manager, Data Center アクイジション` is an English title
    # with a Japanese fragment glued on the end. Counting letters is the
    # expensive half and is only needed when there is CJK to weigh against it.
    cjk = len(_CJK.findall(text))
    if cjk:
        letters = sum(1 for character in text if character.isalpha())
        if letters and cjk / letters > 0.30:
            return "cjk", f"{cjk} CJK characters"

    tokens = _WORD.findall(text.casefold())
    if not tokens:
        return "unknown", None
    scores = Counter()
    for token, count in Counter(tokens).items():
        for code in _STOPWORD_LANGUAGES.get(token, ()):
            scores[code] += count
    best = max(_STOPWORDS, key=lambda code: (scores[code], code == "en"))
    if scores[best] < MIN_STOPWORDS:
        return "unknown", None
    hits = sorted(set(tokens) & _STOPWORDS[best])[:4]
    return best, f"{scores[best]}x {', '.join(hits)}"


# Exclusions safe to read out of a body. Everything absent from this set is
# title-only, because it is ordinary job-specification language wherever else
# it appears -- *communications*, *marketing*, *payroll*. These are not: no
# quant posting mentions an actuary, a blockchain or an FPGA in passing.
_BODY_SAFE_EXCLUSIONS = frozenset(
    {"actuarial", "insurance_pricing", "insurance_ops", "crypto_web3", "heavy_systems"}
)

# Distance from the user's centre, which is modelling and research. These turn
# a `role_class` into a `relevance` and are separate from it on purpose: the
# class says which *direction* a posting lies in and the relevance says how
# far. One scale carrying both made `adjacent` mean two opposite things in the
# first hand-labelled sample. Anything in neither set is at the centre.
_NEAR = frozenset({"trading", "quant_dev", "risk"})
_FAR = frozenset({"operations", "engineering"})


def _markets(row, body: str) -> str | None:
    """Any word placing this posting in financial markets at all, or None.

    **The second half of a two-sided test.** A weak positive on its own is not
    evidence: `Data Scientist` is a quant hire at a systematic fund and a
    growth-analytics hire at a payments company, and the corpus contains both.
    `judge` already reasons this way about engineering titles; the same rule
    was missing everywhere else, so a `Computational Chemist` whose body says
    "model validation" once came back as quant work.

    Read from the role first and the body second, and `MARKETS` is banned from
    holding ordinary English for exactly this reason -- see `lexicon`.
    """
    role = lexicon.normalize(f"{row['title'] or ''} {_field(row, 'department') or ''}")
    return (
        lexicon.first(role, lexicon.MARKETS)
        or lexicon.first(role, lexicon.TITLE_ANCHOR)
        or lexicon.first(lexicon.normalize(body), lexicon.MARKETS)
    )


def _class_of(role: tuple[str, str] | None) -> str:
    return role[0] if role else "unknown"


def _relevance_of(role: tuple[str, str] | None) -> str:
    """Relevance for a posting whose title is already known to be quant.

    An unresolved class returns `relevant` rather than something safer. The
    title has already said *quantitative* by the time this is called, and the
    asymmetry this project is built on points one way: under-rating a real
    opening costs the opening, over-rating one costs a few seconds of reading.

    **All trading seats sit here at `less_relevant`, and splitting them by
    `trading_style` was tried and measured and reverted.** It looked
    well-evidenced -- `Quantitative Trader` labelled `relevant`, `Experienced
    FX/Forex Trader` and `Digital Assets Trader` labelled `adjacent`, against
    one bucket saying `less_relevant` to all three -- and scoring the whole
    sheet rather than those three rows showed it gains **one row out of
    eighty**, because it silently broke two that had agreed.

    The sheet contradicts itself on exactly this axis, which is the real
    finding. `Algorithmic Trader` ("trading job but with focus on quant
    strategies") is `less_relevant` and `Quantitative Trader` ("very
    relevant, only downside is trading role") is `relevant` -- the same
    category, two rungs. At one firm, `Graduate Trader` is `less_relevant`
    while `Digital Assets Trader` is `adjacent`. A rank drawn from that is
    fitted to labeller noise, and it moved 194 postings across the corpus to
    buy 1.25% on the fixture.

    `trading_style` still records the fact, which is what it is for: it is
    filterable, and it does not pretend to imply a rank the evidence does not
    support.
    """
    name = _class_of(role)
    if name in _FAR:
        return "adjacent"
    if name in _NEAR:
        return "less_relevant"
    return "relevant"


@dataclass(frozen=True, slots=True)
class Tag:
    ats: str
    token: str
    job_id: str
    dimension: str
    value: str
    confidence: str
    evidence: str | None


def _first(mapping: dict[str, tuple[str, ...]], text: str) -> tuple[str, str] | None:
    """First bucket whose lexicon hits, in the mapping's own order.

    Order is the priority: `head_or_md` before `junior_0_2`, `hardware` before
    `systems`. A dict preserves it, so the lexicon reads as the ladder it is.
    """
    for value, needles in mapping.items():
        found = _hit(text, needles)
        if found:
            return value, found
    return None


def _every(mapping: dict[str, tuple[str, ...]], text: str) -> list[tuple[str, str]]:
    """Every bucket that hits -- for the dimensions that are multi-valued."""
    return [(v, f) for v, needles in mapping.items() if (f := _hit(text, needles))]


def _field(row, name: str):
    """One column, for a row that may predate it.

    `tag_posting` takes both a `sqlite3.Row` and a plain dict -- the tests use
    dicts -- and neither raises the same way for a missing key. A column added
    after a caller was written must read as absent, not as a crash.
    """
    try:
        return row[name]
    except (KeyError, IndexError):
        return None


def tag_posting(row: sqlite3.Row) -> list[Tag]:
    """Every tag for one posting. Never returns an empty list.

    A posting nothing matched still carries `unknown` in every dimension, so
    "not looked at" and "looked at, nothing found" stay different facts.
    """
    body = row["description"] or ""
    # A body was read, so its tags are evidence. A title alone is a guess that
    # happens to be usually right, which is what `weak` has always meant here.
    grade = "strong" if len(body) > 200 else "weak"

    key = (row["ats"], row["token"], row["job_id"])
    tags: list[Tag] = []

    def add(dimension: str, value: str, evidence: str | None, confidence: str = "") -> None:
        tags.append(Tag(*key, dimension, value, confidence or grade, evidence))

    # **The title decides what the role is; the body decides everything else.**
    # Body text is boilerplate on that question -- "strong quantitative skills"
    # is in the description of an insurance accounting job, and every bank's
    # about-us names market and credit risk.
    #
    # This is not classifying on the title alone: a title carrying no signal
    # falls through to the body, and seniority, gates, languages and asset
    # class are read from the body throughout. It is the title winning where
    # the two disagree about what the job *is*.
    #
    # Each field is folded once and the combinations composed, because folding
    # a 200 KB description twice was the largest cost left in a re-tag.
    just_title = fold(row["title"])
    just_body = fold(body)
    department = fold(row["department"])
    title = _joined(just_title, department)
    text = _joined(just_title, just_body, department)
    where = _joined(fold(row["location"]), just_title)

    # Stage one, before anything else looks at this posting. A hospital hiring
    # a statistician is still a hospital, so this outranks a quant title
    # rather than competing with it -- that is what makes it a gate and not
    # another exclusion.
    category = _field(row, "category")
    trade = _hit(title, _OFF_INDUSTRY)
    if category in _OFF_INDUSTRY_FIELDS:
        off_industry = f"field {category!r}"
    elif mcf := _mcf_off_industry(category):
        off_industry = mcf
    elif danish := _jobindex_off_industry(category):
        off_industry = danish
    elif trade:
        off_industry = f"title {trade!r}"
    elif compounded_trade := _compound(just_title, _TRADE_HEADS_INFLECTED):
        # `Elsäljare` and `Fältsäljare` are one token each, so no needle sees
        # them. Read from the title alone, never the department: a
        # `Säljarstöd` department on a markets posting is the firm's org chart.
        off_industry = f"title {compounded_trade!r}"
    else:
        off_industry = None

    # Exclusions are read from the **title**, and from the body only for the
    # handful of words that are never boilerplate. A Schonfeld quant posting
    # was tagged `support_function` on "maintain strong stakeholder
    # communications" -- a sentence in every job specification ever written.
    exclusions = _every(_EXCLUSION, title)
    named = {value for value, _ in exclusions}
    exclusions += [
        (value, evidence)
        for value, evidence in _every(_EXCLUSION, just_body)
        if value not in named and value in _BODY_SAFE_EXCLUSIONS
    ]
    # Which of them the *title* said, because one of the two soft categories
    # is read differently depending on where it appeared -- see `hard` below.
    from_title = named
    # The three categories that rank instead of rejecting, and each for its own
    # reason.
    #
    # **`heavy_systems` reads differently in a title and a body, and both
    # halves are load-bearing.** In a *body* it must not reject: `fpga` in a
    # paragraph about the stack was removing 295 postings, `Senior Software
    # Engineer, C++` at Flow Traders and `Low-Latency Engineer` at **Jane
    # Street** among them. In a *title* it must: `Junior FPGA Engineer` at
    # Eagle Seven is a hand rejection whose note reads "electronics work". So
    # `hard` below keeps it only when the title said it.
    #
    # **`crypto_web3` is the asymmetric half**: soft here so it cannot outrank
    # a weak positive, hard below, because crypto is on the exclude list
    # outright.
    #
    # **`discretionary_investing` ranks at the reader's decision**, overriding
    # a hand sheet that rejected nine such rows in a row: a markets seat at a
    # markets firm belongs on the board below the quant work rather than off
    # it. It also had a plain defect -- its own comment says "title only" while
    # `title` here carries the department, so `Rates Sales - SEK Focus` was
    # rejected on `investment banking`, the desk's name and not the job's.
    # **Whenever a needle list says "title only", check what text it is handed.**
    # Re-matched against `just_title` below, and kept out of `hard` entirely.
    SOFT = ("crypto_web3", "heavy_systems", "discretionary_investing")
    exclusions = [
        (value, evidence) for value, evidence in exclusions
        if value != "discretionary_investing"
        or _hit(just_title, _EXCLUSION["discretionary_investing"])
    ]
    rejecting = [v for v, _ in exclusions if v not in SOFT]
    hard = [
        value for value, _ in exclusions
        # Never hard, wherever it was found: it ranks now. See `SOFT` above.
        if value != "discretionary_investing"
        and (value != "heavy_systems" or value in from_title)
    ]
    # Two grades of core needle, because a desk word qualifies one and not the
    # other. `_QUANT_CORE` is unambiguous -- nothing called *quantitative* or
    # *statistical arbitrage* is an ops role. `_QUANT_CORE_TITLE` names a
    # *domain*: "Credit Risk Quant" is quant work and "Credit Risk Operations
    # (Debt Collections)" is a collections job, and only the qualifier tells
    # them apart. That one reached the shortlist as `apply_now`.
    certain = _hit(title, _QUANT_CORE)
    domain_only = _hit(title, _QUANT_CORE_TITLE)
    core = certain or domain_only
    adjacent = _hit(title, _QUANT_ADJACENT)
    # **From the job title alone, never the department.** `Senior Trading
    # Associate` sits in a department called *Trading Operations* and was
    # rejected as desk support -- the first false rejection the hand sheet
    # found. A department is nothing but the desk's name.
    desk = _hit(just_title, _DESK_ADJACENT)

    # A management title outranks a weak positive, the way an exclusion does:
    # `Director of Trading` and `Product Manager - B2C Credit` reached
    # `adjacent` on one ordinary word while announcing that somebody else does
    # the work. An unambiguous quant word still wins -- `Head of Quantitative
    # Research` is a quant role, and its *seniority* says it is out of reach.
    #
    # Title alone, for the same reason as `desk`: `Associate - Fund Governance`
    # sits in a department called *Director Services*, and a department is not
    # a grade.
    #
    # **A student rung outranks a management word**, because that is the grade
    # the title states about the applicant. Nordea's `Student Client Credit
    # Manager to Stockholm` was rejected on *manager*, which there names the
    # book rather than the reports. The 95 titles carrying both are mostly
    # Greystar's `Student Living` brand, where *student* is the tenant -- and
    # those never depended on this rule, `student living` being `_OFF_INDUSTRY`.
    student_rung = lexicon.first(lexicon.normalize(row["title"]), lexicon.INTERN_TITLE)
    management = (
        _hit(just_title, _MANAGEMENT)
        if not (_hit(just_title, _NOT_MANAGEMENT) or student_rung) else None
    )

    # A software-specialty title outranks a weak positive for the same reason a
    # management title does: the title has said what the job is, and the
    # quant-sounding word beside it names the system rather than the work.
    # Title alone, like `desk` and `management`. See `_SOFTWARE_SPECIALTY`.
    software = _hit(just_title, _SOFTWARE_SPECIALTY)

    # One value, and from the title first. `_ROLE_CLASS` replaced the
    # multi-valued `role_family` because seven values is a word count rather
    # than a classification, and its order is the priority: `operations`
    # before `trading` so "Trading Operations Analyst" is operations, and
    # `quant_dev` before `quant_research` so a title naming both lands on the
    # building half. Reading the title first is what makes that order mean
    # anything -- over a long body every class matches something.
    title_role = _first(_ROLE_CLASS, title)
    role = title_role or _first(_ROLE_CLASS, text)
    add("role_class", role[0] if role else "unknown", f"{role[1]!r}" if role else None)

    # **Most trading postings are not quant trading**, and the difference is
    # one word in the title -- so the split is its own dimension rather than a
    # rank. Feeding it into `_relevance_of` looked obviously right and measured
    # at one row out of eighty; see that function for why the sheet cannot
    # settle it.
    #
    # Title alone, and the *seat* rather than the word. `role_class` falls back
    # to the body, which over a Kraken posting files SOX auditors as trading,
    # and `_ROLE_CLASS["trading"]` includes bare *trading* -- a department's
    # name, which made `Backend Engineer - Trading & Asset Optimization` a pure
    # trader. Only the nouns for the job itself count here.
    seat = _hit(title, _TRADER_SEAT)
    if seat:
        add("trading_style", "quant" if certain else "pure",
            f"{seat!r}" + (f" qualified by {certain!r}" if certain else ", no quant word"))
    else:
        add("trading_style", "unstated", None)

    # Where the seat is. Read from the whole text because a title almost never
    # says it, and `front_office` wins inside `_DESK` so an incidental mention
    # of trade lifecycle on a trading-floor posting does not file it as ops.
    office = _first(_DESK, text)
    add("desk", office[0] if office else "unstated",
        f"{office[1]!r}" if office else None)
    # Only a **body** may demote on desk. A title naming both -- `Quantitative
    # Researcher, Trading Operations` -- is a researcher embedded in the ops
    # org, and the existing rule that a quant title outranks a desk word is
    # right about it. What that rule cannot see is a title saying nothing and
    # a body describing reconciliations all the way down.
    seat = _first(_DESK, just_body)
    back = seat is not None and seat[0] in ("middle_office", "back_office")

    # Four buckets, ordered by distance from the user's centre rather than by
    # job family -- `role_class` already records the family, and a relevance
    # scale that also encodes direction ends up meaning two things at once.
    # That is exactly what went wrong with the old three-bucket scale: the
    # same `adjacent` value was used for "a quant dev role, less relevant to
    # me" and "very close to what I want", in adjacent rows of the same
    # hand-labelled sample.
    #
    #   relevant       the output is research, modelling or signal work
    #   less_relevant  real quant work, but the day job is trading, building
    #                  or risk rather than research
    #   adjacent       a markets firm and a quantitative title, but the seat
    #                  is operational or the signal is weak
    #   rejected       the exclude list
    if off_industry:
        # First branch, so nothing below can talk it out of this. A posting
        # the source itself files under healthcare does not become a quant
        # role because its body says "analys".
        add("relevance", "rejected", f"off industry: {off_industry}")
    elif desk and not core:
        # "Trading Operations Engineer" is not a trading role, and neither is
        # "Campus Recruiter" filed under a Trading department.
        add("relevance", "rejected", f"desk support: {desk!r}")
    elif desk and not certain:
        # A desk word beside a domain word demotes, it does not reject. A
        # missed posting is the expensive failure here, so `Algorithmic Sales
        # Trader` stays readable at a lower rank rather than disappearing.
        add("relevance", "adjacent", f"{domain_only!r} qualified by {desk!r}")
    elif management and not certain:
        add("relevance", "rejected", f"management title: {management!r}")
    elif software and not certain and not _hit(just_body, lexicon.QUANT_MARKETS_BODY):
        # The specialty is the job. `Senior DevOps Engineer - Trading
        # Platforms` and `Cloud Engineer` both reached the board on a markets
        # word that belongs to the platform, and both were rejected by hand.
        #
        # A body naming markets *activity* still holds it open, which is the
        # same exemption `lexicon.judge` gives a named occupation and it is
        # load-bearing: `tests/test_tagging.py` pins a `Cloud Engineer` at a
        # firm running *statistical arbitrage* reaching `adjacent`, and that
        # is a real posting shape rather than a hypothetical. Nothing writes
        # *statistical arbitrage* about a platform it merely hosts.
        add("relevance", "rejected", f"software title: {software!r}")
    elif core and back:
        # The title says quant and the body describes the middle office.
        # `Quantitative Trading Associate` is the standing example: market-hours
        # oversight, runbooks, incident response and position reconciliation,
        # under a title that reads like a seat on the desk.
        add("relevance", "adjacent", f"title {core!r}, but {seat[0]}")
    elif core:
        add("relevance", _relevance_of(role), f"title {core!r}, {_class_of(role)}")
    elif rejecting:
        # Ahead of `adjacent`, because an exclusion outranks a weak positive:
        # "Actuarial Pricing Analyst" matched *pricing analyst* and came back
        # adjacent, and actuarial work is on the exclude list outright.
        add("relevance", "rejected", f"{rejecting[0]}, no quant signal in title")
    elif adjacent and _markets(row, body):
        add("relevance", "adjacent", f"title {adjacent!r}, {_markets(row, body)!r}")
    elif (found := _hits(just_body, _QUANT_CORE_BODY)) and (
        len(found) >= 2 or _markets(row, body)
    ):
        # Nothing in the title said anything, so the body is all there is --
        # and **one phrase in a body is not a quant role.** `Data Management
        # Analyst - Data Governance` says "model validation" once, the way
        # every governance document does, and came back as research work. A
        # second distinct phrase is what makes it evidence, the corroboration
        # rule `domains.py` uses one layer down.
        #
        # **Which phrases are read matters as much as how many.** This counted
        # bare `quantitative` until the hand sheet caught it -- the one word
        # every employer writes about every role -- so `_QUANT_CORE_BODY`
        # drops the adjectives.
        if len(found) >= 2:
            add("relevance", _relevance_of(role),
                f"body only {found[0]!r} + {found[1]!r}", "weak")
        else:
            # One phrase, but a markets word to corroborate it -- see the
            # branch condition. Without one this never runs at all, and the
            # posting falls through to `judge` below, which is where a
            # computational chemist saying "model validation" belongs.
            add("relevance", "adjacent",
                f"body only {found[0]!r}, once, at {_markets(row, body)!r}", "weak")
    elif hard:
        # `hard`, not `exclusions`: see where it is built. A body mentioning
        # FPGA is the one exclusion that may not remove a posting.
        add("relevance", "rejected", f"{hard[0]}")
    elif (call := lexicon.judge(row["title"], row["department"], body)).verdict == "reject":
        # **The last word on relevance.** `lexicon.judge` carries the long
        # occupation lists -- wealth advisers, counsel, named trades -- where
        # `_EXCLUSION` above carries seven categories, so a `Wealth Advisor`
        # fell through both and was reported `unknown`: "nothing looked at
        # this", when three rules had.
        #
        # It runs **last on purpose**: it can only convert an `unknown`, never
        # overturn a positive, so it cannot manufacture a false rejection in
        # the rows that matter.
        add("relevance", "rejected", f"{call.reason}: {call.evidence or 'no signal'}")
    elif desk_named := (
        lexicon.first(
            lexicon.normalize(f"{row['title'] or ''} {_field(row, 'department') or ''}"),
            lexicon.MARKETS,
        )
        # **An investing title is a markets title.** Stopping a rejection is
        # not the same as conferring a reading: when
        # `discretionary_investing` came off the reject list, 201 of the 342
        # postings that reached the board arrived at `relevance: unknown` and
        # sorted to the bottom with the purchasers -- `Investment Analyst,
        # Public Equity` ranking below `Bäcker`. The category only fires on a
        # title naming private equity, wealth or asset management, so by then
        # the posting has placed itself in markets as firmly as `MARKETS` does.
        or next((f"investing title: {e}" for v, e in exclusions
                 if v == "discretionary_investing"), None)
    ):
        # **A title naming a markets desk is not a posting nothing looked at.**
        # `Commodities Sales to FICC Markets`, `Market Data Specialist` and
        # `APO to Group Treasury` all came back `unknown` -- the same verdict
        # as `Inköpare för UBW Inköp support`, sorted into the same block. That
        # is what "too much junk and too little jobs" is: one bucket holding
        # everything the tagger could not read.
        #
        # It runs **last, after `judge`**, which is what makes it safe: it can
        # only convert an `unknown`, so it cannot rescue a wealth adviser.
        # `adjacent` and no better, because a markets word says *where* the
        # posting is and never what the work is -- `_fit` caps it at
        # `plausible`. Title and department only; a body naming markets is the
        # employer describing itself.
        add("relevance", "adjacent", f"markets title {desk_named!r}", "weak")
    else:
        add("relevance", "unknown", None)

    # Title first, body only as a fallback graded `weak`. Every Schonfeld
    # posting listed `rates`, because the "Who We Are" paragraph names the
    # firm's four strategies -- the employer, not the desk. The body reading is
    # kept rather than dropped, since for a posting with no title signal it is
    # the only reading there is; it just no longer claims to be evidence.
    named_assets = _every(_ASSET_CLASS, title)
    for value, evidence in named_assets:
        add("asset_class", value, f"title {evidence!r}")
    if not named_assets:
        from_body = _every(_ASSET_CLASS, text)
        for value, evidence in from_body:
            add("asset_class", value, f"body {evidence!r}", "weak")
        if not from_body:
            add("asset_class", "unstated", None)

    gates: set[str] = set()
    for dimension, mapping in (("horizon", _HORIZON), ("hard_gates", _HARD_GATES)):
        found = _every(mapping, text)
        if dimension == "hard_gates" and _hit(text, _PHD_NOT_REQUIRED):
            # " no phd required " contains " phd required ", so a posting
            # saying the opposite of the gate would otherwise trip it.
            found = [(v, e) for v, e in found if v != "phd_required"]
        for value, evidence in found:
            add(dimension, value, f"{evidence!r}")
            if dimension == "hard_gates":
                gates.add(value)
        if not found:
            add(dimension, "unknown", None)

    # **A compulsory doctorate is an eligibility fact, and it gates.** Two
    # hand-labelled rows read *"perfect fit - but has hard requirement of
    # phd"*, and *perfect fit* is the half that decides where it belongs: the
    # relevance stays `relevant`, because saying otherwise would put an
    # eligibility fact on a scale that measures subject matter. Same call as
    # `student_intern` leaving the seniority ladder.
    #
    # So it comes off the *board* rather than out of the *verdict*: the row
    # stays in `jobs`, the tag keeps its evidence, and one line in `GATES` puts
    # it back with no re-tag.
    if "phd_required" in gates:
        add("exclusion_reason", "phd_required",
            _hit(text, _HARD_GATES["phd_required"]) or "doctorate compulsory")

    # A soft filter and never a gate: it caps the fit one notch rather than
    # rejecting, because a posting wanting Dutch is still worth seeing. English
    # and Swedish are deliberately not in `_SPOKEN_REQUIRED` -- the user has
    # both, and the old `local_language_required` gate flagged "flytande
    # svenska" on Stockholm postings as though it were an obstacle.
    required = _every(_SPOKEN_REQUIRED, text)
    for value, evidence in required:
        add("spoken_language", value, f"{evidence!r}")
    if not required:
        add("spoken_language", "none", None)

    # What the advertisement is *written* in, which is a different fact from
    # what it *demands* -- a Stockholm firm advertising in English is usually
    # the international desk.
    written, why = posting_language(row["title"], body, row["department"])
    add("posting_language", written, why)

    # **The rank is in the title**, for the same reason relevance is. In a body
    # every authority word is furniture: a *partner* in Schonfeld's diversity
    # paragraph made an internship a `head_or_md` posting and moved it off the
    # shortlist. Losing a "Senior" mentioned only in a body costs an
    # over-rating; inventing a managing director costs the posting.
    #
    # The body reaches rank through **one door**, an explicit years figure --
    # see `_YEARS`. The student gate was the second and is closed: being a
    # student is `hard_gates: student_only`, not a grade.
    #
    # **`just_title`, not `title`.** The code passed `fold(title, department)`
    # here for a long time, which went unnoticed while the needles were phrases
    # like `head of` that a department rarely carries. Bare `director` is not
    # one of those -- `Associate - Fund Governance` sits in a department called
    # *Director Services*.
    rank = _first(_SENIORITY, just_title)
    if rank and rank[0] == "head_or_md" and _hit(just_title, _NOT_HEAD_GRADE):
        # The officer word belongs to a phrase that is not an officer grade.
        # Re-read the ladder with that rung out of the way -- `Associate
        # Director, EQD Quant` is a `senior_6_10` hire and `Art Director` is
        # not on this ladder at all.
        rank = _first(_BELOW_HEAD, just_title)

    # The one thing a body says about rank that beats the title, and it is a
    # number rather than a word. Both hand-labelled disagreements were this:
    # `Quantitative Trading Associate` reads junior on "associate" and asks
    # for "3+ years"; `Quantitative Research / Developer - Intern` read intern
    # and asks for "2-3 years". A grade word describes the ladder, a years
    # figure states the bar, and where they disagree the bar is the fact.
    floor = experience_floor(text)
    add("experience_floor", str(floor) if floor is not None else "unstated",
        f"{floor} years demanded" if floor is not None else None)

    named = rank[0] if rank else "unknown"
    if floor is not None and named in _FLOOR_DECIDES:
        by_floor = next(value for lower, value in _FLOOR_RANK if floor >= lower)
        # Promote only. See `_LADDER`: a number in a body is the posting's own
        # bar when the title under-sells itself, and is noise when it
        # contradicts a grade word the title actually carries.
        if named in _LADDER and _LADDER.index(by_floor) <= _LADDER.index(named):
            seniority_value = named
            add("seniority", seniority_value,
                f"{rank[1]!r}, over a floor of {floor} years")
        else:
            evidence = f"{floor} years demanded"
            if by_floor != named and rank:
                evidence += f", over title {rank[1]!r}"
            seniority_value = by_floor
            add("seniority", seniority_value, evidence)
    else:
        seniority_value = named
        add("seniority", seniority_value, f"{rank[1]!r}" if rank else None)

    for dimension, mapping in (("code_depth", _CODE_DEPTH), ("contract", _CONTRACT)):
        found = _first(mapping, text)
        add(dimension, found[0] if found else "unknown", f"{found[1]!r}" if found else None)

    for language in _LANGUAGES:
        if f" {language} " in text:
            add("language", language, None)

    for value, evidence in exclusions:
        add("exclusion_reason", value, f"{evidence!r}")
    if off_industry:
        # The first of three exclusions the board acts on by removing rather
        # than ranking, each recorded with the evidence that decided it --
        # `list --exclude off_industry` is how you audit what a gate ate.
        add("exclusion_reason", "off_industry", off_industry)

    # **A rank nobody reaches from under a year of experience.** Title only,
    # like `seniority`, and gated on a *positive* reading: a title carrying no
    # grade word comes back `unknown` and stays on the board. **A gate must
    # fire on evidence, never on the absence of it** -- that asymmetry is what
    # stops a widened lexicon quietly emptying the page.
    out_of_reach = None
    if management:
        out_of_reach = f"management title: {management!r}"
    elif not student_rung and (compounded := _compound_manager(just_title)):
        # Same veto as `management` above, and it has to be repeated here
        # because this branch reads the compound rather than the word list:
        # `Studentmedarbetare till logistikchefen` is a student post beside a
        # manager, not a manager.
        out_of_reach = f"management title: {compounded!r}"
    elif seniority_value in _OUT_OF_REACH:
        out_of_reach = f"seniority: {seniority_value}"
    if out_of_reach:
        add("exclusion_reason", "out_of_reach", out_of_reach)

    # `other` and `unknown` are different facts, and the difference is the
    # whole discipline: `other` is a place we read and it was Bangalore,
    # `unknown` is a posting naming no place. Only the first is gated.
    #
    # **Every place the posting names, not the first one.** A seat open in
    # Amsterdam *and* London is one row and two chances for the reader, so
    # `hub` is multi-valued and `off_location` fires only when *none* of the
    # places is somewhere they would go.
    places = _residual(_every(_HUBS, where), where)
    raw = (row["location"] or "").strip()
    if places:
        hubs = [value for value, _ in places]
        for value, evidence in places:
            add("hub", value, f"{evidence!r}", "strong")
    elif canton := _CH_CANTON.search(raw):
        hubs = ["switzerland"]
        add("hub", "switzerland", f"canton {canton.group(1).upper()!r}", "strong")
    elif state := _US_STATE.search(raw):
        hubs = ["us_other"]
        add("hub", "us_other", f"us state {state.group(1).upper()!r}", "strong")
    elif _HK_SITE.match(raw):
        hubs = ["hong_kong"]
        add("hub", "hong_kong", f"site code {raw[:20]!r}", "strong")
    elif raw and not _NO_PLACE.match(raw):
        hubs = ["other"]
        add("hub", "other", f"{raw[:40]!r}", "strong")
    else:
        # Either no location at all, or one that names no place -- Workday's
        # `2 Locations`, a bare `Remote`. Both are "we do not know", and the
        # board keeps `unknown` while it drops `other`.
        hubs = ["unknown"]
        add("hub", "unknown", f"{raw[:40]!r}" if raw else None, "strong")

    # **Geography gates the board, at the reader's instruction, and this is the
    # one departure from "geography ranks, it never gates".** That rule is
    # about the *universe* and is unchanged: the row keeps its place in `jobs`
    # and re-running rebuilds the verdict. What changed is the board -- a job
    # in Kiruna or Paris is not one this reader will take.
    #
    # It is why `_HUBS` had to become city-precise first: a gate on a label
    # saying "Stockholm" when it means "somewhere in Sweden" deletes exactly
    # the wrong postings.
    #
    # **One place on the board is enough.** Gating a Zurich-and-Milan posting
    # because Milan is named would be the gate firing on a fact that argues
    # for keeping the row.
    if not set(hubs) & BOARD_HUBS:
        add("exclusion_reason", "off_location", f"{'/'.join(hubs)}: {raw[:40]!r}")

    return tags


def _fit(tags: list[Tag]) -> Tag:
    """The one dimension that encodes the user's profile.

    Under a year of experience, already graduated, Python and research rather
    than C++ and systems. Advisory only -- `out_of_scope` still keeps its row.
    """
    single = {
        tag.dimension: tag.value
        for tag in tags
        if tag.dimension in ("seniority", "relevance", "code_depth",
                             "experience_floor", "desk")
    }
    seniority = single.get("seniority", "unknown")
    relevance = single.get("relevance", "unknown")
    depth = single.get("code_depth", "unknown")
    # Multi-valued. Named for the evidence string by the first one `_HUBS`
    # lists, which is its priority order, so a posting in Stockholm and
    # Frankfurt says "stockholm" rather than whichever tag came last.
    hubs = {tag.value for tag in tags if tag.dimension == "hub"} or {"unknown"}
    hub = next((name for name in _HUBS if name in hubs), sorted(hubs)[0])
    gates = {tag.value for tag in tags if tag.dimension == "exclusion_reason"}
    hard = {tag.value for tag in tags if tag.dimension == "hard_gates"}
    spoken = {
        tag.value for tag in tags
        if tag.dimension == "spoken_language" and tag.value != "none"
    }
    stated = single.get("experience_floor", "unstated")
    floor = int(stated) if stated.isdigit() else None

    key = (tags[0].ats, tags[0].token, tags[0].job_id)
    _CAP = {"apply_now": "strong", "strong": "plausible", "plausible": "stretch"}

    # Every soft filter is a notch, and they compose. None rejects: each is a
    # reason a posting is further away, not a reason it is not a posting.
    notches: list[str] = []
    # A relevance read out of the body because the title said nothing is the
    # weakest evidence here: `Executive Assistant` and `Full Stack Engineer`
    # reached the shortlist that way, on a body that mentions quant work
    # because the firm does quant work.
    if any(tag.dimension == "relevance" and (tag.evidence or "").startswith("body only")
           for tag in tags):
        notches.append("title said nothing")
    # A core quant role in São Paulo keeps its row but should not outrank one
    # in Amsterdam -- Santander's global board once filled the shortlist from
    # `hub: other` while Stockholm showed one entry. One focus hub among
    # several keeps the notch off.
    if not hubs & _FOCUS_HUBS:
        notches.append("outside the focus hubs")
    if "phd_required" in hard:
        notches.append("phd required")
    if spoken:
        notches.append(f"{'/'.join(sorted(spoken))} required")
    # Under a year of experience, a three-year bar is a real distance. Six is
    # handled further down, because the floor has already moved the seniority.
    if floor is not None and floor >= 3:
        notches.append(f"{floor} year bar")

    def make(bucket: str, why: str) -> Tag:
        for notch in notches:
            bucket, why = _CAP.get(bucket, bucket), f"{why}; {notch}"
        return Tag(*key, "fit", bucket, "weak", why)

    # Reads the hard gate now rather than the seniority ladder, which is where
    # this fact moved: a future graduation date is something the reader cannot
    # pass, not a grade they might grow into.
    if "student_only" in hard:
        return make("out_of_scope", "requires a future graduation date")
    if relevance == "rejected":
        return make("out_of_scope", f"excluded: {'/'.join(sorted(gates)) or 'no quant signal'}")
    # A senior posting is a stretch however well the subject matter fits.
    #
    # **But a rank the reader cannot reach caps a posting they would otherwise
    # want; it must not *promote* one nobody has read.** `stretch` outranks
    # `unknown` in `index.html`'s `FIT_RANK`, so while `senior_6_10` was a gate
    # this branch was unreachable without a verdict. Removing the gate made it
    # reachable, and 290 of 466 Nordic cards became `Senior <IT consultant>`
    # above every genuine markets posting still at `unknown`. *Senior* is not
    # evidence about subject matter, and this dimension is about subject
    # matter -- so the cap needs a relevance to cap.
    if seniority in ("head_or_md", "lead", "senior_6_10") and relevance != "unknown":
        return make("stretch", f"seniority {seniority}")
    if relevance == "relevant" and seniority in ("junior_0_2", "new_grad"):
        return make("apply_now", f"research/modelling, {seniority}, {hub}")
    if relevance == "relevant":
        if depth in ("systems", "hardware"):
            return make("plausible", f"research/modelling but {depth}")
        return make("strong", f"research/modelling, seniority {seniority}")
    if relevance == "less_relevant":
        # Real quant work, wrong half of it: a trading seat or a build seat
        # rather than a research one. Worth reading, never the top bucket.
        if seniority in ("junior_0_2", "new_grad"):
            return make("strong", f"quant but {single.get('desk', 'unstated')}"
                                  f"/{seniority}")
        return make("plausible", "quant, but not research")
    if relevance == "adjacent":
        return make("plausible", "adjacent to the desk")
    return make("unknown", "nothing in the text decided it")


def postings(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Postings with no tag from the current lexicon version."""
    return connection.execute(
        """
        SELECT j.ats, j.token, j.job_id, j.title, j.location, j.department,
               j.category, j.description
        FROM jobs j
        WHERE NOT EXISTS (
            SELECT 1 FROM job_tags t
            WHERE t.ats = j.ats AND t.token = j.token AND t.job_id = j.job_id
              AND t.tagger = ?
        )
        LIMIT ?
        """,
        (TAGGER, limit),
    ).fetchall()


def record(connection: sqlite3.Connection, tags: list[Tag]) -> None:
    timestamp = db.now()
    with connection:
        connection.executemany(
            "INSERT OR REPLACE INTO job_tags"
            " (ats, token, job_id, dimension, value, confidence, evidence,"
            "  tagger, tagged_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (t.ats, t.token, t.job_id, t.dimension, t.value, t.confidence,
                 t.evidence, TAGGER, timestamp)
                for t in tags
            ],
        )


def run(connection: sqlite3.Connection, limit: int) -> tuple[int, int]:
    """Tag up to `limit` postings. Returns (postings, tags)."""
    connection.executescript(SCHEMA)
    rows = postings(connection, limit)

    written = 0
    batch: list[Tag] = []
    for row in rows:
        tags = tag_posting(row)
        tags.append(_fit(tags))
        batch.extend(tags)
        written += len(tags)
        if len(batch) >= 2_000:
            record(connection, batch)
            batch.clear()
    record(connection, batch)
    return len(rows), written


def summary(connection: sqlite3.Connection, dimension: str):
    connection.executescript(SCHEMA)
    return connection.execute(
        "SELECT value, COUNT(*) AS n,"
        "       SUM(confidence = 'strong') AS strong"
        " FROM job_tags WHERE dimension = ? AND tagger = ?"
        " GROUP BY value ORDER BY n DESC",
        (dimension, TAGGER),
    ).fetchall()


def search(
    connection: sqlite3.Connection,
    *,
    require: dict[str, tuple[str, ...]] | None = None,
    exclude: dict[str, tuple[str, ...]] | None = None,
    since: str | None = None,
    limit: int = 50,
):
    """Postings matching every `require` and none of `exclude`.

    This is where filtering belongs -- principle 4. Every lexicon bug found so
    far was fixed by re-running over stored rows, which a write-time filter
    would have thrown away.

    `require` is AND across dimensions and OR within one, which is what a
    person means: hub in (amsterdam, stockholm) *and* fit in (apply_now,
    strong). `exclude` drops a posting carrying any listed value.
    """
    where = ["j.removed_at IS NULL"]
    params: list[object] = []

    for dimension, values in (require or {}).items():
        if not values:
            continue
        marks = ",".join("?" * len(values))
        where.append(
            "EXISTS (SELECT 1 FROM job_tags t WHERE t.ats = j.ats"
            " AND t.token = j.token AND t.job_id = j.job_id AND t.tagger = ?"
            f" AND t.dimension = ? AND t.value IN ({marks}))"
        )
        params += [TAGGER, dimension, *values]

    for dimension, values in (exclude or {}).items():
        if not values:
            continue
        marks = ",".join("?" * len(values))
        where.append(
            "NOT EXISTS (SELECT 1 FROM job_tags t WHERE t.ats = j.ats"
            " AND t.token = j.token AND t.job_id = j.job_id AND t.tagger = ?"
            f" AND t.dimension = ? AND t.value IN ({marks}))"
        )
        params += [TAGGER, dimension, *values]

    if since:
        where.append("j.first_seen >= ?")
        params.append(since)

    return connection.execute(
        f"""
        SELECT j.ats, j.token, j.job_id, j.title, j.location, j.url, j.domain,
               j.first_seen,
               (SELECT value FROM job_tags v WHERE v.ats = j.ats
                 AND v.token = j.token AND v.job_id = j.job_id
                 AND v.dimension = 'fit' AND v.tagger = ?)  AS fit,
               -- Multi-valued: a posting open in two cities carries a
               -- row per city, and a scalar subquery would print whichever
               -- one SQLite reached first. Joined, so the filter and the
               -- column agree about what matched.
               (SELECT group_concat(value, '/') FROM job_tags v WHERE v.ats = j.ats
                 AND v.token = j.token AND v.job_id = j.job_id
                 AND v.dimension = 'hub' AND v.tagger = ?)  AS hub,
               (SELECT value FROM job_tags v WHERE v.ats = j.ats
                 AND v.token = j.token AND v.job_id = j.job_id
                 AND v.dimension = 'seniority' AND v.tagger = ?) AS seniority
        FROM jobs j
        WHERE {' AND '.join(where)}
        ORDER BY CASE fit
                     WHEN 'apply_now' THEN 0 WHEN 'strong' THEN 1
                     WHEN 'plausible' THEN 2 WHEN 'stretch' THEN 3 ELSE 4 END,
                 j.first_seen DESC
        LIMIT ?
        """,
        (TAGGER, TAGGER, TAGGER, *params, limit),
    ).fetchall()


def dimensions(connection: sqlite3.Connection):
    """Every dimension and value in use, so the filter is discoverable."""
    connection.executescript(SCHEMA)
    return connection.execute(
        "SELECT dimension, value, COUNT(*) AS n FROM job_tags WHERE tagger = ?"
        " GROUP BY dimension, value ORDER BY dimension, n DESC",
        (TAGGER,),
    ).fetchall()


def shortlist(connection: sqlite3.Connection, limit: int = 40):
    """The postings the tags say to read first."""
    connection.executescript(SCHEMA)
    return connection.execute(
        """
        SELECT j.title, j.location, j.url, j.domain, f.value AS fit,
               -- Pinned to the current lexicon and joined, for the two
               -- reasons the rest of this file pins and joins: `job_tags`
               -- keeps retired versions, so an unpinned read sums them, and
               -- `hub` is multi-valued, so a scalar read picks one at random.
               (SELECT group_concat(value, '/') FROM job_tags h WHERE h.ats = j.ats
                 AND h.token = j.token AND h.job_id = j.job_id
                 AND h.dimension = 'hub' AND h.tagger = ?) AS hub
        FROM job_tags f
        JOIN jobs j ON j.ats = f.ats AND j.token = f.token AND j.job_id = f.job_id
        WHERE f.dimension = 'fit' AND f.value IN ('apply_now', 'strong')
          AND f.tagger = ? AND j.removed_at IS NULL
        ORDER BY CASE f.value WHEN 'apply_now' THEN 0 ELSE 1 END, j.first_seen DESC
        LIMIT ?
        """,
        (TAGGER, TAGGER, limit),
    ).fetchall()


def stale_taggers(connection: sqlite3.Connection) -> list[tuple[int, int]]:
    """(tagger, rows) for every lexicon version that is not the current one."""
    connection.executescript(SCHEMA)
    return [
        (row["tagger"], row["n"])
        for row in connection.execute(
            "SELECT tagger, COUNT(*) AS n FROM job_tags"
            " WHERE tagger <> ? GROUP BY tagger ORDER BY tagger DESC",
            (TAGGER,),
        )
    ]


def prune(connection: sqlite3.Connection) -> int:
    """Delete every tag written by a superseded lexicon. Returns rows removed.

    **This deletes data, so the argument has to be better than "the table is
    big".** It is: the retention those rows represent does not exist. The
    primary key omits `tagger`, so `INSERT OR REPLACE` overwrites the previous
    version's row whenever a posting keeps the same value -- only rows whose
    value *changed* survive, which is the opposite of a diff. The table was
    storing whichever fragments of thirty-four versions happened not to be
    overwritten, and those are harmful: an unpinned `COUNT(*)` once read 49,808
    postings in a bucket that had already been split out.

    Safe because `job_tags` is derived -- principle 5, and re-running `tag`
    reconstructs the current version in full.

    Deliberately a separate command rather than a step in `run`: an automatic
    prune would delete the previous version at the moment a mistaken lexicon
    change is most likely to need backing out.
    """
    connection.executescript(SCHEMA)
    with connection:
        cursor = connection.execute(
            "DELETE FROM job_tags WHERE tagger <> ?", (TAGGER,)
        )
    return cursor.rowcount
