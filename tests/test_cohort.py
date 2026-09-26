"""Cohort fixtures are fictional declarations, never measured model results."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evidence_bench import cohort
from evidence_bench import evaluation as ev
from evidence_bench.comparison import compare_runs
from test_evaluation import AS_OF, CAPTURED, FIXTURE, dataset, invoke, supplied_run


def answered(data, identifier, factual):
    run = ev.prepare_run(data, run_id=identifier, created_at=CAPTURED)
    run["review"]["method"] = "synthetic"
    for record, judgment in zip(run["records"], factual):
        record.update(outcome="answered", response_text="Fictional supplied response.")
        record["judgments"] = {"factual": judgment, "citation": "unscored", "refusal_decision": "correct"}
    return ev.score_run(data, run)


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.data = dataset()
        self.a = answered(self.data, "fictional-a", ["correct", "correct", "incorrect"])
        self.b = answered(self.data, "fictional-b", ["unscored", "incorrect", "correct"])
        self.c = answered(self.data, "fictional-c", ["correct", "unscored", "incorrect"])
        self.sources = [self.a, self.b, self.c]
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()

    def report(self, sources=None, baseline="fictional-a"):
        return cohort.compare_cohort(self.data, self.sources if sources is None else sources, baseline_id=baseline)

    def save(self, value, name):
        path = self.directory / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def arguments(self):
        return ["compare-cohort", "--dataset", FIXTURE, "--baseline", self.save(self.a, "a.json"),
                "--run", self.save(self.c, "c.json"), "--run", self.save(self.b, "b.json")]

    def test_pairwise_and_common_intersections_are_distinct(self):
        report = self.report()
        aggregate = report["aggregate"]
        pairs = aggregate["baseline_pairs"]
        for pair in pairs:
            quality = pair["paired_quality"]["factual"]
            self.assertEqual(quality["eligible_pairs"], 2)
            self.assertEqual(quality["left_score"], ev.ratio(1, 2))
            self.assertEqual(quality["right_score"], ev.ratio(1, 2))
            self.assertEqual(quality["rate_delta"], 0)
        common = aggregate["all_run_common_quality"]["factual"]
        self.assertEqual(common["eligible_cases"], 1)
        self.assertEqual(common["excluded_cases"], 2)
        self.assertEqual(common["eligible_case_ids"], [self.data.cases[2]["id"]])
        self.assertEqual([row["score"] for row in common["scores"]], [ev.ratio(0, 1), ev.ratio(1, 1), ev.ratio(0, 1)])
        self.assertEqual([row["rate_delta_from_baseline"] for row in common["scores"]], [0, 1, 0])
        self.assertEqual([row["metrics"]["factual"]["score"] for row in aggregate["run_metrics"]], [ev.ratio(2, 3), ev.ratio(1, 2), ev.ratio(1, 2)])

    def test_baseline_pairs_match_existing_comparison_engine(self):
        report = self.report()
        for index, artifact in enumerate(self.sources[1:]):
            comparison = compare_runs(self.data, self.a, artifact)
            pair = dict(report["aggregate"]["baseline_pairs"][index])
            pair.pop("candidate")
            self.assertEqual(pair, comparison["aggregate"])
            metadata = report["baseline_setup_comparisons"][index]
            self.assertEqual(metadata["declared_setup_changes"], comparison["declared_setup_changes"])
            self.assertEqual(metadata["applicability_label_changes"], comparison["applicability_label_changes"])
            for dimension, strata in comparison["strata"].items():
                for name, expected in strata.items():
                    pair = dict(report["strata"][dimension][name]["baseline_pairs"][index])
                    pair.pop("candidate")
                    self.assertEqual(pair, expected)

    def test_all_unscored_common_rates_are_null_not_zero(self):
        common = self.report()["aggregate"]["all_run_common_quality"]["citation"]
        self.assertEqual(common["eligible_cases"], 0)
        self.assertEqual(common["eligible_case_ids"], [])
        self.assertEqual(common["excluded_cases"], 3)
        for row in common["scores"]:
            self.assertEqual(row["score"], ev.ratio(0, 0))
            self.assertIsNone(row["rate_delta_from_baseline"])
        # Exclusion counts overlap across runs and are deliberately not summed.
        self.assertEqual(sum(row["unscored"] for row in common["excluded_by_run"]), 9)

    def test_missing_and_not_applicable_remain_separate_from_incorrect(self):
        baseline = ev.score_run(self.data, supplied_run(self.data))
        empty = ev.prepare_run(self.data, run_id="fictional-empty", created_at=CAPTURED)
        report = self.report([baseline, ev.score_run(self.data, empty)])
        common = report["aggregate"]["all_run_common_quality"]["factual"]
        self.assertEqual([(row["unscored"], row["not_applicable"]) for row in common["excluded_by_run"]], [(1, 1), (3, 0)])
        pair = report["aggregate"]["baseline_pairs"][0]
        self.assertEqual(pair["response_availability"]["became_missing"], 2)
        self.assertEqual(pair["paired_quality"]["factual"]["eligible_pairs"], 0)
        self.assertEqual(pair["paired_quality"]["factual"]["regressed"], 0)
        self.assertEqual(report["aggregate"]["run_metrics"][1]["metrics"]["factual"]["counts"]["incorrect"], 0)

    def test_strata_keep_empty_groups_and_exact_common_case_ids(self):
        report = self.report()
        self.assertEqual(report["sample_scope"], {"cases": 3, "synthetic": 3, "real": 0, "reviewed": 2, "pending": 1})
        for group in report["strata"]["answerability"].values():
            self.assertEqual(group["sample_size"], 1)
        real = report["strata"]["synthetic"]["real"]
        self.assertEqual(real["sample_size"], 0)
        for common in real["all_run_common_quality"].values():
            self.assertEqual(common["eligible_cases"], 0)
            self.assertTrue(all(row["score"] == ev.ratio(0, 0) for row in common["scores"]))
        self.assertEqual(report["strata"]["synthetic"]["synthetic"], report["aggregate"])
        selected = [row["id"] for row in self.data.cases if row["answerability"] == "supported"]
        self.assertEqual(report["strata"]["answerability"]["supported"]["all_run_common_quality"]["factual"]["eligible_case_ids"], selected)

    def test_adding_run_shrinks_intersection_without_changing_existing_sources(self):
        two = self.report(self.sources[:2])
        three = self.report()
        self.assertEqual(two["aggregate"]["all_run_common_quality"]["factual"]["eligible_cases"], 2)
        self.assertEqual(three["aggregate"]["all_run_common_quality"]["factual"]["eligible_cases"], 1)
        self.assertEqual(two["aggregate"]["baseline_pairs"][0], three["aggregate"]["baseline_pairs"][0])
        self.assertNotEqual(two["cohort_sha256"], three["cohort_sha256"])

    def test_explicit_baseline_controls_direction_not_candidate_input_order(self):
        expected = self.report(baseline="fictional-c")
        reordered = self.report([self.c, self.b, self.a], baseline="fictional-c")
        self.assertEqual(ev.canonical(expected), ev.canonical(reordered))
        self.assertEqual([row["run_id"] for row in expected["runs"]], ["fictional-c", "fictional-a", "fictional-b"])
        self.assertEqual(expected["baseline"], expected["runs"][0])
        self.assertNotEqual(expected["cohort_sha256"], self.report()["cohort_sha256"])

    def test_sources_are_not_mutated_and_report_contains_no_raw_payloads(self):
        run = deepcopy(self.b["run"])
        markers = ["fictional-private-prompt", "fictional-private-response", "fictional-private-model", "fictional-private-reviewer", "fictional-private-parameter"]
        run["records"][0]["prompt_override"] = markers[0]
        run["records"][0]["response_text"] = markers[1]
        run["generation"] = {"model_label": markers[2], "parameters": {"fictional": markers[4]}}
        run["review"]["reviewer_label"] = markers[3]
        sources = [self.a, ev.score_run(self.data, run)]
        original = deepcopy(sources)
        report = self.report(sources)
        serialized = ev.canonical(report).decode()
        for marker in markers:
            self.assertNotIn(marker, serialized)
        self.assertEqual(sources, original)
        report["case_manifest"][0]["case_id"] = "fictional-changed-report"
        self.assertEqual(sources, original)
        self.assertNotEqual(self.data.cases[0]["id"], "fictional-changed-report")

    def test_declared_dates_and_effective_prompts_are_compared_not_forbidden(self):
        run = deepcopy(self.b["run"])
        run["created_at"] = "2026-02-01T12:00:00Z"
        run["records"][0]["prompt_override"] = self.data.cases[0]["question"]
        run["records"][1]["prompt_override"] = "Fictional changed prompt."
        report = self.report([self.a, ev.score_run(self.data, run)])
        changes = report["baseline_setup_comparisons"][0]["declared_setup_changes"]
        self.assertTrue(changes["created_at_changed"])
        self.assertEqual(changes["effective_prompts_changed"], 1)
        self.assertFalse(changes["model_label_changed"])

    def test_numeric_parameter_identity_is_preserved(self):
        left = deepcopy(self.a["run"])
        right = deepcopy(self.b["run"])
        left["generation"]["parameters"] = {"seed": 9007199254740993, "weight": 1}
        right["generation"]["parameters"] = {"seed": 9007199254740993, "weight": 1.0}
        sources = [ev.score_run(self.data, run) for run in (left, right)]
        report = self.report(sources)
        self.assertTrue(report["baseline_setup_comparisons"][0]["declared_setup_changes"]["parameters_changed"])
        self.assertEqual([row["run_sha256"] for row in report["runs"]], [artifact["run_sha256"] for artifact in sources])
        reloaded = [ev.decode_json(ev.canonical(source), "fictional input") for source in sources]
        self.assertEqual(report, self.report(reloaded))
        self.assertEqual(reloaded[0]["run"]["generation"]["parameters"]["seed"], 9007199254740993)
        self.assertIs(type(reloaded[1]["run"]["generation"]["parameters"]["weight"]), float)

    def test_duplicates_invalid_baselines_and_run_counts_are_rejected(self):
        same_id = deepcopy(self.b["run"])
        same_id["run_id"] = "fictional-a"
        cases = [([self.a], "fictional-a"), ([], "fictional-a"), ([self.a, self.a], "fictional-a"),
                 ([self.a, ev.score_run(self.data, same_id)], "fictional-a"),
                 (self.sources, "fictional-missing"), (self.sources, []), (iter(self.sources), "fictional-a")]
        for sources, baseline in cases:
            with self.subTest(index=cases.index((sources, baseline))), self.assertRaises(ev.EvaluationError):
                self.report(sources, baseline)
        many = []
        for index in range(cohort.MAX_COHORT_RUNS + 1):
            run = deepcopy(self.a["run"])
            run["run_id"] = f"fictional-{index:02d}"
            many.append(ev.score_run(self.data, run))
        self.assertEqual(len(self.report(many[:-1], "fictional-00")["runs"]), cohort.MAX_COHORT_RUNS)
        with self.assertRaises(ev.EvaluationError):
            self.report(many, "fictional-00")

    def test_mismatched_dataset_and_validation_date_are_rejected(self):
        cases = deepcopy(list(self.data.cases))
        cases[0]["question"] += " Fictional changed dataset."
        altered = ev.load_dataset([self.save(cases, "altered.json")], AS_OF)
        later = ev.load_dataset([FIXTURE], "2026-02-01")
        for data in (altered, later):
            other = answered(data, "fictional-b", ["correct"] * 3)
            with self.assertRaises(ev.EvaluationError):
                self.report([self.a, other])

    def test_tampered_sources_are_recomputed_before_aggregation(self):
        mutations = [
            lambda a: a["metrics"]["factual"]["score"].update(rate=0.75),
            lambda a: a.update(run_sha256="0" * 64),
            lambda a: a.update(dataset_sha256="0" * 64),
            lambda a: a.update(scoring_policy="fictional-other"),
            lambda a: a.update(schema_version=True),
            lambda a: a["case_manifest"].pop(),
            lambda a: a["run"]["records"].pop(),
            lambda a: a["run"]["records"].append(deepcopy(a["run"]["records"][0])),
            lambda a: a["run"]["records"][0].update(case_sha256="0" * 64),
            lambda a: a["run"]["generation"].update(parameters={"fictional": float("nan")}),
            lambda a: a.update(extra="fictional-private-marker"),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                altered = deepcopy(self.b)
                mutate(altered)
                with patch.object(cohort, "_group", side_effect=AssertionError("must validate first")), self.assertRaises(ev.EvaluationError):
                    self.report([self.a, altered, self.c])

    def test_strict_report_verification_rejects_any_stale_or_tampered_field(self):
        report = self.report()
        self.assertEqual(cohort.verify_cohort(self.data, self.sources[::-1], report, baseline_id="fictional-a"), report)
        mutations = [
            lambda r: r.update(cohort_sha256="0" * 64),
            lambda r: r.update(schema_version=True),
            lambda r: r.update(extra="fictional-private-marker"),
            lambda r: r["limitations"].pop(),
            lambda r: r["aggregate"]["all_run_common_quality"]["factual"]["scores"][0]["score"].update(rate=1),
            lambda r: r["strata"]["synthetic"]["real"].update(sample_size=1),
            lambda r: r["baseline_setup_comparisons"][0]["declared_setup_changes"].update(model_label_changed=True),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                altered = deepcopy(report)
                mutate(altered)
                with self.assertRaises(ev.EvaluationError):
                    cohort.verify_cohort(self.data, self.sources, altered, baseline_id="fictional-a")
        for sources, baseline in ((self.sources[:2], "fictional-a"), (self.sources, "fictional-b")):
            with self.assertRaises(ev.EvaluationError):
                cohort.verify_cohort(self.data, sources, report, baseline_id=baseline)
        changed = deepcopy(self.b["run"])
        changed["records"][0]["response_text"] += " Fictional revision."
        with self.assertRaises(ev.EvaluationError):
            cohort.verify_cohort(self.data, [self.a, ev.score_run(self.data, changed), self.c], report, baseline_id="fictional-a")

    def test_programmatic_byte_limits_reject_before_aggregation(self):
        largest = max(len(ev.canonical(source)) for source in self.sources)
        with patch.object(ev, "MAX_ARTIFACT_BYTES", largest - 1), self.assertRaises(ev.EvaluationError):
            self.report()
        total = sum(len(ev.canonical(source)) for source in self.sources)
        with patch.object(cohort, "MAX_COHORT_INPUT_BYTES", total - 1), self.assertRaises(ev.EvaluationError):
            self.report()
        with patch.object(cohort, "MAX_COHORT_INPUT_BYTES", total):
            self.assertEqual(len(self.report()["runs"]), 3)

    def test_cli_roundtrip_is_deterministic_private_offline_and_no_clobber(self):
        args = self.arguments()
        target = self.directory / "private-output" / "cohort.json"
        second = self.directory / "private-output" / "cohort-second.json"
        with patch("socket.create_connection", side_effect=AssertionError("network must not be used")):
            result = invoke(*args, "--output", target)
        self.assertEqual(result, (0, "PASS: 3 run(s), 3 case(s); private cohort comparison saved. No ranking or significance is inferred.\n", ""))
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(ev.read_json(target), self.report())
        original = target.read_bytes()
        self.assertEqual(invoke(*args, "--output", second)[0], 0)
        self.assertEqual(original, second.read_bytes())
        result = invoke(*args, "--output", target)
        self.assertEqual(result[:2], (1, ""))
        self.assertNotIn(str(self.directory), result[2])
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(list(target.parent.glob(".evidence-bench-*.tmp")), [])

    def test_cli_verification_writes_nothing_and_preserves_reports(self):
        args = self.arguments()
        target = self.save(self.report(), "report.json")
        original = target.read_bytes()
        with patch.object(ev, "write_private_json", side_effect=AssertionError("verification must not write")):
            result = invoke(*args, "--verify-report", target)
        self.assertEqual(result, (0, "PASS: 3 run(s), 3 case(s); cohort report matches supplied sources. No files were written.\n", ""))
        self.assertEqual(target.read_bytes(), original)
        report = self.report()
        report["aggregate"]["sample_size"] = 99
        target.write_text(json.dumps(report))
        result = invoke(*args, "--verify-report", target)
        self.assertEqual(result[:2], (1, ""))
        self.assertNotIn(str(self.directory), result[2])

    def test_cli_safe_errors_for_invalid_sources_and_missing_baseline(self):
        args = self.arguments()
        candidate = self.directory / "b.json"
        target = self.directory / "never-written.json"
        originals = [path.read_bytes() for path in (self.directory / "a.json", self.directory / "c.json")]
        for value in (b'{"fictional-private-marker": 1}', b'{"run": 1, "run": 2}', b'{"value": 1e400}', b'not JSON', b'\xff'):
            candidate.write_bytes(value)
            result = invoke(*args, "--output", target)
            self.assertEqual(result[:2], (1, ""))
            self.assertFalse(target.exists())
            self.assertNotIn("fictional-private-marker", result[2])
            self.assertNotIn(str(self.directory), result[2])
        self.assertEqual(originals, [path.read_bytes() for path in (self.directory / "a.json", self.directory / "c.json")])
        args[args.index("--baseline") + 1] = self.directory / "fictional-private-missing.json"
        result = invoke(*args, "--output", target)
        self.assertEqual(result[:2], (1, ""))
        self.assertNotIn("fictional-private-missing", result[2])

    def test_cli_duplicate_and_too_many_sources_fail_before_writing(self):
        args = self.arguments()
        target = self.directory / "never-written.json"
        result = invoke(*args, "--run", self.directory / "a.json", "--output", target)
        self.assertEqual(result[:2], (1, ""))
        self.assertFalse(target.exists())
        too_many = args + [item for _ in range(cohort.MAX_COHORT_RUNS) for item in ("--run", self.directory / "does-not-exist.json")]
        with patch.object(ev, "_read_text", side_effect=AssertionError("count must be checked before reading")):
            result = invoke(*too_many, "--output", target)
        self.assertEqual(result[:2], (1, ""))
        self.assertFalse(target.exists())

    def test_cli_aggregate_raw_byte_limit_includes_whitespace(self):
        args = self.arguments()
        paths = [self.directory / name for name in ("a.json", "b.json", "c.json")]
        total = sum(path.stat().st_size for path in paths)
        paths[1].write_bytes(paths[1].read_bytes() + b" " * 100)
        target = self.directory / "never-written.json"
        with patch.object(cohort, "MAX_COHORT_INPUT_BYTES", total + 99):
            result = invoke(*args, "--output", target)
        self.assertEqual(result[:2], (1, ""))
        self.assertFalse(target.exists())
        self.assertNotIn(str(self.directory), result[2])
        with patch.object(cohort, "MAX_COHORT_INPUT_BYTES", total + 100):
            self.assertEqual(invoke(*args, "--output", target)[0], 0)

    def test_cli_rejects_symlink_output_ancestors_and_source_overwrite(self):
        args = self.arguments()
        real = self.directory / "real"
        real.mkdir()
        alias = self.directory / "alias"
        alias.symlink_to(real, target_is_directory=True)
        result = invoke(*args, "--output", alias / "report.json")
        self.assertEqual(result[:2], (1, ""))
        self.assertFalse((real / "report.json").exists())
        baseline = self.directory / "a.json"
        original = baseline.read_bytes()
        result = invoke(*args, "--output", baseline)
        self.assertEqual(result[:2], (1, ""))
        self.assertEqual(baseline.read_bytes(), original)

    def test_cli_output_and_verification_modes_are_mutually_exclusive(self):
        args = self.arguments()
        result = invoke(*args, "--output", "fictional-private-output", "--verify-report", "fictional-private-report")
        self.assertEqual(result[0], 2)
        self.assertNotIn("fictional-private", result[2])
        result = invoke("compare-cohort", "--dataset", FIXTURE, "--run", "fictional-private-run")
        self.assertEqual(result[0], 2)
        self.assertNotIn("fictional-private", result[2])

    def test_cli_oversized_report_creates_no_partial_output(self):
        args = self.arguments()
        target = self.directory / "never-written.json"
        # Keep the scored sources within the limit but make the larger report fail.
        limit = max(len(ev.canonical(source)) for source in self.sources) + 1000
        with patch.object(ev, "MAX_ARTIFACT_BYTES", limit):
            result = invoke(*args, "--output", target)
        self.assertEqual(result[:2], (1, ""))
        self.assertFalse(target.exists())
        self.assertEqual(list(self.directory.glob(".evidence-bench-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
