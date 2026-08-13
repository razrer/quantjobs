# Job tagging — design

How a posting in `jobs` becomes a set of tags you can filter and rank on.
Nothing here is implemented yet; this is the design and its prerequisites.

## The one rule

**Tags rank, they never delete.** A posting the classifier thinks is irrelevant
keeps its row and gets tagged `relevance:rejected` with the evidence that said
so. This is principle 1 (never filter the universe) and principle 4 (classify at
read time) applied one layer up: a wrong classifier must be re-runnable over
history, and it cannot be if it deleted what it rejected.

Every dimension therefore has an explicit **`unknown`** value. A posting with no
seniority tag is indistinguishable from one nothing has looked at — the same
hole `ats.py` refuses to leave with its "untiered" state.

## Prerequisite: 92% of postings have no description

This blocks the whole design and should be built first.

| ATS | postings | description |
|---|---|---|
| workday | 7,086 | **none** |
| greenhouse | 188 | full |
| ashby | 91 | full |
| lever | 90 | short |
| breezy, bamboohr, personio, smartrecruiters | 208 | **none** |
| workable, recruitee | 72 | full |

The list endpoints those formats publish return title, location and date only.
`CLAUDE.md` says never to classify on a title alone, and this corpus shows
exactly why: a substring sweep for quant words over the 7,735 titles returns
884 hits, and among the most frequent are **`Corporate Administrator`** —
`admini`**`strat`**`or` contains "strat" — and **`Alpha Account Services Data
Analyst`**, because State Street's custody platform is *called* Alpha. Same
lesson as the roster's `GRASSHOPPER ESCAPEMENT, LLC`: a false hit hides a real
one, so it is worse than a false miss.

Workday's per-posting endpoint is
`/wday/cxs/{tenant}/{site}{externalPath}` and returns `jobDescription` —
verified against LSEG, 6,207 characters — plus `timeType`, `country` and
`startDate`, which feed three dimensions below. The other formats have
equivalents. This is ~7,300 fetches, parallel across tenants because the
throttle is per host.

Store the fetched body verbatim in `jobs.description`. Strip markup at read
time, not write time.

## Storage

```sql
CREATE TABLE job_tags (
    ats, token, job_id,          -- the posting, matching `jobs`
    dimension   TEXT NOT NULL,   -- seniority, code_depth, ...
    value       TEXT NOT NULL,   -- the bucket
    confidence  TEXT NOT NULL,   -- strong | weak
    evidence    TEXT,            -- the span that decided it
    tagger      INTEGER NOT NULL,-- lexicon version
    tagged_at   TEXT NOT NULL,
    PRIMARY KEY (ats, token, job_id, dimension, value)
);
```

Long and narrow, so one posting can hold several values in a dimension (a
multi-asset desk, two programming languages) without a schema change. Derived,
so it rebuilds from `jobs` on demand — same contract as `firms`.

`evidence` is not decoration. It is what let Stage 4 catch `australia.com`
matching a bank, and it is the only way to tell a lexicon bug from a genuinely
odd posting when a tag looks wrong.

`tagger` is the lexicon version. Bump it on every change and the diff between
two versions over the same corpus is a free regression test.

---

## The dimensions

Three groups: what the posting says, what we already know about the firm, and
what the two together mean for you.

### A. From the posting

**1. `relevance`** — `core` · `adjacent` · `rejected` · `unknown`

The include list from `CLAUDE.md`, not a keyword: quant research/analysis/
trading/development, systematic and algorithmic trading, alpha and signal
research, portfolio construction, execution research, strategist, market and
credit risk quant, model validation, and DS/ML *at a markets firm*. `adjacent`
is for the genuine maybes — a data-engineering role on a research platform.

**2. `role_family`** — `research` · `trading` · `quant_dev` · `risk` ·
`model_validation` · `data_science` · `portfolio_construction` · `execution` ·
`strategist` · `other`

Separate from relevance because the ranking treats them differently and because
one posting can be two of them.

**3. `seniority`** — `intern` · `student_only` · `new_grad` · `junior_0_2` ·
`mid_3_5` · `senior_6_10` · `lead` · `head_or_md` · `unknown`

