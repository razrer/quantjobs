# Implementation plan

The acquisition methodology lives in
`C:\Users\razre\.claude\plans\snoopy-growing-hoare.md`. This file is the
*execution* order: what gets built, in what sequence, and — the part that was
missing — **how each stage knows it is finished.**

## Why this file exists

Stages 0 collection was done opportunistically: probe a source, write an
adapter, commit, repeat. That produced working code but no answer to "is this
stage done?", so the stopping point was a judgement call every time. Every
stage below has an explicit exit criterion instead.

**Rule: do not start a stage until the previous stage's exit criterion is met.**
If a stage turns out to be blocked, record it in `ACTION-REQUIRED.md` and stop —
do not skip ahead to something more interesting.

## Geographic priority

**Focus:** Stockholm, Copenhagen, Amsterdam, Switzerland, Hong Kong, Singapore.
**Deprioritized:** Germany, US, London/UK, China, Dubai.

Dubai was deprioritized after Stage 3. Its register is the one behind a CAPTCHA,
so it could not be built anyway; the roster firms that matter there are already
in the universe through the seed file. It stays in the audit fixture and reports
with the deprioritized hubs.

This sets **what gets built next**, not what gets ingested. Data already
collected stays — `sec_adv` and `sec_bd` are 26,500 US rows and they remain in
the universe, because geography ranks results rather than gating membership, and
deleting employers is the one mistake this design refuses to make. It simply is
not where the next unit of effort goes.

Deprioritizing the UK is convenient: the FCA was the only blocked source, so
nothing in the near-term plan now waits on a human.

## Status

| # | Stage | Status |
|---|---|---|
| 0 | Employer universe — raw collection | done |
| 1 | Employer identity (entity resolution) | done |
| 2 | Coverage audit harness | done |
| 3 | Close audit-flagged gaps | done |
| 4 | Layer 2 — domain resolution | **in progress** — mechanism built, queue long |
| 4b | Switzerland (FINMA) | done |
| 5 | Layer 2 — ATS resolution | **in progress** — fingerprinter built |
| 6 | Layer 3 — ATS extraction | **in progress** — 10 formats, jobs landing |
| 7 | Layer 4 — JobTech JobStream (Sweden) | not started |
| 8 | Silent-failure alerting | not started |
| 9 | Layer 3B — Tier B change detection | not started |
| 10 | Coverage measurement | not started |

---

## Stage 0 — Employer universe, raw collection *(done)*

Seven registries, ~30,500 employer rows. Each is a module behind one interface;
each declares a `MIN_EXPECTED` floor so a silent breakage fails loudly.

**Exit criterion (met):** more than one jurisdiction per region of interest, and
every fetch recorded in `runs`.

---

## Stage 1 — Employer identity *(done)*

**The problem.** One real company occupies up to four rows: Jane Street is in
`sec_bd`, `afm_nl`, `eurex` and `euronext`; Tower Research trades as `LATOUR
TRADING LLC`; HRT as `HRT FINANCIAL LP`. Everything downstream multiplies on
this — resolving a domain four times, polling one careers feed four times, and
emitting the same job four times.

**This is why it goes before more sources.** Each new registry makes the
duplication worse, not better, so adding sources first is compounding a debt.

**Build.** A `firms` table derived from `employers`, grouped by deterministic
keys in precedence order:

1. **LEI** — a global identifier; `eurex` already carries it
2. **Domain** — registrable host from the `website` field
3. **Registry key** — Swedish org number, SEC CRD
4. **Normalized name** — legal-form suffixes stripped, nothing else

Plus a small hand-curated alias table for the cases no key can bridge, which
the methodology explicitly calls for.

**Conservatism.** Normalization strips *only* legal forms (`AB`, `B.V.`, `LLC`,
`GmbH`…). It must not strip distinguishing words like `Trading`, `Capital` or
`Securities` — "Capital Fund Management" and "Fund Management" are not the same
firm. Prefer a false split over a false merge; a duplicate costs a second of
reading, a wrong merge silently deletes an employer.

`employers` is not modified. `firms` is rebuilt from scratch on demand, so the
resolution logic can be improved and re-run without re-scraping.

