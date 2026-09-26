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


class BrowserStateDiagnosticsTests(unittest.TestCase):
    def state(self, **changes):
        value = {"target": "first-case", "case_buttons": 20, **{field: False for field in runner.STATE_FLAGS}}
        value.update(changes)
        return value

    def payload(self, **changes):
        value = {"browser": "firefox", "scenario": "review-controls", "passed": False,
                 "checkpoint": 90, "error_kind": "timeout", "reason": "unknown", "state": self.state()}
        value.update(changes)
        return json.dumps(value)

    def decode(self, text):
        return runner.failure_checkpoint(text, "firefox", "review-controls")

    def test_valid_state_reports_only_fixed_codes_and_bounded_flags(self):
        for count in (0, 20, 63):
            output = self.decode(self.payload(state=self.state(case_buttons=count, filters_clear=True)))
            self.assertIn(f"case_buttons={count}", output)
            self.assertIn("target=first-case", output)
            self.assertIn("filters_clear=1", output)
            self.assertIn("target_hit=0", output)
            self.assertLess(len(output), 400)

    def test_missing_state_remains_compatible_and_capture_failure_omits_state(self):
        without = json.loads(self.payload())
        without.pop("state")
        expected = " at checkpoint 90 (timeout; unknown)"
        self.assertEqual(self.decode(json.dumps(without)), expected)
        self.assertEqual(self.decode(self.payload(state=None)), expected)

    def test_untrusted_fields_values_and_types_reject_the_entire_diagnostic(self):
        canary = "FictionalDiagnosticCanary-7391"
        states = [self.state(extra=canary), self.state(target=canary), self.state(target="response"),
                  self.state(case_buttons=-1), self.state(case_buttons=64), self.state(case_buttons=True),
                  self.state(case_buttons=1.0), self.state(case_buttons=canary), [], canary]
        for field in runner.STATE_FLAGS:
            for value in (0, 1, None, "false", canary):
                states.append(self.state(**{field: value}))
        incomplete = self.state()
        incomplete.pop("target_hit")
        states.append(incomplete)
        for state in states:
            with self.subTest(state_type=type(state).__name__):
                output = self.decode(self.payload(state=state))
                self.assertEqual(output, "")
                self.assertNotIn(canary, output)

    def test_state_cannot_be_attached_to_unrelated_scenario_or_target(self):
        for scenario in ("deleted-run", "failed-selection", "reload-failure", "diagnostic-privacy"):
            value = json.loads(self.payload(scenario=scenario))
            self.assertEqual(runner.failure_checkpoint(json.dumps(value), "firefox", scenario), "")
        self.assertEqual(self.decode(self.payload(checkpoint=94)), "")
        value = json.loads(self.payload(scenario="preview-layout", checkpoint=21, state=self.state(target="reset-filters")))
        self.assertIn("target=reset-filters", runner.failure_checkpoint(json.dumps(value), "firefox", "preview-layout"))

    def test_duplicate_oversized_and_deep_documents_are_rejected(self):
        document = self.payload()
        nested_duplicate = document.replace('"case_buttons": 20', '"case_buttons": 0, "case_buttons": 20')
        top_duplicate = document.replace('"checkpoint": 90', '"checkpoint": 91, "checkpoint": 90')
        for text in (nested_duplicate, top_duplicate, document + " " * 4096, "[" * 1500 + "]" * 1500, None, b"{}"):
            self.assertEqual(self.decode(text), "")

    def test_capture_deadline_and_page_errors_do_not_return_raw_diagnostics(self):
        import shutil
        import subprocess

        node = shutil.which("node")
        self.assertIsNotNone(node, "Browser diagnostic tests require Node.js; no checks are skipped.")
        script = """
const {captureState} = require(process.argv[1]);
(async () => {
  const canary = "FictionalDiagnosticCanary-7391";
  const rejected = await captureState({isClosed: () => false, evaluate: async () => { throw new Error(canary); }}, 90);
  const missing = await captureState(null, 90);
  const closed = await captureState({isClosed: () => true}, 90);
  const unavailable = await captureState({isClosed: () => false, evaluate: () => new Promise(() => {})}, 90);
  process.stdout.write(JSON.stringify({rejected, missing, closed, unavailable}));
})().catch(() => { process.exitCode = 1; });
"""
        result = subprocess.run([node, "-e", script, str(TOOLS / "diagnostics.cjs")], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), {"rejected": None, "missing": None, "closed": None, "unavailable": None})
        self.assertNotIn("FictionalDiagnosticCanary-7391", result.stdout)


