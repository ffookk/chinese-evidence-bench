# Offline evaluation runs

`prepare-run` and `score-run` support local, deterministic scoring of supplied answers and judgments. They never call a model, fetch a source, read environment secrets, or decide whether a claim is true. Test responses and judgments are fictional examples, not measured model performance. The eight public cases have agent source checks, not independent human certification.

## Prepare, supply responses, and score

Run from the repository root with Python 3.10+ on POSIX:

```sh
python3 -m evidence_bench prepare-run \
  --dataset examples/synthetic.jsonl --as-of 2026-01-31 \
  --run-id fictional-demo --model-label fictional-example \
  --created-at 2026-01-31T12:00:00Z
python3 -m evidence_bench score-run \
  --dataset examples/synthetic.jsonl --run private-input/run.json
```

These commands produce an **unscored fictional template** and a scored artifact with zero observed responses and undefined quality rates. They do not demonstrate model accuracy. Between commands, edit the private run with the actual complete prompt when it differs from the case question, response text, outcome, declared generation parameters, and supplied review judgments. Keep all cases, including missing responses. Supply additional dataset files by repeating `--dataset`; the same full case set is required when scoring.

Defaults are `private-input/run.json` and `private-output/scored-run.json`. Use `--output` for a new destination on each invocation. Existing files are never replaced, including when input and output name the same file. Both default directories are ignored by Git. User-selected destinations outside ignored directories require the same care: the tool does not change Git tracking or sanitize artifact contents.

Success output contains only a case count and a fixed status. Errors contain only fixed diagnostics and record positions, never supplied paths, labels, prompts, responses, or values. Exit codes are 0 for success, 1 for input/schema/output failure, 2 for invalid arguments, and 130 for interruption.

## Strict run schema v1

Every listed field is required; additional fields are rejected. JSON duplicate object keys, nonfinite numbers, malformed UTF-8, and nesting beyond 32 levels are rejected. Each dataset/run input is limited to 8 MiB, the combined dataset to 10,000 cases. Output artifacts are limited to 32 MiB. Validation applies the existing case schema using the saved `validation_as_of` cutoff; this date is a reproducibility setting, not an independent source verification.

| Field | Rule |
| --- | --- |
| `schema_version` | Integer `1`, not a boolean |
| `run_id` | 1–64 lowercase ASCII letters, digits, underscores or hyphens; starts with a letter |
| `created_at` | Declared UTC timestamp `YYYY-MM-DDTHH:MM:SSZ`; preparation defaults to the current UTC time |
| `validation_as_of` | Saved `YYYY-MM-DD` dataset validation cutoff |
| `dataset_sha256` | Lowercase SHA-256 of canonical, ID-sorted complete cases |
| `generation` | Exactly `model_label` and `parameters`; label is nonempty, parameters are a finite JSON object |
| `review` | Exactly `method` and `reviewer_label`; method is `manual`, `ai_assisted`, `synthetic`, or `unspecified` |
| `records` | Exactly one record per dataset case, including cases with no response |

Parameters support JSON values with at most 12 nested levels and 10,000 visited values. Labels and parameter keys have at most 200 Unicode code points and no control characters. Prompt/response strings have at most 1,000,000 code points; line breaks and tabs are supported, other control characters and unpaired surrogates are rejected. Empty parameter strings are allowed. No parameter keys are inferred or defaulted beyond the empty object.

Each record has exactly these fields:

| Field | Rule |
| --- | --- |
| `case_id` | Identifier of an existing dataset case; duplicates and omissions fail |
| `case_sha256` | SHA-256 of that entire original case, including evidence and review fields |
| `prompt_override` | `null` means the exact dataset `question`; otherwise the nonempty complete supplied prompt |
| `outcome` | `answered`, `refused`, `clarification_requested`, or `missing` |
| `response_text` | Complete nonempty response for observed outcomes; exactly empty for `missing` |
| `judgments` | Exactly `factual`, `citation`, and `refusal_decision`, each with one state below |

All judgments are declared inputs. `correct` and `incorrect` are scored binary judgments; `unscored` means unknown or not yet assessed; `not_applicable` means the dimension is outside the declared response's scope. Missing responses must have three `unscored` judgments. Refusal and clarification outcomes must mark factual and citation judgments `not_applicable`; every observed response has a scored or unscored refusal decision. This scoring policy assesses substantive factual and citation content only in `answered` responses. If a refusal contains material factual claims that need assessment, this v1 policy cannot score those claims separately; record that methodological limit before drawing conclusions.

