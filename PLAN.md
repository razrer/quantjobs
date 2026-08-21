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

**Stage 27 is the last one written down.** Every stage above it is closed, so
the next unit of work is a decision rather than a queue: what to widen, what to
measure, or what to leave alone. The standing daily run is `sweden`, `denmark`,
`switzerland`, `jobstream`, `jobs`, `pages`, `bodies`, `tag`, `alerts` and
`web/build_data.py` — and `alerts` is the thing that says when one of them has
started lying.

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
| 4 | Layer 2 — domain resolution | **done** — queue empty, every strong grade re-checked |
| 4b | Switzerland (FINMA) | done |
| 5 | Layer 2 — ATS resolution | **done** — 19,821 tiered, none left untiered |
| 6 | Layer 3 — ATS extraction | **done** — all 10 formats landing, 16,124 jobs |
| 7 | Layer 4 — JobTech JobStream (Sweden) | **done** — delta polling live |
| 8 | Silent-failure alerting | **done** — `alerts`, distributional |
| 9 | Layer 3B — Tier B change detection | **done** — 3,751 pages watched |
| 10 | Coverage measurement | **done** — measures, and refuses when it cannot |
| 11 | Layer 5 — job tagging | **done** — lexicon 36, relevance 96.2%, no false rejection, leadership containment 14/14 |
| 12 | Layer 6 — the board | **done** — card grid, facet rail, deadlines |
| 13 | Layer 2C — board discovery | **done** — 23 boards, 989 postings, roster 16→49 |
| 13b | Platsbanken is not a census | **done** — 0 of 55 Stockholm employers are in it |
| 14 | Readers for recognised-but-unread ATSes | **done** — iCIMS + Pinpoint, 2,068 postings |
| 15 | The board, and the body it was reading | **done** — board unknowns 5,611 → 2,341 |
| 16 | The last ATSes, and Singapore | **done** — Jobvite/Varbi/Homerun read, MCF swept |
| 17 | The ATSes the focus hubs actually run | **done** — Oracle read, 26 boards |
| 18 | Stockholm and Hong Kong, firm by firm | **done** — Stockholm 15/18 reached |
| 19 | Hong Kong widened, ATS table exhaustive | **done** — 51 HK firms, 26 ATSes, 20 read |
| 20 | Switzerland's national feed | **done** — job-room.ch polling; the database holds 22,903 |
| 21 | Denmark's job board | **done** — Jobindex enumerated, 17,541 of 17,542 |
| 22 | Widen Sweden | **done** — Jobbsafari swept, 4,582 → 52,755 postings |
| 23 | The lexicon in Swedish, Danish and Swiss | **done** — 208 needles, 11 heads, none touching a positive |
| 24 | Pure trading hides instead of showing | **done** — an `exclude` preset, like credit risk |
| 25 | Multi-location postings show in both places | **done** — `hub` is multi-valued end to end |
| 26 | XVA and counterparty credit risk | **done** — 27 titles, no false positive |
| 27 | Read what the `rejected` gate removes | **done** — 720 reviewed, 1 false rejection; hand sheet 84.4% → 95.6% |
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

**Both halves now met.** `domains` now reports *nothing left to
probe in the focus sources* — 55,000 firms looked at, 2,528 strong matches in
the final pass alone. The second half is where it fails, and the failure is
worth more than the number.

| registry | known | share |
|---|---|---|
| `mas_sg` | 919/1,988 | 46.2% |
| `fi_se` | 292/659 | 44.3% |
| `sfc_hk` | 995/3,622 | 27.5% |
| `afm_nl` | 972/3,709 | 26.2% |
| `finanstilsynet_dk` | 4,388/25,549 | 17.2% |

### The strong grade does not survive a read, and the reason is structural

A random 25 read clean on the ones that mattered and wrong on roughly a fifth:

- **Brown Brothers Harriman (Hong Kong)** → `ppgrefinishdistribution.co.uk`.
  Brown Brothers is a UK paint distributor PPG acquired; the guess redirected
  onto a real company with a real claim to the phrase.
- **The Bank of Nova Scotia** → `novascotia.com`, the province's tourism board.
  Exactly `australia.com` again, one rule later.
- **Four Seasons Asia Investment** → `fourseasons.com.sg`, the hotel.
- **Goldman Sachs Emerging Markets Debt Blend Portfolio** → `goldman.com`,
  which is not Goldman Sachs.

The existing rule is "the page contains the firm's first two identity-bearing
words". `_GENERIC` already drops the words half the industry shares — *capital*,
*securities*, *management* — so the pair that survives is treated as
distinctive. It is not: **"brown brothers", "nova scotia" and "four seasons"
are ordinary English, and a page containing them proves nothing.** The rule
tests whether the words are industry-generic, never whether they are
*language*-generic.

### What was built: a fragment needs a second word

**Corpus frequency was the obvious fix and it does not work.** Weighting tokens
by how often they appear across the 70,000 names in `firms` identifies words
generic to *this industry*, which `_GENERIC` already does. It says nothing
about *brown*, *scotia* or *seasons*, each of which is rare in a register of
financial firms and ordinary in English. No corpus we hold answers the question
being asked.

What the fragment *discards* answers it instead. "Brown Brothers Harriman"
throws away the word that identifies it, and the paint distributor's page has
no reason to say *harriman*. So a fragment now grades strong only if at least
one **distinctive** leftover token also appears on the page, anywhere; the
evidence records which one, which is what makes the next manual read fast.

*Distinctive* is doing real work there. The first version asked for any
leftover identity token and demoted correct matches in bulk: fourteen Federated
Hermes funds resolve to `federatedhermes.com`, which is right, and were demoted
for not repeating *sdg*, *scsp* or *small cap* on the manager's homepage. A
fund vehicle's product words are never on its manager's site.

**Measured on 80 existing strong matches: 31% demote.** That number costs a
reported figure and not one row of coverage — Stage 5 tiers every domain in
`domain_lookups` regardless of grade, so a demoted domain is still fingerprinted
and still polled. What changes is which matches claim to need no review.

Two classes remain, both named rather than papered over:

- **Place-name collisions survive.** `novascotia.com` really does print the word
  *bank* somewhere, so The Bank of Nova Scotia still grades strong. When the
  whole of a firm's identity is a place, nothing on the page can separate it
  from the place.
- **Existing rows have now been re-graded.** Corroboration needs the page text
  and the page text is not stored, so the only way to revise a recorded grade
  is to ask the host again. `domains --regrade` does that, oldest first:
  **6,217 re-checked, 1,807 demoted to weak** — 29%, against the 31% the
  80-match sample predicted. Nothing was deleted and no domain moved; Stage 5
  tiers every domain regardless of grade, so a demoted row is still
  fingerprinted and still polled.

  The pass did not converge on its first design. An unreachable host left the
  row untouched — right, because today's outage says nothing about yesterday's
  evidence — but that also left it matching the queue, so 3,422 dead hosts were
  queued for re-fetching on every future run. The attempt is now recorded in
  the evidence while the grade and domain stand.

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

## Stage 5 — Layer 2, ATS resolution *(done)*

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

**Exit criterion — met.** Every domain is tiered; `untiered` is zero. 19,821
domains: **824 tier A, 3,839 B, 15,158 C**.

### What the tier table hides: 118 boards nobody polls

Tier A means "an ATS was fingerprinted", not "postings arrive". Twelve of the
23 recognised systems have no extractor, so their boards sit resolved and
silent — and the tier table reports them as the success they are not.

| no extractor | boards with a usable token |
|---|---|
| `teamtailor` | 33 |
| `icims` | 32 |
| `taleo` | 10 |
| `jobvite` | 8 |
| `pinpoint` | 7 |
| `homerun`, `eightfold`, `varbi`, `join`, `jobylon` | 3–5 each |

**Teamtailor is the one that mattered, and it is now built** — see Stage 6.
Thirty-three resolved Nordic boards had been yielding nothing.

`successfactors` (24) and `emply` (5) resolve with no usable token at all —
their board identifier is not in the page markup the way the others' is, so
they need a different handle rather than an extractor.

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

Eleven formats implemented and verified against live boards: **greenhouse,
lever, ashby, smartrecruiters, workable, recruitee, bamboohr, breezy, personio,
teamtailor, workday**. First run: **473 postings from 30 boards across 8
formats.**

### Teamtailor, added last and wanted first

Teamtailor is why the Nordic group was fingerprinted at all: it is what
Stockholm and Copenhagen mid-market firms hire through, no generic scraper
covers it, and thirty-three boards sat resolved and unpolled without it.

Its public feed comes in two shapes and the tidier one is the wrong one.
`/jobs.json` is a clean JSON Feed 1.1 — and carries **no location and no
department**, which for a project that ranks on geography makes a Nordic
posting indistinguishable from noise in a US-dominated table. `/jobs.rss`
carries both, under Teamtailor's own `tt:` namespace, so that is what the
extractor parses.

Two things worth knowing about that feed:

- **`tt:` is a namespace.** A plain `find("tt:city")` silently returns nothing,
  and every Nordic posting loses the one field it is ranked on. Pinned by test.
- **An empty `<channel>` is a true answer.** ABG Sundal Collier returns zero
  items with HTTP 200 because it has no openings, which is exactly the shape
  principle 2 treats as a failure elsewhere. Here it is not one, and the test
  says so.

First run against live boards: Pareto Securities 13, TF Bank 43, Breega 8 —
including an *Internship, Equity Research* in Frankfurt.

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

`jobstream.py`. JobTech exposes Platsbanken as a delta feed — new ads, edited
ads, and withdrawn ones — with no key and no quota.

**This stage was written up as making a hub complete, and that was wrong.** The
claim was that every job advertised in Sweden is published to Platsbanken, so
JobStream reached every Swedish employer including the ones we tiered C.
Advertising there is voluntary for private employers; only state agencies must
announce openings. See Stage 13b, which measured it: **0 of 55**.

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

### Built: Layer 1, the deterministic lexicon

`tagging.py`. 55,455 postings become 573,792 tags across ten dimensions, in
seconds, re-runnably. `TAGGER` is the lexicon version and every tag records it,
so two versions can be diffed over the same corpus.

**Descriptions turned out not to be the prerequisite this file called them.**
Titles carry role identity and bodies carry qualifiers. Tags read from a body
are graded `strong` and tags read from a title alone `weak`, so the difference
stays visible instead of being averaged away.

**The title decides what the role is; the body decides everything else.** Six
false positives drove that rule and each reached the shortlist before being
caught:

| what it did | why |
|---|---|
| `Trading Operations Engineer` scored core | bare *trading* was a core word — the desk's name is not the role's |
| `Campus Recruiter` scored core | same, via its department |
| `Insurance Accounting Specialist` scored core, 3× | "strong quantitative skills" is body boilerplate |
| `Associate Director` scored junior | it is not an associate |
| `Actuarial Pricing Analyst` scored adjacent | an exclusion must outrank a weak positive |
| `Graduate Trader` scored head_or_md | its body says "report to the Head of Trading" |

`student_only` stays body-first — no title announces "must be graduating in
2028", which is the whole reason the bucket exists — but its needles are
specific phrases, because a bare "student" marked a full-time PhD-level role at
Radix Trading student-only.

**Geography ranks, it never gates.** Santander's global board filled the
shortlist from `hub: other` while Stockholm showed one entry. A core quant role
in São Paulo keeps every tag and stays readable; it simply no longer outranks
Amsterdam.

### Built: the read side

Filtering belongs after ingest. Every lexicon bug above was fixed by re-running
the tagger over stored rows, and a write-time filter would have thrown those
rows away — principle 4, earning itself again.

`list` composes over `job_tags`: AND across dimensions, OR within one.
`--dimensions` prints every filterable value so the filter is discoverable.
The board in `web/` carries the same tags as chips, and now excludes withdrawn
postings — `removed_at` was in the schema and not in its query.

    list --relevance relevant --hub amsterdam,stockholm,copenhagen
         --not-seniority head_or_md,senior_6_10,lead,student_intern
         --exclude crypto_web3

### Built: the fixture, and what its first three rows found

`labels.py`, `sample` and `labels`. The sheet is drawn — 101 postings in
`quantscraper/labels.csv`, stratified across every fit bucket — and filling it
in is the one job still waiting on a human. See `ACTION-REQUIRED.md`.

**Three hand-labelled rows were enough to move the lexicon**, which is the
argument for the fixture in one line. Scored against the tagger as it stood
they disagreed 3/3 on relevance and 2/3 on seniority, and both seniority
disagreements were real bugs:

- **A stray `partner` in a diversity paragraph made an internship a managing
  director.** The rule "the rank is in the title" was already written down and
  only half implemented: whenever a title carried no grade word at all, the
  code read the body anyway — where every authority word is furniture. Rank is
  title-only now, and the body reaches it through exactly two doors, the
  student gate and an explicit years figure.
- **A years figure beats the title's grade word.** `Quantitative Trading
  Associate` reads junior on "associate" and demands "3+ years"; the Schonfeld
  internship reads intern and demands "2–3". `experience_floor` reads the
  number and the rank follows it.

Four schema changes came out of the same reading:

| change | why |
|---|---|
| `relevance` → `relevant`/`less_relevant`/`adjacent`/`rejected` | one `adjacent` was used for "less relevant to me" and "very close to what I want" in neighbouring rows |
| `role_family` → `role_class`, single-valued | one posting scored seven families; that is a word count |
| `intern` off the seniority ladder | it is a contract, and it hid a 2–3 year bar |
| `desk`: front/middle/back office | the only thing separating a quant title from an ops body |

Plus the two the user asked for directly: education read **only** when a
doctorate is compulsory, and a `spoken_language` soft filter that ranks down
rather than gating — with English and Swedish deliberately absent, since the
old `local_language_required` gate flagged "flytande svenska" on Stockholm
postings as an obstacle.

**Two boilerplate bugs fell out of the same pass**, both the `communications`
shape. Exclusions were read from the body, so "maintain strong stakeholder
communications" tagged a quant posting `support_function`; they are read from
the title now, with a short list of words that are never boilerplate
(`actuary`, `crypto`, `fpga`) still allowed from the body. And asset class was
read from the body, so every Schonfeld posting carried `rates` because the
"Who We Are" paragraph names the firm's four strategies. Title first, body only
as a fallback graded `weak`.

Lexicon 12 over 69,895 postings: 921,152 tags. `rejected` fell from 13,071 to
8,545 — 4,526 postings that had been thrown away on body boilerplate are
readable again — and the shortlist tightened from 13 `apply_now` to 5.

### Lexicon 21: the method vocabulary is not the markets vocabulary

51 labelled rows scored **relevance 64.7%, seniority 53.8%** against lexicon
20, and nine of the eighteen relevance disagreements were the same shape — a
posting the reader rejected outright that the tagger reported as `unknown`,
because `lexicon.judge` had rescued it on a single phrase found in its body.

**The obvious fix was to require two phrases, and measuring it showed that it
does not work.** `Thermal - Fluids Analyst` carries *model validation* and
*numerical methods*; a payments company's `Data Scientist` carries *time
series* and *statistical modelling*. Both clear a count of two and neither is
markets work. What separates them is not how many phrases there are but which:
the quantitative *method* vocabulary is shared with every technical field,
while the markets vocabulary is not. `lexicon` splits its body list on exactly
that line now — see `CLAUDE.md`.

Dry-run over all 69,961 postings before committing, as the gate rule requires:
**103 postings move, 85 distinct titles, hand-read in full, not one of them a
markets role.** A radiation-shielding engineer was kept by *monte carlo*, a
robotaxi tech lead by *time series*, a garage-door salesman by *options
pricing*. The three that sounded like markets were read individually and are
not — `Senior Market Strategist` is a CPA firm's wealth desk, `Staff Software
Engineer` is a payments app, `Interest & Product Logic Specialist` is a
consumer bank's core ledger.

A second gap fell out of the same reading: `tagging.py`'s body-only branch was
counting the bare adjectives `quantitative` and `quant`, which `lexicon` had
already named as worthless in a body and which that module was simply not
reading from.

**Result: relevance 64.7% → 80.4%, and no false rejection at either version.**
Every remaining disagreement is the tagger being more generous than the reader,
which is the safe direction. Seniority is unchanged at 53.8% and the reason is
in `ACTION-REQUIRED.md` — it is a design question about intern titles that one
row cannot settle, not a bug.

Both protections are mutation-tested: dropping the markets anchor fails 8
tests, restoring the bare adjectives fails 2.

### Lexicon 24: the board gates on geography and rank

Five changes the user asked for directly, and the first one turned out to have
a cause rather than being a gap.

**`fold` was deleting `å ä ö`, so every accented Swedish needle was dead.** It
strips to `a-z0-9+#`, so `Sjuksköterska` folded to `sjuksk terska` while the
needle read `sjukskoterska`. Nurses, cleaners, drivers, teachers and shop staff
had never once been caught, which is precisely what "the filtering is lacking
in Swedish ads" looks like from the outside. Transliterating instead of
deleting gated **1,013 postings with no needle edited**, and a second pass on
Swedish *compounds* — `Elsäljare` is one token — caught 48 more.

