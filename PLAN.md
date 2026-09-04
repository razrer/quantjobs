# Implementation plan

The acquisition methodology lives in
`C:\Users\razre\.claude\plans\snoopy-growing-hoare.md`. This file is the
*execution* order: what gets built, in what sequence, and — the part that was
missing — **how each stage knows it is finished.**

Collection was originally done opportunistically: probe a source, write an
adapter, commit, repeat. That produced working code but no answer to "is this
stage done?", so the stopping point was a judgement call every time. Every stage
below has an explicit exit criterion instead.

**Rule: do not start a stage until the previous stage's exit criterion is met.**
If a stage turns out to be blocked, record it in `ACTION-REQUIRED.md` and stop —
do not skip ahead to something more interesting.

**What each stage *learned* is in `CLAUDE.md`, not here.** This file records
what was built and what proved it; the gotchas belong where they are read every
session.

## Where it stands

**Stage 45 is the last one written down and every stage is closed**, so the next
unit of work is a decision rather than a queue: what to widen, what to measure,
or what to leave alone. `ACTION-REQUIRED.md` is empty of open items for the
first time — everything in it is settled and kept only so it does not get
re-asked. The standing sequence is one command, `python -m
quantscraper daily`, and `python web/publish.py` puts the result on the CDN.
Both are deliberately manual, because the search is the expensive half and it is
free on this machine.

Candidates, none of them queued:

- **Four sources still publish no description, down from six, and two of the
  rest are now known-closed rather than untried.** Jobvite, Breezy and Personio
  were fixed in Stage 45; ADP and BambooHR were probed properly and publish
  nothing on any public surface. What is left is `site` (694 postings -- the
  hand-written readers, each of which would need its own detail fetcher),
  `avature` (51), `join` (54) and `jobylon` (6). ~30 board cards between them,
  which is why none is queued.

- ~~**Five sources still publish no description and now have no excuse.**~~
  `bodies.coverage` prints a `0%` row for ADP (637 postings, 47 board cards),
  Jobvite (370/46), BambooHR (445/36), Personio (148/24), Breezy (191/19) and
  Avature (51/8). Both list endpoints that *look* like they carry prose were
  probed and do not: Breezy publishes no `description` key at all and
  Personio's is an empty string, so each needs a per-posting fetcher the way
  the other four did. ~180 board cards between them, against 1,651 for the
  four that were built — this is the tail, and the pattern is now established
  enough that the next one is an afternoon.
- **`withdrawn` is now the widest gate on the board at 30,522 postings**, and
  the number to re-read whenever a reader changes. It trusts that a board's
  newest `last_seen` is its last *complete* read, which holds only while
  `upsert_jobs` stamps one timestamp per board per poll. If anything ever
  starts writing `last_seen` per row, the gate silently inverts and the
  freshest posting on a board retires all its neighbours.
- **`solutions architect` is the one measured needle left on the table**, and it
  points the *keeping* direction rather than the rejecting one — see Stage 35.
  328 live titles; `ENGINEERING` is two-sided, so the missing plural costs a
  keep at RBC Capital Markets rather than merely a reason.
- **The reclassify clicks are a standing input now.** `corrections` pulls them
  off the live board into `labels.csv`; reading the `rejected` rows in bulk is
  what Stage 35 was, and it is worth repeating whenever a batch accumulates.
  The query is in that stage: join the hand labels to `job_tags`, keep the rows
  no gate removes.

- **Switzerland is the focus hub with the most unreached roster firms** (three
  of 41 absent from the universe; more present but unpolled). Closing them is
  per-firm hand work like `sites.py`, not another `discover` sweep — that sweep
  was re-run and re-confirmed rather than extending anything.
- **The ADP/UKG list has more on it.** Radancy 12 firms, HiBob 5, Talentsoft 4,
  JazzHR 3, Dayforce 3, Zoho 3, Cornerstone 2. Build down that list, which was
  measured, not down a list of vendors you have heard of — but **weight it by
  the firms on it first.** Avature was ninth at 3 firms and one of them was Two
  Sigma, which Stage 33 built for that reason.
- **The rest of the focus-hub miss list is per-firm hand work, and most of it
  has no board to find.** `audit --pipeline` names every one. Twenty-one Hong
  Kong firms were probed by hand in Stage 33: eight 404 on every careers path
  and most of the rest publish a careers page with no postings on it. The
  Swiss remainder is private banks. Neither is another sweep.
- **Two vendors are closed rather than pending**: Paylocity renders
  client-side and Jefferies' `tal.net` portal sits behind an Altcha CAPTCHA.
  **Eightfold was on this list and should not have been** — it answers 403 on
  Morgan Stanley's tenant and 200 with 219 positions on Millennium's, which is
  what "a closure is a claim about one tenant" means. Recorded in `CLAUDE.md`
  so neither is re-derived.
- **The sub-$110M US adviser tail has no source**, and neither does
  sponsored-access. Both are recorded as structural in `README.md`.
- **`job_tags` retention is broken by design** — the primary key omits `tagger`,
  so "compare two lexicon versions" is unavailable. Fixing it forward is a
  schema change; `prune` is the interim.

## Geographic priority

**Focus:** Stockholm, Copenhagen, Amsterdam, Switzerland, Hong Kong, Singapore.
**Deprioritized:** Germany, US, London/UK, China, Dubai.

Dubai was deprioritized after Stage 3. Its register is the one behind a CAPTCHA
so it could not be built anyway, and the roster firms that matter there are in
the universe through the seed file. It stays in the audit fixture and reports
with the deprioritized hubs.

This sets **what gets built next**, not what gets ingested. Data already
collected stays — `sec_adv` and `sec_bd` are 26,500 US rows and they remain,
because geography ranks results rather than gating membership, and deleting
employers is the one mistake this design refuses to make. The single exception
is the *board*, which gates on geography at the user's instruction; the database
is untouched and one line in `web/build_data.py` reverses it.

## Status

| # | Stage | Outcome |
|---|---|---|
| 0 | Employer universe — raw collection | done |
| 1 | Employer identity (entity resolution) | done |
| 2 | Coverage audit harness | done |
| 3 | Close audit-flagged gaps | done |
| 4 | Layer 2 — domain resolution | queue empty, every strong grade re-checked |
| 4b | Switzerland (FINMA) | 2,832 institutions |
| 5 | Layer 2 — ATS resolution | 19,821 domains tiered, none untiered |
| 6 | Layer 3 — ATS extraction | all formats landing |
| 7 | Layer 4 — JobTech JobStream (Sweden) | delta polling live |
| 8 | Silent-failure alerting | `alerts`, distributional |
| 9 | Layer 3B — tier-B change detection | 3,751 pages watched |
| 10 | Coverage measurement | measures, and refuses when it cannot |
| 11 | Layer 5 — job tagging | relevance 95.6%, no false rejection, containment 14/14 |
| 12 | Layer 6 — the board | card grid, facet rail, deadline-first |
| 13 | Layer 2C — board discovery | 23 boards, 989 postings |
| 13b | Platsbanken is not a census | 0 of 55 Stockholm employers are in it |
| 14 | Readers for recognised-but-unread ATSes | iCIMS + Pinpoint, 2,068 postings |
| 15 | The board, and the body it was reading | board unknowns 5,611 → 2,341 |
| 16 | The last ATSes, and Singapore | Jobvite/Varbi/Homerun read, MCF swept |
| 17 | The ATSes the focus hubs actually run | Oracle read, 26 boards |
| 18 | Stockholm and Hong Kong, firm by firm | `sites.py`, Stockholm 15/18 reached |
| 19 | Hong Kong widened, ATS table exhaustive | 51 HK firms, 26 ATSes, 20 read |
| 20 | Switzerland's national feed | job-room.ch polling |
| 21 | Denmark's job board | Jobindex enumerated, 17,541 of 17,542 |
| 22 | Widen Sweden | Jobbsafari swept, 4,582 → 52,755 postings |
| 23 | The lexicon in Swedish, Danish and Swiss | 208 needles, 11 heads, none touching a positive |
| 24 | Pure trading hides instead of showing | an `exclude` preset, like credit risk |
| 25 | Multi-location postings show in both places | `hub` multi-valued end to end |
| 26 | XVA and counterparty credit risk | 27 titles, no false positive |
| 27 | Read what the `rejected` gate removes | 720 reviewed, 1 false rejection |
| 28 | One command to refresh, one to publish | live at quantjobs.spawned.app |
| 29 | The board read back, in Swedish | a body arriving after the tag was never read |
| 30 | The Nordic board: one bucket held junk and misses | 23 ranked cards → 66 |
| 31 | Every hub read the way Stockholm was | ranked cards +21% across all hubs |
| 32 | The sixth gate: a board publishing no markets work | 906 cards, no ranked card lost |
| 33 | The marquee firms, one at a time | 145/253 reached, 1,258 postings |
| 34 | The board read as empty, and Singapore had stopped | pin takes the shortlist; 95,536 of 95,561 swept |
| 35 | The reclassify clicks, read as evidence | 40 unwanted cards → 23, no `relevant` card lost |
| 36 | Two fabricated links, and the rest of the IB desk | board 8,513 → 6,666, shortlist unchanged at 224 |
| 37 | Hong Kong: the national board is closed, so employers instead | 1,414 → 1,526 postings, 207 → 224 rated positively |
| 38 | The boards that resolved and polled silence | 167 silent boards read; 5 vendors opened; Millennium found |
| 39 | The classifier was starved, not wrong | board 6,120 → 4,459, unread 3,635 → 1,843, shortlist held |

---

## The stages

### 0 — Employer universe, raw collection

Registries behind one interface, each declaring a `MIN_EXPECTED` floor so a
silent breakage fails loudly.

**Exit (met):** more than one jurisdiction per region of interest, and every
fetch recorded in `runs`.

### 1 — Employer identity

One real company occupies up to four rows: Jane Street is in `sec_bd`,
`afm_nl`, `eurex` and `euronext`; Tower Research trades as `LATOUR TRADING LLC`.
Everything downstream multiplies on that — one domain resolved four times, one
feed polled four times, one job emitted four times. **This went before more
sources**, because each new registry makes the duplication worse.

`firms` is derived from `employers` on deterministic keys in precedence order —
LEI, domain, registry key (Swedish org number, SEC CRD), normalized name — plus
a small curated alias table for cases no key bridges. Normalization strips
*only* legal forms.

**Exit (met):** the collapse is measurable and re-runnable, and no curated alias
merges two firms the roster keeps apart.

### 2 — Coverage audit harness

Coverage had been checked with ad-hoc `grep`s typed fresh each time, which
caused at least one overstated claim about what was missing. Built
`quantscraper/roster.csv` and `python -m quantscraper audit`, matching through
Stage 1's resolution.

**Exit (met):** `audit` reports a per-hub hit rate; every focus-hub miss carries
a printed reason; stale entries (IPM) and never-real entries (AP5 — there is no
*Femte AP-fonden*) are marked and excluded from the rates.

Reporting one number per hub would have been misleading, which is why there are
two: **present** and **local**. Hong Kong was 9/9 present and 1 local.

### 3 — Close audit-flagged gaps

Universe 30,590 → 63,724 rows; `finanstilsynet_dk`, `mas_sg` and `sfc_hk` added.
`fi_se`'s category walk had covered 20 of FI's 495 codes and the omissions were
not all funds — Alecta is a *mutual* filed under `TJPÖMS`.

**Exit (met):** no focus-hub miss at all, and every miss a buildable source
would fix is fixed. The one source that would close a remaining *local* gap is
blocked on a human (DFSA).

### 4 — Layer 2, domain resolution

The focus-region registries publish no websites at all, so domains are derived:
guess candidates from the name, then accept only if the page **names the firm**.
Graded `registry` / `name-strong` / `name-weak` / `unresolved`, and only the
first two count. `fca.py` was added as a *website* donor, not a registry.

**Exit (met):** every firm reported by a focus-region registry has been probed at
least once, and the strong matches survive a manual read. The second half is
what produced the four false positives `README.md` records — one word is not
evidence, and evidence must not be circular.

