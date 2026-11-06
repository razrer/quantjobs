"""User's quant-finance scope, separate from general markets relevance.

These are reversible display exclusions, not acquisition filters. A markets
employer or ordinary financial modelling is insufficient; actual trading,
quantitative model work and specialised trading/research engineering survive.
Inputs to ``exclusion`` are already folded by the tagger.
"""
from __future__ import annotations

import html
import re

from . import lexicon

STRICT_SUPPORT = (
    "legal", "counsel", "attorney", "lawyer", "paralegal", "jurist",
    "bolagsjurist", "juridisk", "advokat", "accountant", "accounting",
    "bookkeeping", "bookkeeper", "accounts payable", "accounts receivable",
    "financial accounts", "tax", "payroll", "redovisningsekonom",
    "redovisningsekonomer", "redovisningsansvarig", "ekonomiassistent",
    "recruiter", "recruitment", "talent acquisition", "human resources",
    "hr generalist", "hr specialist", "hr partner",
    "hr consultant", "hr technology", "people direct advisor",
    "personalansvarig", "ekonomiansvarig",
)

FINANCE_TITLES = (
    "portfolio manager", "portfolio management", "portfolio analyst",
    "portfolio associate", "portfolio specialist", "portfolio administrator",
    "investment manager", "investment management", "investment analyst",
    "investment associate", "investment officer", "investment counsellor",
    "investment counselor", "investment adviser", "investment advisor",
    "investment research", "investment banking", "investment banker",
    "equity research", "equities research", "credit research", "fundamental research",
    "equity capital markets", "debt capital markets", "corporate finance",
    "corporate development", "mergers and acquisitions", "leveraged finance",
    "wealth", "private banking", "private equity", "venture capital",
    "asset management", "fund manager", "fund management", "fund analyst",
    "fund administration", "fund services", "fund operations",
    "treasury", "treasurer", "cash management", "liquidity management",
    "financial analyst", "finance analyst", "finance associate", "controller",
    "financial reporting", "financial control", "product control",
    "audit", "auditor", "assurance", "compliance", "regulatory reporting",
    "risk reporting", "risk governance", "risk control", "risk controls",
    "credit officer", "credit analyst", "credit assessment",
    "operational risk", "enterprise risk", "business risk",
    "middle office", "back office", "trade support", "trading support",
    "backoffice", "backoffice administrator", "backofficekonsulter",
    "settlement analyst", "depositary officer", "fondadministrator",
    "vardepappersadministrator", "relationship associate",
    "trade operations", "trading operations", "settlements", "reconciliation",
    "client service", "client services", "client portfolio", "client processing",
    "relationship manager", "account manager", "accountmanager",
    "portfoljforvaltare", "portfoljforvaltning", "portfoljanalytiker",
    "kapitalforvaltare", "kapitalforvaltning", "fondforvaltare",
    "aktieforvaltare", "ranteforvaltare", "formueforvaltning",
    "formogenhetsforvaltning", "vermogensverwaltung", "vermogensbeheer",
    "gestion de portefeuille", "gestionnaire de portefeuille", "gerant de portefeuille",
)

# Fund and portfolio management seats. Most are conventional: a stock-picker's
# day holds no modelling. The user's rule is that one belongs on the board only
# when it is a quant job or adjacent to one, so these answer to `QUANT_FAMILIES`
# as well as to the duty sentences every other finance title answers to.
FUND_TITLES = (
    "portfolio manager", "portfolio management", "portfolio analyst",
    "investment manager", "investment management", "asset management",
    "fund manager", "fund management", "fund analyst",
    "portfoljforvaltare", "portfoljforvaltning", "portfoljanalytiker",
    "kapitalforvaltare", "kapitalforvaltning", "fondforvaltare",
    "aktieforvaltare", "ranteforvaltare",
)

# Work inside a fund house that is adjacent to quant whatever the rest of the
# posting says. Only consulted once `FUND_TITLES` has matched, so "Operational
# Risk Analyst" is still judged as the risk-control role it is.
FUND_ADJACENT_TITLES = (
    "risk analyst", "riskanalytiker", "riskanalys",
    "asset allocation", "tillgangsallokering", "allokeringsstrateg",
)

