# Refactor results — September 2026

## What changed

- Preserved resolved Workday locations when list polls return a count placeholder.
- Invalidated derived tags when source evidence changes; unchanged polls retain tags.
- Rotated limited ATS and careers-page queues by attempt age, including failures.
  Shared ATS boards are polled once per queue rather than once per employer alias.
- Added a separate audit sample without classifier, language, geography, or URL
  filters. Repaired quota rounding, board identity in sampling, a redraw race,
  and loss of labels when their posting is missing.
- Refused unversioned lexicon drift without erasing its recorded fingerprint.
- Built from one indexed temporary metadata snapshot; descriptions are fetched
  only for candidates that pass existing gates. Consolidated duplicate clustering.
- Made board-file replacement atomic and checked the tagger version on publication.
- Anchored relative posting dates to the source poll, preventing jobs from becoming
  apparently newer merely because the board was rebuilt tomorrow.
- Replaced duplicate operational narratives with concise current guides and linked
  historical evidence. The original independent proposal remains identifiable.

## Verification

The baseline had **1,112 passing tests**. The completed implementation has
**1,130 passing tests**. Existing tests emit Python 3.13 unclosed-connection
ResourceWarnings; these did not cause failures. Source health reports all sources
healthy.

The initial build correctly refused publication because **20,835 existing postings
had no current tags**. Classifying that backlog wrote 334,674 tags without changing
classification rules. The readable board rose from 4,690 to **4,854 cards**, and
the shortlist from 215 to **216**. This is backlog completion, not a claimed
accuracy improvement or a performance-refactor effect.

On that completed database, the original builder took **286.90 seconds**.
An initial hashing-only optimization took 296.72 seconds: no demonstrated speedup.
Profiling located about 90 seconds in employer profiling and 40 seconds in board
domain grouping. Replacing repeated wide-table reads with indexed build-local
metadata brought the build to **129.79–144.12 seconds**, about **2.0–2.2× faster**.
The temporary table consumes RAM during the build and disappears when it closes;
there is no permanent database duplication or new dependency.

With both database and calendar date held fixed, the entire optimized payload
matched the original: card IDs, ordering, every card field, firms, and gate counts.
The separate date correction intentionally changes relative posting dates and
therefore may change date ordering; it does not alter classification rules.
The final release comparison confirmed **1,224 corrected posting-date fields**,
zero changed card identities, zero other changed card fields, and unchanged firms,
card count, and shortlist.

The existing human sheet scored 387 postings: relevance agreement **241/385
(62.6%)**, **zero false rejections**, 95 unanswered relevance cases, and leadership
containment **14/16**, with zero openings lost to the rank gate. The historical
90% agreement criterion is **not met**. These development labels do not establish
independent recall. A new 100-row local `audit-labels.csv` awaits human
review and must not be presented as ground truth before it is labelled.

## Limits

This is an implemented refactor with regression and real-corpus checks, not proof
that every external adapter is bug-free or every vacancy is observable. No new
vendor adapter or speculative paid service was added. Existing lost location
names still need subsequent detail fetches; retaining future values cannot
reconstruct past evidence. Human-label locking remains process-local. Historical
incident material is preserved under [history](history/README.md).

Local verification logs and before/after payloads are in `logs/refactor-*` and
remain gitignored. Code commits are pushed together and data published once at
the end of the task; the task's delivery confirmation records the release outcome.
The generated audit sheet and imported personal methodology snapshot also remain
local and gitignored; they are not part of the source-code publication.
