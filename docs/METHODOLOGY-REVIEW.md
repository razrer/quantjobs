# Methodology review — 22 October 2026

Read against the live database and today's build. Nothing here is implemented.
Current policy is [METHODOLOGY.md](../METHODOLOGY.md); this document proposes
changes to it and marks each claim by how it was established:

- **(M)** measured today against `employers.sqlite3`, `web/data.js` or
  `logs/weekly-2026-10-22-124733.*`
- **(C)** read off the code, not measured
- **(P)** candidate route, not verified — the probe that would decide it is stated

Findings are ranked by expected value, not by layer. Section 4 maps each one to
the code it would collapse, which is the part meant to be read alongside a
refactor.

---

## 1. The measured state of the pipeline

### 1.1 The funnel, end to end (M)

| Stage | Count | Notes |
|---|---|---|
| Registry rows (`employers`) | 81,209 | 14 registries, all refreshed today |
| Firms after identity resolution | 70,370 | |
| Firm names probed for a domain | 53,789 | 16,581 firms never probed |
| Domains resolved | 35,323 | 65.7% of those probed |
| Domains probed for a board | 20,033 | |
| → tier A (board fingerprinted) | **1,263** | |
| → tier B (careers page, no vendor) | 3,561 | watched for change only |
| → tier C (no careers page found) | 15,209 | |
| Boards actually polled this week | **1,133** | 130 tier-A rows unreachable — see F6 |
| Postings held (`jobs`) | 1,187,720 | 921,024 (77.5%) from six national portals |
| Tag rows (`job_tags`) | 19,321,954 | 16.3 per posting, one live `TAGGER` |
| Cards on the board | **4,187** | 1,216 distinct firms |
| Shortlist (`apply_now` + `strong`) | **283** | 37 + 246 |

70,370 firms produce 1,216 firms visible on the board: 1.7%. That number is not
by itself a failure — most Form ADV filers should never appear — but it is the
funnel every finding below acts on.

### 1.2 Yield per source (M)

Cards and shortlist from today's build, against rows held per source.

| Source | Rows held | Cards | Shortlist | Cards / 1k rows |
|---|---|---|---|---|
| avature | 79 | 42 | 13 | **532** |
| site (hand-written readers) | 1,482 | 248 | 26 | **167** |
| eightfold | 1,324 | 100 | 14 | 76 |
| greenhouse | 13,748 | 704 | **84** | 51 |
| lever | 2,061 | 31 | 4 | 15 |
| icims_cs | 12,196 | 166 | 4 | 14 |
| ukg | 2,076 | 12 | 3 | 5.8 |
| successfactors | 17,403 | 137 | 6 | 7.9 |
| ashby | 4,696 | 37 | 0 | 7.9 |
| workday | 142,542 | 869 | 40 | 6.1 |
| **mycareersfuture** | **309,100** | 932 | 54 | 3.0 |
| **jobroom** (CH) | **220,899** | 407 | 3 | 1.8 |
| oracle_hcm | 53,126 | 58 | 3 | 1.1 |
| **jobbsafari** | **163,551** | 86 | 13 | 0.5 |
| **jobindex** | **74,622** | 37 | 9 | 0.5 |
| **iesjobs** (HK) | **37,298** | 16 | **0** | 0.4 |
| **jobtech** (JobStream) | **115,554** | 5 | 4 | 0.04 |

The employer-first architecture is vindicated by its own numbers: Greenhouse
returns 51 cards per thousand rows ingested, JobStream 0.04. The six national
portals hold 77.5% of the corpus and supply 35% of the cards and 26% of the
shortlist.

### 1.3 What it costs (M)

- **Database: 9.69 GB** (2,366,835 × 4 KiB pages, freelist 0 — no reclaimable space).
  - `job_tags` text ≈ 2.84 GB (19.32M rows × 147 bytes measured) plus its three
    indexes ≈ **6.3 GB, about 65% of the database**
  - `jobs.description` 1.95 GB over 817,156 postings (20%)
  - everything else ≈ 1.4 GB
- **Weekly run ≈ 2 h 15 m** wall (12:47 → 15:03), dominated by the two
  four-second-interval portal sweeps: Singapore 956 pages, Hong Kong 650.
- **Code: 22,090 lines in `quantscraper`** — 10,504 code, 4,892 comment,
  4,131 docstring, 2,563 blank. **41% is prose.** Tests are 14,851 lines over
  1,130 cases; `tests/test_tagging.py` alone is 3,207 lines and 277 cases with
  443 inline literals. `web/build_data.py` is 1,143 lines of which 464 is code.

That last line matters for the refactor brief: there are not 22,000 lines of
code to shorten. There are ~10,500, and they are reasonably tight for 34 ATS
readers, six national portals, 14 registries and a 16-dimension classifier. The
two real levers are (a) the 9,023 prose lines, which AGENTS.md already says
belong in `docs/history`, and (b) structural duplication inside the 10,500.

---

## 2. Findings

### F1 — Layer 2 has not run since August. The pollable board set is frozen. (M)

`domain_lookups`: **53,742 of 53,789 rows last checked in August 2026**.
`ats_resolution`: **19,839 of 20,033 last checked in August 2026**. Forty-six
rows each in October.

