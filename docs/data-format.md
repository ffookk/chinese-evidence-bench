# Case data format v1

This specification defines the current validator's rules. The validator uses only the Python 3.10+ standard library, with no additional dependencies or network access.

## Files and fields

Inputs use UTF-8. A `.json` file must contain a top-level array of cases; each nonempty line in a `.jsonl` file must contain one case object. Blank JSONL lines are allowed. Every input file must contain at least one readable case. Duplicate JSON keys, `NaN`, `Infinity`, and unknown fields are errors. IDs are checked for uniqueness across all files passed to one command.

JSONL physical lines may end with LF, CRLF, or CR. Unicode text separators inside JSON strings remain part of the field value. These rules are identical for file input, standard input, byte-limited validation, and evaluation.

Every case must include all fields below. Nullable fields must explicitly use `null`; they cannot be omitted.

| Field | Format and meaning |
| --- | --- |
| `schema_version` | Integer `1` |
| `id` | 3–64 lowercase ASCII letters, digits, `_`, or `-`, starting with a letter; do not use identity, account, or contact details |
| `synthetic` | Boolean; fictional cases must use `true` and cannot count as real benchmark data |
| `question` | Nonempty string; published fixtures use English, and the program does not detect natural language |
| `reference_answer` | Nonempty answer for `supported`; must be `null` for other states |
| `evidence` | Array of source objects; at least one for `supported`, otherwise optionally empty |
| `time_sensitive` | Boolean indicating whether the answer depends on time |
| `valid_as_of` | Required `YYYY-MM-DD` for time-sensitive cases; otherwise `null` |
| `verified_at` | Required date of the most recent evidence review for `reviewed`; must be `null` for `pending`; the batch notes disclose the review method and scope |
| `answerability` | `supported` / `insufficient_evidence` / `needs_clarification` |
| `review_status` | `pending` / `reviewed` |

`answerability` and `review_status` are independent. `supported` + `pending` means the author has proposed a sourced candidate answer awaiting review. `reviewed` + `insufficient_evidence` means the review concluded that evidence is insufficient; it does not establish an answer. Empty evidence arrays are structurally valid for insufficient-evidence or unclear questions, but the reasoning and search scope still require human review.

`reviewed` means the source-support review disclosed in the batch notes was completed. The label alone does not establish that a human performed it. Each real-data batch must state whether a human or AI agent checked it, the date, evidence locations, and scope limitations. Do not claim human certification without independent human review. See the [initial source review](source-review.md). This clarifies the documentation's review terminology; the JSON v1 fields and validation logic are unchanged.

Each source object must contain exactly these fields:

| Field | Format and meaning |
| --- | --- |
| `source_url` | HTTPS URL without user information, query parameters, fragments, backslashes, whitespace, raw control characters, or a port other than 443. Put anchor information in the locator field. Hostnames use valid ASCII labels; internationalized names require Punycode. Synthetic cases may use only subdomains of `.invalid`. Real cases require dotted hostnames and reject IP addresses, `localhost`, `.local`, `.invalid`, `.test`, `.example`, and `example.com` / `example.org` / `example.net`, including their subdomains |
| `source_title` | Nonempty source title |
| `evidence_locator` | Object containing exactly `type` and `value` |

`evidence_locator.type` is `paragraph`, `page`, `section`, `table`, or `timestamp`. Its `value` is a nonempty string, such as `Section 2, paragraph 3`. The validator checks only that a locator exists. Open the source to assess whether the location is usable, precise, and supports the answer, then disclose the review method in the batch notes. Source URLs must not contain access credentials, tracking parameters, or personal information. Convert parameterized source links to stable, publicly shareable URLs first.

The real-source IP exclusion also rejects numeric-only hostnames, including shortened IPv4 and hexadecimal or octal spellings. Numeric labels within an ordinary domain remain allowed. Bracketed address authorities, including IPvFuture forms, are not accepted as domain names for real or synthetic sources.

Dates must be strict ISO calendar dates, such as `2026-01-15`. Impossible dates, missing zero padding, timestamps, and future dates are rejected. The future-date cutoff defaults to the local current date; use `--as-of YYYY-MM-DD` for a fixed, reproducible cutoff. When both dates are present, `verified_at` cannot precede `valid_as_of`. This format describes previously reviewed facts, not future predictions.

## Type checks while editing

- Write `schema_version` as integer `1`; `1.0`, `true`, and string `"1"` are not substitutes.
- Use JSON booleans `true` / `false` for `synthetic` and `time_sensitive`, not `0` / `1` or strings.
- Required nonempty text cannot consist only of spaces, tabs, or newlines. The current check tests emptiness after stripping leading and trailing whitespace.
- Text must be representable as UTF-8; escaped lone surrogate values are rejected, while valid supplementary Unicode code points are preserved.
- Object-field order does not affect validation. Retaining every required field matters more than copying a particular order.
- Every source in an array is checked. One valid source does not cancel another source's format error in the same case.
- `insufficient_evidence` and `needs_clarification` may retain relevant sources, which must still satisfy every format constraint.
- `evidence_locator.value` must be a string, even for locator types `page` and `timestamp`.
- Case IDs are not automatically trimmed or converted to lowercase. Enter them in the required form.

## Validation, admission, and evaluation

```sh
python3 -m evidence_bench validate examples/synthetic.jsonl
python3 -m evidence_bench validate examples/synthetic.jsonl --as-of 2026-01-31
python3 -m unittest discover -s tests -v
```

Use `--real-only --require-reviewed` when admitting real cases to require real, reviewed records. `data/public-facts.jsonl` passes this gate. The fictional fixtures fail both flags as expected; this failure is not a tool defect.

```sh
python3 -m evidence_bench validate examples/synthetic.jsonl --real-only --require-reviewed
```

Exit codes: `0` means format checks passed, `1` means a data or input-file error, and `2` means a command-line argument error. Diagnostics use input-file indices and case or line numbers without echoing field values, file paths, or source contents.

Passing format checks does not establish factual accuracy, source availability, licensing compliance, or absence of personal information. `--real-only` checks only a label and cannot detect data incorrectly marked as real. The repository currently contains 8 agent-reviewed public-fact cases in English. Independent human review and a formal scoring process remain incomplete, and the published fixtures do not provide Chinese-language evaluation coverage. Complete the agreed independent review and scoring rules before model evaluation.