class BrowserRepetitionTests(unittest.TestCase):
    def exercise(self, arguments, fail_at=None, malformed=False):
        import contextlib
        import io
        from types import SimpleNamespace
        from unittest.mock import Mock, patch

        servers, children = [], []
        stdout, stderr = io.StringIO(), io.StringIO()

        def make_server(data):
            server = Mock(origin="http://127.0.0.1:12345")
            servers.append(server)
            return server

        def run_child(command, **kwargs):
            if command[1] == "-p":
                return SimpleNamespace(returncode=0, stdout="true\n", stderr="")
            browser, scenario = command[-2:]
            children.append((browser, scenario))
            if len(children) == fail_at:
                result = {"browser": browser, "scenario": scenario, "passed": False,
                          "checkpoint": 94, "error_kind": "timeout", "reason": "disabled"}
                if malformed:
                    result["details"] = "fictional-private-child-output"
                return SimpleNamespace(returncode=1, stdout=json.dumps(result), stderr="fictional-private-child-output")
            return SimpleNamespace(returncode=0, stdout=json.dumps({"browser": browser, "scenario": scenario,
                                   "passed": True, "external_requests": 0, "page_errors": 0}), stderr="")

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", ["browser-check", *arguments]))
            stack.enter_context(patch.object(runner.shutil, "which", return_value="node"))
            stack.enter_context(patch.object(runner.subprocess, "run", side_effect=run_child))
            stack.enter_context(patch.object(runner, "dataset", return_value=object()))
            seed = stack.enter_context(patch.object(runner, "seed"))
            stack.enter_context(patch.object(runner, "create_server", side_effect=make_server))
            threads = stack.enter_context(patch.object(runner.threading, "Thread", side_effect=lambda **kwargs: Mock()))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            code = runner.main()
        self.assertEqual(seed.call_count, len(children))
        self.assertEqual(threads.call_count, len(children))
        self.assertEqual(len({id(server) for server in servers}), len(children))
        for server in servers:
            server.shutdown.assert_called_once_with()
            server.server_close.assert_called_once_with()
        return code, children, stdout.getvalue(), stderr.getvalue()

    def test_default_runs_each_engine_and_scenario_once(self):
        code, children, output, errors = self.exercise([])
        self.assertEqual(code, 0)
        self.assertEqual(children, [(engine, scenario) for engine in ("chromium", "firefox") for scenario in runner.SCENARIOS])
        self.assertNotIn("iteration", output)
        self.assertEqual(errors, "")

    def test_repetitions_use_fresh_state_and_do_not_duplicate_requested_engine(self):
        code, children, output, errors = self.exercise(["--browser", "firefox", "--browser", "firefox", "--repeat", "2"])
        self.assertEqual(code, 0)
        self.assertEqual(children, [("firefox", scenario) for _ in range(2) for scenario in runner.SCENARIOS])
        self.assertIn("(iteration 1/2)", output)
        self.assertIn("(iteration 2/2)", output)
        self.assertIn("PASS: 12 browser scenarios", output)
        self.assertEqual(errors, "")

    def test_first_failure_stops_repetitions_and_preserves_fixed_diagnostics(self):
        code, children, output, errors = self.exercise(["--browser", "firefox", "--repeat", "3"], fail_at=7)
        self.assertEqual(code, 1)
        self.assertEqual(len(children), 7)
        self.assertIn("(iteration 2/3) at checkpoint 94 (timeout; disabled)", errors)
        self.assertNotIn("fictional-private-child-output", errors + output)
        self.assertNotIn("PASS: 18 browser scenarios", output)

    def test_repeated_failure_does_not_publish_untrusted_child_details(self):
        code, children, output, errors = self.exercise(["--browser", "firefox", "--repeat", "2"], fail_at=1, malformed=True)
        self.assertEqual(code, 1)
        self.assertEqual(len(children), 1)
        self.assertNotIn("fictional-private-child-output", errors + output)
        self.assertNotIn("checkpoint", errors)

    def test_repeat_bounds_and_invalid_arguments_fail_before_starting_browser(self):
        import contextlib
        import io
        from unittest.mock import patch

        self.assertEqual(runner.repeat_count("1"), 1)
        self.assertEqual(runner.repeat_count("20"), 20)
        for value in ("0", "21", "-1", "1.5", "fictional-private-argument", "9" * 5000, chr(0x0661)):
            with self.subTest(value_kind="long" if len(value) > 30 else value):
                errors = io.StringIO()
                with patch.object(sys, "argv", ["browser-check", "--repeat", value]), patch.object(runner.shutil, "which") as which, contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as result:
                    runner.main()
                self.assertEqual(result.exception.code, 2)
                which.assert_not_called()
                self.assertIn("repeat must be an integer from 1 through 20", errors.getvalue())
                self.assertNotIn("fictional-private-argument", errors.getvalue())
                self.assertNotIn("9" * 5000, errors.getvalue())