`cli._daily` gathers `sweden`, `denmark`, `switzerland`, `jobstream`, `jobs`,
`pages`, and under `--full` adds `singapore`, `hongkong`, `registries`. It does
not run `resolve`, `domains`, `ats` or `discover`. So the 14 registries deliver
fresh employers every week — all 14 ran today — and nothing downstream looks at
them: no domain is resolved, no board is fingerprinted, no page enters the
watch list.

Three consequences, all silent:

- a firm that migrated ATS since August is quiet, and the only trace is its old
  board failing in `board_polls`;
- every employer registered since August has no domain and no board;
- the 15,209 tier-C and 3,561 tier-B rows have never been re-probed, although
  `ats.reprobe_targets` and `domains.regrade_targets` exist for exactly that.

This is the gap `docs/DISCOVERY-STRATEGY.md` named in September — "a standing
job sweep alone cannot find newly registered employers" — answered then by
adding `registries` to `--full` and not by scheduling what consumes them.

**Correction to the magnitude, measured while implementing this (22 October).**
The first draft above implied a large unworked backlog. It is not one: run by
hand, `domains` answered *"nothing left to probe in the focus sources"* and
`ats` found one untiered domain. The proximate cause is narrower and worse than
a backlog — **`resolve` is the blocked link.** Every Layer 2 queue is drawn from
`firms`, which `resolve` rebuilds from `employers`, and `resolve` had not run
since August. So the 1,984 employer rows that arrived in September and October
— 678 of them in the focus registries — were in no firm at all, and the queues
below were empty because they could not see them, not because the work was
done.

Proven by the fix: `resolve` took **4 seconds** and took `firms` from 70,370 to
**72,130**; `domains`, which had just reported nothing to do, then probed 40
firms and resolved **9 domains**. The cost of this defect is therefore ongoing
drift — roughly 500 unseen new firms a week, plus two re-verification passes
that have never run — rather than a one-time hole.

**Done (22 October).** `cli._layer2` runs `domains → ats → discover → regrade →
reprobe` in order inside a single concurrent gather slot, with `resolve` moved
into the `--full` prologue ahead of it; `alerts` grew a `layer2` check so the
layer going quiet is loud rather than invisible. Budgets are weekly rates
rather than a monthly block, because stages 54, 56 and 58 are all
missed-Wednesday incidents and a monthly trigger would have skipped a month on
any one of them. Two defects found on the way are in F6a.

**Refactor consequence:** `_daily`'s three hand-built step lists become one
phase table with a cadence column (`weekly` / `monthly` / `full`), which also
removes the duplication between `_daily`, `weekly.ps1` and the README's
description of them.

### F6a — Two scheduling defects that made the budgeted passes no-ops. (M)

Found by writing the tests for F1, and both are the same failure: a queue with
no cursor.

**`ats.reprobe_targets` was `ORDER BY a.tier, a.domain`.** `reprobe` writes a
row only when `_improves` allows it — the promotions-only rule, which is
correct — so the thousands it declines keep their old `checked_at` and keep
sorting first. Under a `--limit` that is not a queue: the same alphabetical
head of tier A every run, and tier B, the 3,561 rows the sweep exists for,
never reached at all. Fixed with an `ats_attempts` table on the
`pages.page_attempts` pattern — an attempt is not a result — and an oldest-
attempt ordering.

**`domains.regrade_targets` never selected `evidence`, and `regrade` writes it
back.** The `hit is None` branch builds `f"{row['evidence']} [unreachable at
regrade]"` outside the `try` that guards `verify`, so the `IndexError` escaped
`work`, came back out of `pool.map` and killed the pass on the first
unreachable host. The marker that branch exists to write has therefore **never
been written once**: 0 rows carry it, against a queue 3,502 deep — and the
comment beside it describes converging a loop that never converged. Two further
early returns from `work` recorded nothing either; all three now record the
attempt.

Both are pinned: `tests/test_ats.ReprobeCursorTest`,
`tests/test_domains.RegradeConvergesTest`.

### F2 — The census portals cost 77% of the corpus for 26% of the shortlist, and their own facets make a bounded cut measurable. (M)

Hong Kong, from today's log — one sweep of 650 pages, ~50 minutes, read against
a `robots.txt` that ends `Disallow: /`:

```
Cook / Waiter 1,138   Others 1,215        Cleaner 966      Construction 979
Driver 754            Clerk 726           Labourer 502     Management/Admin 896
Sales 1,058           Technician 515      Teacher 345      Stockkeeper 368
...  Computer and IT 202   Engineering 148   Other Professional 297   Accounting 328
```

Total 12,728 postings. Lifetime contribution to the board: **16 cards, 0
shortlisted, ever.** The portal publishes an enumerable job-type facet, and the
facets a quant role could plausibly be filed under (IT, Engineering, Other
Professional, Accounting, Management/Admin, Others) are ~3,100 postings — under
a quarter of the sweep.

The same shape holds for Jobindex's 81 subcategories, MyCareersFuture and
job-room.ch, and the corpus needed to decide it is already held.

**Do** — three parts, and the third is what keeps it honest:

1. Recompute, from the corpus you already have, the facet → outcome table for
   every census source: postings, non-rejected postings, cards, shortlist.
2. Read in full, weekly, every facet that has ever produced a non-rejected
   posting.
3. Read the residual as a **fixed, recorded random fraction** (10% is a
   starting point). This is the part that distinguishes this from narrowing: the
   sample *measures* what step 2 misses, continuously, instead of assuming it
   misses nothing. The repo's own counter-example — a Stockholm quant risk role
   that JobStream filed under *Säkerhet och bevakning* — is exactly the error
   the sample bounds.