`student_only` is its own bucket, not a flavour of intern: you have graduated,
so a posting requiring a *future* graduation date is noise, and it is noise that
titles never announce. The evidence lives in the body — "must be enrolled",
"graduating in 2027", "final-year students".

**4. `experience_floor`** — the smallest number of years the text demands, as an
integer, plus `unstated`

Parsed separately from `seniority` because the two disagree constantly: titles
say "Senior" over a body asking for three years, and Jane Street says "Trader"
over a body asking for none. Where they disagree, the body wins and both tags
are kept — the disagreement is itself a signal that the title is unreliable at
that firm.

**5. `code_depth`** — the ladder your question was really about

| | bucket | what it looks like |
|---|---|---|
| 0 | `none` | regulatory, compliance, policy; "familiarity with models" |
| 1 | `spreadsheet_sql` | Excel, VBA, SQL, a BI tool |
| 2 | `python_analytical` | pandas/numpy, notebooks, backtests — **your centre** |
| 3 | `python_production` | packaging, tests, CI, services in Python |
| 4 | `systems` | C++/Rust/Java as a primary requirement, latency work |
| 5 | `hardware` | FPGA, kernel bypass, colocation engineering |

Down-rank 4 and 5, never drop them: `CLAUDE.md` is explicit that many quant-dev
roles list C++ second and still fit. Keep `language:*` tags alongside
(`python`, `cpp`, `rust`, `java`, `kdb`, `matlab`, `r`, `sql`) so "C++ nice to
have" and "C++ expert" are distinguishable at read time rather than collapsed
into one number.

**6. `research_vs_engineering`** — `research_heavy` · `balanced` ·
`engineering_heavy`

Orthogonal to `code_depth`. A research-heavy role can be code-deep; a
platform role can be shallow. Both matter and one number cannot carry them.

**7. `asset_class`** — `equities` · `futures` · `fx` · `rates` · `credit` ·
`commodities` · `options_vol` · `crypto` · `multi_asset` · `unstated`

Multi-valued. `crypto` is an exclusion signal on its own, and a strong one when
it is the *only* value.

**8. `horizon`** — `hft` · `mid_frequency` · `stat_arb` · `long_horizon` ·
`fundamental_quant` · `unstated`

The best available predictor of whether `code_depth` 4 is real. An HFT desk
asking for Python is asking for glue; a stat-arb desk asking for Python means
it.

**9. `hard_gates`** — multi-valued, each one a reason you cannot apply

`phd_required` · `visa_sponsorship_none` · `security_clearance` ·
`specific_degree` · `local_language_required` · `onsite_only` ·
`years_above_floor`

Kept as tags rather than a filter so you can see how much of the market each
gate costs you. If half of Amsterdam says `visa_sponsorship_none`, that is
worth knowing as a number, not as an empty result list.

**10. `contract`** — `permanent` · `fixed_term` · `internship` · `contractor` ·
`part_time` · `unknown`

Workday's `timeType` gives this for free on 7,000 postings.

**11. `posting_language`** — ISO code, from the body

Routes the lexicon — "kvantitativ analytiker" and "handelaar" need the Swedish
and Dutch word lists — and is itself a signal: a Swedish-language posting at a
Stockholm firm is a local hire, an English one at the same firm is often the
international desk.

**12. `work_mode`** — `onsite` · `hybrid` · `remote` · `unstated`

**13. `hub`** — `stockholm` · `copenhagen` · `amsterdam` · `switzerland` ·
`hong_kong` · `singapore` · `deprioritized` · `other` · `unknown`

Normalized from `location`, which is free text and often several cities in one
string. Reuses `resolve.py`'s country normalizer rather than inventing a second
one.

**14. `compensation`** — `disclosed_band` (with the numbers) · `disclosed_vague`
· `undisclosed`

Almost entirely a US and increasingly a EU-transparency artefact, but where it
exists it is the cheapest seniority cross-check available.

**15. `freshness`** — `today` · `week` · `month` · `stale` · `unknown`

Workday publishes *"Posted 30+ Days Ago"*, a relative string, not a date. Store
the string verbatim and bucket it at read time; do not convert it to a date and
pretend it is one.

### B. From the firm — free, no description needed

These come from tables already built, which makes them available on the whole
corpus today rather than after the description backfill.