**Exit criteria — all met:**
- [x] every `employers` row maps to exactly one firm — 30,527/30,527
- [x] `firms` is materially smaller than `employers` — 28,713 from 30,527
- [x] Jane Street collapses to one firm — 10 rows across 5 sources
- [x] Tower Research resolves to Latour, HRT to HRT Financial
- [x] rebuilding twice yields identical output
- [x] `stats` reports the collapse ratio

**What this stage found.** Two false merges, both caught by inspecting the
largest groups rather than trusting the totals:

1. Over 4,000 Form ADV filers give a **LinkedIn page** as their "Website
   Address". Treating that domain as an identifier merged 6,688 unrelated firms
   into one. Fixed with a platform blocklist plus a frequency backstop, so an
   unlisted platform cannot do the same thing again.
2. A curated alias prefix of `"maven "` absorbed **Maven Capital Partners**, an
   unrelated UK private-equity firm, into Maven Securities. Short prefixes are
   themselves a false-merge risk; the table now uses specific ones.

**Honest limitation.** Only 1,814 rows collapsed, because most rows carry no
website and legal names genuinely differ. Stage 4 is what improves this: once
every firm has a domain, `domain:` will unify entities that name matching
cannot. `firms` is rebuilt from scratch on demand precisely so that re-running
after Stage 4 costs nothing.

---

## Stage 2 — Coverage audit harness *(done)*

**The problem.** Coverage had been checked with ad-hoc `grep`s typed fresh each
time. That is not repeatable, and it was the direct cause of at least one
overstated claim about which firms were missing.

**Built.** `quantscraper/roster.csv` — 163 entries across 11 hubs, expanded from
the methodology's named roster — plus `python -m quantscraper audit`, matching
through Stage 1's resolution.

The roster is the *audit set*, never the universe. Deprioritized hubs stay in
the fixture but report separately, so London and the US measure coverage without
competing for attention with the hubs that matter.

**Exit criteria — all met:**
- [x] `audit` runs and reports per-hub hit rate
- [x] every miss in a focus hub is recorded with a reason, printed by `audit`
- [x] stale entries (IPM) and never-real entries (AP5) are marked and excluded

**Focus-hub result:** Stockholm 19/20, Amsterdam 12/13, Switzerland 9/11,
Copenhagen 5/7, Singapore 7/10, Hong Kong 9/9, Dubai 3/7.

