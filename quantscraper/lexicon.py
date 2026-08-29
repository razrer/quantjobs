"""Which postings are the wrong job, and the evidence that says so.

`tagging.py` decides what a posting *is* -- role family, seniority, code depth,
asset class, fit. This module decides what a posting is **not**, which turns
out to need a different rule and a much longer word list, so it lives apart.
One import and one call adopts it:

    from . import lexicon
    call = lexicon.judge(row["title"], row["department"], row["description"])
    # call.verdict is "keep" | "reject" | "undecided"

Bump `VERSION` on any change here. `job_tags.tagger` records it, so the diff
between two versions over the same corpus is a free regression test.

## The asymmetry the whole module rests on

`CLAUDE.md` says never to filter on a job title alone. That rule is about
*inclusion* and it is right: Goldman says "Strat", Jane Street says "Trader",
Stockholm says "kvantitativ analytiker", so a title that fails to look
quantitative proves nothing at all.

Exclusion is not its mirror image. Some titles name the entire occupation, and
no body text turns a *Receptionist* into a quant role. So:

- **a title can never prove a posting is relevant** -- that needs the body, or a
  word specific enough to stand alone;
- **a title can prove a posting is a different job** -- and the word that proved
  it is recorded as evidence.

That distinction is what makes this corpus tractable: most postings are a
title, a location and a date, so a classifier that waits for descriptions
classifies almost nothing while one that rejects named occupations can clear
most of the noise today.

It is also the sharpest place in the project to be wrong, so every rejection
stores the phrase that caused it and nothing is deleted: `job_tags` rebuilds
from `jobs`, and a lexicon bug costs one re-run.

## Three verdicts, because two would force a guess

`keep` - `reject` - `undecided`.

`undecided` is not a failure state, it is the **backfill queue**: a posting
with an ambiguous title and no body is exactly the one worth fetching a body
for, and `bodies.py` reads it that way. A two-verdict classifier has to guess
on those, and a guess is either a false rejection or a board full of noise.

## Two-sided rules, for the two cases a word list gets wrong

A one-sided list gets *receptionist* right and both cases that matter wrong:

- **Pure programming.** `Software Engineer` is in scope at Optiver and out of it
  on a retail bank's payments team, so an engineering title rejects only when
  **no markets anchor appears anywhere in the posting**. The tag records which
  anchor rescued it, or that none did.
- **Non-quantitative finance.** `Economist`, `Financial Analyst` and `Credit
  Analyst` are quantitative at one firm and commentary at the next. These are
  never rejected on a title; they go to `undecided` and the body settles it.

Firm boilerplate is deliberately not allowed to answer either question about
the *role*. A quant fund's description says "we are a systematic trading firm"
on its office-manager posting too, so anchors found in the title and department
decide the role, while anchors found in the body only ever support or rescue.

**And a body may only support next to a markets anchor.** The engineering rule
above is the general one: `monte carlo` is derivatives pricing at a bank and
radiation shielding at a reactor, `time series` is signal research at a fund
and telemetry on a robotaxi. The quantitative *methodology* vocabulary belongs
to every technical field; only the markets vocabulary is ours. So a phrase
found in a body counts for nothing unless the posting places itself in markets
somewhere -- see `judge`, where `quant_body` is computed.

## Matching is on token boundaries, never substrings

`admini`*strat*`or` contains "strat", and State Street's custody platform is
called *Alpha*; both were real false hits in this corpus. Every phrase here is
normalized the same way the text is and matched with a space on each side, so a
phrase can only ever match whole words.

## The lists are multilingual because the corpus is

The national feeds are Swedish, Danish, German and French; the Teamtailor
boards are Nordic; Workday serves several languages from the same tenants. An
English-only word list rejects none of them, which reads as "nothing was wrong
with these" rather than as a gap -- the same silent failure as a scraper
returning zero rows with HTTP 200.

**Never translate a word list into a new language; mine it out of the corpus
and read what it matches.** German *Anlage* is both *investment* and
*industrial plant*, and here it is overwhelmingly the second: `anlagenführer`
is 212 titles and every one is a machine operator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

VERSION = 9

# Everything that is not a letter, digit, `+` or `#` is a separator. Those two
# are kept because `c++` and `c#` name things a posting is graded on, and
# dropping them turns both into a bare `c`.
_SEPARATOR = re.compile(r"[^0-9a-zÀ-ɏ+#]+")

# Markup arrives in `description` verbatim -- stripping it is a read-time job,
# per principle 4. The bound matters: `ats.py` lost two and a half hours of CPU
# to an unbounded pattern over fetched markup, and the failure looked like a
# slow network rather than an error.
_MARKUP = re.compile(r"<[^>]{0,4000}>")
MAX_BODY = 200_000

# Below this a description is a stub -- a one-line summary or an empty div --
# and absence of evidence in it is not evidence of absence.
MIN_BODY = 200


def normalize(text: str | None) -> str:
    """Fold text to space-delimited lowercase tokens, padded at both ends.

    The padding is what makes `" quant "` a token match rather than a substring
    one, which is the entire safety property of this module.
    """
    if not text:
        return " "
    body = text[:MAX_BODY]
    if "<" in body:
        body = _MARKUP.sub(" ", body)
    return " " + _SEPARATOR.sub(" ", body.casefold()).strip() + " "


def _terms(*phrases: str) -> tuple[str, ...]:
    """Normalize a group of phrases once, at import."""
    return tuple(normalize(phrase).strip() for phrase in phrases)


# A phrase can only match if its first word is a token of the text, so most of
# a long list can be skipped on a set lookup instead of scanned. Measured over
# the corpus: 9x on the largest list, and matching is half the cost of a re-tag.
#
# Keyed by `id()` for an O(1) lookup -- hashing a 600-tuple on every call would
# cost more than it saves -- and each tuple is stored beside its index so it
# cannot be freed and have its id reused.
_INDEX: dict[int, tuple[tuple[str, ...], tuple[tuple[str, str, str], ...]]] = {}


def _index(terms: tuple[str, ...]) -> tuple[tuple[str, str, str], ...]:
    """(first word, padded phrase, phrase) for each phrase, built once."""
    entry = _INDEX.get(id(terms))
    if entry is None or entry[0] is not terms:
        entry = (terms, tuple(
            (term.split(" ", 1)[0], f" {term} ", term) for term in terms
        ))
        _INDEX[id(terms)] = entry
    return entry[1]


@lru_cache(maxsize=16)
def _words(text: str) -> frozenset[str]:
    """The text's distinct tokens. Cached, because one posting is matched
    against ~110 phrase lists over the same three or four normalized strings."""
    return frozenset(text.split())


def first(text: str, terms: tuple[str, ...]) -> str | None:
    """The first phrase of `terms` present in already-normalized `text`."""
    words = _words(text)
    for head, padded, term in _index(terms):
        if head in words and padded in text:
            return term
    return None


def every(text: str, terms: tuple[str, ...]) -> list[str]:
    """Every phrase of `terms` present, for the rules that count corroboration."""
    words = _words(text)
    return [term for head, padded, term in _index(terms)
            if head in words and padded in text]


# --------------------------------------------------------------------------
# Anchors -- the vocabulary that says a posting is about markets at all
# --------------------------------------------------------------------------

# Strong. A posting carrying one of these is doing quantitative work on
# markets, and that is enough to keep it on its own. Nothing ambiguous across
# industries belongs here: `optimization` and `modelling` are ordinary words in
# logistics and insurance, `stochastic` and `backtest` are not.
QUANT = _terms(
    # English
    "quant", "quants", "quantitative", "quantitatively",
    "quantitative research", "quantitative analyst", "quantitative developer",
    "quantitative trading", "quantitative strategies", "quantitative finance",
    "systematic trading", "systematic strategies", "algorithmic trading",
    "algo trading", "statistical arbitrage", "stat arb", "pairs trading",
    "alpha research", "alpha generation", "alpha signals", "signal research",
    "market making", "market maker", "market makers", "electronic trading",
    "high frequency trading", "low latency trading", "execution algorithms",
    "smart order routing", "execution research", "transaction cost analysis",
    "portfolio construction", "portfolio optimization", "portfolio optimisation",
    "derivatives pricing", "options pricing", "pricing models", "exotic derivatives",
    "volatility surface", "implied volatility", "term structure",
    "model validation", "model risk", "model governance", "xva", "cva",
    "counterparty credit risk", "market risk models", "value at risk",
    "econometric", "econometrics", "econometrician", "time series",
    "stochastic", "stochastic calculus", "monte carlo", "numerical methods",
    "statistical modelling", "statistical modeling", "bayesian inference",
    "backtest", "backtests", "backtesting", "factor models", "risk premia",
    "systematic investing", "trading strategies", "trading strategy",
    "financial engineering", "mathematical finance", "computational finance",
    "risk quant", "strats",
    # Nordic
    "kvantitativ", "kvantitativa", "kvantitative", "kvantitativt",
    "kvantitativ analytiker", "algoritmisk handel", "systematisk handel",
    "matematisk statistik", "finansiell matematik",
    # Dutch, German, French
    "kwantitatief", "kwantitatieve", "quantitativ", "quantitative analyse",
    "quantitatif", "finance quantitative", "modellvalidierung",
)

# Bare `quantitative` is decisive in a title and nearly worthless in a body.
# "Strong quantitative skills" is boilerplate in half the job specs ever
# written, and on its own it promoted an insurance operations manager, a
# regional VP of P&C operations and a financial-services lawyer into the keep
# list. So a body is read against the *specific* phrases only -- the ones no
# firm writes unless the role does the thing.
GENERIC_IN_BODY = frozenset(_terms(
    "quant", "quants", "quantitative", "quantitatively",
    "kvantitativ", "kvantitativa", "kvantitativt", "kvantitative",
    "quantitativ", "quantitatif", "kwantitatief", "kwantitatieve",
))
QUANT_BODY = tuple(term for term in QUANT if term not in GENERIC_IN_BODY)

# The specific phrases split again, into two kinds of evidence, because only
# one of them stands alone.
#
# **Some name markets activity: the anchor is inside the phrase.** No document
# says "statistical arbitrage" about anything else, so one in a body settles it.
#
# **The rest name a method, and every technical field owns them.** `monte
# carlo` is derivatives pricing at a bank and radiation shielding at a reactor;
# `time series` is signal research at a fund and telemetry on a robotaxi.
# Measured, not guessed -- see `judge`.
#
# The split is asymmetric, so doubtful phrases go in the method bucket: a wrong
# entry there costs nothing unless the posting mentions markets nowhere, which
# no genuine quant advertisement manages, while a wrong entry above costs a
# false keep. `quantitative finance` reads like the strongest phrase here and
# is below, because a consumer bank's core-ledger posting carries it.
SELF_ANCHORING = frozenset(_terms(
    "systematic trading", "algorithmic trading", "algo trading",
    "statistical arbitrage", "stat arb", "pairs trading",
    "market making", "market maker", "market makers",
    "electronic trading", "high frequency trading", "low latency trading",
    "execution algorithms", "smart order routing", "transaction cost analysis",
    "derivatives pricing", "exotic derivatives",
    "volatility surface", "implied volatility",
    "counterparty credit risk", "market risk models", "value at risk",
    "risk premia", "systematic investing", "quantitative trading",
    "trading strategies", "trading strategy", "xva", "cva", "risk quant",
    "algoritmisk handel", "systematisk handel",
))
QUANT_MARKETS_BODY = tuple(term for term in QUANT_BODY if term in SELF_ANCHORING)
QUANT_METHOD_BODY = tuple(term for term in QUANT_BODY if term not in SELF_ANCHORING)

# The mirror image, and the reason `CLAUDE.md` names Jane Street: `Trader` in a
# title *is* the job, and in a body it is furniture -- every bank's boilerplate
# mentions traders somewhere. These keep a posting when they appear in a title,
# and are checked *after* the non-quant finance list so that `Sales Trader` and
# `Trader Support` reject on the phrase that names them rather than on the word
# they happen to contain.
TITLE_ANCHOR = _terms(
    "trader", "traders", "trading strategist", "proprietary trader",
    "handlare", "handelaar", "händler",
)

# Contextual. These say "markets", not "quantitative". They are never enough to
# keep a posting on their own -- they are the second half of a two-sided test,
# the part that separates a trading-systems engineer from a payments one.
#
# **Ordinary English is banned from this list**, and the reason is a measured
# one. `portfolio`, `equity`, `options`, `execution` and `benchmark` all mean
# something else in a job advertisement: a venture firm's *portfolio
# companies*, a startup's *equity* compensation, *stock options*, *strategy
# execution*. With those words in here, every engineer AlphaSense and eleven
# venture boards were hiring came out as a markets role. This is `_GENERIC` in
# `domains.py` all over again -- a word can be rare in this industry and still
# be ordinary language, and it is the second that decides whether it is
# evidence.
MARKETS = _terms(
    "trading", "trader", "traders", "trading floor", "trading desk",
    "front office", "buy side", "sell side", "hedge fund", "proprietary trading",
    "asset management", "investment management", "portfolio management",
    "portfolio manager", "fund management", "equities", "equity research",
    "fixed income", "derivatives", "swaps", "foreign exchange", "commodities",
    "securities", "capital markets", "financial markets", "money markets",
    "structured products", "structuring", "structurer", "market data",
    "order book", "prime brokerage", "brokerage", "market risk", "credit risk",
    "counterparty risk", "risk analytics", "investment strategy",
    "investment research", "asset allocation", "exchange traded",
    "alternative investments", "listed derivatives",
    # Both measured and both sitting entirely inside finance. `treasury` is
    # markets-adjacent rather than markets, and `adjacent` is exactly the rank
    # this list confers. **`cash management` was measured and dropped**: 64
    # genuine titles, but transaction banking rather than markets.
    "treasury", "mutual fund", "mutual funds",
    # **Bare `handel` came off this list**, which is the ban above applied to
    # Swedish: it is *commerce* -- e-handel, detaljhandel -- and names a shop
    # as often as a desk. It was invisible while `MARKETS` was only ever the
    # second half of a two-sided test; of the 85 live titles carrying it,
    # essentially all are supermarket and wine-shop staff. The compounds
    # replace it. **A contextual list is only as safe as the strongest thing
    # that reads it.**
    "aktiehandel", "valutahandel", "derivathandel", "värdepappershandel",
    "börshandel", "obligationshandel", "råvaruhandel", "handelsbord",
    "handelsgolv", "handelsstöd",
    "värdepapper", "kapitalmarknad", "kapitalförvaltning",
    "effecten", "beleggingen", "vermogensbeheer", "handelaar",
    "wertpapiere", "kapitalmarkt", "marché financier",
    # ----------------------------------------------------------------------
    # **Nordic, and the yield is the finding rather than the disappointment.**
    # The Nordic quant vocabulary carries almost no signal, because the Nordic
    # quant postings are written in English: of 54 candidates dry-run over
    # every live title, **forty have zero hits** -- `räntebärande`,
    # `marknadsrisk`, `modellvalidering`, not one occurrence between them.
    # The twelve below are here because each is cheap and each names a real
    # seat the board was missing. Translating the *negative* half is what moves
    # a Nordic board; this half is insurance.
    #
    # **The compounds only, never the bare head**, the same rule `handel` is
    # here under: `förvaltare` alone is a property caretaker and out-numbers
    # the portfolio-manager reading in this corpus.
    "ränteförvaltare", "aktieförvaltare", "kapitalförvaltare",
    "portföljförvaltare", "portföljförvaltning", "fondförvaltare",
    "porteføljeforvalter", "kapitalforvaltning", "formueforvaltning",
    "värdepappersadministratör", "fondadministratör", "fondadministration",
    "likvida marknader", "allokering", "tillgångsallokering",
    "markedsdata", "marknadsdata", "rentedata", "renteprodukter",
    # Two initialisms and a product name, each placing a posting in markets as
    # firmly as any phrase above: `ficc` is the desk, `ifrs 9` is the
    # impairment standard for financial instruments, and `simcorp` is the
    # portfolio system the Nordic institutions run -- AP4's `Systemförvaltare
    # SimCorp Dimension` is a front-office seat whose title reads as a
    # caretaker.
    "ficc", "ifrs 9", "simcorp",
    # ----------------------------------------------------------------------
    # **The same list read against every hub rather than just the Nordic
    # one.** Ranking the phrases by how many board postings still sitting at
    # `relevance: unknown` each would move turned up two families this list
    # had missed, and both are ordinary English rather than a translation
    # problem.
    #
    # **The first is word order and synonym.** `model risk` was here and `risk
    # model` was not, so Denmark's `Risk Model Developer` read as a posting
    # nothing had looked at; `portfolio management` was here and `portfolio
    # analysis` was not; `alternative investments` was here and `alternative
    # assets` was not. A needle list written phrase by phrase acquires these
    # silently, and only a frequency count over what is still unread finds
    # them.
    #
    # **The second is the desk vocabulary of firms that are not trading
    # firms** -- custody, fund services, surveillance, syndicate. Those are
    # where State Street, Apex, Euronext and SimCorp advertise, and they were
    # invisible.
    #
    # Every phrase below was measured over all 295,347 live titles and the
    # promoted examples read by hand. **Three that looked obviously right were
    # dropped:**
    #
    # - **`broker`** promotes 61 postings and 59 of them are *insurance*
    #   brokers -- Marsh, Ryan Specialty, HW Kaufman, `Property & Casualty
    #   Broker`, `Senior Placement Broker Haftpflichtversicherung`. Insurance
    #   is on the reader's exclude list outright. `brokers` is worse: 18 of 18
    #   are one Singapore recruiter's `HSBC Life Investment Brokers`.
    # - **`valuation`** promotes 12 and they are `Valuation Analyst - Real
    #   Estate Advisory` and `Forensic Litigation & Valuation Services`.
    #   Property and disputes, not marks. SimCorp's `Valuation Product Area`
    #   is reached by `simcorp` instead, which is the specific handle.
    # - **`order management`** is supply chain at Motorola as often as it is
    #   an OMS.
    #
    # `dealer` survives the same test where `broker` fails: 8 promotions, all
    # of them `FX Dealer`, `Multi Asset Dealer`, `Institutional Dealer`.
    "risk model", "risk models", "portfolio analysis", "alternative assets",
    "global markets", "private markets", "investor services", "collateral",
    "private credit", "open ended fund", "real assets",
    "financial institutions", "corporate banking", "private bank",
    "dealer", "markets analyst", "post trade", "fund services",
    "fund accounting", "depositary", "trade surveillance",
    "structured finance", "spot trade", "market abuse",
    "middle office", "back office", "trade support", "securities lending",
    "repo", "money market",
    # ----------------------------------------------------------------------
    # **The American desk vocabulary, read off the postings the United States
    # left at `relevance: unknown`.** Emptying that bucket from below with
    # occupation words and from above with a markets reading is one repair, and
    # doing only half of it makes the page worse -- so this is the other half of
    # the American batch in `tagging._OFF_INDUSTRY`.
    #
    # `exchange traded` was already here and never matched, because the corpus
    # writes **ETF**: Invesco and AllianceBernstein advertise `ETF Strategist`,
    # `Sr. Equity ETF Strategist` and `Senior ETF Engineer, Investment
    # Technology`, and all fourteen sat unread. `market making` is the same
    # shape of omission one word over -- SIG's `C++ Developer | Options Market
    # Making` and Marex's `Market Making Technology`.
    #
    # `portfolio implementation` is the one worth naming: ten postings, AQR's
    # summer analyst and AllianceBernstein's associate among them, and it is
    # execution and portfolio construction, which is the reader's own subject.
    #
    # **`secondaries` was dropped after reading what it promotes.** All eleven
    # are private-equity, infrastructure and real-estate secondaries -- the
    # `discretionary_investing` exclusion, arriving under a markets-sounding
    # word.
    "etf", "market making", "portfolio implementation", "reference data",
    "multi asset", "investment grade", "high yield", "municipals",
    "separately managed accounts",
)


# --------------------------------------------------------------------------
# Hard negatives -- occupations a title fully determines
# --------------------------------------------------------------------------
#
# Each list is grouped by the reason it rejects, and the reason is stored with
# the tag: "what did the filter throw away, and on what word" is then one query
# rather than a re-run. Anything ambiguous belongs in `AMBIGUOUS` further down,
# not here -- a false rejection is the one failure this project treats as
# expensive, so the bar for entry is "no body text could change this".

UNRELATED = _terms(
    # front of house, facilities, skilled trades
    "receptionist", "reception", "front desk", "housekeeper", "housekeeping",
    "janitor", "custodian", "cleaner", "cleaning", "groundskeeper", "porter",
    "maintenance technician", "maintenance supervisor", "maintenance manager",
    "facilities technician", "hvac", "plumber", "electrician", "welder",
    "machinist", "carpenter", "roofer", "painter", "landscaper", "locksmith",
    "forklift", "warehouse", "picker", "packer", "driver", "truck driver",
    "delivery driver", "chauffeur", "courier", "mechanic", "technician",
    "installer", "fitter", "machine operator", "assembler", "seamstress",
    "operator", "detailer", "car wash", "rental agent", "rental sales",
    "fleet", "dispatcher", "groundsman", "handyman", "lifeguard",
    "guest service", "station manager", "airport", "buyer", "material planning",
    "lot attendant", "customer return", "production tech", "service advisor",
    "bar team", "team member", "crew member", "attendant",
    # health and care
    "nurse", "nursing", "physician", "surgeon", "dentist", "dental",
    "pharmacist", "pharmacy", "therapist", "physiotherapist", "psychologist",
    "caregiver", "care assistant", "midwife", "veterinarian", "paramedic",
    "radiologist", "medical assistant", "clinical", "patient care",
    # food, retail, hospitality
    "chef", "cook", "sous chef", "kitchen", "waiter", "waitress", "server",
    "barista", "bartender", "dishwasher", "restaurant", "catering",
    "food service", "store manager", "store associate", "sales associate",
    "shop assistant", "cashier", "merchandiser", "stylist", "barber",
    "hairdresser", "beautician", "tattoo", "piercing", "concierge", "valet",
    "flight attendant", "cabin crew", "pilot", "baggage", "housekeeping attendant",
    # education, public safety, social work
    "teacher", "tutor", "instructor", "lecturer", "childcare", "preschool",
    "daycare", "nanny", "social worker", "youth worker",
    "security guard", "guard", "firefighter", "police", "correctional",
    # engineering that is real engineering in the wrong industry
    "civil engineer", "mechanical engineer", "electrical engineer",
    "chemical engineer", "process engineer", "structural engineer",
    "manufacturing engineer", "production engineer", "field engineer",
    "service engineer", "operating engineer", "mining engineer",
    "avionics", "aircraft", "aerospace", "automotive", "construction",
    "site manager", "foreman", "surveyor", "geologist", "hydrogeologist",
    "biologist", "laboratory", "quality inspector", "production operator",
    "shift supervisor", "plant manager", "warehouse associate",
    "property manager", "leasing", "real estate agent", "facilities manager",
    "building automation", "process safety", "quality engineer",
    "building engineer", "robotics", "maintenance engineer", "hardware engineer",
    "packaging", "logistics coordinator", "supervisor", "foreperson",
    # Swedish, Danish, Norwegian
    "sjuksköterska", "undersköterska", "vårdbiträde", "läkare", "specialistläkare",
    "tandläkare", "tandsköterska", "fysioterapeut", "sjukgymnast", "arbetsterapeut",
    "barnmorska", "psykolog", "kurator", "logoped", "apotekare", "farmaceut",
    "medicinsk sekreterare", "personlig assistent", "boendestödjare",
    "socialsekreterare", "behandlingspedagog", "vårdcentral", "rehab",
    "kock", "kallskänka", "servitör", "servitris", "restaurangbiträde",
    "bagare", "köksmästare", "diskare", "kallskänk",
    "lokalvårdare", "städare", "städ", "vaktmästare", "fastighetsskötare",
    "chaufför", "lastbilsförare", "truckförare", "lagerarbetare", "montör",
    "svetsare", "elektriker", "snickare", "målare", "plattsättare", "murare",
    "mekaniker", "bärgare", "väktare", "brandman", "maskinförare",
    "lärare", "förskollärare", "barnskötare", "fritidspedagog", "rektor",
    "butikssäljare", "butikschef", "frisör", "florist", "hantverkare",
    "sygeplejerske", "pædagog", "tømrer", "rengøring", "kokk",
    # Widened with Sweden, which arrived as 48,173 postings on a board that
    # publishes no taxonomy at all -- so unlike Jobindex and MyCareersFuture
    # there is nothing to gate on but the words. The plural is half of it:
    # matching is exact, so `undersköterska` never saw `Undersköterskor`.
    # Every needle here was dry-run over all 236,077 live titles and none of
    # them touches a posting the tagger rates positively.
    "undersköterskor", "sjuksköterskor", "tandsköterskor", "tandhygienist",
    "personliga assistenter", "elevassistenter", "stödassistenter",
    "behandlingsassistenter", "vårdpersonal", "hemtjänst", "hemtjänsten",
    "äldreboende", "ungdomsboende", "gruppboende", "förskola", "förskolor",
    "hemstädning", "städuppdrag", "trädgårdsuppdrag", "barberare",
    "däckskiftare", "mötesbokare", "taxiförare", "ordningsvakt",
    "parkeringsvakt", "optiker", "kalkylator", "besiktningsman",
    "fastighetsskötare", "plattsättare", "golvläggare", "takläggare",
    "murare", "lackerare", "plåtslagare", "rivare", "konditor", "kallskänka",
    "maskinoperatörer", "montörer", "chaufförer", "lagermedarbetare",
    # Danish. `jobindex` is gated by its own taxonomy and leaks almost nothing,
    # but a `--since` top-up writes a NULL category and a NULL category passes
    # that gate -- these are what stands behind it.
    "sygeplejersker", "social- og sundhedsassistent", "sosu", "pædagoger",
    "pædagogmedhjælper", "lærer", "lærere", "tandlæge", "tandplejer",
    "rengøringsassistent", "kok", "tjener", "opvasker", "murer", "smed",
    "lagermedarbejder", "salgsassistent", "butiksassistent",
    "butiksmedarbejder", "plejehjem", "hjemmeplejen", "håndværker",
    "vægter",
    # Dutch, German, French
    "verpleegkundige", "verzorgende", "monteur", "schoonmaak", "docent",
    "magazijn", "verkoopmedewerker", "beveiliger",
    "pflegefachkraft", "krankenschwester", "erzieher", "verkäufer",
    "lagerist", "hausmeister", "koch", "fahrer", "mechatroniker",
    "infirmier", "cuisinier", "serveur", "vendeur", "technicien",
    "conducteur", "magasinier", "hôte", "hôtesse",
    "aushilfe", "minijob", "autovermietung", "bereitschaftsdienst",
    # Santander and Citi publish large Iberian and Latin American retail books
    # through the same Workday tenants as their trading desks, so these arrive
    # mixed into boards that are genuinely markets employers.
    "técnico", "tecnico", "reparación", "anfitrion", "anfitrión",
    "ejecutivo", "ejecutiva", "espec", "especialista", "operario", "auxiliar",
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
    "copywriter", "content writer", "social media", "graphic designer",
    "ux designer",
    # The company-secretary family, and it is a *governance officer* rather
    # than an assistant -- the two-word phrases only, because bare `secretary`
    # would be the `administrator` trap on the list below. Coeli's `Corporate
    # Secretary` was one of the reader's hand-rejections and it carries a body
    # too short for the absence test to read. Dry-run: 89 live titles, not one
    # rated positively, and they are DBS, LSEG, Apex and T. Rowe Price -- real
    # markets employers, whose company secretary is still not this line of work.
    "corporate secretary", "company secretary",
    "ui designer", "product designer", "designer", "design lead",
    "community manager", "customer success", "event manager",
    "legal counsel", "counsel", "paralegal", "attorney", "lawyer", "solicitor",
    "translator", "interpreter", "archivist", "librarian",
    "project manager", "programme manager", "program manager",
    "operations manager", "service manager", "general manager", "team leader",
    "subject matter expert", "corporate administrator", "senior executive",
    "associate executive", "training", "trainer", "quality assurance",
    "executive", "program administrator", "property administrator",
    "office coordinator", "administration",
    "rekryterare", "lönespecialist", "kommunikatör", "marknadsförare",
    "administratör", "avtalsadministratör", "jurist", "personalchef",
    "kundtjänst", "kundservice", "receptionist",
)

# Finance, but the relationship, advice and processing part of it. This is
# `CLAUDE.md`'s exclude list made concrete, and it is the list most likely to
# need trimming later -- `middle office` at a systematic fund is not what it is
# at a custodian. Anything that turns out to be borderline belongs in
# `AMBIGUOUS` instead, where a body decides it.
NON_QUANT_FINANCE = _terms(
    "relationship manager", "relationship banker", "personal banker",
    "private banker", "branch manager", "bank teller", "teller",
    "mortgage advisor", "mortgage adviser", "mortgage loan", "loan officer",
    "loan processor", "financial advisor", "financial adviser", "wealth advisor",
    "wealth manager", "wealth strategist", "client advisor", "insurance advisor",
    "insurance broker", "customer service", "client service", "client services",
    "customer care", "contact centre", "contact center", "call centre",
    "call center", "account manager", "account executive", "business development",
    "sales manager", "sales representative", "sales executive", "sales support",
    "inside sales", "telesales", "sales trader", "client onboarding",
    "onboarding specialist", "accountant", "accounting", "bookkeeper",
    "accounts payable", "accounts receivable", "financial reporting",
    "fund accounting", "fund administration", "fund administrator",
    "transfer agency", "tax manager", "tax advisor", "tax analyst", "auditor",
    "internal audit", "external audit", "compliance officer", "compliance analyst",
    "compliance manager", "regulatory reporting", "anti money laundering",
    "aml", "kyc", "know your customer", "financial crime", "fraud",
    "sanctions", "collections", "debt recovery", "underwriter", "underwriting",
    "claims", "claims handler", "actuary", "actuarial", "insurance pricing",
    "trade support", "trading support", "middle office", "back office",
    "settlements", "corporate actions", "reconciliation", "custody",
    "customer experience", "personal banking", "banking associate",
    "mobile mortgage", "financial services representative", "financial consultant",
    "personal financial", "wealth executive", "consumer banking", "retail banking",
    # Retail branch staff, added after a 1,000-posting machine-labelled sample
    # showed the largest single disagreement was `relevance: unknown` on
    # postings that are plainly nothing to do with markets. Bare `banker`
    # subsumes *Universal*, *Premier*, *Associate*, *Retail* and *Personal
    # Banker* on a token match; 1,435 postings carry it and not one of them was
    # rated positively by the tagger, which is the check that mattered.
    "banker", "banking advisor", "banking adviser",
    "client relationship consultant", "relationship consultant",
    "small business specialist", "client associate",
    # An audit or tax *programme* seat, which the analyst words above miss.
    "audit staff", "audit intern", "tax staff", "tax intern",
    # Lending, and the qualifier is the whole difference -- the same shape as
    # `Credit Risk Operations` and as the `investment analyst` exclusion the
    # sheet already forced. `Distressed Loan Analyst` reached `keep` on the
    # bare word *analyst* plus one phrase from a long body, and was labelled
    # "a lawyer/accountant job"; `Senior Lending Analyst - Portfolio & Risk
    # Analytics` reached `adjacent` on *risk analytics*. Step 5 runs first, so
    # `Quantitative Analyst, Lending` keeps its quant reading.
    "loan analyst", "lending analyst", "distressed loan", "loan servicing",
    # Real-estate and insurance broking. `Associate, Brokerage` and two
    # `Brokerage Coordinator` postings were all labelled "real estate job",
    # and the only live posting the bare word touches that the tagger rated
    # positively is `Senior Risk Analyst - Insurance Brokerage`, which belongs
    # here too. A prime-brokerage quant is unaffected: step 5 has already let
    # every quantitative title through by the time this runs.
    "brokerage",
    # Investment banking, which the sheet rejected nine rows in a row and
    # `ACTION-REQUIRED.md` recorded as a decision. Bare `capital markets` is
    # deliberately absent -- 166 titles carry it and three of them are quant
    # seats at RBC and a treasury desk; the two IB desks are named instead.
    "investment banking", "equity capital markets", "debt capital markets",
    # **The rest of the IB desk, at the reader's instruction that investment
    # banking is out of scope.** The three words above were already here, which
    # is why `Equity Capital Markets - Associate` at Rothschild was off the
    # board -- the gap was every IB title that does not spell "investment
    # banking".
    #
    # `corporate finance` is the one that mattered: 94 live titles, 19 of them
    # on the board, and it is what `Analytiker I EY Parthenon Corporate
    # Finance`, `Corporate Finance Specialist` and `SEB Corporate Finance and
    # Corporate Finance Growth Analysts` were all riding on. Its four
    # positively-rated hits were read -- three `Corporate Finance Executive
    # (Commodity Trading)` at one Singapore recruiter and an `Analyst,
    # Corporate Finance & Treasury` -- and none is quant work. A quantitative
    # title is safe regardless: step 5 has already kept it before step 6 runs.
    #
    # `mergers` is one needle for both spellings, because `&` folds to a space
    # and `Mergers & Acquisitions` and `Mergers and Acquisitions` share only
    # that word. `ecm` and `dcm` were kept after reading all 36 between them:
    # every one is an IB desk bar `Gap ECM Marketing Lead`, a retailer's
    # content management, which rejects anyway.
    #
    # **Three that look obviously right were dropped:**
    #
    # - **`m a`**, the folded form of `M&A`. 173 titles against 29 for
    #   `mergers`, and four of the positives could not be accounted for by
    #   reading the title -- a two-letter needle is the `AQR` and `tbe` shape,
    #   and `mergers` already covers the family.
    # - **`origination`** promotes 39 and its two positives are `Senior
    #   Associate Americas Fixed Income Origination` at LSEG and `UIT Trading &
    #   Origination` at Guggenheim. Those are markets desks, not IB coverage.
    # - **`corporate banking`** is on `MARKETS` deliberately and carries 89
    #   positively-rated titles. Moving it here would be a different decision
    #   from this one.
    #
    # `restructuring`, `ipo` and `syndicate` were measured and left: the first
    # two are ambiguous outside IB, and `syndicate` is four titles whose one
    # positive is an asset-backed debt syndication desk.
    "corporate finance", "mergers", "investment bank", "leveraged finance",
    "ecm", "dcm", "transaction advisory", "deal advisory", "capital raising",
    "loan syndication", "sponsor coverage", "investment banking division",
    "sales agent", "sales development", "account handler", "financial planner",
    "claim representative", "client manager", "deposit specialist",
    "commercial banking", "business banking", "premier banking",
    "bankrådgivare", "redovisningsekonom", "redovisningsansvarig",
    "ekonomiassistent", "löneadministratör", "revisor", "försäkringsrådgivare",
    "kundenberater", "bankfiliale", "conseiller clientèle",
    # Santander and Citi publish large Iberian and Latin American retail books
    # through the same tenants as their trading desks.
    "clientes", "cajero", "sucursal", "asesor", "atendimento", "gerente",
)

# Engineering titles, rejected only for the *absence* of markets. Two-sided
# because `Software Engineer, Trading Systems` at Optiver is exactly in scope
# and `Senior Backend Engineer, Payments Platform` at a retail bank is exactly
# not, and no amount of tuning a one-sided list separates them.
ENGINEERING = _terms(
    "software engineer", "software developer", "software development",
    "developer", "programmer", "full stack", "fullstack", "front end",
    "frontend", "back end", "backend", "web developer", "mobile developer",
    "android", "ios developer", "react", "angular",
    "devops", "sre", "site reliability", "cloud engineer", "cloud architect",
    "platform engineer", "infrastructure engineer", "network engineer",
    "systems engineer", "systems administrator", "system administrator",
    "database administrator", "security engineer", "cyber security",
    "cybersecurity", "information security", "penetration testing", "qa engineer",
    "test engineer", "automation engineer", "release engineer", "build engineer",
    "solution architect", "enterprise architect", "technical architect",
    "it support", "help desk", "helpdesk", "service desk", "desktop support",
    "application support", "technical support", "it project", "it business",
    "salesforce", "sap", "servicenow", "sharepoint", "scrum master",
    "product owner", "product manager", "business analyst", "data engineer",
    "data platform", "etl", "integration engineer", "ai engineer",
    "systemutvecklare", "utvecklare", "programmerare", "systemadministratör",
    "softwareentwickler", "entwickler", "développeur", "ontwikkelaar",
)

# **A Swedish job title is one token, which killed the Swedish half of the list
# above.** `utvecklare` has been a needle for a long time while the corpus
# advertises `Fullstackutvecklare` and `Javautvecklare` -- 855 live titles a
# whole-word match cannot see inside. Same shape as `tagging._TRADE_HEADS`, and
# safe for the same reason: the heads are long and Swedish is agglutinative.
#
# **This list stays two-sided, which is what makes a broad head safe.**
# `ENGINEERING` never rejects on its own -- step 7 keeps the posting whenever
# a markets word appears, so `Systemutvecklare till SEB Markets` survives and
# `Fullstackutvecklare till en e-handelsplattform` does not. That is why
# `-arkitekt` is here despite reaching ~25 town planners: the verdict is the
# one `_OFF_INDUSTRY` would reach, only under a less precise reason.
#
# **`-tekniker` and `-konsulent` were dropped.** `tekniker` is already gated
# twice over, and `konsulent` is the ordinary Danish word for a consultant.
ENGINEERING_HEADS = (
    "utvecklare", "udvikler", "utvikler", "programmerare", "arkitekt",
)

# Genuinely ambiguous: quantitative at one firm, commentary at the next. These
# are never rejected on a title -- they go to `undecided`, which is the queue
# that says "fetch this body". The economists live here, and this is why the
# description backfill has a priority order rather than being 42,730 fetches.
AMBIGUOUS = _terms(
    "analyst", "senior analyst", "financial analyst", "investment analyst",
    "credit analyst", "risk analyst", "data analyst", "business intelligence",
    "economist", "economics", "strategist", "consultant", "associate",
    "portfolio analyst", "performance analyst", "valuation", "valuations",
    "pricing analyst", "reporting analyst", "analytics", "modeller", "modeler",
    "data scientist", "data science", "machine learning", "statistician",
    "researcher", "research analyst", "investment officer", "treasury analyst",
    "analytiker", "ekonom", "nationalekonom", "analytikere", "analiste",
)

CRYPTO = _terms(
    "crypto", "cryptocurrency", "blockchain", "web3", "defi",
    "bitcoin", "ethereum", "nft",
)

# --------------------------------------------------------------------------
# Seniority, but only the end of the ladder that rejects
# --------------------------------------------------------------------------

# `vice president` is deliberately absent. At a bank it is a mid-career grade --
# State Street and Citi stamp it on five-year hires -- so treating it as an
# officer title would reject a large and genuinely relevant slice of the corpus.
#
# Bare `president` is absent for a duller reason: it is a token of *vice
# president*, so including it rejected every AVP and VP in the corpus while the
# comment above claimed the opposite. The list said one thing and did another,
# which is exactly the kind of confident wrong answer the evidence field exists
# to expose.
HEAD_OR_MD = _terms(
    "head of", "global head", "regional head", "group head", "chief",
    "managing director", "senior vice president", "executive vice president",
    "svp", "evp", "ceo", "cfo", "coo", "cto", "cio",
    "director", "partner", "verkställande direktör", "avdelningschef",
    "geschäftsführer", "directeur",
)

# Checked first and they win: a `Director` inside one of these is not the grade.
NOT_HEAD = _terms(
    "associate director", "assistant director", "deputy director",
    "director of engineering", "art director", "creative director",
    "funeral director", "board of directors",
)

# Swedish builds occupations by compounding, and token matching cannot see
# inside a compound: `chaufför` is in the list above and does not match
# `skåpbilschaufför`, so a van driver's ad reads as unclassifiable rather than
# as a driver. These are the occupational *heads* -- the last element, which is
# the one that names the job -- matched as a token suffix.
#
# The same trick would be wrong in English, where a compound is two tokens and
# the suffix test would fire on any word ending in the same letters. It is safe
# here because the heads are long and Swedish is agglutinative.
SWEDISH_HEADS = (
    "chaufför", "förare", "sköterska", "läkare", "lärare", "pedagog",
    "terapeut", "arbetare", "biträde", "säljare", "montör", "mekaniker",
    "tekniker", "vaktmästare", "städare", "snickare", "målare", "bagare",
    "brevbärare", "assistent", "handläggare", "sekreterare", "vårdare",
    # The plurals, and the Danish heads. Swedish inflects the head itself, so
    # `underskötersk*or*` ends in nothing the singular list can see, and
    # `däckmontörer`, `taxichaufförer` and `maskinoperatörer` were all reaching
    # the board. Danish compounds the same way: `musiklærer`, `timelærere`,
    # `konsultationssygeplejerske`, `klejnsmed`.
    "sköterskor", "montörer", "chaufförer", "operatörer", "väktare",
    "lærer", "lærere", "sygeplejerske", "sygeplejersker", "smed",
)
MIN_COMPOUND = 9  # shorter than this and a suffix is a coincidence


def compound(text: str, heads: tuple[str, ...] = SWEDISH_HEADS) -> str | None:
    """The first token of `text` that ends in an occupational head."""
    for token in text.split():
        if len(token) < MIN_COMPOUND:
            continue
        for head in heads:
            if len(token) > len(head) and token.endswith(head):
                return token
    return None

# Body-only, and the one gate a graduate cannot pass. A posting requiring a
# *future* graduation date is noise for someone who has already graduated, and
# titles never announce it -- `Summer Analyst` and `Analyst` look identical.
# Titles that say the posting is a student position outright. Their job is to
# corroborate the body gate below -- see `judge` step 4 for why a body alone is
# not allowed to reject a quantitative title.
INTERN_TITLE = _terms(
    "intern", "interns", "internship", "praktikant", "praktik", "praktikplats",
    "werkstudent", "stagiaire", "summer analyst", "summer associate",
    "summer intern", "sommarjobb", "co op", "student",
)

# Titles naming a formal programme that **requires** matriculation, so the
# title alone settles it. This is the module's asymmetry used exactly as
# intended: a title cannot prove a posting is relevant, and it can prove the
# posting is a job this reader cannot hold. A German *Duales Studium* or
# *Werkstudent* contract is void without current enrolment, and the reader has
# graduated.
#
# **Bare `intern` is deliberately not here**, and that is the whole care in
# this list. Aquatic Capital's `Quantitative Researcher, Early Career` and
# `Quantitative Researcher, PhD` are the most on-target postings in the corpus
# and an over-eager student rule threw them away once already. An internship
# is often open to a recent graduate; an enrolment-bound programme is not.
STUDENT_PROGRAMME = _terms(
    "duales studium", "dual course of studies", "duale ausbildung",
    "ausbildung zum", "ausbildung zur", "werkstudent", "werkstudentin",
    "werkstudium",
    # A contract or a contest that cannot be held without being a student, both
    # from the hand-labelled sheet: `Euronext Securities Copenhagen - Student
    # Employee` ("student job - also no relevant tasks") and Walleye's `Stock
    # Competition (2026)` ("this is a stock competition for students"). One
    # title each in the whole corpus and neither touches a posting the tagger
    # rates positively, which is the check that decides a needle here. Bare
    # `competition` is not on the list -- three titles carry it and one is a
    # *Competition Law* seat.
    "student employee", "student worker", "stock competition",
    "trading competition", "case competition", "student ambassador",
    # Swiss-German apprenticeships, which are the same contract as a *duales
    # Studium* one line up: a `Lehrstelle` cannot be held without being
    # enrolled, and `Lernende/r` is what the holder is called. 585 titles
    # across Switzerland, none rated positively.
    #
    # **`Praktikum` is deliberately not here and must not be added.** It is
    # German for *internship*, which is a contract rather than a programme --
    # the same call `CLAUDE.md` records for `vikarie`, and the dry-run makes
    # the point: its one positively-rated hit is `Praktikum Private Equity
    # (m/w/d)`, a posting this reader could take.
    "lehrstelle", "lernende", "lernender",
)

# `are enrolled` is deliberately absent: "employees who are enrolled in our
# benefits plan" is ordinary handbook language, and this list rejects outright.
STUDENT_ONLY = _terms(
    "currently enrolled", "must be enrolled", "still studying",
    "final year student", "final year students", "penultimate year",
    "graduating in 2027", "graduating in 2028", "expected graduation",
    "pursuing a degree", "currently pursuing a", "enrolled at a university",
    "studerar", "pågående studier", "under utbildning", "ingeschreven student",
)

# The reasons, so a caller can enumerate them without scraping the rules.
REASONS = (
    "unrelated_occupation",
    "corporate_function",
    "non_quant_finance",
    "pure_engineering",
    "too_senior",
    "student_only",
    "crypto_web3",
    "no_markets_signal",
)


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    verdict: str            # keep | reject | undecided
    reason: str | None      # one of REASONS, when the verdict is reject
    evidence: str | None    # the phrase that decided it
    confidence: str         # strong | weak


def judge(
    title: str,
    department: str | None = None,
    description: str | None = None,
) -> Verdict:
    """Decide whether a posting is worth reading, and record what decided it.

    `role` is the title and department -- what the posting is *for*. `body` is
    the description -- what the firm is *like*. Keeping them apart is what stops
    a quant fund's boilerplate from making its receptionist look relevant.

    The order of the tests is the argument. Occupation runs first because it is
    the only evidence here that is conclusive; the anchors run before the
    ambiguous-title tests because a posting that says *quantitative* has already
    answered the question those tests would be guessing at.
    """
    role = normalize(f"{title or ''} {department or ''}")
    body = normalize(description)
    has_body = len(body) > MIN_BODY

    quant_role = first(role, QUANT)
    # Split deliberately. A markets word in the title is about the job; the same
    # word in the body may only be about the employer's customers, which is how
    # a market-data vendor's every backend engineer came out as a markets hire.
    markets_role = first(role, MARKETS)
    markets_body = first(body, MARKETS)

    # **A methodology phrase is evidence only next to a markets anchor** -- the
    # two-sided test step 7 applies to engineering titles, which steps 6, 8 and
    # 9 never asked. The same question decides whether "monte carlo" is
    # derivatives pricing or radiation shielding.
    #
    # **Counting phrases was the obvious alternative and it was measured not to
    # work**: `Thermal - Fluids Analyst` carries *model validation* and
    # *numerical methods*, a payments company's `Data Scientist` carries *time
    # series* and *statistical modelling*. Two phrases each, no markets, both
    # rejected by hand. The dry-run moved 103 postings, hand-read in full: a
    # radiation-shielding engineer kept by *monte carlo*, a robotaxi tech lead
    # by *time series*, and a **garage-door salesman by *options pricing***.
    #
    # A phrase naming markets activity outright is exempt: a body saying
    # "backtesting for statistical arbitrage" has already answered the
    # question, and two tests pin that the narrowing does not cost it.
    markets_activity = first(body, QUANT_MARKETS_BODY)
    quant_body = markets_activity
    if quant_body is None and (markets_role or markets_body):
        quant_body = first(body, QUANT_METHOD_BODY)

    # `markets_activity` is the first half of `quant_body`, kept under its own
    # name because **overturning a title that already named the occupation
    # takes more than reading an ambiguous one**. Step 6 runs after step 5 has
    # let every quantitative title through, so by then the title says *wealth
    # advisor* and nothing quantitative -- and its escape was one `quant_body`
    # phrase, which a wealth manager's advertisement contains the way every
    # governance document contains "model validation". Measured: `Wealth
    # Advisor` with no body rejects, and the same title with a 28,572-character
    # body came back `undecided` on one phrase of the firm's self-description.

    # 1. A named occupation. The strongest evidence in the module -- but a
    #    quantitative word in the title *itself* means the title is doing
    #    something else ("Lead Technical Recruiter, Quant Engineering"), so it
    #    downgrades the rejection to a read rather than being overridden by it.
    for terms, reason in (
        (UNRELATED, "unrelated_occupation"),
        (CORPORATE, "corporate_function"),
    ):
        hit = first(role, terms) or compound(role)
        if hit:
            if quant_role:
                return Verdict("undecided", None, f"{hit} + {quant_role}", "weak")
            return Verdict("reject", reason, hit, "strong")

    # 2. Too senior to be reachable from under a year of experience. Read from
    #    the title alone: `Associate - Fund Governance` sits in a department
    #    called "Director Services", and a department is not a grade.
    just_title = normalize(title)
    if not first(just_title, NOT_HEAD):
        hit = first(just_title, HEAD_OR_MD)
        if hit:
            return Verdict("reject", "too_senior", hit, "strong")

    # 3. Crypto and web3 are an exclusion in their own right, and unlike most
    #    of this list the word means one thing wherever it appears.
    hit = first(role, CRYPTO)
    if hit:
        return Verdict("reject", "crypto_web3", hit, "strong")

    # 4a. A programme that cannot be held without being enrolled. Read from the
    #     title, and unlike the body gate below it needs no corroboration --
    #     the title *is* the contract.
    hit = first(role, STUDENT_PROGRAMME)
    if hit:
        return Verdict("reject", "student_only", hit, "strong")

    # 4b. A body demanding a future graduation date, which outranks the tests
    #     below -- `Quantitative Research Intern` is the most relevant title in
    #     the corpus and still unreachable for someone who has graduated.
    #
    #     **But a body alone is not enough**: Aquatic Capital's `Quantitative
    #     Researcher, Early Career` and `Quantitative Researcher, PhD` were
    #     both rejected on "expected graduation" and "pursuing a degree", which
    #     their bodies use to describe who *may* apply. So a quantitative title
    #     downgrades the gate to a read, as it does in step 1.
    hit = first(body, STUDENT_ONLY)
    if hit:
        student_title = first(role, INTERN_TITLE)
        if student_title:
            return Verdict("reject", "student_only",
                           f"{student_title} + {hit}", "strong")
        if quant_role or first(role, TITLE_ANCHOR):
            return Verdict("undecided", None,
                           f"{hit}, against a quantitative title", "weak")
        return Verdict("reject", "student_only", hit, "strong")

    # 5. The title says quantitative. There is nothing further to decide.
    if quant_role:
        return Verdict("keep", None, quant_role, "strong")

    # 6. Finance, but the relationship-and-processing part of it.
    hit = first(role, NON_QUANT_FINANCE)
    if hit:
        if markets_activity:
            return Verdict("undecided", None, f"{hit} + {markets_activity}", "weak")
        return Verdict("reject", "non_quant_finance", hit, "strong")

    # 6b. A title-only anchor, below the finance list on purpose -- `Sales
    #     Trader` has already rejected by the time this runs, and `Trader` has
    #     not been looked at by anything else.
    hit = first(role, TITLE_ANCHOR)
    if hit:
        return Verdict("keep", None, hit, "strong")

    # 7. Engineering, and three-sided rather than two. Where the markets word
    #    was found decides how far it carries: in the title it is the job, in
    #    the body it is only a maybe, and `undecided` is what a maybe is for.
    #    Collapsing that middle into `keep` is what filled the board with a
    #    vendor's backend engineers; collapsing it into `reject` would throw
    #    away the trading-systems roles this project exists to find.
    hit = first(role, ENGINEERING) or compound(role, ENGINEERING_HEADS)
    if hit:
        if quant_body:
            return Verdict("keep", None, f"{hit} + {quant_body}", "strong")
        if markets_role:
            return Verdict("keep", None, f"{hit} + {markets_role}", "weak")
        if markets_body:
            return Verdict("undecided", None, f"{hit} + {markets_body}", "weak")
        return Verdict("reject", "pure_engineering", hit,
                       "strong" if has_body else "weak")

    # 8. The ambiguous middle -- analysts, economists, strategists, consultants.
    #    Never rejected on a title. Without a body this is the backfill queue.
    hit = first(role, AMBIGUOUS)
    if hit:
        if quant_body:
            return Verdict("keep", None, f"{hit} + {quant_body}", "strong")
        if markets_role or markets_body:
            return Verdict("undecided", None,
                           f"{hit} + {markets_role or markets_body}", "weak")
        if has_body:
            return Verdict("reject", "non_quant_finance",
                           f"{hit}, no markets language in the body", "weak")
        return Verdict("undecided", None, hit, "weak")

    # 9. No rule fired, so the title matched nothing in any list -- and a title
    #    this module cannot place is exactly where body evidence is least
    #    trustworthy. `quantitative research` in a product designer's posting is
    #    user research, and `model validation` in a computational chemist's is
    #    chemistry; both landed in the keep list until this returned a maybe
    #    instead. A full body with no markets word anywhere in it, by contrast,
    #    is real evidence -- absence measured over a whole document.
    #
    #    **`markets_body` used to switch this rejection off, and that is the
    #    single largest hole the reader's hand-rejections found.** Of the 40
    #    postings they marked `rejected` on the live board, 19 escaped here on
    #    one `MARKETS` word in a body belonging to an employer rather than to
    #    the job: Adidas's `Part-Time Sales Consultants` and Fortum's `Balance
    #    Settlement Specialist` on bare *trading*, Karolinska Institutet's
    #    `Projektadministratör` on *front office* -- a hospital's reception
    #    desk -- a `Swedish Content Writer` on *market data*, and Accenture's
    #    `Service Now business architect` on *structuring*.
    #
    #    This module already says so twice and did not act on it here:
    #    `MARKETS` is a **role** list, banned from holding ordinary English
    #    because in a body it describes the employer's customers. So the
    #    absence test now reads the role only. Nothing is lost that a body can
    #    prove, because the branch above it is a body test: `quant_body` is
    #    markets *activity*, and a posting whose description names any is still
    #    held open. What is refused is the weaker claim -- that a firm
    #    mentioning markets somewhere makes an unreadable title into a job
    #    worth reading.
    #
    #    Only this step changes. Steps 7 and 8 still read `markets_body`, and
    #    should: there the title has already been recognised as an engineer or
    #    an analyst, so the body is corroborating a reading rather than
    #    supplying the only one there is.
    if quant_body:
        return Verdict("undecided", None, quant_body, "weak")
    if has_body and not markets_role:
        return Verdict("reject", "no_markets_signal", None, "weak")
    return Verdict("undecided", None, markets_role or markets_body, "weak")


# --------------------------------------------------------------------------
# Board profile -- the firm-level signal, measured rather than asserted
# --------------------------------------------------------------------------
#
# The obvious firm signal is `employers.category`, on the grounds that a
# regulator's classification beats a firm's own marketing. It does -- but it
# classifies the *licensed entity* while the board belongs to the *group*.
# LaSalle Investment Management Asia is a Singapore Capital Markets Services
# Licensee whose domain resolves to `jll.com`, 2,021 property-management
# postings; `airbus.com` arrived the same way via Airbus Aeroassurances. The
# category is not wrong, it is answering a different question.
#
# So the honest firm signal is measured from what the board actually publishes.
# It also catches a board that is somebody else's -- Palmer Square's careers
# page links to a jewellery retailer's Lever feed.

MIN_BOARD = 10  # below this a share is noise, not a profile

# A national feed is not a firm's board. Profiling one returns "non_markets",
# which is true and useless: it carries every job in the country by design.
#
# **The rule is the source's shape, not its size** -- if one token carries
# postings from thousands of unrelated employers, no profile of it means
# anything. Only `jobtech` was here for a long time, and once `board_profile`
# was wired to a gate that gap went live: `jobindex/denmark` sits on 13 keeps
# against a floor of 10, so a lexicon change costing Denmark four keeps would
# have silently gated the whole Danish feed.
NOT_A_BOARD = ("jobtech", "jobbsafari", "jobindex", "jobroom", "mycareersfuture")


def board_profile(keep: int, undecided: int, rejected: int) -> tuple[str, str] | None:
    """(profile, evidence) for one board, or None if there is too little to say.

    `undecided` counts towards relevance deliberately -- **but not as much as a
    keep**, and getting that wrong made the measure useless in the one
    direction it exists for. Scoring `keep + undecided` against the total
    called **`bosch.com` a markets board with `keep = 0`**: 149 unplaceable
    titles against 157 rejections is 49% "not rejected", and Bosch is a
    manufacturer.

    Counting `undecided` at all is still right -- a board of ambiguous finance
    titles is a finance employer nobody has read, and ignoring those would
    measure how many bodies we happened to fetch. What is wrong is treating "we
    could not read this" as equal to "we read it and it is markets work": in
    this corpus an undecided is overwhelmingly *a six-word title in some
    industry*. So it is worth a quarter of a keep, and a board with no keeps
    can never be `markets`.
    """
    total = keep + undecided + rejected
    if total < MIN_BOARD:
        return None
    # A keep is a full vote, an undecided a quarter of one -- the smallest
    # weight that still separates a board of unread finance titles from a board
    # of unread anything.
    relevant = keep + undecided
    weighted = (keep + 0.25 * undecided) / total
    if keep and weighted >= 0.40:
        profile = "markets"
    # **A share is the wrong statistic for a large board**, and `non_markets`
    # is the verdict that cannot afford to be wrong about one: `td.com` carries
    # 58 postings read as markets work and `dbs.com` 42 -- real desks at real
    # banks -- and both scored under 5% against 2,400 and 1,600 postings of
    # retail branch work. So the floor is absolute as well as proportional: a
    # board that has shown us `MIN_BOARD` markets postings is a markets
    # employer however much else it publishes.
    elif weighted >= 0.05 or keep >= MIN_BOARD:
        profile = "mixed"
    else:
        profile = "non_markets"
    return profile, f"{relevant}/{total} not rejected, {keep} of them read as markets work"
