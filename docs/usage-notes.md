# Input and diagnostic notes

- `validate` requires at least one file argument; omitting files is a command-line argument error.
- File extensions are case-insensitive; for example, `.JSONL` is still read as one case per line.
- Diagnostic labels `input 1` and `input 2` follow the command-line file order; preserve that order when investigating errors.
- A JSONL `line` refers to the physical input line number. Blank lines are skipped, but still count toward later line numbers.
- A syntax error on one JSONL line does not hide diagnostics on later lines; the overall validation still fails.
- A JSON array file is parsed as a whole. Any JSON syntax error prevents case validation for that file.
- Success summaries go to standard output; validation diagnostics and failure summaries go to standard error. Scripts should handle them separately.
- The `case(s)` count includes successfully parsed entries that may still have field errors; it is not a count of valid cases.
- The `error(s)` count measures individual problems. One case can contribute multiple errors by violating multiple rules.
- Save files as UTF-8 without a BOM; the current JSON decoding flow does not automatically remove an initial BOM.
- The command does not recursively find cases in directories. Pass each `.json` or `.jsonl` file explicitly.
- If one input file fails, the command continues checking later files. Read all diagnostics before rerunning it.
- `--real-only` and `--require-reviewed` apply to every input in that invocation. Use separate commands when files require different gates.
- `--as-of` changes only the date cutoff. It does not update record dates or fetch sources again.
- To convert JSONL to `.json`, combine the case objects into a JSON array. Changing the extension alone is insufficient.
