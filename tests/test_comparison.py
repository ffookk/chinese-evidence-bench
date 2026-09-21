"""Paired-analysis tests use fictional judgments, never real model results."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from evidence_bench import evaluation as ev
from evidence_bench.comparison import compare_runs
from test_evaluation import AS_OF, FIXTURE, dataset, invoke, supplied_run


def changed_run(data):
    run = supplied_run(data)
    run["run_id"] = "fictional-b"
    clarification, insufficient, supported = run["records"]
    clarification.update(outcome="clarification_requested", response_text="Fictional clarification response.")
    clarification["judgments"] = {"factual": "not_applicable", "citation": "not_applicable", "refusal_decision": "correct"}
    insufficient.update(outcome="answered", response_text="Fictional unsupported answer.")
    insufficient["judgments"] = {"factual": "incorrect", "citation": "unscored", "refusal_decision": "incorrect"}
    supported["judgments"] = {"factual": "incorrect", "citation": "correct", "refusal_decision": "unscored"}
    return run


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.data = dataset()
        self.left = ev.score_run(self.data, supplied_run(self.data))
        self.right = ev.score_run(self.data, changed_run(self.data))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()

    def save(self, value, name):
        path = self.directory / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_known_improved_regressed_and_unscored_pairs(self):
        report = compare_runs(self.data, self.left, self.right)
        pairs = report["aggregate"]["paired_quality"]
        self.assertEqual(pairs["factual"]["regressed"], 1)
        self.assertEqual(pairs["factual"]["improved"], 0)
        self.assertEqual(pairs["citation"]["improved"], 1)
        self.assertEqual(pairs["refusal_decision"]["regressed"], 1)
        for axis in ev.AXES:
            self.assertEqual(pairs[axis]["eligible_pairs"], 1)
            self.assertEqual(pairs[axis]["not_comparable"], 2)
            self.assertEqual(pairs[axis]["unchanged"], 0)
            self.assertEqual(pairs[axis]["left_score"]["denominator"], 1)
            self.assertEqual(pairs[axis]["right_score"]["denominator"], 1)
        self.assertEqual(pairs["factual"]["right_only_scored"], 1)
        self.assertEqual(pairs["factual"]["neither_scored"], 1)
        self.assertEqual(pairs["refusal_decision"]["left_only_scored"], 1)
        self.assertEqual(pairs["refusal_decision"]["right_only_scored"], 1)
        self.assertEqual(pairs["refusal_decision"]["neither_scored"], 0)
        self.assertEqual(pairs["citation"]["improvement_rate"], ev.ratio(1, 1))
        self.assertEqual(pairs["factual"]["regression_rate"], ev.ratio(1, 1))

    def test_aggregate_and_paired_deltas_have_distinct_denominators(self):
        group = compare_runs(self.data, self.left, self.right)["aggregate"]
        self.assertEqual(group["aggregate_deltas"]["factual"]["score"], {"numerator_delta": -1, "denominator_delta": 1, "rate_delta": -1.0})
        self.assertEqual(group["left_metrics"]["refusal_decision"]["score"], ev.ratio(2, 2))
        self.assertEqual(group["right_metrics"]["refusal_decision"]["score"], ev.ratio(1, 2))
        self.assertEqual(group["aggregate_deltas"]["refusal_decision"]["score"]["rate_delta"], -0.5)
        self.assertEqual(group["paired_quality"]["refusal_decision"]["rate_delta"], -1.0)
        self.assertEqual(group["aggregate_deltas"]["response_coverage"], {"numerator_delta": 1, "denominator_delta": 0, "rate_delta": 0.333333})

    def test_strata_include_empty_groups_with_undefined_rates(self):
        report = compare_runs(self.data, self.left, self.right)
        self.assertEqual(report["sample_scope"], {"cases": 3, "synthetic": 3, "real": 0, "reviewed": 2, "pending": 1})
        self.assertEqual(set(report["strata"]["answerability"]), {"supported", "insufficient_evidence", "needs_clarification"})
        for group in report["strata"]["answerability"].values():
            self.assertEqual(group["sample_size"], 1)
        real = report["strata"]["synthetic"]["real"]
        self.assertEqual(real["sample_size"], 0)
        self.assertEqual(real["left_metrics"]["answer_coverage"], ev.ratio(0, 0))
        self.assertIsNone(real["aggregate_deltas"]["answer_coverage"]["rate_delta"])
        self.assertIsNone(real["paired_quality"]["factual"]["rate_delta"])
        self.assertEqual(report["strata"]["synthetic"]["synthetic"], report["aggregate"])

    def test_coverage_transitions_are_separate_from_quality(self):
        group = compare_runs(self.data, self.left, self.right)["aggregate"]
        self.assertEqual(group["response_availability"], {"became_observed": 1, "became_missing": 0, "remained_observed": 2, "remained_missing": 0})
        self.assertEqual(group["outcome_transitions"]["missing"]["clarification_requested"], 1)
        self.assertEqual(group["outcome_transitions"]["refused"]["answered"], 1)
        self.assertEqual(sum(sum(row.values()) for row in group["outcome_transitions"].values()), 3)
        self.assertEqual(group["paired_quality"]["refusal_decision"]["improved"], 0)

    def test_identical_runs_are_unchanged_only_where_scored(self):
        report = compare_runs(self.data, self.left, self.left)
        for axis, expected in (("factual", 1), ("citation", 1), ("refusal_decision", 2)):
            paired = report["aggregate"]["paired_quality"][axis]
            self.assertEqual(paired["unchanged"], expected)
            self.assertEqual(paired["not_comparable"], 3 - expected)
            self.assertEqual(paired["rate_delta"], 0)
        self.assertFalse(any(report["declared_setup_changes"].values()))

    def test_all_missing_runs_do_not_claim_wrong_or_unchanged_quality(self):
        missing = ev.score_run(self.data, ev.prepare_run(self.data))
        group = compare_runs(self.data, missing, missing)["aggregate"]
        for axis in ev.AXES:
            paired = group["paired_quality"][axis]
            self.assertEqual(paired["eligible_pairs"], 0)
            self.assertEqual(paired["neither_scored"], 3)
            self.assertEqual(paired["unchanged"], 0)
            self.assertEqual(paired["improved"], 0)
            self.assertEqual(paired["regressed"], 0)
            self.assertIsNone(paired["rate_delta"])
            self.assertIsNone(group["aggregate_deltas"][axis]["score"]["rate_delta"])

    def test_declared_configuration_prompt_and_applicability_label_changes_are_visible(self):
        run = changed_run(self.data)
        run["generation"] = {"model_label": "fictional-other-model", "parameters": {"temperature": 0.3}}
        run["review"] = {"method": "ai_assisted", "reviewer_label": "fictional-other-reviewer"}
        run["created_at"] = "2026-02-01T12:00:00Z"
        run["records"][0]["prompt_override"] = self.data.cases[0]["question"]
        run["records"][2]["prompt_override"] = "Fictional modified prompt."
        report = compare_runs(self.data, self.left, ev.score_run(self.data, run))
        self.assertEqual(report["declared_setup_changes"], {
            "model_label_changed": True, "parameters_changed": True,
            "review_method_changed": True, "reviewer_label_changed": True,
            "created_at_changed": True, "effective_prompts_changed": 1,
        })
        for axis in ("factual", "citation"):
            self.assertEqual(report["applicability_label_changes"][axis], {"moved_from_not_applicable": 1, "moved_to_not_applicable": 1})
        self.assertEqual(report["applicability_label_changes"]["refusal_decision"], {"moved_from_not_applicable": 0, "moved_to_not_applicable": 0})
        self.assertTrue(any("controlled experiment" in line for line in report["limitations"]))

    def test_comparison_is_deterministic_and_does_not_copy_response_payloads(self):
        first = compare_runs(self.data, self.left, self.right)
        second = compare_runs(self.data, self.left, self.right)
        self.assertEqual(ev.canonical(first), ev.canonical(second))
        serialized = ev.canonical(first).decode("utf-8")
        self.assertNotIn("Fictional unsupported answer.", serialized)
        self.assertNotIn("fictional-test-model", serialized)
        self.assertEqual([case["case_id"] for case in first["case_changes"]], sorted(case["id"] for case in self.data.cases))
        self.assertEqual(first["case_changes"][2]["judgments"]["citation"]["transition"], "improved")

    def test_reversing_runs_reverses_direction_without_changing_pairs(self):
        forward = compare_runs(self.data, self.left, self.right)["aggregate"]
        backward = compare_runs(self.data, self.right, self.left)["aggregate"]
        for axis in ev.AXES:
            left, right = forward["paired_quality"][axis], backward["paired_quality"][axis]
            self.assertEqual(left["eligible_pairs"], right["eligible_pairs"])
            self.assertEqual(left["improved"], right["regressed"])
            self.assertEqual(left["regressed"], right["improved"])
            self.assertEqual(left["rate_delta"], -right["rate_delta"])
        self.assertEqual(backward["response_availability"]["became_missing"], 1)

    def test_mismatched_dataset_and_validation_context_are_rejected(self):
        altered_cases = deepcopy(list(self.data.cases))
        altered_cases[0]["question"] += " Fictional altered case."
        changed = ev.load_dataset([self.save(altered_cases, "changed.json")], AS_OF)
        other = ev.score_run(changed, supplied_run(changed))
        later_data = ev.load_dataset([FIXTURE], "2026-02-01")
        later = ev.score_run(later_data, supplied_run(later_data))
        for right in (other, later):
            with self.subTest(fingerprint=right["dataset_sha256"][:8]), self.assertRaises(ev.EvaluationError):
                compare_runs(self.data, self.left, right)

    def test_tampered_metrics_hashes_and_missing_or_duplicate_records_fail(self):
        changes = [
            lambda a: a["metrics"]["factual"]["score"].update(rate=1),
            lambda a: a.update(run_sha256="0" * 64),
            lambda a: a.update(scoring_policy="other"),
            lambda a: a.update(schema_version=True),
            lambda a: a["case_manifest"].pop(),
            lambda a: a["run"]["records"].pop(),
            lambda a: a["run"]["records"].append(deepcopy(a["run"]["records"][0])),
            lambda a: a["run"]["records"][0].update(case_sha256="0" * 64),
            lambda a: a["run"]["generation"].update(parameters={"value": float("nan")}),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                right = deepcopy(self.right)
                change(right)
                with self.assertRaises(ev.EvaluationError):
                    compare_runs(self.data, self.left, right)
                with self.assertRaises(ev.EvaluationError):
                    compare_runs(self.data, right, self.left)

    def test_cli_comparison_roundtrip_no_clobber_permissions_and_private_stdout(self):
        left, right = self.save(self.left, "fictional-left.json"), self.save(self.right, "fictional-right.json")
        output = self.directory / "private-output" / "comparison.json"
        arguments = ("compare-runs", "--dataset", FIXTURE, "--left", left, "--right", right, "--output", output)
        result = invoke(*arguments)
        self.assertEqual(result, (0, "PASS: 3 paired case(s); private comparison saved. No statistical significance is inferred.\n", ""))
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        original = output.read_bytes()
        artifact = ev.read_json(output)
        self.assertEqual(artifact, compare_runs(self.data, self.left, self.right))
        result = invoke(*arguments)
        self.assertEqual(result[0:2], (1, ""))
        self.assertNotIn(str(self.directory), result[2])
        self.assertNotIn("fictional-left", result[2])
        self.assertEqual(output.read_bytes(), original)

    def test_invalid_artifact_cli_suppresses_output_and_raw_values(self):
        left, right = self.save(self.left, "left.json"), self.save(self.right, "right.json")
        output = self.directory / "not-created.json"
        for content in ('{"fictional-private-marker":1}', '{"run":1,"run":2}', '{"value":1e400}', 'not JSON'):
            right.write_text(content)
            result = invoke("compare-runs", "--dataset", FIXTURE, "--left", left, "--right", right, "--output", output)
            self.assertEqual(result[0:2], (1, ""))
            self.assertFalse(output.exists())
            self.assertNotIn("fictional-private-marker", result[2])
            self.assertNotIn(str(self.directory), result[2])


if __name__ == "__main__":
    unittest.main()
