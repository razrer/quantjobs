# Tagging and human evaluation

`quantscraper/tagging.py` assigns independent dimensions using the deterministic
multilingual vocabulary in `lexicon.py`. Evidence stays in SQLite; rejects are
retained. The board applies display gates after classification.

## Dimensions and evidence

Run `./run.ps1 list --dimensions` for the authoritative values. Main dimensions:

| Dimension | Question |
|---|---|
| relevance / role_class | How relevant is the work, and what kind of role is it? |
| seniority / experience_floor | What level and minimum experience are stated? |
| code_depth / language | What programming work and tools are required? |
| contract / hard_gates | What employment type and eligibility requirements apply? |
| hub / posting_language / spoken_language | Where is it, what language is the ad, and what languages are required? |
| desk / asset_class / horizon / trading_style | What markets work does it involve? |
| exclusion_reason / fit | Why is it ranked or hidden, and how actionable is it? |

Multi-valued dimensions include hub, asset_class, hard_gates, horizon, language,
spoken_language, and exclusion_reason. Unknown evidence stays explicitly unknown
in the database; default values are omitted from the static board payload.

Match token boundaries after the established Unicode folding. Preserve genuine
CJK and Greek text when handling confusable Latin characters. Titles, departments,
bodies, and employer profiles are different evidence sources: a boilerplate
markets word does not necessarily describe the role. Confidence describes the
rule's evidence strength, not a calibrated probability.

Internship is a contract, student-only is eligibility, and seniority is a level.
A job can have multiple locations. National-board readers must supply country
context where a town alone is ambiguous. Unrecognized taxonomy labels pass.

## Storage and refresh

`job_tags` stores posting identity, dimension, value, confidence, evidence, tagger
version, and timestamp. Its primary key omits the version: it is a current derived
view, not a reliable historical comparison store. Save a fixed-corpus output
snapshot before changing rules.

Bump `TAGGER` for classifier changes and run `tag` before rebuilding. Polling
changes to classification inputs invalidate stored tags; unchanged polls preserve
them. Detail fetching also invalidates tags. The daily sequence intentionally runs
`tag`, then `bodies`, then `tag` again.

## Two samples for different questions

```powershell
./run.ps1 sample --limit 100
./run.ps1 sample --audit --limit 100 --out audit-labels.csv
./run.ps1 labels --file audit-labels.csv
```

The default sample focuses human effort on plausible markets roles and contested
cases, with a cap per `(ats, token)`. It is development evidence and cannot measure
errors among the rows its language, vocabulary, and display filters remove.

The audit sample uses a stable hash of posting identity across retained jobs not
explicitly marked removed. It does not consult tags or filter geography, language,
URLs, or occupations. Some ads will be stale or unreadable: flag unavailable
context in notes and report that separately. Do not treat them as correct rejects.
The sample concerns retained records, not the unobserved employer universe.

Use a separate audit sheet and freeze it before tuning. Do not mix development
labels into it or repeatedly tune against it while calling it held-out evidence.
After using audit cases to improve rules, reserve new independently reviewed cases
for the next evaluation. Blinded sheets omit predictions and scatter row order.

Fill `relevance`, `seniority`, and optional `note`; do not edit the posting keys.
Label from the actual role requirements. Under-specified evidence may warrant
an unknown seniority or an unfilled relevance with a note; a title alone cannot
establish every eligibility requirement.

## Read the scores honestly

`labels` reports agreement, disagreements, and seniority containment. Human,
automatic, and agent-authored sheets are reported separately. Inspect false
rejections and the display gates that hide human-positive jobs. Historical scores
were measured on earlier development samples, not on an independent population
sample, and are not current recall estimates.

No false rejection in a finite sample proves zero missed jobs. Report the sample
frame, unavailable evidence, and relevant source/language/location slices. The
independent audit still needs human labels before a new accuracy claim is possible.

## Label durability

Human sheets are inputs, never generated verdicts. Redraws preserve completed rows,
refuse to erase a label whose posting is missing, and share the correction writer's
lock around the entire read-modify-write. Replacement is atomic and UTF-8 with BOM
for Excel. The lock protects threads in one process; avoid concurrent writers in
separate processes. Back up human sheets independently of derived data.

[Historical rule decisions and counterexamples](docs/history/tagging.md) explain
why particular exclusions and evidence boundaries exist.
