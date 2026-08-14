"""Word lists for job tagging, and the token-boundary matcher they need.

Kept apart from `tags.py` because the two change for different reasons. The
rules there are a short ordered decision that should almost never move; the
vocabulary here grows every time a board turns up a word we had not seen. Bump
`VERSION` on any change and `job_tags.tagger` records which lexicon produced a
tag, so the diff between two versions over the same corpus is a free regression
test.

**Matching is on token boundaries, never substrings.** `admini`*strat*`or` and
State Street's custody platform -- which is called *Alpha* -- were both real
false hits in this corpus under a naive `in`. Every phrase here is normalized
the same way the text is and matched with spaces on both sides, so a phrase
can only match whole words.

The lists are multilingual because the corpus is: Sweden's JobStream feed is
Swedish, the Teamtailor boards are Nordic, and Workday serves French, German
and Portuguese postings from the same tenants. A word list that is English-only
silently keeps every foreign posting, which reads as "nothing was rejected"
rather than as a gap.
"""

from __future__ import annotations

import re

VERSION = 1

# Everything that is not a letter, digit, `+` or `#` is a separator. The two
# punctuation marks are kept because `c++` and `c#` are the names of things we
# grade a posting on, and splitting them turns both into a bare `c`.
_SEPARATOR = re.compile(r"[^0-9a-zÀ-ɏ+#]+")

# Markup arrives in `description` verbatim -- stripping it is a read-time job,
# per principle 4. The bound on the tag body is what keeps a pathological one
# from being quadratic in anything downstream; `<[^>]*>` over an unclosed angle
# bracket is the same shape of trap `ats.py` was stalled by.
_TAG = re.compile(r"<[^>]{0,4000}>")
MAX_BODY = 200_000


def normalize(text: str | None) -> str:
    """Fold text to space-delimited lowercase tokens, padded on both ends.

    The padding is what makes `" quant "` a token match rather than a
    substring one, which is the whole safety property of this module.
    """
    if not text:
        return " "
    body = text[:MAX_BODY]
    if "<" in body:
        body = _TAG.sub(" ", body)
    return " " + _SEPARATOR.sub(" ", body.casefold()).strip() + " "


def _terms(*phrases: str) -> tuple[str, ...]:
    """Normalize a group of phrases once, at import."""
    return tuple(normalize(p).strip() for p in phrases)


def first(text: str, terms: tuple[str, ...]) -> str | None:
    """The first phrase in `terms` present in already-normalized `text`."""
    for term in terms:
        if f" {term} " in text:
            return term
    return None


def every(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if f" {term} " in text]


# --------------------------------------------------------------------------
# Anchors: the vocabulary that says a posting is about markets at all.
# --------------------------------------------------------------------------

# Strong. A posting carrying one of these is doing quantitative work on
# markets, and that is enough to keep it on its own. Words here must not be
# ambiguous across industries -- `optimization` and `modelling` are, so they
# are absent; `stochastic` and `backtest` are not.
QUANT = _terms(
    # English
    "quant", "quants", "quantitative", "quantitatively",
    "quantitative research", "quantitative analyst", "quantitative developer",
    "quantitative trading", "quantitative strategies", "quantitative finance",
    "systematic trading", "systematic strategies", "algorithmic trading",
    "algo trading", "statistical arbitrage", "stat arb", "pairs trading",
    "alpha research", "alpha generation", "alpha signals", "signal research",
    "market making", "market maker", "market makers", "electronic trading",
    "high frequency", "low latency", "execution algorithms", "smart order routing",
    "portfolio construction", "portfolio optimization", "portfolio optimisation",
    "derivatives pricing", "options pricing", "pricing models", "exotic derivatives",
    "volatility surface", "implied volatility", "greeks", "term structure",
    "model validation", "model risk", "model governance", "xva", "cva",
    "counterparty credit risk", "market risk models", "value at risk",
    "econometric", "econometrics", "econometrician", "time series",
    "stochastic", "stochastic calculus", "monte carlo", "numerical methods",
    "statistical modelling", "statistical modeling", "bayesian",
    "backtest", "backtests", "backtesting", "factor models", "risk premia",
    "systematic investing", "trading strategies", "trading strategy",
    "financial engineering", "mathematical finance", "computational finance",
    # Nordic
    "kvantitativ", "kvantitativa", "kvantitative", "kvantitativt",
    "kvantitativ analytiker", "algoritmisk handel", "systematisk handel",
    "matematisk statistik", "finansiell matematik",
    # Dutch / German / French
    "kwantitatief", "kwantitatieve", "quantitativ", "quantitative analyse",
    "quantitatif", "finance quantitative", "modellvalidierung",
)

