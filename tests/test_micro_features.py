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
            stream = io.BytesIO(stdin) if isinstance(stdin, bytes) else io.StringIO(stdin)
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

if __name__ == "__main__":
    unittest.main()
