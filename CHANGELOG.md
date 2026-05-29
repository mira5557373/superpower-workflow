# Changelog

All notable changes to superpower-workflow are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
