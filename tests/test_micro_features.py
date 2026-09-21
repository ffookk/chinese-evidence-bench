import contextlib
import io
import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from evidence_bench import __version__
from evidence_bench.__main__ import main


class MicroFeatureTests(unittest.TestCase):
    def fixture(self):
        return json.loads((Path(__file__).resolve().parents[1] / "examples/synthetic.jsonl").read_text().splitlines()[0])

    def run_cli(self, *options, cases=None, content=None, inputs=("file",), stdin=b""):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "fixture.jsonl"
            cases = [self.fixture()] if cases is None else cases
            path.write_text(content if content is not None else "\n".join(json.dumps(case) for case in cases), encoding="utf-8")
            argv = ["validate", *[str(path) if name == "file" else name for name in inputs], "--as-of", "2026-01-31", *options]
            stream = stdin if stdin is None or hasattr(stdin, "read") else io.BytesIO(stdin) if isinstance(stdin, bytes) else io.StringIO(stdin)
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err, patch("sys.stdin", stream):
                try:
                    result = main(argv)
                except SystemExit as exit:
                    result = exit.code
            return result, out.getvalue(), err.getvalue()

    def stats(self, *options, **kwargs):
        result, output, error = self.run_cli("--stats", *options, **kwargs)
        self.assertEqual((result, error), (0, ""))
        return json.loads(next(line[7:] for line in output.splitlines() if line.startswith("STATS: ")))

    def test_version(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as exit:
            main(["--version"])
        self.assertEqual(exit.exception.code, 0)
        self.assertEqual(output.getvalue(), "evidence-bench package " + __version__ + " (schema v1)\n")

    def test_quiet(self):
        self.assertEqual(self.run_cli("--quiet"), (0, "", ""))
        self.assertEqual(self.run_cli("--quiet", content="broken")[0], 1)

    def test_json_summary(self):
        result, out, err = self.run_cli("--json-summary")
        self.assertEqual((result, err), (0, ""))
        self.assertEqual(json.loads(out)["synthetic"], 1)
        self.assertEqual(len(json.loads(out)), 7)
        self.assertEqual(self.run_cli("--json-summary", "--summary")[0], 2)

    def test_expected_count(self):
        self.assertEqual(self.run_cli("--expect-cases", "1")[0], 0)
        self.assertEqual(self.run_cli("--expect-cases", "2", "--summary")[1], "")
        result, out, err = self.run_cli("--expect-cases", "private-argument-marker")
        self.assertEqual(result, 2)
        self.assertNotIn("private-argument-marker", out + err)

    def test_minimum_sources(self):
        self.assertEqual(self.run_cli("--min-sources", "1")[0], 0)
        self.assertEqual(self.run_cli("--min-sources", "2")[0], 1)

    def test_required_answerability(self):
        self.assertEqual(self.run_cli("--require-answerability", "supported")[0], 0)
        self.assertEqual(self.run_cli("--require-answerability", "needs_clarification")[0], 1)
        self.assertNotIn("private-marker", self.run_cli("--require-answerability", "private-marker")[2])

    def test_locator_type(self):
        self.assertEqual(self.run_cli("--require-locator-type", "paragraph")[0], 0)
        self.assertEqual(self.run_cli("--require-locator-type", "page")[0], 1)

    def test_review_age(self):
        self.assertEqual(self.run_cli("--max-review-age", "16")[0], 0)
        self.assertEqual(self.run_cli("--max-review-age", "15")[0], 1)

    def test_source_hosts(self):
        self.assertEqual(self.run_cli("--source-host", "FIXTURE.INVALID")[0], 0)
        result, out, err = self.run_cli("--source-host", "private-host-marker.invalid")
        self.assertEqual(result, 1)
        self.assertNotIn("private-host-marker", out + err)

    def test_source_host_diversity(self):
        self.assertEqual(self.run_cli("--min-source-hosts", "1")[0], 0)
        self.assertEqual(self.run_cli("--min-source-hosts", "2")[0], 1)

    def test_identifier_prefix(self):
        self.assertEqual(self.run_cli("--id-prefix", "synthetic-")[0], 0)
        result, out, err = self.run_cli("--id-prefix", "private-id-marker")
        self.assertEqual(result, 1)
        self.assertNotIn("private-id-marker", out + err)

    def test_sorted_identifiers(self):
        left, right = self.fixture(), self.fixture()
        left["id"], right["id"] = "aaa", "bbb"
        self.assertEqual(self.run_cli("--sorted-ids", cases=[left, right])[0], 0)
        self.assertEqual(self.run_cli("--sorted-ids", cases=[right, left])[0], 1)

    def test_unique_question_wording(self):
        left, right = self.fixture(), self.fixture()
        left["id"], right["id"] = "aaa", "bbb"
        right["question"] = "  " + left["question"].upper() + "  "
        self.assertEqual(self.run_cli(cases=[left, right])[0], 0)
        self.assertEqual(self.run_cli("--unique-questions", cases=[left, right])[0], 1)

    def test_input_byte_limit(self):
        text = json.dumps(self.fixture(), ensure_ascii=False)
        size = len(text.encode("utf-8"))
        self.assertEqual(self.run_cli("--max-input-bytes", str(size), content=text)[0], 0)
        self.assertEqual(self.run_cli("--max-input-bytes", str(size - 1), content=text)[0], 1)
        self.assertEqual(self.run_cli("--max-input-bytes", "9" * 50)[0], 2)

    def test_stdin_utf8_and_single_operand(self):
        data = json.dumps(self.fixture()).encode("utf-8")
        self.assertEqual(self.run_cli(inputs=("-",), stdin=data)[0], 0)
        self.assertEqual(self.run_cli(inputs=("-", "-"), stdin=data)[0], 2)
        self.assertEqual(self.run_cli(inputs=("-",), stdin=bytes([255]))[0], 1)
        self.assertEqual(self.run_cli(inputs=("-",), stdin=None)[0], 1)
        self.assertEqual(self.run_cli("--max-input-bytes", "1", inputs=("-",), stdin=data)[0], 1)
        closed = io.StringIO()
        closed.close()
        self.assertEqual(self.run_cli(inputs=("-",), stdin=closed)[0], 1)
        self.assertEqual(self.run_cli(inputs=("bad" + chr(0) + ".jsonl",))[0], 1)

    def test_explicit_input_format(self):
        text = json.dumps([self.fixture()])
        self.assertEqual(self.run_cli("--input-format", "json", inputs=("-",), stdin=text)[0], 0)
        self.assertEqual(self.run_cli("--input-format", "json", content=text)[0], 0)
        self.assertEqual(self.run_cli("--input-format", "jsonl", content=text)[0], 1)

    def test_blank_jsonl_gate(self):
        text = "\n" + json.dumps(self.fixture())
        self.assertEqual(self.run_cli(content=text)[0], 0)
        result, out, err = self.run_cli("--reject-blank-lines", content=text)
        self.assertEqual((result, out), (1, ""))
        self.assertIn("line 1", err)

    def test_json_diagnostics(self):
        result, out, err = self.run_cli("--json-errors", content="private-input-marker")
        records = [json.loads(line) for line in err.splitlines()]
        self.assertEqual((result, out), (1, ""))
        self.assertEqual(records[0]["location"], "input 1, line 1")
        self.assertEqual(set(records[0]), {"location", "message"})
        self.assertNotIn("private-input-marker", err)

    def test_diagnostic_limit(self):
        result, out, err = self.run_cli("--max-diagnostics", "0", content="broken\nalso broken")
        self.assertEqual((result, out), (1, ""))
        self.assertEqual(err, "FAIL: 0 case(s), 3 error(s).\n")
        self.assertEqual(len(self.run_cli("--max-diagnostics", "1", content="broken")[2].splitlines()), 2)

    def test_statistics_basics(self):
        counts = self.stats()
        self.assertEqual((counts["files"], counts["cases"]), (1, 1))
        self.assertEqual(self.run_cli("--stats", "--json-summary")[0], 2)
        self.assertEqual(self.run_cli("--stats", content="broken")[1], "")

    def test_temporal_label_counts(self):
        counts = self.stats()
        self.assertEqual((counts["time_sensitive_cases"], counts["time_independent_cases"]), (1, 0))

    def test_source_reference_counts(self):
        case = self.fixture()
        case["evidence"] *= 2
        counts = self.stats(cases=[case])
        self.assertEqual((counts["source_references"], counts["unique_source_urls"]), (2, 1))

    def test_batch_host_count(self):
        case = self.fixture()
        other = json.loads(json.dumps(case["evidence"][0]))
        other["source_url"] = "https://second.invalid/rule"
        case["evidence"].append(other)
        self.assertEqual(self.stats(cases=[case])["unique_source_hosts"], 2)

    def test_evidence_coverage_counts(self):
        none, one, many = self.fixture(), self.fixture(), self.fixture()
        none.update(id="none", evidence=[], answerability="needs_clarification", reference_answer=None)
        one["id"], many["id"] = "one", "many"
        many["evidence"] *= 2
        counts = self.stats(cases=[none, one, many])
        self.assertEqual([counts[key] for key in ("cases_without_sources", "cases_with_one_source", "cases_with_multiple_sources")], [1, 1, 1])

    def test_locator_histogram(self):
        counts = self.stats()["locator_type_counts"]
        self.assertEqual(counts, {"page": 0, "paragraph": 1, "section": 0, "table": 0, "timestamp": 0})

    def test_real_label_review_counts(self):
        case = self.fixture()  # Structural test data, not a factual source claim.
        case.update(synthetic=False, question="Fictional classification test only.", review_status="pending", verified_at=None)
        case["evidence"][0]["source_url"] = "https://www.rfc-editor.org/rfc/rfc8259"
        counts = self.stats(cases=[case])
        self.assertEqual((counts["real_reviewed_cases"], counts["real_pending_cases"]), (0, 1))
        self.assertEqual(self.stats()["real_reviewed_cases"], 0)

    def test_review_age_buckets(self):
        cases = []
        for identifier, reviewed in (("fresh", "2026-01-15"), ("recent", "2025-12-01"), ("older", "2024-01-01")):
            case = self.fixture()
            case.update(id=identifier, verified_at=reviewed, time_sensitive=False, valid_as_of=None)
            cases.append(case)
        counts = self.stats(cases=cases)
        self.assertEqual([counts[key] for key in ("reviews_within_30_days", "reviews_31_to_365_days", "reviews_over_365_days")], [1, 1, 1])

    def test_cross_case_source_reuse(self):
        first, second = self.fixture(), self.fixture()
        first["evidence"] *= 2
        self.assertEqual(self.stats(cases=[first])["source_urls_used_by_multiple_cases"], 0)
        second["id"] = "second-case"
        self.assertEqual(self.stats(cases=[first, second])["source_urls_used_by_multiple_cases"], 1)

    def test_question_lengths(self):
        first, second = self.fixture(), self.fixture()
        first.update(id="first", question="A B")
        second.update(id="second", question="ABCDE")
        counts = self.stats(cases=[first, second])
        self.assertEqual([counts[key] for key in ("question_characters_min", "question_characters_max", "question_characters_total")], [3, 5, 8])

    def test_answer_lengths(self):
        first, second = self.fixture(), self.fixture()
        first.update(id="first", reference_answer="A")
        second.update(id="second", reference_answer="WORD")
        counts = self.stats(cases=[first, second])
        self.assertEqual([counts[key] for key in ("reference_answer_count", "answer_characters_min", "answer_characters_max", "answer_characters_total")], [2, 1, 4, 5])

if __name__ == "__main__":
    unittest.main()
