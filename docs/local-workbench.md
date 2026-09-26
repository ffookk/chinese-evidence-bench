# Local browser evaluation workbench

The workbench is an in-memory interface to the existing Python run validator, scorer and paired comparison engine. It helps review locally supplied answers against a fixed startup dataset. It never calls a model, fetches evidence, automatically determines truth, or authenticates declared generation and review metadata. Existing English fixtures do not establish Chinese-language evaluation coverage.

## Start a session

From a source checkout, use Python 3.10+ and a modern browser:

```sh
python3 -m evidence_bench workbench \
  --dataset examples/synthetic.jsonl --as-of 2026-01-31
```

Repeat `--dataset` to include additional explicit JSON/JSONL case files. They must pass the existing strict case validator, have globally unique IDs, and fit the limits below. The terminal prints a numeric loopback address with an ephemeral port, followed by a short status. Open that address manually. There is no browser auto-launch, remote-bind option, fixed port, or URL capability. Press Ctrl-C in the terminal to stop the session.

The startup dataset is copied into memory and stays fixed for the session. The saved `--as-of` date is a validation cutoff, not an independent evidence verification. Imported runs must match that date and the complete dataset/case fingerprints. Start a new session to use changed cases or a different cutoff.

An optional package installation includes the workbench's HTML, CSS and JavaScript assets and the `evidence-bench` command. A locally built wheel can be installed without runtime dependencies:

```sh
python3 -m pip install --no-deps path/to/chinese_evidence_bench.whl
evidence-bench workbench --dataset examples/synthetic.jsonl --as-of 2026-01-31
```

Replace the placeholder wheel filename with the actual built wheel. Dataset paths always refer to explicit local inputs; repository fixtures are not installed as hidden default data. Building the package requires setuptools; running it needs only the Python standard library. The distribution version follows normalized Python packaging notation, while the CLI reports the project's `0.3.1-alpha.1` version label.

## Review a run

1. Choose **Create unscored run** or select a JSON file with **Import run or scored JSON**. Creation includes every case as missing/unscored. Import accepts a strict original run or an intact scored artifact; Python verifies all identities and recomputes stored metrics before accepting a scored artifact. Synthetic examples are demonstrations, not measured model results.
2. Search case IDs/questions or filter by answerability, synthetic/real label, and response outcome. The case list defaults to 20 items per page. Case details show the question, reference answer, source text and recorded review state. Evidence URLs are displayed as text and are never fetched.
3. Enter the declared outcome and complete supplied response. A null prompt override means the exact original case question; uncheck the default-prompt control to enter a complete alternate prompt. Enter factual, citation and refusal-decision judgments using the same scoring rules as the CLI.
4. Switching cases preserves the tab's draft edits. Editing the response, prompt or outcome resets judgments to unscored for review; factual/citation axes on refusals and clarification requests remain not applicable. Changing an observed response to missing asks before clearing its text and judgments in the draft.
5. Live metrics are calculated by Python after a short debounce. Invalid drafts show an error instead of old or misleading rates. A valid preview is marked **not saved** and does not change the saved run. Choose **Save changes to memory** to validate and save all changed records and metadata together.
6. Export the saved run or scored artifact explicitly to retain a file. Exports and comparisons are disabled while the tab has unsaved edits. **Discard draft** restores the last loaded saved state. **Reload selected run** loads the latest server revision, with a confirmation before discarding a draft.

The UI displays answer and response coverage, each quality score's numerator/denominator, judgment coverage, unknown/not-applicable counts, and declared outcomes. Empty quality denominators are undefined, not zero accuracy. The [offline evaluation guide](offline-evaluation.md) defines the authoritative schema, manual criteria, edge cases and reproducibility boundaries.

## Metadata and exact numeric types

The metadata panel permits explicit edits to run ID, UTC capture timestamp, model label, review method, reviewer label and raw generation-parameter JSON. These remain declarations, not verified provenance. The validation date and case identities are fixed by the startup dataset.

Generation parameters are carried as raw JSON text; browser code does not parse them into JavaScript numbers. Editing another field leaves the Python parameter object untouched. Explicit parameter changes are parsed strictly by Python. This preserves distinctions such as integer `1`, float `1.0`, negative zero, and integers outside JavaScript's exact numeric range. Run imports send the selected file's original decoded text; artifact exports download authoritative Python bytes without parsing and reserializing them in JavaScript.

## Compare saved runs

Select a baseline and candidate and choose **Compare paired judgments**. The comparison engine scores the saved runs, verifies them, and uses the same complete case set and validation context. The UI displays:

- Jointly scored quality denominators and improved/regressed/unchanged counts, separately from excluded pairs.
- Baseline and candidate aggregate score/coverage denominators and descriptive deltas.
- Left-only, right-only and neither-scored pair counts; response availability and outcome transitions.
- Answerability and synthetic/real strata, including empty groups with undefined rates.
- Declared setup changes, effective prompt changes, applicability-label transitions, and private case-level judgment transitions.

Changing a selection or editing a run clears the displayed comparison. Export computes the selected saved revisions again and downloads authoritative bytes. Unknown and not-applicable states are never converted to incorrect or unchanged quality. Matching datasets and positive deltas do not establish a controlled experiment, statistical significance, causality, independent human review, or general model rankings. Setup changes and denominator differences remain explicit.

## Multiple tabs and session lifetime

Every saved run has an integer revision. Save, preview, remove, export and comparison operations include the revision last observed by the tab. A stale, missing, null, boolean or incorrect revision is rejected; stale edits never overwrite another tab's saved changes. Reload deliberately to obtain current state. Comparison and export also reject stale revisions rather than silently changing the requested result.

