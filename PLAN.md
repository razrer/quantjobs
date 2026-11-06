# Refactor stage 49 — implementation verified

Stages 0-48 and their original measurements are in
[the stage archive](docs/history/stages.md). Current methodology is in
[METHODOLOGY.md](METHODOLOGY.md).

## Scope and exit criteria

Requested: independent methodology before repository inspection; compare with
existing methodology; improve acquisition, labelling, code, performance, and
docs. Preserve geography and free local execution. Priorities: coverage and
correctness, maintainability, speed. Commit verified units, then push and publish
once at the end.

Exit criteria:

- Independent method and an evidence-based comparison recorded.
- Concrete defects have regression coverage; the complete suite passes.
- Behavior-preserving optimizations retain board cards and shortlist on a fixed DB.
- Documentation has one concise current guide and linked historical evidence.
- Changes committed, code pushed, data published, live output verified.
- Unmeasured coverage and work requiring human labels are stated explicitly.

## Progress

- Independent proposal saved before opening repo files.
- Original external proposal found under `.claude/plans`; the `.Codex` path
  supplied in the old instructions does not exist.
- Baseline: 1,112 regression tests pass; existing tests emit unclosed-connection
  ResourceWarnings under Python 3.13.
- Implementation verified: 1,130 tests pass; source alerts report healthy.
- Existing backlog classified: 20,835 postings, 334,674 tags written.
- Fixed-corpus comparison: 4,854 cards, 216 shortlisted, complete payload unchanged
  by the performance refactor with the calendar held fixed.
- Build time: 286.90s before; 129.79–144.12s after (about 2.0–2.2x faster).
- Relative posting dates now use the source poll date, a separately tested fix.
- Human-sheet agreement is 62.6%, with zero false rejections; the historic 90%
  criterion is not met. Independent audit labels remain human work, not a blocker
  on publishing the verified refactor.
- Release policy: push the verified commits together and publish the release build
  once. The task's final confirmation records the external delivery outcome.

Details and limitations: [refactor results](docs/REFACTOR-RESULTS.md).
Stage 49 was pushed and published; the subsequent investigation is below.

## Stage 50 — niche-employer discovery and duplicate display

Requested: improve exhaustiveness in Hong Kong, Singapore and Stockholm; provide
a separate Markdown outreach list without adding it to the website; then reduce
duplicate posts. Preserve free local execution and coverage before compression.

Exit criteria: test public discovery routes against local coverage, distinguish
new employers from affiliates/channel gaps, document an actionable strategy,
fix verified collection/identity gaps, and reduce repeated display cards without
losing underlying opportunities. Test, then push and publish once at the end.

- [Discovery strategy and evidence](docs/DISCOVERY-STRATEGY.md) records the HKEX,
  ACRA, cross-border affiliate and Stockholm fund-platform probes. Bulk ACRA
  ingestion and a recurring discovery refresh remain proposed, not implemented.
- Local-only `docs/OUTREACH-FIRMS.md` holds four verified outreach candidates and
  two affiliate cautions; gitignored and excluded from the board.
- UTR8's inline Hong Kong/Utrecht Graduate Trader now has a live-tested reader.
  One posting ingested and tagged `strong`; missing layout fails loudly.
- Rejected the unrelated author domain for Starfish Bay; local cached match reset.
- Similar-posting bundles retain independent links, filtering, save/correction
  controls and eligibility. Baseline: 91 cards in 40 bundles, 51 fewer repeated
  card slots versus stacking off; no card IDs or shortlist entries removed.
- Verification: 1,135 Python tests and four JavaScript tests pass. Expanded
  three-version Hong Kong bundle verified in the browser.
- Rebuild: 4,855 cards and 217 shortlisted. All 4,854 previous card payloads
  remain identical; UTR8 is the sole addition. Stacking-off survives reload.
- Release artifacts verified locally; the task's final confirmation records
  the final push, publication and external verification outcome.

## Stage 51 — Swedish noise and repeated cards

Requested: remove unrelated Swedish jobs and reduce duplicate display.
Preserve uncertain markets/research opportunities, underlying records, human
labels, employer identities, and individual links inside visual stacks.

Exit criteria: regressions pass, re-tag with the new classifier version,
compare every board card and shortlist ID, then commit, push and publish once.