**What this stage found.** Reporting one number per hub would have been
misleading, so the audit reports two: *present* (in the universe under some
name) and *local* (some row places the firm in that hub's country).

1. **Hong Kong reads 9/9 present but 1 local.** Every HK roster firm except HSBC
   is visible only through a US registration. A single hit-rate would have
   declared Hong Kong solved while no HK register had been ingested at all.
   Dubai is the same story at 3/7 present, 0 local.
2. **A false hit hides a miss**, which makes it worse than a false miss here. A
   bare `Grasshopper` roster entry matched `GRASSHOPPER ESCAPEMENT, LLC` and
   reported Singapore one firm better covered than it was. Caught by printing
   the employer names each entry matched, which `-v` now always does; roster
   names are kept specific for the same reason.
3. **Two focus-hub misses are fixable bugs, not missing registries** — see
   Stage 3 items 1 and 2 below. Both were invisible before this stage.
4. **Three Shanghai firms were found via Hong Kong** — Mingshi, Lingjun and
   Tianyan hold HK entities in `sec_adv`. A hub can be partly covered from a
   neighbour, which is only visible with a repeatable check.

---

## Stage 3 — Close audit-flagged gaps *(done)*

**Exit criteria — met:** `audit` reports **no focus-hub miss at all**, and every
miss a buildable source would fix is fixed. The one source that would fix a
remaining *local* gap is blocked on a human (DFSA, see `ACTION-REQUIRED.md`).

| Hub | Before | After | Local |
|---|---|---|---|
| Stockholm | 19/20 | **20/20** | 20 |
| Copenhagen | 5/7 | **7/7** | 7 |
| Amsterdam | 12/13 | **13/13** | 13 |
| Switzerland | 9/11 | **11/11** | 6 |
| Dubai | 3/7 | **7/7** | 3 |
| Hong Kong | 9/9 | **9/9** | 8 *(was 1)* |
| Singapore | 7/10 | **10/10** | 7 |

The universe went from 30,590 rows to 63,724, and three new registries were
added: `finanstilsynet_dk`, `mas_sg`, `sfc_hk`.

**What was done, in the order it was done:**

1. **`fi_se` category walk was incomplete.** It walked 20 of FI's 495 codes, and
   the omissions were not all funds: Alecta, Sweden's largest occupational
   pension manager, is a *mutual* undertaking filed under `TJPÖMS`, not a
   `Tjänstepensionsaktiebolag`. Added that plus the association and foreign
   forms. Corporate pension foundations (807 of them) stay excluded, now with a
   written reason.
2. **`afm_nl` read only two of AFM's registers.** The AIFM manager registers are
   published as **spreadsheets** on the same page as the CSV export links, and
   only as spreadsheets. That cost PGGM Vermogensbeheer and APG Asset
   Management. Needed a minimal stdlib `.xlsx` reader (`parsing.xlsx_rows`).
3. **`finanstilsynet_dk`** — Copenhagen. 26,495 entities.
4. **Seed file** — the five sovereign wealth funds. Five lines, five misses.
5. **`mas_sg`** — Singapore. 1,992 institutions across 21 categories.
6. **`sfc_hk`** — Hong Kong. 3,623 licensed corporations. Took HK from 1 local
   to 8, and incidentally found Ubiquant and High-Flyer, two Shanghai misses,
   through their Hong Kong entities.

**What this stage found that the plan did not predict:**

- **The DNB register was the wrong answer.** Stage 2 recorded "Dutch pension
  managers are DNB-supervised" as the reason PGGM was missing. Reconnaissance
  disproved it — DNB's register does not contain PGGM at all. The real cause was
  `afm_nl` reading two of AFM's registers. A recorded reason is a hypothesis
  until someone checks it, and the fixture now says so.
- **Julius Baer was never missing.** `Bank Julius Bär & Co. AG` had been in
  `eurex` since the day it was added. The audit reported it absent because
  matching was anchored to the *start* of the name, and the registry name begins
  with "Bank". Same bug would have hidden `Fondsmæglerselskabet Maj Invest A/S`.
  Matching is now token-aligned anywhere in the name, which is what makes the
  Switzerland and Copenhagen numbers above trustworthy.
- **Denmark has no enumerable endpoint**, so `finanstilsynet_dk` sweeps a
  substring search over single letters and unions the result. It saturates part
  way through the alphabet, which is the evidence it is complete.
- **The DFSA register is behind a CAPTCHA.** Dubai is the one focus hub with no
  local register and it needs a human. See `ACTION-REQUIRED.md`.

**Deferred, each with a written reason rather than an oversight:** DNB (real
source, fixes no audit miss — 147 pension funds and 786 banks if it is ever
wanted), FINMA (Switzerland is 11/11 present but 6 local), Nasdaq Stockholm
participants, BaFin, FCA, AMAC, and the US state-adviser tail.

---

## Stage 4 — Layer 2, domain resolution

Registry `website` fields first, then guess-and-verify for the rest.

**The exit criterion as written is not measurable, and the shortfall is real.**
It says "≥90% of firms in priority cities have a domain, or are explicitly
marked unresolvable" — but *every* firm ends up explicitly marked, so the clause
makes the bar trivially passable while saying nothing. Worse, "priority cities"
is not a field we have: `fi_se`, `sfc_hk`, `mas_sg` and `finanstilsynet_dk`
publish no city at all.

Replaced with two numbers that mean something:

- **known** — the firm has a domain from a registry or a *strong* verified match
- **probed** — the firm has been looked at, so the remainder is a queue length
  rather than an unknown

**Exit criterion:** every firm reported by a focus-region registry has been
probed at least once, and the strong matches survive a manual read.

### The problem this stage exists to solve

Registries in the focus regions publish **no websites at all** — not one of
`fi_se`, `afm_nl`, `finanstilsynet_dk`, `mas_sg` or `sfc_hk` carries a single
one. Across the 34,047 firms they report, 2.3% had a domain, and 95% of even
those arrived via a US registration rather than a local one.

### Guess, then verify

`domains.py` derives candidate domains from the firm's name and accepts one only
if the page that answers actually names the firm. **An unverified guess is worse
than no domain**: it points Layer 3 at someone else's careers page, and the
result is a silently empty feed rather than a visible error.

Matches are graded, and the grading is the whole safety mechanism:

- **strong** — the page contains the firm's full name, or its first two
  identity-bearing words. Counted as resolved.
- **weak** — the page contains only one word of a multi-word name. Stored with
  its evidence, **not counted**, and not to be used by Layer 3 until confirmed.

Three false positives drove that design and are worth keeping in mind:
`australia.com` (the tourism board) for *Australia and New Zealand Banking
Group*, `societe.com` for *Societe Generale*, and `citadel.com` for *Citadel
Securities* — a different employer with a different careers page, and precisely
the merge the roster is careful to keep apart. A fourth, `marketfrance.com`,
"proved" itself by printing its own domain name on the page, which is circular:
the domain was the thing we guessed.

### Where it stands

360 firms probed, 119 strong matches (33%), 128 weak held back, the rest
unresolved. A random sample of 30 strong matches read clean. Following redirects
matters: `PineBridge Global Funds` resolves to `metlife.com`, which looks wrong
until you remember MetLife acquired PineBridge.

| Registry | Known | Share |
|---|---|---|
| `mas_sg` | 200/1,988 | 10.1% |
| `afm_nl` | 255/3,709 | 6.9% |
| `sfc_hk` | 228/3,622 | 6.3% |
| `fi_se` | 34/659 | 5.2% |
| `finanstilsynet_dk` | 447/25,549 | 1.7% |

### Overseas sources surveyed

Checked for sources that carry firms beyond their own borders, on the theory
that made the SEC and FCA worth having. Result: one clear win, one blocked, two
not worth it.

| Source | Verdict |
|---|---|
| **ESMA** (EEA) | **Added** as `esma_eea`. 13,930 firms, real enumeration |
| **FINMA** (CH) | Found bulk `.xlsx`, blocked on TLS — `ACTION-REQUIRED.md` item A |
| **GLEIF** (global) | Skipped: ~2.5M LEIs, no websites, and ESMA already supplies the LEIs that matter here |
| **Companies House** (UK) | Skipped: enumerates every UK company but publishes no websites, and London is deprioritized |

**ESMA is the find.** Every national regulator notifies it, so one adapter
covers Amsterdam, Stockholm and Copenhagen at once plus twenty member states we
have no adapter for. It is Solr-backed with an open query endpoint, so it
enumerates rather than searches — the shape this project prefers, and the reason
it was worth chasing where the FCA was not.

Its real value was not the head count. **Three quarters of ESMA records carry an
LEI, and no national register we hold publishes one.** LEI is the strongest key
entity resolution has, so it welds together firms already held under names that
match nothing: cross-registry firms went from 2,595 to **4,234**, and 8,877
firms are now LEI-keyed. A domain found for any one of them now covers all of
them. Websites, by contrast, appear on only 383 of the 13,930 — this is an
identity source, not a domain source.

### The FCA register as a domain donor

`fca.py`, added after the credentials arrived. **Not a registry** — the register
cannot enumerate (no bulk file; sub-three-character queries rejected; broad ones
return `Request Entity Too Large`; the only other handle is a millon-wide FRN
space). Treating it as one would overstate UK coverage.

What it does is publish a `Website Address` and a `Country` per firm, so it
enriches firms the universe already has. First 200 lookups produced 29 domains,
**13 of them non-UK entities** — Cyprus, Ireland, Belgium, Spain, Luxembourg,
Germany, Slovakia — which is the overseas reach that made it worth doing.

Because it is authoritative rather than inferred, it also corrects the guesser:
Commonwealth Bank of Australia resolves to `commbank.com.au`, where guessing had
offered `commonwealth.com`. Yield is lower than guessing (15% vs 33%) but the
results need no manual read.

### Still to do in this stage

- **The queue is the work**: ~34,000 focus-region firms, of which the Danish
  register contributes 25,549 that are mostly fund vehicles. At the observed
  rate this is hours of wall time, not minutes. `--limit` makes it incremental,
  writes are batched every 100 so an interrupted run keeps its progress, and the
  cache makes re-runs free.
- Weak matches need a confirmation pass. Stage 5 gives one for free: a domain
  with no careers page and no ATS fingerprint is evidence the guess was wrong.
- Certificate Transparency (`crt.sh`) for careers subdomains, once firms have a
  domain to start from. It enumerates `careers.*` hosts that are never linked
  from the homepage. This is Stage 5's input, not a name resolver.
- Ordering is by how many registries saw the firm, which is a good proxy for
  "operating company rather than fund vehicle" but surfaces large international
  banks first. Resolving the audit roster ahead of the tail would be a cheap
  improvement.

---

## Stage 5 — Layer 2, ATS resolution *(in progress)*

`ats.py`. A domain is not a job feed: almost every firm outsources hiring, and
each ATS has one public endpoint shape, so `(ats, token)` is what Layer 3 needs.
`greenhouse` + `flowtraders` is a feed; `flowtraders.com` is a homepage.

**Fingerprinted, not guessed.** The careers page links to, or loads script from,
whichever ATS it uses. That outbound host is the evidence and the board token
falls out of the same URL. 23 systems are recognised, including the Nordic group
(Teamtailor, Varbi, Jobylon, Emply, Personio) — without those, Stockholm and
Copenhagen are not exhaustive, because no generic scraper covers them.

**Every domain gets a tier, because "no ATS" is a real answer:**

- **A** — ATS and token fingerprinted; Layer 3 polls the feed
- **B** — a careers page exists but runs on nothing recognised; Layer 3B diffs
  it instead, which works on any page structure
- **C** — no careers page found at all

*Untiered* is the state that must not exist: a domain nobody looked at is
indistinguishable from a firm that is not hiring.

**Two token-extraction bugs, caught by reading the first five results.** Both
produced a confident wrong answer rather than an error:

- `boards-api.greenhouse.io/v1/boards/{token}` carries an API version before the
  board, so matching the host alone extracted **"v1" as the board token** — for
  every Greenhouse user on earth.
- `www.teamtailor.com` matched the `{board}.teamtailor.com` shape and gave Lynx
  the board **"www"**.

Both are now filtered against a list of infrastructure hostnames, and a
recognised ATS with an unusable token is recorded with the ATS and a NULL token
rather than discarded — knowing the feed *shape* is still worth having.

### The stall that produced no error at all

Two `ats` runs sat at **100% CPU for two and a half hours and wrote nothing**.
No exception, no partial output, no slow endpoint to blame — from the outside
it was indistinguishable from a queue of unresponsive hosts, which is what it
was taken for. Both were stuck inside a regular expression.

Two independent quadratic patterns, and the second is the one worth
remembering because every host pattern here had it:

- `[^"']*(?:career|jobs|…)[^"']*` over an href that never closes. Real markup
  ends attributes early all the time — an apostrophe inside inline script does
  it — and the two unbounded runs then compete for the same characters once per
  word occurrence. Hrefs are extracted with a bounded pattern now and matched
  against the word list in Python.
- `([a-z0-9-]+)\.teamtailor\.com` over an **inline base64 data URI**, which is
  a long run of label characters containing no dot. The capture swallows the
  run, backtracks through it, fails, and the engine starts again one character
  along. A 40 KB image was minutes of CPU in a single pattern; pages carry
  several. Host labels are bounded to 63 characters — a DNS label cannot be
  longer — and prefixed with `(?<![a-z0-9-])`, so inside a blob every position
  fails on the first check rather than the sixty-third.

`tests/test_ats.py` times both, and fetched markup is capped at 2 MB: 23
patterns over an unbounded body holds up every other worker through the GIL.

This is the same failure class as principle 2 — an implausible result that
announces nothing — in the one place the plan had not looked for it. A run that
produces *nothing* is as silent as a run that produces zero rows.

**Exit criterion:** every firm with a domain is either resolved to an ATS or
assigned tier B/C. No firm left untiered.

**Where it stands:** 1,130 domains tiered — 118 tier A, 390 B, 622 C — against
a queue of roughly 13,900 domains that `domains.py` has produced so far. Both
queues are incremental and cached, so this is wall time, not a design problem.

---

## Stage 6 — Layer 3, ATS extraction *(in progress)*

`extract.py`. Stage 5 resolved firms to `(ats, token)`; each ATS publishes one
endpoint shape, so this is one small function per format rather than one scraper
per firm. That is the payoff the employer-first architecture was bought for.

Ten formats implemented and verified against live boards: **greenhouse, lever,
ashby, smartrecruiters, workable, recruitee, bamboohr, breezy, personio,
workday**. First run: **473 postings from 30 boards across 8 formats.**

Postings land in `jobs`, unclassified. Whether a posting is a quant role is a
read-time question — titles are not comparable across firms ("Strat" at Goldman,
"Trader" at Jane Street, "kvantitativ analytiker" in Stockholm) and a classifier
that runs at write time cannot be re-run over history.

### The Workday trap, and the correction

The plan recorded that `limit` above 20 returns an empty `jobPostings` array
with HTTP 200. Against the tenants here it returns **HTTP 400** — loud, not
silent. The note was half right, and the half that matters was somewhere else.

**The real trap is `total`.** Workday reports the true count on the first page
and **`total: 0` on every page after it**. Stopping when `len(jobs) >= total`
therefore truncates every board at 20 postings, returns no error, and looks like
a complete result. `abrdn` has 24 openings; that reader would have found 20 and
never known. Every large bank publishes through Workday.

The extractor caps the page size at 20, pages by `offset`, and stops only on a
short page. `tests/test_workday.py` covers all three. Both protections were
mutation-tested: raising the cap fails 5 of 6 tests, and reintroducing the
`total` stop fails the test written for it.

### And then the guard against that trap became the trap

With the re-fingerprinted tenants in, Workday returned 3,193 postings from 18
boards — and **LSEG and State Street both returned exactly 800**. A round
number is what a cap looks like from the outside. It was ours: a 40-page bound
added as "a guard against a broken stop condition". State Street has **1,295**
openings, so the guard against silent truncation was silently truncating, on
the two largest boards in the set and therefore on the firms with the most to
find. Nothing in the output said so.

The bound is 1,000 pages now, which is a last-ditch stop for a tenant that
never returns a short page rather than a limit on how big a board may be. A
second stop condition covers the case the bound existed for: a tenant that
ignores `offset` serves page one forever, so a page identical to the previous
one ends the walk. Both are tested, and the old bound fails the new test.

Re-polling lifted the same 18 boards from 3,193 postings to 3,718.

### Two token bugs this stage exposed in Stage 5

Both produced boards that look resolved and yield nothing forever:

- **Workday needs `tenant|wdN|site`**, not just the tenant. A tenant alone
  builds a URL that 404s on every poll. Fingerprinting now requires all three
  and refuses the match otherwise.
- **`jobs.lever.co/500`** on an error page produced the board token `"500"`.
  Purely numeric tokens are now rejected.

### A careers page can link to somebody else's board

The one Lever board resolved so far is `palmersquare.com` → `heyrowan`, and it
is wrong. Palmer Square Capital Management's careers page carries a single
`jobs.lever.co/heyrowan` link with a Google `srsltid` tracking parameter on it
— syndicated content, not their own board — and the 90 postings it yields are
*Piercing Studio Nurse* and *Store Manager* at a jewellery retailer.

The rows are kept, because raw tables are append-only and read-time
classification discards these on sight. But it is a new failure shape for
Stage 5, distinct from the token bugs above: the token is well-formed, the ATS
is real, the feed is live, and the firm is somebody else. Nothing in the
markup distinguishes it from a genuine off-site careers link, which is why no
heuristic is being invented from one example. The durable answer is
confirmation at Layer 3 — Greenhouse and Lever both publish the board's own
company name, so the feed can be asked who it belongs to — and that is worth
doing when a second example turns up rather than before.

**Exit criterion:** jobs land from at least one firm per implemented ATS format
*(10 of 10 by format, but the Lever board is the mis-attribution above, so nine
formats are proven against a firm that actually owns the board)*, and the
Workday trap has a test that fails if the protection is removed *(met)*.

---

## Stage 7 — Layer 4, JobTech JobStream

Sweden's incremental change feed. Makes Stockholm effectively complete for a few
hours of work.

**Exit criterion:** delta polling works; a full re-search is never needed.

---

## Stage 8 — Silent-failure alerting

Per-source volume anomaly detection on the `runs` history, and assert-non-empty
everywhere. `MIN_EXPECTED` is the crude version of this and already exists;
this stage makes it distributional rather than a fixed floor.

**Exit criterion:** deliberately breaking a parser produces an alert rather than
a quiet zero.

---

## Stages 9–10 and beyond

Layer 3B change detection for firms with no ATS, then capture–recapture coverage
measurement per city. From Stage 10 on, **let the measurement choose the next
piece of work** rather than this list.

Deliberately deferred: LinkedIn, Common Crawl mining, Wayback backfill. The
methodology explains why each looks more attractive than it is.