# Contextual. These say "markets", not "quantitative". They are never enough to
# keep a posting on their own -- they are the *second* half of a two-sided test,
# the thing that separates a trading-systems engineer from a payments one.
MARKETS = _terms(
    "trading", "trader", "traders", "trade floor", "trading floor",
    "front office", "buy side", "sell side", "hedge fund", "proprietary trading",
    "asset management", "investment management", "portfolio management",
    "portfolio manager", "portfolio", "portfolios", "fund management",
    "equities", "equity research", "fixed income", "derivatives", "futures",
    "options", "swaps", "foreign exchange", "commodities", "securities",
    "capital markets", "financial markets", "money markets", "structured products",
    "structuring", "structurer", "market data", "order book", "liquidity",
    "execution", "clearing", "settlement", "prime brokerage", "brokerage",
    "market risk", "credit risk", "counterparty risk", "risk analytics",
    "investment strategy", "investment research", "index", "indices", "etf",
    "benchmark", "asset allocation", "wealth", "treasury", "exchange traded",
    "handel", "värdepapper", "kapitalmarknad", "kapitalförvaltning",
    "effecten", "beleggingen", "vermogensbeheer", "handelaar",
    "wertpapiere", "kapitalmarkt", "marché financier", "gestion d actifs",
)

# Programming languages, kept as their own dimension so "C++ nice to have" and
# "C++ expert" stay distinguishable at read time rather than collapsing into
# one number. `CLAUDE.md` is explicit that a C++-second quant-dev role fits.
LANGUAGES = {
    "python": _terms("python", "pandas", "numpy", "scipy", "pytorch", "jupyter"),
    "cpp": _terms("c++", "cpp"),
    "rust": _terms("rust"),
    "java": _terms("java", "scala", "kotlin"),
    "csharp": _terms("c#", "dotnet", "net"),
    "kdb": _terms("kdb", "kdb+", "q kdb"),
    "matlab": _terms("matlab"),
    "r": _terms("rstudio", "tidyverse"),
    "sql": _terms("sql", "postgres", "snowflake"),
}

ASSET_CLASSES = {
    "equities": _terms("equities", "equity", "cash equities", "aktier", "aandelen"),
    "futures": _terms("futures", "listed derivatives", "terminer"),
    "fx": _terms("fx", "foreign exchange", "currencies", "valuta"),
    "rates": _terms("rates", "interest rate", "government bonds", "treasuries", "räntor"),
    "credit": _terms("credit", "corporate bonds", "high yield", "cds", "krediter"),
    "commodities": _terms("commodities", "power", "gas", "metals", "energy trading", "råvaror"),
    "options_vol": _terms("options", "volatility", "vol trading", "exotics", "optioner"),
    "crypto": _terms("crypto", "cryptocurrency", "digital assets", "defi", "web3", "bitcoin"),
}

ROLE_FAMILIES = {
    "research": _terms(
        "quantitative research", "quantitative researcher", "research analyst",
        "alpha research", "signal research", "investment research", "researcher",
        "equity research", "strategist", "economist",
    ),
    "trading": _terms(
        "trader", "trading", "market making", "market maker", "dealer",
        "portfolio manager", "handlare",
    ),
    "quant_dev": _terms(
        "quantitative developer", "quant developer", "quantitative engineer",
        "trading systems", "trading technology", "trading platform",
        "quantitative software", "research engineer", "platform quant",
    ),
    "risk": _terms(
        "market risk", "credit risk", "risk management", "risk analytics",
        "counterparty risk", "liquidity risk", "riskkontroll", "risk quant",
    ),
    "model_validation": _terms(
        "model validation", "model risk", "model governance", "validation quant",
    ),
    "data_science": _terms(
        "data scientist", "data science", "machine learning", "applied scientist",
        "artificial intelligence", "deep learning",
    ),
    "execution": _terms(
        "execution", "algo execution", "transaction cost", "smart order routing",
        "electronic execution",
    ),
    "structuring": _terms("structuring", "structurer", "structured products"),
}


