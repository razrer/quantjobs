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

**1. `relevance`** — `relevant` · `less_relevant` · `adjacent` · `rejected` ·
`unknown`

**Distance from the centre, and nothing else.** The centre is modelling and
research; the include list from `CLAUDE.md` decides what is on the scale at all.

- `relevant` — the output is research, modelling or signal work
- `less_relevant` — real quant work, but the day job is trading, building or
  risk rather than research
- `adjacent` — a markets firm and a quantitative title, but the seat is
  operational or the signal is thin
- `rejected` — the exclude list

**Why four and not three.** The original scale was `core`/`adjacent`/`rejected`,
and the first three hand-labelled rows broke it: `adjacent` was written against
"a quant dev role, so less relevant for me" and against "very close to what I'm
looking for" in neighbouring rows of the same sheet. One value was carrying two
opposite meanings because the scale was being asked to encode *direction* as
well as distance — and direction is what `role_class` is for. Splitting them is
what made both legible.

**2. `role_class`** — `quant_research` · `quant_dev` · `trading` ·
`portfolio_management` · `risk` · `data_science` · `operations` ·
`engineering` · `unknown`

**One value, not a set.** It replaced a multi-valued `role_family`, which said
almost nothing: a single Schonfeld posting came back as research *and* trading
*and* quant_dev *and* risk *and* execution *and* portfolio_construction *and*
strategist, because every one of those words appears somewhere in a long body.
Seven values is a word count, not a classification.

Order is priority, and it encodes three decisions. `quant_dev` runs first so a
title naming both halves — `Quantitative Research / Developer`, which folds to
"research developer" — lands on the building half. `quant_research` runs before
`operations`, so a quant word outranks the name of the desk it sits on.
`operations` still runs before `trading`, so `Trading Operations Analyst` is
operations: the desk's name is not the role's name.

**What the reader is not looking for**, learned from the fixture and now three
named rules rather than a feeling:

- **Management.** Under a year of experience and no interest in running the
  work. A management title rejects outright unless an unambiguous quant word
  appears — `Head of Quantitative Research` survives and its *seniority* is
  what puts it out of reach, while `Director of Trading` does not.
- **Investing by judgement.** Private equity, sell-side research, traditional
  asset management, wealth. `investment analyst` and `portfolio analyst` had
  been filed as weak *positives*; nine consecutive hand-labelled rows said
  otherwise.
- **Trading is fine.** Confirmed rather than assumed: it sits at
  `less_relevant`, one step out from research, and stays readable. Splitting it
  by `trading_style` — quant seats up, pure seats down — was tried and
  measured at **one row out of eighty**, because the sheet contradicts itself
  on that axis twice: `Algorithmic Trader` is `less_relevant` and
  `Quantitative Trader` is `relevant`, and at one firm `Graduate Trader` is
  `less_relevant` while `Digital Assets Trader` is `adjacent`. `trading_style`
  still records the fact and is filterable; it does not imply a rank the
  evidence will not carry.

**2b. `desk`** — `front_office` · `middle_office` · `back_office` · `unstated`

The dimension a title almost never carries and a body almost always does, and
the only thing that separates two postings the title cannot. `Quantitative
Trading Associate` reads like a seat on the desk; its body is market-hours
oversight, runbooks, incident response and position reconciliation. A body
placing the role in the middle or back office demotes relevance one step.

Only a **body** may demote. `front_office` is checked first for the same
reason: a trading-floor posting names middle-office machinery all the time —
"a grasp of trade-lifecycle workflows" — while the reverse is rare, so the
specific claim has to beat the incidental mention.

**3. `seniority`** — `student_intern` · `new_grad` · `junior_0_2` · `mid_3_5` ·
`senior_6_10` · `lead` · `head_or_md` · `unknown`

**`intern` is not on this ladder, and one posting is the whole argument.**
Schonfeld's `Quantitative Research / Developer - Intern` demands "2–3 years
buy- or sell-side experience" and converts to full time. It is an internship
*contract* wrapped around a mid-level *bar*, and a ladder with `intern` on it
swallowed the posting whole — reporting the rank as "intern" while the body
asked for three years. The two facts are stored separately now: whether it is
an internship is `contract: internship`, and `seniority` always carries a level.

