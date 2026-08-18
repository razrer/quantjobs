"""Layer 5 -- turning 57,000 postings into something you can rank.

Designed in `TAGGING.md`; this is Layer 1 of that design, the deterministic
lexicon. It runs over the whole corpus in seconds and is re-runnable, which is
what makes a lexicon bug cheap to fix rather than expensive to discover.

**Tags rank, they never delete.** A posting the lexicon rejects keeps its row
and gets `relevance:rejected` with the span that said so. Every dimension has
an explicit `unknown`, because a posting with no seniority tag has to be
distinguishable from one nothing has looked at -- the same hole `ats.py`
refuses to leave with its untiered state.

**Most postings are a title and a location, and that is workable.** 92% of the
corpus carries no description because the list endpoints Workday, BambooHR,
Personio, Breezy and SmartRecruiters publish return title, location and date
only. Tagging on that is thinner but not blind: it grades those tags **weak**
and the ones read out of a body **strong**, so the difference is visible at
read time rather than averaged away.

**Token boundaries, never substrings.** This corpus contains `Corporate
Administrator` -- admini*strat*or -- and `Alpha Account Services Data Analyst`,
because State Street's custody platform is called Alpha. A naive `in` scores
both as quant roles. Text is folded to spaced tokens and every needle is
matched with its padding, the same trick `domains.py` uses on firm names.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from . import db, lexicon

# Bump on every lexicon change: the diff between two versions over the same
# corpus is a free regression test, and it is the only way to tell "the
# classifier improved" from "the market moved".
TAGGER = 35

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
-- `postings()` asks "has this posting been tagged at the current version", as a
-- correlated NOT EXISTS on (ats, token, job_id, tagger). The primary key covers
-- the first three and stops there, so SQLite then walked every row for that
-- posting -- roughly fifteen dimensions per lexicon version, across every
-- version still in the table -- to test `tagger`. Measured: 18 seconds to
-- return 50,529 rows. Putting `tagger` in the index turns that into a seek.
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


def fold(*parts: str | None) -> str:
    """Everything folded to lowercase ASCII tokens, padded so needles can be too."""
    text = " ".join(part for part in parts if part)
    text = _TAGS.sub(" ", text).casefold().translate(_CONFUSABLES).translate(_ACCENTS)
    for symbol, replacement in _SYMBOLS:
        text = text.replace(symbol, replacement)
    return " " + " ".join(re.sub(r"[^a-z0-9+#]+", " ", text).split()) + " "


def _terms(*phrases: str) -> tuple[str, ...]:
    """Fold needles the same way the text is folded, once, at import.

    A needle carrying punctuation or a diacritic can never match otherwise:
    `fold` strips `ç` and `ß` outright, so a hand-written "français courant"
    is a needle that cannot fire and looks exactly like one that never
    matched. Folding both sides is the same discipline `domains.py` learned
    when it compared a normalized firm name against raw page text.
    """
    return tuple(fold(phrase).strip() for phrase in phrases)


def _hit(text: str, needles: tuple[str, ...]) -> str | None:
    """The first needle present as whole tokens, or None."""
    for needle in needles:
        if f" {needle} " in text:
            return needle
    return None


def _hits(text: str, needles: tuple[str, ...]) -> list[str]:
    """Every needle present, for the rules that count corroboration."""
    return [needle for needle in needles if f" {needle} " in text]


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
    # The noun forms, because the participle ones miss the actual seat:
    # `Algorithmic Trader` is not "algorithmic trading" and was reading as a
    # trader with no quant signal at all.
    "algorithmic trader", "algo trader", "systematic trader",
    "statistical arbitrage", "stat arb", "alpha research", "signal research",
    "alpha generation", "execution research", "model validation",
    "risk quant", "kwantitatief", "quantitatif",
)

# The same list with the bare adjectives removed, for the one branch that reads
# the body *alone*. `lexicon` learned this first and named the set: "strong
# quantitative skills" is boilerplate in half the job specs ever written, so a
# bare `quantitative` decides nothing about a document it appears in once.
# Above, in a title, the same word is the whole job -- which is why there are
# two lists rather than one edit to `_QUANT_CORE`.
#
# It was reading them. `Cloud Engineer` reached `adjacent` on "body only
# 'quantitative', once, at 'investment management'" and `Walleye Stock
# Competition (2026)` on "body only 'quant'" -- both hand-labelled rejections,
# both rescued by a word their employer's boilerplate happened to contain.
_QUANT_CORE_BODY = tuple(
    needle for needle in _QUANT_CORE if needle not in lexicon.GENERIC_IN_BODY
)

# These name the role in a title and are boilerplate in a body. Every finance
# company's "about us" mentions market and credit risk, which scored
# `Interest & Product Logic Specialist` and `Insurance Accounting Specialist`
# as core quant roles. In a title the same words are the job.
# `research analyst` was here and is now a weak positive instead. `Equity
# Research Analyst` is sell-side equity research -- an investment-banking job,
# and the hand-labelled sheet rejected it outright -- while `Quantitative
# Research Analyst` is caught a line above by the word *quantitative*. Bare
# "research analyst" is the same shape as bare "trader": the job it names is
# quant at one firm and something else entirely at the next, so it belongs
# where the body can still rescue it rather than where it decides on its own.
_QUANT_CORE_TITLE = (
    "trader", "trading strategist", "strat", "strats",
    "market risk", "credit risk", "derivatives pricing",
    "portfolio construction", "handelaar", "handlare", "systematisk",
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
    # Widened at the user's request: a title announcing that somebody else does
    # the work is not reachable from under a year of experience, whatever the
    # subject matter. Bare `manager` is in deliberately -- it was the one word
    # holding the line between `Product Manager` (already here) and `Manager,
    # Data Science` (not), and there is no version of the second that is a
    # first job.
    "manager", "senior manager", "associate manager", "project manager",
    "project leader", "project lead", "team leader", "team lead",
    "scrum master", "agile coach", "chapter lead", "tribe lead",
    "vice president", "vp", "avp", "svp", "president",
    "supervisor", "foreman", "principal consultant",
    # Nordic. `projektledare` and `gruppchef` are the same job as the two
    # above, and the compound rule below catches the rest of the family.
    "projektledare", "teamledare", "gruppledare", "verksamhetsledare",
    "gruppchef", "enhetschef", "avdelningschef", "ekonomichef", "platschef",
    "regionchef", "kontorschef", "verkstallande direktor",
)

# Swedish builds a manager's title by compounding, and a word list cannot see
# inside a compound: `ekonomichef` is above but `inköpschef`, `IT-chef` and
# `hållbarhetschef` are not, and there is no end to that list. The occupational
# head is the last element, so it is matched as a token suffix -- the trick
# `lexicon.SWEDISH_HEADS` already uses one module over.
#
# Safe here because both heads are long and neither ends an English word: no
# English title ends in `chef` (the cook is a whole token, and `Chef de Partie`
# is off-industry anyway) or in `ledare`.
_MANAGER_HEADS = ("chef", "ledare")

# The same trick for occupations rather than ranks. `Elsäljare` is one token, so
# the needle `saljare` cannot see it, and the board was still carrying
# `Fältsäljare`, `Mediesäljare`, `Tandsköterska` and `Skadetekniker` after the
# accent fix -- 48 of them.
#
# **Two obvious heads were dropped after the dry-run.** `-arbetare` catches
# *medarbetare*, which is simply Swedish for "employee" and says nothing about
# the job; `-assistent` catches *Forskningsassistent*, a research assistant,
# which is a posting this project might want. Both are the `chef`-is-a-CFO
# mistake in a new place.
_TRADE_HEADS = (
    "saljare", "skoterska", "larare", "mekaniker", "elektriker",
    "handlaggare", "sekreterare", "tekniker", "montor", "stadare",
    "vaktmastare", "bagare", "chauffor", "forare",
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
# here, on the grounds that a bank stamps them on a five-year hire, and
# `PLAN.md` records that argument. The user has since asked for director titles
# to be removed outright, and the two readings agree for this reader: a bank's
# five-year Associate Director is exactly as unreachable from under a year as a
# real one. They now count as management.
#
# It was not academic. Three `Assistant Director` and `Associate Director`
# postings reached the labelling sheet after the gate was added, because the
# protection here sent them to `seniority`, where a body asking for three years
# read `mid_3_5` and cleared the bar.
_NOT_MANAGEMENT = _terms(
    "art director", "creative director", "director of photography",
    "funeral director", "board of directors",
)

# The software specialties, treated harder than the rest of engineering.
#
# `lexicon.ENGINEERING` is deliberately two-sided and says so: `Software
# Engineer, Trading Systems` at Optiver is in scope, `Senior Backend Engineer,
# Payments Platform` is not, and no one-sided list separates them. These
# titles are the subset where that ambiguity does not exist -- the specialty
# *is* the job, and no amount of markets context around it makes it quant
# work.
#
# Six hand-labelled rows, one shape: `Senior Software Engineer, Frontend
# (Coinbase Advisor - Agentic Trading)`, `Senior DevOps Engineer - Trading
# Platforms`, `Principal Engineer - Trading Core`, `Cloud Engineer`, `Data
# Infrastructure Engineer` and `Staff QE`. Every one was rejected by hand, and
# every one had reached `adjacent` or `unknown` on the bare word *trading* --
# the name of the platform the engineer maintains, not the work. `CLAUDE.md`
# had already recorded the shape from `Backend Engineer - Trading & Asset
# Optimization` and fixed it one list over, in `trading_style`.
#
# **Bare `software engineer` and `developer` are deliberately absent.** A
# quant-dev role often calls itself one, and `CLAUDE.md` is explicit that heavy
# systems engineering is a down-rank rather than a hard drop. `principal
# engineer` and `staff engineer` are in because they name the software IC
# ladder outright, which no quant title does.
#
# An unambiguous quant word still wins, exactly as it does for a management
# title: `Quantitative Developer` and `Quant Platform Engineer` never reach
# this branch.
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
    # `qe` is two characters and would normally be refused on that alone. It
    # earns the place by measurement rather than by length: eight titles in the
    # whole corpus carry it, and the one the tagger rated positively is `Staff
    # QE` -- the row the sheet rejected as "quality engineering role for
    # software". In a *body* it would be quantitative easing; this list is read
    # from the title only.
    "qe",
    "it support", "help desk", "helpdesk", "service desk", "desktop support",
    "application support", "technical support",
    "salesforce", "servicenow", "sharepoint",
)

_QUANT_ADJACENT = (
    "trading", "researcher", "research analyst",
    "data scientist", "data science", "machine learning", "deep learning",
    "statistician", "statistics", "econometrics", "financial engineering",
    "pricing analyst", "portfolio analyst", "investment analyst",
    "risk analyst", "analytics", "research engineer", "datavetenskap",
)

# What kind of job this is, as **one** value rather than a set.
#
# It replaces `role_family`, which was multi-valued and therefore said almost
# nothing: a single Schonfeld posting came back as research *and* trading *and*
# quant_dev *and* risk *and* execution *and* portfolio_construction *and*
# strategist, because every one of those words appears somewhere in a long
# body. Seven values is not a classification, it is a word count.
#
# Order is the priority and it carries three deliberate decisions:
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
        # A *risk quant* is a modelling role and `CLAUDE.md` puts it on the
        # include list beside quant research. A *risk analyst* is not
        # necessarily one, and stays in `risk` below -- the qualifier is the
        # whole difference, exactly as it is for `Credit Risk Operations`.
        "risk quant", "quant risk", "credit risk quant", "market risk quant",
        "market risk models", "quantitative risk",
        "researcher", "research analyst", "kvantitativ analytiker",
        "kvantitativ", "forskning", "onderzoek", "recherche",
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
    ),
    "portfolio_management": _terms(
        "portfolio manager", "portfolio management", "portfolio construction",
        "asset allocation", "investment manager", "fund manager",
        "portfolio analyst",
    ),
    "risk": _terms(
        "market risk", "credit risk", "risk analyst", "risk manager",
        "risk management", "counterparty risk", "risk analytics",
        "riskhantering", "risico", "risiko",
    ),
    "data_science": _terms(
        "data scientist", "data science", "machine learning", "deep learning",
        "datavetenskap",
    ),
    "engineering": _terms(
        "software engineer", "software developer", "developer", "programmer",
        "platform engineer", "infrastructure engineer", "data engineer",
        "devops", "site reliability", "utvecklare", "ontwikkelaar",
        "systemutvecklare", "engineer",
    ),
}

# Where the role sits, which the title almost never says and the body almost
# always does. This is the dimension that separates two postings the title
# cannot: `Quantitative Trading Associate` reads like a desk seat and its body
# is market-hours oversight, runbooks, incident response and position
# reconciliation -- middle office wearing a quant title.
#
# `front_office` is checked **first** on purpose. A front-office posting names
# middle-office machinery all the time -- a trading-floor STRAT role asks for a
# "grasp of trade-lifecycle workflows" -- while the reverse is rare, so the
# specific claim ("you will sit on the trading floor") has to win over the
# incidental mention.
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

# **`intern` is no longer a rank**, and one posting is the whole argument.
# Schonfeld's `Quantitative Research / Developer - Intern` demands "2-3 years
# buy- or sell-side experience" and converts to full time; it is an internship
# *contract* wrapped around a mid-level *bar*. The old ladder had `intern` as
# a seniority value, so it swallowed that posting whole and reported the rank
# as "intern" while the body asked for three years.
#
# So the two facts are now stored separately, as they always should have been:
#
# - **is it an internship** -- `contract: internship`, which already existed
# - **what does it demand** -- `seniority`, which now always carries a level
#
# **`student_intern` has left the ladder, at the user's decision.** It was here
# because a posting demanding a future graduation date is unreachable for
# someone who has already graduated, which is true and is not a *rank*. Being a
# student is an eligibility fact and a contract, and both were already recorded
# elsewhere: `contract: internship` carries it for 1,307 postings, and
# `lexicon.judge` rejects on `student_only` for the same phrases.
#
# It was doing almost no work on this ladder -- 67 postings against those 1,307
# -- while costing something real. The labelling sheet offered `student_intern`
# as a seniority value, so every intern-titled row was labelled that way and
# disagreed with a tagger that reads rank from the title and finds no grade
# word. The scale asked a question the tagger does not answer.
#
# The phrases did not go anywhere: they are `_HARD_GATES["student_only"]` now,
# which is where a thing you cannot pass belongs, and they still rank.
# **`vp` and bare `director` moved up to `head_or_md`, and the evidence is
# four hand-labelled rows saying the same thing four times.** `Credit Risk
# Sanctioner (VP)`, `Client Portfolio Manager - VP`, `VP, Corporate
# Development` and `Vice President, Assistant Portfolio Manager` were all
# labelled `head_or_md` with the note *"filter out becuase VP role"*, against
# `senior_6_10` here.
#
# `PLAN.md` records the argument for the old placement -- at a bank VP is a
# mid-career grade -- and it is true and no longer decides anything. This list
# was the only place in the module still saying so: `_MANAGEMENT` has carried
# `vp`, `vice president` and bare `director` since the user asked for director
# titles to be removed outright, so the *gate* already treated these postings
# as unreachable while the *rank* called them mid-career. One word, two lists,
# two answers -- the shape that has cost this project a bug at every layer.
#
# `associate director` and `executive director` stay on `senior_6_10`, and
# bare `director` would swallow both on a token match -- `_first` takes the
# first bucket that hits and `head_or_md` is first, so order cannot express
# this. `_NOT_HEAD_GRADE` below is the guard, and it is the same shape as
# `_NOT_MANAGEMENT`: the two lists ask different questions of the same word,
# because seniority is a ladder and management is a gate.
#
# `md` was held back as the postal abbreviation for Maryland and the dry-run
# cleared it: **78 titles in 157,464 carry it and exactly one is rated
# positively** -- `Financial Institution Credit Risk Management (ED/MD)`, which
# is an officer seat and belongs here. The state code lives in the *location*
# column, which this never reads.
_SENIORITY = {
    "head_or_md": _terms(
        "head of", "managing director", "chief", "partner", "global head",
        "director of", "director", "md", "vp", "vice president", "president",
    ),
    # `leader` was missing while `lead` was here, so `Applied Science / Data
    # Science Leader` carried no grade word at all and a body asking for three
    # years read it as `mid_3_5` -- a leadership title arriving one rung above
    # entry level. `_MANAGEMENT` had `leader` all along; this list did not.
    "lead": _terms("lead", "leader", "principal", "staff engineer", "team lead"),
    "senior_6_10": _terms(
        "senior", "erfaren", "avp", "associate director", "executive director",
    ),
    # `graduate` moved up from `junior_0_2`. In a *title* it names the intake
    # -- `Graduate Trader`, `Graduate Programme` -- and a graduate scheme is a
    # different prospect from a job wanting two years, which is exactly the
    # distinction the ladder exists to draw. Only 168 postings in 55,455 read
    # `new_grad` before this, against 3,174 `junior_0_2`.
    "new_grad": _terms(
        "graduate programme", "graduate program", "new grad", "campus hire",
        "traineeprogram", "trainee", "graduate", "graduates", "nyexaminerad",
    ),
    "junior_0_2": _terms("junior", "associate", "entry level"),
    "mid_3_5": _terms("mid level", "experienced hire"),
}

# Titles where `director` is not an officer grade. Two kinds, and bare
# `director` needs both: the ones where the word means something else entirely
# (`Art Director`, `Funeral Director`), which `_NOT_MANAGEMENT` already guards
# on the gate side, and the bank grades stamped on a five-year hire
# (`Associate Director, EQD Quant`), which the ladder must keep at
# `senior_6_10`. Both are pinned by tests, and both broke the moment bare
# `director` went in above.
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

# A number attached to "years of experience" is the least ambiguous statement a
# body ever makes, and it is why `PLAN.md`'s "the rank is in the title" rule
# needs one carve-out rather than an exception.
#
# That rule was written against *stray words*: a body saying "you report to the
# Head of Trading" made `Graduate Trader` a `head_or_md` posting, because the
# words describe somebody else's rank. A years figure is not that -- it is the
# posting stating its own bar, and where it disagrees with the title the title
# is simply wrong. `Quantitative Trading Associate` says associate and asks for
# "3+ years"; `Quantitative Research / Developer - Intern` says intern and asks
# for "2-3 years". Both are mid, and only the body knows.
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

_ASSET_CLASS = {
    "equities": ("equity", "equities", "cash equities", "aktier", "aandelen"),
    "futures": ("futures", "term determineerbaar"),
    "fx": ("fx", "foreign exchange", "currencies", "valuta"),
    "rates": ("rates", "fixed income", "government bonds", "swaps", "rante"),
    "credit": ("credit", "corporate bonds", "cds", "kredit"),
    "commodities": ("commodities", "commodity", "energy trading", "power gas"),
    "options_vol": ("options", "volatility", "vol trading", "derivatives", "optioner"),
    "crypto": ("crypto", "cryptocurrency", "digital assets", "defi", "web3", "blockchain"),
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
    # Education is read **only** when a doctorate is compulsory. Everything
    # softer -- "PhD preferred", "MSc or PhD", "advanced degree a plus" -- is
    # not a gate and is deliberately not tagged: a degree preference is how
    # every quantitative posting on earth is written, so tagging it would
    # produce a dimension that fires on the whole corpus and separates nothing.
    # Read from title and body alike, and the title forms matter: two
    # hand-labelled rows were rejected as "perfect fit - but has hard
    # requirement of phd", and only one of them carried a body phrase this
    # list could see. The other announces it in the title as `PhD+`, which
    # `fold` keeps as one token because `+` survives folding.
    #
    # **Bare `phd` is deliberately absent, and the dry-run is why.** 220 titles
    # carry it and 29 are rated positively -- `Campus Quantitative Researcher,
    # PhD`, `Junior Quantitative Researcher (Ph.D.)`, `2027 Internship -
    # Quantitative Researcher (PhD)`. Those name the *audience* a posting is
    # open to, not a bar it sets, and `CLAUDE.md` records that an over-eager
    # student rule threw away Aquatic Capital's `Quantitative Researcher, PhD`
    # once already. Only the compulsory phrasings are here.
    "phd_required": _terms(
        "phd required", "phd is required", "phd is a requirement",
        "must hold a phd", "must have a phd", "requires a phd",
        "phd mandatory", "phd degree required", "doctorate required",
        "doctorate is required", "phd essential", "phd+", "phd only",
        "phd candidates only", "phd holders only", "phd degree is required",
    ),
    "visa_sponsorship_none": _terms(
        "no visa sponsorship", "not able to sponsor", "unable to sponsor",
        "without sponsorship", "must have the right to work",
    ),
    # Moved off the seniority ladder, where it was pretending to be a rank. A
    # posting demanding a *future* graduation date is one this reader cannot
    # pass, which is exactly what a hard gate is. Specific phrases only: a bare
    # "student" fired on any body that merely welcomes them, and marked a
    # full-time PhD-level research role at Radix Trading as student-only.
    "student_only": _terms(
        "currently enrolled", "must be enrolled", "final year student",
        "final year students", "penultimate year", "still studying",
        "graduating in 2027", "graduating in 2028", "graduating in 2029",
        "expected graduation", "pursuing a degree", "studerande vid",
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

# A soft filter, not a gate. The user reads and writes English and Swedish, so
# a posting demanding either is not filtered by language at all -- which is why
# neither appears here, and why the old `local_language_required` gate was
# wrong: it flagged "flytande svenska" on Stockholm postings, the one hub the
# project cares most about, as though it were an obstacle.
#
# Multi-valued, because Hong Kong asks for two. Requirement phrasing only: a
# posting that merely *offers* language classes is not asking for one.
# **Built from frames rather than hand-written, because hand-writing it caught
# 151 postings out of 69,961.** The old list was three phrasings per language --
# "fluent in X", "X is required", "native X" -- and job advertisements ask for a
# language in twenty other ways: "proficiency in", "good command of", "written
# and spoken", "C1", "verhandlungssicher", "i tal och skrift". A requirement the
# reader would actually hit was being missed roughly nine times in ten.
#
# The frames are still *requirement* phrasings. A posting that merely mentions a
# language, or offers classes in one, is not asking for it -- so `{L} a plus`,
# `{L} is a bonus` and bare `{L}` are deliberately not frames. This is a soft
# filter that costs one notch of rank rather than a gate, so the cost of a
# generous frame is small and the cost of a missing one is a surprise at
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

_CONTRACT = {
    "internship": ("intern", "internship", "praktik", "praktikant"),
    "fixed_term": ("fixed term", "temporary", "vikariat", "tijdelijk", "befristet"),
    "contractor": ("contractor", "freelance", "consultant"),
    "part_time": ("part time", "deltid", "parttime", "teilzeit"),
    "permanent": ("permanent", "full time", "tillsvidare", "heltid", "vast contract"),
}

# The exclude list, one tag each, so it is auditable by category. `crypto` and
# `heavy_systems` down-rank; the rest reject.
_EXCLUSION = {
    "actuarial": ("actuary", "actuarial", "aktuarie", "actuaris"),
    "insurance_pricing": ("insurance pricing", "skadereglering"),
    # `underwriting` and `claims` used to sit above, and `insurance_pricing` is
    # on `_BODY_SAFE_EXCLUSIONS` -- so both were matched against the *body*,
    # where they are ordinary banking words. Debt underwriting is securities
    # issuance, not insurance. **1,834 postings were rejected this way on a
    # clean title**, `Associate, FICC Structuring, Fixed Income` among them.
    # Exactly the failure `CLAUDE.md` names: boilerplate is the default failure
    # mode of any body-matched rule. They are a title-only category now.
    "insurance_underwriting": ("underwriting", "claims", "claims handler"),
    "non_markets_fintech": ("payments", "kyc", "aml", "fraud detection", "lending platform"),
    # Lending is not markets, and the qualifier is the whole difference -- the
    # same shape as `Credit Risk Operations` and `discretionary_investing`
    # below. `lexicon.NON_QUANT_FINANCE` carries these too, and that was not
    # enough on its own: `judge` runs last, so `Senior Lending Analyst -
    # Portfolio & Risk Analytics` had already reached `adjacent` on *risk
    # analytics* before anything asked it. An exclusion outranks a weak
    # positive, which is the branch order that makes this fire.
    "lending": _terms(
        "loan analyst", "lending analyst", "distressed loan", "loan servicing",
        "loan officer", "mortgage analyst",
    ),
    "insurance_ops": (
        "insurance accounting", "insurance reporting", "policy administration",
        "skadeforsikring", "forsikring",
    ),
    "support_function": (
        "recruiter", "recruitment", "talent acquisition", "human resources",
        "marketing", "communications", "office manager", "receptionist",
        "accounting", "bookkeeping", "payroll",
    ),
    "crypto_web3": ("crypto", "web3", "defi", "blockchain", "nft"),
    "heavy_systems": ("fpga", "verilog", "kernel bypass", "embedded systems"),
    # Investing done by judgement rather than by model: private equity, sell-
    # side research, traditional asset management, wealth. The hand-labelled
    # sheet rejected nine of these in a row -- `Senior Investment Analyst`,
    # `Portfolio Associate`, `Asset Management Analyst`, `Partner, Private
    # Equity` -- while the lexicon had `investment analyst` and `portfolio
    # analyst` filed as weak *positives*.
    #
    # Matched on the title only, and read after the core check, so a
    # `Quantitative Analyst, Private Equity` keeps its quant reading. The
    # qualifier is the whole difference, exactly as it is for `Credit Risk
    # Operations`.
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
# Every other exclusion in this file *ranks* -- it says a posting is further
# from the centre, and the posting stays readable. This one is different in
# kind: a nurse, a welder and a `Medical AI Specialist` are not distant quant
# roles, they are other jobs, and the board drops them rather than ranking
# them. That is the only place in the pipeline where a classifier removes
# something from view, so it is deliberately the narrowest rule here.
#
# It never touches the database. `jobs` keeps every row, the tag records why,
# and re-running the tagger rebuilds the verdict -- so a term that turns out
# to be wrong costs one `build_data.py` run, not a re-scrape.
#
# Two signals, and the first is much the stronger:
#
# 1. **The source's own taxonomy.** JobStream files every Swedish ad under one
#    of 21 occupation fields. That is an enumeration written by the employer,
#    not a guess read off a title, and fifteen of the fields can never hold a
#    quant job. This is why `jobs.category` exists.
# 2. **Unambiguous occupation words in the title.** Only for the ATS boards,
#    which publish no taxonomy at all. Every needle below was dry-run over the
#    whole corpus first and hit nothing in finance.
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

# MyCareersFuture's own taxonomy, the same argument the Swedish fields make one
# comment up: an enumeration the employer picked from beats any word list we
# would write. It needs its own set because the portal files a posting under
# *several* categories at once, so this is a subset test rather than equality.
#
# **Dry-run over the 37,000 postings already swept, and the first attempt was
# wrong.** A loose probe put `Building and Construction` at the top of the
# "carries quant titles" list with 619 hits -- which is what happens when the
# probe matches `risk` and `model`, because construction has risk managers and
# BIM modellers. Tightened to unambiguous markets and quant words, the
# categories that genuinely carry them are the ones kept below, and the pick of
# the evidence is `Junior Quantitative Analyst (Multi-Strategy)` filed under
# *Banking and Finance*.
#
# Kept deliberately, each because the dry-run found real quant work in it:
# Banking and Finance, Information Technology, Engineering, Risk Management,
# Sciences / Laboratory / R&D, Insurance, Consulting, Professional Services,
# Accounting / Auditing / Taxation, Manufacturing, Wholesale Trade,
# Healthcare / Pharmaceutical (data scientists), Public / Civil Service (GIC
# and Temasek are roster firms), General Management, Others, Telecommunications.
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


def _mcf_off_industry(category: str | None) -> str | None:
    """Whether every category this posting carries is off-industry.

    A subset test, never equality: the portal files most postings under more
    than one category, and one kept category is enough to keep the posting.
    That direction is the same one the Swedish drop list picks -- an
    unrecognised field passes, and a mixed posting passes.
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
    # Added at the user's request: "accountant, salesperson etc., especially
    # lacking in Swedish ads". The Swedish half of that complaint had a cause
    # rather than a gap -- `fold` was deleting `å ä ö`, so every needle above
    # spelled `sjukskoterska` or `stadare` had never once matched the text it
    # was written for. That is fixed in `fold`; these are the genuinely missing
    # occupations, and every one was dry-run over all 69,961 titles first.
    #
    # **Four obvious-looking candidates were dropped after that dry-run**, and
    # each would have eaten markets work: `salesperson` is *Rates Salesperson*
    # and *Cross Asset Solutions Salesperson*, `sales associate` is *Alternative
    # Sales Associate, Sales*, `sales representative` is *Jr Equity/Fixed Income
    # Solutions Sales Representative*, and `controller` is *Hedge Fund
    # Controller* and *Product Controller*. All four are the wrong *job* rather
    # than the wrong industry, so they stay where they were -- rejected on
    # relevance, still on the board, one click away. `administrator` went the
    # same way on *Database Administrator*.
    #
    # `accountant` is here despite being an occupation rather than an industry,
    # because the user named it: 433 hits, all of them genuinely accountants,
    # and fund accounting is already an exclusion one layer up.
    "accountant", "accounting clerk", "bookkeeper",
    "redovisningsekonom", "redovisningskonsult", "ekonomiassistent",
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
    # Venue, events and front-of-house, found by machine-labelling 1,000
    # postings: the largest disagreement was `relevance: unknown` on rows any
    # reader would reject on sight, and these are what they were. Live Nation
    # and student-housing operators publish through the same ATS platforms as
    # the trading firms, so they arrive mixed in.
    #
    # Dry-run over all 69,961 titles first, as ever, and the check that decides
    # it is not the head count but whether a needle touches a posting the
    # tagger currently rates positively. **None of these touches one.**
    # `landscape` was dropped for failing exactly that kind of reading -- it
    # caught `Managing Technical Consultant, Landscape Architecture`, and a
    # *data* landscape is one usage away.
    "retail associate", "ticket taker", "usher", "box office", "music hall",
    "production runner", "venue", "greeter", "host", "workplace ambassador",
    "student living", "environmental inspector", "auto appraiser",
    "rental service agent",
    # French and German field sales, which arrive through the same tenants
    "conseiller commercial", "aussendienst",
    # A second pass over what was left. **`environmental inspector` did not
    # match `Environmental Inspectors (Field Based)`** -- token matching is
    # exact and the corpus advertises the plural, which is the same shape as
    # `Elsäljare` and worth the reminder: check the form the postings actually
    # use, not the form the dictionary does.
    "inspector", "inspectors", "project engineer", "design engineer",
    "events support", "promotions", "property associate",
)