### 4b — Switzerland (FINMA)

Diagnosed as "FINMA serves an incomplete TLS chain" and that was wrong: Windows
populates its root store lazily. `http.py` loads a full bundle from Git or
msys2. 2,832 institutions; Switzerland went 6/11 local to 9/11.

### 5 — Layer 2, ATS resolution

Domain → `(ats, token)` by fingerprint, else tier B (a readable careers page) or
tier C (nothing). **Exit (met):** every domain is tiered and `untiered` is zero
— 19,821 domains: 824 tier A, 3,839 B, 15,158 C.

Two `ats` runs stalled at 100% CPU for two and a half hours here, which is where
the bounded-regex rule came from.

### 6 — Layer 3, ATS extraction

One reader per format; postings land in `jobs`.

**Exit (met):** jobs land from at least one firm per implemented format, and the
Workday trap has a test that fails if the protection is removed. Lever was last
and is proven on a board the firm actually owns, independent of the Palmer
Square mis-attribution that taught "read the postings, not just the token".

### 7 — Layer 4, JobTech JobStream

**Exit (met):** delta polling works and a full re-read is never needed. Cold
start pulled 5,053 changes over 24 hours; the next poll, resuming from the
stored cursor in `feed_state`, pulled 133. The cursor rewinds ten minutes before
each poll — a duplicate costs an idempotent upsert, a gap costs a posting.

### 8 — Silent-failure alerting

`MIN_EXPECTED` only catches catastrophe: Finanstilsynet normally returns 26,495
rows against a floor of 15,000, so a parser returning 16,000 clears the floor
while having lost ten thousand firms. `alerts` is distributional over the `runs`
history instead.

**Exit (met):** breaking the Cboe parser live produced a named failure and exit
1; restoring it returned `all sources healthy` and exit 0.

### 9 — Layer 3B, tier-B change detection

**Exit (met):** every tier-B page has a baseline (3,751 of 3,839; the rest are
unreachable hosts), a change is detected and dated, and a page that only
reorders its links is not a change.

### 10 — Coverage measurement

**Exit (met):** coverage is measured where a second source exists, declines to
guess where one does not, and names the employers that reach us only through the
national feed.

### 11 — Layer 5, job tagging

The deterministic lexicon, the hand-labelled fixture and the scoring. Design and
method in `TAGGING.md`.

**Exit (met):** every posting carries a value in every dimension; relevance
95.6% on the hand sheet; **no false rejection** in it. `seniority` was added to
the bar at the user's request and is scored as *containment* — 14/14 labelled
leadership withheld, at a cost of 2 `adjacent` rows — because rung agreement
answers a different question badly.

### 12 — Layer 6, the board

**Exit (met):** the board sorts deadline-first under every sort, every tagged
dimension is filterable with a live count, and no filter or grouping can hide a
posting rather than rank it — with the deliberate exception of `GATES`, which
removes and says so on every build.

### 13 — Layer 2C, board discovery

The firms that matter were all tier B, because the careers walk settled on Jane
Street's overview page, a Cloudinary **image** for DRW and a **PDF** for Man
Group. No regex over the page we did fetch fixes that: guess the token from the
name and prove it against the feed.

**Exit (met for the roster sweep):** every active roster firm has either a
pollable board or a recorded reason it has none, and the reason is specific —
"54 probed over 6 tokens, 1 live board named another firm" is an answer; a
silent absence is not. 23 boards verified, 989 postings landed.

### 13b — Platsbanken is not a census

Publishing there is voluntary for private employers, so "every job advertised in
Sweden is published to Platsbanken" was false and "JobStream makes a hub
complete" followed from it. Measured: of the Stockholm employers reached through
their *own* board, JobStream carries **0 of 55** — a disjoint set, not a
shortfall.

**Exit (met):** no file claims Platsbanken is complete, and `coverage.blindspot`
prints the number that refutes it rather than remembering it. JobStream itself
is unchanged: it is a wide net, not a backstop.

### 14 — The ATSes we recognised and could not read

`ats.py` recognised 22 systems while `extract.py` read 11, so 88 boards sat tier
A with a token, counted as resolved, polling nothing.

**Exit (met):** 2,068 postings from 47 boards that previously returned nothing,
one board failed loudly rather than silently, and no tier-A row holds an
infrastructure token. Taleo, Jobvite, Varbi, Eightfold, Homerun and Join were
deferred **with specifics** — 41 boards, each with a named reason.

### 15 — The board, and the body it was reading

4,366 descriptions fetched, corpus re-tagged: corpus `relevance: unknown`
12,365 → 9,095, board postings with no verdict 5,611 → 2,341.

**Exit (met), and the last row is the point:** postings worth reading stayed at
60. Reading more bodies emptied the unknown bucket without inventing a single
new opportunity, which is what a backfill queue is supposed to do.

### 16 — The last ATSes, and Singapore

Three of the six remaining formats do publish a feed; the board page just never
says so. Varbi's `/{lang}/what:list/` answers *404 Unallowed call* and Homerun's
board is script-rendered — reading the page's own link shapes rather than
guessing paths found both. Jobvite was hiding a 50-posting cap behind a missing
trailing slash, and its own pagination text said so.

**Exit (met):** every recognised format either has a reader or a recorded reason,
and MyCareersFuture is swept through the listing endpoint rather than the search
one, which 418s from page 100.

### 17 — The ATSes the focus hubs actually run

Stage 13 found its work in a throwaway script — the same "typed fresh each time"
problem `audit.py` was written to end. `audit --pipeline` asks it properly, and
**present and polled are different properties**: `audit` alone reported 100%
present for all six focus hubs while 61/120 roster firms produced postings.

Oracle Fusion Recruiting was recognised by nothing at all. **Exit (met):** the
formats the focus hubs actually run are read, 26 boards resolved.

### 18 — Stockholm and Hong Kong, firm by firm

Asked for directly: get the named firms in the two most important hubs producing
postings, to at least 80%. **Every miss was probed by hand before a line was
written**, and that changed what the work was — the thirteen Stockholm misses
were not thirteen missing feeds but four firms with no ATS at all, one on an
unrecognised ATS, two saying outright they have no vacancies, one publishing to
LinkedIn only, two refusing us, and **two that had ceased to exist**.

Built `sites.py`, Layer 3C: hand-written readers riding Layer 3 as
`ats='site'`, each of which **raises** rather than returning `[]` when its
anchor is missing.

**Exit (met):** Stockholm 15/18, Hong Kong unchanged at 8/9, and every remaining
miss recorded as investigated rather than untried.

### 19 — Hong Kong widened, and the ATS table made exhaustive

Hong Kong went from 9 roster lines to 51, **every one verified against an
`sfc_hk` register row before being written**. Mining the register for a literal
quant word found 13 names and most were false hits; the working method was the
reverse — propose candidates, then verify each through `audit._matches`.

**The finding is that most small Hong Kong funds run no public board at all.**
All 51 were probed across every discoverable ATS and the sweep found two. The
rest hire through recruiters and personal networks.

**Exit (met):** `tests/test_oracle_hcm.EveryFingerprintHasAReaderTest` makes the
table exhaustive by construction — every name in `ATS_PATTERNS` must have a
reader or a recorded reason there is none.

### 20 — Switzerland's national feed

The blocker was our own URL: a 401 from one `/api/` too many, recorded for
months as a registered-API wall. The real path answers a bare unauthenticated
POST.

**Exit (met):** a poll lands Swiss postings with location, employer and
description, and the walk audits its own arithmetic against the advertised
total. Live run: **12,033 advertised, 12,033 collected** — where a single-ended
walk returns exactly 10,000 and reports success.

### 21 — Denmark's job board

Jobindex publishes its own result window (`max_page: 50`), so it is enumerated
through its own 81-subcategory taxonomy and the four slices bigger than the
window are **split again** rather than truncated.

**Exit (met):** a sweep lands Danish postings with employer, domain, location,
published closing date and description; the walk audits its arithmetic; every
oversized slice is split. Live: 100 slices over 1,207 pages, **17,541 distinct
postings against the 17,542 advertised**.

### 22 — Widen Sweden

Jobbsafari is Jobindex's Swedish sibling and shares none of its problems: one
unfiltered walk, no result window, robots-clean.

**Exit (met):** one walk lands every posting the board advertises and audits its
arithmetic against that total. Live: **48,173 over 99 pages against an
advertised 48,552** — 379 short on a two-minute walk during which 378 rows were
served twice, which is the index breathing rather than truncation.

The first attempt reported 5,421 postings cleanly, because page 11 returned 499
rows instead of 500 and the walk read that as the end. `MIN_EXPECTED` is what
announced it.

### 23 — The lexicon in Swedish, Danish and Swiss

**Exit (met):** every needle added was dry-run over every live title and **not
one touches a posting the tagger rates positively**. That is the check that
matters — a gate's head count says nothing about whether it ate something.

### 24 — Pure trading hides instead of showing

**Exit (met):** `Hide pure trader roles` is an `exclude` preset alongside `Hide
credit risk` and it hides without judging — the tag is unchanged, the facet
still ticks it, a crumb above the grid says what is hidden, and clicking the
crumb brings it back. Nothing leaves the database and no re-tag is involved.

### 25 — A posting open in two cities is in both

**Exit (met):** a multi-city posting carries one `hub` row per city, the board
counts it under each, and `off_location` fires only when **none** of them is
somewhere the reader would go.

### 26 — XVA and counterparty credit risk

**Exit (met):** dry-run over every live title and body — 27 matches, **every one
a bank markets-quant seat**, no false positive anywhere in the corpus. `cva` and
`ccr` are title-only, because in a body they are somebody else's initialism.

### 27 — Read what the `rejected` gate removes

**Exit (met):** twelve independent reviews of 60 postings each, drawn in two
near-disjoint passes from the frame where a false rejection could actually hide.
**One false rejection in 720**, and it was a real bug rather than a missing word.
Hand sheet 84.4% → 95.6%.

### 28 — One command to refresh, one to publish

**Exit (met):** the board answers on https://quantjobs.spawned.app with the same
posting count `build_data.py` last printed, and a second publish moves it. A
re-upload comes back as `RefreshHit` carrying the new bytes, so nothing has to
invalidate the distribution.

### 29 — The board read back, in Swedish

The cause was an ordering, not a vocabulary: `daily` ran `bodies` before `tag`,
and `bodies.targets` reads `job_tags` to find postings the tagger could not
place — so a fresh arrival was not in that queue at all and spent its first day
judged on a six-word title.

**Exit (met):** the Swedish and Danish postings on the board are ones a reader
would consider, and the nine genuine ones the same sweep carried are still on
it. Both halves pinned by tests.

### 30 — The Nordic board: one bucket held the junk and the misses

"Too much junk and too little jobs" was one fault: 176 of the 199 Nordic cards
were `relevance: unknown`, the bucket holding both the purchasers and the real
markets seats, so they sorted together. Emptying it from below (occupation
words) and from above (a markets-title branch) is the same repair.

**Exit (met):** four ranked cards under 176 unranked ones became **66 ranked
cards** — AP3's global equity managers, Swedbank's `Ränteförvaltare`, Nordea's
`[Assistant/Regular/Senior]` quant seat, SEB's FICC internship, Saxo's
electronic-trading trader.

### 31 — Every hub read the way Stockholm was

**Exit (met):** ranked cards per hub, lexicon 46 → 48 — Singapore 429 → 499,
Stockholm 58 → 70, Hong Kong 156 → 170, Amsterdam 29 → 33, Copenhagen 11 → 17,
Switzerland 37 → 39 with ten false positives removed from the top of the page.
Every needle dry-run over every live title, every promoted example read by hand,
every rule change pinned by a test.

**The frame mattered more than the vocabulary.** A hub reached only through firm
ATS boards is already a filtered population; a hub fed by a national board
carries every job in the country. Comparing the wrong pair wastes the pass.