# Independent kinds of quantitative evidence. Counted by family, so that
# "kvantitativ" and "kvantitativa" are one signal and not two.
QUANT_FAMILIES = (
    ("python", "matlab", "programmering", "programming"),
    ("kvantitativ", "kvantitativa", "kvantitativt", "kvantitativ analys",
     "quantitative"),
    ("matematik", "mathematics", "statistik", "statistics", "statistical",
     "ekonometri", "econometrics"),
    ("optimering", "optimization", "optimisation", "portfoljoptimering"),
    ("machine learning", "maskininlarning"),
)
# One word proves nothing in a fund house, where an equity manager also "works
# with portfolio optimisation" and a skills list may mention Python. Three
# independent kinds were measured to separate Swedbank Robur's index manager and
# Entelios' power portfolio manager from AP3's and Alecta's stock-pickers.
QUANT_FAMILIES_REQUIRED = 3

# An internship is not a seat in the fund: the user has graduated and has ruled
# student internships out. Without this a dated SEB internship with no body read
# as adjacent on its title alone.
FUND_INTERN_TITLES = ("intern", "internship", "praktik", "praktikant", "praktikplats")

QUANT_TITLES = (
    "quant", "quants", "quantitative", "kvantitativ", "kvantitativa",
    "kvantitative", "kwantitatief", "quantitatif", "quantitativ",
    "systematic", "systematisk", "algorithmic", "algo", "strats",
    "statistical arbitrage", "alpha research", "signal research",
    "execution research", "portfolio construction", "portfolio optimization",
    "portfolio optimisation", "derivatives pricing", "options pricing",
    "model validation", "modellvalidering", "modelvalidering", "modellvalidierung",
    "model developer", "model development", "risk modelling", "risk modeling",
    "pricing models", "xva", "cva", "machine learning researcher",
)

TRADING_SEATS = ("trader", "traders", "market maker", "market making",
                 "handlare", "handelaar", "haendler")

TECH_TITLES = (
    "engineer", "developer", "development engineer", "programmer", "architect",
    "it analyst", "it specialist", "it support", "technology analyst",
    "technology consultant", "technical consultant", "systems analyst",
    "system analyst", "systems specialist", "system specialist",
    "systemspecialist", "systemforvaltare", "systemutvecklare", "utvecklare",
    "business analyst", "data scientist", "data science", "data analyst",
    "data architect", "data specialist", "data engineer", "analytics engineer",
    "devops", "cybersecurity", "cyber security", "information security",
    "informationssakerhet", "systems administrator", "database administrator",
    "scrum master", "product owner", "servicenow", "salesforce", "sharepoint",
    "microsoft 365", "microsoft dynamics 365", "it infrastructure specialist",
)

ENTERPRISE_IT = (
    "network reliability", "network engineer", "systems administrator",
    "system administrator", "database administrator", "desktop", "help desk",
    "service desk", "it support", "cybersecurity", "cyber security",
    "information security", "informationssakerhet", "servicenow", "salesforce",
    "sharepoint", "enterprise architect", "scrum master", "business systems",
    "microsoft 365", "microsoft dynamics 365", "mainframe",
    "it infrastructure specialist",
)

TRADING_TECH = (
    "trading systems", "trading system", "trading platform", "trading platforms",
    "trading infrastructure", "trading applications", "trading application",
    "trading and operational infrastructure", "trading software",
    "hpc", "high performance compute", "real time data distribution",
    "etrading", "e trading", "electronic trading", "algorithmic trading",
    "execution engine", "execution systems", "execution algorithms",
    "order management", "market data", "pricing engine", "pricing library",
    "pricing libraries", "risk engine", "research platform", "research infrastructure",
    "research engineer", "research engineering", "research tools", "low latency",
    "research technology", "strategy research", "portfolio engineer",
    "risk pricing", "risk technology",
    "real time trading", "live trading", "trading floor", "trading risk",
    "model computation", "signal generation", "quantitative research",
    "equities autocallables", "derivatives pricing", "kdb",
)

