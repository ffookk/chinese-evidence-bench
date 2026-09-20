# Roadmap

Completed items are checked below. Fictional format fixtures do not count as real benchmark data. Model evaluation and experiments remain unimplemented. Published fixtures are in English and do not provide Chinese-language evaluation coverage.

## PR 1: Data format and initial cases

- [x] Define the JSON/JSONL format, unique identifiers, source locations, and time-related fields (see the [v1 data format](docs/data-format.md)).
- [x] Build an offline validator that detects missing fields, duplicate identifiers, invalid dates, and contradictory review states.
- [x] Add 3 entirely fictional format fixtures and focused standard-library tests.
- [x] Add 8 public-fact cases checked against original sources by an agent, individual source-review notes, a real, reviewed-case gate, and cross-file ID checks.
- [ ] Independently review the first 8 cases with a human reviewer; their current `reviewed` state reflects agent review, not human certification.
- [ ] Build 30 independently reviewed real evidence cases with English questions and answers, including sufficient- and insufficient-evidence cases. Any future Chinese-language evaluation must use separately reviewed local translations outside version control unless the public language policy changes; current English fixtures do not establish that coverage.

Acceptance: each answer can be traced to supporting original evidence; the validator detects actual data errors; review states are explicit.

## PR 2: Reproducible evaluation

- [ ] Save model identifiers, inputs, outputs, run parameters, and timestamps.
- [ ] Define factual errors, citation errors, correct refusals, and unnecessary refusals separately.
- [ ] Report answer coverage and publish human scoring rules and edge cases.

Acceptance: another contributor can recalculate the same scores from saved run records. Distinguish reproducible scoring from reproducibility of stochastic model generation.

## PR 3: An improvement experiment

- [ ] Compare performance with and without retrieval on the same test set and scoring rules.
- [ ] Save retrieved source locations and evidence-version information available at the time.
- [ ] Report quality, coverage, and cost together, including cases that did not improve.

Acceptance: experimental conclusions are traceable to individual case results, with sample size, scope, and sources of error stated explicitly.