- Added explicit service-occupation vocabulary for observed Swedish leaks;
  classifier version 64. No blanket Sweden or unknown-relevance exclusion.
- Visual stacks now recognize corroborated employer aliases, existing Unicode
  folding, and narrowly documented location variants. Every card survives.
- Full re-tag and rebuild complete: 4,810 cards, exactly 45 identified removals,
  and all 217 shortlist IDs preserved. Every surviving card payload is unchanged
  apart from visual grouping. Stacking saves 60 card slots versus 51 previously.
- Verification: 1,140 Python tests and five JavaScript tests pass. The Swedish
  cross-source stack opens both original application links in the browser.
- Release verified locally; the task's final confirmation records the push,
  publication and external verification outcome. Details are in
  [the incident record](docs/history/engineering.md#september-2026-swedish-noise-and-visual-duplicate-stacks).

## Stage 52 — Quantitative-finance role scope

Requested: substantially reduce conventional finance and generic IT, preserving
actual trading, quantitative portfolio work, pricing/risk models and validation.
Exit criteria: inspect real ads with Luna reviewers, protect genuine quantitative
counterexamples, pass regressions, re-tag all retained jobs, compare every board
and shortlist ID, then push and publish once.

- Scope decisions are recorded in METHODOLOGY. Reversible gates preserve source
  records and human labels. Missing developer descriptions remain unknown.
- Three Luna reviews and follow-up counterexamples informed the rules; these are
  development evidence, not independent accuracy or recall measurements.
- Classifier version 66; 1,153 Python and five JavaScript tests pass.
- Controlled re-tag of 602,025 records complete. Board: 4,810 → 3,618 cards; exactly
  1,192 reviewed removals (585 finance/support, 607 generic technology), no added
  or unexpectedly removed IDs. Shortlist: 217 → 215; the two removed roles are
  network reliability and ML support automation.
- Surviving card content and human labels are unchanged. One duplicate count
  drops from two to one after a matching source variant is gated.
- While release was paused by the account limit, the September 16 scheduled
  refresh acquired newer evidence and published version 66: 3,496 cards and
  238 shortlisted. Live index/data/robots match the refreshed local files.
  Preserve that newer output; the older controlled comparison is historical.
- Scheduled correction sync and a manual retry hit Windows access denial on
  labels.csv. Existing labels remain unchanged; see ACTION-REQUIRED.
- Details: [scope incident record](docs/history/engineering.md#september-2026-quantitative-finance-display-scope).

## Stage 53 — Windows correction-sheet replacement

Requested: fix the access-denied failure that prevented live corrections from
reaching `labels.csv`.

- Windows now uses its native atomic file-replacement operation for existing
  files; new files and other platforms retain the portable rename path. The
  destination ACL and crash-safe read/modify/write behavior are preserved.
- Pulled all 310 pending remote entries. Thirteen were new rejections; the rest
  were idempotent. Rebuild: 3,496 → 3,492 cards, exactly four current cards
  removed, no additions, no shortlist change, and no surviving-card changes.
- Verification: 1,155 Python and five JavaScript tests pass. The correction-file
  action item is resolved; final release verification is recorded in the task.

## Stage 54 — missed Wednesday refresh

- The September 23 run was missed while the laptop slept from September 22
  through September 24. The task had `WakeToRun`, but the active Samsung power
  plan disabled wake timers on battery. Windows started a catch-up run on
  September 24; it was interrupted before publication.
- Enabled battery wake timers and made `install-weekly.ps1` enforce wake timers
  on AC and battery when registering the task. The task remains set for
  Wednesdays at 03:00 with catch-up enabled.
- The missed interval overflowed job-room.ch's 20,000-result two-ended window.
  Its collector now bridges nested day windows and verifies distinct IDs against
  the largest advertised total. A targeted recovery collected 28,825 Swiss ads
  against 28,823 advertised (two changed during the walk); the source cursor
  advanced only after this complete read. All 1,158 Python tests pass.
- The full September 24 refresh published 3,743 cards and 245 shortlisted.
  Live `data.js` matches the local file byte-for-byte. Against the September 16
  build: 3,143 card IDs retained, 600 added, 349 removed; 220 shortlist IDs
  retained, 25 added, 18 removed. The source and tag evidence for removed
  shortlist entries was checked.
- The active refresh later paused when the lid closed and Windows entered
  Modern Standby, then hibernation on battery. `weekly.ps1` now requests an
  awake system during execution to prevent ordinary idle sleep; forced lid
  closure still suspends the laptop. A temporary awake request protects the
  currently running process while the laptop remains open.
- The run exited nonzero because it had loaded the old Swiss reader before the
  separate successful recovery, and because alerts found all 14 employer
  registries stale after 33 days plus Ashby/finvest's repeated 404. The full
  weekly sweep now includes the established registry reads. A one-time refresh
  completed successfully for all 14 registries; the stale registry alerts
  cleared. The Finvest failure remains visible while its public feed returns
  404, with its last five acquired postings preserved.
- UTR8's public careers page changed application links to buttons carrying
  application attributes. The reader now accepts both page formats and a live
  re-poll recovered its one Graduate Trader posting. The UTR8 alert cleared.
  All 1,160 Python tests pass. The rebuilt board's job and firm data exactly
  matches the already published copy; only its build timestamp differs.

## Stage 55 — browser cache after publication

- The live CDN served the September 24 board, but a visitor still saw the
  September 16 build date. The page requested the same `data.js` URL on every
  visit, and the response has no `Cache-Control` header, allowing a browser to
  reuse its old copy. Load board data with a fresh URL on each page load.

## Stage 56 — September 30 scheduled refresh

- The laptop was asleep from September 29 at 22:13 until October 1 at 11:13,
  so Wednesday's 03:00 trigger could not run. The queued catch-up attempt and
  a manual Task Scheduler start both ended with Windows code `0xC000013A`
  before publication. The task's Operational history was disabled and could
  not be enabled from this session.
- `weekly.ps1` no longer attaches its Python child to the scheduled process's
  absent interactive console. The scheduled wrapper was still interrupted
  later with `0xC000013A`, but the hidden Python child survived and continued
  collecting; a temporary awake request protects it. The installer now
  disables stop-on-idle-end and allows 24 hours for a lid-paused run. These
  task settings were applied while the orphaned child continued; the next
  trigger is Wednesday, October 7 at 03:00.
- Four national feeds reported `database is locked` under concurrent writes;
  the Swiss portal separately returned HTTP 504. A targeted Swiss retry
  recovered all 26,834 advertised postings. Future gathers retry locked
  sources serially after the concurrent phase. Direct retries recovered
  JobStream (39,641 changes), Denmark (17,164 postings), Singapore (95,506),
  and Hong Kong (13,311, matching its advertised total).
- An interim October 1 build was uploaded and verified byte-for-byte at the
  public CDN: 3,838 cards, 241 worth reading. The hidden child survived its
  interrupted wrapper, finished enrichment, and uploaded another October 1
  build. Closing the lid suspended it for 96 minutes; it resumed on wake.
- The final correction sync encountered Windows `ReplaceFileW` error 1175
  after repeated per-entry replacements. It now applies all corrections under
  one lock and one atomic replacement; all 338 remote corrections synced.
  `run.ps1` now propagates the Python exit status. All 1,163 tests pass.
- The fully recovered build is live and byte-for-byte verified at the CDN:
  3,808 cards, 250 worth reading, built October 1 at 17:00 UTC. Against the
  previous October 1 copy: 3,743 card IDs retained, 65 added, 14 removed;
  238 shortlist IDs retained, 12 added, five removed. Four removals match
  human rejections; raw records remain held. The only remaining alert is
  Ashby/finvest's existing 404, with its last five postings retained.

## Stage 57 — learn from rejected postings

Requested: inspect the user's rejected postings and improve the classifier from
the observed mistakes. Preserve raw jobs, human labels, ambiguous missing-body
roles, genuine quantitative work and the shortlist.

- Reviewed all 402 human rejections against stored evidence. Version 67 adds
  observed occupation and support-role variants, explicit office IT specialties,
  and duties-based checks for welfare-fraud analysis and executive recruitment.
- Controlled preflight across 896,110 retained postings: automatic exclusion of
  human rejections improves from 301 to 329; no newly excluded human-positive
  posting. This is development evidence, not independent accuracy measurement.
- All 1,169 regressions pass. Re-tagged all 896,110 retained postings at version
  67; human labels are byte-for-byte unchanged. All 22 non-rejected human relevance
  labels were checked, with no newly excluded label.
- Final board: 3,808 → 3,797 cards. The new rules remove exactly the 12 reviewed
  cards. Recomputing existing employer profiles separately removes two CMC
  business-analyst cards, adds three missing-description roles, and changes five
  existing ratings. Each of those ten differences reproduces under version 66
  with the same refreshed profiles. All other surviving card payloads and every
  one of the 250 shortlist IDs are unchanged.
- Details and limits: [rejection review](docs/history/engineering.md#october-2026-rules-learned-from-human-rejections).
- Published October 2; the CDN's index, data and robots files match the verified
  local files byte-for-byte. Code and verification are committed; the final task
  confirmation records the remote push outcome.

## Stage 58 — October 7 missed weekly refresh

- The laptop was closed during Wednesday's 03:00 trigger. Its wake-time catch-up
  ended `0xC000013A` before writing a log. A manual scheduled start while fully
  awake on October 8 completed the pipeline and uploaded an interim board;
  its public `data.js` matched the local file byte-for-byte.
- The full run exposed two coverage failures. Jobindex moved its search response
  into a different Stash key; a repaired full retry read 18,687 Danish postings
  against 18,661 advertised. Oracle's Kotak board advertised about 16,000 but
  stopped at the 10,000-result window; documented date bounds now partition
  larger boards, and a targeted retry read 15,983 postings and cleared its alert.
- A daily noon retry trigger is installed alongside Wednesday 03:00. Its guard
  skipped both a still-running sweep and a completed current-week build without
  duplicating source reads. Distinct attempts now keep timestamped logs.
- Re-tagged the recovered rows, fetched details for all 16 new title-only
  candidates (five bodies filled), and re-tagged those five. The final alert
  check has only Workday/Aesop's 422 and Ashby/finvest's 404; their last records
  are retained. All 1,172 Python tests pass.
- The final build is live and byte-for-byte verified with a fresh CDN download:
  3,899 cards, 261 worth reading, built October 8 at 13:38 UTC. Against the
  interim October 8 build, all 3,893 card IDs remain and six Danish cards were
  added. The strong/apply-now shortlist retained all 259 IDs and gained two.

## Stage 59 — Layer 2 back on the schedule

Requested: a methodology review of discovery, retrieval, reliability and
tagging, then the first item from it — put `resolve`, `domains`, `ats` and
`discover` back on the weekly schedule. The review and its recorded decisions
are in [the methodology review](docs/METHODOLOGY-REVIEW.md).

- Measured the funnel and the per-source yield that the review is built on:
  70,370 firms produce 1,263 tier-A boards and 1,216 firms visible on the
  board; the six national portals hold 77.5% of 1,187,720 postings and supply
  26% of the 283-card shortlist; `job_tags` is about 65% of a 9.69 GB database.
- `domain_lookups` had 53,742 of 53,789 rows last checked in August and
  `ats_resolution` 19,839 of 20,033, while all 14 registries reported healthy
  every week. The cause was narrower than a backlog: every Layer 2 queue is
  drawn from `firms`, `resolve` had not run since August, and the 1,984
  employer rows that arrived since were in no firm at all. `domains` therefore
  answered "nothing left to probe" with two months of new employers invisible
  to it.
- `cli._layer2` runs `domains → ats → discover → regrade → reprobe` in order
  inside one concurrent gather slot, with `resolve` in the `--full` prologue
  ahead of it. Weekly rates rather than a monthly block: stages 54, 56 and 58
  are missed-Wednesday incidents, and every queue here is self-advancing, so a
  missed week costs one week instead of a cycle. Budgets in
  `cli.LAYER_TWO_BUDGET`, sized against measured throughput — domains 1.2 s a
  firm, ats 0.58 s, regrade 0.65 s, reprobe 0.35 s, discover 22 s a candidate —
  so the slot stays inside the hour Singapore and Hong Kong already take.
  `discover` is scoped to each focus registry in turn, because its global
  ordering acts as a filter inside a `--limit`.
- Two defects found while testing it, both a queue with no cursor.
  `ats.reprobe_targets` ordered alphabetically while `reprobe` writes only an
  improvement, so a budgeted pass re-walked the same head every run and never
  reached tier B; an `ats_attempts` table on the `page_attempts` pattern is now
  the cursor. `domains.regrade_targets` never selected `evidence` although
  `regrade` writes it back, so the first unreachable host raised `IndexError`
  out of `pool.map` and killed the pass — the marker that branch exists to
  write had never been written once, 0 rows against a queue 3,502 deep.
- `alerts` grew a `layer2` check: these steps write no `runs` row, because a
  count that is sometimes the budget and sometimes an empty queue is not a
  volume, so the check asks when each cache last did work. `domains` excludes
  `method = 'registry'`, because `harvest_registry_domains` rewrites
  `checked_at` on a fifth of the table with no network at all and would read as
  health.
- Verified live: `resolve` took 4 seconds and raised `firms` from 70,370 to
  72,130; `domains` then probed 40 firms for 9 domains where it had just
  reported nothing to do; `ats` fingerprinted 40 domains into 2 new tier-A
  boards; `reprobe` re-walked 40 and corrected 29, `bentley.com` among them,
  from a tokenless SuccessFactors row to `workday|wd5|bentley`.
- Not done here and still open: the SuccessFactors token extraction reads the
  vendor's datacentre host rather than the tenant, which leaves 35 tier-A rows
  tokenless including Eurex, Clearstream, Hang Seng and PFA. That is F6 in the
  review, approved and not yet implemented.

## Stage 60 — SuccessFactors' second surface

Requested: fix the SuccessFactors token extraction so the tokenless tier-A rows
get a real token, then reprobe them.

- It was not a token-extraction bug. The token shape was already right -- the
  firm's own host -- and those rows sit on RMK's unify career site, which
  renders its list from a JSON API, so the classic reader's selectors match
  nothing and `_serves_feed` was correctly refusing to record a host whose feed
  could not be read. A reader was missing, not a pattern.
- `extract._sf_unify` reads it: `POST /services/recruiting/v1/jobs`, taken off
  the site's own `j2w.searchManager.min.js`, with a GET's 405 confirming the
  path first. The locale is read from the page (`en_US` against Orkla returns
  `totalJobs: 0`), the posting URL is `/job/{display title}/{id}-{locale}` from
  the widget's href builder and then opened, and the walk repeats until it
  finds no new requisition, because the API shuffles which page each row lands
  on -- Royal London served 33 rows for 26 distinct. `_shortfall` gained
  `sweep.problem`'s served/distinct distinction. The fallback is gated on the
  unify marker so an unparseable layout stays loud.
- One real defect underneath: `_custom_host` skipped its own vendor rule
  whenever the host patterns had named the vendor, including when they named it
  and captured nothing.
- 5 rows resolved, 4 boards, **505 postings, and zero board yield**: 384
  out_of_scope, 116 unknown, 3 stretch, 2 background. Consumer goods, corporate
  services, insurance and payments are not quant employers, so the gates are
  right. Recorded as a zero-yield result, per DISCOVERY-STRATEGY.
- `alerts` grew an `unpollable` check. Tier A means Layer 3 polls the feed, and
  two states satisfy the tier without satisfying the sentence -- no token, or
  an ats with no extractor -- which `extract.targets` filters out silently. It
  now reports 29 tokenless rows across nine vendors and 10 Taleo rows.
- `reprobe_targets` puts tokenless rows ahead of tokened ones among equally
  stale rows, so the weekly pass reaches the strictly worse state first.
- Eurex, Clearstream, Hang Seng and PFA are **not** fixed: their stored careers
  URL is a marketing page rather than a board. That is the careers-page walk
  (F5, F8), not a vendor reader. `jobs.paysafe.com` has an expired certificate.
- 1,210 tests pass.

## Stage 61 — regional ATS hosts and misattached roster domains

Requested: read SEB's Lever board, look for other missed platforms, then fix
Lever EU, Greenhouse's regional hosts and the roster firms on the wrong domain.

- Lever's EU instance is a separate deployment: SEB's board answers on
  `api.eu.lever.co` and 404s on `api.lever.co`, so it is its own `lever_eu`
  vendor and is discoverable by name. Greenhouse's regional hosts are pages only;
  the global API serves them, so that fix is the pattern alone.
- Pinned nine firms in `sites.py`: SEB, UBP, GAM, Bank of America, Swiss Re,
  Zurich, SIX, Verition, Fisch. Each token was read through its extractor first.
  Dymon and Karl Lagerfeld resolved through the fixed patterns unaided.
- Real corpus, with the fixed classifier version 67: 4,623 → 4,739 cards, none
  removed, every surviving payload unchanged; shortlist 299 → 315, none removed.
  Those boards account for 87 cards and nine shortlist entries. The other 29 and
  seven are boards already tier A that had never been polled, Blocktech mainly.
  Bank of America fell from 382 cards to 65 once descriptions were read.
- Not done: `audit --pipeline` still counts an aggregator name match as reached,
  so the 171/254 it now reports overstates board coverage. Stored `union.com.hk`
  and `mb.seb.se` matches remain. Readers for Oleeo, Radancy, HiBob, Refline,
  ReachMee, Heartpace, Paylocity and ApplicantPro are unbuilt and their endpoints
  unverified. A card's hub can read a city from its title: Zurich's Köln role
  shows Switzerland.
- 1,217 tests pass.

## Stage 62 — an honest pipeline audit, and the boards it exposed

Requested: fix the audit's overstatement, then build the unbuilt readers.

- `audit --pipeline` counted a national portal's adverts as reaching a firm, and
  counted withdrawn postings. Portal adverts now sit in their own column and never
  count as a board; only open postings count. 171/254 reached became 107/254.
- It also read `jobs.domain` alone, but one board shared by several domains is
  filed under the first, so Danske's 500 postings looked like nothing. It now asks
  the board. `sites.ROSTER_BOARDS` names firms read under another domain, such as
  DBS and Swedbank.
- New vendors: `radancy` (BlackRock 281) and `oleeo` (Jefferies 50), both
  fingerprinted for future probes. New reader: `gresearch` (64). Pinned on existing
  readers: Optiver, Qube, JPMorgan, Citi, Mirabaud, LGT, Lloyds, Standard Chartered.
  With the roster names above: 107/254 → 130/254 have a board, 128 producing,
  47 more seen only on a portal. The split between the two was not measured.
- Real corpus, classifier version 67 unchanged: 4,739 → 5,660 cards, 939 added, 18
  removed, 2 changed; 315 → 362 worth reading. 17 of the removals are JPMorgan's
  MyCareersFuture adverts, each matched by title on its own board. The other is an
  Atos posting, and the changes are a dup count and a posted date; none come from
  this work.
- Left closed: HiBob answers 401, and these answered 403 to our client: Goldman's
  careers page, UBS jobs, Julius Baer, Wells Fargo, Fidelity, Temasek, NatWest,
  Swiss Life, EFG, Edmond de Rothschild, Jyske, BNP. `nb.com` answered 429.
- Not done: Refline, ReachMee (Alecta), Heartpace (AP2), Paylocity, ApplicantPro,
  PGGM's vendor, and own-site boards at APG, ABN AMRO, Deutsche Bank, Vanguard,
  Balyasny, PEAK6. Many careers-page guesses 404ed, so those firms' vendors are
  unknown, not absent. Radancy and Oleeo are title-only until the tagger asks: the
  body queue takes only `unknown` rows, and Oleeo has no fetcher. Oleeo's job pages
  held no description in the one fetched.
- To check: Citi's Radancy site lists 3,112 and its Workday board 2,017, unexplained.
  The Workday token holds 9,174 rows marked live, many unseen since September. One
  Standard Chartered card is dated 2026-12-10, in the future.

## Stage 63 — the remaining vendors, and a Swedish census

Requested: build the remaining readers, then make Sweden completely covered,
because a few misses matter more in a small market.

- New vendors: `refline` (ZKB), `paylocity` (XR Trading), `applicantpro` (Group
  One), `reachmee` (Alecta, FI, Riksbanken, Riksgälden, Folksam), `heartpace` (AP2),
  `deel` (Klarna), `attrax` (Vattenfall). Jobylon now reads company groups.
- The census started from about 120 real Swedish employers on their real domains,
  not the roster, because the roster only shows gaps in firms already thought of.
  Most misses had no domain, or a wrong one, in the universe. `roster.csv` gained 52
  Stockholm lines, so `audit --pipeline` now measures these firms.
- Result: 164/306 roster firms have a board we read, 162 producing, 53 more
  seen only on a portal. The denominator grew from 254, so this is not comparable
  with Stage 62's 130/254. Board: 5,699 cards, 364 worth reading; Stockholm
  112 → 136 cards since Stage 62's snapshot was taken.
- ReachMee lists no place, so its cards had no hub and were judged on titles alone.
  The reader now fetches each posting. Riksbanken's pages state no place, so its
  cards still have no hub.
- Not changed: the classifier. `non_quant_finance` hides Swedish portfolio and fund
  management roles such as Alecta's aktieförvaltare and SEB's Portfolio Analyst,
  which is a scope decision for the user. Student-only roles stay out by the
  existing scope.
- Open in Stockholm, see `audit --pipeline`. Own-site or unread: SEK, Kommuninvest
  (Teamtailor widget with no public board found), Ziklo, Simplicity, Stabelo,
  Catella, Lannebo, Spiltan, Cevian. DNB Carnegie's old site lists nothing and its
  new site returned almost nothing. Blocked (403): Euroclear. The Teamtailor widget
  key on Kommuninvest's page was not used. A TLS failure stops Atlant and Movestic.
  Portal counts in that list are name substrings, so `Atlant 133` is a lead only.

## Stage 64 — fund seats that are quant or adjacent (tagger 69)

Requested: Swedish portfolio and fund management roles appear only if they are a
quant job or adjacent to one.

- `role_scope._quant_fund_seat`: a fund title stays if the title itself names risk
  analysis or asset allocation, or if the body shows three independent kinds of
  quantitative evidence. Conventional stock-picking seats stay hidden. Internships
  and engineering titles do not qualify: the first version let through a SEB
  internship and Yokogawa's industrial "Asset Management & Reliability" roles.
- `_duties` reads Swedish duty headings and verbs, and splits on `•`. Bullets used to
  merge into one sentence, so a verb could pair with a term from another bullet.
- Board: 5,699 → 5,705 cards, 364 worth reading unchanged, Stockholm 136 → 138
  (Entelios portfolio manager, Pensionsmyndigheten risk analyst). 10 added, 4 removed,
  1 changed. Removed: three Luxoft business analyst cards and a JPMorgan production
  engineer, all in Singapore, which had passed only on the bullet merge.
- Not caused by the classifier: two added Marex cards and one changed one depend
  only on Marex counting as a quant board, which is measured afresh on every `tag`.
- Now pass the fund rule but stay off the board as too senior: Swedbank Robur's index
  manager, AP7's asset allocation manager. Swedbank's model auditor stays under
  `audit_tax`.
- The Pensionsmyndigheten advert was last seen on 2026-08-22 with no deadline, so it
  may have closed. Not checked.
- SEB's 2027 internships remained on the board, several rated `strong`, although the
  scope excludes student roles. Closed by Stage 65.
- Open: `tag` hung on its first run. A pipe write to the pool failed with WinError
  1450 on 7.7 GB of RAM with 918,000 postings pending, and the pool waited
  indefinitely. Committed chunks survive, so re-running resumes. Both full re-tags
  here ran with `--limit 100000` in a loop, without failure. `tagging.run` still sizes
  chunks by corpus and needs a cap.

## Stage 65 — a student / internship category (tagger 71)

Requested: student and internship roles get their own category and are easy to filter
out. Some internships are open to non-students, so the board does not remove them.

- `tagging._student_title` adds a `student_role` tag, read from the title only. The
  `Contract` facet could not serve: it reads bodies, and labels SBAB's Erfaren
  Riskanalytiker and Jane Street's Quantitative Researcher as internships.
- The tag does not touch `fit`, gates or exclusions. The board gains a `Student /
  internship` facet and a `Hide student / internship` toggle, off by default.
- Words ending in `student` or `praktikum` count, for compounds such as
  `Juriststudent`. Swedish `intern` meaning internal, and `student housing`, stay out.
  Graduate and trainee programmes stay out because a graduate can hold them.
- Board: 5,705 cards before and after, none added, removed or re-rated. 494 are in the
  category. Stockholm 14 of 138: the SEB internships and student roles, plus Alecta,
  Fairlo, Lynx, Vattenfall, Citi and Soderberg & Partners.
- The rail counts cards still open, the toggle counts all of them. The 25 cards apart
  at tagger 70 were past their closing date, which the board hides by default.
- Open: `Contract: internship` still reads bodies and stays unreliable. `MBA Value
  Summer Research Associate` at Invesco is a title the word list misses.
