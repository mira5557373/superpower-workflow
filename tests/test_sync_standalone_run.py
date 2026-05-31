"""v1.3.1 HIGH #5: DbSyncAdapter must ingest project-level events (run_id="")
into a synthetic standalone SwRun per project, not silently drop them.
"""

from __future__ import annotations

import json

import pytest

from superpower_workflow.db.engine import create_engine_from_url, get_session_factory
from superpower_workflow.db.models import Base, SwEvent, SwRun
from superpower_workflow.db.sync_adapter import DbSyncAdapter


@pytest.fixture
def db_engine():
    engine = create_engine_from_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _write_jsonl(tmp_path, events):
    p = tmp_path / "telemetry.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in events))
    return p


class TestStandaloneRunIngestion:
    def test_spec_lint_with_empty_run_id_ingested(self, db_engine, tmp_path):
        """v1.3.1 HIGH #5: pre-fix this event was silently dropped."""
        path = _write_jsonl(
            tmp_path,
            [
                {
                    "type": "spec_lint_completed",
                    "run_id": "",
                    "spec_path": "spec.md",
                    "score": 92,
                    "checks_passed": 6,
                    "checks_warned": 1,
                    "checks_failed": 0,
                    "blocker_count": 0,
                }
            ],
        )
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="proj-X", project_path="/p", jsonl_path=path)

        session = get_session_factory(db_engine)()
        events = session.query(SwEvent).filter(SwEvent.event_type == "spec_lint_completed").all()
        assert len(events) == 1, "spec_lint_completed must be ingested"
        # And a standalone SwRun must exist for the project
        standalone_runs = session.query(SwRun).filter(SwRun.run_id.like("standalone-%")).all()
        assert len(standalone_runs) == 1
        assert standalone_runs[0].status == "standalone"
        session.close()

    def test_standalone_run_reused_across_events(self, db_engine, tmp_path):
        """Two project-level events should share one standalone run."""
        path = _write_jsonl(
            tmp_path,
            [
                {"type": "spec_lint_completed", "run_id": "", "score": 80},
                {"type": "spec_lint_completed", "run_id": "", "score": 90},
            ],
        )
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="proj-Y", project_path="/p", jsonl_path=path)

        session = get_session_factory(db_engine)()
        events = session.query(SwEvent).filter(SwEvent.event_type == "spec_lint_completed").all()
        assert len(events) == 2
        standalone_runs = session.query(SwRun).filter(SwRun.run_id.like("standalone-%")).all()
        assert len(standalone_runs) == 1, "must reuse standalone run, not create per event"
        session.close()

    def test_unknown_event_with_empty_run_id_still_dropped(self, db_engine, tmp_path):
        """Whitelist semantics: only known standalone events get the synthetic run.
        Unknown types still fall through (existing behavior — they're dropped
        because we can't infer their project-level vs run-scoped intent)."""
        path = _write_jsonl(
            tmp_path,
            [{"type": "random_unknown_event", "run_id": ""}],
        )
        adapter = DbSyncAdapter(db_engine)
        adapter.sync(project_name="proj-Z", project_path="/p", jsonl_path=path)
        session = get_session_factory(db_engine)()
        events = session.query(SwEvent).all()
        assert events == []
        session.close()