### 32 — The sixth gate: a board that publishes no markets work

`non_markets_board` removes a posting when its board publishes no markets work
**and** the tagger could not read the title. It lives in `web/build_data.py`
rather than `tagging.py`, which is forced rather than chosen: a board profile
needs the whole board and `tagging.run` is incremental.

**Exit (met):** 906 cards removed, **no hub lost a single ranked card**, and the
shortlist unchanged at 95. Every build prints the count and the boards it
emptied, which is the audit substitute for `list --exclude` on a gate whose
evidence is not in `job_tags`.

**The sheet and the board still gate alike by construction.** This reason cannot
live in `tagging.GATES` where `labels.py` reads, exactly as `rejected` cannot,
and it needs no entry there: the sheet's frame requires `labels.anchored`, and
the markets-title branch added in Stage 30 runs last and converts any anchored
posting out of `unknown`. A row still at `unknown` therefore has neither. **If
that branch is ever moved, this stops being true.**

### 33 — The United States promoted, and two location faults it exposed

The user moved the US out of `deprioritized`. The numbers say it should have
been out already: **876 postings rated `adjacent` or better against 887 for all
six older focus hubs put together**, and New York alone carries 468.

**Three metros plus a residual, not one national hub.** `new_york`, `chicago`
and `boston` are focus; `us_other` is on the board and ranks below them, which
is what makes it unlike `sweden_other`. Measured: the metros hold 74% of the
positively-rated American postings in 27% of the volume. The Bay Area, Texas and
Miami stayed out on what their positives *are* — wealth advisers, tax
principals, real-estate capital markets.

**The location plumbing was wrong in both directions and nothing said so.**

- `_US_STATE` was `re.IGNORECASE` with a `\b`, so it claimed Bengaluru for
  Indiana, Berlin for Delaware, Casablanca for Massachusetts and `Dublin, Co.
  Dublin, Ireland` for Colorado 37 times. Uppercase and `(?![.\w])` now, with
  `IN` and `DE` off the list entirely and their American half named instead.
- `AR` and `NE` moved to the cantons: 235 postings on `, AR` and every one
  Appenzell, 419 on `, NE` of which 380 are Neuchâtel. The old rule that kept
  them American expired the moment both sides became focus hubs.
- 2,017 American postings **spell the state out** and read as `other`, which
  the board deletes. Plus 374 saying only `Remote US`.

**Exit (met), measured at lexicon v50 after the whole sequence had run:** New
York **4,840 postings / 508 positive / 119 relevant** — more `relevant` than any
other hub on the board, and more than the next two put together. Chicago
1,598/171/37 sits level with Hong Kong 1,312/190/36; Boston 1,061/84/16 sits
between Stockholm and Amsterdam. `us_other` 25,264/360/44, shown and ranked
below the metros. `deprioritized` is down to the 6,504 that are genuinely UK,
Germany, China and Dubai.

On the board: **New York 921 cards, Chicago 339, Boston 192, elsewhere in the US
1,628.** Every American needle dry-run over all 296,096 live postings; exactly
one touched a positively-rated posting (`environmental services` reaches an
equity research seat) and it was dropped.

### 34 — `N Locations` was never "unknown", and the board collapsed the rest

Two faults with one cause, both reported by the user.

