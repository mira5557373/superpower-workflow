# superpower-workflow — Feature Roadmap

**Last updated:** 2026-05-24
**Current version:** 0.1.0.dev0 (90 tests, proven on 35 milestones)

## Sub-Projects (SP1-SP7)

Each SP gets its own spec → plan → `sw run` cycle. Order matters — later SPs depend on earlier ones.

### SP1: Quality Gates (→ v0.2.0) — NOT STARTED
**Scope:** Self-review pipeline (lint + SAST + secret scan before commit), coverage-target test generation, loop detection, backpressure gates, git trailers for AI attribution, dependency vulnerability scanning.
**Depends on:** Nothing (enhances existing Phase B/C)
**Key interfaces:**
- Quality gate results feed into gap report (gap_summaries)
- Git trailers added to every commit by subagents
- Dep scan results integrated into production-readiness skill
**Spec:** (not yet written)
**Status:** Not started

### SP2: Telemetry & Analytics (→ v0.3.0) — NOT STARTED
**Scope:** Structured telemetry (JSONL), quality trend tracking, rework rate, defect density, cost-per-successful-task metrics.
**Depends on:** SP1 (needs quality gate data)
**Key interfaces:**
- Writes to `.claude/telemetry.jsonl` per run
- Provides data API for SP3 (dashboard)
- Tracks: tokens, cost, duration, test count, lint score, gap count per phase
**Spec:** (not yet written)
**Status:** Not started

### SP3: Dashboard (→ v0.4.0) — NOT STARTED
**Scope:** `sw dashboard` (web at localhost:3000), `sw watch` (terminal TUI), real-time milestone progress, cost ticker, log stream, Prometheus /metrics endpoint.
**Depends on:** SP2 (reads telemetry data)
**Key interfaces:**
- Reads `.claude/telemetry.jsonl` and `workflow-state.json`
- Web: React or plain HTML + SSE for live updates
- TUI: rich or textual library
- Prometheus: optional /metrics endpoint for Grafana
**Spec:** (not yet written)
**Status:** Not started

### SP4: Security & Compliance (→ v0.5.0) — NOT STARTED
**Scope:** HMAC-chained audit trail, SBOM generation, Ed25519 signed artifacts, secrets broker, configurable policy engine.
**Depends on:** SP1 (quality gates as enforcement point)
**Key interfaces:**
- Audit log: `.claude/audit-trail.jsonl` with HMAC chain
- SBOM: generated per milestone, stored alongside tag
- Policy engine: rules in workflow.json `policies` section
- Secrets: env-only, never in prompts or disk
**Spec:** (not yet written)
**Status:** Not started

### SP5: Integrations (→ v0.6.0) — NOT STARTED
**Scope:** GitHub Issues, Linear/Jira tracker integration, CI self-correction, Slack notifications, PR auto-creation.
**Depends on:** SP2 (sends metrics to integrations)
**Key interfaces:**
- `sw run --from-issue 42` reads GitHub Issue → milestone
- CI self-correction: pull failure logs → fix → re-push
- Notifiers: plugin-based (Slack, Discord, webhook, email)
- PR: auto-create with summary, test results, cost breakdown
**Spec:** (not yet written)
**Status:** Not started

### SP6: Parallel & Multi-Model (→ v0.7.0) — NOT STARTED
**Scope:** Git worktree isolation, multi-model routing (complexity → model), best-of-N execution, remote SSH execution, Agent Teams integration.
**Depends on:** SP1 (quality gates per agent)
**Key interfaces:**
- Worktrees: each Phase B subagent in own worktree, merge when complete
- Router: workflow.json `model_routing` section maps task complexity → model
- Remote: `sw run --remote ssh://host` for offloading
- Agent Teams: native Claude Code parallel teammates for Phase B
**Spec:** (not yet written)
**Status:** Not started

### SP7: Docs, DX & Plugins (→ v0.8.0-v1.0.0) — NOT STARTED
**Scope:** Auto-generate README/CHANGELOG/API docs/architecture diagrams, `sw bootstrap` (one-command project setup), dependency freshness (`sw upgrade`), pluggable agent/runtime/tracker/notifier system, plugin marketplace.
**Depends on:** SP1-SP6 (plugins wrap all features)
**Key interfaces:**
- Docs: generated post-milestone, committed alongside code
- Bootstrap: generates devcontainer, CI, hooks, CLAUDE.md, docs scaffold
- Plugins: entry-point-based discovery, `sw plugin add <name>`
- Plugin API: hooks into orchestrator lifecycle (pre-phase, post-phase, pre-commit, post-milestone)
**Spec:** (not yet written)
**Status:** Not started

## Cross-Cutting Design Decisions

(Updated as SPs are implemented)

- **Telemetry format:** JSONL (one JSON object per line) — decided SP2, used by SP3/SP4/SP5
- **Plugin API:** Entry-point-based (setuptools) — decided SP7, but interface designed in SP1
- **Audit format:** HMAC-SHA256 chained JSONL — decided SP4
- **Config location:** All in `.claude/workflow.json` under version-specific sections
- **Backward compatibility:** schema_version bump on breaking changes, migration function provided

## Version Mapping

| Version | Sub-Project | Status |
|---|---|---|
| v0.1.0 | Initial release (current) | ✅ Ready to tag |
| v0.2.0 | SP1: Quality Gates | Not started |
| v0.3.0 | SP2: Telemetry & Analytics | Not started |
| v0.4.0 | SP3: Dashboard | Not started |
| v0.5.0 | SP4: Security & Compliance | Not started |
| v0.6.0 | SP5: Integrations | Not started |
| v0.7.0 | SP6: Parallel & Multi-Model | Not started |
| v0.8.0-v1.0.0 | SP7: Docs, DX & Plugins | Not started |
