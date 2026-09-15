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
    "trade operations", "trading operations", "settlements", "reconciliation",
    "client service", "client services", "client portfolio", "client processing",
    "relationship manager", "account manager", "accountmanager",
    "portfoljforvaltare", "portfoljforvaltning", "portfoljanalytiker",
    "kapitalforvaltare", "kapitalforvaltning", "fondforvaltare",
    "aktieforvaltare", "ranteforvaltare", "formueforvaltning",
    "formogenhetsforvaltning", "vermogensverwaltung", "vermogensbeheer",
    "gestion de portefeuille", "gestionnaire de portefeuille", "gerant de portefeuille",
)

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
)

ENTERPRISE_IT = (
    "network reliability", "network engineer", "systems administrator",
    "system administrator", "database administrator", "desktop", "help desk",
    "service desk", "it support", "cybersecurity", "cyber security",
    "information security", "informationssakerhet", "servicenow", "salesforce",
    "sharepoint", "enterprise architect", "scrum master", "business systems",
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
)

WORK_VERBS = (
    "develop", "developing", "design", "designing", "build", "building",
    "implement", "implementing", "calibrate", "calibrating", "validate",
    "validating", "backtest", "backtesting", "research", "researching",
    "optimise", "optimising", "optimize", "optimizing", "enhance", "enhancing",
    "maintain", "maintaining", "construct", "constructing", "test", "testing",
    "utveckla", "utveckling", "validera", "validering",
)

SECTION_PATTERNS = (
    r"(?im)\b(?:responsibilities|what you(?:['’]ll| will) do|your (?:role|responsibilities)|role summary|position duties|key duties|arbetsuppgifter)\b|^\s*(?:role|the role)\s*[:\n]",
    r"(?im)(?:^\s*|(?<=[.!?:])\s*)(?:qualifications|requirements|skills you|what (?:we offer|you(?:['’]ll)? bring)|the position requires|about (?:us|the company)|benefits|equal opportunity)\b|\b(?-i:REQUIREMENTS|QUALIFICATIONS)\b",
)
RESEARCH_DATA = ("data pipelines", "features", "feature engineering", "datasets",
                 "research data", "data validation")
RESEARCH_PURPOSE = ("systematic portfolio managers", "predictive modelling in finance",
                    "quantitative research", "systematic strategies", "alpha signals")
BODY_WORK = MODEL_WORK + TRADING_TECH + RESEARCH_PURPOSE


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
    for part in re.split(r"[\n;]+|(?<=[.!?])\s+", text):
        normalized = lexicon.normalize(part)
        # Without a responsibilities section, require a sentence assigning
        # work to the applicant or a verb-led duty, not "our firm develops...".
        if not start and not (re.match(r"\s*(?:you\b|your\b|we are looking for\b|as a\b|this role\b|this position\b|the successful candidate\b|in this role\b)", normalized)
                              or re.search(r"\bour (?:\w+ ){0,4}(?:engineers|developers|interns) (?:work|build|develop)\b", normalized)
                              or any(normalized.lstrip().startswith(v + " ") for v in WORK_VERBS)):
            continue
        if _hit(normalized, WORK_VERBS) or inherited_action:
            statements.append(normalized)
        # A duty such as "you will build our:" assigns the following noun
        # bullets to the applicant too. Scope already ends at skill headings.
        if part.rstrip().endswith(":") and _hit(normalized, WORK_VERBS):
            inherited_action = True
        elif part.rstrip().endswith((".", "!", "?")):
            inherited_action = False
    return statements, lexicon.normalize(text) if start else " "


def exclusion(title: str, body: str, description: str) -> tuple[str, str] | None:
    """Return a scope gate and its evidence; unknown occupations stay unknown."""
    if hit := _hit(title, STRICT_SUPPORT):
        return "non_quant_finance", f"support occupation in title: {hit}"
    # Actual trading seats stay, including discretionary/commodity trading.
    if _hit(title, TRADING_SEATS):
        return None
    if _hit(title, QUANT_TITLES):
        return None
    finance = _hit(title, FINANCE_TITLES)
    tech = _hit(title, TECH_TITLES)
    if not finance and not tech:
        return None
    # A specialised trading/research engineering title is evidence of the job,
    # whereas a markets firm's self-description is not.
    if tech and _hit(title, TRADING_TECH):
        return None
    # Missing descriptions are an enrichment gap, not proof that an otherwise
    # ambiguous developer/data-science seat is enterprise IT. Named enterprise
    # specialties still decide on their own title.
    if tech and not finance and len(body.strip()) < lexicon.MIN_BODY and not _hit(title, ENTERPRISE_IT):
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
