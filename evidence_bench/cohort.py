"""Source-bound, descriptive multi-run comparisons; no ranking or inference."""

from pathlib import Path

from . import comparison as paired
from . import evaluation as ev
from .validator import ANSWERABILITY

COHORT_POLICY = "baseline_common_binary_v1"
MAX_COHORT_RUNS = 16
MAX_COHORT_INPUT_BYTES = 64 * 1024 * 1024
LIMITATIONS = paired.LIMITATIONS + [
    "The baseline is explicitly selected; candidates are ordered by identifier, never by score.",
    "Baseline pairs use their own jointly scored cases; all-run common quality uses the intersection scored in every run for that axis.",
    "Adding a run can shrink the common intersection and change common rates without changing any earlier responses or judgments.",
    "Per-run exclusion counts overlap; they must not be added to obtain the number of excluded cases.",
    "Run and case identifiers and fingerprints remain potentially identifying; keep reports private even though raw responses and declared labels are omitted.",
    "Report verification establishes reproducibility from the supplied sources, not authenticity or independent review.",
]


def _run_count(count):
    if not 2 <= count <= MAX_COHORT_RUNS:
        raise ev.EvaluationError("cohort: expected between 2 and 16 scored runs including the baseline.")


def _sources(dataset, artifacts, baseline_id):
    """Validate before aggregation and retain canonical integer/float identities."""
    if not isinstance(artifacts, (list, tuple)):
        raise ev.EvaluationError("cohort: expected a bounded array of scored artifacts.")
    _run_count(len(artifacts))
    if not isinstance(baseline_id, str):
        raise ev.EvaluationError("cohort: baseline identifier must name one supplied run.")
    verified = {}
    fingerprints = set()
    total = 0
    for artifact in artifacts:
        size = len(ev.canonical(artifact))
        total += size
        if size > ev.MAX_ARTIFACT_BYTES or total > MAX_COHORT_INPUT_BYTES:
            raise ev.EvaluationError("cohort: scored input exceeds the byte limit.")
        result = ev.verify_scored(dataset, artifact)
        identifier = result["run"]["run_id"]
        if identifier in verified or result["run_sha256"] in fingerprints:
            raise ev.EvaluationError("cohort: duplicate run identifier or fingerprint.")
        verified[identifier] = result
        fingerprints.add(result["run_sha256"])
    if baseline_id not in verified:
        raise ev.EvaluationError("cohort: baseline identifier must name one supplied run.")
    return [verified[baseline_id]] + [verified[key] for key in sorted(verified) if key != baseline_id]


def _identity(artifact):
    return {"run_id": artifact["run"]["run_id"], "run_sha256": artifact["run_sha256"]}


def _common_quality(cases, records, identities, axis):
    eligible = [index for index in range(len(cases)) if all(run[index]["judgments"][axis] in paired.SCORED for run in records)]
    correct = [sum(run[index]["judgments"][axis] == "correct" for index in eligible) for run in records]
    denominator = len(eligible)
    return {
        "eligible_cases": denominator,
        "eligible_case_ids": [cases[index]["id"] for index in eligible],
        "excluded_cases": len(cases) - denominator,
        "scores": [{
            **identity,
            "score": ev.ratio(numerator, denominator),
            "rate_delta_from_baseline": round((numerator - correct[0]) / denominator, 6) if denominator else None,
        } for identity, numerator in zip(identities, correct)],
        "excluded_by_run": [{
            **identity,
            "unscored": sum(record["judgments"][axis] == "unscored" for record in run),
            "not_applicable": sum(record["judgments"][axis] == "not_applicable" for record in run),
        } for identity, run in zip(identities, records)],
    }


def _group(cases, records, identities):
    return {
        "sample_size": len(cases),
        "run_metrics": [{**identity, "metrics": ev.metrics_for(run)} for identity, run in zip(identities, records)],
        "baseline_pairs": [{
            "candidate": identity,
            **paired._comparison(records[0], run),
        } for identity, run in zip(identities[1:], records[1:])],
        "all_run_common_quality": {axis: _common_quality(cases, records, identities, axis) for axis in ev.AXES},
    }


