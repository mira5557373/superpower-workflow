from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from superpower_workflow.db.engine import get_session_factory
from superpower_workflow.db.models import Base
from superpower_workflow.db.queries import create_milestone, create_run, get_or_create_project
from superpower_workflow.server.app import create_app
from superpower_workflow.server.config import ServerConfig


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
def seeded_engine(db_engine):
    factory = get_session_factory(db_engine)
    session = factory()
    proj = get_or_create_project(session, "test-app", "/home/user/test-app")
    run = create_run(
        session,
        project_id=proj.id,
        run_id="20260525-120000",
        model="opus",
        milestone_count=3,
    )
    create_milestone(session, run_id=run.id, name="sp1-quality-gates")
    create_milestone(session, run_id=run.id, name="sp2-telemetry")
    session.close()
    return db_engine


@pytest.fixture
def client(seeded_engine):
    from fastapi.testclient import TestClient

    cfg = ServerConfig(api_key="", database_url="")
    app = create_app(cfg)
    app.state.engine = seeded_engine
    return TestClient(app)


class TestProjectsRouter:
    def test_list_projects(self, client):
        r = client.get("/api/v1/projects")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "test-app"

    def test_get_project_by_id(self, client):
        r = client.get("/api/v1/projects")
        proj_id = r.json()[0]["id"]
        r2 = client.get(f"/api/v1/projects/{proj_id}")
        assert r2.status_code == 200
        assert r2.json()["name"] == "test-app"

    def test_get_project_not_found(self, client):
        fake_id = str(uuid.uuid4())
        r = client.get(f"/api/v1/projects/{fake_id}")
        assert r.status_code == 404

    def test_get_project_invalid_uuid_returns_422(self, client):
        r = client.get("/api/v1/projects/not-a-uuid")
        assert r.status_code == 422

    def test_trigger_sync(self, client):
        r = client.post("/api/v1/projects/sync", json={"path": "/p/app"})
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"


class TestRunsRouter:
    def test_list_runs(self, client):
        r = client.get("/api/v1/runs")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_list_runs_with_project_filter(self, client):
        r = client.get("/api/v1/projects")
        proj_id = r.json()[0]["id"]
        r2 = client.get(f"/api/v1/runs?project_id={proj_id}")
        assert r2.status_code == 200
        assert len(r2.json()) == 1

    def test_get_run_by_id(self, client):
        runs = client.get("/api/v1/runs").json()
        if runs:
            run_id = runs[0]["id"]
            r = client.get(f"/api/v1/runs/{run_id}")
            assert r.status_code == 200
            assert "milestones" in r.json()

    def test_get_run_not_found(self, client):
        fake_id = str(uuid.uuid4())
        r = client.get(f"/api/v1/runs/{fake_id}")
        assert r.status_code == 404

    def test_list_runs_pagination(self, client):
        r = client.get("/api/v1/runs?limit=1&offset=0")
        assert r.status_code == 200

    def test_compare_runs(self, client):
        runs = client.get("/api/v1/runs").json()
        if runs:
            run_id = runs[0]["id"]
            r = client.get(f"/api/v1/runs/compare?ids={run_id}")
            assert r.status_code == 200

    def test_get_run_accepts_human_run_id(self, client):
        """Regression for soak bug #6: human run_id must work, not just UUID."""
        runs = client.get("/api/v1/runs").json()
        assert runs
        human_id = runs[0]["run_id"]
        assert "-" in human_id  # confirm it's the timestamp form, not a UUID
        r = client.get(f"/api/v1/runs/{human_id}")
        assert r.status_code == 200
        assert r.json()["run_id"] == human_id

    def test_compare_runs_accepts_human_run_ids(self, client):
        """Regression for soak bug #6: compare must accept human run_ids."""
        runs = client.get("/api/v1/runs").json()
        assert runs
        human_id = runs[0]["run_id"]
        r = client.get(f"/api/v1/runs/compare?ids={human_id}")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["run_id"] == human_id

    def test_get_run_populates_milestones(self, client):
        """Regression for soak bug #5: run detail must include its milestones."""
        runs = client.get("/api/v1/runs").json()
        assert runs
        r = client.get(f"/api/v1/runs/{runs[0]['id']}")
        assert r.status_code == 200
        milestones = r.json()["milestones"]
        assert len(milestones) == 2
        names = {m["name"] for m in milestones}
        assert names == {"sp1-quality-gates", "sp2-telemetry"}


