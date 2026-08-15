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

from . import db

# Bump on every lexicon change: the diff between two versions over the same
# corpus is a free regression test, and it is the only way to tell "the
# classifier improved" from "the market moved".
TAGGER = 11

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


def fold(*parts: str | None) -> str:
    """Everything folded to lowercase tokens, padded so needles can be too."""
    text = " ".join(part for part in parts if part)
    text = _TAGS.sub(" ", text).casefold()
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
    "statistical arbitrage", "stat arb", "alpha research", "signal research",
    "alpha generation", "execution research", "model validation",
    "risk quant", "kwantitatief", "quantitatif",
)

# These name the role in a title and are boilerplate in a body. Every finance
# company's "about us" mentions market and credit risk, which scored
# `Interest & Product Logic Specialist` and `Insurance Accounting Specialist`
# as core quant roles. In a title the same words are the job.
_QUANT_CORE_TITLE = (
    "trader", "trading strategist", "strat", "strats", "research analyst",
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

_QUANT_ADJACENT = (
    "trading", "researcher", "data scientist", "data science", "machine learning", "deep learning",
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
# Order is the priority and it carries two deliberate decisions:
#
# - `operations` runs first so "Trading Operations Analyst" is operations
#   rather than trading. The desk's name is not the role's name -- the same
#   rule that stopped `Trading Operations Engineer` scoring as a trading role.
# - `quant_dev` runs before `quant_research` so a title naming both -- and
#   `Quantitative Research / Developer` is a real posting, folding to
#   "research developer" -- lands on the building half. A title that says only
#   *researcher* still falls through to `quant_research` on the next line.
_ROLE_CLASS = {
    "operations": _terms(
        "trading operations", "trade operations", "trading services",
        "trade support", "trading support", "middle office", "back office",
        "settlements", "reconciliation", "reconciliations", "trade lifecycle",
        "operations analyst", "operations associate", "trade capture",
        "corporate actions", "post trade", "handelsstod",
    ),
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
        "researcher", "research analyst", "kvantitativ analytiker",
        "kvantitativ", "forskning", "onderzoek", "recherche",
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
# `student_intern` stays in the ladder because it is genuinely a rank: a
# posting requiring a *future* graduation date is unreachable for someone who
# has already graduated, whatever else it says.
_SENIORITY = {
    # Specific phrases only. A bare "student" or "students" fired on any body
    # that merely welcomes them, and marked a full-time PhD-level research
    # role at Radix Trading as student-only.
    "student_intern": _terms(
        "currently enrolled", "must be enrolled", "final year student",
        "final year students", "penultimate year", "still studying",
        "graduating in 2027", "graduating in 2028", "graduating in 2029",
        "expected graduation", "pursuing a degree", "studerande vid",
    ),
    "head_or_md": _terms(
        "head of", "managing director", "chief", "partner", "global head",
        "director of",
    ),
    "lead": _terms("lead", "principal", "staff engineer", "team lead"),
    "senior_6_10": _terms(
        "senior", "vp", "vice president", "erfaren", "associate director",
        "executive director", "avp",
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
# `head_or_md`, `lead` or `student_intern`, because those are structural facts
# about the role rather than a length of service.
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
    "phd_required": _terms(
        "phd required", "phd is required", "phd is a requirement",
        "must hold a phd", "must have a phd", "requires a phd",
        "phd mandatory", "phd degree required", "doctorate required",
        "doctorate is required", "phd essential",
    ),
    "visa_sponsorship_none": _terms(
        "no visa sponsorship", "not able to sponsor", "unable to sponsor",
        "without sponsorship", "must have the right to work",
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
_SPOKEN_REQUIRED = {
    "dutch": _terms(
        "fluent in dutch", "dutch is required", "dutch fluency", "native dutch",
        "dutch speaking", "vloeiend nederlands", "nederlands is vereist"),
    "german": _terms(
        "fluent in german", "german is required", "german fluency",
        "native german", "verhandlungssicher", "gute deutschkenntnisse",
        "deutsch erforderlich"),
    "danish": _terms(
        "fluent in danish", "danish is required", "native danish",
        "dansk pa modersmalsniveau", "flydende dansk"),
    "norwegian": _terms(
        "fluent in norwegian", "norwegian is required", "native norwegian",
        "flytende norsk"),
    "finnish": _terms(
        "fluent in finnish", "finnish is required", "native finnish"),
    "french": _terms(
        "fluent in french", "french is required", "french fluency",
        "native french", "francais courant"),
    "mandarin": _terms(
        "fluent in mandarin", "mandarin is required", "native mandarin",
        "fluent in chinese", "mandarin chinese is required", "putonghua",
        "fluency in mandarin"),
    "cantonese": _terms(
        "fluent in cantonese", "cantonese is required", "native cantonese",
        "fluency in cantonese"),
    "japanese": _terms(
        "fluent in japanese", "japanese is required", "native japanese"),
    "spanish": _terms(
        "fluent in spanish", "spanish is required", "native spanish"),
    "italian": _terms(
        "fluent in italian", "italian is required", "native italian"),
    "portuguese": _terms(
        "fluent in portuguese", "portuguese is required", "native portuguese"),
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
    "insurance_pricing": ("insurance pricing", "underwriting", "claims", "skadereglering"),
    "non_markets_fintech": ("payments", "kyc", "aml", "fraud detection", "lending platform"),
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
}

_HUBS = {
    "stockholm": ("stockholm", "sverige", "sweden", "solna", "goteborg"),
    "copenhagen": ("copenhagen", "kobenhavn", "denmark", "danmark"),
    "amsterdam": ("amsterdam", "netherlands", "nederland", "rotterdam", "utrecht"),
    "switzerland": ("zurich", "geneva", "zug", "switzerland", "schweiz", "suisse"),
    "hong_kong": ("hong kong", "hongkong", "kowloon"),
    "singapore": ("singapore",),
    "deprioritized": (
        "london", "united kingdom", "new york", "chicago", "germany",
        "frankfurt", "munich", "dubai", "shanghai", "beijing", "united states",
    ),
}


_FOCUS_HUBS = frozenset(
    {"stockholm", "copenhagen", "amsterdam", "switzerland", "hong_kong", "singapore"}
)


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

    exclusions = _every(_EXCLUSION, text)
    rejecting = [v for v, _ in exclusions if v not in ("crypto_web3", "heavy_systems")]

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
    desk = _hit(title, _DESK_ADJACENT)

    if desk and not core:
        # "Trading Operations Engineer" is not a trading role, and neither is
        # "Campus Recruiter" filed under a Trading department.
        add("relevance", "rejected", f"desk support: {desk!r}")
    elif desk and not certain:
        # A desk word beside a domain word demotes, it does not reject. A
        # missed posting is the expensive failure here, so `Algorithmic Sales
        # Trader` stays readable at a lower rank rather than disappearing.
        add("relevance", "adjacent", f"{domain_only!r} qualified by {desk!r}")
    elif core:
        add("relevance", "core", f"title {core!r}")
    elif rejecting:
        # Ahead of `adjacent`, because an exclusion outranks a weak positive:
        # "Actuarial Pricing Analyst" matched *pricing analyst* and came back
        # adjacent, and actuarial work is on the exclude list outright.
        add("relevance", "rejected", f"{rejecting[0]}, no quant signal in title")
    elif adjacent:
        add("relevance", "adjacent", f"title {adjacent!r}")
    elif body_core := _hit(text, _QUANT_CORE):
        # Nothing in the title said anything, so the body is all there is.
        # Weak by construction, whatever the body's length.
        add("relevance", "core", f"body only {body_core!r}", "weak")
    elif exclusions:
        add("relevance", "rejected", f"{exclusions[0][0]}")
    else:
        add("relevance", "unknown", None)

    # One value, and from the title first. `_ROLE_CLASS` replaced the
    # multi-valued `role_family` because seven values is a word count rather
    # than a classification, and its order is the priority: `operations`
    # before `trading` so "Trading Operations Analyst" is operations, and
    # `quant_dev` before `quant_research` so a title naming both lands on the
    # building half. Reading the title first is what makes that order mean
    # anything -- over a long body every class matches something.
    role = _first(_ROLE_CLASS, title) or _first(_ROLE_CLASS, text)
    add("role_class", role[0] if role else "unknown", f"{role[1]!r}" if role else None)

    for dimension, mapping in (
        ("asset_class", _ASSET_CLASS),
        ("horizon", _HORIZON),
        ("hard_gates", _HARD_GATES),
    ):
        found = _every(mapping, text)
        for value, evidence in found:
            add(dimension, value, f"{evidence!r}")
        if not found:
            add(dimension, "unknown" if dimension != "asset_class" else "unstated", None)

    # Seniority follows the same rule as relevance, and for the same reason.
    # A body saying "you will report to the Head of Trading" made *Graduate
    # Trader* a `head_or_md` posting, and one saying "work with senior
    # colleagues" made it `senior_6_10`. The rank is in the title.
    #
    # `student_intern` is the exception and is checked against the body first,
    # because that is the only place it is ever written: no title announces
    # "must be graduating in 2028", which is exactly why it needs its own
    # bucket. Its needles are specific phrases for the same reason -- a bare
    # "students" tripped on bodies that merely welcome them.
    gate = _hit(text, _SENIORITY["student_intern"])
    rank = _first(_SENIORITY, title) or _first(_SENIORITY, text)
    if gate:
        add("seniority", "student_intern", f"{gate!r}")
    else:
        add("seniority", rank[0] if rank else "unknown", f"{rank[1]!r}" if rank else None)

    for dimension, mapping in (("code_depth", _CODE_DEPTH), ("contract", _CONTRACT)):
        found = _first(mapping, text)
        add(dimension, found[0] if found else "unknown", f"{found[1]!r}" if found else None)

    for language in _LANGUAGES:
        if f" {language} " in text:
            add("language", language, None)

    for value, evidence in exclusions:
        add("exclusion_reason", value, f"{evidence!r}")

    # `other` and `unknown` are different facts and the difference is the whole
    # discipline: `other` is a place we read and it was Bangalore, Pune or
    # Massachusetts; `unknown` is a posting with no location at all. Collapsing
    # them reported 92% of the corpus as ungeolocated when most of it is simply
    # somewhere else.
    hub = _first(_HUBS, where)
    if hub:
        add("hub", hub[0], f"{hub[1]!r}", "strong")
    elif (row["location"] or "").strip():
        add("hub", "other", f"{row['location'][:40]!r}", "strong")
    else:
        add("hub", "unknown", None, "strong")

    return tags


def _fit(tags: list[Tag]) -> Tag:
    """The one dimension that encodes the user's profile.

    Under a year of experience, already graduated, Python and research rather
    than C++ and systems. Advisory only -- `out_of_scope` still keeps its row.
    """
    value = {tag.dimension: tag.value for tag in tags if tag.dimension != "language"}
    seniority = value.get("seniority", "unknown")
    relevance = value.get("relevance", "unknown")
    depth = value.get("code_depth", "unknown")
    hub = value.get("hub", "unknown")
    gates = {tag.value for tag in tags if tag.dimension == "exclusion_reason"}

    key = (tags[0].ats, tags[0].token, tags[0].job_id)
    # A relevance read out of the body because the title said nothing is the
    # weakest evidence here: `Executive Assistant` and `Full Stack Engineer`
    # reached the shortlist that way, on a body that mentions quant work
    # because the firm does quant work. Capped one notch down.
    body_only = any(
        tag.dimension == "relevance" and (tag.evidence or "").startswith("body only")
        for tag in tags
    )
    _CAP = {"apply_now": "strong", "strong": "plausible"}
    # Geography ranks results; it never gates them. A core quant role in São
    # Paulo is a real posting and keeps its row, but it should not outrank one
    # in Amsterdam -- and it did: Santander's global board filled the shortlist
    # from `hub: other` while Stockholm showed one entry.
    outside = hub not in _FOCUS_HUBS

    def make(bucket: str, why: str) -> Tag:
        if body_only:
            bucket, why = _CAP.get(bucket, bucket), f"{why}; title said nothing"
        if outside and bucket in _CAP:
            bucket, why = _CAP[bucket], f"{why}; outside the focus hubs"
        return Tag(*key, "fit", bucket, "weak", why)

    if seniority == "student_intern":
        return make("out_of_scope", "requires a future graduation date")
    if relevance == "rejected":
        return make("out_of_scope", f"excluded: {'/'.join(sorted(gates)) or 'no quant signal'}")
    # Under a year of experience: a senior posting is a stretch however well
    # the subject matter fits, and saying so is the whole point of the
    # dimension. `CLAUDE.md` puts "too senior" on the exclude list.
    if seniority in ("head_or_md", "lead", "senior_6_10"):
        return make("stretch", f"seniority {seniority}")
    if relevance == "core" and seniority in ("junior_0_2", "new_grad"):
        return make("apply_now", f"core quant, {seniority}, {hub}")
    if relevance == "core":
        if depth in ("systems", "hardware"):
            return make("plausible", f"core quant but {depth}")
        return make("strong", f"core quant, seniority {seniority}")
    if relevance == "adjacent":
        return make("plausible", "adjacent role family")
    return make("unknown", "nothing in the text decided it")


def postings(connection: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Postings with no tag from the current lexicon version."""
    return connection.execute(
        """
        SELECT j.ats, j.token, j.job_id, j.title, j.location, j.department,
               j.description
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
