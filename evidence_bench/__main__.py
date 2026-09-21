"""Run with: python3 -m evidence_bench validate examples/synthetic.jsonl"""

import argparse
from datetime import date
import json
import io
from pathlib import Path
import sys
from urllib.parse import urlsplit

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


def read_cases(path, max_bytes=None):
    """Yield (position, case, error); JSONL errors do not hide later records."""
    try:
        if path == Path("-"):
            if sys.stdin is None:
                raise OSError
            data = getattr(sys.stdin, "buffer", sys.stdin).read(-1 if max_bytes is None else max_bytes + 1)
            data = data.encode("utf-8") if isinstance(data, str) else data
            if max_bytes is not None and len(data) > max_bytes:
                yield "file", None, "input exceeds the byte limit"
                return
            stream = io.StringIO(data.decode("utf-8"))
        elif max_bytes is not None:
            with path.open("rb") as source:
                data = source.read(max_bytes + 1)
            if len(data) > max_bytes:
                yield "file", None, "input exceeds the byte limit"
                return
            stream = io.StringIO(data.decode("utf-8"))
        else:
            stream = path.open(encoding="utf-8")
        with stream:
            if path == Path("-") or path.suffix.lower() == ".jsonl":
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
    except (OSError, UnicodeError, ValueError):
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
    validate.add_argument("--max-review-age", type=_count, help="maximum review age in days relative to --as-of")
    validate.add_argument("--source-host", action="append", default=[], help="allowed source hostname; repeat to allow more hosts")
    validate.add_argument("--min-source-hosts", type=_count, help="minimum distinct evidence hostnames per case")
    validate.add_argument("--id-prefix", help="require every case identifier to start with this prefix")
    validate.add_argument("--sorted-ids", action="store_true", help="require ascending identifiers across all inputs")
    validate.add_argument("--unique-questions", action="store_true", help="reject repeated normalized question wording")
    validate.add_argument("--max-input-bytes", type=_count, help="maximum bytes read from each input")
    args = parser.parse_args(argv)
    if args.summary and args.json_summary:
        parser.error("choose one summary format")
    if args.paths.count(Path("-")) > 1:
        parser.error("standard input may be supplied only once")
    seen = set()
    errors = 0
    count = 0
    summary = {
        "real": 0, "synthetic": 0,
        "reviewed": 0, "pending": 0,
        "supported": 0, "insufficient_evidence": 0, "needs_clarification": 0,
    }
    previous_identifier = None
    seen_questions = set()
    for file_index, path in enumerate(args.paths, 1):
        if path != Path("-") and path.suffix.lower() not in {".json", ".jsonl"}:
            print(f"input {file_index}: expected a .json or .jsonl extension", file=sys.stderr)
            errors += 1
            continue
        records = 0
        for position, case, error in read_cases(path, args.max_input_bytes):
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
            if args.max_review_age is not None and not problems and (case["verified_at"] is None or (args.as_of - date.fromisoformat(case["verified_at"])).days > args.max_review_age):
                problems.append("verified_at: absent or older than the allowed review age")
            if args.source_host and not problems and any(urlsplit(source["source_url"]).hostname not in {host.lower() for host in args.source_host} for source in case["evidence"]):
                problems.append("evidence: source host is outside the allowed set")
            if args.min_source_hosts is not None and not problems and len({urlsplit(source["source_url"]).hostname for source in case["evidence"]}) < args.min_source_hosts:
                problems.append("evidence: fewer than the required distinct source hosts")
            if args.id_prefix is not None and not problems and not case["id"].startswith(args.id_prefix):
                problems.append("id: does not use the required prefix")
            if args.sorted_ids and not problems:
                if previous_identifier is not None and case["id"] < previous_identifier:
                    problems.append("id: identifiers are not in ascending order")
                previous_identifier = case["id"]
            if args.unique_questions and not problems:
                wording = " ".join(case["question"].split()).casefold()
                if wording in seen_questions:
                    problems.append("question: repeated normalized wording")
                seen_questions.add(wording)
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