# Deliberately absent, each after matching something real in the corpus:
# `coach` is *Portfolio Manager/Agile Coach* and *Financial Coach*; `pilot` is
# *Paint Pilot Projects*; `librarian` is *ECAD Librarian*; `translator` is
# DBS's *Data Translator*; `interpreter` is *Parts Interpreter*. Every one of
# them is a job this project might want, under a word that looks like a trade.

# A location field that names no place. Workday publishes `2 Locations` for
# every multi-site posting and 6,281 rows carry one, so reading them as `other`
# claimed we had looked and found somewhere else. `unknown` is the true answer,
# and it matters now that geography gates: `other` is dropped from the board
# and `unknown` is not, because a posting that could be in Amsterdam must not
# disappear for failing to say so.
_NO_PLACE = re.compile(r"^\s*(\d+\s+locations?|remote|multiple locations|various)\s*$",
                       re.IGNORECASE)

# `Cincinnati, OH` and `Waltham, MA` are the United States, which is
# semi-target and therefore kept -- and 5,987 of them were being gated as
# somewhere else, because no US city list is ever finished. The state code is
# the reliable handle.
#
# **It cannot go in `_HUBS`.** Hub matching runs over `fold(location, title)`,
# so a two-letter needle would fire on the title: `IN`, `OR`, `ME`, `HI`, `OK`
# and `DE` are all English words and all state codes. Matched here instead,
# against the **location alone**, and anchored to the `, XX` shape a US address
# actually takes -- which no European location in this corpus does.
_US_STATE = re.compile(
    r",\s*(A[LKZR]|C[AOT]|DE|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|"
    r"N[CDEHJMVY]|OH|OK|OR|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY]|DC)\b",
    re.IGNORECASE)

