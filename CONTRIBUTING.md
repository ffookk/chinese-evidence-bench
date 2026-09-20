# Contributing

## Make a clear, focused change

1. Choose one independent task from [ROADMAP.md](ROADMAP.md) and describe its expected result.
2. Make changes on a new branch and use a clear commit message.
3. Open a pull request describing the purpose, sources, validation, and limitations.

Use English for public documentation, fixtures, comments, issues, discussions, PRs, commit messages, and release notes. Preserve identifiers, source URLs, and technical notation. Published English fixtures do not count as Chinese-language evaluation coverage.

## Evidence and data

- Prefer official documents, original data, or original research for factual records. Retain precise evidence locations and review dates.
- Distinguish source statements, author inferences, unverified information, and experimental results.
- State the applicable date for time-sensitive material and retain necessary correction notes when updating it.
- Do not treat conversation transcripts or AI answers as proof that facts have been verified.
- Check licensing and redistribution conditions before importing external material. Prefer links and the minimum necessary excerpts.

## Privacy and validation

- Use fictional or lawfully public examples. Do not submit API keys, credentials, real household contact details, or private conversations.
- Data changes should be traceable and reviewable. Code changes should include suitable usage instructions and validation results.
- When adding public facts, update `docs/source-review.md` with the corresponding case IDs and source URLs so that the existing data tests can check the review trail.
- Clearly identify work that has not been implemented or verified; do not present plans as completed results.

## Automated checks

Before submitting, read the [privacy notes](docs/privacy.md), run the validation commands in the README, and run `python3 scripts/privacy_check.py --history`. The PR Checks workflow runs the privacy check, unit tests, synthetic and public-case validation, and the real, reviewed-case gate.

`main` requires a pull request and a passing `validate` check, including for administrators. Commit on a working branch; force pushes and deletion of the main branch are prohibited. Automated checks do not replace review of facts, privacy, or practical results.

Run `python3 scripts/check_english.py` after staging changes. CI checks current tracked text, including decoded JSON values, for CJK scripts. This guard is not a general language classifier; manually review all public wording and GitHub collaboration text for English. Historical revisions are outside this check.