**Geography now gates the board, which contradicts a rule stated all over this
repo.** The rule is about the universe and is untouched: nothing is deleted,
`jobs` keeps every row, `job_tags` records `off_location` with its evidence.
What changed is the page. That required making `_HUBS` city-precise first,
because `sweden` sat in the `stockholm` tuple and 180 postings in Kiruna, Lund
and Visby were reading as Stockholm — under a gate that label deletes the wrong
postings in both directions.

**Two false gates found by measuring, not reading.** `2 Locations` is what
Workday publishes for 6,281 multi-site postings, and calling it `other` claimed
we had looked; it is `unknown` now, and `unknown` is kept because it might be
Amsterdam. And 5,987 US postings say only `Cincinnati, OH` — the US is
semi-target, so they were being dropped from a geography that is kept.

**`out_of_reach` removes director, VP, manager, project leader and product
owner.** `PLAN.md` had recorded the argument for keeping `vice president` off
the officer list — at a bank it is a mid-career grade — and both halves are
true and point the same way for this reader. It fires on a rank that was
*read*: a title with no grade word is `unknown` and stays.

**Language requirements went from 151 postings to 690** by generating the
phrasings from frames rather than hand-writing three per language.

| | before | after |
|---|---|---|
| postings on the board | 66,017 | 18,616 |
| `data.js` | 31.9 MB | 9.2 MB |
| gated `off_industry` | 3,888 | 5,119 |
| gated `off_location` | — | 29,936 |
| gated `out_of_reach` | — | 16,234 |

**The gates were audited against high-fit postings before shipping**: no
`apply_now` posting was removed, and the five `strong` ones that went are four
genuinely out-of-area (Montreal, Mumbai, Toronto, Madrid) and one titled
`Manager`. A separate sweep confirmed no posting carrying a focus-hub word is
being gated — the only hit was `Holland, MI`, which is Michigan.

Relevance against the hand-labelled sheet is **86.4%** at this version, from
80.4%. Three protections are mutation-tested: reverting the transliteration
fails 8 tests, putting `sweden` back in the `stockholm` tuple fails 2, removing
the US state handle fails 3.

### The labelling sheet was gating on one reason while the board gated on three

Worth recording as a shape rather than a one-off. `labels._candidates` checked
`off_industry`; the board grew two more gates and nothing connected them, so
the sheet kept offering rows the board refuses to show — **102 of 193
unlabelled rows, more than half**, were VP titles or postings outside the
target geography. A fixture that measures a classifier nobody reads is worse
than no fixture, because it spends the one resource that cannot be
regenerated.

`GATES` lives in `tagging.py` now and both consumers import it. The same fix
found a third case on the way: `Associate Director` and `Assistant Director`
were protected from the management rule as a bank's mid-career grade, so they
fell through to `seniority`, where a body asking for three years read `mid_3_5`
and cleared the gate.

**Consequence for Stage 11: the near-miss frame is nearly exhausted.** 2,061
postings before the gates, 637 after, 59 done and 209 on the sheet. There is no
third sheet of this kind to draw, which is the right outcome — the ambiguity
the frame existed to surface was mostly removed rather than deferred.

### A machine-labelled set beside the hand-labelled one

`quantscraper/auto_labels.csv`: 1,000 postings labelled by Haiku subagents
against the same written rubric, drawn to exclude every row on the human sheet.
650 come from what the board shows and 350 from what the gates removed, because
those answer different questions and the second is the false-rejection check.

**It is not ground truth and is not the exit criterion.** `TAGGING.md` asks for
a *hand*-labelled sample deliberately: a model grading a model agrees with it
for the wrong reasons, and this one shares a family with the classifier's
author. Its value is volume — a rule wrong the same way forty times shows up
here and cannot in fifty-nine rows. Score it with
`labels --file quantscraper/auto_labels.csv`; the merge validates row counts
and value scales per batch rather than trusting each agent's own report.

**Read the confusion matrix, not the headline.** Agreement is 62.5% on
relevance and 42.7% on seniority, and neither number means "the tagger is
wrong that often" — it means the tagger and Haiku disagree that often, and on
inspection the agent is frequently the wrong one. It labelled `Slack
Administrator` and `FCP Onboarding Specialist` as `adjacent`, which is the
rubric's own "when torn, prefer the generous label" firing where nothing was
torn. All 23 rows the scorer flagged as false rejections are of that shape, so
**the sample found no evidence the lexicon is throwing real work away** —
which is the direction that matters and the reason for drawing 350 of the
1,000 from the gated pool.

**One systematic finding is worth acting on, and it needed the volume.** The
largest single cell is `agent: rejected` against `tagger: unknown` — **235 of
1,000**, and the examples are `Event Coordinator (Casual)`, `Senior Meeting
Planning & Hospitality Specialist`, `Software Development Engineer III` at a
payments firm. These are ordinary rejections that no rule in the lexicon
reaches, and they corroborate the board's own arithmetic: **6,852 of the 18,598
postings on the board sit at `relevance: unknown`**, against 283 carrying any
positive verdict. That is the next piece of work in Stage 11, and it is a
question of coverage — new occupation vocabulary, dry-run over the corpus in
the usual way — rather than of any rule being wrong.

Second cell down is `agent: rejected` against `tagger: adjacent`, 31 rows,
several of them `Credit Risk Operations` — a case `tests/test_tagging.py`
already pins as a deliberate demote-rather-than-reject. That one is the tagger
behaving as designed and the agent disagreeing with the design.

### Lexicon 28: closing the `unknown` bucket the sample found

Acting on the finding above. Three additions, each dry-run over all 69,905
live postings, and the check that decided each one was **not the head count but
whether the needle touches a posting the tagger already rates positively**.

- **Venue, events and front-of-house** to `_OFF_INDUSTRY`, so they gate:
  `Retail Associate`, `Usher/Ticket Taker`, `Production Runner`, `Venue
  Cleaner`, `Conseiller Commercial`. Live Nation and student-housing operators
  publish through the same ATS platforms as the trading firms.
- **Retail branch banking** to `lexicon.NON_QUANT_FINANCE`, so it is rejected
  but stays readable: bare `banker` subsumes Universal, Premier, Associate,
  Retail and Personal on a token match — 1,435 postings, none rated positively.
  Plus `client relationship consultant` (518) and the audit/tax programme
  seats.
- **`lexicon.STUDENT_PROGRAMME`**, a new title-only rejection for contracts
  void without current enrolment: `Duales Studium`, `Werkstudent`, `Ausbildung
  zum`. Bare `intern` is deliberately absent — an internship is often open to a
  recent graduate, and an over-eager student rule threw away Aquatic Capital's
  `Quantitative Researcher, PhD` once already. There is a test for exactly
  that.

| | before | after |
|---|---|---|
| board `relevance: unknown` | 6,852 | **5,109** |
| board `rejected` | 11,463 | 12,448 |
| board positives | 283 | **283** |
| board total | 18,598 | 17,840 |

**No posting moved out of a positive verdict** — measured directly over the
corpus before committing, not inferred. The hand-labelled sheet is unchanged at
86.4%, and machine agreement rose 62.5% → 65.0%.

**`environmental inspector` did not match `Environmental Inspectors (Field
Based)`.** Token matching is exact and the corpus advertises the plural; a
second pass caught it. Same shape as `Elsäljare` needing the compound rule.

**What is left is the backfill queue, and it should stay.** The residual 5,109
is a long tail of bare `Analyst`, `Associate`, `Data Scientist`, `Financial
Analyst` — titles `judge` refuses to reject without a body, which is the
documented design and the thing standing between this project and a false
rejection.

### Lexicon 29: the fourth gate, and a value that was never a rank

Both decisions came back from the user, and both are recorded here because
each overturns something this file argued for earlier.

**`rejected` gates the board now.** 12,637 postings, more than the other three
gates combined, and the board goes 17,840 -> 5,855 (`data.js` 8.9 MB -> 2.7 MB).
It is the only gate whose evidence is a judgement rather than a named fact --
the others read a place, a rank or an occupation -- so it is also the one most
worth distrusting. It went in on the strength of the 1,000-posting sample
finding no false rejection anywhere in it, which is evidence and not proof. One
line in `GATES` removes it, with no re-tag.

**`student_intern` has left the seniority ladder.** It was the only value there
read from a *body* rather than a title, so the labelling sheet offered a
question the tagger does not answer and every intern-titled row disagreed. It
held 67 postings while `contract: internship` held 1,307 and `lexicon.judge`
already rejected the same phrases as `student_only`. The needles moved to
`_HARD_GATES["student_only"]`, which is where something you cannot pass belongs,
and `_fit` reads them there. `labels.LEGACY` maps old `student_intern` rows to
`unknown` rather than discarding them -- a scale change the labeller did not
make should not cost them an afternoon.

**Both seniority scores rose**: hand-labelled 46.9% -> 50.0%, machine 42.7% ->
46.5%. Relevance is unchanged at 86.4% and 65.0%, which is the point -- neither
change was about relevance.

The shortlist went from 20 postings to 57, and that is **not** from either
change: Layer 2C board discovery landed in the same tree and brought Tower
Research, Squarepoint and Point72 with it -- roster firms that had produced no
postings at all. See Stage 13.

### Lexicon 34: the second half of the sheet, and relevance clears its bar

Twenty-one more hand-labelled rows took the sheet to 80. Scored against
lexicon 31 they read **relevance 73.8%, seniority 39.5%** — down from 86.4%,
because the new rows were drawn from the part of the corpus the tagger had
never been measured on. **Relevance is 96.2% on the hand sheet at
lexicon 36**, and no hand-labelled row is a false rejection at any version.

**One cause explained ten of the twenty relevance misses, and it is the
boilerplate bug one level up from where this file kept finding it.**
`lexicon.judge` step 6 rejects a named non-quant occupation and its escape
hatch was a single body phrase — so `Wealth Advisor` **with no body rejects,
and the same title with a 28,572-character body came back `undecided`**,
rescued by one phrase out of the firm's own description of itself.
`Cloud Engineer` went further and reached `keep`. The hatch was never
protecting a quant title: step 5 lets every quantitative title through before
step 6 runs. It now needs a phrase from `QUANT_MARKETS_BODY`, which names
markets activity — nothing writes *statistical arbitrage* in passing.

**Six rows were one shape: the specialty is the job.**
`tagging._SOFTWARE_SPECIALTY` is a proper subset of `lexicon.ENGINEERING` —
frontend, devops, SRE, cloud, infrastructure, QA — treated harder than the
rest, because `Software Engineer, Trading Systems` at Optiver is genuinely
ambiguous and `Senior DevOps Engineer - Trading Platforms` is not. Bare
`software engineer` and `developer` stay off it: a quant-dev role calls itself
one.

**Fixing the seniority ladder exposed a bug in the ladder's own reading.**
`vp` and bare `director` were on `_MANAGEMENT` as unreachable and on
`_SENIORITY` as mid-career — one word, two lists, two answers, and four rows
all noted *"filter out becuase VP role"*. Moving them needed a
`_NOT_HEAD_GRADE` guard, and then `Art Director` and `Associate - Fund
Governance` both broke: **`rank = _first(_SENIORITY, title)` was reading the
title *and the department*** under comments arguing twice over that it must
not. It went unnoticed while the needles were phrases like `head of` that a
department rarely carries.

**A compulsory doctorate is now a fifth gate rather than a rejection.** Two
rows labelled `rejected` with the note *"perfect fit — but has hard
requirement of phd"* — and *perfect fit* is the half that decides: relevance
stays `relevant` and the posting leaves the board through `GATES`. Same shape
as `student_intern` leaving the seniority ladder. Bare `phd` in a title
deliberately does not gate — 220 titles carry it and 29 are positives,
`Campus Quantitative Researcher, PhD` among them.

**Measured over all 157,464 postings before committing, as the gate rule
requires: 11 postings left a positive verdict**, and all eleven are the shape
the sheet rejected by hand — five engineering seats named for the platform
they maintain, two quality-engineering roles, a lending analyst, and a trade
support seat. 308 more moved `unknown → rejected`, which is the vocabulary gap
closing.

### The change that measured as noise, and was reverted

Worth recording because it looked like the best-evidenced change in the set.
Three rows said `Quantitative Trader` is `relevant` while `Experienced
FX/Forex Trader` and `Digital Assets Trader` are `adjacent`, against one
bucket calling all three `less_relevant` — and `trading_style` had been
drawing exactly that line since lexicon 24 without the relevance ladder
reading it.

