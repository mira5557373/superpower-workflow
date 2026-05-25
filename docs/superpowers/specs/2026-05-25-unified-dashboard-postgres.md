# Unified Dashboard + PostgreSQL + REST API + Docker — Design Spec

**Date:** 2026-05-25
**Spec version:** 1.0
**Status:** Approved for implementation
**Goal:** Multi-project unified dashboard backed by PostgreSQL, with REST API and Docker deployment. Hybrid: server optional — sw run works with flat files alone.

> Validated through ultrathink gap analysis (25 gaps found, all resolved).

---

## 1. Overview

Add PostgreSQL + FastAPI + unified web dashboard to superpower-workflow. The server is OPTIONAL infrastructure — `sw run` continues to work with flat files. When the server is available, it provides: cross-project visibility, historical analytics, searchable events, REST API for external tools, and real-time WebSocket updates.

**Architecture:**
```
sw run (unchanged) → JSONL + JSON flat files (always)
                   → PostgreSQL via TelemetryDbWriter (when DB available)

sw server start    → FastAPI + WebSocket → Unified Dashboard at :3001
                   → REST API /api/v1/* for Grafana/external tools
                   → Reads from PostgreSQL (or flat files as fallback)

docker compose up  → Postgres + API Server (one command)
```

---

## 2. Database Schema (PostgreSQL, SQLAlchemy 2.0)

8 tables, all prefixed `sw_`:

```sql
sw_projects (id UUID PK, name UNIQUE, path TEXT, created_at, updated_at)
sw_runs (id UUID PK, project_id FK, run_id VARCHAR(20), status, model, spec_sha, started_at, completed_at, total_cost_usd, milestone_count, completed_count, failed_count, skipped_count, duration_seconds)
sw_milestones (id UUID PK, run_id FK, name, status, cost_usd, duration_seconds, tests_added, started_at, completed_at)
sw_phases (id UUID PK, milestone_id FK, phase_type, status, cost_usd, duration_ms, session_id, model, input_tokens, output_tokens, started_at, completed_at)
sw_events (id UUID PK, run_id FK, milestone_name, event_type, timestamp, data_json JSON)
sw_quality_gates (id UUID PK, milestone_id FK, checkpoint, gate_name, passed BOOL, detail TEXT)
sw_coverage_results (id UUID PK, milestone_id FK, coverage_pct, threshold, passed BOOL)
sw_gap_reports (id UUID PK, milestone_id FK, pass_num, critical, architectural, important, minor, deferred, converged BOOL)
```

Composite indexes: `(run_id, event_type)` on events, `(project_id, status)` on runs, `(run_id, name)` on milestones.

Connection pooling: `pool_size=5, max_overflow=10, pool_timeout=30` (configurable via `SW_DB_POOL_SIZE`).

---

## 3. TelemetryDbWriter (Dual-Write)

Wraps `TelemetryEmitter` with same `.emit()` interface (duck typing). Background thread with queue for async DB writes — never blocks the synchronous orchestrator.

- JSONL always written first (source of truth)
- Events queued for DB insert
- Background thread flushes queue every 1s or at 50 items
- Failsafe: log warning at 100 queued events, disable DB writes at 1000
- Maps telemetry event types → SQLAlchemy model inserts
- Maintains in-memory `{run_id: UUID, milestone_name: milestone_uuid}` map for foreign keys

---

## 4. DbSyncAdapter (JSONL → Postgres Importer)

Bulk-ingest existing JSONL files into Postgres. Powers `sw server sync --all`.

- Reads via TelemetryReader, groups by run_id
- Creates project + run + milestone + phase + event rows in single transaction
- Idempotent: `ON CONFLICT DO NOTHING`
- Incremental: tracks `last_synced_line` in DB, only reads new lines on re-sync

---

## 5. REST API (FastAPI)

All routes prefixed `/api/v1/`. Authentication via `SW_API_KEY` env (header: `Authorization: Bearer <key>`).

**Endpoints:**
- `GET /api/v1/health` — `{"status": "ok", "db": "connected"}`
- `GET /api/v1/projects` — list all projects
- `GET /api/v1/projects/{id}` — project detail with latest run
- `POST /api/v1/projects/sync` — trigger sync for a project path
- `GET /api/v1/runs?project_id=X&status=Y` — list runs (paginated)
- `GET /api/v1/runs/{id}` — run detail with milestones
- `GET /api/v1/runs/compare?ids=X,Y` — side-by-side comparison
- `GET /api/v1/milestones?run_id=X` — milestones for a run
- `GET /api/v1/milestones/{id}` — milestone detail with phases, gates, gaps
- `GET /api/v1/events?run_id=X&type=Y&since=Z&limit=100` — search/filter
- `GET /api/v1/metrics/costs?project_id=X` — cost analytics
- `GET /api/v1/metrics/quality?project_id=X` — quality trends
- `GET /api/v1/metrics/models` — model usage analytics
- `WS /ws/live?key=<key>&project_id=X` — real-time WebSocket