`student_intern` stays, because it is genuinely a rank: a posting requiring a
*future* graduation date is unreachable for someone who has graduated, whatever
else it says. Its evidence lives in the body — "must be enrolled", "graduating
in 2027", "final-year students" — and titles never announce it.

**4. `experience_floor`** — the smallest number of years the text demands, as an
integer, plus `unstated`

Parsed separately from `seniority` because the two disagree constantly: titles
say "Senior" over a body asking for three years, and Jane Street says "Trader"
over a body asking for none. Where they disagree, **the number wins**, and both
tags are kept — the disagreement is itself a signal that the title is
unreliable at that firm.

This is the one carve-out from "the rank is in the title", and it needs to be
narrow. That rule was written against *stray words*: a body saying "you report
to the Head of Trading" made `Graduate Trader` a `head_or_md` posting, because
those words describe somebody else's rank. A years figure is not that — it is
the posting stating its own bar. Both hand-labelled seniority disagreements
were exactly this shape: `Quantitative Trading Associate` reads junior on
"associate" and asks for "3+ years"; the Schonfeld internship above reads
intern and asks for "2–3".

*Smallest*, because a posting saying "3+ years, 5+ preferred" has a floor of
three. A floor never produces `head_or_md`, `lead`, `new_grad` or
`student_intern` — those are structural facts about a role rather than a length
of service, and overriding a graduate scheme to `senior_6_10` on a stray number
would drop it out of the shortlist entirely.

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
`onsite_only`

Kept as tags rather than a filter so you can see how much of the market each
gate costs you. If half of Amsterdam says `visa_sponsorship_none`, that is
worth knowing as a number, not as an empty result list.

**Education is read only when a doctorate is compulsory.** `specific_degree` is
gone from this list deliberately: every quantitative posting on earth prefers a
higher degree, so tagging the preference produces a dimension that fires on the
whole corpus and separates nothing. "PhD preferred", "MSc or PhD", "advanced
degree a plus" are all untagged; only a demand is a gate.

Two things that made this harder than it reads. `Ph.D.` folds to the two tokens
"ph d", so every needle spelled `phd` silently missed the postings that
punctuate it — which is most of them; it is folded to one word now. And
matching is on token runs, so " no phd required " *contains* " phd required "
and a posting saying the opposite of the gate would otherwise trip it.

**9b. `spoken_language`** — multi-valued, `none` when nothing is demanded

A **soft filter, never a gate**: it ranks a posting down one notch and never
drops it. English and Swedish are deliberately not on the list — you have both,
so a posting demanding either is not filtered by language at all. The old
`local_language_required` gate got this backwards and flagged "flytande
svenska" on Stockholm postings, the one hub the project cares most about, as
though it were an obstacle.

Requirement phrasing only, in twelve languages. A posting that merely *offers*
language classes is not asking for one.

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
`hong_kong` · `singapore` · `deprioritized` · `sweden_other` ·
`denmark_other` · `netherlands_other` · `other` · `unknown`

**Multi-valued.** `location` is free text and often several cities in one
string, and taking the first of them answered a question nobody asked: which of
a posting's cities the lexicon happens to list earliest. A seat open in
Amsterdam *and* London carries a row for each, the board counts it under both,
and the geography gate fires only when **none** of them is somewhere the reader
would go.

The three `*_other` values are the complement of a focus hub inside its own
country, so they are never emitted beside the hub they are the complement of —
`Stockholm, Sverige` is one job, and `sweden_other` beside `stockholm` would be
one posting asserting "in Sweden" and "in Sweden but not Stockholm" at once.
The collapse is on the country's own *name* and nothing else, so
`Copenhagen, Aarhus` keeps both.

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

- **A labelled sample of 100 postings**, hand-read once, spanning the ATS
  formats and several languages — the `roster.csv` of this layer.