class TestMilestonesRouter:
    def test_list_milestones_for_run(self, client):
        runs = client.get("/api/v1/runs").json()
        if runs:
            run_id = runs[0]["id"]
            r = client.get(f"/api/v1/milestones?run_id={run_id}")
            assert r.status_code == 200
            data = r.json()
            assert len(data) == 2

    def test_get_milestone_by_id(self, client):
        runs = client.get("/api/v1/runs").json()
        if runs:
            run_id = runs[0]["id"]
            milestones = client.get(f"/api/v1/milestones?run_id={run_id}").json()
            if milestones:
                ms_id = milestones[0]["id"]
                r = client.get(f"/api/v1/milestones/{ms_id}")
                assert r.status_code == 200
                assert "phases" in r.json()

    def test_milestone_not_found(self, client):
        fake_id = str(uuid.uuid4())
        r = client.get(f"/api/v1/milestones/{fake_id}")
        assert r.status_code == 404


class TestEventsRouter:
    def test_list_events_empty(self, client):
        runs = client.get("/api/v1/runs").json()
        if runs:
            run_id = runs[0]["id"]
            r = client.get(f"/api/v1/events?run_id={run_id}")
            assert r.status_code == 200
            assert isinstance(r.json(), list)

    def test_events_pagination(self, client):
        r = client.get("/api/v1/events?limit=10&offset=0")
        assert r.status_code == 200

    def test_events_type_filter(self, client):
        r = client.get("/api/v1/events?event_type=phase_completed")
        assert r.status_code == 200

    def test_events_type_filter_actually_filters(self, client, seeded_engine):
        """Regression for soak bug #4: ?type=X was silently ignored (param mismatch)."""
        from superpower_workflow.db.engine import get_session_factory
        from superpower_workflow.db.models import SwRun
        from superpower_workflow.db.queries import create_event

        s = get_session_factory(seeded_engine)()
        run = s.query(SwRun).first()
        create_event(s, run_id=run.id, event_type="milestone_started", data_json={"x": 1})
        create_event(s, run_id=run.id, event_type="phase_completed", data_json={"x": 2})
        create_event(s, run_id=run.id, event_type="run_completed", data_json={"x": 3})
        s.close()

        r = client.get("/api/v1/events?event_type=phase_completed")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["event_type"] == "phase_completed"

    def test_events_run_id_accepts_human_run_id(self, client, seeded_engine):
        """Regression for soak bug #5/#6: human run_id must work, not just UUID."""
        from superpower_workflow.db.engine import get_session_factory
        from superpower_workflow.db.models import SwRun
        from superpower_workflow.db.queries import create_event

        s = get_session_factory(seeded_engine)()
        run = s.query(SwRun).first()
        human_id = run.run_id
        create_event(s, run_id=run.id, event_type="run_started", data_json={"x": 1})
        s.close()

        r = client.get(f"/api/v1/events?run_id={human_id}")
        assert r.status_code == 200
        assert len(r.json()) >= 1


class TestMetricsRouter:
    def test_cost_metrics(self, client):
        r = client.get("/api/v1/metrics/costs")
        assert r.status_code == 200
        data = r.json()
        assert "total_cost" in data

    def test_cost_metrics_with_project(self, client):
        projects = client.get("/api/v1/projects").json()
        if projects:
            pid = projects[0]["id"]
            r = client.get(f"/api/v1/metrics/costs?project_id={pid}")
            assert r.status_code == 200

    def test_quality_metrics(self, client):
        r = client.get("/api/v1/metrics/quality")
        assert r.status_code == 200
        data = r.json()
        assert "rework_rate" in data
        assert "gap_reports" in data

    def test_model_metrics(self, client):
        r = client.get("/api/v1/metrics/models")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))
