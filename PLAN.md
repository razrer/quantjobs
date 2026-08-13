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

## Status

| # | Stage | Status |
|---|---|---|
| 0 | Employer universe — raw collection | done |
| 1 | Employer identity (entity resolution) | done |
| 2 | Coverage audit harness | **next** |
| 3 | Close audit-flagged gaps | not started |
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

## Stage 2 — Coverage audit harness

**The problem.** Coverage has been checked with ad-hoc `grep`s typed fresh each
time. That is not repeatable, and it is the direct cause of at least one
overstated claim about which firms were missing.

**Build.** The methodology's named roster (~130 firms across 11 hubs) as a
checked-in fixture, plus `python -m quantscraper audit` reporting present/missing
per hub, matched through Stage 1's resolution.

The roster is the *audit set*, never the universe — it measures coverage, it
does not define it.

**Exit criteria:**
- [ ] `audit` runs and reports per-hub hit rate
- [ ] every miss is either fixed or recorded in the README with a reason
- [ ] known-stale roster entries (IPM) are marked so they stop reading as bugs

---

## Stage 3 — Close audit-flagged gaps

Only now add sources, and only the ones Stage 2 proves are needed. Candidates,
in rough order: a hand-maintained seed file (AP1–AP6, Da Vinci), Nasdaq
Stockholm and Cboe Europe participant lists, Finanstilsynet (DK), BaFin (DE),
FINMA (CH), SFC (HK), MAS (SG), AMAC (CN).

**Exit criterion:** audit miss list is empty, or every remaining miss has a
written reason and an entry in `ACTION-REQUIRED.md` if it needs a human.

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
