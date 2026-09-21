"""All response and review data below are fictional test inputs, not model results."""

import contextlib
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evidence_bench.__main__ import main
from evidence_bench import evaluation as ev

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/synthetic.jsonl"
AS_OF = "2026-01-31"
CAPTURED = "2026-01-31T12:00:00Z"


def dataset():
    return ev.load_dataset([FIXTURE], AS_OF)


def supplied_run(data):
    run = ev.prepare_run(data, run_id="fictional-a", model_label="fictional-test-model", created_at=CAPTURED)
    run["review"] = {"method": "synthetic", "reviewer_label": "fictional-test-review"}
    for record, case in zip(run["records"], data.cases):
        if case["answerability"] == "supported":
            record.update(outcome="answered", response_text="Fictional response: three wooden discs.")
            record["judgments"] = {"factual": "correct", "citation": "incorrect", "refusal_decision": "correct"}
        elif case["answerability"] == "insufficient_evidence":
            record.update(outcome="refused", response_text="Fictional refusal: insufficient evidence.")
            record["judgments"] = {"factual": "not_applicable", "citation": "not_applicable", "refusal_decision": "correct"}
    return run


def invoke(*args):
    with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
        try:
            code = main(list(map(str, args)))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.data = dataset()
        self.run = supplied_run(self.data)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Resolve the operating system's temporary-directory alias before use.
        self.directory = Path(self.temp.name).resolve()

    def save(self, value, name="run.json"):
        path = self.directory / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def invalid(self, run):
        with self.assertRaises(ev.EvaluationError):
            ev.score_run(self.data, run)

    def test_prepare_is_complete_unscored_and_prompt_default_is_explicit(self):
        prepared = ev.prepare_run(self.data, created_at=CAPTURED)
        self.assertEqual(len(prepared["records"]), 3)
        self.assertTrue(all(record["prompt_override"] is None for record in prepared["records"]))
        metrics = ev.score_run(self.data, prepared)["metrics"]
        self.assertEqual(metrics["response_coverage"], ev.ratio(0, 3))
        for axis in ev.AXES:
            self.assertEqual(metrics[axis]["counts"]["unscored"], 3)
            self.assertEqual(metrics[axis]["score"], ev.ratio(0, 0))
            self.assertEqual(metrics[axis]["judgment_coverage"], ev.ratio(0, 3))

    def test_known_mixed_metrics_have_explicit_denominators(self):
        metrics = ev.score_run(self.data, self.run)["metrics"]
        self.assertEqual(metrics["outcome_counts"], {"answered": 1, "refused": 1, "missing": 1, "clarification_requested": 0})
        self.assertEqual(metrics["answer_coverage"], ev.ratio(1, 3))
        self.assertEqual(metrics["response_coverage"], ev.ratio(2, 3))
        self.assertEqual(metrics["factual"]["counts"], {"correct": 1, "incorrect": 0, "unscored": 1, "not_applicable": 1})
        self.assertEqual(metrics["factual"]["score"], ev.ratio(1, 1))
        self.assertEqual(metrics["factual"]["judgment_coverage"], ev.ratio(1, 2))
        self.assertEqual(metrics["citation"]["score"], ev.ratio(0, 1))
        self.assertEqual(metrics["refusal_decision"]["score"], ev.ratio(2, 2))
        self.assertEqual(metrics["refusal_decision"]["judgment_coverage"], ev.ratio(2, 3))

    def test_provenance_and_prompt_are_preserved_without_authentication_claims(self):
        self.run["generation"]["parameters"] = {"temperature": 0.2, "seed": 0, "options": [True, None, {"mode": "fictional"}]}
        self.run["records"][0]["prompt_override"] = "Fictional alternate prompt."
        artifact = ev.score_run(self.data, self.run)
        self.assertEqual(artifact["run"], self.run)
        self.assertEqual(artifact["run"]["created_at"], CAPTURED)
        self.assertTrue(any("not authenticated" in text for text in artifact["limitations"]))

    def test_scoring_is_deterministic_and_record_order_independent(self):
        first = ev.score_run(self.data, self.run)
        self.run["records"].reverse()
        second = ev.score_run(self.data, self.run)
        self.assertEqual(ev.canonical(first), ev.canonical(second))
        for name, value in (("a.json", first), ("b.json", second)):
            ev.write_private_json(self.directory / name, value)
        self.assertEqual((self.directory / "a.json").read_bytes(), (self.directory / "b.json").read_bytes())

    def test_dataset_identity_ignores_input_order_but_binds_content(self):
        paths = [self.save([case], f"case-{index}.json") for index, case in enumerate(self.data.cases)]
        reordered = ev.load_dataset(paths[::-1], AS_OF)
        self.assertEqual(reordered.sha256, self.data.sha256)
        changed = deepcopy(list(self.data.cases))
        changed[0]["question"] += " Fictional change."
        altered = ev.load_dataset([self.save(changed, "changed.json")], AS_OF)
        self.assertNotEqual(altered.sha256, self.data.sha256)
        with self.assertRaises(ev.EvaluationError):
            ev.score_run(altered, self.run)

    def test_dataset_rejects_duplicate_empty_invalid_and_future_cases(self):
        for paths, cutoff in (([FIXTURE, FIXTURE], AS_OF), ([FIXTURE], "2026-01-01"), ([], AS_OF)):
            with self.subTest(paths=len(paths), cutoff=cutoff), self.assertRaises(ev.EvaluationError):
                ev.load_dataset(paths, cutoff)
        for value in ([], [{}], {"cases": []}):
            with self.subTest(value=value), self.assertRaises(ev.EvaluationError):
                ev.load_dataset([self.save(value)], AS_OF)

    def test_records_must_be_unique_complete_and_bound_to_case_hashes(self):
        changes = [
            lambda r: r["records"].pop(),
            lambda r: r["records"].append(deepcopy(r["records"][0])),
            lambda r: r["records"][0].update(case_id="fictional-unknown"),
            lambda r: r["records"][0].update(case_sha256="0" * 64),
            lambda r: r.update(dataset_sha256="0" * 64),
            lambda r: r.update(validation_as_of="2026-02-01"),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                run = deepcopy(self.run)
                change(run)
                self.invalid(run)

    def test_strict_required_fields_and_types_at_every_level(self):
        changes = [
            lambda r: r.update(extra="fictional-private-marker"),
            lambda r: r.pop("created_at"),
            lambda r: r.update(schema_version=True),
            lambda r: r.update(schema_version=2),
            lambda r: r.update(records={}),
            lambda r: r["generation"].update(extra=0),
            lambda r: r["generation"].update(parameters=[]),
            lambda r: r["review"].update(method="unverified-extra-mode"),
            lambda r: r["review"].pop("reviewer_label"),
            lambda r: r["records"][0].update(extra=0),
            lambda r: r["records"][0]["judgments"].update(extra=0),
            lambda r: r["records"][0]["judgments"].update(factual=True),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                run = deepcopy(self.run)
                change(run)
                self.invalid(run)

    def test_text_timestamp_and_parameters_limits(self):
        changes = [
            lambda r: r.update(created_at="2026-01-31T12:00:00+00:00"),
            lambda r: r.update(created_at="2026-02-30T12:00:00Z"),
            lambda r: r.update(run_id="Invalid identifier"),
            lambda r: r["generation"].update(model_label="line\nbreak"),
            lambda r: r["generation"].update(parameters={"number": float("inf")}),
            lambda r: r["generation"].update(parameters={"number": float("nan")}),
            lambda r: r["generation"].update(parameters={"value": object()}),
            lambda r: r["records"][0].update(prompt_override=""),
            lambda r: r["records"][0].update(prompt_override="bad" + chr(0)),
            lambda r: r["records"][0].update(prompt_override=chr(0xD800)),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                run = deepcopy(self.run)
                change(run)
                self.invalid(run)
        with self.assertRaises(ev.EvaluationError):
            ev.prepare_run(self.data, created_at="")
        nested = {}
        self.run["generation"]["parameters"] = nested
        for _ in range(15):
            nested["nested"] = {}
            nested = nested["nested"]
        self.invalid(self.run)

    def test_outcome_and_judgment_consistency(self):
        changes = [
            lambda r: r["records"][0].update(response_text="Unexpected response for a missing outcome."),
            lambda r: r["records"][0]["judgments"].update(factual="correct"),
            lambda r: r["records"][1]["judgments"].update(factual="unscored"),
            lambda r: r["records"][1]["judgments"].update(refusal_decision="not_applicable"),
            lambda r: r["records"][2].update(response_text=" "),
            lambda r: r["records"][2].update(outcome="unexpected"),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                run = deepcopy(self.run)
                change(run)
                self.invalid(run)
        record = self.run["records"][0]
        record.update(outcome="clarification_requested", response_text="Fictional clarification request.")
        record["judgments"] = {"factual": "not_applicable", "citation": "not_applicable", "refusal_decision": "unscored"}
        self.assertEqual(ev.score_run(self.data, self.run)["metrics"]["response_coverage"], ev.ratio(3, 3))

    def test_json_rejects_duplicates_nonfinite_numbers_and_deep_structure(self):
        for raw in ('{"x":1,"x":2}', '{"x":{"k":1,"k":2}}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e400}', '[' * 2000 + '0' + ']' * 2000):
            with self.subTest(raw_length=len(raw)), self.assertRaises(ev.EvaluationError):
                ev.decode_json(raw, "test input")

    def test_read_errors_and_size_limits_are_value_free(self):
        path = self.directory / "fictional-private-marker.json"
        path.write_bytes(b"\xff")
        for candidate in (path, self.directory / "missing.json", "bad" + chr(0) + "path"):
            with self.subTest(candidate_type=type(candidate).__name__), self.assertRaises(ev.EvaluationError) as error:
                ev.read_json(candidate)
            self.assertNotIn("fictional-private-marker", str(error.exception))
        path.write_text("12345")
        with self.assertRaises(ev.EvaluationError):
            ev.read_json(path, max_bytes=4)

    def test_integrity_verification_recalculates_every_stored_field(self):
        artifact = ev.score_run(self.data, self.run)
        self.assertEqual(ev.verify_scored(self.data, artifact), artifact)
        changes = [
            lambda a: a.update(run_sha256="0" * 64),
            lambda a: a.update(dataset_sha256="0" * 64),
            lambda a: a.update(scoring_policy="other"),
            lambda a: a.update(extra=True),
            lambda a: a["case_manifest"][0].update(synthetic=False),
            lambda a: a["metrics"].update(sample_size=3.0),
            lambda a: a["metrics"]["answer_coverage"].update(rate=True),
            lambda a: a["metrics"]["citation"]["score"].update(numerator=1),
            lambda a: a["limitations"].clear(),
        ]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                altered = deepcopy(artifact)
                change(altered)
                with self.assertRaises(ev.EvaluationError):
                    ev.verify_scored(self.data, altered)

    def test_private_save_permissions_and_no_clobber(self):
        target = self.directory / "new" / "nested" / "result.json"
        ev.write_private_json(target, {"fictional": True})
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(target.parent.parent.stat().st_mode & 0o777, 0o700)
        original = target.read_bytes()
        with self.assertRaises(ev.EvaluationError):
            ev.write_private_json(target, {"fictional": False})
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_private_save_rejects_symlink_ancestors_and_target_links(self):
        real = self.directory / "real"
        (real / "nested").mkdir(parents=True)
        alias = self.directory / "alias"
        alias.symlink_to(real, target_is_directory=True)
        with self.assertRaises(ev.EvaluationError):
            ev.write_private_json(alias / "nested" / "out.json", {})
        self.assertFalse((real / "nested" / "out.json").exists())
        original = self.directory / "original.json"
        original.write_text("original")
        link = self.directory / "link.json"
        link.symlink_to(original)
        hard = self.directory / "hard.json"
        os.link(original, hard)
        for target in (link, hard):
            with self.subTest(target=target.name), self.assertRaises(ev.EvaluationError):
                ev.write_private_json(target, {})
        self.assertEqual(original.read_text(), "original")

    def test_competing_target_is_preserved_and_temporary_file_removed(self):
        target = self.directory / "race.json"
        original_link = os.link
        def competing_link(source, destination, **kwargs):
            target.write_text("competing fictional content")
            return original_link(source, destination, **kwargs)
        with patch.object(ev.os, "link", side_effect=competing_link), self.assertRaises(ev.EvaluationError):
            ev.write_private_json(target, {})
        self.assertEqual(target.read_text(), "competing fictional content")
        self.assertEqual(list(self.directory.glob(".evidence-bench-*.tmp")), [])

    def test_temporary_name_collision_preserves_unowned_content(self):
        existing = self.directory / ".evidence-bench-collision.tmp"
        existing.write_text("existing fictional content")
        with patch.object(ev.secrets, "token_hex", return_value="collision"), self.assertRaises(ev.EvaluationError):
            ev.write_private_json(self.directory / "out.json", {})
        self.assertEqual(existing.read_text(), "existing fictional content")
        self.assertFalse((self.directory / "out.json").exists())

    def test_held_directory_prevents_parent_replacement_redirect(self):
        parent = self.directory / "parent"
        parent.mkdir()
        other = self.directory / "other"
        other.mkdir()
        moved = self.directory / "moved"
        original_link = os.link
        def replacing_link(source, destination, **kwargs):
            parent.rename(moved)
            parent.symlink_to(other, target_is_directory=True)
            return original_link(source, destination, **kwargs)
        with patch.object(ev.os, "link", side_effect=replacing_link):
            ev.write_private_json(parent / "out.json", {})
        self.assertTrue((moved / "out.json").is_file())
        self.assertFalse((other / "out.json").exists())
        self.assertEqual(list(moved.glob(".evidence-bench-*.tmp")), [])

    def test_cli_prepare_and_score_are_private_and_no_network_is_needed(self):
        prepared = self.directory / "fictional-private-marker" / "run.json"
        output = self.directory / "score.json"
        with patch("socket.create_connection", side_effect=AssertionError("network must not be used")):
            result = invoke("prepare-run", "--dataset", FIXTURE, "--as-of", AS_OF, "--created-at", CAPTURED, "--model-label", "fictional-private-label", "--output", prepared)
            self.assertEqual(result, (0, "PASS: 3 case(s); private unscored run template saved. No model was called.\n", ""))
            prepared.write_text(json.dumps(self.run))
            result = invoke("score-run", "--dataset", FIXTURE, "--run", prepared, "--output", output)
        self.assertEqual(result, (0, "PASS: 3 case(s); private scored run saved. Supplied judgments are not independently verified.\n", ""))
        self.assertEqual(ev.verify_scored(self.data, ev.read_json(output))["metrics"]["sample_size"], 3)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(str(self.directory), result[1] + result[2])

    def test_cli_failure_never_emits_payload_or_creates_output(self):
        self.run["records"][0]["case_id"] = "fictional-private-marker"
        source = self.save(self.run)
        output = self.directory / "failed.json"
        result = invoke("score-run", "--dataset", FIXTURE, "--run", source, "--output", output)
        self.assertEqual(result[0:2], (1, ""))
        self.assertNotIn("fictional-private-marker", result[2])
        self.assertNotIn(str(self.directory), result[2])
        self.assertFalse(output.exists())
        result = invoke("prepare-run", "--dataset", FIXTURE, "--run-id", "fictional private marker", "--output", output)
        self.assertEqual(result[0:2], (1, ""))
        self.assertNotIn("fictional private marker", result[2])
        self.assertFalse(output.exists())
        result = invoke("score-run", "--dataset", FIXTURE, "--unknown-fictional-private-marker")
        self.assertEqual(result[0], 2)
        self.assertNotIn("unknown-fictional-private-marker", result[2])


if __name__ == "__main__":
    unittest.main()
