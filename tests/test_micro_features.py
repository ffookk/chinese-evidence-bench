import contextlib
import io
import unittest
from evidence_bench import __version__
from evidence_bench.__main__ import main


class MicroFeatureTests(unittest.TestCase):
    def test_version(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as exit:
            main(["--version"])
        self.assertEqual(exit.exception.code, 0)
        self.assertEqual(output.getvalue(), "evidence-bench package " + __version__ + " (schema v1)\n")

if __name__ == "__main__":
    unittest.main()
