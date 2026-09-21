"""Standard-library-only validation; never retrieves sources or calls models."""

from datetime import date
import ipaddress
import re
from urllib.parse import urlsplit


CASE_FIELDS = {
    "schema_version", "id", "synthetic", "question", "reference_answer",
    "evidence", "time_sensitive", "valid_as_of", "verified_at",
    "answerability", "review_status",
}
EVIDENCE_FIELDS = {"source_url", "source_title", "evidence_locator"}
ANSWERABILITY = {"supported", "insufficient_evidence", "needs_clarification"}
LOCATOR_TYPES = {"paragraph", "page", "section", "table", "timestamp"}
ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]{2,63}\Z")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def nonempty(value):
    return (isinstance(value, str) and bool(value.strip())
            and not any(0xD800 <= ord(char) <= 0xDFFF for char in value))


def _fields(value, expected, path, errors):
    if not isinstance(value, dict):
        errors.append(f"{path}: must be an object")
        return False
    missing = expected - value.keys()
    if missing:
        errors.append(f"{path}: missing required fields: {', '.join(sorted(missing))}")
    if value.keys() - expected:
        errors.append(f"{path}: unknown fields are not allowed")
    return True


def _date(value, field, today, errors):
    if value is None:
        return None
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        errors.append(f"{field}: expected YYYY-MM-DD or null")
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        errors.append(f"{field}: invalid calendar date")
        return None
    if parsed > today:
        errors.append(f"{field}: future dates are not allowed")
    return parsed


def _source_url(value, synthetic):
    if not nonempty(value) or "\\" in value or any(char.isspace() or ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    if (parsed.scheme != "https" or not hostname or "[" in parsed.netloc or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or port not in (None, 443)):
        return False
    labels = hostname.split(".")
    if len(hostname) > 253 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        return False
    # Synthetic evidence must never point at an actual person's or site's record.
    if synthetic is True:
        return hostname.endswith(".invalid")
    reserved = {"example.com", "example.org", "example.net", "localhost", "invalid", "local", "test", "example"}
    if "." not in hostname or any(hostname == domain or hostname.endswith("." + domain) for domain in reserved):
        return False
    if all(re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", label, re.IGNORECASE) for label in labels):
        return False
    try:
        ipaddress.ip_address(hostname)
        return False
    except ValueError:
        return bool(re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", hostname))


def validate_case(case, *, today=None):
    """Return structural errors without echoing field values or source content."""
    today = date.today() if today is None else today
    errors = []
    if not _fields(case, CASE_FIELDS, "case", errors):
        return errors
    if type(case.get("schema_version")) is not int or case.get("schema_version") != 1:
        errors.append("schema_version: must be integer 1")
    identifier = case.get("id")
    if not isinstance(identifier, str) or not ID_PATTERN.fullmatch(identifier):
        errors.append("id: use 3-64 lowercase ASCII letters, digits, underscores or hyphens; start with a letter")
    for field in ("synthetic", "time_sensitive"):
        if type(case.get(field)) is not bool:
            errors.append(f"{field}: must be boolean")
    if not nonempty(case.get("question")):
        errors.append("question: must be a nonempty string")
    answerability = case.get("answerability")
    if not isinstance(answerability, str) or answerability not in ANSWERABILITY:
        errors.append("answerability: invalid status")
    review = case.get("review_status")
    if not isinstance(review, str) or review not in {"pending", "reviewed"}:
        errors.append("review_status: invalid status")
    reference = case.get("reference_answer")
    if answerability == "supported":
        if not nonempty(reference):
            errors.append("reference_answer: supported cases require a nonempty answer")
    elif reference is not None:
        errors.append("reference_answer: must be null unless answerability is supported")

    verified = _date(case.get("verified_at"), "verified_at", today, errors)
    valid = _date(case.get("valid_as_of"), "valid_as_of", today, errors)
    if review == "pending" and case.get("verified_at") is not None:
        errors.append("verified_at: pending cases must use null")
    if review == "reviewed" and case.get("verified_at") is None:
        errors.append("verified_at: reviewed cases require a date")
    if case.get("time_sensitive") is True and case.get("valid_as_of") is None:
        errors.append("valid_as_of: time-sensitive cases require a date")
    if case.get("time_sensitive") is False and case.get("valid_as_of") is not None:
        errors.append("valid_as_of: use null for cases that are not time-sensitive")
    if verified and valid and verified < valid:
        errors.append("verified_at: cannot precede valid_as_of")

    evidence = case.get("evidence")
    if not isinstance(evidence, list):
        errors.append("evidence: must be an array")
        return errors
    if answerability == "supported" and not evidence:
        errors.append("evidence: supported cases require at least one source")
    for index, source in enumerate(evidence, 1):
        path = f"evidence[{index}]"
        if not _fields(source, EVIDENCE_FIELDS, path, errors):
            continue
        if not nonempty(source.get("source_title")):
            errors.append(f"{path}.source_title: must be a nonempty string")
        if not _source_url(source.get("source_url"), case.get("synthetic")):
            errors.append(f"{path}.source_url: invalid source URL; see the data specification")
        locator = source.get("evidence_locator")
        if not _fields(locator, {"type", "value"}, f"{path}.evidence_locator", errors):
            continue
        kind = locator.get("type")
        if not isinstance(kind, str) or kind not in LOCATOR_TYPES:
            errors.append(f"{path}.evidence_locator.type: invalid locator type")
        if not nonempty(locator.get("value")):
            errors.append(f"{path}.evidence_locator.value: must be a nonempty string")
    return errors
