"""Dataset release gates; these checks do not verify source truth or availability."""

import contextlib
import io
from pathlib import Path
import unittest

from evidence_bench.__main__ import main, read_cases


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "data/public-facts.jsonl"


class PublicDatasetTests(unittest.TestCase):
    def run_cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as errors:
            result = main(["validate", *map(str, args)])
        self.assertEqual(result, 0, errors.getvalue())

    def test_published_data_passes_real_reviewed_release_gate(self):
        self.run_cli(PUBLIC, "--real-only", "--require-reviewed")

    def test_all_shipped_datasets_have_globally_unique_ids(self):
        datasets = sorted((ROOT / "data").glob("*.jsonl"))
        datasets += sorted((ROOT / "examples").glob("*.jsonl"))
        self.assertIn(PUBLIC, datasets)
        self.run_cli(*datasets)

    def test_each_published_case_has_a_review_trail(self):
        records = list(read_cases(PUBLIC))
        self.assertGreaterEqual(len(records), 8)
        review = (ROOT / "docs/source-review.md").read_text(encoding="utf-8")
        for position, case, error in records:
            with self.subTest(position=position):
                self.assertIsNone(error)
                self.assertIn(f'`{case["id"]}`', review)
                for evidence in case["evidence"]:
                    self.assertIn(evidence["source_url"], review)


if __name__ == "__main__":
    unittest.main()
