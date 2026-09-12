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
