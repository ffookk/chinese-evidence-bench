"""Run with: python3 -m evidence_bench validate examples/synthetic.jsonl"""

import argparse
from datetime import date
import json
from pathlib import Path
import sys

from . import __version__
from .validator import ANSWERABILITY, LOCATOR_TYPES, validate_case


def _strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non-standard JSON constant")


def _decode(text):
    return json.loads(text, object_pairs_hook=_strict_object, parse_constant=_reject_constant)


def read_cases(path):
    """Yield (position, case, error); JSONL errors do not hide later records."""
    try:
        with path.open(encoding="utf-8") as stream:
            if path.suffix.lower() == ".jsonl":
                for line_no, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    try:
                        yield f"line {line_no}", _decode(line), None
                    except (ValueError, RecursionError):
                        yield f"line {line_no}", None, "invalid JSON (including duplicate keys or non-standard constants)"
            else:
                try:
                    cases = _decode(stream.read())
                except (ValueError, RecursionError):
                    yield "file", None, "invalid JSON (including duplicate keys or non-standard constants)"
                    return
                if not isinstance(cases, list):
                    yield "file", None, "JSON input must be an array of cases"
                    return
                for index, case in enumerate(cases, 1):
                    yield f"case {index}", case, None
    except (OSError, UnicodeError):
        yield "file", None, "cannot read input as UTF-8"


def _count(value):
    if not value.isascii() or not value.isdecimal() or len(value) > 9:
        raise ValueError
    return int(value)


def _as_of(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid command-line arguments; use --help for supported options.\n")


def main(argv=None):
    parser = SafeParser(prog="evidence-bench", description="Offline evidence case format checks; does not verify factual truth or privacy.")
    parser.add_argument("--version", action="version", version="evidence-bench package " + __version__ + " (schema v1)")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate JSON arrays or JSONL case files")
    validate.add_argument("paths", nargs="+", type=Path)
    validate.add_argument("--as-of", type=_as_of, default=date.today(), help="date ceiling for reproducible validation (default: local today)")
    validate.add_argument("--require-reviewed", action="store_true", help="reject pending cases")
    validate.add_argument("--real-only", action="store_true", help="reject synthetic cases")
    validate.add_argument("--summary", action="store_true", help="print fixed-schema aggregate counts only after every input passes")
    validate.add_argument("--quiet", action="store_true", help="suppress the ordinary success line")
    validate.add_argument("--json-summary", action="store_true", help="emit only the seven summary counters as JSON")
    validate.add_argument("--expect-cases", type=_count, help="require this nonnegative total case count")
    validate.add_argument("--min-sources", type=_count, help="minimum source entries per case")
    validate.add_argument("--require-answerability", choices=sorted(ANSWERABILITY), help="require one answerability state throughout")
    validate.add_argument("--require-locator-type", choices=sorted(LOCATOR_TYPES), help="require evidence with this locator type")
    args = parser.parse_args(argv)
    if args.summary and args.json_summary:
        parser.error("choose one summary format")
    seen = set()
    errors = 0
    count = 0
    summary = {
        "real": 0, "synthetic": 0,
        "reviewed": 0, "pending": 0,
        "supported": 0, "insufficient_evidence": 0, "needs_clarification": 0,
    }
    for file_index, path in enumerate(args.paths, 1):
        if path.suffix.lower() not in {".json", ".jsonl"}:
            print(f"input {file_index}: expected a .json or .jsonl extension", file=sys.stderr)
            errors += 1
            continue
        records = 0
        for position, case, error in read_cases(path):
            prefix = f"input {file_index}, {position}"
            if error:
                print(f"{prefix}: {error}", file=sys.stderr)
                errors += 1
                continue
            records += 1
            count += 1
            problems = validate_case(case, today=args.as_of)
            if isinstance(case, dict):
                identifier = case.get("id")
                if isinstance(identifier, str):
                    if identifier in seen:
                        problems.append("id: duplicate across the supplied inputs")
                    seen.add(identifier)
                if args.require_reviewed and case.get("review_status") != "reviewed":
                    problems.append("review_status: --require-reviewed rejects pending cases")
                if args.real_only and case.get("synthetic") is not False:
                    problems.append("synthetic: --real-only requires false")
            if args.min_sources is not None and not problems and len(case["evidence"]) < args.min_sources:
                problems.append("evidence: fewer than the required source entries")
            if args.require_answerability and not problems and case["answerability"] != args.require_answerability:
                problems.append("answerability: does not match the required state")
            if args.require_locator_type and not problems and (not case["evidence"] or any(source["evidence_locator"]["type"] != args.require_locator_type for source in case["evidence"])):
                problems.append("evidence: missing evidence or a different locator type")
            for problem in problems:
                print(f"{prefix}: {problem}", file=sys.stderr)
            errors += len(problems)
            if (args.summary or args.json_summary) and not problems:
                summary["synthetic" if case["synthetic"] else "real"] += 1
                summary[case["review_status"]] += 1
                summary[case["answerability"]] += 1
        if records == 0:
            print(f"input {file_index}: no readable case records", file=sys.stderr)
            errors += 1
    if args.expect_cases is not None and count != args.expect_cases:
        print("batch: case count does not match the requested total", file=sys.stderr)
        errors += 1
    if errors:
        print(f"FAIL: {count} case(s), {errors} error(s).", file=sys.stderr)
        return 1
    if not args.quiet and not args.json_summary:
        print(f"PASS: {count} case(s); format checks only. Factual support and privacy still require review.")
    if args.summary or args.json_summary:
        print(("" if args.json_summary else "SUMMARY: ") + json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