**16. `firm_type`** — `prop_trading` · `market_maker` · `hedge_fund` ·
`asset_manager` · `bank` · `pension` · `exchange` · `broker` · `vendor` ·
`insurance` · `unknown`

Derived from `employers.category`, the regulator's own classification, kept
verbatim at ingest for exactly this purpose. It is authoritative where a
description would be marketing.

**17. `firm_scale`** — `boutique` · `small` · `mid` · `large` · `unknown`

**We have no headcount, and this design does not pretend otherwise.** Three
proxies, tagged with which one was used:

- open postings on the firm's board — available now, and the shape of the
  distribution is informative on its own;
- `firms.source_count`, how many registries report the firm — already the
  corroboration proxy Stage 5 orders its queue by;
- registry category, which separates a licensed bank from a two-desk prop shop
  by legal form.

Failure modes, both real in this corpus: a group publishing through one board
reads as enormous (LSEG, 830 postings), and a firm hiring exclusively through
headhunters reads as tiny. The tag records the proxy so a wrong ranking is
traceable to it.

What you actually want from this dimension is not size but **hiring shape** —
whether there is a structured graduate track (banks, large asset managers) or a
single high-bar opening (prop shops). `firm_type` carries more of that than
`firm_scale` does, which is why it is listed first.

**18. `hiring_volume`** — postings on this board now, and the change since the
last poll

A firm that went from 2 openings to 9 is a different prospect from one sitting
at 9 all year. This needs no new data — `jobs.first_seen`/`last_seen` already
records it.

### C. Derived, for you specifically

**19. `fit`** — `apply_now` · `strong` · `plausible` · `stretch` ·
`out_of_scope`

The one dimension that encodes your profile: under a year of experience,
graduated, Python and research rather than C++ and systems.

**20. `exclusion_reason`** — multi-valued, and only ever advisory

`actuarial` · `insurance_pricing` · `non_markets_fintech` · `crypto_web3` ·
`too_senior` · `student_only` · `heavy_systems` · `wrong_geography`

Straight from the exclude list, one tag each so you can audit what the filter
threw away by category. `heavy_systems` and `wrong_geography` down-rank; the
rest reject.

---

## How a tag gets assigned

A funnel, cheapest first, because the corpus is 7,700 postings and the budget
is zero.

**Layer 1 — deterministic lexicon.** Multilingual word lists per dimension,
matched against the *body*, each hit recording its span as evidence. Handles
seniority, contract, language, hub, compensation, gates, freshness and the
firm-derived dimensions outright. Runs over the whole corpus in seconds and is
re-runnable, which is what makes a lexicon bug cheap.

Match on token boundaries, never substrings. `admini`**`strat`**`or` and State
Street's `Alpha` platform are both in this corpus, and both would be false hits
under a naive `in`.

**Layer 2 — adjudication**, for `relevance`, `role_family`, `code_depth` and
`research_vs_engineering`, which need to read the posting rather than scan it.
Only postings Layer 1 marks as plausible reach it — roughly 900 of 7,700 on
current numbers, and fewer once the rejections are properly evidenced. That is
a small enough set to run a model over, or to read yourself.

**Grade every tag `strong` or `weak`**, exactly as `domains.py` grades a match.
`weak` tags are stored and shown but never gate a decision on their own. The
lesson that produced that rule — `citadel.com` matching *Citadel Securities* —
applies here unchanged: a confident wrong answer costs more than no answer.

## Ranking is not tagging

Keep the score in a separate, cheap function over the tags. Re-weighting "how
much does C++ cost a posting" must not mean re-classifying 7,700 rows, and it
will be re-weighted often — after every week of applying, probably.

## How this stage knows it is finished

Tagging needs the same thing coverage needed in Stage 2: a fixture, or the
accuracy claim is a feeling.

- **A labelled sample of 100 postings**, hand-read once, spanning all ten ATS
  formats and at least three languages — the `roster.csv` of this layer.
- **Exit criterion:** every posting carries a value in every dimension,
  `unknown` included; the classifier reproduces the labelled sample at ≥90% on
  `relevance` and `seniority`; and **no false `rejected`** in the sample, which
  is the asymmetry this whole project is built on — a missed posting is the
  expensive failure, a false positive costs a few seconds of reading.
