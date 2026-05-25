from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Engine

from superpower_workflow.db.engine import get_session_factory
from superpower_workflow.db.models import SwEvent, SwMilestone, SwRun
from superpower_workflow.db.queries import get_or_create_project, get_run_by_run_id

logger = logging.getLogger(__name__)


class DbSyncAdapter:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def sync(self, project_name: str, project_path: str, jsonl_path: Path) -> None:
        if not jsonl_path.exists():
            return

        lines = jsonl_path.read_text(encoding="utf-8").splitlines()
        events: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        if not events:
            return

        factory = get_session_factory(self._engine)
        session = factory()
        try:
            proj = get_or_create_project(session, project_name, project_path)
            run_uuids: dict[str, uuid.UUID] = {}
            milestone_uuids: dict[str, uuid.UUID] = {}

            for event in events:
                run_id = event.get("run_id", "")
                event_type = event.get("type", "")

                if event_type == "run_started" and run_id:
                    existing = get_run_by_run_id(session, proj.id, run_id)
                    if existing:
                        run_uuids[run_id] = existing.id
                        continue
                    run = SwRun(
                        id=uuid.uuid4(),
                        project_id=proj.id,
                        run_id=run_id,
                        model=event.get("model", ""),
                        status="running",
                        milestone_count=event.get("milestone_count", 0),
                        spec_sha=event.get("spec_sha"),
                    )
                    session.add(run)
                    session.flush()
                    run_uuids[run_id] = run.id
                    evt = SwEvent(
                        id=uuid.uuid4(),
                        run_id=run.id,
                        event_type=event_type,
                        data_json=event,
                    )
                    session.add(evt)
                    continue

                if run_id not in run_uuids:
                    existing = get_run_by_run_id(session, proj.id, run_id) if run_id else None
                    if existing:
                        run_uuids[run_id] = existing.id
                    else:
                        continue

                run_uuid = run_uuids[run_id]

                if event_type == "milestone_started":
                    ms_name = event.get("milestone", "")
                    if ms_name and ms_name not in milestone_uuids:
                        ms = SwMilestone(
                            id=uuid.uuid4(),
                            run_id=run_uuid,
                            name=ms_name,
                            status="running",
                        )
                        session.add(ms)
                        session.flush()
                        milestone_uuids[ms_name] = ms.id

                if event_type == "run_completed":
                    run_obj = session.query(SwRun).filter(SwRun.id == run_uuid).first()
                    if run_obj:
                        run_obj.status = event.get("status", "complete")
                        run_obj.total_cost_usd = event.get("total_cost_usd", 0.0)
                        run_obj.completed_count = event.get("completed_count", 0)

                evt = SwEvent(
                    id=uuid.uuid4(),
                    run_id=run_uuid,
                    milestone_name=event.get("milestone"),
                    event_type=event_type,
                    data_json=event,
                )
                session.add(evt)

            session.commit()
        except Exception:
            session.rollback()
            logger.warning("Sync failed", exc_info=True)
        finally:
            session.close()
