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
        self.assertIn("PASS: 8 browser scenarios", output)
        self.assertEqual(errors, "")

    def test_first_failure_stops_repetitions_and_preserves_fixed_diagnostics(self):
        code, children, output, errors = self.exercise(["--browser", "firefox", "--repeat", "3"], fail_at=5)
        self.assertEqual(code, 1)
        self.assertEqual(len(children), 5)
        self.assertIn("(iteration 2/3) at checkpoint 94 (timeout; disabled)", errors)
        self.assertNotIn("fictional-private-child-output", errors + output)
        self.assertNotIn("PASS: 12 browser scenarios", output)

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
