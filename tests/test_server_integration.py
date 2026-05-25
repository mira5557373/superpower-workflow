from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from superpower_workflow.db.engine import get_session_factory
from superpower_workflow.db.models import Base
from superpower_workflow.db.queries import (
    create_event,
    create_gap_report,
    create_milestone,
    create_phase,
    create_quality_gate,
    create_run,
    get_or_create_project,
)
from superpower_workflow.db.sync_adapter import DbSyncAdapter
from superpower_workflow.db.writer import TelemetryDbWriter
from superpower_workflow.server.app import create_app
from superpower_workflow.server.config import ServerConfig
from superpower_workflow.server.registry import ProjectRegistry
from superpower_workflow.telemetry import (
    MilestoneCompleted,
    MilestoneStarted,
    PhaseCompleted,
    RunCompleted,
    RunStarted,
    TelemetryEmitter,
)


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def full_pipeline(db_engine):
    factory = get_session_factory(db_engine)
    session = factory()
    proj = get_or_create_project(session, "integration-app", "/home/user/app")
    run = create_run(
        session,
        project_id=proj.id,
        run_id="20260525-120000",
        model="opus",
        milestone_count=3,
    )
    ms1 = create_milestone(session, run_id=run.id, name="sp1-quality-gates")
    ms2 = create_milestone(session, run_id=run.id, name="sp2-telemetry")
    ms3 = create_milestone(session, run_id=run.id, name="sp3-dashboard")
    create_phase(session, milestone_id=ms1.id, phase_type="plan", model="opus", status="completed")
    create_phase(
        session, milestone_id=ms1.id, phase_type="implement", model="opus", status="completed"
    )
    create_quality_gate(
        session, milestone_id=ms1.id, checkpoint="qcb", gate_name="lint", passed=True
    )
    create_gap_report(
        session, milestone_id=ms1.id, pass_num=1, critical=0, important=2, converged=True
    )
    for ms in (ms1, ms2, ms3):
        create_event(
            session,
            run_id=run.id,
            milestone_name=ms.name,
            event_type="milestone_started",
            data_json={"milestone": ms.name},
        )
    create_event(
        session,
        run_id=run.id,
        event_type="run_completed",
        data_json={"status": "complete", "total_cost_usd": 25.0},
    )
    session.close()
    return db_engine


class TestFullPipeline:
    def test_all_data_accessible_via_api(self, full_pipeline):
        from fastapi.testclient import TestClient

        cfg = ServerConfig(api_key="", database_url="")
        app = create_app(cfg)
        app.state.engine = full_pipeline
        client = TestClient(app)

        projects = client.get("/api/v1/projects").json()
        assert len(projects) == 1
        assert projects[0]["name"] == "integration-app"

        runs = client.get("/api/v1/runs").json()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "20260525-120000"

        run_detail = client.get(f"/api/v1/runs/{runs[0]['id']}").json()
        assert len(run_detail["milestones"]) == 3

        milestones = client.get(f"/api/v1/milestones?run_id={runs[0]['id']}").json()
        assert len(milestones) == 3

        ms_detail = client.get(f"/api/v1/milestones/{milestones[0]['id']}").json()
        assert "phases" in ms_detail
        assert "quality_gates" in ms_detail
        assert "gap_reports" in ms_detail

        events = client.get(f"/api/v1/events?run_id={runs[0]['id']}").json()
        assert len(events) >= 4

        costs = client.get("/api/v1/metrics/costs").json()
        assert "total_cost" in costs

        quality = client.get("/api/v1/metrics/quality").json()
        assert "gap_reports" in quality

        models = client.get("/api/v1/metrics/models").json()
        assert "models" in models