# --------------------------------------------------------------------------
# Hard negatives: occupations a title fully determines.
# --------------------------------------------------------------------------
#
# The asymmetry these rest on is the point of the whole module. A title can
# never *prove* a posting is quantitative -- Goldman says "Strat", Jane Street
# says "Trader" -- but some titles name the entire occupation, and no body text
# turns a *Receptionist* into a quant role. Rejecting on those is safe where
# accepting on a title never is.
#
# Each entry is a phrase, grouped by the reason it rejects. The reason is
# stored with the tag, so "what did the filter throw away, and on what word"
# is one query rather than a re-run.

UNRELATED = _terms(
    # front of house, facilities, trades
    "receptionist", "reception", "front desk", "housekeeper", "housekeeping",
    "janitor", "custodian", "cleaner", "cleaning", "groundskeeper", "porter",
    "maintenance technician", "maintenance supervisor", "maintenance manager",
    "facilities technician", "hvac", "plumber", "electrician", "welder",
    "machinist", "carpenter", "roofer", "painter", "landscaper", "locksmith",
    "forklift", "warehouse", "warehouse associate", "picker", "packer",
    "driver", "truck driver", "delivery driver", "chauffeur", "courier",
    "mechanic", "technician", "field technician", "service technician",
    "installer", "fitter", "operator", "machine operator", "assembler",
    # health and care
    "nurse", "nursing", "physician", "surgeon", "dentist", "dental",
    "pharmacist", "pharmacy", "therapist", "physiotherapist", "psychologist",
    "caregiver", "care assistant", "midwife", "veterinarian", "paramedic",
    "radiologist", "medical assistant", "clinical", "patient",
    # food, retail, hospitality
    "chef", "cook", "sous chef", "kitchen", "waiter", "waitress", "server",
    "barista", "bartender", "dishwasher", "restaurant", "catering",
    "food service", "housekeeping attendant", "front office agent",
    "store manager", "store associate", "sales associate", "shop assistant",
    "cashier", "merchandiser", "stylist", "barber", "hairdresser",
    "beautician", "tattoo", "piercing", "concierge", "valet",
    "flight attendant", "cabin crew", "pilot", "baggage",
    # education, public safety, social
    "teacher", "tutor", "instructor", "lecturer", "childcare", "preschool",
    "daycare", "nanny", "social worker", "youth worker",
    "security guard", "guard", "firefighter", "police", "correctional",
    # heavy industry and site engineering -- real engineering, wrong industry
    "civil engineer", "mechanical engineer", "electrical engineer",
    "chemical engineer", "process engineer", "structural engineer",
    "manufacturing engineer", "production engineer", "field engineer",
    "service engineer", "operating engineer", "mining engineer",
    "avionics", "aircraft", "aerospace", "automotive", "construction",
    "site manager", "foreman", "surveyor", "geologist", "hydrogeologist",
    "biologist", "environmental", "laboratory", "quality inspector",
    "production operator", "shift supervisor", "plant manager",
    "property manager", "leasing", "leasing consultant", "real estate agent",
    "facilities manager", "building automation",
    # Swedish / Danish / Norwegian
    "sjuksköterska", "undersköterska", "vårdbiträde", "läkare", "specialistläkare",
    "tandläkare", "tandsköterska", "fysioterapeut", "sjukgymnast", "arbetsterapeut",
    "barnmorska", "psykolog", "kurator", "logoped", "apotekare", "farmaceut",
    "medicinsk sekreterare", "personlig assistent", "boendestödjare",
    "socialsekreterare", "behandlingspedagog",
    "kock", "kallskänka", "servitör", "servitris", "restaurangbiträde",
    "bagare", "köksmästare", "diskare", "barista",
    "lokalvårdare", "städare", "städ", "vaktmästare", "fastighetsskötare",
    "chaufför", "lastbilsförare", "truckförare", "lagerarbetare", "montör",
    "svetsare", "elektriker", "snickare", "målare", "plattsättare", "murare",
    "mekaniker", "bärgare", "väktare", "brandman",
    "lärare", "förskollärare", "barnskötare", "fritidspedagog", "rektor",
    "butikssäljare", "butikschef", "frisör", "receptionist",
    "sygeplejerske", "pædagog", "tømrer", "rengøring", "elektriker",
    # Dutch / German / French
    "verpleegkundige", "verzorgende", "monteur", "schoonmaak", "docent",
    "magazijn", "chauffeur", "verkoopmedewerker",
    "pflegefachkraft", "krankenschwester", "erzieher", "verkäufer",
    "lagerist", "hausmeister", "koch", "fahrer", "mechatroniker",
    "infirmier", "cuisinier", "serveur", "vendeur", "technicien",
    "conducteur", "magasinier", "agent d entretien",
)