# **City before country, and the difference is a posting.** `sweden` used to sit
# in the `stockholm` tuple, so every Swedish advertisement read Stockholm --
# Kiruna, Lund, Visby and Kalmar included, 180 of them. That was survivable
# while geography only ranked. It is not survivable now that the board drops
# what is out of area, because the label would be deleting postings for being
# somewhere they are not and keeping them for being somewhere they are not.
#
# So a focus hub is the city and the distance somebody would actually commute,
# and the rest of the same country gets its own value. Those are gated by
# default and one line in `web/build_data.py` brings any of them back.
#
# Switzerland stays national on purpose: the roster is national, the country is
# small, and no Swiss city dominates it the way Stockholm dominates Sweden.
_HUBS = {
    "stockholm": (
        "stockholm", "stockholms lan", "solna", "sundbyberg", "kista",
        "bromma", "nacka", "danderyd", "sollentuna", "taby", "huddinge",
        "jarfalla", "lidingo", "sigtuna", "arlanda", "kungsholmen",
        "sodermalm", "upplands vasby", "tyreso", "botkyrka", "haninge",
    ),
    "copenhagen": (
        "copenhagen", "kobenhavn", "kbh", "frederiksberg", "gentofte",
        "lyngby", "glostrup", "soborg", "hellerup", "ballerup", "herlev",
        "taastrup", "hilleroed", "hillerod", "roskilde", "amager",
    ),
    "amsterdam": (
        "amsterdam", "amstelveen", "schiphol", "hoofddorp", "diemen",
        "zaandam", "haarlem", "almere", "randstad",
    ),
    "switzerland": (
        "zurich", "zuerich", "geneva", "geneve", "genf", "zug", "basel",
        "bern", "berne", "lausanne", "lugano", "winterthur", "st gallen",
        "switzerland", "schweiz", "suisse", "svizzera",
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
    # Semi-target: kept on the board, ranked below the focus hubs. The list was
    # eleven names and that was a ranking list. As a *gate* it has to be a
    # geography, so the country names and the cities that carry the head count
    # are all here -- 3,261 postings say only "USA" and 675 say San Francisco.
    "deprioritized": (
        "london", "united kingdom", "uk", "england", "scotland", "edinburgh",
        "manchester", "glasgow", "birmingham", "leeds", "bristol", "cambridge",
        "new york", "nyc", "manhattan", "jersey city", "new jersey", "chicago",
        "boston", "san francisco", "seattle", "austin", "dallas", "houston",
        "atlanta", "denver", "los angeles", "miami", "philadelphia",
        "washington dc", "charlotte", "california", "texas", "illinois",
        "massachusetts", "united states", "usa", "u s a", "us remote",
        "germany", "deutschland", "frankfurt", "munich", "muenchen", "berlin",
        "hamburg", "dusseldorf", "stuttgart", "cologne", "koeln",
        "dubai", "abu dhabi", "united arab emirates", "uae", "difc",
        "shanghai", "beijing", "shenzhen", "hangzhou", "guangzhou", "china",
    ),
    # The right country, the wrong city. Named rather than lumped into `other`
    # so the board can say what it dropped and why, and so turning Gothenburg
    # or Aarhus back on is a one-line change rather than a lexicon edit.
    "sweden_other": (
        "sweden", "sverige", "goteborg", "gothenburg", "malmo", "lund",
        "uppsala", "linkoping", "vasteras", "orebro", "helsingborg",
        "norrkoping", "jonkoping", "umea", "lulea", "kiruna", "kalmar",
        "boras", "visby", "sundsvall", "gavle", "vaxjo", "karlstad",
        "ostersund", "skelleftea", "halmstad", "eskilstuna", "sodertalje",
    ),
    "denmark_other": (
        "denmark", "danmark", "aarhus", "arhus", "odense", "aalborg",
        "esbjerg", "kolding", "vejle", "horsens", "randers",
    ),
    "netherlands_other": (
        "netherlands", "nederland", "the hague", "den haag", "rotterdam",
        "utrecht", "eindhoven", "groningen", "tilburg", "breda", "nijmegen",
        "arnhem", "maastricht", "leiden", "delft", "apeldoorn", "landgraaf",
        "cuijk",
    ),
}


_FOCUS_HUBS = frozenset(
    {"stockholm", "copenhagen", "amsterdam", "switzerland", "hong_kong", "singapore"}
)

# Ranks the reader cannot reach from under a year of experience. `mid_3_5` is
# deliberately *not* here: a three-year bar is a stretch rather than a wall,
# and `experience_floor` already carries the number for anyone who wants to
# filter harder. `unknown` is not here either, which is the point -- the gate
# fires on a rank that was read, never on one that was missing.
_OUT_OF_REACH = frozenset({"senior_6_10", "lead", "head_or_md"})

# What the board will show. Everything else is gated -- see `_off_location` and
# the note in `web/build_data.py`. `unknown` is deliberately in: a posting that
# never stated a place is not a posting somewhere else.
BOARD_HUBS = _FOCUS_HUBS | {"deprioritized", "unknown"}

# The exclusion reasons that *remove* a posting rather than ranking it.
# Everything else in `job_tags` ranks.
#
# **One definition, because two consumers.** `web/build_data.py` uses it to
# decide what reaches the board, and `labels.py` uses it to decide what is
# worth a person's hour -- and those must agree. They did not: the sheet went
# on offering VP roles in Kiruna after the board had stopped showing them,
# which is a labelling fixture measuring a classifier nobody reads.
#
# Deleting a line here puts those postings back on the next build, with no
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
# `TAGGING.md` dimension 11, and it earns its place twice: it routes the
# lexicon, and it is itself a signal -- a Swedish-language posting at a
# Stockholm firm is a local hire and an English one at the same firm is often
# the international desk. It is also what keeps a French production-line
# advertisement off a hand-labelling sheet.
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

    letters = sum(1 for character in text if character.isalpha())
    cjk = len(_CJK.findall(text))
    # A script beats a word list, but only when it is carrying the sentence --
    # `Land Acquisition Manager, Data Center アクイジション` is an English title
    # with a Japanese fragment glued on the end.
    if letters and cjk / letters > 0.30:
        return "cjk", f"{cjk} CJK characters"

    tokens = _WORD.findall(text.casefold())
    if not tokens:
        return "unknown", None
    seen = set(tokens)
    scores = {
        code: sum(1 for token in tokens if token in words)
        for code, words in _STOPWORDS.items()
    }
    best = max(scores, key=lambda code: (scores[code], code == "en"))
    if scores[best] < MIN_STOPWORDS:
        return "unknown", None
    hits = sorted(seen & _STOPWORDS[best])[:4]
    return best, f"{scores[best]}x {', '.join(hits)}"

# Exclusions safe to read out of a body. Everything absent from this set is
# matched against the title only, because it is ordinary job-specification
# language wherever else it appears -- *communications*, *marketing*,
# *accounting*, *recruitment*, *payroll*. These are not: no quant posting
# mentions an actuary, a blockchain or an FPGA in passing.
_BODY_SAFE_EXCLUSIONS = frozenset(
    {"actuarial", "insurance_pricing", "insurance_ops", "crypto_web3", "heavy_systems"}
)

# Distance from the user's centre, which is modelling and research. The three
# groups are what turn a `role_class` into a `relevance`, and they are separate
# from it on purpose: the class says which direction a posting lies in, and
# the relevance says how far. One scale carrying both is what made `adjacent`
# mean two opposite things in the first hand-labelled sample.
_CENTRE = frozenset({"quant_research", "data_science", "portfolio_management"})
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
    text = fold(row["title"], body, row["department"])
    where = fold(row["location"], row["title"])
    # A body was read, so its tags are evidence. A title alone is a guess that
    # happens to be usually right, which is what `weak` has always meant here.
    grade = "strong" if len(body) > 200 else "weak"

    key = (row["ats"], row["token"], row["job_id"])
    tags: list[Tag] = []

    def add(dimension: str, value: str, evidence: str | None, confidence: str = "") -> None:
        tags.append(Tag(*key, dimension, value, confidence or grade, evidence))

    # **The title decides what the role is; the body decides everything else.**
    # Body text is boilerplate on this question -- "strong quantitative
    # skills" appears in the description of an insurance accounting job, and
    # every bank's about-us paragraph names market and credit risk. Scoring
    # relevance over the body made `Insurance Accounting & Reporting
    # Specialist` a core quant role three times over.
    #
    # This is not classifying on the title alone, which `CLAUDE.md` forbids:
    # a title carrying no signal at all still falls through to the body, and
    # seniority, gates, languages and asset class are read from the body
    # throughout. It is the title winning where the two disagree about what
    # the job *is*.
    title = fold(row["title"], row["department"])
    just_title = fold(row["title"])
    just_body = fold(body)

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
    elif trade:
        off_industry = f"title {trade!r}"
    elif compounded_trade := _compound(just_title, _TRADE_HEADS):
        # `Elsäljare` and `Fältsäljare` are one token each, so no needle sees
        # them. Read from the title alone, never the department: a
        # `Säljarstöd` department on a markets posting is the firm's org chart.
        off_industry = f"title {compounded_trade!r}"
    else:
        off_industry = None

    # Exclusions are read from the **title**, and from the body only for the
    # handful of words that are never boilerplate. A Schonfeld quant posting
    # was tagged `support_function` on the word *communications*, from the
    # line "maintain strong stakeholder communications" -- a sentence in every
    # job specification ever written. `marketing`, `accounting`, `recruitment`
    # and `payroll` fail the same way; `actuary`, `crypto` and `fpga` do not,
    # because no quant posting mentions them in passing.
    exclusions = _every(_EXCLUSION, title)
    named = {value for value, _ in exclusions}
    exclusions += [
        (value, evidence)
        for value, evidence in _every(_EXCLUSION, just_body)
        if value not in named and value in _BODY_SAFE_EXCLUSIONS
    ]
    rejecting = [v for v, _ in exclusions if v not in ("crypto_web3", "heavy_systems")]
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
    # rejected outright as desk support -- the first false rejection the
    # hand-labelled sheet found, and the exact failure this rule was written
    # to prevent. The desk's name is not the role's name, and a department is
    # nothing but the desk's name.
    desk = _hit(fold(row["title"]), _DESK_ADJACENT)

    # A management title outranks a weak positive, the same way an exclusion
    # does. `Director of Trading`, `Head of Managed Accounts`, `Applied Science
    # Leader` and `Product Manager - B2C Credit` all reached `adjacent` on one
    # ordinary word -- *trading*, *data science*, *model validation* -- while
    # the thing the title actually announces is that somebody else does the
    # work. An unambiguous quant word still wins: `Head of Quantitative
    # Research` is a quant role with a management grade, and the seniority
    # dimension is what says so.
    # Read from the job title alone, for the same reason as `desk` above and
    # the same reason `judge` uses `just_title` for its officer test:
    # `Associate - Fund Governance` sits in a department called *Director
    # Services*, and a department is not a grade. That posting is named in the
    # seniority comments already, and it was still being rejected here.
    management = (
        _hit(just_title, _MANAGEMENT)
        if not _hit(just_title, _NOT_MANAGEMENT) else None
    )

    # A software-specialty title outranks a weak positive, for the same reason
    # a management title does: the title has already said what the job is, and
    # the quant-sounding word beside it is the name of the system rather than
    # the work. Read from the job title alone, like `desk` and `management`
    # above -- `Data Infrastructure Engineer` sits in a department called
    # *Engineering*, and a department is not a role. See `_SOFTWARE_SPECIALTY`.
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
    # one word in the title. `Quantitative Trader` and `Energy Trader` are
    # both `role_class: trading` and only one of them is the job -- so the
    # split gets its own dimension rather than a rank.
    #
    # **A dimension rather than a rank, and that was re-tested rather than
    # assumed.** Feeding this into `_relevance_of` looked obviously right and
    # measured at one row out of eighty; see that function for why the sheet
    # cannot settle it.
    #
    # Read from the **title alone**, deliberately. `role_class` falls back to
    # the body, and over a Kraken posting body that fallback files SOX
    # auditors and product designers as trading. A dimension whose whole
    # purpose is to be precise about traders cannot inherit that.
    # The seat, not the word. `_ROLE_CLASS["trading"]` includes bare
    # *trading*, which is the name of a department and appears in `Backend
    # Engineer - Trading & Asset Optimization` and `Account Manager (Wholesale
    # & Trading)`. Both came back as pure traders. Only the nouns for the job
    # itself count here.
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
        # Analyst - Data Governance` says "model validation" once, in the way
        # every governance document does, and came back as research work.
        #
        # A second, distinct phrase is what makes it evidence. That is the rule
        # `domains.py` arrived at for the same reason one layer down: a
        # fragment needs a corroborating word before it counts, because a
        # single ordinary phrase proves nothing about the document it sits in.
        #
        # **Which phrases are read matters as much as how many.** This counted
        # bare `quantitative` until the hand-labelled sheet caught it, and a
        # bare adjective is the one word every employer writes about every
        # role -- so `_QUANT_CORE_BODY` drops them and the count is over
        # phrases that mean something. Two of those still beat one, because
        # the corroboration here is one body against itself; `judge`, below,
        # asks the stronger question of whether the posting is in markets at
        # all.
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
    elif exclusions:
        add("relevance", "rejected", f"{exclusions[0][0]}")
    elif (call := lexicon.judge(row["title"], row["department"], body)).verdict == "reject":
        # **The last word goes to the module written to say what a posting is
        # not**, and until now nothing asked it. `lexicon.judge` carries the
        # long occupation lists -- wealth advisers, counsel, directors, named
        # trades -- while `_EXCLUSION` above carries seven categories, so a
        # `Wealth Advisor` or an `Alliance Director` fell through both and was
        # reported as `unknown`: "nothing looked at this", when in fact three
        # rules had and none of them covered it.
        #
        # It runs **last on purpose**. It can only ever convert an `unknown`,
        # never overturn a positive, so a title that already said *quant* is
        # out of its reach and it cannot manufacture a false rejection in the
        # rows that matter.
        add("relevance", "rejected", f"{call.reason}: {call.evidence or 'no signal'}")
    else:
        add("relevance", "unknown", None)

    # Asset class from the title first, and from the body only as a fallback
    # graded `weak`. Schonfeld's every posting listed `rates` because the
    # "Who We Are" paragraph names the firm's four strategies -- "Quant,
    # Tactical, Fundamental Equity and Discretionary Macro & Fixed Income" --
    # which describes the employer and not the desk. The body reading is kept
    # rather than dropped, because for the 81% of postings with no body at all
    # it is the only reading there is; it just no longer claims to be evidence.
    named_assets = _every(_ASSET_CLASS, title)
    for value, evidence in named_assets:
        add("asset_class", value, f"title {evidence!r}")
    if not named_assets:
        from_body = _every(_ASSET_CLASS, text)
        for value, evidence in from_body:
            add("asset_class", value, f"body {evidence!r}", "weak")
        if not from_body:
            add("asset_class", "unstated", None)

    hard: set[str] = set()
    for dimension, mapping in (("horizon", _HORIZON), ("hard_gates", _HARD_GATES)):
        found = _every(mapping, text)
        if dimension == "hard_gates" and _hit(text, _PHD_NOT_REQUIRED):
            # " no phd required " contains " phd required ", so a posting
            # saying the opposite of the gate would otherwise trip it.
            found = [(v, e) for v, e in found if v != "phd_required"]
        for value, evidence in found:
            add(dimension, value, f"{evidence!r}")
            if dimension == "hard_gates":
                hard.add(value)
        if not found:
            add(dimension, "unknown", None)

    # **A compulsory doctorate is an eligibility fact, and it gates.** Two
    # hand-labelled rows say so: `Quantitative Researcher (Full-Time - PhD+)`
    # and `PhD Degree Required - Quantitative Analyst/Programmer` were both
    # labelled `rejected`, with the note *"perfect fit - but has hard
    # requirement of phd"*.
    #
    # "Perfect fit" is the important half. The *relevance* of those postings is
    # `relevant` and stays `relevant` -- the role is exactly this line of work,
    # and saying otherwise would put an eligibility fact on a scale that
    # measures subject matter. That is the mistake this file finished unwinding
    # for `student_intern`, at the user's own decision, and `student_only`
    # lives in `hard_gates` for the same reason.
    #
    # So it comes off the *board* rather than out of the *verdict*, which is
    # what a gate is for: the row stays in `jobs`, the tag keeps its evidence,
    # and `list --exclude phd_required` shows what it ate. One line in `GATES`
    # puts them back, with no re-tag.
    if "phd_required" in hard:
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

    # Seniority follows the same rule as relevance, and for the same reason.
    # A body saying "you will report to the Head of Trading" made *Graduate
    # Trader* a `head_or_md` posting, and one saying "work with senior
    # colleagues" made it `senior_6_10`. The rank is in the title.
    #
    # **Title only, and the body now reaches rank through one door**: an
    # explicit years figure. The student gate was the second door and it has
    # been closed -- being a student is an eligibility fact rather than a
    # grade, so it is `hard_gates: student_only` now. See `_SENIORITY`.
    #
    # The old fall-through to the body was the same bug `PLAN.md` recorded and
    # only half fixed. It said "the rank is in the title" and then, whenever a
    # title carried no grade word at all, read the body anyway -- where every
    # authority word is furniture. Schonfeld's `Quantitative Research /
    # Developer - Intern` came back `head_or_md` on the word *partner*, from
    # the diversity paragraph at the bottom of the advertisement, and that one
    # tag moved it from the shortlist to `stretch`.
    #
    # Losing a real "Senior" mentioned only in a body costs an over-rating,
    # which is the cheap direction. Inventing a managing director costs the
    # posting.
    # **`just_title`, not `title`.** Every comment in this block says the rank
    # is read from the title alone, and the argument was made twice over -- and
    # the code passed `fold(title, department)`, which is the title *and the
    # department*. It went unnoticed while the needles were words like `head
    # of` that a department rarely carries. Bare `director` is not one of
    # those: `Associate - Fund Governance` sits in a department called
    # *Director Services*, and that posting is named in the comments here
    # already as the case this must not get wrong.
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

    # **A rank nobody reaches from under a year of experience.** Read from the
    # title only, exactly as `seniority` is, and gated on a *positive* reading:
    # a posting whose title carries no grade word at all comes back `unknown`
    # and stays on the board. That asymmetry is the whole safety property --
    # the gate can only fire on evidence, never on the absence of it.
    #
    # `vice president` is here now and `PLAN.md` records the argument for
    # keeping it out: at a bank it is a mid-career grade rather than an officer
    # title. Both halves are true, and they point the same way for this reader
    # -- a bank's five-year VP hire is as far out of reach as a real one.
    out_of_reach = None
    if management:
        out_of_reach = f"management title: {management!r}"
    elif compounded := _compound_manager(just_title):
        out_of_reach = f"management title: {compounded!r}"
    elif seniority_value in _OUT_OF_REACH:
        out_of_reach = f"seniority: {seniority_value}"
    if out_of_reach:
        add("exclusion_reason", "out_of_reach", out_of_reach)

    # `other` and `unknown` are different facts and the difference is the whole
    # discipline: `other` is a place we read and it was Bangalore, Pune or
    # Massachusetts; `unknown` is a posting with no location at all. Collapsing
    # them reported 92% of the corpus as ungeolocated when most of it is simply
    # somewhere else.
    hub = _first(_HUBS, where)
    raw = (row["location"] or "").strip()
    if hub:
        hub_value = hub[0]
        add("hub", hub_value, f"{hub[1]!r}", "strong")
    elif state := _US_STATE.search(raw):
        hub_value = "deprioritized"
        add("hub", hub_value, f"us state {state.group(1).upper()!r}", "strong")
    elif raw and not _NO_PLACE.match(raw):
        hub_value = "other"
        add("hub", hub_value, f"{raw[:40]!r}", "strong")
    else:
        # Either no location at all, or one that names no place -- Workday's
        # `2 Locations`, a bare `Remote`. Both are "we do not know", and the
        # board keeps `unknown` while it drops `other`.
        hub_value = "unknown"
        add("hub", hub_value, f"{raw[:40]!r}" if raw else None, "strong")

    # **Geography gates now, and this is a deliberate departure from a rule
    # written all over this repo.** "Geography ranks, it never gates" is about
    # the *universe*: a firm or a posting is never dropped from the database
    # for being out of area, and it still is not -- the row keeps its place in
    # `jobs`, this tag records the reason, and re-running rebuilds it. What
    # changed is the reader's own instruction about the reader's own board: a
    # job in Kiruna, Barcelona or Paris is not one they will take, so ranking
    # it below Amsterdam is answering a question they did not ask.
    #
    # It stays inside principle 4 the same way `off_industry` does, and it is
    # the reason `_HUBS` had to become city-precise first. A gate on a label
    # that says "Stockholm" when it means "somewhere in Sweden" deletes exactly
    # the wrong postings.
    if hub_value not in BOARD_HUBS:
        add("exclusion_reason", "off_location", f"{hub_value}: {raw[:40]!r}")

    return tags


def _fit(tags: list[Tag]) -> Tag:
    """The one dimension that encodes the user's profile.

    Under a year of experience, already graduated, Python and research rather
    than C++ and systems. Advisory only -- `out_of_scope` still keeps its row.
    """
    single = {
        tag.dimension: tag.value
        for tag in tags
        if tag.dimension in ("seniority", "relevance", "code_depth", "hub",
                             "experience_floor", "desk")
    }
    seniority = single.get("seniority", "unknown")
    relevance = single.get("relevance", "unknown")
    depth = single.get("code_depth", "unknown")
    hub = single.get("hub", "unknown")
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

    # Every soft filter is a notch, and they compose. None of them rejects:
    # each is a reason a posting is further away rather than a reason it is
    # not a posting, which is the same call `PLAN.md` made about geography and
    # the same asymmetry the whole project runs on.
    notches: list[str] = []
    # A relevance read out of the body because the title said nothing is the
    # weakest evidence here: `Executive Assistant` and `Full Stack Engineer`
    # reached the shortlist that way, on a body that mentions quant work
    # because the firm does quant work.
    if any(tag.dimension == "relevance" and (tag.evidence or "").startswith("body only")
           for tag in tags):
        notches.append("title said nothing")
    # Geography ranks results; it never gates them. A core quant role in São
    # Paulo is a real posting and keeps its row, but it should not outrank one
    # in Amsterdam -- and it did: Santander's global board filled the shortlist
    # from `hub: other` while Stockholm showed one entry.
    if hub not in _FOCUS_HUBS:
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
    # Under a year of experience: a senior posting is a stretch however well
    # the subject matter fits, and saying so is the whole point of the
    # dimension. `CLAUDE.md` puts "too senior" on the exclude list.
    if seniority in ("head_or_md", "lead", "senior_6_10"):
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

    This is where filtering belongs. Nothing is dropped at ingest -- principle
    4, and it has earned itself here repeatedly: every lexicon bug found so far
    was fixed by re-running over stored rows, which a write-time filter would
    have thrown away. Reading is the reversible end.

    `require` is AND across dimensions and OR within one, which is what a
    person actually means: hub in (amsterdam, stockholm) *and* fit in
    (apply_now, strong). `exclude` drops a posting carrying any listed value,
    so one `crypto_web3` tag is enough to lose it.
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
               (SELECT value FROM job_tags v WHERE v.ats = j.ats
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
               (SELECT value FROM job_tags h WHERE h.ats = j.ats
                 AND h.token = j.token AND h.job_id = j.job_id
                 AND h.dimension = 'hub') AS hub
        FROM job_tags f
        JOIN jobs j ON j.ats = f.ats AND j.token = f.token AND j.job_id = f.job_id
        WHERE f.dimension = 'fit' AND f.value IN ('apply_now', 'strong')
          AND f.tagger = ? AND j.removed_at IS NULL
        ORDER BY CASE f.value WHEN 'apply_now' THEN 0 ELSE 1 END, j.first_seen DESC
        LIMIT ?
        """,
        (TAGGER, limit),
    ).fetchall()
