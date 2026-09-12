# Job tagging — the dimensions and how they are decided

Layer 5. `quantscraper/tagging.py` turns a row in `jobs` into rows in
`job_tags`; `quantscraper/lexicon.py` holds the vocabulary and the "what is this
posting *not*" judgement. Run `python -m quantscraper list --dimensions` for the
live values.

## The one rule

**Tags rank, they never delete.** A posting the classifier rejects keeps its row
and gets `relevance: rejected` with the evidence that said so — principle 1 (never
filter the universe) and principle 4 (classify at read time) applied one layer up.
Every dimension has an explicit `unknown` or `unstated`, so a posting nothing
decided stays distinguishable from one nothing looked at.

The board is the only thing that removes, and it removes by not rendering — see
`GATES` in `tagging.py` and `web/build_data.py`. Deleting a gate puts those
postings back on the next build with no re-tag.

## Storage

```sql
CREATE TABLE job_tags (
    ats, token, job_id,          -- the posting, matching `jobs`
    dimension   TEXT NOT NULL,   -- seniority, code_depth, ...
    value       TEXT NOT NULL,   -- the bucket
    confidence  TEXT NOT NULL,   -- strong (read from a body) | weak (title only)
    evidence    TEXT,            -- the span that decided it
    tagger      INTEGER NOT NULL,-- lexicon version
    tagged_at   TEXT NOT NULL,
    PRIMARY KEY (ats, token, job_id, dimension, value)
);
```

**The primary key omits `tagger`, so this table does not keep history.**
`INSERT OR REPLACE` overwrites the previous version's row whenever a posting
keeps the same value, so only rows whose value *changed* survive a re-tag —
the opposite of a diff. Treat "compare two taggers" as unavailable, always pin
`tagger = TAGGER` when counting, and use `prune` to drop superseded versions.

## The dimensions

Multi-valued: `asset_class`, `hard_gates`, `horizon`, `language`,
`spoken_language`, `exclusion_reason`, `hub`. The rest carry one value.

| dimension | values |
|---|---|
| `relevance` | `relevant` · `less_relevant` · `adjacent` · `rejected` · `unknown` |
| `role_class` | `quant_research` · `quant_dev` · `trading` · `portfolio_management` · `risk` · `data_science` · `operations` · `engineering` · `unknown` |
| `desk` | `front_office` · `middle_office` · `back_office` · `unstated` |
| `seniority` | `new_grad` · `junior_0_2` · `mid_3_5` · `senior_6_10` · `lead` · `head_or_md` · `unknown` |
| `experience_floor` | the smallest number of years demanded, or `unstated` |
| `code_depth` | `spreadsheet_sql` · `python_analytical` · `python_production` · `systems` · `hardware` · `unknown` |
| `trading_style` | `quant` · `pure` · `unstated` |
| `asset_class` | equities · futures · fx · rates · credit · commodities · options_vol · crypto · multi_asset · `unstated` |
| `horizon` | `hft` · `mid_frequency` · `stat_arb` · `long_horizon` · `unknown` |
| `hard_gates` | `phd_required` · `visa_sponsorship_none` · `student_only` · `security_clearance` · `onsite_only` · `unknown` |
| `spoken_language` | a language the posting *requires*, or `none` |
| `posting_language` | ISO code of the language it is *written* in, `cjk`, or `unknown` |
| `contract` | `permanent` · `fixed_term` · `internship` · `contractor` · `part_time` · `unknown` |
| `hub` | the nine focus hubs · `us_other` · `deprioritized` · `sweden_other` · `denmark_other` · `netherlands_other` · `other` · `unknown` |
| `exclusion_reason` | why a posting ranks down or comes off the board |
| `fit` | `apply_now` · `strong` · `plausible` · `stretch` · `out_of_scope` · `unknown` |

**Four scales rather than three for relevance.** `core`/`adjacent`/`rejected`
broke on the first three hand-labelled rows: `adjacent` was written against both
"a quant dev role, so less relevant" and "very close to what I'm looking for" in
neighbouring rows, because one value was carrying *direction* as well as
distance. Direction is `role_class`; distance is `relevance`.

