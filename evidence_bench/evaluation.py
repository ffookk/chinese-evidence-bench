"""Offline scoring of supplied responses and judgments; no model or network calls."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import secrets
import unicodedata

from .validator import validate_case

SCHEMA_VERSION = 1
SCORING_POLICY = "manual_binary_v1"
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
MAX_CASES = 10000
AXES = ("factual", "citation", "refusal_decision")
JUDGMENTS = ("correct", "incorrect", "unscored", "not_applicable")
OUTCOMES = ("answered", "refused", "clarification_requested", "missing")
RUN_FIELDS = {"schema_version", "run_id", "created_at", "validation_as_of", "dataset_sha256", "generation", "review", "records"}
RECORD_FIELDS = {"case_id", "case_sha256", "prompt_override", "outcome", "response_text", "judgments"}
ARTIFACT_FIELDS = {"schema_version", "artifact_type", "scoring_policy", "dataset_sha256", "run_sha256", "run", "case_manifest", "metrics", "limitations"}
LIMITATIONS = [
    "Scores summarize supplied judgments; factual truth and source support are not automatically verified.",
    "Model, generation, reviewer, and timestamp metadata are declarations, not authenticated provenance.",
    "Unscored and not-applicable judgments are excluded from score denominators and reported separately.",
    "Coverage counts observed response labels, not answer quality; small or synthetic samples do not support model rankings.",
    "Content hashes identify the supplied data and records; they are not signatures or proof of authenticity.",
]


class EvaluationError(Exception):
    """A fixed, value-free diagnostic suitable for display."""


@dataclass(frozen=True)
class Dataset:
    cases: tuple
    sha256: str
    validation_as_of: str


def _keys(value, required, context):
    if not isinstance(value, dict) or set(value) != set(required):
        raise EvaluationError(context + ": missing or unexpected fields.")


def _version(value, context):
    if type(value) is not int or value != SCHEMA_VERSION:
        raise EvaluationError(context + ": unsupported schema version.")


def _text(value, context, *, allow_empty=False, limit=1000000, multiline=True):
    if not isinstance(value, str) or len(value) > limit or (not allow_empty and not value.strip()):
        raise EvaluationError(context + ": invalid text.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise EvaluationError(context + ": invalid Unicode text.") from exc
    allowed = "\n\r\t" if multiline else ""
    if any(unicodedata.category(character) == "Cc" and character not in allowed for character in value):
        raise EvaluationError(context + ": unsupported control characters.")
    return value


def _date(value, context):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except ValueError as exc:
        raise EvaluationError(context + ": expected a valid YYYY-MM-DD date.") from exc


def _timestamp(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
            raise ValueError
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.isoformat(timespec="seconds").replace("+00:00", "Z") != value:
            raise ValueError
    except ValueError as exc:
        raise EvaluationError("run created_at: expected a UTC timestamp with seconds and Z.") from exc


def _finite_parameters(value):
    if not isinstance(value, dict):
        raise EvaluationError("generation parameters: expected a JSON object.")
    pending = [(value, 0)]
    visited = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if depth > 12 or visited > 10000:
            raise EvaluationError("generation parameters: structure exceeds supported limits.")
        if isinstance(item, dict):
            for key, child in item.items():
                _text(key, "parameter key", limit=200, multiline=False)
                pending.append((child, depth + 1))
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, str):
            _text(item, "parameter value", allow_empty=True)
        elif type(item) is float:
            if not math.isfinite(item):
                raise EvaluationError("generation parameters: numbers must be finite.")
        elif item is not None and type(item) not in (int, bool):
            raise EvaluationError("generation parameters: unsupported JSON value.")


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise EvaluationError("Data cannot be represented as strict UTF-8 JSON.") from exc


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _hash(value, context):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise EvaluationError(context + ": expected a lowercase SHA-256 fingerprint.")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("nonfinite number")


def _number(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("nonfinite number")
    return parsed


def decode_json(text, context):
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_number)
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 32:
                raise ValueError("JSON nesting limit exceeded")
            children = item.values() if isinstance(item, dict) else item if isinstance(item, list) else ()
            pending.extend((child, depth + 1) for child in children)
        return value
    except (ValueError, RecursionError) as exc:
        raise EvaluationError(context + ": invalid strict JSON.") from exc


def _read_text(path, context, max_bytes=MAX_INPUT_BYTES):
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise EvaluationError(context + ": input exceeds the byte limit.")
        return data.decode("utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        raise EvaluationError(context + ": unable to read UTF-8 input.") from exc


def read_json(path, context="run input", max_bytes=MAX_INPUT_BYTES):
    return decode_json(_read_text(path, context, max_bytes), context)


def load_dataset(paths, validation_as_of):
    ceiling = _date(validation_as_of, "dataset validation date")
    cases = {}
    for input_index, raw_path in enumerate(paths, 1):
        context = f"dataset input {input_index}"
        path = Path(raw_path)
        text = _read_text(path, context)
        if path.suffix.lower() == ".jsonl":
            records = [decode_json(line, context + f", line {number}") for number, line in enumerate(text.splitlines(), 1) if line.strip()]
        elif path.suffix.lower() == ".json":
            records = decode_json(text, context)
            if not isinstance(records, list):
                raise EvaluationError(context + ": expected a case array.")
        else:
            raise EvaluationError(context + ": expected a .json or .jsonl file.")
        if not records:
            raise EvaluationError(context + ": no case records.")
        for index, case in enumerate(records, 1):
            if validate_case(case, today=ceiling):
                raise EvaluationError(context + f", case {index}: invalid case schema or state.")
            if case["id"] in cases:
                raise EvaluationError("dataset: duplicate case identifier.")
            canonical(case)
            cases[case["id"]] = case
            if len(cases) > MAX_CASES:
                raise EvaluationError("dataset: case limit exceeded.")
    if not cases:
        raise EvaluationError("dataset: no case records.")
    ordered = tuple(cases[key] for key in sorted(cases))
    return Dataset(ordered, fingerprint({"dataset_schema": 1, "cases": ordered}), ceiling.isoformat())


def prepare_run(dataset, *, run_id="draft", model_label="unspecified", created_at=None):
    run = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if created_at is None else created_at,
        "validation_as_of": dataset.validation_as_of,
        "dataset_sha256": dataset.sha256,
        "generation": {"model_label": model_label, "parameters": {}},
        "review": {"method": "unspecified", "reviewer_label": "unspecified"},
        "records": [{
            "case_id": case["id"], "case_sha256": fingerprint(case), "prompt_override": None,
            "outcome": "missing", "response_text": "", "judgments": {axis: "unscored" for axis in AXES},
        } for case in dataset.cases],
    }
    return normalize_run(dataset, run)


def normalize_run(dataset, run):
    _keys(run, RUN_FIELDS, "run")
    _version(run["schema_version"], "run")
    if not isinstance(run["run_id"], str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", run["run_id"]):
        raise EvaluationError("run identifier: invalid format.")
    _timestamp(run["created_at"])
    _date(run["validation_as_of"], "run validation date")
    if run["validation_as_of"] != dataset.validation_as_of:
        raise EvaluationError("run: validation date does not match the dataset context.")
    _hash(run["dataset_sha256"], "run dataset fingerprint")
    if run["dataset_sha256"] != dataset.sha256:
        raise EvaluationError("run: dataset fingerprint mismatch.")
    _keys(run["generation"], {"model_label", "parameters"}, "generation metadata")
    _text(run["generation"]["model_label"], "model label", limit=200, multiline=False)
    _finite_parameters(run["generation"]["parameters"])
    _keys(run["review"], {"method", "reviewer_label"}, "review metadata")
    method = run["review"]["method"]
    if not isinstance(method, str) or method not in {"manual", "ai_assisted", "synthetic", "unspecified"}:
        raise EvaluationError("review metadata: unsupported method.")
    _text(run["review"]["reviewer_label"], "reviewer label", limit=200, multiline=False)
    if not isinstance(run["records"], list) or len(run["records"]) > MAX_CASES:
        raise EvaluationError("run records: expected a bounded array.")
    expected = {case["id"]: fingerprint(case) for case in dataset.cases}
    records = {}
    for index, record in enumerate(run["records"], 1):
        context = f"run record {index}"
        _keys(record, RECORD_FIELDS, context)
        identifier = _text(record["case_id"], context + " identifier", limit=64, multiline=False)
        if identifier not in expected:
            raise EvaluationError(context + ": case is not in the dataset.")
        if identifier in records:
            raise EvaluationError("run: duplicate case record.")
        _hash(record["case_sha256"], context + " fingerprint")
        if record["case_sha256"] != expected[identifier]:
            raise EvaluationError(context + ": case fingerprint mismatch.")
        if record["prompt_override"] is not None:
            _text(record["prompt_override"], context + " prompt override")
        outcome = record["outcome"]
        if not isinstance(outcome, str) or outcome not in OUTCOMES:
            raise EvaluationError(context + ": unsupported response outcome.")
        _text(record["response_text"], context + " response", allow_empty=outcome == "missing")
        _keys(record["judgments"], AXES, context + " judgments")
        for axis in AXES:
            judgment = record["judgments"][axis]
            if not isinstance(judgment, str) or judgment not in JUDGMENTS:
                raise EvaluationError(context + ": unsupported judgment state.")
        if outcome == "missing":
            if record["response_text"] != "" or any(record["judgments"][axis] != "unscored" for axis in AXES):
                raise EvaluationError(context + ": missing responses require empty text and unscored judgments.")
        else:
            if record["judgments"]["refusal_decision"] == "not_applicable":
                raise EvaluationError(context + ": observed responses need a scored or unscored refusal decision.")
            if outcome != "answered" and any(record["judgments"][axis] != "not_applicable" for axis in ("factual", "citation")):
                raise EvaluationError(context + ": non-answer content judgments must be not applicable.")
        records[identifier] = record
    if set(records) != set(expected):
        raise EvaluationError("run: missing case records; represent absent responses explicitly.")
    normalized = dict(run)
    normalized["records"] = [records[key] for key in sorted(records)]
    return json.loads(canonical(normalized))


def ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator, "rate": round(numerator / denominator, 6) if denominator else None}


def metrics_for(records):
    metrics = {"sample_size": len(records), "outcome_counts": {outcome: 0 for outcome in OUTCOMES}}
    for record in records:
        metrics["outcome_counts"][record["outcome"]] += 1
    metrics["answer_coverage"] = ratio(metrics["outcome_counts"]["answered"], len(records))
    metrics["response_coverage"] = ratio(len(records) - metrics["outcome_counts"]["missing"], len(records))
    for axis in AXES:
        counts = {judgment: 0 for judgment in JUDGMENTS}
        for record in records:
            counts[record["judgments"][axis]] += 1
        scored = counts["correct"] + counts["incorrect"]
        metrics[axis] = {
            "counts": counts,
            "score": ratio(counts["correct"], scored),
            "judgment_coverage": ratio(scored, len(records) - counts["not_applicable"]),
        }
    return metrics


def score_run(dataset, run):
    normalized = normalize_run(dataset, run)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "scored_run",
        "scoring_policy": SCORING_POLICY,
        "dataset_sha256": dataset.sha256,
        "run_sha256": fingerprint(normalized),
        "run": normalized,
        "case_manifest": [{"case_id": case["id"], "case_sha256": fingerprint(case), "synthetic": case["synthetic"], "answerability": case["answerability"]} for case in dataset.cases],
        "metrics": metrics_for(normalized["records"]),
        "limitations": list(LIMITATIONS),
    }


def verify_scored(dataset, artifact):
    _keys(artifact, ARTIFACT_FIELDS, "scored artifact")
    _version(artifact["schema_version"], "scored artifact")
    expected = score_run(dataset, artifact["run"])
    if canonical(artifact) != canonical(expected):
        raise EvaluationError("scored artifact: stored identity, policy, manifest, or metrics do not match recomputation.")
    return expected


def _output_directory(parent):
    """Hold each directory while opening its child without following symlinks."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise OSError("private output requires POSIX directory operations")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open("/" if parent.is_absolute() else ".", flags)
    try:
        parts = parent.parts[1:] if parent.is_absolute() else parent.parts
        for part in parts:
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def write_private_json(path, value):
    """Publish a complete 0600 file without replacing content or following aliases."""
    directory = None
    temporary = None
    try:
        target = Path(path)
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n"
        if len(payload) > MAX_ARTIFACT_BYTES:
            raise EvaluationError("output: artifact exceeds the byte limit.")
        directory = _output_directory(target.parent)
        candidate = ".evidence-bench-" + secrets.token_hex(16) + ".tmp"
        descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        temporary = candidate
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            if descriptor is not None:
                os.close(descriptor)
        os.link(temporary, target.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError, NotImplementedError) as exc:
        raise EvaluationError("output: unable to save a private file without replacing existing content.") from exc
    finally:
        if directory is not None:
            try:
                if temporary is not None:
                    os.unlink(temporary, dir_fd=directory)
            except OSError:
                pass
            finally:
                os.close(directory)


