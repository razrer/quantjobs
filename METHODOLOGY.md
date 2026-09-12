# Acquisition and evaluation methodology

Current policy. The [independent proposal](REFACTOR-METHODOLOGY.md) was written
before repository inspection; the original proposal is retained locally at
`docs/history/original-methodology.md` as historical context, not as a list of
implemented capabilities. That imported personal reference is gitignored.

## Scope

Coverage and correctness come first, maintainability second, speed third.
Run acquisition on this Windows machine using free libraries and public sources;
do not create accounts, buy data, or use metered inference. Existing hosting is
unchanged. Publish the static output, never the database or scraper runtime.

Focus on Stockholm, Copenhagen, Amsterdam, Switzerland, Hong Kong, Singapore,
New York, Chicago, and Boston. Other US locations rank below focus. Preserve all
acquired records regardless of geography; user-specific display gates are reversible.
The target is a graduate with under one year of experience, oriented toward
Python and research. Work authorization is not an ingestion filter.

## Collection

1. Enumerate employers from registries and exchange lists. Keep source IDs and
   provenance. A register covers its own regulated population, not every possible
   employer; sponsored-access firms and other documented gaps require discovery.
2. Resolve identity conservatively. Prefer duplicate firms to merging unrelated
   employers. The named roster measures known gaps and is not the universe.
3. Resolve official careers channels and verify employer ownership. Keep unresolved,
   inaccessible, empty, and successfully polled channels distinguishable. Aggregators
   supplement direct feeds and reveal employers missing from the universe.
4. Ingest broadly. Audit pagination, partitions, unique IDs, source totals, and
   minimum volumes. A partial or failed walk must report failure and must not infer
   that unvisited jobs were withdrawn. A successful empty poll needs separate
   evidence before it is treated as a genuine empty board.
5. Schedule oldest attempts first where queues are limited. Count failure attempts
   too, so one dead host cannot permanently starve the rest. Deduplicate work by
   channel identity, not employer alias. Keep rate limits shared across workers.
6. Preserve acquired evidence and detail enrichment. List summaries must not
   overwrite resolved Workday locations. Changed evidence invalidates derived tags;
   unchanged polls do not need reclassification.

The weekly sequence is corrections → concurrent source reads → tag → bodies →
tag → alerts → build/publish. The two tagging passes have different inputs.
Robots exclusions are read past only under the standing slow weekly policy;
CAPTCHAs, WAF refusals, and 429 responses retain the existing restrictions.

Discovery must recur alongside polling existing jobs. Use corporate snapshots,
exchange activity and evidenced affiliate/adviser relationships to investigate
unlicensed or unfamiliar names; keep relationships separate from entity identity.
Audit unresolved careers channels, including vacancies embedded directly in prose.
Verified firms without advertised vacancies belong in the local outreach file,
not on the board. See [the measured discovery strategy](docs/DISCOVERY-STRATEGY.md)
for the Hong Kong, Singapore and Stockholm pilot and proposed refresh cadence.

## Classification and evaluation

Use deterministic multilingual rules with separate dimensions, explicit uncertainty,
and evidence spans. Store rejects. Only the board gates visibility. Human labels
remain separate, durable inputs; do not overwrite them with machine predictions.

Use two distinct samples:

- **Focused development sample:** plausible markets roles and contested decisions,
  spread across boards. Useful for improving rules, not for estimating corpus recall.
- **Independent audit sample:** a stable hash sample of all retained postings not
  explicitly marked removed, without classifier, language, geography, or URL filters.
  It includes hidden records and may include stale or unreadable ads. Record those
  limitations; never silently count missing evidence as a correct rejection.

Keep an audit sheet separate and freeze it before tuning. Once its cases inform
rules, it becomes development evidence; use fresh independent cases for the next
evaluation. Do not generate supposedly independent ground truth with the classifier
being evaluated. Report human and machine sheets separately, and inspect false
exclusions by source, language, location, and gate. The current score command reports
dimension agreement and containment; these are not whole-market recall estimates.

The audit's population is retained database records, not all available vacancies.
Even a perfect score cannot measure employers or postings never collected. Coverage
reports must name their denominator and unknown gaps instead of asserting 90%.

## Refactor acceptance

- Preserve identities, retained rows, known vendor quirks, and per-host throttling.
- Test each corrected failure; compare real-corpus output for behavior-preserving work.
- Compare card IDs, classifications, shortlist, and gate counts on a fixed database.
  Explain deliberate differences rather than relying on an unchanged total.
- Measure performance using the same corpus. Avoid optimizing by omitting ingestion.
- Commit verified units; push and publish once at the end of this refactor, as requested.
- Keep current instructions brief. Historical counts and incident narratives belong
  in [history](docs/history/README.md), not in operational instructions.