All list endpoints paginated: `?limit=100&offset=0`, max 1000. Rate limiting: 100 req/min per IP.

**Fallback:** When no Postgres, routers read from ProjectRegistry + flat files via TelemetryReader.

---

## 6. Unified Dashboard

Served at `GET /` on the FastAPI server. Multi-page (client-side hash routing):

- `/#/` — Global overview: project cards, cost trend chart, recent milestones, quality metrics
- `/#/project/{name}` — Project detail: milestone timeline, cost by phase, test growth, gap history
- `/#/compare?runs=X,Y` — Run comparison: side-by-side cost/quality/duration
- `/#/search` — Event search with filters (project, severity, type, date)
- `/#/analytics` — Model usage, cost efficiency, rework rates

Vanilla JS + CSS (no framework), dark theme, monospace. Fetches from REST API. WebSocket for live updates. Charts rendered with inline SVG.

---

## 7. Project Registry

`~/.claude/sw-projects.json` — global file tracking all project paths.

```json
{"projects": [{"name": "my-app", "path": "/path/to/my-app", "added_at": "2026-05-25T12:00:00Z"}]}
```

Auto-registered by `sw init` and `sw run`. Registry enables the unified dashboard to find projects without Postgres.

---

## 8. CLI Commands

```
sw server start [--host HOST] [--port PORT] [--database-url URL]
sw server stop
sw server init-db
sw server sync [--project PATH] [--all]
```

Server start: checks DB schema, auto-migrates if needed, starts uvicorn. Uses PID file for graceful stop.

---

## 9. Docker Compose

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: sw
      POSTGRES_PASSWORD: ${SW_DB_PASSWORD:-changeme}
      POSTGRES_DB: superpower_workflow
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sw"]

  api-server:
    build: {context: .., dockerfile: docker/Dockerfile.server}
    ports: ["3001:3001"]
    environment:
      SW_DATABASE_URL: postgresql+asyncpg://sw:${SW_DB_PASSWORD:-changeme}@postgres:5432/superpower_workflow
      SW_API_KEY: ${SW_API_KEY}
    depends_on:
      postgres: {condition: service_healthy}

volumes:
  pgdata:
```

---

## 10. Orchestrator Integration

In `orchestrator.py`, after creating TelemetryEmitter:

```python
db_url = os.environ.get("SW_DATABASE_URL") or config.get("database", {}).get("url_env", "")
if db_url:
    try:
        from superpower_workflow.db.writer import TelemetryDbWriter
        self._telemetry = TelemetryDbWriter(emitter=self._telemetry, database_url=db_url)
    except ImportError:
        pass  # asyncpg not installed, flat files only
```

Duck typing: TelemetryDbWriter has same `.emit()` and `.close()` as TelemetryEmitter. No other orchestrator changes needed.

---

## 11. Configuration

New optional sections in workflow.json:

```json
{
  "database": {"url_env": "SW_DATABASE_URL", "retention_days": 90, "auto_sync": true},
  "server": {"host": "0.0.0.0", "port": 3001, "cors_origins": ["http://localhost:3001"]}
}
```

---

## 12. Security

- API key auth on all endpoints (`SW_API_KEY` env)
- WebSocket auth via query param
- CORS defaults to localhost only
- DB URL via env var only (never in config files)
- Document: use reverse proxy for HTTPS in production
- OpenAPI docs (`/docs`) disabled when API key set unless authenticated
- Rate limiting: 100 req/min per IP

---

## 13. Files to Create/Modify

| Action | Files |
|---|---|
| Create | `src/superpower_workflow/db/{__init__,engine,models,writer,sync_adapter,queries}.py` |
| Create | `src/superpower_workflow/server/{__init__,app,config,deps,registry}.py` |
| Create | `src/superpower_workflow/server/routers/{__init__,projects,runs,milestones,events,metrics,ws}.py` |
| Create | `src/superpower_workflow/dashboard/unified_static.py` |
| Create | `alembic/`, `alembic.ini`, `alembic/versions/001_initial_schema.py` |
| Create | `docker/Dockerfile.server`, `docker/docker-compose.yml` |
| Create | 9 test files |
| Modify | `pyproject.toml`, `cli.py`, `orchestrator.py`, `dashboard/data.py`, `templates/workflow.json` |

---

## 14. Appendix — Gap Analysis

25 gaps found via ultrathink: 5 security (auth, HTTPS, CORS, WebSocket auth, DB URL exposure), 9 reliability (connection pooling, failsafe, auto-sync, auto-migrate, graceful shutdown, retention, incremental sync, silent failure handling, indexes), 4 API design (versioning, health, pagination, rate limiting), 4 Docker (healthcheck, password defaults, volumes, env docs), 3 nice-to-have (reconnection, OpenAPI, static files). All resolved in design.