def compare_cohort(dataset, artifacts, *, baseline_id):
    """Recompute sources and return a stable report without mutating inputs.

    The baseline comes first; other runs use ascending run_id. Captured timestamps
    may differ, but dataset content and validation dates must agree. Raw response,
    prompt, model/reviewer labels, and parameter values are never copied.
    """
    verified = _sources(dataset, artifacts, baseline_id)
    identities = [_identity(artifact) for artifact in verified]
    records = [artifact["run"]["records"] for artifact in verified]

    def group(predicate):
        positions = [index for index, case in enumerate(dataset.cases) if predicate(case)]
        return _group([dataset.cases[index] for index in positions], [[run[index] for index in positions] for run in records], identities)

    cohort_identity = {
        "cohort_policy": COHORT_POLICY,
        "scoring_policy": ev.SCORING_POLICY,
        "dataset_sha256": dataset.sha256,
        "validation_as_of": dataset.validation_as_of,
        "baseline": identities[0],
        "runs": identities,
    }
    synthetic = sum(case["synthetic"] for case in dataset.cases)
    reviewed = sum(case["review_status"] == "reviewed" for case in dataset.cases)
    return {
        "schema_version": ev.SCHEMA_VERSION,
        "artifact_type": "cohort_comparison",
        **cohort_identity,
        "cohort_sha256": ev.fingerprint(cohort_identity),
        "sample_scope": {"cases": len(dataset.cases), "synthetic": synthetic, "real": len(dataset.cases) - synthetic, "reviewed": reviewed, "pending": len(dataset.cases) - reviewed},
        "case_manifest": verified[0]["case_manifest"],
        "baseline_setup_comparisons": [{
            "candidate": identity,
            "declared_setup_changes": paired.declared_setup_changes(dataset, verified[0]["run"], artifact["run"]),
            "applicability_label_changes": paired.applicability_changes(records[0], run),
        } for identity, artifact, run in zip(identities[1:], verified[1:], records[1:])],
        "aggregate": _group(dataset.cases, records, identities),
        "strata": {
            "answerability": {state: group(lambda case, state=state: case["answerability"] == state) for state in sorted(ANSWERABILITY)},
            "synthetic": {"synthetic": group(lambda case: case["synthetic"]), "real": group(lambda case: not case["synthetic"])},
        },
        "limitations": list(LIMITATIONS),
    }


def verify_cohort(dataset, artifacts, report, *, baseline_id):
    """Check every report field against current supplied source recomputation."""
    expected = compare_cohort(dataset, artifacts, baseline_id=baseline_id)
    if ev.canonical(report) != ev.canonical(expected):
        raise ev.EvaluationError("cohort report: content does not match source recomputation.")
    return expected


def _read_sources(paths):
    _run_count(len(paths))
    total = 0
    artifacts = []
    for path in paths:
        text = ev._read_text(path, "cohort scored input", min(ev.MAX_ARTIFACT_BYTES, MAX_COHORT_INPUT_BYTES - total))
        total += len(text.encode("utf-8"))
        artifact = ev.decode_json(text, "cohort scored input")
        ev._keys(artifact, ev.ARTIFACT_FIELDS, "scored artifact")
        ev._keys(artifact["run"], ev.RUN_FIELDS, "stored run")
        artifacts.append(artifact)
    return artifacts


def run_cohort(args):
    artifacts = _read_sources([args.baseline] + args.run)
    dataset = ev.load_dataset(args.dataset, artifacts[0]["run"]["validation_as_of"])
    baseline_id = artifacts[0]["run"]["run_id"]
    if args.verify_report is not None:
        report = ev.read_json(args.verify_report, "cohort report", ev.MAX_ARTIFACT_BYTES)
        verify_cohort(dataset, artifacts, report, baseline_id=baseline_id)
        print(f"PASS: {len(artifacts)} run(s), {len(dataset.cases)} case(s); cohort report matches supplied sources. No files were written.")
    else:
        report = compare_cohort(dataset, artifacts, baseline_id=baseline_id)
        ev.write_private_json(args.output if args.output is not None else Path("private-output/cohort.json"), report)
        print(f"PASS: {len(artifacts)} run(s), {len(dataset.cases)} case(s); private cohort comparison saved. No ranking or significance is inferred.")
