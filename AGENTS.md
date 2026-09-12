# Repository working rules

Read [PLAN.md](PLAN.md) before work. Current acquisition and evaluation policy is
[METHODOLOGY.md](METHODOLOGY.md); command usage is in [README.md](README.md).
Consult [historical incidents](docs/history/README.md) for the component being
changed. Do not copy history back into routine instructions.

## Priorities and invariants

1. Coverage and correctness, then maintainability, then speed. Duplicates cost
   reading time; silently missed jobs cost opportunities.
2. Employer-first collection. Enumerate registries and exchange lists; use
   aggregators to supplement coverage and discover employers. `roster.csv` is
   an audit set, never the universe.
3. Never delete or narrow the employer universe. Preserve acquired records and
   provenance. Geography affects priorities and board display, not ingestion.
4. Prefer false splits to false employer merges. A shared generic word or a
   portfolio company's careers link is not proof of employer identity.
5. Ingest broadly; classify stored evidence. Tags are derived and reversible.
   Raw acquisition records are retained. The board alone applies user gates.
6. Implausibly small or truncated results fail loudly. Verify pagination,
   advertised totals, and vendor payload shapes. Failed or partial polls must
   not withdraw records they did not visit.
7. Preserve human labels. CSV updates require a lock around the entire
   read-modify-write and atomic replacement. Never regenerate human verdicts.
8. Preserve detail enrichment when a list feed returns only a placeholder.
   Changed evidence must invalidate tags; unchanged polls need not re-tag.
9. Stop and raise any change that would violate these invariants.

## Scope and verification

Work methodically against explicit exit criteria. The current user request
covers methodology, labelling, code, performance, bugs, and documentation.
Do not add speculative sources; establish a coverage gap and verify the real
endpoint first. Use synthetic regressions for failures and real-corpus
comparisons for load-bearing changes. Compare card IDs and shortlist, not only
counts. Keep terminal output to results and warnings.

Third-party libraries are allowed if free, unmetered, and requiring no account
or API key. Prefer established libraries for ordinary glue. Pin dependencies in
`requirements.txt` and explain what they replace. Preserve documented throttle,
retry, name-matching, Unicode-folding, and vendor-specific behavior against its
incident corpus. Do not create accounts or register API keys.

## Execution and crawling

Use the Windows Python under `%LOCALAPPDATA%/Programs/Python/Python313`, with
`PYTHONIOENCODING=utf-8`; `run.ps1` and `run.sh` do this. Install
`requirements.txt`. The weekly pipeline runs only on this machine, scheduled
Wednesday 03:00 via `weekly.ps1`, using the logged-in user's profile.

The pipeline orders corrections, source reads, tag, bodies, tag, alerts, build.
Independent source reads share one process-wide throttle. Failure of one source
must not abandon others or the rebuild. Singapore and Hong Kong belong in
`--full`; their expensive complete sweeps are not optional.

At the user's standing instruction, robots exclusions may be read past under
`http.HOST_INTERVAL_S` (four seconds on those hosts) and at most weekly.
CAPTCHAs and WAF refusals remain closed: do not solve challenges, impersonate a
browser, change user agents to evade refusal, or probe thresholds. Obey 429
backoff; preserve its distinct schedule from 503 retries and retry mid-body
connection failures. Never expose `.env` or stored login credentials.

## Product and publishing

Geography and role scope are in [METHODOLOGY.md](METHODOLOGY.md). Preserve the
current inclusion/exclusion choices unless the user changes them. New York,
Chicago, and Boston are focus hubs; other US locations remain visible below them.
Student-only eligibility matters because the user has already graduated.

The board is static: private S3 and CloudFront, with the existing correction
Function. Keep `web/data.js` gitignored and omit unknown/default tag values;
missing keys already mean unknown. Build locally from SQLite. No scraper or
runtime database goes into CI. The public correction route remains bounded;
`labels.validate` owns vocabulary validation.

Commit each verified unit. **For this refactor, push and publish once at the
end**, per the user's explicit instruction. Remote `quantjobs`, branch `master`.
A code push deploys markup; `web/publish.py` separately deploys locally built
data. Preserve build floors and the check for CLI error text despite exit 0.
Classifier changes require a `tagging.TAGGER` bump and a re-tag before publication.
Function changes require their own deployment; a static publish is insufficient.

## Documentation

Keep current instructions short and authoritative. Store incident narratives and
old counts under `docs/history/`. Update PLAN when a stage closes. Put only
unresolved human decisions or manual work in ACTION-REQUIRED and remove items
when resolved. Preserve existing user choices without asking for them again.
