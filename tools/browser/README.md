# Portable browser regression checks

These development checks exercise the real local workbench with fictional data. Normal CLI and browser use still require only Python's standard library and a browser; Playwright and Node.js are test-only tools.

Use Python 3.10+ and Node.js 24 or newer. From the repository root:

```sh
python3 -m unittest discover -s tests -v
cd tools/browser
npm ci --ignore-scripts --no-audit --no-fund
npx --no-install playwright install chromium firefox
cd ../..
python3 tools/browser/run.py
```

On a supported Linux development machine, the Playwright browser installation may also need `--with-deps` to install system libraries. Dependency and browser installation downloads files; the regression scenarios themselves allow only their ephemeral numeric loopback origin and reject external page requests. The runner fails if Node, a requested browser or a required scenario is unavailable; it does not silently skip coverage. To run one installed engine, use `python3 tools/browser/run.py --browser firefox` or `--browser chromium`.

The package lock pins Playwright 1.63.0 and its development dependency. The fixture generator derives 63 explicitly fictional cases from the tracked synthetic examples and removes its temporary JSON input after validation. Each scenario starts a fresh in-memory server with two declared fictional runs. It never reads user datasets or an existing workbench session.

Each engine checks:

- Eleven review controls, including filtering, paging, ordering, case navigation, Unicode response counts, selective draft restoration and comparison swapping.
- Editing and explicitly saving a draft, then downloading and reimporting a scored artifact through the authoritative Python validator. Raw large-integer and float metadata are retained in downloaded bytes.
- Reload after another tab removes the selected run, correct remaining-run export, and the empty state after final removal.
- Failed run selection restoring the displayed identity, and an interrupted Reload preserving unsaved metadata before a successful retry.
- Mobile viewport overflow, empty browser storage, and absence of external page requests or JavaScript page errors.

Downloads use the browser's temporary test context and are removed when it closes. No screenshots, traces, videos or downloadable test artifacts are produced for CI upload. Diagnostics use fixed scenario names, numeric checkpoints and fixed error/reason codes rather than supplied values or local paths. Checkpoint comments in `checks.cjs` identify the failed stage; raw browser exceptions and child stderr are not printed. Timeout reasons classify only fixed Playwright actionability phrases; they do not reproduce the element description or supplied text. A failed scenario is a test failure; it is not evidence of a real-data leak. These bounded checks do not establish source truth, independent human review, Windows support, or coverage of every browser or privacy risk.

## Continuous integration

The unit-test matrix runs Ubuntu with Python 3.10, 3.11, 3.12, 3.13 and 3.14, plus macOS with Python 3.14. Every entry explicitly installs Node.js 24 and fails if any Python test is skipped. A separate Ubuntu/Python 3.11/Node.js 24 matrix runs the same scenarios in Playwright's Chromium and Firefox builds. These are POSIX targets; Windows is not in this matrix.

The always-running `validate` job requires both matrix jobs to report success, retaining the existing required-check name. CI also preserves the current tracked English guard, privacy scan including reachable history, documented dataset checks and reviewed-real-case gate. Coverage is defined by this workflow; a change is verified on those CI targets only after its corresponding run succeeds.
