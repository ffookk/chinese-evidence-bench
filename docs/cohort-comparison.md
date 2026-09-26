# Compare a private cohort of scored runs

`compare-cohort` compares 2–16 existing scored runs against one explicit baseline. It recomputes every artifact from the same complete dataset before using any stored metric. The output separates each baseline pair's jointly scored cases from the cases scored in **every** run. This makes it possible to inspect several local experiments without concealing differences in coverage or choosing a winner automatically.

This is descriptive analysis of supplied judgments. It does not invoke a model, retrieve evidence, authenticate declarations, test significance, or establish a controlled experiment. The command is available through the Python API and CLI; the browser workbench continues to compare two runs at a time.

## Create and verify a report

Prepare each source with the [offline evaluation workflow](offline-evaluation.md), assigning a different `run_id` and private output path. The baseline is a scored artifact, not an unscored run template. Include each candidate once:

```sh
python3 -m evidence_bench compare-cohort \
  --dataset examples/synthetic.jsonl \
  --baseline private-output/fictional-a-score.json \
  --run private-output/fictional-b-score.json \
  --run private-output/fictional-c-score.json \
  --output private-output/cohort.json

python3 -m evidence_bench compare-cohort \
  --dataset examples/synthetic.jsonl \
  --baseline private-output/fictional-a-score.json \
  --run private-output/fictional-c-score.json \
  --run private-output/fictional-b-score.json \
  --verify-report private-output/cohort.json
```

The second invocation recomputes the complete report from the dataset and all three scored artifacts. It compares every field, including metrics, source identities, setup differences, strata and limitations; trusting only an embedded checksum would be insufficient. It writes no files. Candidate argument order does not affect the result. A changed baseline, added or removed candidate, modified response, mismatched metric, extra report field or changed policy fails verification. JSON object key order and formatting are irrelevant, while JSON numeric types remain part of canonical identity.

Repeat `--dataset` to supply the complete dataset across several files. All runs must use the same dataset fingerprint, case fingerprints, complete case set, scoring policy and `validation_as_of` cutoff. Different `created_at` timestamps, model labels, prompts, parameters and reviewer declarations are permitted and their differences are disclosed. Duplicate run identifiers or fingerprints are rejected, including an accidental repeat of the baseline as a candidate. Distinct run IDs do not prove independently obtained responses or independent samples.

`--output` defaults to `private-output/cohort.json`. It cannot be combined with `--verify-report`. The command uses the existing private writer: mode `0600`, new parent directories `0700`, no file replacement, no symlink output ancestors, and no partial destination on ordinary validation or size failure. Use a new destination for every report. Successful stdout contains run/case counts and a fixed status; failures contain value-free diagnostics. Exit codes remain 0 for success, 1 for source/report/output errors, 2 for invalid arguments, and 130 for interruption.

## Understand the three denominators

Every axis is evaluated independently. A case qualifies as scored only for `correct` or `incorrect`; neither `unscored` nor `not_applicable` is treated as zero accuracy.

| View | Eligible cases | Meaning |
| --- | --- | --- |
| Per-run metrics | That run's own scored cases for the axis | Full original quality and coverage with a potentially different denominator for each run |
| Baseline pair | Cases scored in both baseline and that candidate | Descriptive improvement/regression and rates on the same cases for that pair |
| All-run common quality | Cases scored in every supplied run for the axis | Per-run rates on one shared intersection across the entire cohort |

For example, suppose the fictional factual judgments for three case IDs are:

| Run | Case 1 | Case 2 | Case 3 |
| --- | --- | --- | --- |
| Baseline A | correct | correct | incorrect |
| Candidate B | unscored | incorrect | correct |
| Candidate C | correct | unscored | incorrect |

A versus B uses cases 2 and 3; A versus C uses cases 1 and 3. Both pairs have rates of 1/2 versus 1/2. The common intersection for all three runs contains only case 3, with A=0/1, B=1/1 and C=0/1. These values describe their specific denominators; they are not a general ranking. Adding a run can shrink the intersection and change common rates without changing any earlier response or judgment. An empty intersection produces numerator 0, denominator 0 and rate `null` for every run; baseline deltas are also `null`.

The report retains each axis's eligible case IDs so the subset is inspectable. `excluded_cases` counts cases outside the intersection once. `excluded_by_run` counts each run's own unscored and not-applicable cases; those counts **overlap and must not be summed**. Changes to outcome availability and applicability labels remain visible separately from score changes.

## Report contract and reproducibility

The additive report uses `schema_version: 1`, `artifact_type: cohort_comparison` and `cohort_policy: baseline_common_binary_v1`. Existing case, run and scored-artifact formats are unchanged.