**Workday's list endpoint summarises a multi-site requisition as `2
Locations`.** That is **8,004 postings, 58% of the whole `hub: unknown`
bucket** — not postings that named no place, postings that named several. The
detail endpoint spells them out in `location` + `additionalLocations`, and
`bodies.py` was already fetching that page for its description and discarding
them. It returns `Fetched(description, location)` now, with a second target
queue keyed on the placeholder. Only the placeholder is ever overwritten;
`Remote` deliberately is not.

**`index.html` grouped on `hub[0]`**, so a Stockholm-and-Copenhagen seat
appeared under Stockholm only — under *group by place*, the one view whose whole
question is "what is open in Copenhagen". Every `GROUP_KEY` returns a list now,
`GROUP_NAME` reads the key rather than `list[0]`, and `hubsOf` narrows to the
rail's selection so a filter and its piles cannot contradict each other.

**Exit (met):** 3,155 Workday postings resolved from a count to a real place
list, and **cards carrying more than one hub went 104 → 341** while `unstated`
fell 1,650 → 929. Verified in the browser against the rebuilt board: a
New-York-and-Chicago card renders under both places, the three non-hub
groupings still show it once, and filtering to one city no longer leaves a stray
one-member pile for the other.

**Resolving a place removes cards as well as adding them, and that is correct.**
~1,082 of the resolved postings turned out to be in India, the Philippines,
Poland or Brazil, and are now gated rather than sitting on the board as "we do
not know". Total cards 7,880 → 6,714 for that reason and the American occupation
vocabulary together.

**5,041 placeholders remain and 91% of them are by design:** 4,588 are already
gated for another reason, so the queue never fetches them. The other **453 were
queued and the fetch failed** — 404s and tenants that refuse — and they stay in
the queue for the next run, which is what makes the pass resumable.

**A postscript worth its own line: the fetch queue was a one-thread pool.**
`bodies` ran twelve workers over rows ordered `first_seen DESC`, which arrives
clustered by tenant — so with the throttle booked per host, the workers queued
behind one tenant's one-second slot and the run cost the *sum* of those
stretches. Observed live: **270 postings in half an hour**. `bodies._spread`
round-robins over hosts, longest same-host run **335 → 102**, roughly 90 minutes
to roughly 12. The floor is the largest board — 723 rows at one a second.


## Stage 33 — the marquee firms, one at a time

**The exit criterion:** every firm `audit --pipeline` named as a focus-hub miss
is either producing postings, or recorded with the reason there is no board to
find. Reached, not guessed at.

**What it was.** `audit --pipeline` reported 125/253 roster firms reached, and
the miss list was the roll-call this project exists for: Citadel, Citadel
Securities, Two Sigma, D. E. Shaw, DRW, Bridgewater, Renaissance, Northern
Trust, Wolverine, Headlands, Five Rings, Garda, Acadian, Teza, Magnetar,
Robeco. Every one of them was tier B or C — a careers page running on nothing
recognised — which is the blind spot `discover.py` was written for and could
not close, because none of these firms' board tokens is guessable from the
name and six of them had the wrong domain stored.

**Three different repairs, and only one of them was code that scrapes.**

1. **A regex gap, worth 29 boards.** The Greenhouse pattern matched
   `?for={board}` but not `/js?for={board}`, which is the shape Greenhouse's
   own snippet uses. Those domains resolved *tier A with a NULL token* — a
   board nobody polls, invisible to every sweep. Maven Securities alone was 39
   postings across three focus hubs. `job_app?for=` had to be admitted too, for
   GSA Capital.
2. **Nine boards found by hand and recorded as `sites.Site` rows with no
   reader** — the Nasdaq precedent. Two Sigma, Northern Trust, Bridgewater,
   Robeco, Wolverine, Five Rings, Headlands, Garda, Acadian, Teza, Magnetar,
   VivCourt. Each names an extractor that already exists, so none needed
   parsing; what they needed was the right page read once by a person.
3. **One new ATS and five hand-written readers.** Avature (Two Sigma, 50
   postings) is a real multi-tenant vendor whose board is the customer's own
   hostname. Citadel and Citadel Securities are read from the **career sitemap
   they publish for crawlers**, because every HTML page on both hosts answers
   403 while `robots.txt` says `Allow: /`. DRW ships its whole board inside
   `__NEXT_DATA__`; D. E. Shaw serves 86 cards on one page; Renaissance
   publishes twelve anchors.

**What it bought.** 1,258 postings from firms that were contributing nothing:
Northern Trust 637, DRW 160, D. E. Shaw 86, Citadel Securities 85, Citadel 51,
Two Sigma 50, Maven Securities 39, Wolverine 20, Five Rings 17, Bridgewater 16,
Robeco 14, Geneva Trading 13, Acadian 12, Renaissance 12, Garda 11, Teza 11,
Vatic 10, Headlands 7, Magnetar 3, VivCourt 3, 323 Trading 1.

GSA Capital is the one that resolved and added nothing: its board was already
being polled under `gsa-coral.com`, a sibling domain of the same group, so the
fix corrected the record rather than opening a feed. **A tokenless tier-A row
can be a duplicate of a board already reached under another of the firm's
domains** -- worth checking before counting a fix as postings.

`audit --pipeline` moved from **125/253 roster firms reached to 145/253**, and
the focus hubs from US 41/79 to **57/79**, Amsterdam 8/13 to **11/13**, Hong
Kong 18/51 to **21/51**, Singapore 9/10 to **10/10**.

**What it did not close, and why that is the answer rather than a gap.**
Twenty-one Hong Kong firms were probed by hand: eight 404 on every careers
path, and most of the rest publish a careers page with no postings on it.
Eightfold (Morgan Stanley), Paylocity (XR Trading) and Jefferies' `tal.net`
portal are each closed for a stated reason. Those are recorded in `CLAUDE.md`
so the next reader does not spend the afternoon again.

## Stage 34 — the board had grown and read as empty, and Singapore had stopped

**The exit criterion:** the postings the board rates highest are on the first
screen, and a source that dies says so. Both measured, not asserted.

**Reported as two faults and it was two, sharing one source.**

**"Very few jobs on the board."** The board had *grown*: measured against the
archived `board` branch, 5,211 cards on 21 August to 8,469 on the 27th,
`apply_now` 16 to 44, `strong` 79 to 180. Nothing had been lost. What had
changed was what stood in front of it. `order()` pinned any card with a
closing date inside the pin window above everything else, whatever the sort
said — and that rule was written when a closing date was **rare**, published by
JobStream and almost nothing else. MyCareersFuture publishes one on every row
and had become **1,777 of the board's 1,813 dated cards**, so the tie-break had
quietly become the ordering: **776 postings across 426 firm tiles above the
page, 763 of them Singapore, and 558 of them cards the tagger had never managed
to read** — `Admin Assistant`, `Desktop Engineer - Shift Based`, a Copenhagen
hotel night porter — sitting above all 224 cards rated `apply_now` or `strong`.

The rule promoted on the **absence** of a verdict, which is the board's own gate
rule read in a mirror. Requiring a verdict was the fix and was not sufficient:
at "worth reading" the block was still 83 tiles and 116 of its 118 postings were
Singapore, because a gate on evidence cannot rebalance a field 98% of which
comes from one place. At the reader's instruction the pin takes the
**shortlist** — 10 tiles, and the board opens on Flow Traders, Two Sigma,
Point72 and an `apply now` quant analyst. Nothing is hidden: an unpinned card
keeps its place in the chosen spine and `Closing date` still sorts purely by
deadline.

**"Singapore crashed when I swept."** It had, and three separate things kept it
quiet. `api.mycareersfuture.gov.sg` answers a sustained walk with HTTP 429,
`x-amzn-errortype: ForbiddenException`, and a header somebody typed:
`scrapper: contact us via the feedback form if you have legitimate reasons`.
`http._send` gave a 429 the same `2 ** attempt` schedule as a 503, so the whole
retry budget went in **three seconds**; the sweep died ~400 pages in having
written 37,562 postings. `_record_poll` runs *after* a sweep returns, so a
crashed sweep recorded nothing — and `alerts`, whose one job is noticing
silence, then printed **`all sources healthy`** with Singapore down. That is the
job-room.ch failure one step along: not a source nobody asked about, but one
that was asked and did not come back.

Four repairs, and one deliberate non-repair:

1. **A 429 gets its own schedule** — `Retry-After` honoured when sent (seconds
   or HTTP-date, clamped), otherwise 30s/90s/300s. A 5xx keeps `2 ** attempt`.
2. **`http.HOST_INTERVAL_S`** puts this host on one request per four seconds.
   Slowing down is what a 429 *asks for*. The user agent was not changed, the
   limit was not retried around, and the threshold was not probed for — those
   are evasion, and the header names the route the operators want instead.
3. **`cli._poll`** records `ok=0` for a Layer 4 sweep that raises, which is the
   contract `_fetch` has had for the registries since the beginning.
4. **A refusal ends the walk rather than throwing it away.** `Sweep.blocked`
   carries the portal's own sentence, and `problem` reports it **before** the
   shortfall arithmetic — a refusal reported as "truncation" reads as our paging
   being wrong when the portal has simply declined.
5. **`alerts.coverage` widened to the national boards.** It named only
   `REGISTRIES`, and `check` cannot judge a source with no rows — so a Layer 4
   source that had never run was invisible to the check *and* to the backstop
   written for that case. Both blind at once is how `all sources healthy` was
   printed for ten days.
6. **Not repaired, because it is not ours to settle:** whether to write to them
   via the feedback form they name. Item 5 of `ACTION-REQUIRED.md`.

**Proved rather than hoped.** A full sweep at four seconds ran **958 pages and
95,536 postings against the 95,561 the portal advertised** — 25 short, 0.03%,
inside tolerance — with no refusal in it, and wrote the **first MyCareersFuture
row `runs` has ever held**. That also paid the staleness debt the crash had run
up: what had looked like 54,159 rows of unknown status resolved to 29,262
genuinely withdrawn, only 1,800 of them still claiming a future deadline.
Backing off was the entire fix, and nobody had to find the threshold to do it.

756 tests, up from 732: the refusal path, the 429 schedule, the per-host
interval, and a source-level check that every Layer 4 poller goes through
`_poll` — a poller wired straight to its module is invisible when it crashes,
which is the state this whole stage existed to get out of.

## Stage 35 — the reclassify clicks, read as evidence

**The exit criterion:** every posting the reader hand-rejected is either off the
board or accounted for by a rule they asked for, and the change is measured
against the whole corpus rather than against the sheet it came from.

**A fixture that can only find one kind of error had been reporting no errors.**
`sample` draws its frame from `lexicon.judge`'s *contestable* rejections,
because a false rejection can only hide among postings that could plausibly be
in scope — and by that measure the tagger is clean: **zero false rejections in
152 hand-labelled rows.** The board's reclassify dropdown measures the opposite
direction and nothing had ever read it in bulk. 137 rows marked `rejected`, 62
of them new: **97 already gated, 40 still on the board.**

**Four families, and only two are bugs.**

**One — a markets word in a body switched the absence test off (19 of the 40).**
`lexicon.judge` step 9 rejects a posting whose title matched no list and whose
description never mentions markets. Its test read `markets_role or
markets_body`, so **one word anywhere in a description was enough**: Adidas's
`Part-Time Sales Consultants` and Fortum's `Balance Settlement Specialist` on
bare *trading*, Karolinska Institutet's `Projektadministratör` on *front
office* — a hospital's reception desk — a `Swedish Content Writer` on *market
data*, Accenture's `Service Now business architect` on *structuring*. The module
says three times over that `MARKETS` is a **role** list and this one call site
never acted on it. Steps 7 and 8 still read the body deliberately: there the
title has already been recognised, so the body corroborates rather than
supplying the only reading there is.

**Two — the English half of `_MANAGEMENT` had never been inflected (2).**
`Delivery Managers` escaped `delivery manager`, and `redovisningskonsulter`
escaped `redovisningskonsult` — the `Undersköterskor` lesson in the language the
list is written in. `managers`, `directors`, `leaders`, `supervisors` went in on
146 hits and one positive read by hand; **`partners`, `principals`, `presidents`
and `heads of` were measured and dropped**, three of them because the *reason*
would have been wrong even where the verdict was right — `CLSA Capital
Partners` is a firm's name and `Preschool Principals` is an occupation.

**Three — `discretionary_investing` (9), which is the reader's own standing
call** that markets seats which are not quant work rank rather than reject. 443
board cards ride on it, Point72 and Wellington among them. Unchanged, and
reversible in one line as `ACTION-REQUIRED.md` already says.

**Four — a markets word in the *title* of a back-office seat (5).**
`Fondadministratör`, `Backoffice Administrator - Mutual Funds`, `Reference Data
Specialist`. `desk_named` confers `adjacent` from a title word and caps at
`plausible`, which is the design; these sit at the bottom of the board rather
than in front of anything. Recorded, not changed.

**Measured over all 382,034 live postings, old tagger against new**, with the
harness proved first by running it against unchanged code (100 transitions of
drift, 0.026%, from bodies fetched after tagging):

| | net of drift |
|---|---|
| `unknown → rejected` | 2,504 |
| `adjacent → rejected` | 29 |
| `relevant` cards lost | **0** |
| postings leaving the board | 2,209 |
| hand-rejections fixed | 17 of 40 |

All 29 `adjacent` losses were read by hand: thirteen are one Singapore
recruiter's `HSBC Life Wealth Management Advisor` — insurance, on the exclude
list outright — and the rest are investor relations, wealth management and
Oliver Wyman's consulting grade ladder. **Not one is a quant posting.**

**One finding worth the next stage rather than this one.** A stricter step 9
amplifies every inflection gap in the lists above it: 61 of the 2,506 removals
reach it only because a plural was invisible one list earlier. In all but one
the verdict is identical and only the reason differs, so it was left — except
`solutions architect`, 328 live titles, whose list is *two-sided*, so the gap
costs a **keep**: `Solutions Architect, RBC Capital Markets` should reach step 7
with its anchor and falls off the end instead.

767 tests, up from 756.

## Stage 36 — two fabricated links and the rest of the IB desk

**The exit criterion:** every card on the board opens the advertisement it
claims to be, and investment banking is off it. Both measured.

**Reported as one card and it was two extractors.**

**"An ad from Nasdaq and Sun Life that just links to their entire recruiting
page."** `extract.workday` built its URL unconditionally —
`f"{origin}/en-US/{site}{path}"` with `path = externalPath or ""` — so an entry
Workday published without a path produced the board's own front door. **42
boards held exactly one each**: empty `job_id`, empty `title`, and a card that
opens a recruiting site. State Street, US Bank, DBS, Barclays and Airbus were
all in it.

The two halves are now handled separately, which is the whole fix: a posting
with a **title and no path** is kept with `url=None` — it is a posting, however
badly published, and principle 4 says classification is a read-time job — while
an entry with **neither** is not a posting at all. Nothing about it can ever be
read and there is no id to re-fetch it by, so creating a row for it is the
write-time mistake in its purest form. The 42 were retired with `removed_at`
rather than deleted; six rows with a real path and no title remain in `jobs` and
are held off the board by the new `untitled` counter in `web/build_data.py`,
which exists so the next extractor that does this cannot do it quietly.

**And a second one, found looking for the first.** **Every live SmartRecruiters
row had a NULL URL — 1,507 across all 12 boards.** `ref` is a dict of links on
some boards and a bare API self-link on others; where it is a string `applyUrl`
is null too, so both fallbacks resolved to nothing. The code carried a comment
saying `ref` came in two shapes and then gave up on the second. The public ad is
`jobs.smartrecruiters.com/{company}/{id}` — verified against the live board, not
guessed, and the title slug some boards append is optional.

**"IB jobs are not in scope."** Half of it already was: `investment banking`,
`equity capital markets` and `debt capital markets` had been on
`NON_QUANT_FINANCE` for a long time, which is why Rothschild's `Equity Capital
Markets - Associate` was off the board and why the family read as handled. The
gap was every IB title that does not spell the words, and **`corporate finance`
was the hole: 94 live titles, 19 of them on the board**, carrying three of the
reader's own hand-rejections. Twelve needles went in; all four of `corporate
finance`'s positively-rated hits were read and none is quant work.

**Three were measured and dropped, and two of them name markets desks rather
than banking coverage** — `origination` promotes LSEG's `Fixed Income
Origination` and Guggenheim's `UIT Trading & Origination`, and `corporate
banking` is on `MARKETS` deliberately with 89 positively-rated titles. The third
is `m a`, the folded form of `M&A`: 173 titles against 29 for `mergers`, with
four positives that could not be accounted for by reading the title. **A
two-letter needle is the `AQR` and `tbe` shape** — it finds something, and what
it finds cannot be checked by eye.

782 tests, up from 756 at the start of Stage 35. `tests/test_smartrecruiters.py`
is new.

**Measured on the rebuilt board, Stages 35 and 36 together:**

| | before | after |
|---|---|---|
| cards | 8,513 | **6,666** |
| firms | 1,515 | 1,137 |
| **worth reading** | **224** | **224** |
| `rejected` gate | 104,710 | 108,014 |
| hand-rejections still shown | 40 of 137 | **22 of 137** |
| `labels.csv` relevance | 71.7% | **83.6%** |
| false rejections in `labels.csv` | 0 | **0** |

**The number that matters is the one that did not move.** A fifth of the board
came off and the shortlist is unchanged at 224, which is what "the junk was
removed and the work was not" looks like from outside. The hand sheet's
agreement rose twelve points with **no false rejection in it at either end** —
the exit criterion `TAGGING.md` sets, and the reason tightening was safe here at
all.

False rejections in the *machine* sheet went 24 → 34, and that is the honest
cost. Reading all ten new ones: eight are retirement-plan administrators, tax
specialists, a Slack administrator and a P2P lender's relationship officer, and
**two are arguable** — `Summer Internship 2027` at Pareto Securities, a Nordic
investment bank whose title says nothing else, and `Broker Public Debt Desk`,
where `broker` is deliberately off `MARKETS` because 59 of its 61 hits are
insurance. Both were graded by the machine rather than by the reader, and
`TAGGING.md` already says why that sheet cannot be the criterion.

**The two URL fixes need no migration.** `db.upsert_jobs` sets
`url = excluded.url` unconditionally, so the next `jobs` poll backfills all
1,507 SmartRecruiters rows. The 42 Workday ghosts are already retired.


## Stage 37 — Hong Kong's national board is closed, so the answer is employers

**The question was the right one to ask and the answer is no.** Singapore's
statutory portal is the board's largest source, so Hong Kong's equivalent was
worth finding. It exists — the Labour Department's **Interactive Employment
Service** — and its `robots.txt` ends `Disallow: /`, names `/0/api/*`
separately, and allow-lists about forty paths of which the only sector pages
are elderly care, catering, retail and construction. **The exact inverse of
MyCareersFuture**, which says `Disallow:` and points at a sitemap. The rest was
measured rather than assumed: `hk.jobsdb.com` disallows `*?` and `*/job/`;
**`efinancialcareers.hk` and `ctgoodjobs.hk` answer HTTP 405 to every path
including their homepages**, eFC's own advertised job sitemaps included;
`recruit.com.hk` pages by ASP.NET postback and publishes no hitcount, so a
sweep of it could not be checked for truncation; and `jobmarket.com.hk`, the
one board that is open, enumerable and states its own total, **is 3,639
postings in total**. `data.gov.hk` has no vacancy dataset. Written up as
`ACTION-REQUIRED.md` item 6, because overriding a `Disallow: /` is the user's
call and the Jobindex argument does not transfer to it.

**So the supply had to come from employers, and the largest gap was structural.**
`sfc_hk` enumerates licensed *corporations* under the SFO. **An exchange
controller and a central bank are neither**, so HKEX and the HKMA were absent
from a universe of 79,225 firms while running live boards. HKEX hid twice over:
its careers page is on **`hkexgroup.com`** while the firm's site is
`hkex.com.hk`, so a walk that starts at the domain never reaches the hop that
names the board. Both are seeded now and on the roster.

**Five boards added, three of them needing no parsing:**

| Firm | Board | Postings |
|---|---|---|
| HKEX | Workday `hkex\|wd3\|HKEXCareerPage` | 164 |
| HKMA | own vacancies table, with its own closing dates | 14 |
| Pandtong Quantitative Research | own page, read in English | 13 |
| Capula Investment Management | Workable, via the *correct* domain | 12 |
| Anatole Investment Management | own page | 2 |

**HKEX's 164 postings would have been deleted rather than added.** Its board
writes the office rather than the city — `HK-TWO ES 11/F`, `HK-TKO 5/F` — so
every one matched no needle in `_HUBS` and read as `other`, which the board
gates. `_HK_SITE` is the handle, anchored on the raw location like the canton
and state patterns and dry-run first: **no live posting in the corpus wrote a
location beginning `HK-`**, so it can claim nothing already read correctly.
Three tests pin it.

**Four roster firms had somebody else's domain, and one was dangerous.**
`capula.com` is **Capula Ltd, a Staffordshire engineering contractor** with a
live careers page; the hedge fund is `capulaglobal.com`. That row sat at tier
B — which is exactly what `ats --regrade` re-walks — so it was one promotion
from polling an engineering board under a hedge fund's name, the `acadian.com`
failure before rather than after. `ortus.com` is a Spanish gym-equipment maker,
`liquid.com` the crypto exchange Quoine, `panview.se` a Swedish image supplier,
`trivest.com` a US private-equity firm. All five were `name-weak` matches.

**`discover` could not sweep a hub at all, and scoping it was only half the
fix.** `--source` was added because Hong Kong's firms are almost all SFC-only
and `source_count DESC` sorts them behind 27,314 others. Scoped, that ordering
stops meaning "an operating company rather than a fund share class" and starts
meaning "a multinational": the first HK sweep probed **ING, Societe Generale,
Intesa Sanpaolo, Natixis, RBC and Bank of China — 50 firms, 0 boards, not one
of them a Hong Kong company.** Scoped sweeps order by `row_count` now, and the
corrected queue leads on BFAM, Arkkan, Argyle Street and Aspex.

**And Workable had to be slowed down.** A discovery sweep asks ten vendors
about every candidate token, which from Workable's side is one client asking
about thousands of boards that do not exist; it began answering 429 and kept
answering it for unrelated reads of a board that does exist.
`http.HOST_INTERVAL_S` gains its second entry, at the same conservative four
seconds and for the same reason — the rate was not probed for.

**Exit (met):** Hong Kong **1,414 → 1,526 live postings and 207 → 224 rated
`less_relevant` or better**, with the hub's two largest employers reachable for
the first time. **Attribution, because the tagger moved 50 → 52 under a
concurrent session's lexicon work as well as this stage's:** the 112 extra
postings are exactly HKEX's 98 plus the HKMA's 14, and **15 of the 17 extra
positives come from the boards added here** (HKEX 12 `adjacent` + 2 `relevant`,
HKMA 1 `adjacent`). The rest of the session's five boards land in `hub:
unknown` — Pandtong and Capula state no city and `unknown` survives the gate,
which is the intended behaviour rather than a miss.

The long tail is confirmed empty by a second measurement rather than assumed:
probing the unreached roster firms by hand again found Janchor, Nine Masts,
Oasis and Blue Pool serving one SPA shell for every path and Ovata saying *No
positions available* in as many words — the same answer Stage 33 got from
twenty-one of them.

**One known miss, deliberately not fixed here.** Pandtong's `Machine learning
researcher` reads `unknown` and its `Python Developer` reads
`pure_engineering`, because the titles carry no markets word and the rules are
title-first — correct in general and wrong at a quant fund. **This is the case
`lexicon.board_profile` exists for** and the note in `CLAUDE.md` already says
so: reach for the board's profile before widening `MARKETS`. It was left alone
because another session was editing `lexicon.py` and `tagging.py` at the time,
and a lexicon change costs a `TAGGER` bump and a full re-tag.

**Unfinished:** the corrected `discover --source sfc_hk` sweep **died at 51 of
300** without writing its summary. Its work is durable — `discover.run` commits
every 25 — and `board_lookups` excludes what it already probed, so re-running
the same command resumes at firm 52. It verified **Cohen & Steers Asia** (27
postings, polled and tagged). It is slow, roughly two minutes a firm behind the
Workable throttle, and the yield so far is one board in fifty-one:

```bash
python -m quantscraper discover --source sfc_hk --limit 300 --workers 8
```

Then `jobs`, `tag`, and a rebuild.


## Stage 38 — the boards that resolved and polled silence

**The exit criterion:** every tier-A board holding no postings has a reason on
the record — a fix, a correct empty, or a named blocker — and nothing is left
reporting "empty" when it means "broken".

**The population nobody was looking at.** `reprobe_targets` covered tier B and
tier A with a NULL token, the two states `CLAUDE.md` calls "a board nobody can
poll". It missed the larger one: **167 rows tier A *with* a token and no
postings**, invisible to every sweep because having a token is what both other
clauses test for. Probing all 167 by running their own extractors is what
produced everything below; the diagnosis was never in the database.

**Four reader bugs, each silent by construction.**

- **UKG serves its tenants from two hosts** and the reader addressed one.
  Eight boards 404'd forever — and **every one had `recruiting2` written in its
  own stored evidence.** Mesirow and Calamos, both Chicago.
- **Oracle stops on an empty page, not a short one.** Its API serves the
  occasional 199-row page mid-board, so the short-page stop truncated Kotak at
  **3,199 of 9,959** and Tata Capital at **1,599 of 5,542**.
- **Oracle's shortfall check had no tolerance for churn**, so BNY advertising
  1,390 and handing over 1,387 raised — **discarding 1,387 real postings.** The
  guard against silent truncation producing the loud version of the same loss.
- **A migrated iCIMS board answers 200 with a 150-byte redirect script**, which
  the reader read as an empty board. Twelve of 36 were in that state.

**Six vendors were recorded as closed and five were not.** Each closure had
been generalised from one firm's board on one endpoint, which is what made them
expensive — the note gets read instead of the endpoint. Eightfold answers **per
tenant** (403 at Morgan Stanley and NAB, 200 at Vale and Millennium);
SuccessFactors' dead end was the `?company=` surface rather than RMK on the
firm's own host; Emply, Jobylon and Join each publish the list in the page
their own board loads. Only **Taleo** survived, and its rows are dead hosts
rather than a closed vendor. Paylocity and Jefferies, recorded separately, are
genuinely closed.

**Millennium is the find.** `mlp.eightfold.ai` holds **219 postings** — 70 New
York, 36 London, 31 Hong Kong, 15 Singapore — carrying `Quantitative
Researcher`, `Portfolio Researcher`, `Deep Learning Quantitative Researcher`
and `Quantitative Developer` seats across four focus hubs. The domain is
registry-sourced (Form ADV names `mlp.com` for MILLENNIUM MANAGEMENT LLC), so
this is not the `acadian.com` shape; the postings corroborate it independently.

**Measured.** Oracle went from 6,242 postings to 26,031 and UKG from 934 to
1,244. Six new readers — `emply`, `icims_cs`, `successfactors`, `jobylon`,
`eightfold`, `join` — landed boards that had never produced a row, and
`successfactors` alone is 5,829 postings from 34 of them. **Taleo is now the
only fingerprinted ATS without a reader**, down from six. Test count 823 → 872.

**Nothing on the board asked whether a posting was still listed.**
`web/build_data.py` selects on `removed_at IS NULL`, and only `jobstream` ever
writes that column — so a posting whose board stopped listing it stayed on the
page for as long as the database did. Two gates now, and they run *before*
every classification gate, because "is this still on offer" is prior to "is it
wanted" and attributing a withdrawn ad to `rejected` would overstate the one
gate this project already says to watch most carefully.

**The rule reads no clock, and that is the design.** "Older than N days" fires
on the *absence* of evidence: it empties the board whenever a run was simply
not made, which is the one thing every gate here is forbidden to do. `withdrawn`
compares a posting against **its own board's last complete read** and against
nothing else. That comparison is exact rather than approximate because
`db.upsert_jobs` stamps one timestamp per call and `extract.run` calls it once
per board — so a board's newest `last_seen` *is* its last complete read, a
failed or empty poll moves nothing, and a partial `jobs --limit` run is safe
because each board's answer is independent.

**Layer 3 only, and that restriction is the safety argument.** `jobtech` is a
delta feed and `jobindex --since` tops up from where the data reaches, so on
those sources "absent from the latest poll" describes most of a live board —
the same rule there would empty Sweden and Denmark. `LAYER_THREE` is derived
from `extract.EXTRACTORS` rather than restated.

**Measured:** `withdrawn` removes **30,522 of 138,961** live Layer 3 postings —
JLL, Citi, TD and US Bank each turning over 40–50% of a three-thousand-posting
board across three weeks. `retired_board` removes **4**, and is not a small
rule for that: it is the precondition for ever moving a board, because a board
nobody polls never reports a withdrawal.

**Which is what let SIG move.** Both iCIMS surfaces list the same ~250
postings; the classic portal publishes **no location and no description on any
of them** while the career site publishes both on all 250 — and the board gates
on geography, so a marquee firm's whole board was arriving as `hub: unknown`.
Aon, Insight Global and Johnson Financial moved for volume instead: their
portals hold one posting, zero and zero against 1,058, 96 and 28.

## Stage 39 — the classifier was starved, not wrong

**The exit criterion:** the largest bucket in the tagger has a diagnosis backed
by a comparison rather than a count, and whatever that diagnosis names is
either built or recorded as refused with the measurement that refused it.

**The diagnosis was written down long ago and read backwards.** `CLAUDE.md`
said the `unknown` bucket "is a vocabulary gap, not a broken rule", on the
evidence that *6,604 of 6,852 had no body at all* — which was taken to mean a
body would not have helped. The number that settles it is a comparison the note
never made. Across every live posting in a board hub:

| | postings | still `relevance: unknown` |
|---|---|---|
| with a body | 214,963 | **1.0%** |
| without a body | 60,455 | **9.3%** |

A ninefold difference. The tagger's biggest bucket is a **data** gap.

**On the board it was 63% of the problem.** Of 3,635 unread cards, 2,298 had no
body, and their sources were SuccessFactors 991, Oracle 430, Workday 282,
iCIMS 230 — and **only Workday had a fetcher**. Each of the other three
publishes the description on a per-posting resource nothing had asked for:
SuccessFactors as `itemprop="description"` microdata, iCIMS as a schema.org
island inside the `?in_iframe=1` frame it already serves its *list* from,
Oracle through `recruitingCEJobRequisitionDetails`. SmartRecruiters was a
fourth found the same way — 1,757 postings, zero bodies, one API call each.

**Three of the four publish the place there too, and that mattered as much.**
747 of the board's 941 placeless cards simply had NULL in `location`: past the
geography gate, correctly, and rankable by nothing. iCIMS' classic portal names
a location nowhere at all; seven SuccessFactors boards — Scania, DekaBank,
NordLB, BayernLB — publish no location column. `_UNRESOLVED` was written
against Workday's `N Locations` and had to learn that **an absent location is
the purest placeholder there is**: it protects a *stated* place from being
overwritten, and an absent one has nothing to protect.

**The word list was the obvious answer and the measurement refused it.** The
non-English titles in that bucket are one European truck-dealership network's
mechanics and apprentices, and the German compound heads dry-run clean at
scale: `-installateur` 3,517 live titles, `-mechaniker` 1,234, `-monteur` 855,
`-techniker` 678, none touching a positively-rated posting. **Their board
impact is 1, 4, 3 and 1 cards** — the other 3,500 are already rejected on
evidence somewhere else. *Pick the frame before believing a yield*, in the
mining direction as well as the fingerprinting one.

**What the corpus does want from that family is the contract, not the trade.**
`Lehrstelle` and `Lernende/r` were already `STUDENT_PROGRAMME`; their four
translations were not — `ausbildung` (332 live titles, replacing three
qualified forms), `lehrling`, `alternance`, `apprenti`, `aprendiz`,
`vocational trainee`. Bare English `apprentice` stays out on the reason rather
than the count: it reaches Euronext's `Treasury Apprentice`.

### The employer, read in the direction nothing read it

**`lexicon.board_profile` was measured, wired to a gate, and only ever allowed
to say no.** `non_markets` removes a posting; `markets` was computed on every
build and consumed by nothing. So a board this project has read hundreds of
times and found quant work on could lend none of it to the posting beside it —
and that is exactly the posting that needs it, because **94% of the postings
rejected as `pure_engineering` at a pure quant shop have no body at all**.
Citadel Securities' `Machine Learning Researcher`, `Deep Learning ML
Researcher` and `Research Engineer` read `unknown`; DRW's `Software Developer
(Research)` and `Software Engineer, Research – Cumberland Systematic` read
`rejected`. Neither is a lexicon failure. There is nothing in either posting to
read.

`tagging.quant_boards` is the other direction, and the evidence is **a quant
title counted over the board** — `_QUANT_CORE` or `_QUANT_CORE_TITLE`, a pure
function of `jobs.title`, so it cannot feed the tagger its own output, and it
costs 17s over 419,475 titles. At `floor=2, share=5%` it selects 77 boards and
the list reads as a directory of quant firms: Point72, SIG, Jane Street, Tower
Research, Citadel, DRW, Jump, Squarepoint, Two Sigma, Man Group, Schonfeld,
D. E. Shaw, Old Mission, Virtu, Millennium, Flow Traders, Akuna, AQR, Voleon,
Gelber, OTC Flow, Wolverine, Geneva Trading, Tudor, Mako, Eagle Seven.

**The second list is one a board may use where a posting may not.**
`_QUANT_CORE_TITLE` names a domain rather than the work, which is why a single
posting needs a qualifier — `Credit Risk Quant` is quant work and `Credit Risk
Operations (Debt Collections)` is a collections job. Over a whole board that
averages out, and it is the difference between recognising a firm and not:
**Gelber Group is 16 quant-domain titles in 19 and zero `_QUANT_CORE`.**

**The share is the half that keeps the banks out.** An absolute floor alone
admits Citi (126 quant titles in 3,724 postings, 3.4%), Barclays 2.8%, LSEG
2.1%, RBC 2.0%, State Street 1.9%, BNY 1.3%, Santander 1.1%, US Bank 1.0%,
DBS 1.0%, TD 0.9% — boards 98% retail banking. It is the mirror of
`board_profile`'s own argument for `non_markets`, where the absolute floor is
the protection.

**Both branches fire only when the posting has no body**, and that is the whole
safety argument: a description naming markets nowhere is evidence measured over
a document, so Jane Street's `MacOS Software Engineer` stays rejected.
`_SOFTWARE_SPECIALTY` is untouched — on the same boards the 124 postings it
rejects are cybersecurity, network, SRE and Salesforce work, every one
correctly. And `_fit` notches whatever this confers one bucket down, because a
relevance read off the employer is weaker than one read off the posting's text.

### Three defects the shortlist read found

**Recruiters at the top of the board.** The desk ladder's third rung was a
hole: an unambiguous quant word switched the demotion off entirely rather than
capping it, so `Quantitative Campus Recruiter` at SIG, `Campus Recruiter,
Machine Learning and Quantitative Research` at Jane Street, `Senior Recruiter,
Quantitative Research` at Voleon and `Experienced Quantitative Investing
Recruiter` at Two Sigma all read `relevant`. **A recruiter does not live next
to a trading desk; a recruiter lives in HR.** Eleven live titles carry a
corporate function and an unambiguous quant word, ten are recruiters and the
eleventh is Northern Trust's `Director Quantitative & Index Product Marketing`
— unanimous, which is what makes it a rule rather than a patch.

**`erfaren` was a rank and `experienced` was not.** 1,463 Swedish and Danish
titles graded `senior_6_10` since the table was written; 478 English ones
graded by nothing, 225 of them `unknown`, so `Experienced Options Trader` at
Akuna and `Experienced Trader` at Gelber sat at `apply_now`.

**A doctorate in the title, and this one reverses an earlier reading.** The old
note said bare `phd` must never gate, on the evidence that 220 titles carried
it and 29 were rated positively — **and those 29 were never read**.
Re-measured: 437 titles carry a doctorate, 71 are rated positively, and 69 of
the 71 name a doctorate and no lesser degree. Two at `apply_now`, six at
`strong`, on a board for a reader who has none. The head count was never the
test.

### And two the rebuilt board found

**A department must never rescue a role, which is the mirror of the rule that
it must never reject one.** `desk`, `management`, `software` and `corporate`
are read from the title, correctly, and each was compared against a quant word
read from title *and department* — so a department called *Quantitative
Research & Trading* switched the rejection off. Thirteen live postings carry a
quant word there and none in the title beside a title-level rejection, and
**four were in the board's top two buckets**: Vatic's `Trading Operations
Specialist` at `apply_now`, and D. E. Shaw's `Product Manager - AI Vendor
Tools`, `Technical Product Manager - Macro` and `Systems: Cloud Engineer` at
`strong`. That is the fourth time this project has found a needle list read
against text it did not mean.

**`china` claims Hong Kong.** 89 live postings match both `hong_kong` and
`deprioritized` on the strength of one word — `Hong Kong, SAR, China` is one
place, not two. It gates nothing and it files a focus-hub card under
*Deprioritized* as well, so group-by-place shows it twice. `_RESIDUAL_OF`
already has the shape for this and `deprioritized` was outside it because it
spans four countries; `china` is the one needle on it that contains a focus
hub, so it goes in with a country-word set of exactly that word. `Hong Kong;
Shanghai` and `Amsterdam; Frankfurt` both keep their second place.

### What it did

| | before | after |
|---|---|---|
| board cards | 6,120 | **4,459** |
| of those, `relevance: unknown` | 3,635 (59%) | **1,843 (41%)** |
| board cards with no place at all | 941 | **251** |
| "worth reading" | 220 | 198 |
| body-less postings still `unknown`, in board hubs | 9.3% | **5.2%** |
| hand sheet relevance | 84.9% (129/152), 0 false rejections | **unchanged** |
| seniority containment | 14/14, 0 openings lost | **unchanged** |

**The number that should not have moved did not.** Of the 216 cards that were
`apply_now` or `strong`, **194 are still there**, and every one of the 22 that
left is attributable to a named rule: eight PhD-required seats gated (Citadel
×3, Citadel Securities ×3, Old Mission, Five Rings, D. E. Shaw), six
`Experienced Trader` postings demoted to `plausible` (Gelber, Akuna, DV), two
recruiters demoted, `Systems: Cloud Engineer` and `Trading Operations
Specialist` demoted by the department fix, and one German economist gated once
its location arrived. **No unexplained loss.**

**At the firms that matter it is a different board.** The `unknown` bucket went
to **zero** at DRW, Citadel, Citadel Securities, D. E. Shaw, Millennium and Two
Sigma, and their rejection rates fell with it — DRW 52% → 27%, Citadel
Securities 33% → 16%, Citadel 23% → 12%. Millennium's positively-rated postings
went 78 → 124.

**`board_triage.csv` barely moves, and that is the right answer.** Precision
over its 1,866 read cards goes 38.6% → 39.1% and **keep recall is unchanged at
84.3%** — no keep was lost. The sheet covers Singapore, Hong Kong and Stockholm,
and `CLAUDE.md` already records that Singapore's `unknown` is a vocabulary gap
rather than a missing body: only 8% of its cards lack a description. It is
precisely the population this stage does not address.

### Two diagnostics that did not exist

Both read `job_tags.evidence`, which every relevance tag has carried since the
beginning and nothing had ever grouped by.

**Needle leverage** ranks the board's positively-rated cards by the phrase that
decided them, which is a ranking by *leverage* rather than by volume — it says
which single needle is doing the most unexamined work, rather than which is
most common. It found `title 'trading', 'trading'` at 351 live postings: a
two-sided test satisfied twice by one word, because bare `trading` is on
`_QUANT_ADJACENT` *and* on `MARKETS`. **Measured, it is inert** — all 351 fall
through to the markets-title branch, which fires on the same word and confers
the same `adjacent`. The evidence string is wrong and the verdict is not.

**Verdict consistency** asks which folded titles hold both a positive and a
rejection, because that difference has to come from somewhere other than the
title. **Eight do, and every split is evidence**: `software developer` is
rejected at 96 firms and `adjacent` at DRW on the board profile, `applied ai
engineer` is `adjacent` at Millennium and rejected at DBS and a VC fund,
`machine learning engineer` is carried by *trading* in Jane Street's own title.
Nothing is split by accident.

### Measured and refused

- **The source taxonomy as a *positive* signal.** The best category in the
  corpus is MyCareersFuture's `Banking and Finance` at **7.7%** positively
  rated over 2,690 postings; everything else is under 5%. Promoting on it
  would add ~2,500 cards to buy ~200 — and it is unnecessary, since that
  category holds only 95 `unknown` rows out of 2,690.
- **`lexicon.judge`'s discarded `keep`.** `tag_posting` consumes only
  `reject`, which is a real asymmetry in a three-verdict module — and it is
  267 postings, half of them a firm's self-description rescuing a title
  `_SOFTWARE_SPECIALTY` had just rejected (`Network Engineer + low latency
  trading`). Measured again on the ground most favourable to it — the 77 quant
  boards, where **393 postings still read `unknown` and every one has a real
  body** — judge keeps `HR Analyst`, `Fund Reporting Associate`, `Storage and
  Backup Engineer` and `Database Support Engineer`, all on the two words
  *systematic investing* in Point72's description of itself. That is the same
  evidence that makes `not has_body` the right guard on the employer rule.
- **Widening `non_markets_board` to catch boards with no keeps at all.** 71
  `mixed`-profiled boards have zero postings read as markets work and
  contribute 569 board cards, all `unknown` — Exponent, Arkema, Atos, Royal
  Caribbean, Volvo, AkzoNobel. Tightening the profile reaches them, and it
  also reaches DekaBank, Allspring and Vitol, which are real markets firms
  with small boards. **Fetching the bodies removes the same cards on the
  posting's own evidence**, which is the direction this project prefers, so
  the gate was left alone.

## Stage 40 — Hong Kong's national board, opened

**Exit criterion:** the territory's statutory board is enumerated and the sweep
can prove it read all of it; every judgement call previously parked in
`ACTION-REQUIRED.md` is settled.

**Stage 37 answered "is Hong Kong's national board readable?" with "it is
closed", and the reader has since said to read it anyway.** That reverses the
*decision*, not the measurement: the `robots.txt` still ends `Disallow: /` and
that is still the exact inverse of MyCareersFuture. What changed is the
project's standing policy, now written down in `CLAUDE.md` under *How this
project crawls* — robots is not honoured, the compensation is rate, and **bot
detection is a different question that stays closed**. Dubai's reCAPTCHA,
Jefferies' Altcha, Quantlab's 403 and the two Hong Kong boards answering HTTP
405 are refusals of *this client*, and getting past them means completing a
challenge or pretending to be a browser. None of that moved.

### What was built

`quantscraper/iesjobs.py`, `python -m quantscraper hongkong`, weekly in
`daily --full`. `www2.jobs.gov.hk` at one request per four seconds — slower
than this project's own default — 715 requests, about 48 minutes.

**It enumerates, which is what makes it checkable.** No result window, unlike
Jobindex's 1,000 and job-room.ch's 10,000: 14,287 postings over 715 pages of
20, page 715 short at 7 rows and page 716 empty. Every page prints
`Results 1 to 20 of 14,287`, and the sweep compares what arrived against it —
a **missing** hitcount fails rather than passes, which is the `X-Total-Count`
lesson.

**Two facets, one measurement, two answers.** Walking a facet instead of the
raw list hands every posting the portal's own classification — the signal
`jobs.category` exists for, and the one `_MCF_OFF_INDUSTRY` and JobStream's
`occupation_field` both prove is worth more than a word list. Whether that is
safe is arithmetic:

- **27 industries sum to 15,175 against 14,287** — a posting carries several,
  so the slices *cover* rather than partition, and one classified under none
  would be absent from every slice while the total still looked right.
  Refused.
- **29 job types sum to 14,287, delta zero** — an exact partition. That is
  what the walk enumerates.

The cost is ~4%: the same 715 pages of postings, plus one first page per
slice. **The gain is not only the label, it is a stronger check** — an
unfiltered walk has one published total to audit against and this one has
thirty, each slice against its own hitcount and the union against the whole
board. That union check is what re-proves the partition on every sweep rather
than trusting today's measurement forever: a posting in two slices arrives as
a repeat, a posting in none as a shortfall.

**Proved on the live board, not only in the hitcounts.** The first full sweep
walked 727 pages and collected **14,287 postings against 14,287 advertised,
with zero served twice** — so no posting is in two slices and none is in
none. Every column landed complete: category, url, location and posted_at are
non-NULL on all 14,287 rows. Each slice also came in exactly on its own
hitcount — Cleaner 1,084/1,084, Construction/Survey 1,035/1,035, Clerk
870/870, Accounting 434/434.

**And the taxonomy is what keeps a focus hub readable.** With English
occupation needles alone the first 2,380 postings came back 62% rejected and
**38% `relevance: unknown`** — `School Worker`, `General Office Clerk`,
`Storekeeper`, `Dish Washer`, `Labourer` — every one an unread card on a focus
hub. `tagging._IES_OFF_INDUSTRY` drops 21 of the 29 types on the advertiser's
own word (`Security Guard` 1,382, `Cleaner` 1,084, `Cook / Waiter` 933,
`Driver` 806), and it is an **equality** test rather than the subset test the
other three taxonomies need, because a partition means one label is the whole
answer. `Others` and `Other Professional/Associate Professional` stay in: a
catch-all is where a posting nobody classified lands, which is the opposite of
evidence.

**Three things the portal does that the pipeline had to be taught.**

- **A district is not a city.** The board writes `Tsing Yi`, `Kwai Hing`,
  `Mong Kok` — finer than its own 21-district taxonomy, matching no needle, so
  all 14,287 would read `other`, and the board *gates* `other`. The territory
  leads, as it does for Singapore. **Not unconditionally**: the portal's own
  `Outside HK` bucket was swept (741 rows) and **461 name only a mainland
  place**, in a vocabulary of nine words — Shenzhen 303, Guangzhou 56,
  Dongguan 42, Mainland China 17, Zhuhai 14, Zhongshan 13, Foshan 11,
  Huizhou 3, Jiangmen 2. The other 280 name a Hong Kong district too and are
  Hong Kong jobs with mainland travel, so they keep both.
- **The employer and the description are on the job card and on neither list
  view** — 14,287 requests against 715 for the board. So the walk writes a NULL
  employer and `bodies.py` fills it on the queue that would change an answer,
  the same split Workday, iCIMS and Oracle already use. `Fetched` gained an
  `employer` field for it, exactly as it gained `location` for Workday's
  `N Locations`; without it the hub would carry fourteen thousand postings from
  nobody, which is the JobStream failure. **The cost is real and stated**:
  until `bodies` reaches a posting its employer is NULL and `firm_key` groups
  it under `~unknown`, and at four seconds a row a few thousand queued
  postings are hours of fetching — so the first `daily --full` after this
  lands is a long one. `--limit` bounds it and the pass is resumable.
- **The card link is minted per render.** `?order=<base64>` differs between two
  fetches of the same list and there is no stable per-posting GET — `?ordno=`,
  `/ordno/` and `?SearchKeyword=` were all tried, and the search is POST only.
  So the token is stored and refreshed by every sweep, and a stale one
  **answers HTTP 200** with the vacancy-search page. `bodies.iesjobs_body`
  tests for the card's own `data-ordno` *and compares it against the row it was
  fetched for* — `get_with_url`'s lesson where the URL cannot be compared, plus
  the `palmersquare.com` guard against writing one firm's description onto
  another's row.

**Landing a national portal means telling every board-profiler about it**, and
that is the part that would have been quiet. `lexicon.NOT_A_BOARD` and
`dedup.PORTALS` both needed the name: one token carrying a territory's whole
board profiles `non_markets` on any threshold, and `non_markets_board` would
then have removed **every unread card in a focus hub**. It stays out of
`build_data.LAYER_THREE` for the opposite reason — that rule needs one
`last_seen` per board per poll and this walk writes one per *page*, so inside
it the freshest page would retire every earlier one.

### And Singapore had the bug this stage was written to avoid

**"Make sure Singapore is reading in everything" turned out to be a real
finding.** `mycareersfuture.walk` stopped on a **short page** — the trap
Jobbsafari and Oracle have each already taught this project, where a short page
mid-walk looks exactly like the real last one and the arithmetic looks perfect
either way. Nothing had gone wrong yet: a seven-page sample across the walk
(37, 113, 246, 401, 588, 733, 866) was 100 rows every time, and the shortfall
check is a real backstop. It is still a latent truncation on the source that
supplies **98% of the board's dated cards**.

Measured live before changing it: page 940 is the genuine last page at 58 rows,
and pages 941 and 942 answer with an empty result set. So the walk stops on the
empty page now, protected by the repeat-page guard it already had, and **the
whole cost is one extra request per sweep**.

### Everything else in `ACTION-REQUIRED.md`, settled

| item | outcome |
|---|---|
| robots.txt | not honoured; the compensation is a four-second interval and a weekly sweep. Bot detection stays closed. |
| model labels | `agent_labels.csv` is in `labels.SHEETS` and scored. |
| Norron | sold to Simplicity AB, page 404s; reader and `Site` row removed, roster row `stale`. |
| `prune` | nothing to do — `job_tags` holds only lexicon 57. `VACUUM` is what returns the 3.5 GB. |
| `board` branch | deleted from `razrer/quantjobs`. |
| MyCareersFuture feedback form | not written; the sweep completes at their rate. |
| Tibra | re-checked, board still serves zero postings, still out. |
| reversible calls | all stand. |

### The board is published and now re-publishes itself

`weekly.ps1` + `install-weekly.ps1`: Windows Task Scheduler, Wednesdays 03:00,
wake-to-run, `daily --full --publish`. **This reverses `CLAUDE.md`'s "nothing
schedules it"** at the reader's instruction — the reasoning behind that line
was about *where the cost lands*, and it still holds. The timer has to be
local: `data.js` builds from the local SQLite database, which is the same
constraint that keeps the GitHub workflow limited to `index.html` and
`robots.txt`.

A wrapper rather than a bare command line, and each of its four jobs is a
failure that would otherwise be silent at 3am: the Windows interpreter (bare
`python` is msys2, no CA bundle, every HTTPS request dies), `PYTHONIOENCODING`,
both streams captured through `Start-Process` rather than `*>&1` (PowerShell
5.1 wraps a native command's redirected stderr in `NativeCommandError` records
and would bury the `FAIL` lines), and `Get-Content -Encoding UTF8` on the way
back — **that last one was a real bug, caught on a probe run**: without it
`Öhman` logs as `Ã–hman` and every Chinese title becomes noise.

First publish after the sweep: **6,438 cards from 997 firms, 199 worth
reading** — the firm count up from 942 as the first Hong Kong employers
landed, and the shortlist unmoved.

### Two fixes found on the way

- **`bodies._clean` never decoded HTML entities**, and three of its fetchers
  read HTML — so every description SuccessFactors, iCIMS and Jobbsafari ever
  backfilled reached the tagger with `&amp;` intact, which folds to the token
  `amp`. That is `extract._text`'s bug in a second module, with the same fix
  and the same ordering: strip tags first, unescape second.
- **Scoring a third label sheet made the exit criterion unreadable.** *No false
  rejection* went from 0 to **78** the moment `agent_labels.csv` joined
  `SHEETS` — not because the tagger moved but because the grader is worse
  (relevance 84.9% hand, 77.9% auto, **45.0%** agent). Every disagreement now
  names its sheet and the block leads with the tally: **41 agent, 37 auto,
  0 hand.**

## Stage 41 — the sweeps were serial against different hosts

**Exit criterion:** the standing sequence costs the longest source rather than
the sum of them, with the per-host rate provably unchanged.

### What was measured

The `runs` table had the answer already — every Layer 4 poll records its start,
so consecutive starts are step durations. From the 27 August run plus today's:

| step | host | wall time |
|---|---|---|
| sweden | jobbsafari.se | 4.3 min |
| denmark | jobindex.dk | **33.6 min** |
| switzerland | job-room.ch | 0.8 min |
| jobstream | jobtechdev.se | ~1 min |
| singapore | api.mycareersfuture.gov.sg | ~70 min |
| hongkong | www2.jobs.gov.hk | ~50 min |

**Six sources, six different hosts, run one after another** — about 160
minutes of sum where the longest is 70. `jobs` and `pages` sit behind them and
touch neither.

### Why it costs no politeness, which is the only question that matters

`http._throttle` books its interval **per host** under a lock, so
concurrency across sources cannot become concurrency against a source.
Measured three ways:

- Synthetic: 4 slots × 3 different hosts, **9.0s serial → 3.0s concurrent**.
- The politeness test: 12 slots on **one** host, concurrent — **still 11s**,
  exactly what one caller making twelve requests costs. Pinned as
  `test_one_host_is_still_serialised_however_many_threads_ask`.
- Live: 2 requests × 3 real national-board hosts, **3.53s → 1.22s (2.9x)**.

And the database was already built for it. `db.connect` sets
`busy_timeout = 60000` and WAL, with a comment saying the long queues "are
meant to be run side by side"; six concurrent writers committing 240 times
measured **0.08s, zero errors**.

### What was built

`_daily` is three phases now: a serial prologue (`corrections`), a
**concurrent gather** of the eight independent sources, and a serial epilogue
(`tag`, `bodies`, `re-tag`, `alerts`). Anything that reads what an earlier
step wrote stays serial by construction.

**Threads rather than subprocesses, deliberately.** Separate processes would
each keep their own `http._last_hit`, so two steps that happen to share a host
— `jobs` and `pages` both reach firm domains — would each grant themselves the
full rate and quietly double it. One process, one throttle table, one
guarantee.

**The report had to survive it.** `contextlib.redirect_stdout` swaps a
process-global, so six concurrent steps would each capture the other five;
`_ThreadStream` routes writes by thread and the buffers are printed whole, in
the order the steps were listed. That works only because **the library is
silent** — every `print` in this project lives in `cli.py`, so nothing runs on
a worker thread and escapes the capture. `test_only_the_cli_prints_so_nothing_
escapes_the_capture` is the guard, and it was verified by planting a `print`
in `pages.py` and watching it fail.

### And the measurement found a bug of its own

Chasing "why is `bodies` filling nothing" turned up a real defect in Stage 40:
**the Hong Kong card token expires.** See `CLAUDE.md` — a twenty-minute-old
token had been taken as evidence of durability, tokens a couple of hours old
return the vacancy-search page with HTTP 200 and no card, and the backfill
filled 968 rows and then went quiet while still spending a request each. The
cause was isolated (a seconds-old token works in a brand-new process, so it is
time and not the session), the fix is a per-posting re-mint through the
portal's POST search, and `jobs.url` is NULL because a card whose open button
lands on a search box is worse than no link.

**A test-isolation bug came with it**: the new fetcher POSTs before it GETs,
and the existing tests stubbed only `get_text` — so the suite quietly started
making real, throttled network calls and went from 24s to 60s. Both are mocked
now, and 24s is the tell.

### Measured and refused

- **More workers.** The `bodies` queue holds 4,015 rows across **178 hosts**
  and only 12 workers, which sounds like the constraint and is not: 1,963 of
  those rows are one host at four seconds, so the pass is bounded at 2.2 hours
  by the throttle and 11 workers sit idle. Confirmed by watching the process —
  **one established TCP connection**, flat CPU. More workers would change
  nothing until that host's queue drains.
- **Raising a host's rate.** The one lever that would actually shorten Hong
  Kong is the four-second interval, and that is the compensation for reading a
  board whose `robots.txt` disallows it. Not a performance decision.
- **A page-wise backfill** is the real next speedup and is not built: one list
  page carries twenty fresh tokens, so fetching cards for the queued postings
  on each page would cost ~285 list pages + N cards instead of 2N requests —
  roughly half. It needs `bodies` to become page-oriented for one source,
  which is a bigger change than this stage.


## Stage 42 -- make `daily --full` finish

**The complaint was that a full run never seems to end, and the measurement is
the whole stage.** A live run was watched: 3h50m of wall clock for **16 minutes
of CPU**, one established TCP connection, and all six Layer 4 sources already
recorded `ok=1`. The gather phase had finished inside 70 minutes; the run spent
everything after that in `bodies`, on Hong Kong, at eight seconds a posting.

Built:

- **`iesjobs.card_links`** -- the card href the walk already parses and
  deliberately discards, returned to a caller that spends it inside the minute.
  Twenty tokens a request against one.
- **`bodies._iesjobs_pass`** -- walks the job-type slices minting tokens in
  bulk, reads each page's cards before asking for the next, and abandons a
  slice once the pages spent exceed the postings found. Falls back to the
  search for anything a slice does not yield.
- **`bodies.run` drives two strategies at once** -- Hong Kong sequentially,
  everything else through the existing pool -- with the writing left in the
  calling thread and producer exceptions re-raised rather than swallowed.
- **`tagging.run` over a process pool**, with a 20,000-posting floor and the
  board profile shipped through the pool's `initializer`.

Measured:

| | before | after |
|---|---|---|
| Hong Kong bodies, 864-row queue | 1,728 requests / 115 min | 1,085 / 72 min |
| re-tag, 40,000 postings | 36.8 s | 9.4 s (3.9x, identical output) |
| `daily --full`, estimated | ~3.9 h | ~2.6 h |

**The rate was not touched and that was the reader's explicit decision.**
`www2.jobs.gov.hk` stays at four seconds a request. The lever was the request
count.

**Exit criterion: met.** 1,005 tests pass; `card_links` and a harvested-token
card read were verified against the live portal, employer and prose both
returned, and the identity guard confirmed to refuse a mismatched order number.

Not done, and deliberately: `bodies` still runs after `tag` rather than
alongside the gather phase. Overlapping them would save perhaps 20 minutes and
costs the ordering that lets a posting scraped this morning be judged on its
body the same run -- `bodies.targets` reads `job_tags` to know what to fetch.


## Stage 43 -- count what Hong Kong is worth

**The question was whether the statutory board earns its runtime, and it was
asked because it looked like junk.** It mostly is, and the useful part of the
answer is that the two halves of its cost are separable.

Measured:

| Hong Kong hub | postings | relevant/less | +adjacent | unreadable |
|---|---|---|---|---|
| Firm ATS boards | 1,789 | 104 | **277** | 84 |
| iesjobs (statutory board) | 13,465 | 2 | **3** | 1,477 |

- **Six** postings rated above `unknown` out of 13,465 -- 0.04% against 15.5%.
- **Two of the six are reachable nowhere else**: `Quantitative Researcher (QR)`
  and `Quantitative Developer (QD)`, small firms running no ATS.
- **Five of the six were found from the title alone**, with no body.
- Body fetching: 1,028 fetched -> **1** positive, 718 still `unknown`, because
  **44% of the descriptions are majority-Chinese** and the lexicon is not.
- **1,223 unreadable cards** were the bulk of what the Hong Kong view showed
  -- measured on the build rather than by query, which had suggested 2,828:
  `rejected`, `withdrawn` and `off_location` fire first, so a standalone
  count of a gate's population overstates it.

Built:

- **`bodies.targets` third arm** -- for `iesjobs` only, fetch a card for a
  posting already *rated* rather than one the tagger could not place. The card
  is still the only place the employer is printed. Queue 864 -> **5**.
- **`build_data.unread_census_card`** -- an eleventh counted gate, with
  `UNREAD_IS_NOISE` naming the sources it applies to and `unread_census`
  as the predicate. Fires on double evidence; every rated card survives.

**Kept, and the reasoning is the stage's own finding:** the walk stays. It is
715 pages inside the gather phase, concurrently with Singapore's longer sweep,
so it is free in wall-clock terms -- **deleting the source outright would have
saved nothing over switching off its body queue.**

**Exit criterion: met.** 1,014 tests pass; the live queue confirmed at 5 rows;
board rebuilt -- 4,495 postings from 1,023 firms, 201 worth reading, the gate
counted on its own line at 1,223, and all six rated Hong Kong cards verified
present in `data.js`.

Combined with Stage 42: `daily --full` ~3.9 h -> **~1.5 h**.

## Stage 44 -- a refactor pass, and the four things it found

**The exit criterion:** the codebase reads the same, runs measurably faster on
the one stage that is CPU-bound, and every gap the pass turned up is either
closed with a test that was verified by planting the failure, or recorded with
the measurement that says why it was left alone.

### What it found

**The build could ship an empty board and would have.** `MIN_EXPECTED` guards
every registry and every national board; `web/build_data.py`, which produces
the file the reader looks at, had no floor. Reproduced accidentally during this
pass: `TAGGER` bumped, re-tag not yet run, every posting `untagged`, a
0-posting `data.js` written, exit code 0. `publish.py` would have uploaded it.
`MIN_CARDS = 500` and an `untagged > rendered` check now refuse *before* the
file is opened, with the gate counts printed first; `publish.py --no-build`
re-measures on the way out because it skips the build by construction.

**A lexicon edit without a `TAGGER` bump had already happened and nothing said
so.** 53 postings carried a verdict at version 58 that version 58's own code no
longer produced. `tagging.fingerprint` hashes the needle lists, `tag` stamps it
into `tagger_state`, `alerts` reports the divergence. The first version of the
fingerprint was itself unstable across processes — `_STOPWORD_LANGUAGES` walks
`frozenset`s and set order follows randomised string hashing — so the alert
fired on a freshly re-tagged database. **An alert that always fires is worse
than no alert.**

**One markets word in a body was holding 1,406 postings open**, and the
histogram of which word says it is the letterhead: `asset management` 180,
`investment management` 110, `financial institutions` 94, `treasury` 76.
`MARKETS_EMPLOYER` splits `MARKETS` the way `GENERIC_IN_BODY` already splits
`QUANT`, and it applies at `judge` step 8 only — narrowing step 7 as well moved
743 postings and cost the hand sheet its first false rejection.

**`labels.csv` could be lost two ways**, both reachable: a lost update between
two `serve.py` request threads, and a truncating `open(..., "w")` that leaves
an empty sheet if the write fails. Locked and atomically replaced now.

### What was built

- **Matching**: one loop instead of two, phrases filed under their rarest word,
  and the eleven needle *ladders* matched as one index each. **1.6x on tagging
  CPU, output identical tag for tag over 5,000 real postings**; a full re-tag of
  509,561 is 10m22s.
- **`quantscraper/sweep.py`**: the shortfall arithmetic four national boards
  had a copy of each.
- **`parsing.text`**: the strip-tags-then-unescape five readers had a copy of
  each, two of them having been fixed separately.
- **`cli._sweep` / `_shortfall` / `_held`**: the open-poll-record-report
  boilerplate five portal commands had a copy of each, and a dispatch table in
  place of a thirty-line `if` chain. `_hongkong` was missing from the
  crashed-poller test and is in it now.
- **The board**: `readable()` applied to portal employers (**462 of 1,031 firm
  tiles were fully capitalised legal names**), the `smart` sort option removed
  (byte-identical to `Newest posted`), and the public correction endpoint
  bounded.

**Exit (met):** 1,029 tests pass; the tagging change is byte-identical over
5,000 real postings and 1.6x faster measured with both variants alternating in
one process; the hand sheet holds at zero false rejections and moves 67.7% →
68.4%; the board goes 4,565 → 4,365 cards with the shortlist 201 → 202. Four
new guards, each verified by planting the failure it exists for.

## Stage 45 -- every silent source, asked once; and four families buried

**The exit criterion:** every board and source that yields nothing has been
*asked* rather than assumed about, each answer is recorded with what it was
asked, and the four job families the reader named are either off the board or
ranked below everything on it -- with the shortlist unmoved.

### The sources

**118 tier-A boards holding no postings were polled and the answers sorted.**
70 answer 200 and are genuinely empty -- small VC and PE firms with nothing
open, and the JSON vendors say so authoritatively (`{"data":[]}`,
`"items":[],"total":0`, feeds with no entries). 29 raise, 26 of those 404 and
most of *those* are a venture firm's careers page linking to its portfolio
companies, which is the `palmersquare.com` shape at scale. 10 are Taleo, which
was re-probed on two more tenants and is still a 1,535-byte redirect stub on
every career-section path. **2 were live and had simply never been reached.**

**What was recoverable, and it was worth the sweep:**

- **Jobvite ships two list layouts** and the reader knew one. `addendacapital`
  advertised `1-3 of 3` and `mercycorps` 32, and both read as nought -- caught
  by the shortfall check rather than by looking empty. 35 postings.
- **24 tier-A rows with a NULL token all named `careerN.successfactors.com`**,
  the vendor's shared pod. The board is on the firm's own hostname, as it is
  for every RMK tenant already read here. Seven answered, and **GIC** is the
  one that matters: Singapore's sovereign fund, **171 postings, 133 in a focus
  hub**, carrying `Portfolio Manager, Securities Finance` and `Associate - VP,
  External Managers, Macro/Fixed Income`. Unreachable by any walk --
  `gic.com.sg` does not resolve at all, only `www.gic.com.sg` does.
- **`tt.teamtailor.com`** was recorded as the board `tt`. Refused by name, not
  by a length rule: `ashby/3e` is a real board with 16 live postings.
- **Nine sources published no description**, and each was asked separately.
  Jobvite and Breezy publish a schema.org island on the page whose URL the list
  already stores; Personio publishes the whole board as XML with the same ids
  plus `occupationCategory`, its own taxonomy. **ADP and BambooHR are genuinely
  closed** -- ADP's requisition has no description key, empty `links` and
  `postingInstructions`, an empty per-requisition route and no `$expand`;
  BambooHR's page is 98 KB of application bootstrap whose `og:description`
  reads *"Take a look at the current openings at 17Capital"*.

**Hong Kong's cards have a link now.** The portal takes the order number in no
GET -- four shapes tried against a posting deep in the board, every one
returning page one of the whole board at HTTP 200 -- so `jobs.url` stays NULL
and the board's *open* control submits a cross-origin form POST to the
portal's own search. Measured cold jar, warm jar, with and without an XHR
header: one row, ours, in all four. The earlier probe that came back with the
whole board had no cookie jar at all, which is a state no browser is in.

### The classifier

**Legal and audit/tax leave the board; sell-side research, enterprise IT and
non-quant development stay and sort last.** Two instructions, implemented
differently: the first is a rejection, the second is a `fit` bucket
(`background`, ranked **-1, below `unknown`**) because the work is real and it
is the reader's profile that excludes it. Both vocabularies had to go in twice
-- `judge` runs last, so a legal or audit title carrying an ordinary markets
word had already reached `adjacent` on the branch above it.

**Exit (met):** 1,044 tests pass, `alerts` reports every source healthy.
Measured against the board this session opened on, after the recovered sources
had been polled and tagged: **4,565 -> 4,645 cards** (the sources put more on
than the classifier took off) from **1,031 -> 1,007 firms**, with the
**shortlist up 201 -> 206**. By family: legal **20 -> 3** cards, audit/tax
**74 -> 2**, IB and sell-side research **94 -> 92 of which 92 are buried**,
IT and cyber 19 of 25 buried, non-quant development 82 of 94 -- the ones left
ranked are the ones a quant or markets word in the title spares, which is the
guard working. The first `background` card sits at **position 4,337 of 4,645**,
strictly below every `unknown`. The hand sheet went 67.7% -> 69.9% with zero
false rejections at both ends.

Every needle was dry-run over 502,782 live postings first and none reaches a
positively-rated posting; every new reader and every new rule is pinned by a
test verified by planting the failure. The Hong Kong link was verified end to
end -- the board's own control captured mid-click, then the same POST replayed
against the live portal, which answered with one row and it was ours.
