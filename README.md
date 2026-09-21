# Chinese Evidence Bench

Tools for checking factual accuracy, citation support, and refusal behavior in AI answers, with a long-term focus on Chinese-language evaluation backed by original evidence.

## Current status

The repository implements a v1 case format, an offline JSON/JSONL validator, and standard-library tests. It contains **8 public-fact cases** drawn from 5 original documents (see the [source review](docs/source-review.md)), plus 3 entirely fictional fixtures marked `synthetic`. An AI agent opened the original sources and checked the public cases individually. **There has been no independent human certification, model evaluation runner, model experiment, or published evaluation score.**

Published questions, answers, and documentation are in English. These English-language fixtures do not establish Chinese-language evaluation coverage; the validator accepts Unicode text without detecting its language. Future Chinese-language evaluation should use locally translated inputs kept outside version control unless the public language policy changes. Translations need their own review; their existence alone does not establish evaluation coverage.

## Local usage

Python 3.10+ is required, with no additional dependencies. Run from the repository root:

```sh
python3 -m evidence_bench validate examples/synthetic.jsonl
python3 -m evidence_bench validate data/public-facts.jsonl --real-only --require-reviewed
python3 -m evidence_bench validate examples/synthetic.jsonl data/public-facts.jsonl
python3 -m evidence_bench validate examples/synthetic.jsonl data/public-facts.jsonl --summary
python3 -m unittest discover -s tests -v
```

Use `python3 -m evidence_bench validate --help` to view validation options. Scripts can use these exit codes:

| Exit code | Meaning |
| --- | --- |
| `0` | Validation passed, or help was displayed normally |
| `1` | An input file could not be read, or case validation failed |
| `2` | Invalid command-line arguments |

The command accepts `.json` arrays of cases and `.jsonl` files with one case per line. Pass multiple files to check for duplicate IDs across files. `--as-of YYYY-MM-DD` fixes the date cutoff; `--require-reviewed` excludes pending records, and `--real-only` excludes synthetic records. The public-fact file passes the latter two options; the fictional fixtures fail them as expected. `reviewed` means only that the review disclosed in the batch notes was completed; it does not imply human certification.

Add `--summary` to append aggregate counts after the usual PASS line. Its `SUMMARY: ` prefix is followed by a JSON object with seven fixed keys: `real`, `synthetic`, `reviewed`, `pending`, `supported`, `insufficient_evidence`, and `needs_clarification`. Counts cover all supplied files, include zero values, and contain no case IDs, text, source URLs, or paths. Any validation error suppresses the summary; strict flags still apply. Counts describe record labels, not factual accuracy or independent human review.

Passing validation establishes only that the format and state combinations are valid. It does not prove source authenticity, factual correctness, or the absence of personal information. The tool does not access the network, read environment variables, call models, or save inputs or run logs. See the [v1 data format](docs/data-format.md) and [fixture notes](examples/README.md) for the complete rules and limitations.

See [input and diagnostic notes](docs/usage-notes.md) for more command details.

## Additional CLI options

- `python3 -m evidence_bench --version` reports the package version and supported schema, not a new release tag. Invalid arguments receive a fixed, value-free error message.
- `validate --quiet` suppresses the ordinary PASS line. Explicit summaries and statistics remain visible; errors are retained.
- `validate --json-summary` emits only the same seven counters as one JSON object. It cannot be combined with `--summary`.
- `validate --expect-cases N` requires exactly N parsed cases. Numeric limits accept 1–9 ASCII decimal digits; errors still suppress every report.
- `validate --min-sources N` requires N evidence entries per case, including uncertain cases.
- `validate --require-answerability STATE` requires the selected schema answerability state throughout the batch.

## Problem

Models may produce incorrect facts, invent sources, or cite real pages that do not support their claims. A single accuracy score cannot distinguish these failures. The project plans to retain questions, answers, original evidence, review dates, and evidence locations so that cases can be reviewed and evaluations reproduced.

## Initial scope

1. Define the data format and build 30 independently reviewed, reliably sourced evidence cases, with questions and answers published in English.
2. Record model versions, complete inputs, raw answers, and run settings to establish a repeatable evaluation process.
3. Compare results on the same questions with and without retrieval, reporting quality, answer coverage, and cost.

See [ROADMAP.md](ROADMAP.md) for tasks and acceptance criteria.

## Case fields

| Field | Meaning |
| --- | --- |
| `id` | Stable, unique case identifier |
| `schema_version` / `synthetic` | Format version and whether the case is entirely fictional |
| `question` | Question and necessary context; published fixtures use English |
| `reference_answer` | Reference answer when evidence is sufficient; `null` when evidence is insufficient or clarification is required |
| `evidence` | Sources, each with `source_url`, `source_title`, and `evidence_locator` |
| `verified_at` | Most recent evidence review date; the method and scope are disclosed in the batch notes |
| `time_sensitive` / `valid_as_of` | Whether the answer depends on time, and its applicable date |
| `answerability` | Sufficient evidence, insufficient evidence, or clarification required |
| `review_status` | Pending or reviewed |

All fields are required. Use `null` for nullable values. The [v1 data format](docs/data-format.md) defines types, states, dates, and source constraints. Evidence locations should be precise enough for review without unnecessarily copying copyrighted material in full.

## Evaluation dimensions

- **Factual accuracy:** whether verifiable claims agree with the evidence.
- **Citation support:** whether citations exist and support their associated claims.
- **Refusal behavior:** whether the model appropriately declines when evidence is insufficient, or unnecessarily declines when it is sufficient.
- **Answer coverage:** the proportion of valid answers, reported alongside quality metrics.
- **Experiment cost:** the applicable time, token, or monetary measures and their calculation methods.

Define scoring rules, denominators, and edge cases before running experiments. Increased refusal must not conceal quality problems.

## Reference project

- [HaluEval](https://github.com/RUCAIBox/HaluEval): a potential evaluation reference identified during initial planning.

This link does not mean its data has been imported or verified here. Check scope, licensing, and provenance before using external material.

## Contributing

Start with a small, reviewable change, follow [CONTRIBUTING.md](CONTRIBUTING.md), and use the repository's PR template. Keep public contributions in English. Real account details, API keys, private conversations, and personal records must not enter fixtures or commit history.