| Field | Contents |
| --- | --- |
| `dataset_sha256`, `validation_as_of`, `scoring_policy` | Shared source and validation context |
| `baseline`, `runs` | Run IDs and canonical run SHA-256 values; baseline first, then ascending candidate IDs |
| `cohort_sha256` | Fingerprint of policy/context, selected baseline and ordered run identities; it binds the inputs, not the report's derived fields |
| `case_manifest` | Complete case IDs, hashes, answerability and synthetic labels |
| `sample_scope` | Case, synthetic/real and reviewed/pending counts; labels do not certify authenticity or human review |
| `baseline_setup_comparisons` | Per-candidate declaration flags, changed effective-prompt count and applicability-label transitions |
| `aggregate.run_metrics` | Each run's full outcome, quality and coverage metrics |
| `aggregate.baseline_pairs` | Each candidate's existing paired-comparison aggregate, with baseline on the left and candidate on the right |
| `aggregate.all_run_common_quality` | Per-axis common case IDs, explicit denominator, per-run scores and rate deltas from baseline, exclusions |
| `strata` | The same complete group reports for each answerability label and each synthetic/real group |
| `limitations` | Fixed interpretation and privacy boundaries |

Empty strata remain present with undefined rates. Each dimension is a separate view; do not sum across answerability and synthetic strata. All counts are integers, rates round to six decimals, and no new timestamp is added. Supplied integers retain their precision, including values outside JavaScript's safe integer range. Parameters `1` and `1.0` retain different identities, matching the existing scoring/comparison rules. Setup flags compare effective prompts after replacing null overrides with the dataset question; repeating the exact default prompt is not a change.

The implementation uses no new dependency and makes no network requests. Inputs are bounded to 16 scored artifacts including baseline, 32 MiB per artifact and 64 MiB combined. CLI combined limits include whitespace in the original UTF-8 files; the Python API checks their canonical representations. Dataset limits remain 8 MiB per file and 10,000 total cases. Output and report-verification input are limited to 32 MiB; the byte limits are not a promise that the process uses only that amount of memory. Oversized reports fail without a partial destination. Comparison work grows with runs and cases, not with every possible pair of runs.

For programmatic use:

```python
from evidence_bench.cohort import compare_cohort, verify_cohort

report = compare_cohort(dataset, scored_artifacts, baseline_id="fictional-a")
verified = verify_cohort(
    dataset, scored_artifacts, report, baseline_id="fictional-a"
)
```

Use a `Dataset` returned by `evaluation.load_dataset` and scored artifacts from `evaluation.score_run` or strict `evaluation.read_json`. Both functions verify all supplied scored artifacts and raise `EvaluationError` on inconsistency. They leave caller inputs unchanged. `verify_cohort` returns the independently recomputed report, not the untrusted input object.

## Fully fictional local example

The following creates the three source files used above from the repository's existing fictional cases. These hand-authored judgments are an arithmetic demonstration; they deliberately do not assess the fixture answers and must never be described as model results. It refuses to overwrite existing output files.

```sh
python3 - <<'PY'
from pathlib import Path
from evidence_bench import evaluation as ev

dataset = ev.load_dataset([Path("examples/synthetic.jsonl")], "2026-01-31")
fictional = {
    "fictional-a": ["correct", "correct", "incorrect"],
    "fictional-b": ["unscored", "incorrect", "correct"],
    "fictional-c": ["correct", "unscored", "incorrect"],
}
for identifier, judgments in fictional.items():
    run = ev.prepare_run(
        dataset, run_id=identifier, model_label="fictional-demo",
        created_at="2026-01-31T12:00:00Z",
    )
    run["review"] = {"method": "synthetic", "reviewer_label": "fictional-demo"}
    for record, judgment in zip(run["records"], judgments):
        record.update(outcome="answered", response_text="Fictional demonstration.")
        record["judgments"] = {
            "factual": judgment,
            "citation": "unscored",
            "refusal_decision": "correct",
        }
    ev.write_private_json(
        Path("private-output") / (identifier + "-score.json"),
        ev.score_run(dataset, run),
    )
PY
```

Then run the creation and verification commands above. Keep the original dataset and scored artifacts with the report so it can be recomputed later. The report omits raw responses, prompts, source URLs, model/reviewer labels and parameter values. It still contains case/run IDs, hashes, judgments-derived metrics and setup-change flags, which may identify private work. Keep it in ignored private directories and separately review it before any publication. Hashes and verification are consistency checks, not signatures, anonymization or proof of truthful inputs.