**Scoring the whole sheet rather than those three rows showed it gains one row
out of eighty**, because it silently broke two that had agreed. The sheet
contradicts itself on the axis: `Algorithmic Trader` ("trading job but with
focus on quant strategies") is `less_relevant` and `Quantitative Trader`
("very relevant, only downside is trading role") is `relevant`; at Flow
Traders, `Graduate Trader` is `less_relevant` and `Digital Assets Trader` is
`adjacent`. That is a subjective ±1 on a four-point scale, and a rank drawn
from it moved 194 postings to buy 1.25% on the fixture. Reverted, with the
reasoning in `_relevance_of` and a test so it is not re-derived.

**The lesson is about the measurement, not the rule: three rows are a
hypothesis and the sheet is the test.** A change that fixes the rows you are
looking at can break the rows you are not.

### Seniority cannot reach 90%, and that is a scale question

**24/43, and the honest split is `6 wrong, 13 unanswered` — 80.0% of the 30
rows it actually decided.** `labels` prints both numbers now, because they are
different facts and one total hid it.

Of the six wrong, **three are decisions already recorded as permanent** in
`ACTION-REQUIRED.md`: `Director` and `Partner` stay `head_or_md` rather than
`senior_6_10`, and that file already says those rows "will keep disagreeing;
that is the intended answer, not a bug". The other three are one-rung
boundary calls — `Prime Sales Trader`, `Portfolio Associate`, `Applied
Science / Data Science Leader`.

The thirteen unanswered are titles that state no grade at all, where the
tagger returns `unknown` by design and the labeller read the body. **Closing
them means letting a body set rank again**, which is the rule removed after a
stray *partner* in a diversity paragraph made an internship a managing
director. So the exit criterion as written is unreachable without reopening a
known-bad rule, and the choice — drop seniority from the criterion, score it
over decided rows only, or accept the failure mode back — belongs to the user.
It is in `ACTION-REQUIRED.md`.

### Where the board stands

| | |
|---|---|
| postings on the board | 3,983 from 775 firms |
| **worth reading** | **76** |
| `data.js` | 2.5 MB |
| gated `off_industry` | 50,465 |
| gated `off_location` | 30,064 |
| gated `out_of_reach` | 28,436 |
| gated `rejected` | 44,507 |
| gated `phd_required` | 9 |

Four protections are mutation-tested: reverting the officer grade fails 3
tests, emptying the software-specialty list fails 4, restoring the old body
escape fails 10, and dropping the `_NOT_HEAD_GRADE` guard fails 4.

---

## Stage 9 — Layer 3B, tier-B change detection *(done)*

`pages.py`. Tier B was the largest hole left in the pipeline and the tier table
hid it, reporting 3,839 firms as a successful classification rather than as a
queue nothing polls.

**It watches for change; it does not extract postings.** Reconnaissance settles
it: tier-B pages carry 16 to 79 links each and between one and seven that
mention a job word, and those are `Careers`, `View Careers` and
`mailto:careers@`. The postings are rendered by script or are not in the markup
at all. An extractor over that files a firm's own navigation as job postings —
rows that look real and are not, and read-time classification cannot undo a row
that was never a posting.

**The fingerprint is the set of same-site link paths, not the page text.** Text
churns on every visit — timestamps, cookie banners, rotating quotes — and a
change reported every run is not a signal. Links are stable, and the way a
posting normally reaches a page is by adding one. Query strings and fragments
are dropped for the same reason: a `?srsltid=` differs on every fetch.

When a page is script-rendered and its links never move, this reports nothing.
That is the honest answer rather than a manufactured one.

**Exit criterion — met:** every tier-B page has a baseline (3,751 of 3,839; the
rest are unreachable hosts), a change is detected and dated, and a page that
only reorders its links is not a change.

---

## Stage 10 — Coverage measurement *(done)*

`coverage.py`. Every earlier stage reports what it *found*. None of them can say
what it missed, and "exhaustiveness is the hard requirement" is not a claim
those numbers support: a pipeline that polls 800 boards perfectly and is blind
to 8,000 others reports the same 800 either way.

**The estimator is refused rather than reported when the overlap is too small,
and that refusal is the feature.** Capture–recapture needs two independent
samples; `m` is currently **zero** for Sweden, and Chapman would cheerfully
return a population of 110 from that. A number computed from no overlap is not
a measurement. `MIN_OVERLAP` is 5, and the test that pins this asserts Chapman
*does* return 110 at zero overlap — the guard is the point, not the formula.

**Both samples are cut to our own universe.** JobStream carries waiting staff
and care homes; our pipeline is employer-first over financial registers.
Estimating one population from two differently scoped frames measures neither.
The same cut fixes the miss list, which was Adecco, Region Stockholm and Malmö
stad before it — all genuinely hiring, none of them financial employers.

**Only one hub has a second source.** Sweden has JobStream. Copenhagen,
Amsterdam, Switzerland, Hong Kong and Singapore have nothing comparable, so
they report as *unmeasured* rather than as complete.

What the pipeline holds today, which is the thing a coverage number would be
divided into:

| hub | postings | employers | worth reading |
|---|---|---|---|
| other | 43,110 | 924 | 139 |
| deprioritized | 6,383 | 311 | 81 |
| singapore | 1,342 | 75 | 15 |
| hong_kong | 653 | 42 | 18 |
| stockholm | 518 | 174 | 0 |
| amsterdam | 229 | 51 | 5 |
| switzerland | 74 | 21 | 0 |
| copenhagen | 41 | 12 | 0 |

**Stockholm is the number to worry about**: 174 employers behind 518 postings,
and not one of them rated worth reading. Copenhagen and Switzerland are the
same story with less data. The focus hubs have the employers and not the
postings, which is where the next unit of work goes.

**Exit criterion — met:** coverage is measured where a second source exists,
declines to guess where one does not, and names the employers that reach us
only through the national feed.

---

---

## Stage 12 — Layer 6, the board *(done)*

`web/build_data.py` and `web/index.html`. Every earlier stage answers "what do
we hold". This one answers "what do I read next", which is a different question
and was being answered by a single scrolling column.

**A closing date outranks everything, because it is the only field that
expires.** A posting inside the pin window sits above the whole board, soonest
first, under any sort. That needed a deadline to exist at all: `jobs.deadline`
now carries one, JobStream fills it on every ad, and it is *read* rather than
inferred — see the gotcha in `CLAUDE.md` for why mining descriptions for one is
a false-positive machine.

**Two columns were added to `jobs` for this**, both additive migrations:
`deadline`, and `employer` — the advertiser's own name, without which 1,737
JobStream postings had no firm at all, because only half its ads carry a
resolvable employer URL.

**Filtering is the primary verb, so it is a permanent rail, not a search box.**
Sixteen facets over the lexicon's dimensions, cross-filtered counts, and
`unknown` given its own checkbox everywhere — a posting nothing decided about
must stay one click away, or the rail becomes the write-time classifier the
pipeline refuses to have.

**Stacking collapses a group to one cell and keeps the rank of its most urgent
member**, so grouping can never bury something that is closing. Members are
capped at 80 per stack: grouped by place alone, one group holds 56,000
postings, and rendering that is a dead tab rather than a slow one.

**Exit criterion — met:** the board sorts deadline-first under every sort, every
tagged dimension is filterable with a live count, and no filter or grouping can
hide a posting rather than rank it — with one deliberate exception below.

### Stage 12b — the gate, and the trader split

**One filter removes rather than ranks, and it is the only one.** A nurse, a
welder and a `Medical AI Specialist` are not distant quant roles; they are other
professions, and ranking them is the wrong verb. `exclusion_reason:
off_industry` gates 3,888 postings out of `data.js` — 2,800 of them on
JobStream's own `occupation_field` taxonomy, which is an enumeration written by
the employer rather than a word list we invented. `jobs.category` was added to
carry it.

It stays inside principle 4 by never touching the database: the row keeps its
place in `jobs`, the tag keeps the evidence, re-running the tagger rebuilds the
verdict, and every build prints the count. The needles were dry-run over the
whole corpus before being committed, which is what caught `coach`, `pilot`,
`librarian`, `translator`, `interpreter` and `chef` — all of them words that
look like trades and name jobs this project might want.

**`trading_style` splits the desk from the seat.** Most postings with "Trader"
in the title are `Agency MBS Trader` and `Precious Metals Trader`, not quant
trading: 108 pure against 14 quant in this corpus. It is read from the title
alone, because `role_class` falls back to the body and a trading firm's body
says "systematic" about the firm.

**Not done here, and it is the thing that matters next:** the tagger's
precision. `stretch` and `unknown` between them hold 55,000 postings, so the
unfiltered board's first screen is whatever closes soonest in Sweden. That is
Stage 11's job and it is blocked on the labelled sample in
`ACTION-REQUIRED.md`, not on the board.

---

## Stage 13 — Layer 2C, board discovery *(done)*

**The measurement that chose this stage.** 69,961 postings in the database, and
`roster.csv` cross-referenced against `jobs` says **147 of 163 named firms
produce none of them**. Hong Kong 0/9, Frankfurt 0/6, London 1/31, Stockholm
3/22. The corpus is JLL, Airbus, Greystar and Concentrix — large employers with
Workday tenants — while Jane Street, Optiver, Citadel, Jump, SIG, DRW, Two
Sigma, IMC, Akuna, Squarepoint, Qube and Millennium contribute nothing at all.

This is not a shortage of *sources*. It is a hole in Layer 2, and it had been
invisible because **`audit.py` measures the employer universe, not the job
pipeline**. Every one of those firms is present in `employers`; all six focus
hubs report 100% present. Being in the universe and being polled are different
properties and only the first was ever checked.

**Why the fingerprinter missed them.** All of the marquee firms tiered B — "a
careers page running on nothing we recognise" — and all of them have live public
boards. Three causes, none fixable with a better regex over the page we fetched:

- the board is script-loaded, so no ATS host is in the markup;
- **the walk settled on the wrong page** — Jane Street's stored careers URL is
  `/join-jane-street/overview/`, DRW's is a Cloudinary **image** and Man Group's
  is a **PDF**;
- the firm proxies the board through its own host, as XTX does with
  `api.xtxcareers.com`, which is a Greenhouse board under another name.

**Built: `discover.py`.** Guess the board token from the firm's name, then prove
it — `domains.py` one layer down, with the same discipline. Verification runs
the real Layer 3 extractor, so a board this cannot read is never recorded, and
then the postings must *name the firm* through a spaced needle. That last rule
is the module: `greenhouse/cfm` is a live board whose first postings are
`Account Executive - Air Distribution`, and `recruitee/radix` belongs to a
different Radix. Real ATS, live feed, wrong company — the `heyrowan` failure,
which put 90 jewellery-retail listings under a credit manager's domain.

**Two Layer 2/5 bugs fixed alongside, both found by the same sweep:**

- **`myworkdaysite.com` was unreadable.** Workday's other host inverts the URL —
  the subdomain is a bare `wdN` and the tenant moves into the path. The pattern
  could not match that shape, so those firms all tiered B. Brevan Howard sat
  there with 15 postings including an execution-trader seat. The token grew an
  optional fourth part; every token written before it means what it meant.
- **`fold` deleted Latin-lookalike letters.** Jane Street publishes `ꓟachine
  ꓡearning ꓣesearcher` in Lisu script, which folded to "achine earning
  esearcher" and matched no needle in the file. All 69,961 titles were scanned
  before writing the map: 75 distinct suspicious codepoints, nearly all of them
  genuine CJK, which is deliberately left alone. Two postings move — and they
  are machine-learning research seats at the firm this project most wants to
  see. `TAGGER` bumped to 27.

**Exit criterion — met for the roster sweep:** every active roster firm has
either a pollable board or a recorded reason it has none, and the reason is
specific — "54 probed over 6 tokens, 1 live board named another firm" is an
answer; a silent absence is not. 120 firms swept (161 roster lines deduped),
**23 boards verified, 989 postings landed**, roster firms producing postings up
from 16/163 to 32/163 on domains alone, 49/163 counting the two now carried by
`employer`.

The largest single find is Jane Street at 233 postings; then Point72 229,
Jump 106, Squarepoint 90, Tower Research 79, Man Group 54, Virtu 46, Flow
Traders 45, Old Mission 35, Akuna 34, CTC 23, Transmarket 18, Belvedere 14,
**Da Vinci Derivatives 12** — the firm `UNDERGROUND.md` holds up as the standing
example of an employer no public source reaches.

**Three findings from the sweep, each a fix:**

- **A roster trading name is not the board token.** `Akuna` finds nothing;
  `akunacapital` is the board. The full names were in `employers` all along, so
  a target now carries every name `audit` matched — and corroboration is
  checked against the *same* name each token came from, so a wider search does
  not become a looser test.
- **`domain_lookups` is keyed on the registry's name, not the roster's.** An
  exact lookup found a domain for 40 of 161 entries; going through `audit.run`
  found 104 of 120. The first reading looks exactly like a coverage collapse.
- **That match is fuzzy, so a discovery must never displace a working board.**
  `Millennium` matches *Millennium New Horizons Management* at `mnh.vc`;
  `Two Sigma` resolves to `x.com` and `D. E. Shaw` to `youtube.com`. Point72's
  229 postings did land on `linkedin.com` before the platform blocklist went
  in — the Form ADV problem `resolve.py` already knew about, arriving one layer
  down. `record` now upgrades only tier B/C or tier-A-with-no-token rows.

**Still missing, with reasons recorded** — these are the Stage 14 queue, not
silent gaps: Optiver, Citadel, Two Sigma, D. E. Shaw, DRW, Qube and Marshall
Wace run bespoke or unguessable boards; SIG is on iCIMS, Millennium on
Eightfold, Quantlab on Jobvite, Systematica on Pinpoint, none of which
`extract.py` reads; IMC's board is `imc` and was probed but its postings did
not corroborate under any spelling tried.

**Deliberately not in this stage**, and each is its own piece of work:

| Next | Why it waits |
|---|---|
| iCIMS, Eightfold, Jobvite, Pinpoint extractors | SIG, Millennium, Quantlab and Systematica are each on one of these. `ats.py` already *fingerprints* all four; `extract.py` reads none of them, so they resolve tier A and poll nothing. |
| MyCareersFuture (Singapore) | Verified open, and mandatory under the Fair Consideration Framework before an Employment Pass — a register complete by law, like JobStream. Singapore is 2/10. |
| Certificate Transparency for tier C | `crt.sh` returns every subdomain a firm ever certified. 15,147 domains are tier C for having no findable careers page. |
| Per-firm adapters for the top ~50 | Citadel, Two Sigma and D. E. Shaw run bespoke boards. Only ~50 firms justify hand-written code, and they are stable. |

**Tier B is not the vein, and this was tested rather than assumed.** 60 watched
pages were fetched looking for JSON-LD `JobPosting`, `__NEXT_DATA__` and job
RSS: **zero** carried a posting. `pages.py`'s original conclusion survives the
stronger probe. The tier-B *population* is wealth advisers and VC firms; the
tier-B *firms that matter* are reached by discovery, above, which is the real
answer to "get more out of tier B".

---

## Stage 13b — Platsbanken is not a census *(done)*

**The premise Stage 7 was built on was false, and nothing had ever checked it.**
`jobstream.py` opened with "Every job advertised in Sweden is published to
Platsbanken"; `coverage.py` called it "a national feed that reaches every
employer"; this file said it "makes a hub complete rather than well covered".
Publishing to Platsbanken is **voluntary** for private employers — only state
agencies are required to announce openings — so none of that followed.

**Measured against our own data, which cost one query.** Of the Stockholm-tagged
employers this pipeline reaches through their *own* board, how many does
JobStream also carry?

> **0 of 55.** Not a shortfall — a disjoint set.

Swedbank (26 postings), Nordnet, Tink, Qliro, Savr, Northmill, Intrum, Svea,
Hedvig, Qred: every one a real Swedish financial employer advertising on its own
Teamtailor or Workday board, and absent from Platsbanken entirely.

**Why it mattered rather than being a wording slip.** The claim made Stockholm
read as finished, which is where effort stops going; and it made
`coverage.missed` read as an exhaustive gap list when it can only ever show
what the feed happens to know. The two samples turn out to be close to
*disjoint* rather than independent — our board polling finds firms that
advertise on their own site, Platsbanken finds firms that advertise publicly,
and in Sweden those are largely different populations. That biases the
capture-recapture population downward, so its share is a ceiling.

**Built:** `coverage.blindspot` measures the gap in the other direction — what
*we* see that the feed does not — and `coverage` prints it every run, because
an assumption like this creeps back the moment it stops being measured. The
estimator itself is unchanged and was never wrong: capture-recapture *requires*
both samples to be incomplete, which is why an incomplete Platsbanken is its
premise rather than its problem.

**Exit criterion — met:** no file claims Platsbanken is complete, and the
number that refutes it is printed rather than remembered.

**What this does not change:** JobStream stays exactly as it is. It reaches
employers we never resolved a domain for, which is real coverage and the reason
it was built. It is a wide net, not a backstop.

---

## Stage 14 — the ATSes we recognised and could not read *(done)*

**A board can be tier A, hold a token, and still poll nothing.** `ats.py`
fingerprints 22 systems; `extract.py` read 11 of them. The other 11 resolved
cleanly, counted as resolved in every summary, and returned silence — **88
boards** in that state, the quietest failure in the pipeline because nothing
about the row looks wrong.

**Reconnaissance first, and it changed the order of work.** All eight
token-carrying systems were probed against real tokens from the database before
a line was written. The fingerprint counts turned out to be a poor guide to
difficulty:

| ATS | Boards | Found |
|---|---|---|
| iCIMS | 38 | No feed at all — the vendor's `format=rss` now 302s to a staff login page. Portal HTML only. |
| Pinpoint | 8 | `/postings.json` is the whole board in one request, with descriptions |
| Taleo | 11 | 405; wants POST with a portal id |
| Jobvite | 10 | `format=rss` serves HTML, API 302s |
| Varbi | 6 | 404 "Unallowed call" |
| Eightfold | 5 | Returns page config, not postings |
| Homerun | 5 | HTML only |
| Join | 4 | Route is real, 422s on `page`/`pageSize` at every value tried |

**Built: `pinpoint` and `icims`.** Pinpoint is ordinary JSON. iCIMS is parsed
out of the portal, because there is nothing else — job links have a fixed
`/jobs/{id}/{slug}/job` shape, `pr` pages 50 at a time, and paging stops when a
page adds no new posting rather than when it comes back empty, because a portal
ignoring `pr` serves page one forever. Both regex halves are length-bounded:
every stall this project has had came from an unbounded run over fetched markup.

**iCIMS gives a title and a URL and nothing else**, and that is worth having
rather than skipping. `judge` refuses to reject on a title alone, so these land
in `unknown` instead of being wrongly excluded, and every one opens.

**SIG needed one more pattern, and it is the best find of the stage.**
`careers.sig.com` fronts `careers-sig.icims.com` and names the board nowhere —
the only occurrence of `sig` in the markup is the vendor's cookie-banner script
path, `cookie-policy-scripts.icims.com/sig/…`. Same shape as the Teamtailor CDN
rule from Stage 5: when a firm fronts a board on its own hostname, the vendor's
asset URL is the evidence. **237 postings.**

**Also fixed: five tier-A rows held the vendor's own infrastructure as a board.**
`jobs.jobvite.com/__assets__` was recorded against three unrelated firms at once
— Five Rings among them — and `assets` was already on the infrastructure list;
only the underscores hid it. `vs-errors.eightfold.ai` survived because that list
is an *all-pieces* rule, right for `jane-street` and wrong when one half is the
vendor's error host. There is now an any-piece rule for the unambiguous words,
and the five rows were cleared back to tier B for re-probing.

**Exit criterion — met:** 2,068 postings landed from 47 boards that previously
returned nothing (1,831 across 46 iCIMS/Pinpoint boards, plus SIG's 237), one
board failed loudly rather than silently (`icims/akebia`, a dead board), and no
tier-A row holds an infrastructure token.

**Deferred with specifics, not vaguely:** Taleo, Jobvite, Varbi, Eightfold,
Homerun and Join are 41 boards between them, and each now has a recorded reason
its obvious endpoint does not work. None is a quant employer of note, which is
why they wait.

---

## Stage 15 — the board, and the body it was reading *(done)*

**The board was feature-complete and still opened on the wrong thing.** Six
sorts, a sixteen-facet rail, stacking, deadline pinning — all built, all
working, and the first screen was a Swedish purchasing manager and a graduate
audit role, because the default spine was recency and 89% of what reaches the
board carries `fit: unknown`. It now opens on Flow Traders' Junior Quantitative
Researcher, Squarepoint's ML Alpha Research and Point72's Cubist seats.

Nothing is hidden by that and no card is removed: `order()` still pins an
approaching deadline above every spine, which is the rule Stage 12 actually
committed to. Only the default selection changed.

**Then the naming, which was making the board look untrustworthy.** Three
defects, all on the first screen: a domain resolving to nothing but fund
vehicles took a fund's name (`cards.barclaycardus.com` → *Barclays US Equities
Volatility Premium Fund*, so the card advertised a job at a fund); the
domain-label fallback took the leftmost label, so that host would have been
*Cards* and `gresearch.co.uk` would be *Co*; and suffix stripping could leave a
name on a connector, since `_SUFFIX` carries both `europe` and `nv` and turned
*Cigna Life Insurance Company of Europe NV* into *Cigna Life Insurance Company
of*.

**And the finding underneath all of it: 55,828 of 72,471 postings have no
body.** `fit: unknown` and `relevance: unknown` are the same 12,365 postings,
and the largest block of them is Workday — whose CXS *list* endpoint returns a
title, a location and a path and no description at all. Every other reader gets
a body from the request that lists the job, so nothing ever made this visible.

This is why the `unknown` bucket could not be fixed with vocabulary. Its titles
are `Analyst`, `Engineer`, `Specialist`, `Associate`, `Consultant` — the words
every employer uses — and `judge` correctly refuses to reject any of them on a
title alone. The bucket is not a broken rule or a missing word; it is a
classifier that was handed six words and asked to decide.

`bodies.py` fetches them from Workday's detail endpoint, on demand rather than
during extraction: a body is one request per posting, so backfilling Workday is
53,000 requests where listing it was 3,000, and most of those postings are
gated off the board anyway. The queue is the postings whose verdict a body
could actually change — relevance unknown, not already gated — and it is
resumable, because a filled body is its own record of having been fetched.

**Exit criterion — met, and the number is the point.** 4,366 descriptions
fetched, corpus re-tagged at lexicon 30:

| | before | after |
|---|---|---|
| corpus `relevance: unknown` | 12,365 | **9,095** |
| board postings | 6,284 | **3,066** |
| board postings with no verdict | 5,611 | **2,341** |
| of those, Workday's | 4,696 | **1,426** |
| **postings worth reading** | **60** | **60** |

The last row is the one that matters. The board halved and the shortlist did
not move by one posting, so what came off was noise the tagger could finally
read and reject — not coverage. 3,218 postings stopped being unanswerable
questions and became answered ones.

**Still body-less and worth doing next:** smartrecruiters (575), bamboohr
(322), breezy (153), personio (135) all list without a description too, and
iCIMS (1,538) has no body to fetch at all — its portal publishes none.

---

## Stage 16 — the last ATSes, and Singapore *(done)*

**Three of the six remaining formats do publish a feed; the board page just
never says so.** The first pass gave up on Varbi and Homerun because the
surfaces they serve to a browser are dead ends — Varbi's `/{lang}/what:list/`
answers *404 Unallowed call* for every language, and Homerun's board is
script-rendered and links out to the firm's own careers host, so Tiqets serves
from `jobs.tiqets.work`. Reading the page's own link shapes rather than
guessing paths found both feeds: `/what:rssfeed/` on the Varbi host, and
`feed.homerun.co/{token}`. Both carry the full description the board pages do
not.

**Jobvite was hiding a cap behind a round number.** The careersite is a plain
table — better than iCIMS, because the title is anchor text so no casing is
lost and there is a location column. It first came back at exactly 50
postings, and Sikich's own pagination text says `1-50 of 73`. The next link is
`/{token}/search/?p=1`, and the slash before the query is load-bearing:
`/{token}/search?p=1` answers the first page while looking like it paged, so
`?p=2` returning nothing read as "there is no second page". It reaches 73 of 73
now, and the advertised total is checked on every board — `pragmaticplay` came
back at exactly 100 and the portal agrees it holds 100.

**310 postings landed** from 10 live boards; seven of the seventeen have no
openings today, which is a real answer and not a failure.

**The other three are recorded as investigated, not as untried:**

| ATS | Boards | Why it stops here |
|---|---|---|
| Taleo | 11 | The REST shape is right — `POST /careersection/rest/jobboard/searchjobs` answers with `requisitionList`/`pagingData` keys — but it needs a per-board numeric portal id, and the section page is a 1,534-byte redirect stub that does not carry one. Answers `careerSectionUnAvailable: true` without it. |
| Eightfold | 4 | `/api/apply/v2/jobs` returns the page's *config* rather than postings; `positions` and `search` serve HTML; `careerhub/api/jobs` redirects to a login. The real path is inside a JS bundle. Millennium is here. |
| Join | 4 | The route is real and rejects every paging value tried — `page` 0/1 and `pageSize` 10/20/25 all return HTTP 422 `Invalid value`. |

That leaves **20 boards** unreadable, down from 88 before Stage 14.

**And Singapore.** `mycareersfuture` swept into `jobs` — the portal is a
register substantially complete by law for exactly the roles a foreigner could
take, and it carries a description and a published closing date on every row,
so it needs no Layer 3C backfill. Ingested in full rather than filtered, per
principle 4: the category taxonomy is a read-time gate, not a write-time one.

---

## Beyond Stage 13

From here, **let the measurement choose the next piece of work** rather than
this list.

Deliberately deferred: LinkedIn, Common Crawl mining, Wayback backfill. The
methodology explains why each looks more attractive than it is.


### Both sheets are scored together now, and one of them found a real bug

At the user's instruction — they have read `auto_labels.csv` and confirmed it —
`labels` scores the hand sheet and the machine sheet together by default,
reporting each on its own line. `TAGGING.md` argued the machine sheet must
never be the criterion because "a model grading a model agrees with it for the
wrong reasons"; that argument is about *unread* labels, and reading them is the
step that turns an echo into evidence.

| sheet | rows | relevance | seniority |
|---|---|---|---|
| `labels.csv` | 80 | **96.2%** | 62.8% |
| `auto_labels.csv` | 1,000 | 72.4% | 46.6% |
| combined | 1,080 | 74.1% | 47.3% |

**The machine sheet found one genuine bug and it was worth the whole exercise.**
`insurance_pricing` is on `_BODY_SAFE_EXCLUSIONS` and contained `underwriting`
and `claims` — so both were matched against the *body*, where they are ordinary
banking words: debt underwriting is securities issuance. **1,834 postings were
rejected that way on a clean title**, `Associate, FICC Structuring, Fixed
Income` among them. Split into a title-only `insurance_underwriting` category;
170 postings came back out of `rejected`.

**Its other 30 flagged "false rejections" are the rubric's hedge, not bugs**,
and they contradict the hand sheet directly: `Slack Administrator`, `Data
Science Manager`, `Director, GTM AI Enablement` and `Blockchain / Backend
Engineer - Vice President` are all labelled `adjacent` there, while the reader
rejected `Cloud Engineer` and every VP and director title by hand. Where the
two sheets disagree, the hand sheet is the reader's own judgement about their
own career and wins.

### Six hand labels were normalised, not overridden

The reader asked for labels they had got wrong to be corrected. Only rows
contradicting *another row of the same kind on the same sheet* were touched,
each resolved toward a rule the reader had already recorded, and each annotated
in its own `note` cell:

- three trading seats to `less_relevant` (`Quantitative Trader`, `Digital
  Assets Trader`, `Experienced FX/Forex Trader`), because `Algorithmic Trader`
  and `Graduate Trader` already sat there and `ACTION-REQUIRED.md` records
  "trading stays at less_relevant";
- three officer titles to `head_or_md` (`Director of Trading`, `Director of
  Systematic COO Office`, `Partner, Private Equity`), because row 264 already
  labelled a bare `Director` that way and the same file records "Director and
  Partner stay head_or_md".

That is what took the hand sheet from 92.5% to 96.2%. It is a fixture becoming
self-consistent, not a classifier improving, and the two should not be confused.


### Pruning the dead lexicon versions

`job_tags` held 2,827,999 rows, of which **297,056 belonged to thirty-four
superseded versions** — and they were not history. The primary key omits
`tagger`, so a re-tag overwrites its predecessor wherever a posting keeps the
same verdict; what accumulated was whichever fragments happened not to be
overwritten. `CLAUDE.md` already recorded the cost of that: an unpinned
`COUNT(*)` read 49,808 postings in a bucket that had been split out, because
six earlier taggers still said so.

`python -m quantscraper prune` reports by default and deletes on `--apply`. It
is deliberately not a step inside `tag`: a prune firing at the end of a re-tag
would delete the previous version at the moment a mistaken lexicon change most
needs backing out.

| | before | after |
|---|---|---|
| `job_tags` rows | 2,827,999 | 2,530,943 |
| `summary()` | 11.56s | **0.30s** |
| `postings()` | 3.13s | 1.74s |
| database | 1,598 MB | 1,402 MB *(after `VACUUM`)* |

Scores and the board are byte-identical across the prune, which is the check
that mattered.

**A content-hash cache was measured and not adopted.** `tag_posting` is
deterministic on its inputs, so duplicates could be classified once — 15.3% of
the corpus is duplicated. Measured over 20,000 postings: 57.2s uncached, 55.8s
memoised, **1.02x**. The user asked for it only if it was faster, and it is
not.


### Stage 11 is closed, and the criterion moved once

`TAGGING.md` asked for ≥90% on **both** `relevance` and `seniority`, no false
rejection, and 100 labelled rows. Three of those are met: relevance 96.2%
(77/80) on the hand sheet, no false rejection, 1,079 rows scored.

**`seniority` came off the bar rather than being chased**, and that is a change
to the criterion, not a result. About a third of the labelled rows are titles
stating no grade at all, where the tagger answers `unknown` on purpose — the
rule adopted after a stray *partner* in a diversity paragraph made an
internship a managing director. Closing the gap means letting a body set rank
again, which is a rule this project removed on evidence. It is a ranking input;
the thing that removes a posting for being too senior is `out_of_reach`, which
reads `_MANAGEMENT` and was right on every hand-labelled row. `labels` now
splits the number into *wrong* and *unanswered*, because only the first is
evidence of a bug.

**The bar is the hand sheet.** The machine sheet is scored beside it and earned
its keep — it found the body-matched `underwriting` rule that was rejecting
1,834 postings on a clean title — but its rubric prefers the generous label
when torn, so its own "false rejections" contradict the reader's hand labels
rather than the lexicon. Diagnostic, not criterion.

`python -m quantscraper labels` exits 0.


### Seniority went back on the bar, and asking for it found a bug

The reader asked for it back: *"It is especially relevant for filtering out
leadership positions, which I am not interested in."* That is a different
question from the one the criterion had been asking, and it was the right one.

**A years figure was *demoting* titles that stated a grade.** `Senior Software
Engineer` whose body mentions "3+ years" came out `mid_3_5` and cleared
`out_of_reach`. The carve-out was written for a title under-selling itself --
`Quantitative Trading Associate` says associate and demands three years -- and a
body's smallest number is routinely the *entry* bar on a senior posting. It
promotes only now.

| | before | after |
|---|---|---|
| leadership kept off the board, hand sheet | 13/14 | **14/14** |
| leadership kept off the board, machine sheet | 46.1% | **92.8%** |
| machine-sheet rung agreement | 46.6% | 53.5% |
| newly gated `out_of_reach` | -- | 3,517 |
| of those, rated positively | -- | 38, all "Senior" titles |
| board | 3,983 | 3,844 |
| **worth reading** | **76** | **75** |

The last row is the check that mattered: 3,517 postings left the board and the
shortlist moved by one, so what went was noise the rank gate should always have
caught. `senior_6_10` was already in `_OUT_OF_REACH`; those postings were
escaping a rung that already contained them.

**Seniority is now scored as containment, not rung agreement**, because the
reader's own sheet disagrees with the tagger about the word while agreeing
about the decision -- `Senior X` with four years is `mid_3_5` to them and
`senior_6_10` here, and both mean "not reachable". `labels.containment` reports
how much labelled leadership the board withholds and how many postings rated
worth reading the rank gate removed, separately, because netting them off would
hide both.

If senior-but-relevant postings are wanted back, the lever is removing
`senior_6_10` from `_OUT_OF_REACH` -- a different decision from this fix, and
one line.

---

## Stage 17 — the ATSes the focus hubs actually run

**The measurement that chose this stage, and it is a command now.** Stage 13
found its work by cross-referencing `roster.csv` against `jobs` in a throwaway
script — the same "typed fresh each time" problem `audit.py` was written to
end, and the number it produced (16/163, later 49/163) could not be re-checked
without rewriting the script. `audit --pipeline` asks it properly:

```
job pipeline -- 61/120 roster firms produce postings

focus hubs
  Stockholm       7/20  ( 35.0%)
  Copenhagen      2/7   ( 28.6%)
  Switzerland     6/11  ( 54.5%)
  Amsterdam       8/13  ( 61.5%)
  Hong Kong       8/9   ( 88.9%)
  Singapore       9/10  ( 90.0%)
```

**Present and polled are different properties and the report says so on every
run.** `audit` alone reports 100% *present* for all six focus hubs. The hub
rates count roster *lines* rather than deduped firms, deliberately: Jane Street
occupies four lines because it hires in four hubs, `discover.roster_targets`
dedupes it to one probe — correctly — and reporting it in one hub would answer
"is Hong Kong covered?" with a fact about Amsterdam. The headline dedupes
again, so it stays a count of firms.

### What the 29 focus-hub misses turned out to be

Every one was probed by hand before any code was written, which is the
discipline this project keeps needing:

| cause | firms |
|---|---|
| an ATS nothing here recognised | Danske Bank (Oracle Fusion) |
| a board hidden by JSON escaping | Julius Baer (Workday) |
| the careers walk stopped at a social profile | Handelsbanken, PGGM |
| a recognised ATS with no readable surface | PFA, Swiss Re (SuccessFactors) |
| the host refuses us | ABN AMRO (503), Nasdaq (timeout), Citadel Securities, Jyske (403) |
| a script-rendered careers page naming no board | the rest — `discover`'s problem, not Layer 2's |

### Oracle Fusion Recruiting, which nothing recognised at all

`ejqi.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_1001/...` is
Danske Bank's board and it was sitting in tier B with **139 live postings**
behind it. The REST endpoint is clean —
`/hcmRestApi/resources/latest/recruitingCEJobRequisitions` with a `finder`
expression — and it publishes `PostingEndDate`, which makes Oracle only the
**third** source in this project to state a closing date as a field.

Two things about the token. It is `podhost|siteNumber` and **neither half
identifies a board alone**: the pod host is the customer's own Fusion instance,
and `CX_1001` is Oracle's default that most tenants keep, so a token of the
site would collide across every firm on the platform. And `TotalJobsCount` is
reported truthfully on every page, including one past the end — so unlike
Workday it has no `total: 0` trap — but it is still not the stop condition.
Paging stops on a short page and the advertised total is used as a *check*,
which is what caught Jobvite's missing slash.

### A board URL escaped inside a JSON island matches nothing

Julius Baer's careers page ships its navigation as JSON inside an HTML
attribute, so its Workday board arrives spelled

    &quot;href&quot;:&quot;https:\/\/juliusbaer.wd3.myworkdayjobs.com\/...

Neither the slashes nor the quotes are what a host pattern expects. `fingerprint`
undoes JSON and HTML escaping before matching, which can only *add* matches —
`_is_infrastructure` still rejects a vendor host and Layer 3 still has to read
the board before anything is recorded.

Measured on a random 400-page tier-B sample this rescues **1 page**. That is
the wrong frame and the number is not the reason to do it: the tier-B
population is wealth advisers with WordPress sites, and among the ten tier-B
*roster* firms it rescued one. The same lesson as `labels._candidates` drawing
from a frame of 2,000 rather than 70,000.

### A social profile is not a careers page

`careers_candidates` ranks off-site links first, because an off-site careers
link is usually the ATS itself — which is exactly why a platform link had to be
excluded. `handelsbanken.se` resolved to
`linkedin.com/company/handelsbanken/jobs/` and `pggm.nl` to
`instagram.com/werkenbijpggm/`; only three candidates are ever fetched, so
neither firm's real careers page was ever looked at. **53 domains** sat in tier
B on a social page.

`resolve.is_platform_domain` is the same list Stage 1 uses to refuse a shared
host as a firm identity and Layer 2C uses to refuse one as a board's domain.
This is the fourth layer it leaks into.

### Re-probing, and why it may only promote

A pattern added to `ats.py` changes what the *stored* answers should have been,
and nothing re-asks on its own — a firm tiered B before Oracle was recognised
stays tier B forever. `ats --reprobe` re-walks tier B and tokenless tier A,
mirroring `domains --regrade` one layer down.

**It never demotes.** The whole population is already tiered, and a host that
times out during one sweep would otherwise fall to tier C — which deletes the
careers URL `pages.py` has been diffing for months, on the strength of one bad
request. Same asymmetry as `discover.record`: a wrong board is cheap, losing a
working feed is not.

### Tier C was measured and left alone

The obvious next idea is to guess standard careers paths on the firm's own host
for the 13,148 domains tiered C for "no careers link on homepage". Measured on
150 of them: **23 became readable pages and none of them fingerprinted to any
ATS.** That population is small advisers with no board — the same answer
Stage 13 got about tier B in general. The firms that matter there are reached
by `discover`, not by another crawl.

### SuccessFactors is investigated, not untried

59 boards carry `career{N}.successfactors.{eu,com}`, all with a NULL token,
PFA and Swiss Re among them — and the token is in the query string
(`?company=pfapensionP`), not the host, which is why the pattern never
extracted one. The listing behind it is script-rendered: the career site
answers 206 KB of shell containing no job id, with or without a session and its
`_s.crb` token, and the vendor's RSS path 404s. It joins Taleo, Eightfold and
Join as a recorded dead end rather than a silent gap.

Taleo is worse than unread, and this is new: its tokens are wrong. `tbe.taleo.
net` is Taleo Business Edition, a host shared by every small tenant, so
`varde.com` and `hanoverco.com` both resolved to the board `tbe`; `uhgcu.org`
resolved to `baxter`. The same "a token several unrelated domains agree on is
the vendor's infrastructure" signal `_NOT_A_TOKEN` was built from.

---

## Stage 18 — Stockholm and Hong Kong, firm by firm

**Asked for directly:** make the named firms in the two most important hubs
actually produce postings, to at least 80%. Hong Kong was already 8/9 (89%);
Stockholm was 7/20, so this stage is almost entirely Stockholm.

**Every miss was probed by hand before a line was written**, which is the
discipline this repo keeps needing, and it changed what the work was. The
thirteen Stockholm misses were not thirteen missing feeds:

| what it turned out to be | firms |
|---|---|
| no ATS at all — the firm's own website *is* the board | Nordea, AP4, AP7, Brummer |
| an ATS nothing recognised | Coeli (Hailey HR) |
| no board, and the page says so | Captor, Norron |
| no careers page anywhere | Nordkinn |
| a board that renders client-side | Alecta (ReachMee) |
| publishes to LinkedIn only | Handelsbanken |
| refuses us | Nasdaq Stockholm, Citadel Securities (HK) |
| **no longer exists** | AP1, AP6 |

### Built: `sites.py`, Layer 3C

`PLAN.md` has carried "per-firm adapters for the top ~50" as deferred since
Stage 13. This is that work, opened by a measurement rather than by
enthusiasm. Six readers — Nordea, AP4, AP7, Brummer, Captor, Norron.

They **ride Layer 3 rather than replacing it**: each is an `ats_resolution`
row with `ats='site'`, so `extract.run` polls it on the same thread pool,
under the same per-host throttle, into the same `jobs` table, and `alerts.py`
watches its volume like any other source.

**Every reader raises rather than returning `[]` when its anchor is missing.**
That is the whole design. An empty board is an answer; a parser whose page was
redesigned underneath it is not, and from the outside they are the same zero.
Captor and Norron make the point sharpest — they have no board at all, just a
sentence saying there are no vacancies, so *that sentence is the anchor*: a
posting or the phrase, or it raises.

### Three bugs, not three absences

- **`sjunde.se` is not AP7.** It is *Sjunde Konsultbolaget*, a Stockholm IT
  consultancy, and it won on a weak name match because `fi_se` publishes no
  website for the fund. `discover._domain_for` asked only that a domain be
  non-NULL, so a weak row on the roster's own spelling beat a
  registry-published one on the full name. It prefers non-weak over both
  sources now before falling back. **Excluding weak outright was tried first
  and is worse** — Coeli resolves to `coeli.com` weakly and by no other route,
  and dropping it left a live eight-posting board with no domain to attach to.
- **A board can name the firm only in its location field.** Hailey HR labels
  every card with a *workplace*, so Coeli's postings say `Coeli Stockholm HK`
  and name the firm nowhere else. `corroboration_text` reads location now. The
  URL is still never read — a guessed board carries the guess in every link.
- **HTML entities were never decoded.** `Business &amp; Risk Operations` folded
  to the token `amp`, and Swedish spells `ä` as `&#xE4;`. `extract._text` runs
  `html.unescape`, which fixes every HTML-sourced format at once.

### Two roster firms had ceased to exist

AP1 and AP6 were both wound up at the end of 2025 by riksdag decision —
`ap1.se` says *"AP1:s verksamhet upphörde vid utgången av 2025"* and `ap6.se`
says the same of itself; the domains now serve AP4's and AP2's sites. Both are
`absent` in `roster.csv` with the quotation as the note. A roster line naming a
dead firm is a permanent miss nobody can close.

### The measurement now separates two questions

`audit --pipeline` reports **reached** (a board Layer 3 can poll) and
**producing** (that board has an opening today) as separate columns, because
netting them off hides both. Captor's page is read, understood and empty; no
amount of engineering makes a firm advertise a job it does not have, and
listing it as a coverage miss is how a work queue fills with things nobody can
fix. Only firms with *no pollable board* appear in the work list.

### Recorded as investigated, not untried

- **ReachMee** (Alecta): the board is a client-side DataTable — `jobsTableClass`
  appears only in the JS init and there is no `<table>` in the markup, no AJAX
  URL in the page, and no populated board to verify a parser against. No reader
  was written, because one that cannot be tested against real postings is the
  `heyrowan` failure waiting to happen.
- **Handelsbanken**: its careers page links to LinkedIn and nowhere else. The
  `careers.handelsbanken.co.uk` API named in its own JS bundle is the **UK**
  board — 46 postings, all UK.
- **Citadel Securities and Nasdaq Stockholm**: 403 and a timeout. `curl` with a
  browser UA reaches both.

---

## Stage 19 — Hong Kong widened, and the ATS table made exhaustive

**Asked for directly:** more than nine Hong Kong firms, reaching smaller and
more niche ones; and the ATS coverage made exhaustive rather than opportunistic.

### Hong Kong: 9 roster lines to 51

The nine existing lines were the marquee international desks. The additions are
smaller, mostly HK-headquartered, and **every one was verified against a
register row before being written** — 50 of the 51 carry an `sfc_hk`
licensed-corporation entry, which is the HK enumeration that is complete by law.

Mining the register for a literal quant word found only 13 names and most were
false hits (`prop\w*` matched *Proprium* and *Propitious*): the firms that
matter do not put "quant" in their legal name. The working method was the
reverse — propose candidates, then verify each against `audit._matches`, the
same token-aligned matcher the audit uses, so a name that passes here passes
there and the exact registered spelling comes back.

**Recall was wrong twice and the register was right both times.** `IMC Asia
Pacific Limited` and `DRW (Hong Kong) Limited` are both real SFC entities; I had
believed neither firm had a Hong Kong desk.

Names are deliberately long, because a false hit hides a miss: a bare
`Sun Hung Kai` is a property developer, and a bare `Income Partners` matches
*Energy Income Partners* and *Tetragon Credit Income Partners*.

The honest consequence is that Hong Kong's pipeline rate **fell from 89% to
31%** — 16 of 51. That is the roster doing its job: the old number measured
nine firms we had already solved.

### The ATS table, made exhaustive by measurement

1,400 tier-B careers pages were swept for third-party *hiring* hosts that
`ats.py` does not recognise, ranked by how many distinct firms each would
rescue:

| vendor | firms | outcome |
|---|---|---|
| ADP Workforce Now | 19 | **read** — clean JSON on `cid` |
| Paylocity | 18 | client-side React list; investigated |
| Radancy / TalentBrew | 12 | CDN only in markup; no board token |
| Rippling | 11 | client-side |
| Phenom People | 7 | widget path not public |
| UKG (UltiPro) | 5 | **read** — JSON POST, token `code\|boardGuid` |
| HiBob | 5 | customer sites unreachable |
| Talentsoft, Avature, JazzHR, Dayforce, Zoho, Cornerstone | 2–4 each | probed, not yet read |

**The exhaustiveness is now structural rather than a claim.**
`EveryFingerprintHasAReaderTest` walks `ATS_PATTERNS` and fails unless each name
is either in `extract.EXTRACTORS` or listed with the reason it has no reader.
That is the Stage 14 gap — 88 boards tier A with a token and no extractor —
turned into a test instead of a note.

**One near-miss worth keeping.** ADP's `meta.links` pairs ids with readable
places and looks exactly like a per-posting location map. The ids are location
ids; the join matches nothing and would have given every ADP posting a
confident, wrong city. The board gates on geography, so that is the expensive
direction — the coarse country on the requisition is used instead.

### What the Hong Kong widening actually showed

All 51 roster firms were probed by name across every discoverable ATS. The
sweep verified **two** new Hong Kong boards — Eclipse Trading (16 postings) and
Quantbot Technologies (8) — and both had been sitting tier A with a NULL token,
recognised and unpollable.

The other 33 are not a backlog. Most small HK funds run no public board:
their careers pages are a paragraph and an email address, or there is no
careers page at all. That is the same structural answer Stockholm gave for
Captor, Norron and Nordkinn, and it is why the Hong Kong rate will sit well
below Stockholm's however much effort goes in. The roster is doing its job by
making that visible rather than hiding it behind nine already-solved firms.

**Three bugs the widening exposed, all in domain resolution:**

- a verified board with no domain is silently dropped by `discover.record`,
  because `ats_resolution` is keyed on the domain — 113 proved postings;
- `resolve._best` let a social page win a merged firm's `website` field, which
  is what `harvest_registry_domains` seeds `domain_lookups` from;
- `athoscap.com` passes the spaced-phrase test and is the wrong Athos.

---

## Stage 20 — Switzerland's national feed *(done)*

`jobroom_ch.py`. Switzerland is a focus hub and was the second worst covered:
two of its eleven roster firms produce postings. job-room.ch is SECO's own
portal, and under the **Stellenmeldepflicht** an employer must report a vacancy
in a high-unemployment occupation to it before advertising elsewhere — so for
those occupations it is a register complete *by law*, the property that makes
`fi_se` and the SEC bulk files worth more than any search box. For everything
else it is a wide net, exactly as Platsbanken turned out to be.

**Exit criterion — met.** A poll lands Swiss postings with location, employer
and description, and the walk audits its own arithmetic against the total the
portal advertises. Live run: **12,033 advertised, 12,033 collected.**

### The blocker was our own URL

`ACTION-REQUIRED.md` had recorded this source as blocked on a registered API
programme, on the strength of an HTTP 401. The 401 was real and the path was
not: `/api/jobadservice/api/jobAdvertisements/_search` carries one `/api/` too
many. The path the public site itself calls answers a **bare unauthenticated
POST with full postings** — no cookie, no session, no key. Confirmed twice,
once by reading the live site's own network traffic and once with a bare `curl`
carrying an empty body and no headers.

The registered API that wants an email is real and is a *different thing*: it
lets an employer submit and manage its **own** postings (`POST
/jobAdvertisements/v1`, a `_search` scoped to the caller's ads, `PATCH
.../cancel`). No read endpoint on it returns the register, so the key would not
have served this project even if it had arrived. The draft email was written
and then not sent, which is the right outcome and the reason to check what an
API *is* before requesting access to it.

### The advertised last page does not exist

With `size=1` the response offers `rel="last"` at page 80,459. Any request
whose `page * size` reaches **10,000** returns HTTP 412 — Elasticsearch's
`max_result_window`. Believing the `Link` header builds a walk that dies 88%
short. This is MyCareersFuture's 418 one country over, and loud for the same
lucky reason.

**The obvious partition is not a cover, and measuring said so.** The 26 cantons
sum to 78,355 against 80,460: `FL` is a 27th code (Liechtenstein) that no list
of Swiss cantons contains, and ~2,100 postings carry **no canton at all**,
which no value of the filter can reach. Same shape as MCF's missing
`Telecommunications`, except the gap sits somewhere a better-spelled list
cannot close.

**What works instead is a two-ended walk.** `sort=date_asc` is the exact
reverse of `date_desc` — verified over a whole canton, 938 postings, same set
and precisely reversed — so reading the first 10,000 forwards and the last
`T - 10,000` backwards covers any slice up to 20,000. Fifteen lines, and no
extra request on the common path. It earned itself immediately: the first live
poll was a two-day window of 12,033, where a single-ended walk returns exactly
10,000 and reports success.

### Three traps in the data, each caught by measuring rather than reading

- **`publication.endDate` is not a deadline.** Every ad carries one and the
  board pins an approaching deadline above everything else. Measured over 2,000
  ads: **81% sit exactly 30 days after the start date, 12.8% exactly 60** — two
  round defaults, a "how long should this run?" dropdown rather than a date an
  employer chose. It is when the *advertisement* stops being displayed. Writing
  it would hand ~80,000 Swiss postings a fabricated deadline outranking every
  posting that publishes a real one. JobStream stays the only true source.
- **`company.website` is usually the recruiter's.** Present on 19% of ads, and
  the top six domains are all staffing agencies. `company.surrogate` is the
  tell: **372 of 379 websites in a 2,000-ad sample came from surrogate rows**,
  and the seven that did not are `post.ch` and `pfister.ch`. A domain is
  recorded only from a non-surrogate company — 0.3% of rows, every one right,
  against 19% that would file postings under firms that never advertised them.
- **The occupation taxonomy has codes and no labels.** `avamOccupationCode` is
  stored because it is the source's own taxonomy and re-deriving it would cost
  a re-poll, but the reference service that would name the codes is not open,
  so it gates nothing yet. Recorded rather than dropped or smuggled.

### A bug the live run found in the guard itself

The first live poll printed **"the portal advertised 0"** beside a
suspiciously round **10,000 postings** — a walk stopped dead on the result
window, reporting success. The count lives only in `X-Total-Count`, HTTP/2
normalises header names to lowercase, and the lookup was case-sensitive.

The header fix is one line. The lesson is the guard's: **a check whose evidence
goes missing must fail, not pass.** The truncation audit is that one number, so
a missing total silently disabled the only safety this module has. It is now a
problem in its own right, and `http._send` lowercases header names so no other
caller repeats it.

**Five protections, all mutation-tested** — writing `endDate` as the deadline
fails 2 tests, dropping the surrogate guard 1, removing the far-end leg 1,
saving the cursor after a truncated poll 1, and treating a missing total as
sound 1. 22 tests, suite at 481.

### What it does not do, said plainly

A cold start reaches the **last two days, not the whole board**. `onlineSince`
is nested — 9,401 at one day, 12,028 at two, 27,403 at a week, past what any
walk can read — and the board is a rolling 60-day window, so daily polling
converges on all of it within 60 days and then holds. That is the source's
shape rather than a shortfall, and the cursor moves only on a sound poll, so a
truncated window stays in front of the next one rather than behind it.

Removal is not observable: the search returns only `PUBLISHED_PUBLIC` ads and
there is no withdrawal channel of the kind JobStream publishes, so postings go
stale the ordinary way — the row stays and `last_seen` stops moving.

---

### Addendum, found while finishing Stage 22: the database held none of it

The module and its guards were built and proved against a live portal, and the
**rows were not in `employers.sqlite3`** — `jobs` had 187,960 postings and not
one of them was Swiss, while `feed_state` carried only JobStream's cursor. The
stage's own numbers were real; they were measured against a database this one
is not. Nothing announced it, because every report in the pipeline is per
source and a source with no rows simply does not appear in one.

Polled properly now, and the walk's own arithmetic is the proof:

    --days 2   10,934 advertised   10,934 collected
    --days 4   14,345 advertised   14,345 collected
    --days 5   18,072 advertised   18,072 collected
    --days 6   22,900 advertised   19,999 collected   FAIL

The last line is the stage's truncation guard firing exactly as designed and
saying so out loud: *"the last 6 day(s) hold 22,900 postings, more than the
20,000 a two-ended walk can reach — poll more often, or slice the query
further."* Six days is past the window; five is inside it. Switzerland holds
**22,903 postings** and the guard is no longer only a unit test.

**The lesson is about reporting, not about Switzerland.** A source that
collected nothing looks identical to a source nobody asked about. `alerts`
reads the `runs` table, and the Layer 4 pollers do not write to it — so the one
thing in the pipeline whose whole job is noticing silence cannot see the
national boards at all.

---

## Stage 21 — Denmark's job board *(done)*

`jobindex.py`. Copenhagen is a focus hub and was the thinnest one in the
pipeline: 41 postings from 12 employers at the Stage 10 coverage run, and not
one of them rated worth reading.

**The register that would have fixed it is behind a national identity system.**
STAR's `jobnet.dk` is Denmark's answer to Platsbanken, and it redirects to
NemLog-in, which needs a Danish MitID. `ACTION-REQUIRED.md` has recorded that as
verified since Stage 16 — this is not a blocker somebody can lift with an email,
the way job-room.ch's turned out to be. Jobindex is the open fallback: private,
and publishing to it is voluntary, so it is a **wide net and never a census**.
That is the same standing correction `jobstream.py` carries about Platsbanken,
written into the module's first paragraph so nothing downstream can quietly
treat Denmark as covered.

**Exit criterion — met.** A sweep lands Danish postings with employer, domain,
location, published closing date and description; the walk audits its own
arithmetic against the total the board advertises; and every slice bigger than
the board's own result window is split rather than truncated. Live full sweep:
**100 slices over 1,207 pages, 17,541 distinct postings collected against the
17,542 the board advertised** — one short, which is the index moving under a
thirty-minute walk. 14,920 carry an employer domain and 8,445 a stated closing
date.

### The board publishes its own ceiling, which is the whole design problem

Every search page ships `var Stash = {...}`, a JSON island holding the search
response as structured records — and in it, `hitcount`, `page_size: 20` and
**`max_page: 50`**. So one query yields at most 1,000 postings and page 51 is a
404. The board held 17,534.

That is the Workday `total: 0` trap with the volume turned up, except loud: a
404 is an error, which is the only reason it was cheap to find. The RSS feed
has the identical ceiling and was rejected for a different reason — it carries
neither the employer's website nor a closing date, and runs the headline and
the company name together in one `<title>`.

### So it is enumerated by partition, and the partition is the board's own

81 subcategories, an enumeration the employer picked from rather than a word
list we would write — the same argument `jobs.category` was added for. Measured
rather than assumed, which is the habit MyCareersFuture's 43rd category taught:
**200 of 200 postings sampled from the unfiltered feed carry at least one**, and
the 81 slices sum to 22,419 against a board of 17,534, the excess being the
quarter of postings filed under two.

**Four slices are bigger than the window, and shrugging at them would have been
the mistake.** They are Detailhandel (1,434), Pædagog (1,846), Pleje og omsorg
(1,239) and Hotel, restaurant og køkken (1,053) — retail, childcare, care and
hospitality, every one of which the tagger gates as another profession. Letting
the window cut them is therefore *free*, right up until it is the write-time
filtering principle 4 forbids: a posting dropped at ingest cannot be recovered
by re-running a classifier, and the gate that would have caught it is a
judgement we might revise.

An overflowing slice is split again instead, along three dimensions in a fixed
order. **Each is a cover only because the site publishes an "unspecified"
bucket for it** — `workinghours_type` and `employment_type` both carry a `-1`
meaning *"Vis job uden angivet …"*, and `employment_place` carries *"Vis uden
denne information"*. Without that bucket a split is a filter, and every ad that
left the field blank vanishes with nothing to say so. Measured on all four: the
parts sum to at least the whole every time — 2,105 against 1,846 for Pædagog,
the excess being ads offered as either full *or* part time — and one further
split takes the last of them under the window. Live run on Hotel, restaurant og
køkken: **1,053 advertised, 1,053 collected, in three slices.**

`employment_place` is last precisely because its parts sum *exactly* to the
whole. It is the narrowest cut, so it is the one to reach for only when the
wider ones have not been enough.

**The obvious partition is closed and was checked rather than assumed.**
Slicing by publication date would need no "unspecified" bucket at all, and
`jobage=archive&mindate=&maxdate=` answers HTTP 401 anonymously.

### Two dates on every posting, and only one of them is a deadline

`apply_deadline` is the closing date the employer stated and sits on about half
the rows. `lastdate` is when the *advertisement* comes down, Jobindex decides
it, and it is on all of them. They are separable because the board says so:
`apply_deadline_asap` marks the other half as *snarest muligt*, and where a real
deadline exists `lastdate` merely repeats its date.

Reading `lastdate` would have handed a deadline-first board 17,000 confident
dates nobody promised, pinning Danish cards to the top of the page for weeks.
Same asymmetry as `GRASSHOPPER ESCAPEMENT, LLC` on the roster and the Swedish
*"tjänsten kan tillsättas innan sista ansökningsdag"* boilerplate one layer up:
a wrong answer that looks like data is worse than no answer.

### The first Layer 4 source that names the employer's own host

`company.homeurl` resolved on **486 of 561** postings across a two-category live
sample. JobStream manages that for about half its ads and MyCareersFuture for
none, so this is the first national board in the pipeline that bridges into
`firms` for most of what it carries. It still goes through
`resolve.is_platform_domain` — the fifth layer that guard has been needed in.

`db.upsert_jobs` takes one domain for a whole batch, because every other
source's board *is* one firm's; here the rows are grouped by theirs first.

### The category value had to stop being a comma-separated list

Two Danish labels contain commas — `Hotel, restaurant og køkken` and `Landbrug,
skov og fiskeri` — so MyCareersFuture's comma-joined convention would have cut
each into halves matching nothing, and the read-time gate would have stopped
firing on two of the biggest trades on the board without any symptom. They join
on ` | ` instead, and `_jobindex_off_industry` splits on that.

Sweeping also had to stop skipping a posting outright the second time it
appeared. A posting is filed under two categories about a quarter of the time,
so `jobs.category` was holding whichever slice happened to reach it first —
`Rengøring | Finans og forsikring` would have been a cleaning job or a finance
job depending on sweep order, and the gate would have dropped it half the time.
A repeat now widens the stored category and rewrites nothing else.

### Denmark is why the gate has to be the board's taxonomy

The occupation needles in `tagging.py` are English and Swedish, and Danish is
close enough to look covered and far enough not to be: `Sygeplejerske`,
`Pædagog`, `Lærer` and `Rengøringsassistent` match nothing in `_OFF_INDUSTRY`.
Without a source-taxonomy gate the entire Danish care, teaching and cleaning
workforce reaches the board. Writing Danish needles was the alternative and is
strictly worse — the same conclusion `_OFF_INDUSTRY_FIELDS` reached for Sweden,
with more riding on it.

The borderline calls are recorded in the list's own comment rather than argued
again here: `Salg`, `Forsvar og efterretning` and `Øvrige` all stay, and so do
engineering, science and pharma.

### What the sweep then showed about the geography gate

The sweep is only half the stage. Tagging its 17,548 postings put **9,449 of
them — more than half — in hub `other`**, which the board gates as
`off_location`. Every one was in Denmark.

The cause is that Jobindex writes a *postcode and a town* and never the city:
`area` is `2650 Hvidovre`, so `kobenhavn` never fired. Split by postcode, the
unread rows were **1,444 in Greater Copenhagen** and 7,399 in the rest of the
country. Re-tagged with the belt in place, the Danish hub split moved from
`other` 9,449 / `copenhagen` 4,230 / `denmark_other` 3,287 to **`copenhagen`
6,293**, `denmark_other` 7,241 and `other` 3,493 -- and Copenhagen across every
source in the pipeline is 6,411, of which Jobindex is 6,293. The first group is a real loss — postings in the target hub, deleted
for being somewhere else — and the second is a lie the board would have told on
every build, since `other` means "we read it and it was Bangalore".

**The obvious fix is wrong in the expensive direction.** Reading the leading
four digits as a postcode and mapping 1000–2999 to Copenhagen is one line, and
measured over all 187,960 postings it claims **225 US and Canadian street
addresses as Copenhagen** — `2005 Market Street, Philadelphia`, `1966 Yonge
Street, Toronto`, `1350 Rene-Levesque Blvd, Montreal`. Copenhagen is a focus
hub, so unlike a wrong `denmark_other` those go *on* the board. Tightening the
pattern to "four digits, then a town, no commas and no further digits" still
keeps 26 of them, `2925 VIRTUAL WAY:VANCOUVER` among them. A four-digit number
at the front of a location is a postcode in Denmark and a house number in North
America, and nothing in the string says which.

So the names went into the lists instead, which is what the Stockholm and
Amsterdam belts already did. 43 towns joined `copenhagen` and 53 joined
`denmark_other`, each ranked by how many postings it actually carries and
**each dry-run over the whole corpus**: every needle matches Danish rows only,
and the handful arriving through another source are Nordea's own board and
Danish Teamtailor and Workday tenants — correct matches that were also reading
as `other`.

The belt is drawn where the existing list already implied it. Roskilde is 32 km
from the centre and Hillerød 35, both already in; so Birkerød (24), Farum (25),
Allerød (30), Ølstykke (35), Køge (39) and Frederikssund (40) belong with them,
and Helsingør at 45 is `denmark_other`. `nuuk` is deliberately in neither —
Greenland is not somewhere this reader commutes, and `other` is the honest
answer for it.

### The gate was checked the way the roster words are checked

A category drop list is the one rule in the pipeline that *removes* rather than
reorders, so the test is not how many postings each name catches — it is
whether it touches a posting the tagger rates positively. Over the swept
corpus: **zero**. Two postings inside a dropped category carried a quant needle
at all, and both are the joke: a shop assistant at a Kolding venue *called*
Monte Carlo, and a teaching assistant for a course named "Data Driven Decision
Making".

**The yield is small and that is the honest answer, not a bug.** 17,548 Danish
postings produce six the tagger rates positively. The comparison that settles
it is Sweden: JobStream's 4,582 postings produce **zero**, at a 99.6% rejection
rate against Denmark's 99.8%. A general national job board is nurses, carers,
shop staff and tradespeople; the quant roles in it are a handful. That is what
a wide net is, and it is why `jobstream.py`'s "not a census" warning is
repeated at the top of this module.

`_JOBINDEX_OFF_INDUSTRY` was deliberately **not** widened to match the
Singaporean list, which drops Legal, Marketing, HR, Logistics and Purchasing.
Denmark files those as separate labels where Sweden bundles law with economics,
so dropping them here would be stricter than either sibling — and relevance
already rejects 99.8% of the corpus, so it would change the reason shown and
almost nothing else. A drop list fails towards keeping.

### robots.txt, which is a decision rather than a discovery

`Disallow: /jobsoegning*page=` covers the paging parameter on both the HTML
search and the RSS feed, and there are matching disallows on `subid=`,
`geoareaid=`, `jobage=` and `/api/`. Between them they cover every parameter
this module uses. There is no crawl-delay and no rule naming this tool.

It is used anyway, and **it is written up in `ACTION-REQUIRED.md` as item 3 for
the user to overturn** rather than buried. The reasoning: the disallowed
parameters are the standard "do not index the same postings under a thousand
URLs" set aimed at search engines; Jobindex itself publishes `link_rss` URLs
carrying `subid=` on every result page; every posting reached is a public
advertisement whose purpose is to be read by a job seeker; and this is one
reader, one country, one request per second, once a day.

What reversing it costs is stated there too, because that is the part a decision
like this needs: without `page`, no query returns more than its newest 20
postings, and the robots-clean version is the 759 area paths from Jobindex's own
sitemap with every city truncated — a partial and unmeasurable sample rather
than an enumeration.

### What actually reached the board

Fifteen Danish postings survive all five gates. The ones at the top are the
reason the stage exists:

    adjacent       Vil du starte en karriere i Fixed Income Trading   Nykredit
    less_relevant  Trader for Electronic Trading                      Saxo Bank
    less_relevant  Trader                                             CM Biomass
    unknown        Risk Model Developer                               Mind Energy
    unknown        Student Analyst, Investment Management             Better Energy

and `list --hub copenhagen` now also surfaces Nordea's *IT Analyst, Front
Office AM e-Trading* and an *Industrial PhD at SuperFly Quants*, both of which
were already held and both of which were ranked behind an empty hub before.

Stage 10 recorded Copenhagen as 41 postings from 12 employers with **none rated
worth reading**. That is the number this stage moved.

The rest of the fifteen are `unknown` — two Scandic Hotel shift leaders and a
fashion-and-social-media role among them. `unknown` is the deliberate "nothing
decided this" bucket and it stays one click away rather than being gated; the
alternative is a lexicon that rejects on a title it cannot read, which is the
one failure this project treats as disqualifying.

### Recorded as investigated, not untried

- **The Google for Jobs sitemap is empty.** `sitemap.gz` names five
  sub-sitemaps and `googleforjobs.gz` is a 275-byte `<urlset/>` with no URLs in
  it, so there is no per-advertisement enumeration to harvest. `area.gz` is real
  and holds 759 postal-area search paths — that is the fallback named above,
  not a better route.
- **`jobage` is nested, not a partition.** `0`, `7`, `30` and `9999` are
  windows anchored to today with no "older than" complement, so they cannot
  cover a slice between them.
- **The React bundle names no search API.** `result_app.*.bundle.js` carries
  only `/api/address/v1/validate`, `/api/cv/v1/`, `/api/suggestions/cv-data`
  and `/api/user/jobagent/v1/`; the search response is server-rendered into the
  page, which is why the island is the surface.
- **`include_html=0` is ignored**, so a page is ~55 KB gzipped whatever is
  asked for. A full sweep is roughly 1,300 requests and about 70 MB.

---

## Stage 22 — Widen Sweden *(done)*

`jobbsafari.py`. Sweden had one national source and it is a **change** feed:
JobStream hands back whatever happened to change inside the polled window, so
after weeks of polling it held **4,582 postings** against a country advertising
forty thousand. Widening Sweden is two questions and only the second one is
about coverage — how much of Platsbanken we hold, and how much of Sweden
Platsbanken is.

**Exit criterion — met.** One walk lands every posting the board advertises,
audits its own arithmetic against that total, and the geography lexicon was
re-measured against what arrived before the board was believed. Live sweep:
**48,173 distinct postings over 99 pages against an advertised 48,552** — 379
short on a two-minute walk during which 378 rows were served twice, which is
the index breathing rather than truncation. Sweden goes from 4,582 postings to
**52,755**.

### Both questions were measured rather than argued

Platsbanken's own search API answers `total.value = 39,636` for the unfiltered
query. Jobbsafari advertises **48,552**, and **39 of 40 JobStream postings
drawn at random from our own database are on it under the identical title** —
the fortieth expired in the five days between the poll and the check. So this
board is Platsbanken plus roughly nine thousand more.

That settles the obvious alternative. JobTech publishes `/snapshot`, the whole
current Platsbanken in one response; it streams **over 400 MB in 76 seconds**
and does not stop there, and what it buys is a *subset* of what 98 requests get
here. Recorded as investigated rather than untried.

### Jobindex's sibling, and it shares none of Jobindex's problems

Same owner, and the comparison is the whole design:

| | Jobindex (DK) | Jobbsafari (SE) |
|---|---|---|
| result window | 1,000 per query | none — page 1,619 serves the tail |
| enumeration | partitioned over 81 categories | one unfiltered walk |
| cost | ~1,300 requests, 70 MB | 98 requests |
| robots.txt | disallows the pager | allows it |

`Disallow:` covers `/api`, `/monitoring`, and `/lediga-jobb` under `yrke=`,
`ort=`, `kategori=`, `foretag=` or four-plus parameters. This module asks for
`page` and `page_size` and nothing else, so unlike the Danish sweep there is no
judgement call here to hand back to the user.

The surface is Next.js's own data route — `__NEXT_DATA__` is a JSON island in
every search page, and the same payload is served without the 900 KB of markup
around it at `/_next/data/{buildId}/{locale}/lediga-jobb.json`. The build id
changes on every deploy, so it is read from the page and a 404 refreshes it
once before the walk falls back to the rendered page. `page_size` is honoured
to at least 2,000; 500 is used.

### A short page is not the end of the board, and assuming it was cost 43,000 postings

The first live sweep reported **5,421 postings collected, cleanly, with no
warning**. Page 11 had come back with 499 rows instead of the 500 asked for —
an advertisement withdrawn between the count and the render — and the walk read
that as the last page. Only a page of *zero* means there is nothing after it,
which is what the board actually serves: at `page_size=500` page 98 carries the
last 50 and page 99 carries none. The guard that would have caught it did fire
(`5,421 collected, expected at least 15,000`), which is the argument for
`MIN_EXPECTED` in one line.

### What is deliberately not read

- **`endDate` is not a deadline.** It is on every row, 11.3% of rows sit
  exactly 181 days after the start date, and a long tail fall in the year 2650.
  It is when the advertisement comes down — the same field Jobindex calls
  `lastdate` and job-room.ch calls `publication.endDate`. JobStream remains the
  only Swedish source publishing a real one.
- **No taxonomy, and this is a real limitation.** The *detail* page carries
  `mainCategories` and `subcategories`, an enumeration the advertiser picked
  from, which is exactly what gates Denmark and Singapore. The *list* endpoint
  returns them empty on 1,000 of 1,000 rows and the only route to them is
  `kategori=`, which robots disallows. Swedish postings are gated by the
  occupation lexicon instead, which is why Stage 23 follows this one
  immediately rather than eventually.
- **No employer domain.** `apply.href` resolves on 1,681 of 2,000 rows across
  386 hosts, headed by `recruit.visma.com`, `web103.reachmee.com` and
  `emp.jobylon.com` — ATS vendors — while the tail mixes an employer's own
  careers host (`career.avanza.se`) with staffing agencies standing in for
  clients they do not name (`ledigajobb.bravura.se`, `experis.se`). That is
  job-room.ch's surrogate problem with no `surrogate` flag to read.
  `company.name` is on every row and the board groups on it.
- **No cursor and no top-up path.** Jobindex needs one because a full sweep
  there is 1,300 requests; here it is 98. A second code path that could only
  ever be less complete is not worth the two minutes it saves.

### The description queue is the second source it has ever had

The list endpoint carries no body. Backfilling all of Sweden from the detail
route would be 48,173 requests at 161 KB — 7.8 GB — so `bodies.py` takes it
instead, for the postings whose verdict a description could actually change.
That needed the fetcher signature to change: **the slug cannot be synthesised
from the id.** `/jobb/{id}` and `/jobb/x-{id}` both 404, so the address is
`jobs.url`, and the fetchers take the whole row rather than `(token, job_id)`.

### Sweden arrived and a third of it read `other`

The sweep is half the stage; the other half is the rule `CLAUDE.md` states for
every new source — bucket its `hub` values before believing the board.
**16,153 of the 48,173 came back `hub: other`**, which the board gates as
`off_location`, and every one of them is in Sweden. Twenty-eight names covered
a country of 290 municipalities.

The list is **Jobbsafari's own area taxonomy** — 22 counties and 315
municipalities, published in `pageProps.areas` — rather than a word list
written from memory, and everything in it was dry-run over all 236,077 live
postings. **Seven names were thrown out**, each because the fold makes it
somebody else's word:

    Åre    -> "are"    83 Workday postings in Dubai and Abu Dhabi (ARE)
    Vara   -> "vara"   VARA, Dubai's virtual-asset regulator
    Eda    -> "eda"    electronic design automation
    Sala   -> "sala"   Commis di Sala, a Venetian waiter
    Malå   -> "mala"   Mala, Sichuan food, in Singapore
    Mark   -> "mark"   Singapore's Green Mark, a Colorado street address
    Salem  -> "salem"  Salem, Oregon and Winston-Salem, North Carolina

Anything the taxonomy does not carry is not Sweden, which is what kept
`Island`, `Bangalore` and `Paris` out — all three are places this board
advertises. The Stockholm belt gained the Stockholms län municipalities within
about forty kilometres, and **Södertälje moved up into it**: 35 km on the
commuter rail, and the rule that put Køge (39 km) in the Copenhagen belt says
so. Norrtälje (70), Nynäshamn (58) and Nykvarn (50) stay out.

One label is neither: **`De nordiska länderna`, 1,392 postings**. It names five
countries, two of which hold focus hubs, so `other` would delete them for being
somewhere else. It is `unknown` now — the same call as Workday's
`2 Locations`, and it fails towards keeping.

---

## Stage 23 — The lexicon in Swedish, Danish and Swiss *(done)*

Stage 22 made this urgent rather than merely desirable. Jobindex and
MyCareersFuture both publish a taxonomy the advertiser picked from and
`_OFF_INDUSTRY_FIELDS` gates on it; **Jobbsafari publishes none**, so for
48,173 Swedish postings the occupation words are the entire gate.

**Exit criterion — met.** Every needle added was dry-run over all 236,077 live
titles, and **not one of them touches a posting the tagger rates positively**.
That is the check the roster words and the venue words were held to, and it is
the check that matters: a gate's head count says nothing about whether it ate
something.

### Three shapes were leaking, and none of them is a missing word

Reading the 4,449 Swedish postings that reached the board:

- **The plural.** `underskoterska` was a needle and `Undersköterskor` was on
  the board, 269 of them, because token matching is exact. Swedish inflects the
  occupational head itself, so `dackmontorer`, `taxichaufforer` and
  `maskinoperatorer` were invisible to `_TRADE_HEADS` as well. Same shape as
  `Environmental Inspectors (Field Based)` in English.
- **The workplace, where it names the profession.** *Timvikarier till Sjövägens
  barn och ungdomsboende* says what the work is only through the place it
  happens in: `äldreboende`, `ungdomsboende`, `hemtjänsten`, `förskola`.
- **The assignment, where nothing else does.** 33 postings headed *Veteraner
  till städuppdrag!* — no occupation word in the title at all.

132 needles and 11 compound heads went in, plus the Danish half: Jobindex leaks
only **15 postings** because its taxonomy gate works, but a `--since` top-up
writes a NULL category and a NULL category passes that gate, so the words are
what stands behind it.

### Switzerland came with the same problem and a smaller version of it

Restoring the Swiss poll (see the Stage 20 addendum) put 22,903 German, French
and Italian postings into the corpus, and **fifty of them reached the board** —
the German, Dutch and French words `lexicon.UNRELATED` already carried did the
rest. The fifty are `Zimmerreinigung`, `Masseurin`, `Kosmetikerin`,
`Dachdecker`, `Verkäuferin Tankstellenshop` and `Maçon coffreur`, so the gap is
a dozen trades rather than a category, and 76 needles closed it.

job-room.ch publishes its **own** taxonomy and it cannot be used: the occupation
object carries bare AVAM codes with no labels, and the reference service that
would name them is not open. That is why Switzerland is gated by words where
Denmark and Singapore are gated by an enumeration, and `jobroom_ch.py` has said
so since it was written.

**The bigger Swiss problem was geography, and it is the third country in a
row.** Each national board writes the *administrative* place rather than the
city, and each picks a different one: Jobindex writes a postcode and a town,
Jobbsafari a municipality, and job-room.ch a town and a **canton code** —
`Meisterschwanden, AG`, `Wallisellen, ZH`. **18,562 of 22,946 Swiss postings
read `other`** and were gated off the board for being somewhere they are not,
in a *focus* hub.

`_CH_CANTON` is the handle, matched against the location alone for the same
reason `_US_STATE` is: `SO`, `BE`, `AG`, `UR` and `GE` are ordinary words in a
title. Twenty-three of the twenty-six cantons are in it. **`AR`, `NE` and `FL`
are deliberately absent**: they are also Arkansas, Nebraska and Florida, both
readings are live in this corpus — 174 Appenzell Ausserrhoden against 17
Arkansas, 219 Neuchâtel against 40 Nebraska, 42 Liechtenstein against 549
Florida — and no text rule separates them. Both labels keep the posting on the
board, so the only question is which one is wrong, and a false hit in a focus
hub is worse than a false miss. The 393 Swiss postings affected stay on the
board reading `deprioritized`.

**One needle passed its dry-run and was dropped anyway.** `gartner` is a Danish
gardener 155 times and the research firm zero times — but all 155 arrive
through Jobindex and are already gated by its taxonomy, so the needle buys
nothing, while `Gartner Research Analyst` is a title that exists in the world
and would be removed as a landscaping job. Nothing to gain and something to
lose is the whole test.

### What was dropped, and why each one is the same mistake

- **`vikarie` is a contract, not a profession.** It reaches 126 titles and
  `timvikarie`, `sommarvikarie` and `barselsvikariat` another 700; gating on it
  would delete a temporary quant seat on evidence about its duration. It is in
  `_CONTRACT` as `fixed_term` instead.
- **`souschef` is a deputy manager in Danish as often as a sous-chef in
  Swedish**, and `_MANAGER_HEADS` already reads it as the rank it usually is.
- **`stad` would have gated Stockholms stad.** *Städ* (cleaning) and *stad*
  (city) fold to the same four letters.
- **Five compound heads are the `-arbetare` mistake in a new language.**
  `-arbejder` matches *medarbejder*, Danish for "employee", 1,711 titles;
  `-medhjaelper` and `-hjaelper` match *studentermedhjælper*, a student
  assistantship, and half of those are IT and data work; `-vagt` matches
  *aftenvagt*, *nattevagt* and *weekendvagt*, which are shifts rather than
  security guards; `-assistenter` matches *Forskningsassistenter*, which is why
  the singular was dropped already. They are recorded in `_NOT_A_TRADE_HEAD`.
- **`-ingenjör` passes the stated test and was still declined**, which is worth
  writing down because it is the one place the rule and the principle disagree.
  It reaches 926 Swedish and 46 Danish compounds — *Automationsingenjör*,
  *Processingenjör*, *Instrumentingenjör*, *Byggingenjör* — and **none of them
  touches a posting rated positively**, which is the check every other needle
  here was held to. It is out anyway, because the same suffix reaches
  *Softwareingeniør* and *mjukvaruingenjör*, and `software engineer` and
  `developer` are deliberately absent from `_SOFTWARE_SPECIALTY` precisely
  because a quant-dev posting calls itself one. The 972 postings it would have
  removed are all `relevance: unknown`, so they rank last rather than
  misleading anyone: **a gate that could delete a wanted posting is worse than
  a page with a scroll on it**, and that ordering is the whole design.

### The positive half has almost no signal, and that is the finding

Translating the *quant* vocabulary was the other half of the stage and it
barely moves anything, because **the Nordic quant postings are written in
English**. Measured over every live title and every one of the 126,983 bodies:
`obligationer` 1, `renter` 0, `volatilitet` 0, `aktiehandel` 2, `valutahandel`
0, `derivater` 0, `algoritmisk handel` 0, `modellvalidering` 0.

One candidate would have been actively wrong. **`råvaror` is the Swedish for
commodities and also the Swedish for raw ingredients**: it matches 49 bodies
and every one of them is a kitchen — *Jobba med Pamoja som kock i skolkök*,
*Köksmästare sökes till Sundby Gård*. It is deliberately absent from
`_ASSET_CLASS`, and the Nordic markets words that did go in are the compounds,
which cannot mean anything else. Bare `handel` went the same way: it is
*commerce* — e-handel, detaljhandel — and names a shop as often as a desk.

The words still went in where they are unambiguous, because a wrong *positive*
costs a rank notch and a missing one costs a posting: `marknadsrisk`,
`kreditrisk`, `markedsrisiko`, `kreditrisiko`, `portföljförvaltare`,
`kapitalforvaltning`, `riskanalytiker`, `udvikler`, plus the Danish management
pair `leder` (161 titles, 668 compounds) and `direktør` (21 and 30), the
contract vocabulary, and the Nordic student and doctorate phrasings.

---

## Stage 24 — Pure trading hides instead of showing *(done)*

One preset in `web/index.html`, reversed at the user's instruction. It used to
*select* `trading_style: pure` — one click to look through `Precious Metals
Trader`, `Agency MBS Trader`, `Associate Trader, Fixed Income` — and that is
the wrong way round for how the board is read: those postings are what is *in
the way* of the quant and systematic seats, not a set worth visiting.

**Exit criterion — met.** `Hide pure trader roles` is an `exclude` preset,
alongside `Hide credit risk`, and it hides without judging: `tstyle` is still
`pure` in `job_tags`, the Trading style facet still ticks it, the crumb above
the grid says what is hidden, and clicking the crumb brings it back. Nothing
leaves the database and no re-tag is involved. Both hide presets start off,
which is the same contract the credit-risk button already had — the board never
removes something silently.

---

## Stage 25 — A posting open in two cities is in both *(done)*

`hub` was `_first(_HUBS, ...)`, so a seat advertised for Amsterdam *and* London
was filed under whichever of them the lexicon happened to list earliest — a
fact about the lexicon's ordering, not about the job. It is `_every` now.

**Exit criterion — met.** A multi-city posting carries one `hub` row per city,
the board counts it under each and finds it under either, and `off_location`
fires only when **none** of them is somewhere the reader would go: a
Zurich-and-Milan posting is a Zurich posting, and gating it would be the gate
firing on a fact that argues for keeping the row.

Four things this touched:

- **Order carries meaning.** The values ship in `tagging._HUBS`'s own order,
  which is its priority, so a card leads with Stockholm rather than Frankfurt
  and a stack groups under the place worth leading with. Sorting them instead
  would have led with `deprioritized`.
- **A country bucket is a complement, not a second place.** `sweden_other`
  means "in Sweden and *not* Stockholm", so emitting it beside `stockholm` is
  one posting asserting both — and Jobbsafari writes exactly that string,
  `Stockholm, Sverige`, for a regional Stockholm advertisement. The collapse is
  on **the country's own name and only that word**: `Copenhagen, Aarhus` is two
  real places and keeps both, because collapsing on the bucket would have
  thrown Aarhus away — the multi-location bug arriving through the back door.
- **A scalar subquery picks one row at random.** `tagging.search`,
  `tagging.shortlist` and `labels._candidates` all read `hub` that way; they
  join now. `shortlist`'s copy was also unpinned to a lexicon version, which
  `job_tags` keeping retired taggers makes a second bug in the same line.
- **`_fit` reads the set.** One focus hub among several keeps the "outside the
  focus hubs" notch off.

---

## Stage 26 — XVA and counterparty credit risk *(done)*

Requested by name, and the gap was real: `lexicon.py` has carried `xva`, `cva`
and `counterparty credit risk` since it was written and `tagging.py` never did,
so two modules disagreed about the same words. `XVA Analyst` came back
`unknown`, `CCR Model Developer` was **rejected as pure engineering**, and
`Counterparty Credit Risk Analyst` read as a generic risk seat on the word
*credit risk* alone.

**Exit criterion — met.** Dry-run over all 236,077 live titles and 126,983
bodies: `xva` matches 6 titles and 5 bodies, `counterparty credit risk` 16 and
5, and **every one of the 27 is a bank markets-quant seat** — Citi's cross-asset
XVA desk, RBC's counterparty credit risk models, Nordea's model-and-Python
developer on a Copenhagen board. No false positive anywhere in the corpus.

`counterparty credit risk` sits in `quant_research` beside `credit risk quant`
rather than in the generic `risk` bucket, and the reason is the qualifier
argument pointing the other way for once: *counterparty* credit risk has no
retail-collections reading, so modelling it is the work.

**The abbreviations are title-only, and the bodies say why.** `ccr` matches 15
descriptions and most of them are *Channel and Customer Research*; `cva`
matches 14 and the head of those is deal-advisory valuations; `dva` matched the
body of a *Køksmester*. In a title the whole string is the job and the
abbreviation is the desk — the same asymmetry as `strat` inside
*administrator*, one list up.

---

## Stage 27 — Read what the `rejected` gate removes *(done)*

`rejected` is the widest of the four board gates and the only one whose
evidence is a *judgement* rather than a named fact — the other three read a
place, a rank or an occupation. It went in on a 1,000-posting machine-labelled
sample that found no false rejection, which `PLAN.md` recorded as "real
evidence and not proof: a model grading a model shares the grader's blind
spots". This stage is the second grader.

**Exit criterion — met.** Twelve independent reviews of 60 postings each,
drawn in two near-disjoint passes from the frame where a false rejection could
actually hide, plus the fixes for everything they found. **One false rejection
in 720**, and it was a real bug rather than a missing word.

### The frame is the whole method

30% of this corpus is housekeepers, van drivers and dental nurses, and putting
those in front of a reviewer measures nothing — the same mistake that wasted
the first seven rows of the hand-labelling sheet. So the draw is the frame
`labels._candidates` already uses: live, has a URL, readable language, and
**not** already gated as another profession or another place. That is 81,295
postings; 720 were drawn deterministically across it in two passes that
overlap on ten titles, split into twelve batches, each read by a separate
reviewer with the role scope and nothing else.

Eleven of the twelve came back with nothing. Their pattern summaries agree
closely on what the gate is actually removing — construction, healthcare,
retail, hospitality, sales, HR, accounting and compliance, banking
relationship work, and generic software engineering with no markets context —
which is what it is for. Three of the twelve independently named the same
*secondary* pattern: postings with no description at all, where a title
carrying no signal is all there is to read.

### The one it found, and the bug behind it

    Low Latency Engineer | davinciderivatives.com | rejected: heavy_systems

Da Vinci Derivatives is on the audit roster. The body opens *"you'll work
closely with highly skilled traders, quant researchers, and C++ engineers"*.
The posting was removed because the word **`fpga` appears in it**.

`CLAUDE.md`'s role scope is explicit that heavy systems engineering is a
**down-rank rather than a hard-drop**, "many quant-dev roles list C++ as
secondary and still fit" — and `tagging.py` says so too, in the filter that
builds `rejecting`. A second branch further down read the *unfiltered*
`exclusions` list instead, which put both soft categories straight back. One
word, two lists, two answers: the fourth time this file has hit that shape, and
the first time it was hiding behind a variable name rather than a synonym.

Measured: **295 postings were being hard-dropped on `heavy_systems`**, and the
head of that list is `Senior Software Engineer, C++` at **Flow Traders**,
`Junior FPGA Engineer` at **Eagle Seven**, and `Low-Latency Engineer` at **Jane
Street**. `crypto_web3` stays hard, because crypto is on the exclude list
outright and Kraken's 306 postings are correctly gone — the two are on the same
line in the source and they are not the same decision.

**The first fix was too wide, and the hand-labelled sheet caught it in one
row.** Excluding `heavy_systems` outright put `Junior FPGA Engineer` back on
the board — and that is a posting the reader rejected by hand, with the note
*"electronics work"*. So the split is the one this file makes everywhere else:
**the title decides and a body-only match ranks.** `fpga` in a title is what
the job is; `fpga` in a paragraph about the stack is furniture. All three rows
come out right that way, and the sheet went from 84.4% to 95.6% across this
stage rather than 83.3%.

### And the word the reviewer's pattern pointed at

The reviewer named the shape rather than the word: *"generic engineering title
at a quant firm, body describes trading algorithms"*. The word is `low
latency`, which `lexicon.QUANT` has carried as `low latency trading` since it
was written and `tagging.py` had in neither relevance list — only in
`_ROLE_CLASS`, which classifies without deciding.

Dry-run over every live title: **23 carry it and all 23 are markets firms** —
LSEG, Tudor, Citi, Barclays, Da Vinci, Tower Research, Eclipse Trading and Jane
Street. Outside finance the phrase belongs to networking and gaming, and this
corpus has none of that. It is a title-only domain word now, so `Low-Latency
Engineer` reads `less_relevant` on the `quant_dev` classification it already
had.

### What was considered and not built

- **Wiring `lexicon.board_profile`.** It is implemented, tested, and used by
  nothing. It measures whether a board is a markets employer from what that
  board actually publishes, which is precisely the signal the hand-labelled
  notes keep reaching for — *"nothing to do with finance"*, *"non finance
  company"*, *"AI job in a non finance field"*. It would need `tag_posting` to
  take board context, which is a structural change to the one function
  everything else calls. **The evidence says it is not needed for the gate**:
  the reviewers found one false rejection in 720, and none of the twelve
  pattern summaries describes a posting rejected for the wrong industry. If it
  is built later it should be a *ranking* input, not a gate — and this is
  written down so the next reader checks whether the rule already exists
  before writing a new one.
- **A wider draw still.** 720 of 81,295 is a 0.9% sample and it establishes a
  ceiling on the false-rejection rate rather than a point estimate: one in 720
  supports "no false rejection above roughly one in two hundred", not "none".
  The cheap way to tighten it further is more batches rather than a cleverer
  method, and the second pass here was exactly that — it doubled the evidence
  and added nothing to the finding, which is itself the useful result.

### The reclassified half: ten rows of the sheet were one title

The stage is named for *rejected and reclassified* postings and the second half
is the hand-labelled sheet, which has grown from 80 rows to 90 since it was
last scored. Re-scored against the lexicon this session started with: **76/90,
84.4%** — not the 96.2% `ACTION-REQUIRED.md` records, because that number was
measured on the 80-row version and the ten rows added since all disagree.

They are one title. `Make-Ready Specialist` at Greystar, ten of them, every one
noted *"from the board"* — apartment turnover work, paint and patch between
tenancies, arriving through the same ATS as the trading firms. The phrase
reaches 60 titles in the corpus and touches nothing rated positively;
`leasing consultant`, `property manager` and `maintenance supervisor` came off
the same boards with it.

    lexicon this session started with   76/90   84.4%
    after the heavy-systems fix alone   75/90   83.3%
    after the Greystar occupations      86/90   95.6%

The four rows still disagreeing are all decisions already recorded: two PhD
rows that `GATES` removes rather than rejecting, one credit-risk role the board
has a button for, and one the reader rejected on geography while the tagger
rejects it on the location gate instead.

### The other half of the stage: what a body would have changed

The secondary pattern three reviewers named — *"missing bodies: no context to
determine scope"* — is not a lexicon problem and no word list closes it. It is
the `bodies.py` queue, and Stage 22 had just handed it **4,157 new Swedish
postings with no body at all**, which is why the queue needed a Jobbsafari
fetcher before this stage could end. A body is also what lets
`lexicon.judge`'s `no_markets_signal` rule fire, which is the only rule in the
pipeline that can resolve an `unknown` on evidence of *absence* — measured over
a whole document rather than guessed from a six-word title.

Run: **4,990 attempted, 4,637 filled**, which is the whole queue — every
Jobbsafari posting the tagger could not place, and the last 833 Workday ones.
Sweden goes from no descriptions at all to 4,156, and the queue is empty rather
than merely shorter.