class TestWriterToApiPipeline:
    def test_writer_events_visible_in_api(self, db_engine, tmp_path):
        from fastapi.testclient import TestClient

        emitter = TelemetryEmitter(tmp_path / "telemetry.jsonl", run_id="wr-test")
        writer = TelemetryDbWriter(
            emitter=emitter,
            engine=db_engine,
            project_name="writer-app",
            project_path="/p/writer",
        )

        writer.emit(RunStarted(spec_sha="abc", model="opus", milestone_count=2))
        writer.emit(MilestoneStarted(milestone="m1", index=0))
        writer.emit(PhaseCompleted(milestone="m1", phase="plan", cost_usd=3.0, duration_ms=10000))
        writer.emit(MilestoneCompleted(milestone="m1", cost_usd=8.0, duration_seconds=60.0))
        writer.emit(RunCompleted(status="complete", total_cost_usd=8.0, completed_count=1))
        writer.close()

        cfg = ServerConfig(api_key="", database_url="")
        app = create_app(cfg)
        app.state.engine = db_engine
        client = TestClient(app)

        projects = client.get("/api/v1/projects").json()
        assert any(p["name"] == "writer-app" for p in projects)

        events = client.get("/api/v1/events").json()
        types = {e["event_type"] for e in events}
        assert "run_started" in types
        assert "phase_completed" in types


class TestSyncToApiPipeline:
    def test_synced_data_visible_in_api(self, db_engine, tmp_path):
        from fastapi.testclient import TestClient

        jsonl = tmp_path / "telemetry.jsonl"
        events = [
            {
                "type": "run_started",
                "run_id": "sync-test",
                "timestamp": "2026-05-25T12:00:00Z",
                "model": "opus",
                "milestone_count": 1,
            },
            {
                "type": "milestone_started",
                "run_id": "sync-test",
                "timestamp": "2026-05-25T12:00:01Z",
                "milestone": "s1",
            },
            {
                "type": "run_completed",
                "run_id": "sync-test",
                "timestamp": "2026-05-25T12:00:02Z",
                "status": "complete",
                "total_cost_usd": 5.0,
            },
        ]
        jsonl.write_text("\n".join(json.dumps(e) for e in events))

        adapter = DbSyncAdapter(db_engine)
        adapter.sync("sync-app", "/p/sync", jsonl)

        cfg = ServerConfig(api_key="", database_url="")
        app = create_app(cfg)
        app.state.engine = db_engine
        client = TestClient(app)

        projects = client.get("/api/v1/projects").json()
        assert any(p["name"] == "sync-app" for p in projects)

        runs = client.get("/api/v1/runs").json()
        assert any(r["run_id"] == "sync-test" for r in runs)


class TestRegistryIntegration:
    def test_registry_tracks_multiple_projects(self, tmp_path):
        reg = ProjectRegistry(tmp_path / "reg.json")
        reg.register("app1", "/p/1")
        reg.register("app2", "/p/2")
        reg.register("app3", "/p/3")
        assert len(reg.list_projects()) == 3
        reg.remove("app2")
        assert len(reg.list_projects()) == 2
        names = [p.name for p in reg.list_projects()]
        assert "app1" in names
        assert "app3" in names

    def test_registry_persists(self, tmp_path):
        path = tmp_path / "reg.json"
        r1 = ProjectRegistry(path)
        r1.register("app", "/p")
        r2 = ProjectRegistry(path)
        assert len(r2.list_projects()) == 1


class TestApiAuth:
    def test_full_pipeline_with_auth(self, full_pipeline):
        from fastapi.testclient import TestClient

        cfg = ServerConfig(api_key="secret-key", database_url="")
        app = create_app(cfg)
        app.state.engine = full_pipeline
        client = TestClient(app)

        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/projects").status_code == 401
        r = client.get("/api/v1/projects", headers={"Authorization": "Bearer secret-key"})
        assert r.status_code == 200
        assert len(r.json()) == 1


class TestDashboardServing:
    def test_dashboard_html_served_at_root(self, full_pipeline):
        from fastapi.responses import HTMLResponse
        from fastapi.testclient import TestClient

        from superpower_workflow.dashboard.unified_static import UNIFIED_DASHBOARD_HTML

        cfg = ServerConfig(api_key="", database_url="")
        app = create_app(cfg)
        app.state.engine = full_pipeline

        @app.get("/")
        def dashboard():
            return HTMLResponse(UNIFIED_DASHBOARD_HTML)

        client = TestClient(app)
        r = client.get("/")
        assert r.status_code == 200
        assert "<!DOCTYPE html>" in r.text
        assert "monospace" in r.text
