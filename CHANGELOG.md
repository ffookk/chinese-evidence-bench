# Changelog

## 0.3.1-alpha.1 (release preparation)

- Include eleven review controls added since the previous tag: filter reset, page size, case order, evidence/review/judgment/draft filters, matching-case navigation, Unicode response counts, selected-case restore, and comparison swapping.
- Repair JSONL Unicode and physical-line handling, URL controls, lone surrogates, legacy numeric and bracketed source addresses, and cross-tab deleted-run or failed-selection recovery. Preserve unsaved drafts when a reload operation fails.
- Repair shared privacy and English inspection gaps in encoded or duplicate JSON members, JSONL separators, linked parent paths, nonregular files, and historical JSON content.
- Keep strict server origin checks while using a same-origin fetch referrer policy, allowing Firefox to send its actual local origin instead of a null origin on POST requests. No cross-origin requests are enabled.
- Add portable Chromium and Firefox regressions using fictional local sessions and pinned development dependencies. Expand CI to Ubuntu Python 3.10–3.14 and macOS Python 3.14 with Node.js 24; the required `validate` check succeeds only when all unit and browser jobs succeed.

This section describes implemented changes prepared for a prerelease. It does not assert that a GitHub Release has already been published. Existing evaluation and privacy limitations remain unchanged.

## 0.3.0-alpha.1

- Add a complete local browser workbench backed by the existing Python run validator, scorer and comparison engine: create/import runs, search/filter cases, inspect reference evidence, edit prompts/responses/judgments, preview metrics, explicitly save revisions in memory, and export authoritative artifacts.
- Display paired quality and coverage denominators, excluded pairs, strata, setup and applicability-label changes, and private per-case transitions. Preserve raw parameter JSON types through imports, unrelated edits and downloads.
- Constrain the server to ephemeral numeric loopback with exact origin/host checks, session capabilities, fixed CSP hashes, no request logs or automatic persistence, bounded content and revision-conflict handling. Browser downloads use browser-controlled locations and permissions.
- Include the HTML, JavaScript and CSS assets in package builds and add the installed `evidence-bench` command. Existing case/run schemas and validation defaults are unchanged.

This remains an offline supplied-judgment tool. It does not call models, automatically verify truth, authenticate declarations, certify human review, or establish measured model improvement.

## 0.2.0-alpha.1

- Add private offline run preparation and deterministic scoring of supplied responses and manual or declared assisted judgments. Strict schemas retain declared generation/review metadata and prompt overrides, bind complete records to dataset/case hashes, and separate unknown judgments from incorrect ones.
- Add paired comparison of two verified scored runs on the same cases, with explicit quality and coverage denominators, improved/regressed/unchanged eligible pairs, fixed answerability/synthetic strata, setup-change indicators, and per-case transitions.
- Save local artifacts with exclusive POSIX publication, mode `0600`, protected directory traversal, and no replacement of existing files. Default artifact directories remain ignored by Git; artifacts can contain sensitive supplied data.

This alpha provides reproducible scoring and descriptive comparison. It does not call models, authenticate declared provenance, verify factual truth automatically, establish human certification, or publish measured model performance. Existing case schema v1 and validation defaults remain unchanged. See the [offline evaluation guide](docs/offline-evaluation.md) for schemas, scoring rules, privacy boundaries, and sample limitations.
