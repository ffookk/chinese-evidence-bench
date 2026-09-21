"""Cross-command parsing regressions using only fictional case data."""

import contextlib
from copy import deepcopy
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from evidence_bench import evaluation as ev
from evidence_bench.__main__ import main, read_cases
from evidence_bench.validator import validate_case


ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-01-31"


class InputRepairTests(unittest.TestCase):
    def setUp(self):
        self.cases = [json.loads(line) for line in (ROOT / "examples/synthetic.jsonl").read_text().splitlines()]
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fictional.jsonl"

    def readers(self, data):
        self.path.write_bytes(data)
        yield list(read_cases(self.path))
        yield list(read_cases(self.path, max_bytes=len(data)))
        for limit in (None, len(data)):
            with patch("sys.stdin", io.BytesIO(data)):
                yield list(read_cases(Path("-"), max_bytes=limit))

    def test_unicode_text_separators_are_not_jsonl_record_boundaries(self):
        for separator in (chr(0x85), chr(0x2028), chr(0x2029)):
            with self.subTest(codepoint=ord(separator)):
                cases = deepcopy(self.cases)
                cases[0]["question"] = "Fictional first" + separator + "second part."
                cases[0]["evidence"][0]["source_title"] = "Fictional source" + separator + "title."
                data = ("\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n").encode("utf-8")
                for records in self.readers(data):
                    self.assertEqual([case for _, case, _ in records], cases)
                    self.assertTrue(all(error is None for _, _, error in records))
                loaded = ev.load_dataset([self.path], AS_OF)
                self.assertEqual(list(loaded.cases), sorted(cases, key=lambda case: case["id"]))
                self.assertEqual(len(ev.prepare_run(loaded)["records"]), len(cases))

    def test_physical_line_endings_agree_across_file_stdin_and_evaluation(self):
        for ending in ("\n", "\r\n", "\r"):
            with self.subTest(ending=repr(ending)):
                data = (ending.join(json.dumps(case) for case in self.cases) + ending).encode("utf-8")
                for records in self.readers(data):
                    self.assertEqual([case for _, case, _ in records], self.cases)
                    self.assertEqual([position for position, _, _ in records], ["line 1", "line 2", "line 3"])
                self.assertEqual(len(ev.load_dataset([self.path], AS_OF).cases), 3)

    def test_blank_and_malformed_lines_keep_physical_positions_when_bounded(self):
        for ending in ("\n", "\r\n", "\r"):
            with self.subTest(ending=repr(ending)):
                data = (json.dumps(self.cases[0]) + ending + ending + "broken" + ending + json.dumps(self.cases[1])).encode("utf-8")
                self.path.write_bytes(data)
                for limit in (None, len(data)):
                    records = list(read_cases(self.path, max_bytes=limit, reject_blank=True))
                    self.assertEqual([position for position, _, _ in records], ["line 1", "line 2", "line 3", "line 4"])
                    self.assertEqual(records[1][2], "blank JSONL line is not allowed")
                    self.assertIn("invalid JSON", records[2][2])
                    self.assertEqual(records[3][1], self.cases[1])

    def test_source_urls_reject_raw_controls_before_url_normalization(self):
        for codepoint in (*range(32), *range(127, 160)):
            for url in (chr(codepoint) + "https://fixture.invalid/rule", "https://fixture.invalid/rule" + chr(codepoint)):
                with self.subTest(codepoint=codepoint, prefix=url.startswith(chr(codepoint))):
                    case = deepcopy(self.cases[0])
                    case["evidence"][0]["source_url"] = url
                    self.assertTrue(any("source_url" in error for error in validate_case(case, today=date.fromisoformat(AS_OF))))
        case["evidence"][0]["source_url"] = "https://fixture.invalid/section%20one"
        self.assertEqual(validate_case(case, today=date.fromisoformat(AS_OF)), [])

    def test_all_required_text_rejects_lone_surrogates_and_preserves_codepoints(self):
        setters = (
            lambda case, value: case.update(question=value),
            lambda case, value: case.update(reference_answer=value),
            lambda case, value: case["evidence"][0].update(source_title=value),
            lambda case, value: case["evidence"][0].update(source_url="https://fixture.invalid/" + value),
            lambda case, value: case["evidence"][0]["evidence_locator"].update(value=value),
        )
        for index, setter in enumerate(setters):
            for codepoint in (0xD800, 0xDFFF, 0x1F642):
                with self.subTest(field=index, codepoint=codepoint):
                    case = deepcopy(self.cases[0]); setter(case, "Fictional" + chr(codepoint))
                    self.path.write_text(json.dumps(case) + "\n", encoding="utf-8")
                    with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                        result = main(["validate", str(self.path), "--as-of", AS_OF, "--summary"])
                    if codepoint < 0x10000:
                        self.assertEqual(result, 1)
                        self.assertEqual(out.getvalue(), "")
                        self.assertNotIn("Fictional", err.getvalue())
                        with self.assertRaises(ev.EvaluationError):
                            ev.load_dataset([self.path], AS_OF)
                    else:
                        self.assertEqual(result, 0)
                        self.assertEqual(ev.load_dataset([self.path], AS_OF).cases[0], case)

    def test_real_sources_reject_legacy_numeric_ip_spellings(self):
        case = deepcopy(self.cases[0]); case["synthetic"] = False
        for host in ("127.1", "0x7f.0.0.1", "0177.0.0.1", "127.0.1", "2130706433", "0X7F.1"):
            with self.subTest(host=host):
                case["evidence"][0]["source_url"] = "https://" + host + "/rule"
                self.assertTrue(any("source_url" in error for error in validate_case(case, today=date.fromisoformat(AS_OF))))
        # Numeric labels inside ordinary hostnames are not numeric addresses.
        case["synthetic"] = True
        case["evidence"][0]["source_url"] = "https://123.fixture.invalid/rule"
        self.assertEqual(validate_case(case, today=date.fromisoformat(AS_OF)), [])
        # This is an invented path used only for format checks; no URL is fetched.
        case["synthetic"] = False
        case["evidence"][0]["source_url"] = "https://123.docs.python.org/fictional-test-only"
        self.assertEqual(validate_case(case, today=date.fromisoformat(AS_OF)), [])

    def test_bracketed_authorities_cannot_masquerade_as_domain_names(self):
        for host, synthetic in (("[v1.a]", False), ("[v1.fixture.invalid]", True), ("[::1]", False)):
            with self.subTest(host=host, synthetic=synthetic):
                case = deepcopy(self.cases[0]); case["synthetic"] = synthetic
                case["evidence"][0]["source_url"] = "https://" + host + "/fictional"
                self.assertTrue(any("source_url" in error for error in validate_case(case, today=date.fromisoformat(AS_OF))))


if __name__ == "__main__":
    unittest.main()
