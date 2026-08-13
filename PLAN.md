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

**Focus:** Stockholm, Copenhagen, Amsterdam, Switzerland, Dubai, Hong Kong,
Singapore. **Deprioritized:** Germany, US, London/UK, China.

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
| 3 | Close audit-flagged gaps | **next** |
| 4 | Layer 2 — domain resolution | not started |
| 5 | Layer 2 — ATS resolution | not started |
| 6 | Layer 3 — ATS extraction | not started |
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

## Stage 3 — Close audit-flagged gaps

Only now add sources, and only the ones Stage 2 proved are needed. The first two
are new — the audit found them, and they are cheap because the registry already
exists:

1. **`fi_se` category walk is incomplete** (SE, Stockholm). It walks 20 of FI's
   139 categories. Alecta — Sweden's largest occupational pension manager — is a
   mutual (*ömsesidigt*) undertaking, not a `Tjänstepensionsaktiebolag`, so it
   falls outside all 20. One line in `CATEGORIES` per category added.
2. **DNB register** (NL, Amsterdam). Dutch pension asset managers are
   DNB-supervised, not AFM. PGGM is absent entirely; APG survives only through
   its US entity. The methodology names this register; it was never built.
3. **Finanstilsynet** (DK) — Copenhagen, 5/7 present and 3 local
4. **FINMA** (CH) — Switzerland, 9/11 present but only 5 local
5. **SFC** (HK) and **MAS** (SG) — the two hubs the audit shows are covered in
   name only
6. **DFSA** (DIFC) and **FSRA** (ADGM) — Dubai, the weakest focus hub at 3/7
7. **Seed file additions** — sovereign wealth funds (ADIA, ADQ, Mubadala, GIC,
   Temasek) appear in no financial register anywhere and no registry will ever
   reach them. Five lines in `seed_firms.csv` closes five focus-hub misses.
8. **Nasdaq Stockholm** participant list — same shape as `eurex`

Deferred with the deprioritized regions: BaFin (DE), FCA (UK), AMAC (CN), and
the US state-adviser tail. Each is a known gap with a written reason, not an
oversight — pick them up if the focus hubs run dry.

**Exit criterion:** `audit` reports no focus-hub miss without a written reason,
and every miss that a buildable source would fix is fixed. Item 7 is the cheapest
and should go first.

---

## Stage 4 — Layer 2, domain resolution

Registry `website` fields first — ~20,700 rows already carry one. Then
Certificate Transparency logs (`crt.sh`) for careers subdomains, then targeted
search for the remainder.

**Exit criterion:** ≥90% of firms in priority cities have a domain, or are
explicitly marked unresolvable.

---

## Stage 5 — Layer 2, ATS resolution

Fingerprint each careers host to `(ats, token)` by outbound link hosts, script
`src` domains, redirect chains and URL patterns. Cache permanently; re-verify
monthly, because a silent ATS migration is an invisible coverage loss.

**Exit criterion:** every firm with a domain is either resolved to an ATS or
assigned tier B/C. No firm left untiered.

---

## Stage 6 — Layer 3, ATS extraction

The eight global endpoint formats plus the Nordic group (Teamtailor, Talentech,
Varbi, Jobylon, Emply) — without the Nordic set Stockholm is not exhaustive.

**Workday must be handled explicitly:** `limit` above 20 returns an empty array
with HTTP 200, which is indistinguishable from "no jobs" unless asserted on.
This one gets a regression test, not a comment.

**Exit criterion:** jobs land in the database from at least one firm per ATS
format, and the Workday trap has a test that fails if the assertion is removed.

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
