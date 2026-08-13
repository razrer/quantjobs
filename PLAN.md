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
| 5 | Layer 2 — ATS resolution | **in progress** — 4,386 tiered, 12,100 queued |
| 6 | Layer 3 — ATS extraction | **done** — all 10 formats landing, 16,124 jobs |
| 7 | Layer 4 — JobTech JobStream (Sweden) | **done** — delta polling live |
| 8 | Silent-failure alerting | **done** — `alerts`, distributional |
| 9 | Layer 3B — Tier B change detection | not started |
| 10 | Coverage measurement | not started |
| 11 | Layer 5 — job tagging | designed, not started — `TAGGING.md` |

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

**Where it stands:** 4,386 domains tiered — 280 tier A, 1,034 B, 3,072 C — with
roughly 12,100 still queued, and the queue grows as `domains.py` runs. Both are
incremental and cached, so this is wall time, not a design problem.

**A tenant can host more than one board, and only the first is kept.**
`arrowstreetcapital.com` fingerprints to `arrowstreetcapital|wd5|Campus_Careers`
— the campus site. If the firm also runs an experienced-hire site under the
same tenant, nothing here will ever see it, because `ats_resolution` is keyed
on the domain and `fingerprint` returns on its first match. That is a coverage
gap of exactly the kind this project treats as expensive, and it is a schema
change (one row per board, not per domain) rather than a patch, so it is
recorded here for a later stage instead of being bolted on now.

---

## Stage 6 — Layer 3, ATS extraction *(done)*

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

The first Lever board resolved was `palmersquare.com` → `heyrowan`, and it is
wrong. Palmer Square Capital Management's careers page carries a single
`jobs.lever.co/heyrowan` link with a Google `srsltid` tracking parameter on it
— syndicated content, not their own board — and the 90 postings it yields are
*Piercing Studio Nurse* and *Store Manager* at a jewellery retailer. The same
shape put `alvier.com` on a Workday tenant belonging to Höganäs, though that
one turned out to be genuine: the tenant is shared and the site really is
`Alvier_Careers`. The evidence string is what distinguishes them, and only a
human read does it.

The rows are kept, because raw tables are append-only and read-time
classification discards these on sight. But it is a new failure shape for
Stage 5, distinct from the token bugs above: the token is well-formed, the ATS
is real, the feed is live, and the firm is somebody else. Nothing in the
markup distinguishes it from a genuine off-site careers link, which is why no
heuristic is being invented from one example. The durable answer is
confirmation at Layer 3 — Greenhouse and Lever both publish the board's own
company name, so the feed can be asked who it belongs to — and that is worth
doing when a second example turns up rather than before.

**Exit criterion — met.** Jobs land from at least one firm per implemented ATS
format, and the Workday trap has a test that fails if the protection is
removed. Lever was the last format outstanding and is now proven on a board the
firm actually owns: `cimgroup.com` → `cimgroup`, 51 investment-firm postings,
independent of the Palmer Square mis-attribution above.

**Where it stands:** 16,124 postings from 116 boards across all ten formats,
from 473 across eight at the start of this stage. Workday is 14,732 of them,
which is what the `total` trap and the page bound were both hiding.

Failures are printed rather than swallowed, and the five in the last run were
all real: two BambooHR boards serving HTML instead of JSON, a Greenhouse 404, a
Recruitee 403, and one stale tenant-only Workday token. Four such tokens
survived the earlier re-fingerprint; clearing them from `ats_resolution` — a
derived table, so it rebuilds — brought all four back as `tenant|wdN|site`,
including Arrowstreet Capital.

---

## Stage 7 — Layer 4, JobTech JobStream *(done)*

`jobstream.py`. Every job advertised in Sweden is published to Platsbanken, and
JobTech exposes it as a delta feed — new ads, edited ads, and withdrawn ones —
with no key and no quota.

**This is the one source that makes a hub complete rather than well covered.**
Firm-level ATS polling only reaches firms we resolved to a feed; JobStream
reaches every Swedish employer, including the ones we tiered C and the ones we
never resolved a domain for.

**Exit criterion — met:** delta polling works and a full re-read is never
needed. Cold start pulled 5,053 changes over a 24-hour window; the very next
poll, resuming from the stored cursor, pulled **133**. The cursor lives in
`feed_state`, so it survives restarts.

**Resume with overlap.** The cursor rewinds ten minutes before each poll.
Re-reading an ad costs an idempotent upsert; missing one because it landed in
the same second as the cursor costs a posting — the same trade this project
makes everywhere.

