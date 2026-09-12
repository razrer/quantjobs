# Independent refactor methodology

Written before opening repository files. This is independent of the existing
implementation, but informed by the user's supplied project requirements.

## Objective and constraints

Find every potentially suitable quantitative-finance opening; make uncertainty
visible rather than silently excluding it. Preserve acquired records so that
classification and presentation decisions can be reversed. Assume free local
execution and the stated geographic priorities unless the user changes them.

## Acquisition

1. Define the employer universe by jurisdiction and employer type. Enumerate
   regulatory registers, exchange participants, and other complete public lists.
   Use job aggregators to discover missing employers and independent postings.
   Record where public enumeration cannot establish completeness.
2. Keep source identities and provenance separate from resolved employers.
   Merge only on strong evidence; retain ambiguous candidates for review.
3. Resolve each employer to its official hiring channels. Treat missing,
   inaccessible, empty, and successfully polled channels as different states.
4. Prefer structured feeds and exhaustive pagination. Establish completeness
   against source totals, stable identifiers, and completed partitions. Preserve
   successful partial ingestion, but never report a partial walk as complete.
5. Infer withdrawals only from a successful complete poll of the relevant scope.
   Failed or incomplete polls must not make live jobs disappear.
6. Schedule work by age, expected yield, uncertainty, and source constraints.
   Persistent queues must eventually revisit every employer. Bound retries and
   concurrency; respect server refusals and rate limits.

## Data and labelling

7. Separate source facts, normalized fields, inferred labels, and human overrides.
   Retain source IDs, timestamps, provenance, and enough text to reproduce a
   decision. Prefer stable identity over title-based deduplication.
8. Label independent dimensions: role relevance, seniority, location, employment
   type, and actionable application status. Represent uncertainty explicitly.
   Apply user-specific display gates after ingestion and classification.
9. Version classification rules. Fetch missing evidence before making confident
   exclusions; reclassify affected records when rules or evidence change.
10. Evaluate on both a representative sample and difficult boundary cases. Keep
    a held-out set separate from examples used to tune rules. Report recall,
    false exclusions, precision, and slices by source, language, and geography.
    Do not claim measured recall for an unknowable universe.
11. Keep human labels durable and attributable. Make corrections survive rebuilds
    and expose conflicts between source facts, rules, and overrides.

## Reliability and performance

12. Measure coverage as a funnel: known employers, resolved channels, recently
    completed polls, live records, sufficient descriptions, and displayed jobs.
    Monitor counts, staleness, incomplete walks, and source-specific failures.
13. Establish baseline outputs and timings before changing load-bearing code.
    Use representative real payloads alongside targeted regression tests.
14. Simplify repeated logic only when contracts genuinely match. Prefer maintained
    free libraries for ordinary parsing and transport; preserve documented vendor
    behavior and proven retry/throttle semantics.
15. Optimize measured costs: redundant requests, repeated classification, database
    scans, and serialization. Use bounded concurrency only where identity,
    throttling, transactions, and failure isolation remain correct.
16. Keep changes independently reviewable. Check output differences, especially
    false exclusions and the user's shortlist, before declaring an improvement.
    Shorter code is useful only when behavior is easier to understand and verify.

## Documentation and delivery

17. Keep the entry document short: purpose, setup, routine commands, architecture,
    invariants, and troubleshooting links. Store incident history separately;
    replace repeated explanations with links to one authoritative definition.
18. Compare this method with the current method before implementation. Record
    agreements, gaps, evidence, and rejected alternatives. Prioritize silent data
    loss and classification errors before cleanup and speculative optimizations.
19. For each completed change, record the problem, behavior, verification, and
    remaining limitations. Publish only within the user's authorized scope.

## Comparison and execution record

Inspected the original external proposal at
`C:/Users/razre/.claude/plans/snoopy-growing-hoare.md`, repository guidance,
stage history, tagging method, and the implementation. The `.Codex/plans` path
in the supplied guidance was stale. The original is now archived in the repo.

| Area | Comparison and decision |
|---|---|
| Employer-first collection | Strong agreement. Preserve it, including broad ingestion and conservative identity resolution. |
| Coverage claims | Original estimates of roughly 90% and statements that discovery is solved have no measured denominator. Replace with explicit population boundaries and structural gaps. |
| Speculative sources | Original CT logs, Common Crawl, social monitoring, geo-diverse egress, and hiring signals are proposals, not delivered coverage. Do not imply they exist or add them without an audited gap. |
| Runtime and geography | Original free-tier/LLM suggestions and broad geography are superseded by the user's current free-local constraint, deterministic rules, and nine focus hubs. |
| Limited polling | Existing ATS targets were alphabetical and repeated on every limited run. Rotate by last attempt and group shared `(ats, token)` boards. |
| Failed careers pages | A failed first read had no stored attempt, so it could monopolize a limited queue. Record attempts separately from successful snapshots; rotate without inventing a change signal. |
| Evidence ownership | A Workday count overwrote enriched places. Share the placeholder rule and preserve resolved values; genuine new places and Remote still refresh. |
| Classification freshness | Poll updates could change evidence without invalidating tags. Invalidate on changed inputs, preserving unchanged polls. This repairs future updates; it cannot reconstruct past overwritten evidence. |
| Evaluation | Focused sampling excludes language/vocabulary/display decisions it should sometimes challenge. Retain it for development and add an independent, filter-free retained-record audit. No new accuracy claim without human labels. |
| Human data | Atomic writes already existed, but redraw read outside the correction lock. Cover the full read-modify-write and refuse to discard orphaned labels. The existing lock remains process-local. |
| Performance | Profiling found repeated reads/joins of the wide jobs table dominated the build. Materialize indexed metadata once per build and defer descriptions until after gating; compare the complete payload. Share identical clustering mechanics while retaining matching policy. |
| Output durability | Build floors already protected against tiny outputs, but direct writing could truncate the old file on failure. Use atomic replacement after the existing checks. |
| Version guards | A tagging run could overwrite the fingerprint that proved unversioned rule drift. Refuse the run and retain the evidence. Publishing an existing file now checks its tagger version as well as its size. |
| Relative posting dates | Comparing builds across midnight exposed a real bug: stored relative dates moved forward on each rebuild. Anchor them to the last source observation, preserving absolute dates and date precision. |
| Documentation | Identical 3,600-line guides, old claims of no dependencies/manual scheduling, and outdated geography obscured current policy. Consolidate current guides, archive history, and use live CLI vocabulary instead of duplicated lists. |

The user confirmed coverage/correctness → maintainability → speed, unchanged
geography and free local execution, and commits during the refactor with one
push/publication at the end.

## Boundaries that remain

- Public sources cannot establish a complete employer or vacancy universe.
- Withdrawal detection still depends on each reader's completed-walk contract;
  introducing a universal poll-generation schema is a separate data migration,
  not a cosmetic refactor. No partial-walk timestamps were changed here.
- Historical labels and current tags are not versioned snapshots of source text.
  The audit must identify missing evidence rather than fabricate it.
- The human-label lock does not coordinate separate processes. Do not run separate
  label writers concurrently. A cross-process storage redesign is not claimed.
- Enriched locations already lost from SQLite need detail fetching again. Retention
  prevents another overwrite; it does not invent recovery from old hub tags.
- Existing vendor-specific adapters remain separate. A shorter universal parser
  without real payload equivalence would trade away the required coverage.
