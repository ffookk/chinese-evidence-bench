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

if __name__ == "__main__":
    unittest.main()
