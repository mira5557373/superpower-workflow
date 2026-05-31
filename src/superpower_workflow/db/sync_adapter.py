from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Engine

from superpower_workflow.db.engine import get_session_factory
from superpower_workflow.db.models import SwEvent, SwMilestone, SwPhase, SwRun
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
            milestone_uuids: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
            phase_uuids: dict[tuple[uuid.UUID, str], uuid.UUID] = {}

            # v1.3.1 HIGH #5: project-level events emitted outside a run
            # (e.g., `sw lint-spec` standalone → spec_lint_completed with
            # run_id="") were silently dropped because the loop continued
            # when run_id wasn't recognized. Lazy-create a synthetic
            # "standalone" SwRun per project so these events persist.
            standalone_uuid: uuid.UUID | None = None
            STANDALONE_EVENTS = {"spec_lint_completed"}

            def _get_standalone() -> uuid.UUID:
                nonlocal standalone_uuid
                if standalone_uuid is not None:
                    return standalone_uuid
                # v1.3.2 #6 fix: SwRun.run_id is String(20). The previous
                # f"standalone-{proj.id}" was 47 chars (UUID is 36) and
                # caused a Postgres StringDataRightTruncation, which the
                # broad except below rolled back, dropping every event in
                # the same flush. SQLite ignored the length and masked
                # the bug. Use the first 8 hex chars of proj.id for a
                # 19-char id that fits the column; uniqueness is still
                # scoped by (project_id, run_id).
                run_id_str = f"standalone-{proj.id.hex[:8]}"
                existing = get_run_by_run_id(session, proj.id, run_id_str)
                if existing:
                    standalone_uuid = existing.id
                else:
                    standalone_run = SwRun(
                        id=uuid.uuid4(),
                        project_id=proj.id,
                        run_id=run_id_str,
                        model="",
                        status="standalone",
                    )
                    session.add(standalone_run)
                    session.flush()
                    standalone_uuid = standalone_run.id
                return standalone_uuid

            for event in events:
                run_id = event.get("run_id", "")
                event_type = event.get("type", "")

                # Route project-level events without a run_id to the synthetic
                # standalone run, then proceed to event insertion.
                if not run_id and event_type in STANDALONE_EVENTS:
                    standalone = _get_standalone()
                    evt = SwEvent(
                        id=uuid.uuid4(),
                        run_id=standalone,
                        milestone_name=event.get("milestone"),
                        event_type=event_type,
                        data_json=event,
                    )
                    session.add(evt)
                    continue

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
                    key = (run_uuid, ms_name)
                    if ms_name and key not in milestone_uuids:
                        existing_ms = (
                            session.query(SwMilestone)
                            .filter(SwMilestone.run_id == run_uuid, SwMilestone.name == ms_name)
                            .first()
                        )
                        if existing_ms is not None:
                            milestone_uuids[key] = existing_ms.id
                        else:
                            ms = SwMilestone(
                                id=uuid.uuid4(),
                                run_id=run_uuid,
                                name=ms_name,
                                status="running",
                            )
                            session.add(ms)
                            session.flush()
                            milestone_uuids[key] = ms.id

                if event_type == "milestone_completed":
                    ms_name = event.get("milestone", "")
                    ms_id = milestone_uuids.get((run_uuid, ms_name))
                    if ms_id is not None:
                        ms_obj = session.query(SwMilestone).filter(SwMilestone.id == ms_id).first()
                        if ms_obj is not None:
                            ms_obj.status = event.get("status", "completed")
                            ms_obj.cost_usd = event.get("cost_usd", ms_obj.cost_usd)
                            ms_obj.duration_seconds = event.get(
                                "duration_seconds", ms_obj.duration_seconds
                            )

                if event_type == "phase_started":
                    ms_name = event.get("milestone", "")
                    phase_type = event.get("phase", "")
                    ms_id = milestone_uuids.get((run_uuid, ms_name))
                    if ms_id is not None and phase_type:
                        phase_key = (ms_id, phase_type)
                        if phase_key not in phase_uuids:
                            phase = SwPhase(
                                id=uuid.uuid4(),
                                milestone_id=ms_id,
                                phase_type=phase_type,
                                status="running",
                                model=event.get("model"),
                                session_id=event.get("session_id"),
                            )
                            session.add(phase)
                            session.flush()
                            phase_uuids[phase_key] = phase.id

                if event_type == "phase_completed":
                    ms_name = event.get("milestone", "")
                    phase_type = event.get("phase", "")
                    ms_id = milestone_uuids.get((run_uuid, ms_name))
                    phase_id = phase_uuids.get((ms_id, phase_type)) if ms_id is not None else None
                    if phase_id is not None:
                        phase_obj = session.query(SwPhase).filter(SwPhase.id == phase_id).first()
                        if phase_obj is not None:
                            phase_obj.status = event.get("status", "completed")
                            phase_obj.cost_usd = event.get("cost_usd", phase_obj.cost_usd)
                            phase_obj.duration_ms = event.get("duration_ms", phase_obj.duration_ms)
                            # Defensive: prefer top-level (post-v1.1.6) but fall back to
                            # usage.* for legacy event dicts.
                            usage = event.get("usage") or {}
                            phase_obj.input_tokens = event.get(
                                "input_tokens",
                                usage.get("input_tokens", phase_obj.input_tokens),
                            )
                            phase_obj.output_tokens = event.get(
                                "output_tokens",
                                usage.get("output_tokens", phase_obj.output_tokens),
                            )

                if event_type == "run_completed":
                    run_obj = session.query(SwRun).filter(SwRun.id == run_uuid).first()
                    if run_obj:
                        run_obj.status = event.get("status", "complete")
                        run_obj.total_cost_usd = event.get("total_cost_usd", 0.0)
                        run_obj.completed_count = event.get("completed_count", 0)
                        run_obj.failed_count = event.get("failed_count", 0)
                        run_obj.skipped_count = event.get("skipped_count", 0)
                        run_obj.duration_seconds = event.get("duration_seconds", 0.0)

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
