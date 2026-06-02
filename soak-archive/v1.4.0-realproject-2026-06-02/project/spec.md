# shrt — URL Shortener CLI Spec

A tiny command-line URL shortener. Python 3.11+. Single-file JSON storage.

## Functional requirements

- `shrt add <url> [--alias NAME]` must accept any valid http(s) URL and produce a short code. When `--alias` is given the alias is the short code (must match `[a-zA-Z0-9_-]{1,32}`); otherwise the short code must be a deterministic 6-character base62 hash of the URL.
- `shrt resolve <code>` must print the long URL associated with the code, or exit 1 with an error to stderr when the code is unknown.
- `shrt list [--limit N]` must print one entry per line in `code\tcreated\turl` tab-separated format, sorted by creation time descending. When `--limit` is omitted all entries print.
- `shrt rm <code>` must remove a code permanently. When the code is unknown the command must exit 1 with an error to stderr.
- `shrt stats` must print total entry count, entries created in the last 24 hours, and most recent entry.

## Non-functional requirements

- Storage at `~/.shrt/store.json` (auto-created with `0o600` permissions).
- All writes must be atomic (write to `.tmp`, fsync, rename).
- All commands must be deterministic — same state, same input, same output.
- All output must be plain text (no ANSI colors) to support piping to other tools.

## Quality gates

- `ruff check .` must report zero violations.
- `pytest -q` must pass with at least 90% branch coverage on the `shrt/` package.
- `pytest -q` must include tests for every CLI subcommand, every error path, and storage edge cases (empty file, corrupted JSON, missing parent directory).

## Out of scope

- No tags, no user accounts, no web UI.
- No analytics or click tracking.
- No multi-user / network features.
- No URL validation beyond http(s) scheme check.