MODEL_WORK = (
    "quantitative models", "quantitative model", "pricing models", "pricing model",
    "risk models", "risk model", "credit models", "credit model",
    "model validation", "model development", "model calibration",
    "derivatives pricing", "options pricing", "stochastic models",
    "alpha signals", "alpha models", "factor models", "factor model",
    "model construction", "signal generation", "back testing",
    "systematic strategies", "systematic trading", "algorithmic trading",
    "portfolio optimization", "portfolio optimisation", "statistical models",
    "statistical modeling", "statistical modelling", "backtesting", "backtest",
    "execution algorithms", "volatility surface", "monte carlo",
    "utveckla modeller", "validera modeller", "kvantitativa modeller",
    "kvantitativ modellering", "kvantitativa metoder", "riskmodeller", "prismodeller",
    # Twice where a letter differs: `body` is folded to ASCII by the tagger, while
    # the duty sentences come through `lexicon.normalize`, which keeps it.
    "statistiska modeller", "portfoljoptimering", "portföljoptimering",
    "quantitative methodologies", "quantitative data models",
)

WORK_VERBS = (
    "develop", "developing", "design", "designing", "build", "building",
    "implement", "implementing", "calibrate", "calibrating", "validate",
    "validating", "backtest", "backtesting", "research", "researching",
    "optimise", "optimising", "optimize", "optimizing", "enhance", "enhancing",
    "maintain", "maintaining", "construct", "constructing", "test", "testing",
    "challenge",
    "utveckla", "utveckling", "validera", "validering", "anvanda", "använda", "bidra", "bygga",
    "analysera", "optimera", "modellera", "ta fram", "granska", "utvardera", "utvärdera",
)

SECTION_PATTERNS = (
    r"(?im)\b(?:responsibilities|what you(?:['’]ll| will) do|your (?:role|responsibilities)|role summary|position duties|key duties|arbetsuppgifter|det här kommer du att arbeta med|i rollen kommer du att|du kommer att)\b|^\s*(?:role|the role)\s*[:\n]",
    r"(?im)(?:^\s*|(?<=[.!?:])\s*)(?:qualifications|requirements|skills you|what (?:we offer|you(?:['’]ll)? bring)|the position requires|about (?:us|the company)|benefits|equal opportunity|vi söker dig|din profil|det är meriterande|vem är du|vi tror att du|din bakgrund)\b|\b(?-i:REQUIREMENTS|QUALIFICATIONS)\b",
)
RESEARCH_DATA = ("data pipelines", "features", "feature engineering", "datasets",
                 "research data", "data validation")
RESEARCH_PURPOSE = ("systematic portfolio managers", "predictive modelling in finance",
                    "quantitative research", "systematic strategies", "alpha signals")
BODY_WORK = MODEL_WORK + TRADING_TECH + RESEARCH_PURPOSE
TEASER_MARKERS = ("fejlmeld annonce", "tjek jobglaeden")

# These describe the work's subject, not the employer. Apply only to a
# responsibilities section; an introduction or skill list is insufficient.
NON_MARKETS_DUTIES = ("välfärdsbrott", "välfärdsbrottsligheten",
                      "felaktiga utbetalningar från välfärdsystemen")
RECRUITMENT_DUTIES = ("longlisting", "candidate contact", "executive search ats")


def _hit(text: str, terms: tuple[str, ...]) -> str | None:
    return lexicon.first(text, terms)


