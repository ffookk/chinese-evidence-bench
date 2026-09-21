"""Deterministic paired analysis of verified runs; no statistical inference."""

from . import evaluation as ev
from .validator import ANSWERABILITY

COMPARISON_POLICY = "paired_binary_v1"
SCORED = {"correct", "incorrect"}
LIMITATIONS = [
    "Results summarize declared responses and supplied judgments, not independently authenticated model performance.",
    "Only cases scored correct or incorrect in both runs contribute to paired quality changes.",
    "Unscored and not-applicable judgments are never converted to incorrect judgments.",
    "Aggregate rates can use different scored denominators; paired rates use the same eligible cases in both runs.",
    "Response availability and answer outcome labels describe coverage, not answer quality.",
    "Synthetic cases are fictional; real labels and reviewed states do not establish independent human certification.",
    "Small or selected samples and descriptive deltas do not establish statistical significance, causality, or general model rankings.",
    "Declared settings and prompts may differ between runs; equal dataset identity alone does not establish a controlled experiment.",
]


def _delta(left, right):
    left_denominator, right_denominator = left["denominator"], right["denominator"]
    difference = None
    if left_denominator and right_denominator:
        difference = round(right["numerator"] / right_denominator - left["numerator"] / left_denominator, 6)
    return {
        "numerator_delta": right["numerator"] - left["numerator"],
        "denominator_delta": right_denominator - left_denominator,
        "rate_delta": difference,
    }


def _transition(left, right):
    if left not in SCORED or right not in SCORED:
        return "not_comparable"
    if left == right:
        return "unchanged"
    return "improved" if right == "correct" else "regressed"


def _paired_axis(left, right, axis):
    counts = {key: 0 for key in ("improved", "regressed", "unchanged", "not_comparable", "left_only_scored", "right_only_scored", "neither_scored")}
    left_correct = right_correct = 0
    for before, after in zip(left, right):
        old, new = before["judgments"][axis], after["judgments"][axis]
        transition = _transition(old, new)
        counts[transition] += 1
        if transition == "not_comparable":
            state = "left_only_scored" if old in SCORED else "right_only_scored" if new in SCORED else "neither_scored"
            counts[state] += 1
        else:
            left_correct += int(old == "correct")
            right_correct += int(new == "correct")
    denominator = len(left) - counts["not_comparable"]
    return {
        **counts,
        "eligible_pairs": denominator,
        "left_score": ev.ratio(left_correct, denominator),
        "right_score": ev.ratio(right_correct, denominator),
        "rate_delta": round((right_correct - left_correct) / denominator, 6) if denominator else None,
        "improvement_rate": ev.ratio(counts["improved"], denominator),
        "regression_rate": ev.ratio(counts["regressed"], denominator),
    }


def _comparison(left, right):
    left_metrics, right_metrics = ev.metrics_for(left), ev.metrics_for(right)
    deltas = {name: _delta(left_metrics[name], right_metrics[name]) for name in ("answer_coverage", "response_coverage")}
    for axis in ev.AXES:
        deltas[axis] = {
            "score": _delta(left_metrics[axis]["score"], right_metrics[axis]["score"]),
            "judgment_coverage": _delta(left_metrics[axis]["judgment_coverage"], right_metrics[axis]["judgment_coverage"]),
            "count_deltas": {state: right_metrics[axis]["counts"][state] - left_metrics[axis]["counts"][state] for state in ev.JUDGMENTS},
        }
    outcomes = {before: {after: 0 for after in ev.OUTCOMES} for before in ev.OUTCOMES}
    availability = {key: 0 for key in ("became_observed", "became_missing", "remained_observed", "remained_missing")}
    for before, after in zip(left, right):
        old, new = before["outcome"], after["outcome"]
        outcomes[old][new] += 1
        if old == "missing":
            state = "remained_missing" if new == "missing" else "became_observed"
        else:
            state = "became_missing" if new == "missing" else "remained_observed"
        availability[state] += 1
    return {
        "sample_size": len(left),
        "left_metrics": left_metrics,
        "right_metrics": right_metrics,
        "aggregate_deltas": deltas,
        "paired_quality": {axis: _paired_axis(left, right, axis) for axis in ev.AXES},
        "response_availability": availability,
        "outcome_transitions": outcomes,
    }


