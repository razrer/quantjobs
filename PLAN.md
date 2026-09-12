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
No additional implementation stage is queued.
