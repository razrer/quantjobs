# Human input still needed

## Independent audit labels

The focused development sample cannot measure errors in records it excludes.
The new `sample --audit` command draws without those filters. Review a separate
local `audit-labels.csv`, flag unavailable evidence, and keep it held out from rule tuning until
scored. The refactor can supply sampling and tests but cannot supply independent
human ground truth or claim an improved recall score without it.

Prior decisions are preserved in [history](docs/history/decisions.md); current
policy is in [METHODOLOGY.md](METHODOLOGY.md).