CORPORATE = _terms(
    "human resources", "hr business partner", "hr manager", "hr advisor",
    "recruiter", "recruiting", "recruitment", "talent acquisition",
    "talent partner", "payroll", "compensation and benefits", "benefits",
    "learning and development", "people operations", "people partner",
    "office manager", "executive assistant", "administrative assistant",
    "personal assistant", "office administrator", "office coordinator",
    "facilities", "procurement", "purchasing", "supply chain", "logistics",
    "marketing", "brand", "communications", "public relations", "press officer",
    "content", "copywriter", "social media", "graphic designer", "ux designer",
    "event", "events", "community manager", "customer success",
    "legal counsel", "paralegal", "attorney", "lawyer", "solicitor",
    "translator", "interpreter", "archivist", "librarian",
    "rekryterare", "lönespecialist", "kommunikatör", "marknadsförare",
    "administratör", "avtalsadministratör", "jurist", "personalchef",
    "kundtjänst", "kundservice", "kundrådgivare",
)

# Finance, but the part of finance that is relationship work, processing or
# advice rather than modelling. `CLAUDE.md`'s exclude list, made concrete.
NON_QUANT_FINANCE = _terms(
    "relationship manager", "relationship banker", "personal banker",
    "private banker", "branch manager", "bank teller", "teller",
    "mortgage advisor", "mortgage adviser", "mortgage loan", "loan officer",
    "loan processor", "financial advisor", "financial adviser", "wealth advisor",
    "wealth manager", "client advisor", "insurance advisor", "insurance broker",
    "customer service", "client service", "client services", "customer care",
    "contact centre", "contact center", "call centre", "call center",
    "account manager", "account executive", "business development",
    "sales manager", "sales representative", "sales executive", "sales support",
    "inside sales", "telesales", "client onboarding", "onboarding specialist",
    "accountant", "accounting", "bookkeeper", "accounts payable",
    "accounts receivable", "financial reporting", "fund accounting",
    "fund administration", "fund administrator", "transfer agency",
    "tax manager", "tax advisor", "tax analyst", "auditor", "internal audit",
    "external audit", "compliance officer", "compliance analyst",
    "compliance manager", "regulatory reporting", "anti money laundering",
    "aml", "kyc", "know your customer", "financial crime", "fraud",
    "sanctions", "collections", "debt recovery", "underwriter", "underwriting",
    "claims", "claims handler", "actuary", "actuarial", "insurance pricing",
    "trade support", "trading support", "middle office", "back office",
    "operations analyst", "settlements", "corporate actions", "reconciliation",
    "banking advisor", "bankrådgivare", "redovisningsekonom", "redovisningsansvarig",
    "ekonomiassistent", "löneadministratör", "revisor", "försäkringsrådgivare",
    "kundberater", "kundenberater", "bankfiliale", "conseiller clientèle",
)

# Engineering titles. These reject only when *no* markets anchor appears
# anywhere in the posting -- a two-sided test, because `Software Engineer,
# Trading Systems` at Optiver is exactly in scope and `Senior Backend Engineer,
# Payments Platform` at a retail bank is exactly not. The tag records which
# anchor rescued it, or that none did.
ENGINEERING = _terms(
    "software engineer", "software developer", "software development",
    "developer", "programmer", "full stack", "fullstack", "front end",
    "frontend", "back end", "backend", "web developer", "mobile developer",
    "android", "ios", "react", "angular", "node js",
    "devops", "sre", "site reliability", "cloud engineer", "cloud architect",
    "platform engineer", "infrastructure engineer", "network engineer",
    "systems engineer", "systems administrator", "system administrator",
    "database administrator", "security engineer", "cyber security",
    "cybersecurity", "information security", "penetration", "qa engineer",
    "test engineer", "automation engineer", "release engineer",
    "solution architect", "enterprise architect", "technical architect",
    "it support", "help desk", "helpdesk", "service desk", "desktop support",
    "application support", "technical support", "it project", "it business",
    "salesforce", "sap", "servicenow", "sharepoint", "workday consultant",
    "scrum master", "product owner", "product manager", "business analyst",
    "data engineer", "data platform", "etl", "integration engineer",
    "systemutvecklare", "utvecklare", "programmerare", "systemadministratör",
    "softwareentwickler", "entwickler", "développeur", "ontwikkelaar",
)