def add_commands(subparsers, as_of_type):
    prepare = subparsers.add_parser("prepare-run", help="create a private, unscored offline run template")
    prepare.add_argument("--dataset", action="append", type=Path, required=True)
    prepare.add_argument("--as-of", type=as_of_type, default=date.today())
    prepare.add_argument("--run-id", default="draft")
    prepare.add_argument("--model-label", default="unspecified")
    prepare.add_argument("--created-at", help="declared UTC capture timestamp, YYYY-MM-DDTHH:MM:SSZ")
    prepare.add_argument("--output", type=Path, default=Path("private-input/run.json"))
    score = subparsers.add_parser("score-run", help="score supplied local responses and judgments without model calls")
    score.add_argument("--dataset", action="append", type=Path, required=True)
    score.add_argument("--run", type=Path, required=True)
    score.add_argument("--output", type=Path, default=Path("private-output/scored-run.json"))


def run_command(args):
    try:
        if args.command == "prepare-run":
            dataset = load_dataset(args.dataset, args.as_of.isoformat())
            run = prepare_run(dataset, run_id=args.run_id, model_label=args.model_label, created_at=args.created_at)
            write_private_json(args.output, run)
            print(f"PASS: {len(dataset.cases)} case(s); private unscored run template saved. No model was called.")
        elif args.command == "score-run":
            run = read_json(args.run)
            _keys(run, RUN_FIELDS, "run")
            dataset = load_dataset(args.dataset, run["validation_as_of"])
            artifact = score_run(dataset, run)
            write_private_json(args.output, artifact)
            print(f"PASS: {len(dataset.cases)} case(s); private scored run saved. Supplied judgments are not independently verified.")
        else:
            raise EvaluationError("unsupported evaluation command.")
        return 0
    except EvaluationError as exc:
        print("Evaluation failed: " + str(exc), file=sys.stderr)
        return 1