Expected: ~70% fewer portal requests, 600–700k fewer rows, ~11M fewer tag rows,
a materially smaller database and a faster re-tag — with the coverage loss
bounded and reported rather than unbounded and assumed. It is also the
strongest available answer to item 4 of ACTION-REQUIRED: read less of the board
that asked you not to be read.

**Decided: adopted, with a 10% check sample on the dropped facets — see §6.**

**Refactor consequence:** one census walker with a facet config and a sample
rate replaces six bespoke partition strategies — see §4.

### F3 — `job_tags` is 65% of the database and most of it is one fact repeated 16 times. (M)

19,321,954 rows, 147 bytes of text each, plus three indexes. Every row carries:

- the `(ats, token, job_id)` text triple — ~45 bytes, repeated 16.3× per posting
  in the table and again in each of three indexes;
- `tagger` and `tagged_at`, which are properties of *the posting's last tagging
  run*, not of the tag. `job_tags_by_tagger` exists only to make that
  redundancy queryable — its own comment records that the query otherwise
  walked every row of a posting to test one column.

**Do:**

1. An integer surrogate key on `jobs`; `job_tags` keyed on it. Saves ~45 bytes
   per row in the table and ~35 in each index.
2. Move `tagger` / `tagged_at` into `job_tagged(job, tagger, tagged_at)` —
   1.19M rows instead of 19.32M copies — which deletes `job_tags_by_tagger`
   entirely and turns "is this posting current" from a correlated `NOT EXISTS`
   into a single-row lookup.
3. `confidence` as an integer; it has two values.

Estimated 3–4 GB saved and a faster `tag` queue. With F2 the database plausibly
lands near 1.5–2 GB, which makes it backupable and makes a full re-tag cheap
enough to stop being a scheduling event.

### F4 — Nothing in the project uses conditional GET. (C)

No `If-None-Match`, no `If-Modified-Since`, no stored ETag anywhere. Every
weekly run re-downloads all 1,133 boards and all 3,312 tier-B pages in full.

`pages.py` is the sharpest case: it exists *only* to detect whether a page
changed, and HTTP has a purpose-built one-header mechanism for that question.
A 304 would skip the fetch body, the link extraction and the fingerprint.

**Do:** store `etag` / `last_modified` per URL and send the validators; treat
304 as "unchanged". Measure the 304 rate before committing to it — many ATS
JSON APIs send no validators, but static careers pages overwhelmingly do.

Second, smaller: `urllib` opens a fresh TCP + TLS connection per request. At
~30k requests a week that is hours of handshake at no benefit. A pooled
connection (urllib3 — free, no account) is contained entirely behind
`http.get`.

**Refactor consequence:** both live inside `http.py`; no caller changes. The
throttle, the 429 schedule and the retry classification stay exactly as they
are — those are measured behaviour and must survive.

### F5 — Tier B is 3,561 pages that have never produced a posting, and 478 of them changed this week. (M)

`pages.py` argues, correctly, that a naive link extractor over a tier-B page
emits the firm's own navigation as job postings. Two non-naive extractors exist
and neither is used:

**(a) schema.org `JobPosting` JSON-LD.** Google for Jobs made this near-universal
on careers pages whose postings are rendered by script — which is precisely the
tier-B failure mode. `bodies.py` already parses JSON-LD for iCIMS, so the
parser is in the repo. A nav link is not a `JobPosting` object, so this cannot
produce the failure `pages.py` is designed against.

**(b) `sitemap.xml` and the `Sitemap:` directive in `robots.txt`.** Used here
for exactly one firm (Citadel, in `sites.py`). A careers sitemap enumerates
posting URLs deterministically, and it is also the fix for the failure
`discover.py` documents — Jane Street's stored careers URL is an overview page,
DRW's is a Cloudinary image, Man Group's is a PDF, so the roles page was never
fetched.

**Also in tier B right now (M):** 386 of 3,560 careers URLs are on third-party
hosts across 318 distinct hosts. **32 of them are on an ATS vendor host — i.e.
pollable boards sitting in tier B:**

| Host | Rows | What it is |
|---|---|---|
| `jobs.dayforcehcm.com` | 5 | Ceridian Dayforce |
| `ats.rippling.com` | 4 | Rippling |
| `*.applytojob.com` | 4 | JazzHR |
| `recruiting.paylocity.com` | 3 | Paylocity |
| `www.paycomonline.net` | 3 | Paycom |
| `careers.hibob.com` | 3 | HiBob |
| `*.cornerstone*` | 3 | Cornerstone OnDemand |
| `jobs.eu.lever.co` | 2 | **Lever's EU host — the pattern `jobs\.lever\.co/` does not match it, and a `lever` reader already exists** |
| `de.umantis.com` | 2 | Umantis (DACH) |
| `*.talentview.io` | 2 | TalentView |
| `*.tal.net` | 1 | Lumesse / Saba TalentLink |

Thirty-two firms is a modest prize and a cheap one: eight host patterns, and
one of them (Lever EU) is a one-character class of bug against a reader that
already exists. The log also shows `bloomberg.avature.net/careers/SearchJobs`
and `jefferies.tal.net/...` in the change report, so the same shape reaches
firms worth having.

