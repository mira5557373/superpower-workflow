# Changelog

All notable changes to superpower-workflow are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.4] — 2026-05-29

### Added — Direction B: strict mode for trust-but-verify
- `validation.strict_mode` (default `false`). When enabled, after Phase C finishes the orchestrator re-runs spec compliance + feature verification and, if any requirement is marked `missing` or any feature is marked `broken`, runs an explicit fix prompt that calls out each item with its evidence and requires TDD fixes. Loops up to `validation.max_strict_iterations` (default 2) and exits as soon as both counters hit zero.
- Why this matters: in the 2026-05-29 M1→M2→M3 soak, M2 implemented `remove` subcommand instead of spec-required `rm`. With strict mode off (existing behavior), this shipped to push and was only fixed by happenstance when M3 needed `rm`. With strict mode on, the loop would have caught and fixed it inside M2.
- New telemetry event `strict_mode_iteration` with `iteration / missing_requirements / broken_features / converged / cost_usd`.
- New config keys: `validation.strict_mode`, `validation.max_strict_iterations`, `validation.strict_iteration_budget`.

### Fixed — Direction A: CI failures observed on first real runs
- CI now passes on the full ubuntu+windows × py3.11+3.12 matrix. Two real issues surfaced and were fixed:
  - `ruff check .` was linting `soak-archive/` and `examples/` (sw-generated content not held to our style). Added `extend-exclude` for `soak-archive`, `examples`, `continue_sp2_sp7.py`.
  - `DashboardData.has_changed()` only compared mtime, which on Windows + Python 3.12 produced false-negatives when tests wrote the file fast enough that two distinct writes shared a FileTime tick. Now compares `(mtime, size)`.

### Validation
- Strict-mode soak with all 4 todo-cli commands in one milestone: $6.38, 24.5 min, full Plan/Implement/Spec/Verify/Review/Push pipeline. Compliance and verification both came back clean on first pass, so strict mode correctly stayed dormant — confirming the loop doesn't false-positive.
- 4 new unit tests (`TestStrictModeTrustButVerify`) cover trigger paths: off-by-default, loop-on-missing-until-resolved, cap-iterations, broken-features-also-trigger.
- Test count: 1070 → **1077** passing on all CI matrix combinations.

## [1.1.3] — 2026-05-29