def compare_runs(dataset, left, right):
    """Recompute both artifacts before matching their complete, ID-sorted records."""
    before = ev.verify_scored(dataset, left)
    after = ev.verify_scored(dataset, right)
    left_records, right_records = before["run"]["records"], after["run"]["records"]

    def group(predicate):
        positions = [index for index, case in enumerate(dataset.cases) if predicate(case)]
        return _comparison([left_records[index] for index in positions], [right_records[index] for index in positions])

    changes = [{
        "case_id": old["case_id"],
        "case_sha256": old["case_sha256"],
        "left_outcome": old["outcome"],
        "right_outcome": new["outcome"],
        "judgments": {axis: {"left": old["judgments"][axis], "right": new["judgments"][axis], "transition": _transition(old["judgments"][axis], new["judgments"][axis])} for axis in ev.AXES},
    } for old, new in zip(left_records, right_records)]
    prompt_changes = sum(
        (old["prompt_override"] if old["prompt_override"] is not None else case["question"])
        != (new["prompt_override"] if new["prompt_override"] is not None else case["question"])
        for case, old, new in zip(dataset.cases, left_records, right_records)
    )
    before_run, after_run = before["run"], after["run"]
    setup_changes = {
        "model_label_changed": before_run["generation"]["model_label"] != after_run["generation"]["model_label"],
        "parameters_changed": ev.canonical(before_run["generation"]["parameters"]) != ev.canonical(after_run["generation"]["parameters"]),
        "review_method_changed": before_run["review"]["method"] != after_run["review"]["method"],
        "reviewer_label_changed": before_run["review"]["reviewer_label"] != after_run["review"]["reviewer_label"],
        "created_at_changed": before_run["created_at"] != after_run["created_at"],
        "effective_prompts_changed": prompt_changes,
    }
    applicability_label_changes = {axis: {
        "moved_from_not_applicable": sum(old["judgments"][axis] == "not_applicable" and new["judgments"][axis] != "not_applicable" for old, new in zip(left_records, right_records)),
        "moved_to_not_applicable": sum(old["judgments"][axis] != "not_applicable" and new["judgments"][axis] == "not_applicable" for old, new in zip(left_records, right_records)),
    } for axis in ev.AXES}
    synthetic = sum(case["synthetic"] for case in dataset.cases)
    reviewed = sum(case["review_status"] == "reviewed" for case in dataset.cases)
    return {
        "schema_version": ev.SCHEMA_VERSION,
        "artifact_type": "paired_comparison",
        "comparison_policy": COMPARISON_POLICY,
        "scoring_policy": ev.SCORING_POLICY,
        "dataset_sha256": dataset.sha256,
        "validation_as_of": dataset.validation_as_of,
        "left_run_sha256": before["run_sha256"],
        "right_run_sha256": after["run_sha256"],
        "left_run_id": before["run"]["run_id"],
        "right_run_id": after["run"]["run_id"],
        "sample_scope": {"cases": len(dataset.cases), "synthetic": synthetic, "real": len(dataset.cases) - synthetic, "reviewed": reviewed, "pending": len(dataset.cases) - reviewed},
        "declared_setup_changes": setup_changes,
        "applicability_label_changes": applicability_label_changes,
        "aggregate": _comparison(left_records, right_records),
        "strata": {
            "answerability": {state: group(lambda case, state=state: case["answerability"] == state) for state in sorted(ANSWERABILITY)},
            "synthetic": {"synthetic": group(lambda case: case["synthetic"]), "real": group(lambda case: not case["synthetic"])},
        },
        "case_changes": changes,
        "limitations": list(LIMITATIONS),
    }


def run_comparison(args):
    left = ev.read_json(args.left, "left scored artifact", ev.MAX_ARTIFACT_BYTES)
    right = ev.read_json(args.right, "right scored artifact", ev.MAX_ARTIFACT_BYTES)
    for artifact in (left, right):
        ev._keys(artifact, ev.ARTIFACT_FIELDS, "scored artifact")
        ev._keys(artifact["run"], ev.RUN_FIELDS, "stored run")
    dataset = ev.load_dataset(args.dataset, left["run"]["validation_as_of"])
    result = compare_runs(dataset, left, right)
    ev.write_private_json(args.output, result)
    print(f"PASS: {len(dataset.cases)} paired case(s); private comparison saved. No statistical significance is inferred.")
