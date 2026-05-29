---
name: production-readiness-review
description: Use after post-impl-review passes — checks security, performance, observability, error resilience, data integrity, deployment readiness, and documentation for production-deployable code
---

# Production Readiness Review

## When to use
After post-impl-review converges. Final quality gate before push.

## Artifact Type Detection
Before running checks, detect type by file structure:
- HTTP endpoint files (FastAPI/Flask routes) → **service**
- argparse/click → **CLI**
- Neither → **library**
- Mixed → apply both profiles

## COMMON Checklist (all profiles)

### Security
- No secrets/credentials in source code
- No secrets in log output or stack traces
- All external input validated at system boundaries
- SQL uses parameterized queries (no string formatting)
- File paths sanitized (no traversal)

### Error Resilience
- Every external call handles or explicitly propagates errors
- Transient failures use retry with backoff
- Error messages are actionable but don't leak internals

### Testing
- No time.sleep in tests (use mocks)
- No network calls in unit tests
- Tests are order-independent
- Assertions verify behavior (not just "doesn't crash")

### Code Quality
- No TODO/FIXME/HACK in shipped code
- Follows CLAUDE.md conventions
- Consistent with existing codebase patterns

## SERVICE Checklist (additional)
- Health check endpoint returns dependency status
- Structured logging (JSON/key=value) at error boundaries
- CORS configured for web endpoints
- Rate limiting on public endpoints
- Request/response size limits
- Graceful shutdown (SIGTERM → drain connections → exit)
- Config validated at startup (fail fast)
- Database migrations are reversible
- API error responses use consistent format
- POST create-endpoints are idempotent
- Connection pool limits configured
- Query timeouts set

## CLI Checklist (additional)
- Exit codes follow convention (0=success, 1=error, 2=usage)
- SIGINT/SIGTERM handled gracefully
- Argument validation with clear error messages
- Environment variables documented in --help or README

## Severity
- 🔴 Critical: secret in code, SQL injection, missing auth, no error handling on external call, public endpoint without rate limiting
- 🔴 Architectural: needs infrastructure setup (KMS, vault, CDN) — flag only, don't auto-fix, doesn't block convergence
- 🟡 Important: missing structured logging, missing health check, hardcoded config, no graceful shutdown
- 🟢 Acceptable: missing optimization, missing non-critical docs

## Dedup Rule
If a gap was already flagged by a prior skill (check gap_summaries for same file:line), don't re-count it. Tag new gaps [production].

## Post-Fix Verification
After fixing production issues, re-run the full test suite before writing gap report. Production fixes (adding try/except, changing control flow) can break existing tests.