And ~25 tier-B rows are not careers pages at all: `prnewswire.com` ×9,
`techcrunch.com` ×5, `www.google.com` ×3, `cnbc.com` ×2,
`framerusercontent.com`, `protection.outlook.com`. Plus 27 on `linkedin.com`.
`ats.careers_candidates` is landing on press coverage and platform pages, which
is both wasted weekly polling and noise in the change report.

**Do:** generic JSON-LD and sitemap readers over tier B, writing with a
distinct low-confidence provenance so the whole route can be audited or
withdrawn wholesale; the vendor patterns above; and a precision pass on
`careers_candidates` to reject press and platform hosts (`is_platform_domain`
exists and is not applied to the chosen careers URL).

**Refactor consequence:** `sites.py` shrinks. Several of its 15 hand-written
readers are "this page has JSON-LD" or "this firm publishes a careers sitemap",
and its own docstring says a hand-written reader is a liability to be deleted
the moment something generic covers it.

### F6 — Forty-six resolved boards no poller can reach, and one of them is a token-extraction bug worth 17 boards. (M)

`ats_resolution` holds 10 tier-A rows with `ats='taleo'` and there is no
`taleo` extractor, plus 36 tier-A rows with a NULL or empty token.
`extract.targets` filters to `EXTRACTORS`, so all 46 fail silently — which is
the one state `ats.py`'s docstring says must not exist, reached from the other
direction. Today's log reads "polled 1,133 boards" against 1,263 tier-A rows,
and nothing reconciles the two numbers.

**The 36 tokenless rows are 17 SuccessFactors boards and the evidence column
says why.** Those rows were fingerprinted on `career2.successfactors.eu` and
`career5.successfactors.eu` — a host naming the vendor's *datacentre*, not the
tenant. SuccessFactors carries the company in the path, so the host pattern
matched, the token builder had nothing to read, and the row landed at tier A
with a NULL token. Structurally the same failure as the Greenhouse `embed`
capture, in a different vendor. The boards it costs:

> Eurex, Clearstream, Hang Seng Bank, PFA, Scania, Moody's, Worldline,
> Paysafe, Royal London, Allianz Life, Orkla, Vistra, Equiti, Bentley,
> Clarion, PayOne, Turning Leaf

Eurex and Clearstream are Deutsche Börse group and Eurex is already a registry
source here; Hang Seng is a Hong Kong focus-hub employer; PFA is a Copenhagen
one. Two further things visible in the same rows: `eurex.com`'s stored careers
URL contains `&amp;` verbatim — the HTML-entity bug written up for
SuccessFactors URLs, still present in this table — and `clarion.com` resolved
to `jobs.faurecia.com`, which is defensible on the acquisition but is the
`heyrowan` shape and should be re-verified.

**The Taleo ten are mostly not worth a reader.** Four carry `token='tbe'`,
which is the generic Taleo path segment and not a tenant; four are irrelevant
employers (a credit union, an insurer, `socialimpact.com`); the real ones are
Société Générale ×2 and OCBC.

**Do:** assert the invariant and report it through `alerts` — every tier-A row
has a non-empty token and an `ats` present in `EXTRACTORS`. Fix the
SuccessFactors token to read the tenant from the path. Regrade the Taleo ten
and let `discover` reach SocGen and OCBC by name. The *check* matters most: it
is the difference between a coverage hole and a coverage hole nobody can see.

### F7 — The employer names already in the database are the cheapest discovery route, and only Sweden uses them. (M/C)

`coverage.missed` lists employers advertising in JobStream that the pipeline
does not poll — for Sweden only, because `coverage.py` has exactly one second
sample and reports Copenhagen, Amsterdam, Switzerland, Hong Kong and Singapore
as unmeasured.

But `jobs.employer` is populated by every portal: 63,217 Danish rows carry an
employer domain, and MyCareersFuture, job-room.ch and IES all carry employer
names. **Every portal posting the lexicon does not reject, whose employer is
absent from `firms`, is a named discovery candidate with evidence attached — in
five more countries, at zero network cost.**

**Do:** a `discovery_candidates` table (`name`, `source_url`, `observed_at`,
`relationship`, `status`) fed from (a) portal employer names absent from
`firms`, and (b) the routes DISCOVERY-STRATEGY already evidenced; a
`discover --review` queue ordered by oldest unvisited; and the per-route yield
counters that document specifies and nothing records. This also unlocks
capture–recapture for four more hubs, which is the measurement `coverage.py`
was built for and cannot currently make.

### F8 — Tier C is 15,209 domains, and a sample says the answer is ranking, not more crawling. (M)

A random sample of tier C: `lfadvisors.com`, `crescentgroveadvisors.com`,
`westridgeadvisors.com`, `zicotrust.com`, `newmountainfinance.com`,
`resultatfabriken.se`. These are small Form ADV advisers. The funnel leak is
real; the population is mostly not worth a harder crawl.

**Do** two things instead:

1. **Rank the queue.** Score tier-C domains by employer plausibility: exchange
   or clearing membership, FIA EPTA, market-maker lists, focus-hub country, a
   quant word in the registry's own name or category field, and — see §3 — H-1B
   quant filings. Spend the crawl budget top-down, with a fixed exploration
   sample of the residual so ranking never becomes a permanent exclusion.
   DISCOVERY-STRATEGY already requires that sample; nothing implements it.
