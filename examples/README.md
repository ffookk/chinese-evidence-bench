# Entirely fictional format fixtures

`synthetic.jsonl` contains only 3 format fixtures created for tool development. **They are not real-world facts, real benchmark data, human evaluation results, or records of actual verification.** The information station, rules, dates, and review states are fictional. Dates and states exercise format branches only. Every source uses a reserved `.invalid` domain and cannot be accessed as an online source. The fixtures are published in English and do not establish Chinese-language evaluation coverage.

From the repository root, run `python3 -m evidence_bench validate examples/synthetic.jsonl --as-of 2026-01-31` to check these fixtures using a fixed date cutoff.

The complete fictional rule referenced by the first two cases is this single paragraph:

> Fictional rule, paragraph 1: From January 10, 2026, each test kit at the fictional Paper Moon information station contains three wooden discs.

The first case demonstrates a candidate reference answer with an evidence locator and a `reviewed` state. The second demonstrates a pending insufficient-evidence case: the rule's silence about metal kits does not prove that none were ever made. The third demonstrates an unclear reference requiring clarification; do not invent a reference answer.

Before editing these fixtures, consult the [field and source constraints](../docs/data-format.md).

Do not copy this directory into the real-data directory and change `synthetic` to `false`. Real cases require independently collected sources, review of personal information and redistribution permissions, and completed human verification.