**What would have gone wrong silently.** A withdrawn ad arrives with `id` set
and *every other field null* — headline, employer, description. Feeding one
through the normal upsert leaves the row in place but wipes it: the job is still
counted and no longer readable, and nothing announces it. Withdrawals therefore
take a separate path that touches only `removed_at`. Rows are never deleted, so
a withdrawal is recorded rather than vanishing.

2,826 of the 5,053 cold-start changes were withdrawals, so this is the common
case, not an edge one.

`tests/test_jobstream.py` covers the withdrawal path, the cursor arithmetic and
the field mapping. Both protections are mutation-tested: routing withdrawals
through the upsert fails 2 tests, removing the overlap fails 1.

**Known cost, not yet a problem.** JobStream carries all of Sweden — roughly
9,000 ads a day, most of them nurses and drivers rather than quants. They are
ingested unclassified, per the read-time rule, which is right but grows the
database by tens of megabytes a day. Stage 11's tagging is what makes them
useful; if storage becomes the binding constraint before then, pruning old
descriptions is the lever, since `jobs` is a pollable table rather than a raw
registry.

---

## Stage 8 — Silent-failure alerting *(done)*

`alerts.py` plus `python -m quantscraper alerts`, which exits non-zero so a
scheduled run fails visibly rather than scrolling past.

**Exit criterion — met.** Breaking the Cboe parser live produced
`fail cboe_europe: Cboe Europe trading firms list not found` and exit 1;
restoring it returned `all sources healthy` and exit 0.

**Why a fixed floor was not enough.** `MIN_EXPECTED` only catches catastrophe.
Finanstilsynet normally returns 26,495 rows and declares a floor of 15,000 — a
parser that breaks and returns 16,000 clears the floor while having lost 40% of
the register, and nothing announces it. The check is now distributional:
compare a run against what that source has historically returned.

**Median, not mean.** Volumes are small samples and one bad run poisons a mean:
a source returning 0 today drags its own baseline down and looks healthy
tomorrow. The median is unmoved by a single outlier, so a breakage cannot
quietly become the new normal. There is a test for exactly that.

Four conditions, each a real way a source has failed or could: `fail` (the
fetch raised), `empty` (zero rows, no error), `shrank` (materially below the
historical median), `stale` (no successful run in 30 days). Plus `unrun` — a
registry that was added and never wired into a schedule, which from inside
`runs` is indistinguishable from a healthy one because it has no rows to be
wrong.

A source with fewer than two prior runs is not judged. One run is not a
baseline, and inventing one produces noise on exactly the sources that are
newest and least verified.

**A bug this stage found in itself:** `runs.started_at` has one-second
resolution, so two runs inside the same second ordered arbitrarily and the
check could pick the wrong one as "latest" — reporting the broken run as
history and the healthy one as current. Ordering now breaks ties on `id`.

---

## Stage 11 — Layer 5, job tagging

Designed in **`TAGGING.md`**: twenty dimensions across the posting, the firm and
the fit, stored in a derived `job_tags` table that rebuilds from `jobs`, with
evidence and a strong/weak grade on every tag.

Two things that design turned up and that the rest of the plan should know:

- **92% of postings have no description.** The list endpoints Workday, Breezy,
  BambooHR, Personio and SmartRecruiters publish carry title, location and date
  only. `CLAUDE.md` forbids classifying on a title alone, so a per-posting
  backfill is the real prerequisite. Workday's detail endpoint is verified —
  `/wday/cxs/{tenant}/{site}{externalPath}` returned 6,207 characters of
  `jobDescription` for an LSEG posting, plus `timeType` and `country`.
- **Substring matching on titles fails the same way the roster did.** A sweep
  for quant words over the 7,735 titles returns 884 hits, and the most frequent
  are `Corporate Administrator` (admini**strat**or) and `Alpha Account Services
  Data Analyst` (State Street's platform is named Alpha). Token boundaries, not
  `in`.

**Exit criterion:** in `TAGGING.md` — a hand-labelled sample of 100 postings,
every posting carrying a value in every dimension, and no false rejection in
the sample.

---

## Stages 9–10 and beyond

Layer 3B change detection for firms with no ATS, then capture–recapture coverage
measurement per city. From Stage 10 on, **let the measurement choose the next
piece of work** rather than this list.

Deliberately deferred: LinkedIn, Common Crawl mining, Wayback backfill. The
methodology explains why each looks more attractive than it is.