2. **Give the careers walk better entry points than homepage links.**
   - well-known paths, by language: `/careers`, `/jobs`, `/en/careers`,
     `/karriar`, `/jobb`, `/vacatures`, `/stellen`, `/work-with-us`,
     `/about/careers`, plus `sitemap.xml`;
   - **CNAME lookups** on `careers.<domain>`, `jobs.<domain>`,
     `apply.<domain>` — a careers subdomain pointing at a vendor host
     identifies the ATS without fetching a page at all, which is cheaper and
     more reliable than fingerprinting markup;
   - **Certificate Transparency** (crt.sh, free, no account) to enumerate those
     subdomains instead of guessing them. **(P)** — probe the JSON endpoint's
     rate behaviour before relying on it.

### F9 — The unread bucket is no longer a missing-body problem. (M)

Today's build: 4,187 cards, **1,385 with no `fit` (33%)**, and only **134 of
those lack a body**. `bodies.py` solved the gap it was built for — its
docstring's "a posting without a body stays `relevance: unknown` 9.3% of the
time" is no longer the binding constraint.

1,251 cards have a full description and the classifier placed none of them. More
body fetching will not empty that bucket. The combination rules will.

### F10 — Human agreement is 62.6%, and the weak part is the combination, not the evidence extraction. (M from PLAN.md, C)

`tag_posting` is a 685-line hand-ordered branch cascade; `_fit` is a five-bucket
ladder with composing "notches". Every individual branch is justified and most
are measured — that work is real and should be kept. What is hand-chosen is the
*order and the thresholds*, and there are now 2,387 human labels across three
sheets to choose them with instead.

**Do:** keep the lexicon as the **evidence extractor**. Its value is that it
produces inspectable spans, handles several languages, and re-runs over the
whole corpus for free. Replace the **combination** step with a linear model over
the extracted features — dimension values, evidence confidence, source,
employer prior — fitted on the human labels and cross-validated.

Why this is not a departure from the project's principles:

- **Deterministic at run time.** The weights are fitted once and shipped; a
  re-tag is a dot product, reproducible, and `fingerprint()` already exists to
  hash them into `TAGGER`.
- **Auditable.** A linear model over ~100 named features explains each card as
  its top contributing features, which is the same evidence contract the board
  already renders.
- **Free.** No inference spend, no account; scikit-learn, or ~80 lines of plain
  Python for a logistic fit.
- **It makes 62.6% an objective** instead of a recorded fact.
- **It produces a continuous score, which sorts.** The board currently has five
  buckets and 1,385 cards tied at the bottom.

**Keep the hard gates deterministic.** `off_industry`, `off_location`,
`student_only`, `phd_required`, `out_of_reach` are *policy*, not prediction, and
must not be learned from labels.

**Decided: adopted, on scikit-learn, with the hard gates staying rules — see §6.**

### F11 — Active learning instead of quota sampling. (C)

`labels.choose` draws by quota, contestability and board spread. Once a model is
fitted, the informative sample is the one it is least certain about, or where
model and lexicon disagree. Twenty labels a week at maximum information will
move 62.6% faster than any widening of a word list. `TAGGING.md`'s rule about
freezing the audit sheet survives untouched: an uncertainty sample is
development evidence by construction.

### F12 — Mine the foreign-language needles instead of writing them. (C/M)

921k postings sit on Swedish, Danish, Swiss and Singaporean boards. The
lexicon's Nordic vocabulary is hand-written, and `tagging.py` carries the
incident where *every* Swedish rule silently never fired because `ö` folded to
a space — a rule that never fires looks exactly like a rule with nothing to
catch.

**Do:** a term-mining pass. Take the postings the English-side rules decided
confidently, rank foreign-language tokens by pointwise mutual information with
those decisions, and emit **candidate needles with corpus evidence and counts
attached**, for human review before they enter the lexicon. Deterministic,
offline, free, and the automatic repeatable version of what Stage 57 did by
hand.

### F13 — Employer priors should shrink, not threshold. (C)

`_QUANT_BOARD_FLOOR = 2` and `_QUANT_BOARD_SHARE = 0.05` are hard cutoffs, so a
board with 2 of 2 quant postings and one with 40 of 800 are the same fact. A
Beta-binomial posterior mean is continuous, behaves correctly at both ends, and
removes two magic numbers. It also becomes a clean feature for F10.

### F14 — Measure precision@k, not dimension agreement. (C)

You read the board top-down. The objective is "how many of the top 50 cards are
worth opening" and "how many human-labelled relevant postings reach the top
50". Dimension agreement and containment are diagnostics, not the objective,
and a classifier can improve on both while the top of the board gets worse.
This changes what `labels.score` prints, and it is the number that should gate a
`TAGGER` bump.

### F15 — Four cheap reliability additions. (C)

**(a) Vendor-level outage detection.** `db.py` explains, correctly, that
auto-retiring a board after N failures is unsafe because Topdanmark's 422s were
indistinguishable from a dead board during a Workday outage. Group each run's
failures by vendor: if a material share of one vendor's boards fail together,
that is an outage. This is simultaneously the thing that suppresses the alert
storm and the thing that makes automated retirement safe for every board that
is *not* in an outage — so it unblocks a change the comment currently has to
refuse.

**(b) Per-board volume regression.** `extract._shortfall` can only fire where a
board states its own total. `board_polls.postings` already stores what each
board returned last time, so a board that held 879 and now returns 12 with
`ok=1` is a silent truncation that nothing reports — on every reader that
publishes no total.

