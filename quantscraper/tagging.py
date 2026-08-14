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
TAGGER = 7

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
)


def fold(*parts: str | None) -> str:
    """Everything folded to lowercase tokens, padded so needles can be too."""
    text = " ".join(part for part in parts if part)
    text = _TAGS.sub(" ", text).casefold()
    for symbol, replacement in _SYMBOLS:
        text = text.replace(symbol, replacement)
    return " " + " ".join(re.sub(r"[^a-z0-9+#]+", " ", text).split()) + " "


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
    "trade support", "operations analyst", "recruiter", "recruitment",
    "sales trader", "client service", "compliance",
)

_QUANT_ADJACENT = (
    "trading", "researcher", "data scientist", "data science", "machine learning", "deep learning",
    "statistician", "statistics", "econometrics", "financial engineering",
    "pricing analyst", "portfolio analyst", "investment analyst",
    "risk analyst", "analytics", "research engineer", "datavetenskap",
)

_ROLE_FAMILY = {
    "research": (
        "research", "researcher", "alpha research", "signal research",
        "forskning", "onderzoek", "recherche",
    ),
    "trading": (
        "trader", "trading", "market making", "market maker", "handelaar",
        "handlare", "haendler",
    ),
    "quant_dev": (
        "quant developer", "quantitative developer", "quant dev",
        "software engineer", "developer", "utvecklare", "ontwikkelaar",
        "engineer", "programmer",
    ),
    "risk": ("risk", "risiko", "risico", "risque", "riskhantering"),
    "model_validation": ("model validation", "model risk", "validation"),
    "data_science": ("data scientist", "data science", "machine learning"),
    "portfolio_construction": ("portfolio construction", "portfolio manager"),
    "execution": ("execution", "algo execution", "transaction cost"),
    "strategist": ("strategist", "strat", "strats", "strateg"),
}

# `student_only` is its own bucket rather than a flavour of intern: the user
# has graduated, so a posting demanding a *future* graduation date is noise --
# and it is noise a title never announces.
_SENIORITY = {
    "student_only": (
        "currently enrolled", "must be enrolled", "final year student",
        "final year students", "penultimate year", "graduating in 2027",
        "graduating in 2028", "studerande", "student", "students",
    ),
    "intern": ("intern", "internship", "praktik", "stage", "praktikant"),
    "new_grad": (
        "graduate programme", "graduate program", "new grad", "campus hire",
        "traineeprogram", "trainee",
    ),
    "head_or_md": (
        "head of", "managing director", "chief", "partner", "global head",
        "director of",
    ),
    "lead": ("lead", "principal", "staff engineer", "team lead"),
    "senior_6_10": (
        "senior", "vp", "vice president", "erfaren", "associate director",
        "executive director", "avp",
    ),
    "junior_0_2": ("junior", "associate", "entry level", "graduate"),
}

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
    "phd_required": ("phd required", "phd is required", "must hold a phd", "doctorate required"),
    "visa_sponsorship_none": (
        "no visa sponsorship", "not able to sponsor", "unable to sponsor",
        "without sponsorship", "must have the right to work",
    ),
    "security_clearance": ("security clearance", "clearance required"),
    "local_language_required": (
        "fluent in swedish", "fluent in danish", "fluent in dutch",
        "fluent in german", "flytande svenska", "vloeiend nederlands",
        "dansk pa modersmalsniveau",
    ),
    "onsite_only": ("onsite only", "fully onsite", "in office five days", "no remote"),
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

    Order is the priority: `student_only` before `intern`, `hardware` before
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
    core = _hit(title, _QUANT_CORE + _QUANT_CORE_TITLE)
    adjacent = _hit(title, _QUANT_ADJACENT)
    desk = _hit(title, _DESK_ADJACENT)

    if desk and not core:
        # "Trading Operations Engineer" is not a trading role, and neither is
        # "Campus Recruiter" filed under a Trading department.
        add("relevance", "rejected", f"desk support: {desk!r}")
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

    for dimension, mapping in (
        ("role_family", _ROLE_FAMILY),
        ("asset_class", _ASSET_CLASS),
        ("horizon", _HORIZON),
        ("hard_gates", _HARD_GATES),
    ):
        found = _every(mapping, text)
        for value, evidence in found:
            add(dimension, value, f"{evidence!r}")
        if not found:
            add(dimension, "unknown" if dimension != "asset_class" else "unstated", None)

    for dimension, mapping in (
        ("seniority", _SENIORITY),
        ("code_depth", _CODE_DEPTH),
        ("contract", _CONTRACT),
    ):
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

    def make(bucket: str, why: str) -> Tag:
        if body_only:
            bucket, why = _CAP.get(bucket, bucket), f"{why}; title said nothing"
        return Tag(*key, "fit", bucket, "weak", why)

    if seniority == "student_only":
        return make("out_of_scope", "requires a future graduation date")
    if relevance == "rejected":
        return make("out_of_scope", f"excluded: {'/'.join(sorted(gates)) or 'no quant signal'}")
    # Under a year of experience: a senior posting is a stretch however well
    # the subject matter fits, and saying so is the whole point of the
    # dimension. `CLAUDE.md` puts "too senior" on the exclude list.
    if seniority in ("head_or_md", "lead", "senior_6_10"):
        return make("stretch", f"seniority {seniority}")
    if relevance == "core" and seniority in ("junior_0_2", "new_grad", "intern"):
        focus = hub in ("stockholm", "copenhagen", "amsterdam", "switzerland",
                        "hong_kong", "singapore")
        return make("apply_now" if focus else "strong", f"core quant, {seniority}, {hub}")
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
