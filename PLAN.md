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
