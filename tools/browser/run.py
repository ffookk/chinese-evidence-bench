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

SCENARIOS = ("review-controls", "deleted-run", "failed-selection", "reload-failure")


def failure_checkpoint(output, browser, scenario):
    """Accept only fixed failure metadata; never return child diagnostics."""
    try:
        value = json.loads(output)
    except (ValueError, TypeError):
        return ""
    if not isinstance(value, dict) or set(value) != {"browser", "scenario", "passed", "checkpoint", "error_kind"}:
        return ""
    if value["browser"] != browser or value["scenario"] != scenario or value["passed"] is not False:
        return ""
    number, kind = value["checkpoint"], value["error_kind"]
    if type(number) is not int or not 0 <= number <= 19 or kind not in ("assertion", "timeout", "other"):
        return ""
    return f" at checkpoint {number} ({kind})"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", action="append", choices=("chromium", "firefox"), help="run one engine; default: both required engines")
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
                    print(f"FAIL: {browser} / {scenario}{location}. A required browser check did not complete; no checks were skipped.", file=sys.stderr)
                    return 1
                summary = json.loads(result.stdout)
                if summary != {"browser": browser, "scenario": scenario, "passed": True, "external_requests": 0, "page_errors": 0}:
                    raise ValueError
                print(f"PASS: {browser} / {scenario}; no external page requests or page errors.")
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