**(c) A second pass at failures inside the same run.** A 404 will still be a
404, but WAF refusals, 5xx and mid-body resets are transient and currently wait
a week. Re-poll the failed set after the gather phase; by then it is 30+ minutes
later under different load. Today's log shows 51 failing boards.

**(d) Resumable portal walks.** Verify first — writes are batched per page, so
rows may already survive a refused sweep even though the sweep reports failure.
If they do not, a stored page cursor per sweep turns a 429 at page 400 of 956
into a resume rather than a restart.

### F16 — Withdrawal is an explicit fact for exactly one source. (M)

`removed_at` is written only by `jobstream.py`; for every other source,
withdrawal is inferred at build time from `last_seen`. That inference is sound,
but it means the strongest signal available is never recorded: *a completed
census sweep did not contain this posting*. `Sweep.problem is None` already
decides whether a sweep was sound — `jobroom_ch` uses exactly that condition to
move its cursor. Writing `removed_at` under the same condition, and only under
it, makes withdrawal auditable and satisfies invariant 6 by construction rather
than by convention.

### F17 — Two numbers about the board's composition worth a decision. (M)

- **Singapore is 1,174 of 4,187 hub tags (28%)** and MyCareersFuture is 932
  cards. 54 of them are shortlisted, so it is not noise — but it is a quarter of
  the reading load from one portal.
- **Top firms by card count** are DRW 106, SIG 101, MLP 100, Point72 62, Jump 56
  — and then `citibank.com.sg` 52, `bankofsingapore.com` 48, `instinet.com` 48,
  `clsa.com` 46. The marquee prop shops and a tail of Singapore bank postings
  occupy the board in similar volume.
- **182 cards have no location** and so pass the geography gate correctly, but
  can be ranked by nothing.
- Swiss postings are 220,899 rows of which **570 carry an employer domain**, so
  cross-source dedup against an employer's own board cannot work for
  Switzerland, and the firm display is weak there.

**Decided for the first two: `source` and `hub` become features in the fitted
combiner, so the discount is learned from the labels rather than chosen — see
§6.** The placeless cards and the Swiss employer-attribution gap are still
open; the latter is the strongest argument for F5's JSON-LD route, which would
attach an employer domain to Swiss postings the portal does not name.

---

## 3. Candidate new sources

Ordered by expected yield. Each names the probe that decides it, per AGENTS.md:
establish the gap and verify the real endpoint before building an adapter.

**The structural point first, because it multiplies everything below:**
`discover.py` already turns a *firm name* into a verified board token by
guessing and then running the real extractor. So every new name list feeds the
existing machinery with no new reader code. A name list is a board-token source.

1. **DOL OFLC H-1B / LCA disclosure data** (US, quarterly bulk, free, no
   account). **(P, high confidence it exists; format needs checking.)** Employer
   name, job title, worksite city and state, wage level. For New York, Chicago
   and Boston this is close to a census of *who pays for quantitative hires*; it
   names prop shops holding no SEC registration; and it is the independent
   second sample `coverage.py` lacks for the US hubs, which is the one thing
   that would let capture–recapture speak about the biggest market. *Probe:*
   one quarter, titles filtered through the lexicon, count employer names absent
   from `firms`.
2. **GLEIF LEI golden-copy files** (daily, free, no account), including Level 2
   parent/child relationship records. **(P, high confidence.)** `resolve.py`
   already keys on LEI. More importantly this supplies the
   evidence-backed relationship edges DISCOVERY-STRATEGY asks to store
   (`affiliate_of`, former names) without inferring them from shared words.
   *Probe:* join against `employers` on name + country; count new LEIs and new
   edges.
3. **Exchange participant lists for the focus hubs that have none.** SIX Swiss
   Exchange participants, SGX members, HKEX participants plus the market-maker /
   LP tables already probed in the September pilot and never implemented, and
   Nasdaq Stockholm members. Small, high-precision lists establishing *proven
   local market activity* — exactly the ranking signal F8 needs. The repo
   already has Eurex, Euronext, Cboe Europe and FIA EPTA, so the adapter shape
   exists. **(P, format varies per exchange.)**
4. **NFA BASIC / CFTC registrants** (US). CTAs, CPOs, FCMs, IBs — a population
   overlapping SEC ADV only partly, and where managed-futures and proprietary
   trading firms sit. *Probe:* whether BASIC exposes a bulk or paged public
   surface without an account.
5. **CME and ICE clearing / member firm lists.** Published, small, precise,
   Chicago-relevant.
6. **ACRA monthly corporate snapshot** (Singapore). Already specified with its
   partition caveats in DISCOVERY-STRATEGY, verified at metadata level, never
   built.
7. **Danish CVR open data** (Copenhagen). *Probe:* whether a free unauthenticated
   distribution exists; Virk / Datafordeler may require registration, which
   would rule it out.
8. **IND register of recognised sponsors** (Netherlands, free). Amsterdam is a
   focus hub with **no national aggregator at all** — the only focus hub in that
   position. This at least enumerates employers that hire internationally.
9. **EURES**, the EU job mobility portal. Would be the first aggregator covering
   Amsterdam. *Probe carefully:* the employer-side API is registered and is a
   different thing — the same trap `jobroom_ch.py` documents about SECO's
   registered API, where a 401 on the wrong path was recorded for weeks as "this
   source is blocked".
10. **Hacker News "Who is hiring" monthly thread**, via the free Algolia HN API,
    no account, one request a month. Jane Street, HRT, Radix and similar post
    there with role and city. Unusual, tiny, and precise for this exact niche.
