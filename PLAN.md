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

**Stage 36 is the last one written down and every stage is closed**, so the next
unit of work is a decision rather than a queue: what to widen, what to measure,
or what to leave alone. The standing sequence is one command, `python -m
quantscraper daily`, and `python web/publish.py` puts the result on the CDN.
Both are deliberately manual, because the search is the expensive half and it is
free on this machine.

Candidates, none of them queued:

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
- **Three vendors are closed rather than pending**: Eightfold answers 403 on
  its jobs API, Paylocity renders client-side, and Jefferies' `tal.net` portal
  now sits behind an Altcha CAPTCHA. Recorded in `CLAUDE.md` so they are not
  re-derived.
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