If another tab removes the selected run, **Reload selected run** opens the first remaining saved run, or shows the empty state when none remain. If selecting or reloading a run fails, the selector returns to the run still displayed in the editor and unsaved drafts remain intact. A loaded run absent from the refreshed saved list is labeled unavailable in that list; an error never relabels the currently loaded data.

A draft exists only in its browser tab until an explicit save. A browser unload prompt helps protect unsaved edits but is subject to browser behavior. Reloading a tab discards its unsaved draft; saved server runs remain available while the process is running. Removing a run removes its saved server state, not any downloaded copies or another tab's already loaded data. Closing a tab does not stop the server. Stopping or restarting the process loses all unexported server runs.

## Network, storage and privacy boundaries

The server binds only `127.0.0.1` on an ephemeral port. API fetches use a same-origin referrer policy so Firefox retains the local request origin; the page response still sets `Referrer-Policy: no-referrer`. Requests remain constrained to the same local origin, and the server continues rejecting absent, null or foreign API origins. It never makes outbound network requests. The browser talks only to that same local origin; there are no model APIs, remote assets, source fetches, cookies, telemetry, service workers or browser storage. HTTP request logging is suppressed. Ordinary terminal output contains the loopback address and fixed status, never responses, file paths, dataset contents or the session capability.

The page receives a cryptographically random session capability, removes it from the DOM and retains it in page memory. The capability never enters a URL, fragment, cookie, localStorage or ordinary logs. Every JSON operation uses POST, exact numeric Host/Origin checks and that capability. Foreign or duplicate boundary headers, DNS aliases, cross-site fetch metadata, wildcard CORS, transfer encoding, unsupported methods, invalid content types and invalid lengths are rejected. Responses are not cached; CSP uses fixed script/style content hashes and rejects framing, external resources, forms and dynamic scripts. Imported text and evidence are rendered through text nodes, not HTML insertion.

The capability protects against unrelated web origins; it does **not** isolate local programs or another process running as the same account. A local program able to fetch the session page can obtain its capability. Use a trusted machine and browser, avoid extensions that can read local pages, and stop the server when finished. A capability is session access, not encrypted storage or proof of user identity.

No endpoint accepts a filesystem path or source URL. Only explicit startup datasets and packaged application assets are read by the server. Browser file imports require user selection and arrive as request text. Saved runs remain in process memory; no automatic file or log persistence occurs. Downloads contain supplied data and may be sensitive. **Browser exports use browser-controlled download locations and permissions; they do not inherit the CLI writer's `0600` guarantee or no-clobber policy.** Browser downloads and existing files may be synchronized by other software. Use the existing CLI private writer when those filesystem guarantees are required, and perform a separate privacy review before publication.

## Bounds and implementation scope

| Boundary | Limit |
| --- | --- |
| Startup dataset | Existing 10,000-case limit plus 8 MiB of canonical case JSON for this workbench |
| Runs in one session | 8 saved runs |
| Imported document / stored run | 8 MiB of raw document / canonical normalized run JSON |
| Total saved run content | 24 MiB of canonical run JSON |
| HTTP JSON request | 16 MiB plus 1 KiB for the raw-document envelope |
| Exported artifact | Existing 32 MiB output cap |
| Accepted connection timeout | 5 seconds per socket operation; one request at a time |

These are content limits, not a hard ceiling on process/browser RAM: parsing, copies, response encoding and the UI use additional memory. The server closes every HTTP connection after its response. Strict JSON rejects duplicate keys, nonfinite numbers, malformed UTF-8 and unsupported nesting. Existing run/schema parameter and text limits still apply. Fixed errors contain schema context and record positions but do not echo supplied field values.

`create_server(dataset)` supports programmatic local testing: it returns an unstarted bound server with `server_address` and `origin`. Call `serve_forever()` in a dedicated thread if needed, then `shutdown()` from another thread and `server_close()` to release it. The CLI serves in the foreground and closes the server on interruption. This is a single-user local alpha workbench, not a hosted service, multi-user authentication system, model runner or complete experiment-management platform.

## Small review controls

- **Reset case filters** clears the search and case filters and returns to the first page without changing any draft.
- **Cases per page** offers 10, 20 or 50 entries. Changing it returns to the first page and preserves drafts.
- **Case order** sorts the filtered list by case ID in either direction or by question text; this does not reorder exported records.
- **Recorded evidence** narrows the list to cases with or without evidence entries. Presence alone does not establish evidence quality.
- **Recorded review status** lists the statuses present in the startup dataset. These supplied labels are not independent certification.
- **Supplied judgments** shows cases with an unscored axis, an incorrect label, or no unscored axes. Not-applicable axes remain distinct from correct labels; filters include tab drafts.
- **Case draft state** shows only unsaved case edits or cases without local edits. Run-metadata edits do not make a case count as edited.
- **Previous case** and **Next case** follow the current filters and ordering, moving the list page when needed. If the selected case is outside the filters, Next case starts at the first match.
- The response character count updates while typing and switching cases. It counts Unicode code points, including spaces and line breaks, without modifying the response.
- **Restore this case** asks before discarding only the selected case's draft. Other case edits and metadata edits remain intact.
- **Swap baseline and candidate** exchanges the comparison selectors and clears any displayed comparison. Run comparison again explicitly to calculate the reversed direction.

### Pending preview layout

While authoritative draft validation is pending, the metrics region reserves its previous height so controls below it remain in place during pointer activation. This prevents a delayed preview from moving Reset case filters between mouse press and release. The reservation is a minimum, so content can expand, and is cleared when validated metrics are rendered. Errors remain visible, later edits can recover, and a new viewport can use its natural layout. This layout repair does not establish that every historical browser timeout has the same cause.