- **Exit criterion:** every posting carries a value in every dimension,
  `unknown` included; the classifier reproduces the **hand-labelled** sample at
  ≥90% on `relevance`; and **no false `rejected`** in it, which is the
  asymmetry this whole project is built on — a missed posting is the expensive
  failure, a false positive costs a few seconds of reading.

  **Met at lexicon 36: relevance 96.2% (77/80), no false rejection, 1,079
  labelled rows scored.**

  `seniority` is on the bar, at the reader's request -- it is what keeps
  leadership off the board, which is the thing they most want filtered.
  **Measured as containment rather than as rung agreement: 14/14 of the
  hand-labelled leadership postings are withheld, at a cost of 2 `adjacent`
  rows.** Rung agreement is reported too and is 55.8%, and that number is not
  the bar, because: about a third of the labelled rows are titles
  stating no grade at all, where the tagger answers `unknown` deliberately —
  the rule adopted after a stray *partner* in a diversity paragraph made an
  internship a managing director. A `Senior X` posting the reader grades
  `mid_3_5` and the tagger grades `senior_6_10` is a disagreement about a word
  and an agreement about the decision, and only the decision has consequences.
  Both numbers are printed, and the rung number is split into *wrong* and
  *unanswered*, because only the first is evidence of a bug.

  **The bar is the hand sheet, and the machine sheet is scored beside it.**
  `auto_labels.csv` earns its place as a diagnostic — it found a body-matched
  `underwriting` rule wrongly rejecting 1,834 postings, which eighty hand rows
  never could — but its rubric prefers the generous label when torn, so it
  files `Slack Administrator` and `Director, GTM AI Enablement` as `adjacent`
  and its "false rejections" contradict the reader's own hand labels rather
  than the lexicon. Read them; do not gate on them.

Built as `sample` and `labels` in `labels.py`. Two things about the draw are
load-bearing and were wrong in the first attempt:

**The sample must not come from the top of the shortlist.** `list --limit 100`
sorts by fit, so it offers the hundred postings the tagger is most confident
about — a sample that can only ever find false *positives*, against a criterion
whose disqualifying condition is a false *rejection*.

**And stratifying over the whole corpus instead is the opposite mistake.** The
first sheet drew 30% of its rows from `out_of_scope`, which in a corpus of
69,961 means housekeepers, van drivers, dental nurses and lifecycle-marketing
directors. The reader's first seven rows were an AI-training gig, a compliance
officer, a commercial lawyer, an applied-AI engineer and a real-estate
acquisition manager, and the notes said so: *"totally wrong"*, *"totally
irrelevant"*, *"nothing to do with finance"*. **A false rejection can only hide
among postings that could plausibly be in scope** — rejecting a van driver is
not a mistake this lexicon can make, so confirming it measures nothing.

The draw therefore runs over a **frame**, not the corpus. Four gates:

| gate | why |
|---|---|
| live, with a URL | the advertisement has to be openable; half the first complaint was that it was gone |
| not `off_industry` | the board already refuses these, and a sheet that disagrees with the board grades the wrong classifier |
| written in English or Swedish | `posting_language`, and only a *positive* identification excludes — `unknown` stays |
| carries a markets or quant word | `judge` calls an unrecognised title `undecided`, which is most of a corpus of `Regional Sales Manager`; a verdict is not a signal |

That is 2,084 postings of 69,961, and the stratification is over `judge`'s own
verdicts: 35% `keep`, 35% `undecided` — the genuine ambiguity, where a human
hour buys most — and 30% **contested rejections**, the reasons a person could
reasonably overturn (`non_quant_finance`, `pure_engineering`, `too_senior`,
`student_only`). `unrelated_occupation` and `corporate_function` are never
asked about. One board may contribute two rows, so no single Workday tenant
fills the sheet.

**The sheet must not show the tagger's verdict** — and leaving the column out
is only half of that. The draw is built bucket by bucket, so writing it in draw
order put every `apply_now` in the first few rows and thirty `out_of_scope` in
one block: position leaked exactly what the hidden column would have. Rows are
scattered by a digest of the posting key, which is stable across redraws, so a
half-filled sheet is never rearranged under the reader. (`hash()` is salted per
process and would reshuffle on every run.)

Columns are in reading order: what you type first, the body next, the keys
last. The file is written with a BOM, because Excel on Windows reads a BOM-less
UTF-8 CSV as cp1252 and turns every Swedish and Dutch posting into mojibake.

`sample` is also non-destructive: a row already carrying a verdict keeps it, and
keeps it even when a later draw would not have picked that posting again.
Hand-labelling is the one input here that cannot be regenerated.