# Titles that are genuinely ambiguous: quantitative at one firm, commentary at
# the next. These are never rejected on a title -- they go to `undecided`,
# which is the queue that says "fetch this body". This is where the economists
# live, and the reason the description backfill has a priority order.
AMBIGUOUS_FINANCE = _terms(
    "analyst", "senior analyst", "financial analyst", "investment analyst",
    "credit analyst", "risk analyst", "data analyst", "business intelligence",
    "economist", "economics", "strategist", "consultant", "associate",
    "portfolio analyst", "performance analyst", "valuation", "valuations",
    "pricing analyst", "reporting analyst", "analytics", "modeller", "modeler",
    "analytiker", "ekonom", "nationalekonom", "analytikere", "analiste",
)

CRYPTO = _terms(
    "crypto", "cryptocurrency", "blockchain", "web3", "defi",
    "bitcoin", "ethereum", "token economics", "nft",
)

# --------------------------------------------------------------------------
# Seniority. Titles carry this reliably at the top of the ladder and unreliably
# in the middle, which is why only the top rejects.
# --------------------------------------------------------------------------

# `vice president` is deliberately absent. At a bank it is a mid-career grade
# -- State Street and Citi stamp it on five-year hires -- so treating it as
# senior would reject a large, genuinely relevant slice of the corpus.
HEAD_OR_MD = _terms(
    "head of", "global head", "regional head", "group head", "chief",
    "managing director", "senior vice president", "executive vice president",
    "svp", "evp", "president", "ceo", "cfo", "coo", "cto", "cio",
    "director", "partner", "vd", "verkställande direktör", "avdelningschef",
    "geschäftsführer", "directeur",
)
# Checked first, and they win: a `Director` in these is not the bank grade.
NOT_HEAD = _terms(
    "associate director", "assistant director", "deputy director",
    "director of engineering", "art director", "creative director",
    "funeral director", "director level", "managing directorate",
)

LEAD = _terms("lead", "principal", "staff", "senior manager", "team lead")
SENIOR = _terms("senior", "sr", "vice president", "vp", "avp", "experienced")
INTERN = _terms(
    "intern", "internship", "praktikant", "praktik", "praktikplats",
    "werkstudent", "stagiaire", "stage", "summer analyst", "summer intern",
    "sommarjobb", "trainee program",
)
NEW_GRAD = _terms(
    "graduate", "graduate program", "graduate programme", "new grad",
    "campus", "entry level", "junior", "nyexaminerad", "traineeprogram",
    "absolvent", "jeune diplômé", "starter",
)

# Body-only. A posting that requires a *future* graduation date is noise for a
# graduate with a year of experience, and titles never announce it.
STUDENT_ONLY = _terms(
    "currently enrolled", "must be enrolled", "are enrolled", "still studying",
    "final year student", "final year students", "penultimate year",
    "graduating in 2027", "graduating in 2028", "expected graduation",
    "pursuing a degree", "currently pursuing", "student at a university",
    "studerar", "pågående studier", "under utbildning", "ingeschreven student",
)

HUBS = (
    ("stockholm", _terms("stockholm", "sverige", "sweden", "solna", "kista")),
    ("copenhagen", _terms("copenhagen", "københavn", "kobenhavn", "denmark", "danmark")),
    ("amsterdam", _terms("amsterdam", "netherlands", "nederland", "rotterdam", "utrecht", "den haag")),
    ("switzerland", _terms("zurich", "zürich", "geneva", "genève", "genf", "zug",
                           "basel", "lugano", "switzerland", "schweiz", "suisse")),
    ("hong kong", _terms("hong kong", "hongkong", "kowloon")),
    ("singapore", _terms("singapore",)),
)

# `employers.category` is the regulator's own classification, kept verbatim at
# ingest for exactly this. Matched on the category string, not the firm name.
FIRM_TYPES = (
    ("exchange", ("exchange participant", "regulated market", "market infrastructure",
                  "trading member", "trading-clearing member")),
    ("broker", ("broker-dealer", "dealing in securities", "dealing in futures",
                "värdepappersbolag", "beleggingsonderneming", "investment firm")),
    ("asset_manager", ("adviser", "asset management", "advising on securities",
                       "portfolio manager", "aifm", "ucits", "fund management",
                       "kapitalförvaltning", "beleggingsinstelling", "beheerder",
                       "capital markets services", "collective assets")),
    ("bank", ("bank", "credit institution", "securities firm", "raiffeisen")),
    ("pension", ("pension", "tjänstepension")),
    ("insurance", ("insurance", "försäkring", "reinsurance")),
)
