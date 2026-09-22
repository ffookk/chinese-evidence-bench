"""Test that browser-failure diagnostics expose only fixed metadata."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "browser"
sys.path.insert(0, str(TOOLS))
try:
    spec = importlib.util.spec_from_file_location("browser_regression_runner", TOOLS / "run.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
finally:
    sys.path.remove(str(TOOLS))


class BrowserDiagnosticsTests(unittest.TestCase):
    def payload(self, **changes):
        value = {"browser": "firefox", "scenario": "review-controls", "passed": False, "checkpoint": 13, "error_kind": "assertion", "reason": "none"}
        value.update(changes)
        return json.dumps(value)

    def test_only_fixed_checkpoint_and_error_kinds_are_reported(self):
        for number, kind, reason in ((0, "other", "none"), (13, "assertion", "none"), (99, "timeout", "disabled")):
            with self.subTest(number=number, kind=kind):
                detail = kind if reason == "none" else f"{kind}; {reason}"
                self.assertEqual(runner.failure_checkpoint(self.payload(checkpoint=number, error_kind=kind, reason=reason), "firefox", "review-controls"), f" at checkpoint {number} ({detail})")

    def test_supplied_diagnostics_and_invalid_types_are_not_reported(self):
        for changes in ({"details": "Fictional supplied detail"}, {"checkpoint": "Fictional supplied detail"}, {"checkpoint": True}, {"checkpoint": -1}, {"checkpoint": 100}, {"error_kind": "Fictional supplied detail"}, {"passed": 0}, {"reason": "Fictional supplied detail"}):
            with self.subTest(fields=sorted(changes)):
                self.assertEqual(runner.failure_checkpoint(self.payload(**changes), "firefox", "review-controls"), "")

    def test_invalid_documents_or_other_scenarios_are_not_reported(self):
        for output in ("Fictional raw child diagnostic", "[]", "null", self.payload(browser="chromium"), self.payload(scenario="deleted-run")):
            self.assertEqual(runner.failure_checkpoint(output, "firefox", "review-controls"), "")