11. **University partner and career portals in the hub cities** — KTH, SSE,
    TU Delft, ETH, NUS, HKUST. Small, stable pages aimed precisely at a graduate
    with under a year of experience, which is the one population no other source
    targets.
12. **arXiv q-fin author affiliations** (free API). Employer discovery for
    research-oriented firms that advertise nowhere. A lead, never a hiring
    signal.

Deliberately **not** proposed: anything needing an account, key or payment
(OpenCorporates, LinkedIn, eFinancialCareers, Reddit's current API); anything
behind a CAPTCHA or WAF; Common Crawl (months stale and indexed by URL prefix,
so it cannot answer "which firms reference a Greenhouse board").

---

## 4. What the refactor can collapse

Estimates, with the method stated. Code lines are tokenizer-counted
(comment and docstring lines excluded), so these are comparable to §1.3.

| Area | Now (total / code) | Target code | Lever |
|---|---|---|---|
| `extract.py` readers | 2,157 / 1,186 | ~700 | ~20 of the 34 readers are a URL plus a JSON field map (`greenhouse`, `lever`, `ashby`, `workable`, `recruitee`, `bamboohr`, `breezy`, …). A declarative spec table plus one generic reader; keep code only for the paginating and HTML ones. |
| Six national portals | 2,614 / ~1,100 | ~550 | One census walker — page-until-short, advertised-total guard, partition-under-result-window, two-ended walk, cursor, facet config, sample rate (F2) — plus six configs. `sweep.py` already proves the pattern for one check; this extends it to the walk. |
| `bodies.py` | 1,214 / 467 | ~250 | Five of nine fetchers are "GET the detail URL, read JSON-LD or microdata, take description + place". Generic reader plus a per-vendor URL builder. |
| `cli.py` | 1,581 / 1,068 | ~600 | Six near-identical portal subcommands and three hand-built pipeline lists become a command table and a phase table with a cadence column (F1). |
| `tagging.py` | 4,093 / 1,736 | ~700 | Needle lists out of `.py` into a data file; `tag_posting`'s branch cascade into a rule table; `_fit` into a fitted linear combiner (F10). |
| `lexicon.py` + `role_scope.py` | 1,647 / 724 | ~250 + data | These are vocabularies, not code. As data, `fingerprint()` hashes the file and `TAGGER` discipline is unchanged. |
| `sites.py` | 1,322 / 609 | ~400 | Retire the readers that a generic JSON-LD or sitemap reader now covers (F5), which the module's own docstring instructs. |
| `web/build_data.py` | 1,143 / 464 | ~400 | Gate definitions shared with `tagging.GATES` rather than restated. |
| Tests | 14,851 | ~6,500 + data | 277 tagging cases with 443 inline literals become a CSV of `(title, department, body, expected…)` plus one parametrised runner. Vendor readers get a `tests/fixtures/` directory of recorded payloads instead of inline JSON — `test_oracle_hcm` 1,124, `test_icims` 768, `test_bodies` 982, `test_iesjobs` 620, `test_jobindex` 636, `test_mycareersfuture` 543. |
| Prose | 9,023 comment + docstring | ~3,000 | Mechanical, not deletion: each essay becomes `# why: <one-line claim>  [history: engineering.md#anchor] [test: TestName]`, the paragraph moves to `docs/history` under that anchor, and the test name is what enforces it. AGENTS.md already mandates this direction. |

Plausible totals: `quantscraper` 22,090 → **9,000–11,000**; tests 14,851 →
**~6,500**. Every line of it has a methodology reason above, which is the point —
nothing in this table is shortening for its own sake.

**One caution.** The 9,023 prose lines are the incident corpus. They are the
reason this pipeline does not re-learn that Workday reports `total: 0` after
page one, that MyCareersFuture's `_links.last` is a lie, that `ö` folds to a
space. Moving them is safe; deleting them is not, and the mechanical rule above
is what keeps the distinction enforceable.

---

## 5. What I would not change

- **Employer-first collection.** §1.2 settles it quantitatively: 51 cards per
  thousand rows from Greenhouse against 0.04 from JobStream.
- **Guess, then verify — and verify by running the real extractor and requiring
  the postings to name the firm.** Two false hits in `discover.py`'s first sixty
  candidates (an HVAC company at `greenhouse/cfm`, somebody else's Radix) are
  the evidence that the weaker check is not enough.
- **The advertised-total guard and `sweep.problem`**, including the `served`
  refinement that distinguishes a truncated walk from a moving index. It has
  caught every truncation on record and it correctly passed today's Jobbsafari
  sweep, where 46,814 distinct of 51,235 advertised looked like an 8.6%
  shortfall and was 4,457 duplicates from re-indexing.
- **`SiteChanged` raising rather than returning `[]`.** An empty board is an
  answer; a missing anchor is a broken reader.
- **The three-verdict lexicon with `undecided` as a backfill queue.**
- **Append-only `employers` and `jobs`; tags derived and reversible; gating only
  at the board.** Everything in F2 and F3 is designed to stay inside this.
- **The per-host throttle and the refusal to probe rate limits.** F4's
  conditional requests reduce traffic; they must not touch the throttle, the
  distinct 429 schedule, or the retry classification.

---

## 6. Decisions taken

Answered by the user on 22 October 2026, after this review was drafted. These
are policy now; the refactor works to them.

**Acquisition**

- **Census: cut to the earned facets, with a 10% check sample.** F2 as proposed
  — every facet that has ever produced a posting worth showing is read in full
  weekly, including the catch-alls; the dropped facets are read as a fixed 10%
  random slice so the loss is reported every week rather than assumed. All six
  portals, Hong Kong included — which also answers the standing robots question
  in ACTION-REQUIRED by reading roughly a third as much of the one board that
  asked not to be read.
- **Visa-sponsorship datasets are in, for discovery and ranking only.** US
  H-1B/LCA disclosure files for New York, Chicago and Boston, and the Dutch IND
  recognised-sponsors register for Amsterdam. H-1B is also the independent
  second sample `coverage.py` lacks for the US hubs, and IND gives Amsterdam its
  first employer list of any kind. METHODOLOGY's "work authorization is not an
  ingestion filter" is unaffected: these are used to find and rank employers,
  never to gate a posting.
- **Unpollable tier-A rows (F6): check, fix, regrade.** Add the `alerts`
  invariant so the hole cannot be silent again; fix the SuccessFactors token to
  read the tenant from the path, recovering 17 boards; regrade the ten Taleo
  rows and let `discover` reach SocGen and OCBC by name. **No Taleo reader** —
  three boards does not justify a 35th hand-written vendor reader, per
  `sites.py`'s own rule.

**Classification and ranking**

- **Fitted combination: yes, with the gates staying rules.** The lexicon keeps
  extracting evidence; `tag_posting`'s ladder and `_fit` become a linear model
  fitted on the 2,387 human labels, weights shipped so a re-tag stays
  deterministic and inspectable. `off_industry`, `off_location`,
  `student_only`, `phd_required` and `out_of_reach` stay hand-written policy.
  F10, F11, F13 and F14 are all in scope.
- **Built on scikit-learn, pinned.** Already installed on this machine
  (scikit-learn 1.7.0, numpy 2.2.0, scipy 1.16.0), pure wheels on Windows, no
  build step, no account, no inference spend. Add all three to
  `requirements.txt` with the usual note on what they replace. Fitting runs once
  per lexicon change; a re-tag stays a dot product.
- **Source and hub become model features rather than hand-set weights.** That
  is the answer to MyCareersFuture's 28% share, and it generalises: job-room.ch
  puts 407 cards on the board for 3 shortlisted and needs a larger discount than
  MyCareersFuture's 932 for 54. One mechanism, learned from the labels, both
  answers.

**Storage and code**

- **Schema: the partial change now, the integer key later.** Move `tagger` and
  `tagged_at` into a per-posting `job_tagged` table and drop
  `job_tags_by_tagger` — about 1.5 GB, and the re-tag queue's "is this posting
  current" becomes a single-row lookup instead of a correlated `NOT EXISTS` over
  16 rows. Blast radius is `tagging.postings` / `record` / `prune` /
  `stale_taggers`, `alerts`' drift check, and `db` schema plus migration. The
  `(ats, token, job_id)` → integer key change is deferred: it is worth another
  ~2.2 GB but touches every join in `build_data`, `labels`, `audit` and
  `bodies`, which is too wide a diff next to a classifier change.
- **Prose: mechanical move with anchors.** Each essay becomes a one-line
  `# why: <claim>  [history: …#anchor] [test: TestName]`, the paragraph moves to
  `docs/history` under that anchor, and the named test enforces it. Nothing is
  deleted.
- **Lead with coverage and ranking.** F1 first regardless. Then the coverage
  work (F5, F7, §3) and the ranking work (F9–F14) together; reliability (F4,
  F6, F15) and the deferred schema work follow.

Expected database trajectory: **9.69 GB → roughly 3 GB** from the census cut,
**→ ~1.5 GB** with the partial schema change, and the facet→yield table plus the
10% sample become the standing coverage measurement for the portals.

## 7. Verify before building

Nothing here is a decision; these are the probes the decisions above depend on,
per AGENTS.md — establish the gap and verify the real endpoint first.

1. **H-1B/LCA disclosure files.** Confirm the current distribution format and
   that the records are employer-level case data (employer, job title, SOC code,
   worksite, wage, status) carrying **no beneficiary names**. If they carry
   personal data, the route changes shape or stops. Then: one quarter, titles
   through the lexicon, count employer names absent from `firms`.
2. **IND recognised sponsors** (Netherlands). Confirm a free unauthenticated
   download exists.
3. **GLEIF golden copy**, Level 1 and Level 2. Confirm no account, then join on
   name + country and count new LEIs and new relationship edges.
4. **Exchange participant lists** — SIX, SGX, HKEX participants and
   market-maker tables, Nasdaq Stockholm members. Each is a separate format
   question.
5. **crt.sh** rate behaviour before relying on Certificate Transparency for
   subdomain enumeration (F8).
6. **Conditional-GET hit rate** (F4). Measure the share of boards and tier-B
   pages that actually send `ETag` or `Last-Modified` before building the store.
7. **Resumability of a refused portal walk** (F15d). Writes are batched per
   page, so rows may already survive a sweep reported as failed; check before
   adding a cursor.
8. **EURES.** The employer-side API is registered and is a different thing —
   the same trap `jobroom_ch.py` documents about SECO's registered API, where a
   401 on the wrong path was recorded for weeks as "this source is blocked".
9. **NFA BASIC and Danish CVR.** Whether either exposes a free unauthenticated
   bulk or paged surface at all.