def _duties(description: str) -> tuple[list[str], str]:
    """Read work statements, excluding company introductions and skill lists."""
    text = re.sub(r"(?i)</(?:li|p|div|h[1-6])>|<br\s*/?>", "\n", description[:lexicon.MAX_BODY])
    text = html.unescape(re.sub(r"<[^>]{0,4000}>", " ", text))
    start = re.search(SECTION_PATTERNS[0], text)
    if start:
        text = text[start.end():]
        stop = re.search(SECTION_PATTERNS[1], text)
        if stop:
            text = text[:stop.start()]
    statements = []
    inherited_action = False
    for part in re.split(r"[\n;•]+|(?<=[.!?])\s+", text):
        normalized = lexicon.normalize(part)
        # Without a responsibilities section, require a sentence assigning
        # work to the applicant or a verb-led duty, not "our firm develops...".
        if not start and not (re.match(r"\s*(?:you\b|your\b|we are looking for\b|as a\b|this role\b|this position\b|the successful candidate\b|in this role\b)", normalized)
                              or re.search(r"\bour (?:\w+ ){0,4}(?:engineers|developers|interns) (?:work|build|develop)\b", normalized)
                              or any(normalized.lstrip().startswith(v + " ") for v in WORK_VERBS)):
            continue
        if (_hit(normalized, WORK_VERBS) or inherited_action
                or (start and re.match(r"\s*we are (?:seeking|looking for)\b", normalized))):
            statements.append(normalized)
        # A duty such as "you will build our:" assigns the following noun
        # bullets to the applicant too. Scope already ends at skill headings.
        if part.rstrip().endswith(":") and _hit(normalized, WORK_VERBS):
            inherited_action = True
        elif part.rstrip().endswith((".", "!", "?")):
            inherited_action = False
    return statements, lexicon.normalize(text) if start else " "


def _quant_fund_seat(title: str, body: str) -> bool:
    """Whether a fund or portfolio title is quant or adjacent to it."""
    if not _hit(title, FUND_TITLES) or _hit(title, FUND_INTERN_TITLES):
        return False
    if _hit(title, FUND_ADJACENT_TITLES):
        return True
    found = sum(1 for family in QUANT_FAMILIES if _hit(body, family))
    return found >= QUANT_FAMILIES_REQUIRED


def exclusion(title: str, body: str, description: str) -> tuple[str, str] | None:
    """Return a scope gate and its evidence; unknown occupations stay unknown."""
    if hit := _hit(title, STRICT_SUPPORT):
        return "non_quant_finance", f"support occupation in title: {hit}"
    analysis_role = (_hit(title, QUANT_TITLES)
                     or _hit(title, ("analyst", "analytiker", "data scientist")))
    if analysis_role and _hit(lexicon.normalize(description), NON_MARKETS_DUTIES):
        _, duties = _duties(description)
        if hit := _hit(duties, NON_MARKETS_DUTIES):
            return "off_industry", f"non-markets duties: {hit}"
    if _hit(title, ("executive researcher",)):
        _, duties = _duties(description)
        if hit := _hit(duties, RECRUITMENT_DUTIES):
            return "non_quant_finance", f"executive recruitment duties: {hit}"
    # Actual trading seats stay, including discretionary/commodity trading.
    if _hit(title, TRADING_SEATS):
        return None
    if _hit(title, QUANT_TITLES):
        return None
    finance = _hit(title, FINANCE_TITLES)
    tech = _hit(title, TECH_TITLES)
    if not finance and not tech:
        return None
    # Not for engineering titles: "asset management" also names industrial plant
    # (Yokogawa), and a developer's skills list always reads as quantitative.
    if finance and not tech and _quant_fund_seat(title, body):
        return None
    # A specialised trading/research engineering title is evidence of the job,
    # whereas a markets firm's self-description is not.
    if tech and _hit(title, TRADING_TECH):
        return None
    # Missing descriptions are an enrichment gap, not proof that an otherwise
    # ambiguous developer/data-science seat is enterprise IT. Named enterprise
    # specialties still decide on their own title.
    missing_body = (len(body.strip()) < lexicon.MIN_BODY
                    or (len(body) < 1000 and _hit(body, TEASER_MARKERS)))
    if tech and missing_body and not _hit(title, ENTERPRISE_IT):
        return None
    # Only parse sentences when a relevant phrase exists somewhere in the body.
    if _hit(body, BODY_WORK):
        statements, context = _duties(description)
        for statement in statements:
            if _hit(statement, MODEL_WORK):
                return None
            if tech and _hit(statement, TRADING_TECH):
                return None
            if tech and _hit(context, RESEARCH_PURPOSE) and _hit(statement, RESEARCH_DATA):
                return None
    if tech:
        return "generic_it", f"generic technology role: {tech}; no quantitative/trading work evidenced"
    return "non_quant_finance", f"conventional finance role: {finance}; no quantitative work evidenced"