**`intern` and `student_intern` are not ranks.** Schonfeld's `Quantitative
Research / Developer - Intern` demands "2–3 years": an internship *contract*
around a mid-level *bar*. Being an internship is `contract`, being a student is
`hard_gates: student_only`, and `seniority` always carries a level.

**`hub` is multi-valued and a country bucket is a complement.** A seat open in
Amsterdam and London carries a row for each and the geography gate fires only
when *none* of them is somewhere the reader would go. But `sweden_other` means
"in Sweden and not Stockholm", so it is dropped beside `stockholm` — and only
when every needle it matched was the country's own name, or `Copenhagen, Aarhus`
loses its second city.

**A national board writes an administrative place, and the reader has to bring
the country.** Jobindex writes a postcode and a town, job-room.ch a town and a
canton code, and Hong Kong's statutory board writes a *neighbourhood* --
`Tsing Yi`, `Kwai Hing`, `Mong Kok`, finer even than its own 21-district
taxonomy. None of those matches a needle, so all of them read `other`, which
the board gates. The handle is not a longer place list: it is the source
prefixing the territory, as `mycareersfuture._location` and
`iesjobs._location` both do. **Whenever a new source lands, bucket its `hub`
values before believing the board** -- `other` filling up is what a place-list
gap looks like from outside.

**The strongest gate a source can give you is its own occupation taxonomy,
and it is only usable if the slices *partition*.** JobStream files every
Swedish ad under one of 21 `occupation_field` values, MyCareersFuture and
Jobindex under several categories each, and Hong Kong's statutory board under
exactly one of 29 job types — measured, its hitcounts sum to 14,287 against an
unfiltered total of 14,287. That last one is why `_IES_OFF_INDUSTRY` is an
**equality** test where `_MCF_OFF_INDUSTRY` and `_JOBINDEX_OFF_INDUSTRY` are
subset tests: with a partition, one label is the whole of what the employer
said. The same portal's 27-industry facet sums to 15,175 and is refused for
exactly that reason — it covers rather than partitions, so a posting filed
under none would be missing and the arithmetic would still look right.

Each of the four is a **drop** list rather than a keep list, because an
unrecognised label has to pass: failing towards keeping is the direction this
project always picks. And each keeps its catch-all — `Others`, `Øvrige`,
`Other Professional/Associate Professional` — since a catch-all is where a
posting nobody classified lands, which is the opposite of evidence.

**Considered and deliberately not built:** `research_vs_engineering`,
`work_mode`, `compensation`, `freshness`, `firm_type`, `firm_scale`,
`hiring_volume`. The firm-level signal that survived is
`lexicon.board_profile`, measured from what a board actually publishes rather
than from what the firm calls itself — `employers.category` classifies the
*licensed entity* while the board belongs to the *group*, which is how a
Singapore Capital Markets Services Licensee resolves to 2,021 property postings.

## How a tag gets assigned

**The title decides what the role *is*; the body decides everything else.**
Scoring relevance over a body made `Insurance Accounting & Reporting Specialist`
a core quant role three times over, because "strong quantitative skills" is
boilerplate and every bank's about-us names market and credit risk. This is not
classifying on the title alone — a title carrying no signal falls through to the
body, and seniority, gates, languages and asset class are read from a body
throughout. It is the title winning where the two disagree.

**The body reaches rank through two doors only**: an explicit years figure,
which states the posting's own bar rather than describing somebody else's, and
`student_only`, because no title announces "must be graduating in 2028".

**Match on token boundaries, never substrings.** `admini`*strat*`or` and State
Street's `Alpha` platform were both real false hits. Text is folded to spaced
tokens and every needle matched with its padding.

**Grade every tag `strong` or `weak`**, as `domains.py` grades a match. A tag
read from a body is evidence; a tag read from a six-word title is a guess that
happens to be usually right.

**And where there is no text at all, the *employer* is the last evidence
there is.** Two branches read `tagging.quant_boards` — a board where at
least two titles and at least 5% of them name quant work or a quant domain —
and both fire **only when the posting has no body**:

- `pure_engineering` ranks instead of rejecting. The reader's own scope calls
  heavy systems engineering a down-rank rather than a hard drop, and `judge`
  step 7 is three-sided on markets words *in the posting*, so a firm that
  publishes no descriptions has no side to land on.
- `unknown` becomes `adjacent`. This is the mirror of `non_markets_board`,
  which removes a posting nothing could read on a board that publishes no
  markets work; until now the mirror did not exist.

The profile is measured from **titles alone** — no tags, no bodies — so it
cannot feed the tagger its own output, and `_fit` notches whatever it confers
one bucket down, because a relevance read off the employer is weaker than one
read off the posting's own text.

## How this stage knows it is finished

A hand-labelled fixture, or the accuracy claim is a feeling. Built as `sample`
and `labels` in `labels.py`.

**Exit criterion:** every posting carries a value in every dimension, `unknown`
included; the classifier reproduces the hand-labelled sample at ≥90% on
`relevance`; and **no false `rejected`** in it — a missed posting is the
expensive failure, a false positive costs a few seconds of reading.

**Met**: relevance 95.6% on the hand sheet with no false rejection.

`seniority` is on the bar too, at the reader's request, and is scored by **what
it is for**. Rung agreement is 55.8% and is not the bar: about a third of the
labelled rows state no grade, where the tagger answers `unknown` deliberately,
and a `Senior X` posting the reader grades `mid_3_5` is a disagreement about a
word and an agreement about the decision. What gates is `labels.containment` —
how much labelled leadership the board withholds (14/14) against how many
openings the rank gate cost (2). Those two errors are not interchangeable, so
netting them off would hide both, and the rung number is split into *wrong*
(what a lexicon fix can move) and *unanswered* (what it cannot).

### The draw is the whole method

**The sample must not come from the top of the shortlist.** `list --limit 100`
sorts by fit, so it offers the hundred postings the tagger is most confident
about — a sample that can only find false *positives*, against a criterion whose
disqualifying condition is a false *rejection*.

**And stratifying over the whole corpus is the opposite mistake.** The first
sheet drew 30% of its rows from `out_of_scope`, which in this corpus is
housekeepers, van drivers and dental nurses; the notes came back *"totally
irrelevant"*, *"nothing to do with finance"*. **A false rejection can only hide
among postings that could plausibly be in scope** — rejecting a van driver is
not a mistake this lexicon can make, so confirming it measures nothing.

So `labels._candidates` draws from a **frame** of ~2,000:

| gate | why |
|---|---|
| live, with a URL | the advertisement has to be openable |
| not gated by the board | a sheet that disagrees with the board grades a classifier nobody reads |
| English or Swedish | and only a *positive* identification excludes; `unknown` stays |
| carries a markets or quant word | `judge` calls an unrecognised title `undecided`, which is most of a corpus of `Regional Sales Manager` — a verdict is not a signal |

Stratified over `judge`'s own verdicts: `keep`, `undecided` (the genuine
ambiguity, where a human hour buys most), and the **contested rejections** a
person could reasonably overturn. `unrelated_occupation` and
`corporate_function` are never put to a human at all.

**The sheet must not show the tagger's verdict** — and leaving the column out is
only half of that. Built bucket by bucket, the draw order leaks the verdict as
plainly as a column would, so rows are scattered by a digest of the posting key.
Stable across redraws, so a half-filled sheet is never rearranged under the
reader; `hash()` is salted per process and would reshuffle every run.

**The sheet does not carry the description, and measuring that was worth
13x.** The three sheets were 4.3 MB of which **3.6 MB was a verbatim copy of
`jobs.description`** — a column the database already owns, checked into git and
rewritten in full on every redraw. Every binary alternative was measured
against simply dropping it and every one lost: SQLite as a table is **4.9 MB**
(larger, on page overhead), CSV+gzip 1.4 MB, CSV+xz 0.9 MB, and Parquet lands
near those while costing a third-party dependency, the git diff, the Excel edit
and `web/serve.py`'s write path. The sheets are 604 KB now. What a labeller
keeps is the title, firm, place, department and a **clickable `url`** — the
posting itself rather than a 4,000-character truncation of it. **The verdicts
are the only thing in these files that cannot be regenerated**; the context
always could be.

The file is written with a BOM, because Excel on Windows reads a BOM-less UTF-8
CSV as cp1252 and turns every Swedish posting into mojibake. `sample` is
non-destructive: a row already carrying a verdict keeps it. Hand-labelling is
the one input here that cannot be regenerated.

**The two machine sheets are scored beside the hand sheet, never gated on.**
`auto_labels.csv` earns its place as a diagnostic — it found a body-matched
`underwriting` rule wrongly rejecting 1,834 postings, which eighty hand rows
never could — but its rubric prefers the generous label when torn, so its
"false rejections" contradict the reader's own hand labels rather than the
lexicon. `agent_labels.csv` joined it after the reader confirmed it, and it is
the noisiest of the three: twelve model labellers over 471 postings, told to
prefer `adjacent` when torn, which duly produced `adjacent` for
`Slack Administrator` and `rejected` for
`Junior Quantitative Analyst (Credit & FI)`.

**Read the per-file lines, never the blended one.** Relevance agreement is
84.9% on the hand sheet, 77.9% on auto and **45.0%** on agent; averaged
together that is 69.0%, which measures the labellers rather than the
classifier. The same asymmetry is why every disagreement carries the sheet it
came from: the exit criterion is *no false rejection*, and the list runs
**41 agent, 37 auto, 0 hand** — the number that matters is the last one, and
without the provenance it is invisible.

**The bar is still the hand sheet, and the criterion in `cli.py` says so in
code.** A machine sheet is evidence to mine, not a target to tune against.
