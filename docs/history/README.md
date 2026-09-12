# Historical evidence

These snapshots preserve incident evidence and prior decisions from before the
September 2026 refactor. They contain obsolete instructions, counts, paths, and
claims. Current policy is in [METHODOLOGY.md](../../METHODOLOGY.md), operational
instructions in [README.md](../../README.md), and agent rules in [AGENTS.md](../../AGENTS.md).

- [Engineering incidents](engineering.md): vendor payload quirks, identity mistakes,
  throttling incidents, classifier counterexamples, and earlier measurements.
- [Stages 0–48](stages.md): implementation history and measurements at each stage.
- [Tagging design](tagging.md): earlier evaluation criteria and sampling rationale.
- [Prior decisions](decisions.md): original record of user choices and resolved items.
- Original acquisition proposal: local, gitignored `original-methodology.md`,
  containing hypotheses before implementation. The comparison is recorded in
  [REFACTOR-METHODOLOGY.md](../../REFACTOR-METHODOLOGY.md).

Consult the relevant incident before changing a vendor parser, name matcher,
throttle, confusable-character folding, or display gate. Historical prose is
evidence to test, not permission to override current instructions.