### Fixed (Path 1 — soak-artifact inspection)
- **Spec compliance / feature verification prompts** rewritten to demand a single JSON object as the response and explicitly forbid file-writing tool calls. Previously the prompts told claude to BOTH `Write .claude/.spec-compliance.json` AND `Output ONLY the JSON content`, so claude often wrote the file (good) but returned a confirmation message in stdout (not JSON), and the parser returned 0/0/0. M2 soak post-fix: 14 requirements / 13 implemented / 1 missing with file:function evidence. M3 soak post-fix: 20/20/0 (full implementation including the auto-fix of M2's `remove`→`rm` subcommand typo).
- **Trust-but-verify reports preserved after milestone success.** `clear_phase_state` was destroying `.gap-report.json` / `.spec-compliance.json` / `.feature-verification.json` between phases, so post-run audit had nothing to inspect. Added `archive_reports(claude_dir, milestone, phase)` that copies them to `.claude/reports/<milestone>/<phase>/` before clearing. Path sanitization defends against directory traversal in milestone names.
- **Gap report `converged=False` when zero gaps** — the model often forgot to flip the flag. Override in `_emit_gap_report`: total_gaps_found == 0 implies converged.

### Fixed (Path 2 — estimator recalibration from real soak data)
- Forecast vs actual was 2.5× under ($1.43-$2.85 forecast, $7.00 actual). Three root causes fixed:
  - `BUDGET_CAP_FRACTION=0.15` artificially clamped per-milestone cost at 15% of total per-phase budgets — no observed basis, removed.
  - `OPTIMISTIC_FACTOR=0.5` was too aggressive — raised to `0.7`.
  - Trust-but-verify costs were not modeled at all. Soak measured 13.5% overhead; added `TRUST_BUT_VERIFY_OVERHEAD=0.15` when validation flags are enabled.
- Post-fix calibration: M2 forecast $5.60-$9.10, actual $6.30 ✓ in range.

### Validation
- 3-milestone real soak (todo-cli M1+M2+M3): $18.68 total, 73 min, 701 lines of test code, working CLI with `add`/`list`/`done`/`rm` commands. All three milestone Phase A/B/spec/verify/C/D paths succeeded.
- Spec compliance now produces actionable signal — M2 caught a real implementation bug (`remove` subcommand vs spec's `rm`); M3 fixed it by adding `rm` as an alias.
- Test count: 1063 → 1070 (+7 regression tests for Paths 1+2 fixes).
- `soak-archive/todo-cli-run2/` preserves the full M1+M2+M3 evidence.

## [1.1.2] — 2026-05-29

### Fixed (real-milestone soak)
- `runner.run_claude` now logs the upstream error when claude returns `is_error=true` or exits non-zero. Previously the orchestrator showed only the generic "claude -p returned an error" with no actionable context, leading to multi-minute retries against an unavailable model. Surfaced upstream message (model not available, auth failures, etc.) at WARNING level on every failed attempt.
- `sw init` `.gitignore` now includes `.claude/.workflow.lock.json`, `.claude/.workflow.lock.filelock`, and `.claude/workflow-complete.json` — the v1.1.0 lock changes introduced these auxiliary files but they weren't ignored, so the next `sw run` falsely tripped the "uncommitted changes" preflight.

### Validation
- End-to-end soak on a fresh todo-cli spec: Plan → Implement → Spec compliance → Feature verification → Review → Push, all phases green. $7.00 total, 26.7 min, 3 test files + working code produced, 11 conventional commits pushed to remote. Confirms the orchestrator hot path is intact after v1.1.0/v1.1.1 changes.

## [1.1.1] — 2026-05-29

### Fixed (post-1.1.0 soak)
- 8 bugs surfaced by v1.1.0 soak test: WebSocket producer wired (polling), sync adapter materializes sw_phases and per-run milestones, `/api/v1/events` filter param renamed (`type` → `event_type`), `/runs/{id}` and `/runs/compare` accept human run_ids, run detail returns its milestones, gap validator no longer flags distinct lines of the same file as duplicates, gap validator falls back to recursive filename search.
- Wheel packaging: `templates/`, `skills/`, `commands/` moved into `src/superpower_workflow/_assets/` so they actually ship with `pip install`. Previously only worked with `pip install -e .`.

### Added
- `.github/workflows/test.yml` — matrix CI on push/PR (ubuntu+windows × py3.11+3.12) with wheel asset-presence check.
- `sw run --dry-run` now prints milestone list, per-phase budget, convergence-loop config, verify commands, and a cost/duration forecast that uses historical telemetry when available. No claude calls made.
- `examples/todo-cli/` — tiny end-to-end demo (spec + expected decomposition + reference workflow.json) for internal onboarding.
- WebSocket emits a warning when `MAX_EVENTS_PER_TICK` is hit so backlog isn't silent.

### Changed
- README install section rewritten for internal distribution: three paths (git+ssh, local wheel, submodule editable). PyPI references removed.

### Stats
- 1063 tests passing across all platforms in CI matrix.

## [1.1.0] — 2026-05-28

### Added
- **Gap Validator** — code-enforced verification that AI-reported gaps reference real files, lines, and symbols. Three states (valid/invalid/unverifiable) with confidence scoring. Cross-checks lint/coverage claims against actual tool output.
- **Spec Compliance Checker** — independent `claude -p` pass that verifies all spec requirements are implemented after Phase B. Reports missing features to Phase C.
- **Feature Verification Tester** — independent `claude -p` pass that runs verification tests for spec features (not just code reviews). Detects features that "exist but don't work."
- **Production-grade lock** — `filelock` library + composite identity (PID + start_time + hostname) + heartbeat. Detects stale locks across PID reuse, terminal restarts, and hung processes.
- **`sw lock status`** — inspect lock holder (PID, host, heartbeat age, stale status).
- **`sw lock force-clean`** — escape hatch when auto-recovery fails.
- **`sw clean`** — remove all runtime files (state, lock, gap reports, telemetry).
- **Unified web dashboard** — multi-project view at `http://localhost:3001` via FastAPI + WebSocket. Drill-down per project, run comparison, search/audit, model analytics.
- **PostgreSQL telemetry storage** — optional dual-write adapter. Flat files remain primary; DB provides cross-project queries, historical analytics, search.
- **REST API** — `/api/v1/*` endpoints for projects, runs, milestones, events, metrics. API key auth, rate limiting, pagination.
- **Docker Compose deployment** — `postgres + api-server` stack. One command (`docker compose up`).
- **`sw server start/stop/init-db/sync`** — manage the unified server.
- **`sw bootstrap`** — one-command project setup (devcontainer, CI, hooks, CLAUDE.md, docs scaffold).
- **`sw upgrade`** — detect outdated deps with AI-assisted migration.
- **`sw plugin add/list/remove`** — plugin system via setuptools entry points.
- **Auto-generated docs** — README, CHANGELOG, API docs (Sphinx/MkDocs), Mermaid diagrams.
- **Multi-model routing** — route tasks by complexity (haiku/sonnet/opus).
- **Parallel execution** — git worktree isolation, best-of-N, remote SSH execution.
- **HMAC audit trail** — tamper-evident chain of events for compliance.
- **CycloneDX SBOM** — generated per milestone.
- **Ed25519 artifact signing** — provenance via git notes.
- **Secrets broker** — env-only secret references (never in config files).
- **Policy engine** — `max_file_lines`, `banned_imports`, `required_license`, etc.
- **GitHub Issues integration** — `sw run --from-issue 42`.
- **Linear/Jira integration** — `sw run --from-ticket LIN-42`.
- **CI self-correction** — when CI fails, pull logs, fix, re-push.
- **Slack notifications** — milestone start/complete/fail webhooks.
- **Auto PR creation** — after each milestone with summary and cost.

### Changed
- `acquire_lock` is now atomic via `O_EXCL` (was: race-prone file existence check).
- `sw init` defaults `verify_commands.test` to `null` (was: `"python -m pytest -q"` which failed on empty projects).
- `sw init` adds Python standard `.gitignore` entries (`.venv/`, `__pycache__/`, etc.).
- `sw init` defaults `docs.readme.enabled` to `True`.
- Estimator uses realistic averages ($8-18/milestone) and historical telemetry when available (was: budget-cap multiplication producing 5-10x overestimates).
- Decomposer has stricter validation prompt + fallback JSON extraction.
- Convergence hook messages include iteration count (`Pass N/M: ...`).
- Phase A prompt instructs CLAUDE.md auto-generation if missing.
- Phase C prompt receives `compliance_report` and `verification_report` as context.

### Fixed
- Stale lock detection: PID liveness check with `start_time` to defeat PID reuse.
- TOCTOU race in lock acquisition (now atomic).
- Hostname check: locks held by other machines on shared filesystems are respected.
- Hung-process recovery via heartbeat staleness check (10 min default).
- Decomposer router crash when `spec_sections` is a list (was: only handled string).
- Resume after Phase B crash recovers via git log analysis.

### Dependencies
- **New runtime:** `filelock>=3.13`, `psutil>=5.9`.
- **Optional `[server]`:** sqlalchemy, alembic, fastapi, uvicorn, psycopg2-binary.
- **Optional `[security]`:** cryptography.

### Known gaps deferred to v1.2.0
- Alembic migrations not yet shipped. Today `Base.metadata.create_all` is the source of truth; safe because the schema is fresh. First schema change triggers Alembic baseline.

## [1.0.0] — 2026-05-24

### Added
- Initial release.
- Core CLI: `sw init`, `sw doctor`, `sw decompose`, `sw estimate`, `sw run`, `sw status`, `sw resume`.
- 4-phase orchestrator (Plan + Ultrathink → Implement → Review + Fix → Push).
- Convergence hook (Stop hook exit code 2) for ultrathink/review loops.
- 4-layer resilience: retry, milestone retry, skip+continue, circuit breaker.
- Skills: `ultrathink-gap-analysis`, `post-impl-review`, `production-readiness-review`.
- Slash command: `/ultrathink`.
- Quality gates: lint, SAST, coverage, dep scan.
- Telemetry (JSONL).
- Web dashboard (single-project).
- Terminal TUI (`sw watch`).
- 90 tests, ruff clean.

[1.1.0]: https://github.com/mira5557373/superpower-workflow/releases/tag/v1.1.0
[1.0.0]: https://github.com/mira5557373/superpower-workflow/releases/tag/v1.0.0
