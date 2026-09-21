import contextlib
from copy import deepcopy
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest

from evidence_bench.__main__ import main
from evidence_bench.validator import validate_case


ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 1, 31)


class CaseValidationTests(unittest.TestCase):
    def setUp(self):
        self.cases = [json.loads(line) for line in (ROOT / "examples/synthetic.jsonl").read_text(encoding="utf-8").splitlines()]
        self.case = deepcopy(self.cases[0])

    def assert_error(self, expected):
        self.assertTrue(any(expected in error for error in validate_case(self.case, today=TODAY)))

    def test_all_synthetic_examples_are_well_formed(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(validate_case(case, today=TODAY), [])

    def test_missing_and_unknown_fields(self):
        del self.case["verified_at"]
        self.assert_error("missing required")
        self.case["unexpected"] = "placeholder"
        self.assert_error("unknown fields")

    def test_duplicate_id_is_rejected_across_files(self):
        with tempfile.TemporaryDirectory() as temp:
            left, right = Path(temp) / "left.json", Path(temp) / "right.jsonl"
            left.write_text(json.dumps([self.case]), encoding="utf-8")
            right.write_text(json.dumps(self.case) + "\n", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(main(["validate", str(left), str(right), "--as-of", "2026-01-31"]), 1)
            self.assertIn("duplicate across", stderr.getvalue())
            self.assertNotIn(self.case["id"], stderr.getvalue())
            self.assertNotIn(temp, stderr.getvalue())

    def test_supported_requires_answer_and_locatable_evidence(self):
        self.case["reference_answer"] = "  "
        self.case["evidence"][0]["evidence_locator"]["value"] = ""
        self.assert_error("reference_answer")
        self.assert_error("evidence_locator.value")
        self.case["evidence"] = []
        self.assert_error("at least one source")

    def test_calendar_dates_and_temporal_order(self):
        for value in ("2026-02-30", "2026-1-15", "2026-01-15T12:00:00", "2027-01-15", 20260115):
            with self.subTest(value=value):
                self.case["verified_at"] = value
                self.assert_error("verified_at")
        self.case["verified_at"] = "2026-01-01"
        self.assert_error("cannot precede")

    def test_pending_cannot_claim_verification(self):
        self.case["review_status"] = "pending"
        self.assert_error("pending cases must use null")
        self.case["verified_at"] = None
        self.assertEqual(validate_case(self.case, today=TODAY), [])

    def test_reviewed_and_time_sensitive_require_dates(self):
        self.case["verified_at"] = None
        self.case["valid_as_of"] = None
        self.assert_error("reviewed cases require")
        self.assert_error("time-sensitive cases require")
        self.case["time_sensitive"] = False
        self.case["valid_as_of"] = "2026-01-10"
        self.assert_error("not time-sensitive")

    def test_uncertain_answer_cannot_contain_reference_answer(self):
        self.case["answerability"] = "insufficient_evidence"
        self.assert_error("must be null unless")

    def test_urls_reject_credentials_query_fragments_and_real_synthetic_sources(self):
        credential_fixture = "https://demo" + ":placeholder@" + "fixture.invalid/rules"
        for value in ("file:///placeholder", "http://fixture.invalid/rules", credential_fixture, "https://fixture.invalid/rules?key=placeholder", "https://fixture.invalid/rules#part", "https://example.org/rules", "https://fixture.invalid:abc/rules", "https://bad..invalid/rules", "https://-bad.invalid/rules"):
            with self.subTest(value=value):
                self.case["evidence"][0]["source_url"] = value
                self.assert_error("source_url")

    def test_real_sources_reject_local_addresses(self):
        self.case["synthetic"] = False
        for value in ("https://127.0.0.1/rules", "https://localhost/rules", "https://fixture.invalid/rules", "https://fixture.local/rules", "https://example.org/rules", "https://docs.example.com/rules", "https://example.net/rules", "https://fixture.test/rules", "https://fixture.example/rules"):
            with self.subTest(value=value):
                self.case["evidence"][0]["source_url"] = value
                self.assert_error("source_url")

    def test_source_url_rejects_backslashes(self):
        self.case["evidence"][0]["source_url"] = "https://fixture.invalid/" + chr(92) + "rules"
        self.assert_error("source_url")

    def test_bad_types_do_not_crash(self):
        for field in ("answerability", "review_status", "id", "synthetic", "schema_version", "question", "evidence"):
            with self.subTest(field=field):
                case = deepcopy(self.case)
                case[field] = {}
                self.assertTrue(validate_case(case, today=TODAY))
        self.case["schema_version"] = True
        self.assert_error("schema_version")


class CliTests(unittest.TestCase):
    def run_input(self, content, suffix=".jsonl", flags=()):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / ("fixture" + suffix)
            path.write_text(content, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
                result = main(["validate", str(path), "--as-of", "2026-01-31", *flags])
            return result, stdout.getvalue(), stderr.getvalue()

    def test_json_array_and_jsonl(self):
        content = (ROOT / "examples/synthetic.jsonl").read_text(encoding="utf-8")
        cases = [json.loads(line) for line in content.splitlines()]
        for text, extension in (("\n" + content + "\n", ".jsonl"), (json.dumps(cases), ".json")):
            result, output, _ = self.run_input(text, extension)
            self.assertEqual(result, 0)
            self.assertIn("3 case(s)", output)

    def test_real_reviewed_gate_rejects_synthetic_pending_fixtures(self):
        content = (ROOT / "examples/synthetic.jsonl").read_text(encoding="utf-8")
        result, _, error = self.run_input(content, flags=("--real-only", "--require-reviewed"))
        self.assertEqual(result, 1)
        self.assertIn("--real-only", error)
        self.assertIn("--require-reviewed", error)

    def test_invalid_inputs_fail(self):
        for content, suffix in (("", ".jsonl"), ("[]", ".json"), ("{}", ".json"), ('{"id": "a", "id": "b"}', ".jsonl"), ('{"value": NaN}', ".jsonl"), ("broken", ".jsonl"), ("null", ".jsonl")):
            with self.subTest(content=content):
                self.assertEqual(self.run_input(content, suffix)[0], 1)

    def test_missing_file_returns_error_without_echoing_path(self):
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(main(["validate", "missing-fixture.jsonl"]), 1)
        self.assertIn("cannot read", stderr.getvalue())
        self.assertNotIn("missing-fixture", stderr.getvalue())

    def test_malformed_line_does_not_hide_later_lines(self):
        content = (ROOT / "examples/synthetic.jsonl").read_text(encoding="utf-8")
        result, _, error = self.run_input("broken\n" + content)
        self.assertEqual(result, 1)
        self.assertIn("line 1", error)
        self.assertIn("3 case(s)", error)

    def test_default_success_output_is_unchanged(self):
        content = (ROOT / "examples/synthetic.jsonl").read_text(encoding="utf-8")
        result, output, error = self.run_input(content)
        self.assertEqual(result, 0)
        self.assertEqual(error, "")
        self.assertEqual(output, "PASS: 3 case(s); format checks only. Factual support and privacy still require review.\n")

    def test_summary_counts_all_mixed_inputs(self):
        with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
            result = main([
                "validate", str(ROOT / "examples/synthetic.jsonl"), str(ROOT / "data/public-facts.jsonl"),
                "--as-of", "2026-09-20", "--summary",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(stderr.getvalue(), "")
        lines = stdout.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], "PASS: 11 case(s); format checks only. Factual support and privacy still require review.")
        self.assertTrue(lines[1].startswith("SUMMARY: "))
        self.assertEqual(json.loads(lines[1].removeprefix("SUMMARY: ")), {
            "real": 8, "synthetic": 3, "reviewed": 10, "pending": 1,
            "supported": 9, "insufficient_evidence": 1, "needs_clarification": 1,
        })

    def test_summary_suppressed_after_invalid_records(self):
        content = (ROOT / "examples/synthetic.jsonl").read_text(encoding="utf-8")
        invalid = json.loads(content.splitlines()[0])
        invalid["id"] = "invalid-status-fixture"
        invalid["review_status"] = "status-payload-marker"
        for bad_record in ("broken", "null", json.dumps(invalid)):
            with self.subTest(bad_record=bad_record):
                result, output, error = self.run_input(content + "\n" + bad_record, flags=("--summary",))
                self.assertEqual(result, 1)
                self.assertEqual(output, "")
                self.assertIn("FAIL:", error)
                self.assertNotIn("status-payload-marker", error)

    def test_summary_suppressed_for_duplicates_and_unreadable_files(self):
        source = ROOT / "examples/synthetic.jsonl"
        for second in (source, ROOT / "missing-payload-marker.jsonl"):
            with self.subTest(second=second):
                with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
                    result = main(["validate", str(source), str(second), "--as-of", "2026-01-31", "--summary"])
                self.assertEqual(result, 1)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("FAIL:", stderr.getvalue())
                self.assertNotIn(str(second), stderr.getvalue())

    def test_summary_does_not_bypass_strict_gates(self):
        content = (ROOT / "examples/synthetic.jsonl").read_text(encoding="utf-8")
        for gate in ("--real-only", "--require-reviewed"):
            with self.subTest(gate=gate):
                result, output, error = self.run_input(content, flags=("--summary", gate))
                self.assertEqual(result, 1)
                self.assertEqual(output, "")
                self.assertIn(gate, error)

    def test_summary_contains_only_fixed_counts_and_no_payload(self):
        case = json.loads((ROOT / "examples/synthetic.jsonl").read_text(encoding="utf-8").splitlines()[0])
        case.update(id="id-payload-marker", question="Question payload marker", reference_answer="Answer payload marker")
        case["evidence"][0].update(source_url="https://payload-marker.invalid/rule", source_title="Title payload marker")
        case["evidence"][0]["evidence_locator"]["value"] = "Locator payload marker"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "path-payload-marker.json"
            path.write_text(json.dumps([case]), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
                result = main(["validate", str(path), "--as-of", "2026-01-31", "--summary"])
            output = stdout.getvalue()
            self.assertEqual(result, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(output.splitlines()[1], 'SUMMARY: {"real": 0, "synthetic": 1, "reviewed": 1, "pending": 0, "supported": 1, "insufficient_evidence": 0, "needs_clarification": 0}')
            for value in (case["id"], case["question"], case["reference_answer"], case["evidence"][0]["source_url"], case["evidence"][0]["source_title"], case["evidence"][0]["evidence_locator"]["value"], str(path), temp):
                self.assertNotIn(value, output)


if __name__ == "__main__":
    unittest.main()
