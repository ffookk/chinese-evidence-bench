"""Run portable browser regressions without writing or uploading test artifacts."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evidence_bench.workbench import create_server
from fixtures import dataset, seed

SCENARIOS = ("review-controls", "preview-layout", "diagnostic-privacy", "deleted-run", "failed-selection", "reload-failure")


STATE_FLAGS = ("filters_clear", "reset_enabled", "first_selected", "preview_pending", "target_present", "target_enabled", "target_visible", "target_in_view", "target_hit")
STATE_TARGETS = {20: "model-input", 21: "reset-filters", 22: "first-case", 23: "parameters-input", 24: "model-input",
                 90: "first-case", 91: "first-case", 92: "response", 93: "response", 94: "next-case", 95: "next-case", 96: "previous-case", 97: "previous-case"}


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def failure_state(state, scenario, checkpoint):
    """Decode an exact allowlist independently from the browser-side collector."""
    if state is None:
        return ""
    if scenario not in ("review-controls", "preview-layout") or not isinstance(state, dict):
        return None
    if set(state) != {"target", "case_buttons", *STATE_FLAGS}:
        return None
    if state["target"] != STATE_TARGETS.get(checkpoint, "none"):
        return None
    if type(state["case_buttons"]) is not int or not 0 <= state["case_buttons"] <= 63:
        return None
    if any(type(state[field]) is not bool for field in STATE_FLAGS):
        return None
    flags = ", ".join(f"{field}={int(state[field])}" for field in STATE_FLAGS)
    return f" [state target={state['target']}, case_buttons={state['case_buttons']}, {flags}]"


def failure_checkpoint(output, browser, scenario):
    """Accept only fixed failure metadata; never return child diagnostics."""
    if not isinstance(output, str) or len(output) > 4096:
        return ""
    try:
        value = json.loads(output, object_pairs_hook=strict_object)
    except (ValueError, TypeError, RecursionError):
        return ""
    fields = {"browser", "scenario", "passed", "checkpoint", "error_kind", "reason"}
    if not isinstance(value, dict) or set(value) not in (fields, fields | {"state"}):
        return ""
    if value["browser"] != browser or value["scenario"] != scenario or value["passed"] is not False:
        return ""
    number, kind = value["checkpoint"], value["error_kind"]
    if type(number) is not int or not 0 <= number <= 99 or kind not in ("assertion", "timeout", "other"):
        return ""
    reason = value["reason"]
    if reason not in ("none", "unknown", "not-stable", "not-visible", "intercepted", "detached", "disabled", "not-editable", "outside-viewport"):
        return ""
    state = failure_state(value.get("state"), scenario, number)
    if state is None:
        return ""
    detail = kind if reason == "none" else f"{kind}; {reason}"
    return f" at checkpoint {number} ({detail}){state}"


def repeat_count(value):
    """Bound repeated diagnostics without echoing a supplied argument."""
    try:
        if not value.isascii() or not value.isdecimal():
            raise ValueError
        count = int(value)
        if not 1 <= count <= 20:
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError("repeat must be an integer from 1 through 20") from None
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="append", choices=("chromium", "firefox"), help="run one engine; default: both required engines")
    parser.add_argument("--repeat", type=repeat_count, default=1, metavar="1..20", help="repeat every requested scenario with fresh state; stop at the first failure")
    args = parser.parse_args()
    node = shutil.which("node")
    if node is None:
        print("Browser checks require Node.js 24 or newer; no checks were skipped.", file=sys.stderr)
        return 1
    version = subprocess.run([node, "-p", "Number(process.versions.node.split('.')[0]) >= 24"], capture_output=True, text=True, check=False)
    if version.returncode or version.stdout.strip() != "true":
        print("Browser checks require Node.js 24 or newer; no checks were skipped.", file=sys.stderr)
        return 1
    data = dataset()
    passed = 0
    for browser in dict.fromkeys(args.browser or ("chromium", "firefox")):
        for iteration in range(1, args.repeat + 1):
            iteration_label = "" if args.repeat == 1 else f" (iteration {iteration}/{args.repeat})"
            for scenario in SCENARIOS:
                server = create_server(data)
                thread = None
                try:
                    seed(server.session)
                    thread = threading.Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    result = subprocess.run([node, str(Path(__file__).with_name("checks.cjs")), server.origin, browser, scenario], capture_output=True, text=True, timeout=120)
                    if result.returncode:
                        location = failure_checkpoint(result.stdout, browser, scenario)
                        print(f"FAIL: {browser} / {scenario}{iteration_label}{location}. A required browser check did not complete; no checks were skipped.", file=sys.stderr)
                        return 1
                    summary = json.loads(result.stdout)
                    if summary != {"browser": browser, "scenario": scenario, "passed": True, "external_requests": 0, "page_errors": 0}:
                        raise ValueError
                    print(f"PASS: {browser} / {scenario}{iteration_label}; no external page requests or page errors.")
                    passed += 1
                finally:
                    if thread is not None:
                        server.shutdown()
                        thread.join(timeout=10)
                    server.server_close()
    print(f"PASS: {passed} browser scenarios; fictional data only, no artifacts uploaded.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Browser checks could not complete; inspect the local installation. No checks were skipped.", file=sys.stderr)
        raise SystemExit(1)