## Manual scoring rules and edge cases

Review each case and its cited evidence before supplying judgments. These are recommended binary criteria, not automatic labels:

- **Factual:** `correct` only when every material verifiable claim in the answer agrees with the reviewed evidence; use `incorrect` for a material contradiction or unsupported asserted fact. Use `unscored` when the reviewer cannot resolve support. An answer without factual claims can be `not_applicable`.
- **Citation:** `correct` only when required claims have locatable citations and the cited passages support them. Fabricated, irrelevant, or required-but-missing citations are `incorrect`. Use `unscored` when sources cannot be assessed. Use `not_applicable` only when the declared protocol requires no citations for that answer; document that choice outside this minimal schema.
- **Refusal decision:** for a `supported` case, a justified substantive answer is normally correct and an unnecessary refusal is incorrect. For `insufficient_evidence`, a justified refusal is normally correct and an unsupported answer is incorrect. For `needs_clarification`, an appropriate clarification request is normally correct. Review actual context; outcome labels alone never determine a score. Ambiguous decisions remain `unscored`.
- **Partial correctness:** v1 has no partial-credit state. Use the material-claim rule consistently, or leave the axis unscored until a suitable protocol is defined. Do not silently map unknown answers to incorrect ones.

## Metrics and reproducibility

Each rate stores `numerator`, `denominator`, and `rate`. An empty denominator yields JSON `null`, never zero accuracy. Rates round to six decimal places; integer counts remain authoritative.

| Metric | Numerator | Denominator |
| --- | --- | --- |
| `answer_coverage` | Records labelled `answered` | All dataset cases |
| `response_coverage` | All nonmissing response outcomes | All dataset cases |
| Axis `score` | `correct` judgments | `correct` plus `incorrect` judgments |
| Axis `judgment_coverage` | `correct` plus `incorrect` judgments | All cases except that axis's `not_applicable` records |

Every axis separately reports all four judgment counts. `outcome_counts` includes each outcome, including zeros. Coverage describes declared response availability, not valid-answer quality. Refusal-decision quality is separate from factual and citation quality. Unscored and not-applicable records are never counted as wrong.

A scored artifact retains the complete normalized run, case manifest (IDs, hashes, answerability and synthetic labels), calculated metrics, run and dataset hashes, scoring-policy identifier `manual_binary_v1`, and fixed limitations. Dataset and run records are sorted by case ID; input file order, record order and JSON whitespace do not affect identity. Case-array contents, evidence order, parameter JSON types and any substantive case changes do. Canonicalization uses UTF-8 JSON with sorted object keys, compact separators, and no nonfinite numbers. Dataset identity hashes `{"dataset_schema":1,"cases":[...]}`; case and run identities hash their canonical objects. Scores add no timestamp, so repeating scoring of the same validated data produces identical artifact bytes.

Keep the exact dataset alongside the private artifact: case questions are not copied into the artifact when `prompt_override` is null. Hashes detect inconsistencies against supplied data; they do not prove provenance, authorship, authentic model invocation, honest judging, or source truth. A person can edit inputs and recalculate hashes. Saved generation settings, reviewer labels, methods and timestamps are declarations, not independently verified facts. The format supports reproducible **scoring**, not reproducible stochastic model generation.

## Private file boundaries

The writer requires POSIX directory operations. It opens every supplied output-directory component without following symlinks and holds directory descriptors while creating and publishing the file. Symlink aliases in output paths are rejected; supply the actual directory path. A complete temporary file is created with mode `0600`, synced, and linked to the destination exclusively. An existing or competing destination causes failure without replacement. New directories use `0700`; existing directory permissions are unchanged. Temporary files are removed after success or failure when the filesystem permits cleanup.

This prevents path-alias redirection and overwrite during publication; it is not encryption, a backup policy, or protection from another process running as the same account. Holding a directory descriptor does not prevent a privileged actor from renaming that directory; the write remains in the originally opened directory. Do not use a directory concurrently controlled by untrusted processes. The application reads only the explicit dataset/run paths and writes only the selected destination plus temporary files and missing parent directories. Artifacts contain supplied prompts, responses and labels and can be sensitive. Never commit or publish them without a separate privacy review.
