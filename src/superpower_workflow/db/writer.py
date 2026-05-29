from __future__ import annotations

import logging
import queue
import threading
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

    from superpower_workflow.telemetry import TelemetryEmitter, TelemetryEvent

logger = logging.getLogger(__name__)


class TelemetryDbWriter:
    def __init__(
        self,
        emitter: TelemetryEmitter,
        engine: Engine,
        project_name: str = "",
        project_path: str = "",
        flush_interval: float = 1.0,
        max_queue_size: int = 1000,
    ) -> None:
        self._emitter = emitter
        self._engine = engine
        self._project_name = project_name
        self._project_path = project_path
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._db_enabled = True
        self._stop = threading.Event()
        self._flush_interval = flush_interval
        self._project_uuid: uuid.UUID | None = None
        self._run_uuid: uuid.UUID | None = None
        self._milestone_uuids: dict[str, uuid.UUID] = {}
        self._phase_uuids: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
        self._thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._thread.start()

    def emit(self, event: TelemetryEvent) -> None:
        self._emitter.emit(event)
        if not self._db_enabled:
            return
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            logger.warning("DB write queue full, disabling DB writes")
            self._db_enabled = False

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)
        self._flush_remaining()
        self._emitter.close()

    def _flush_loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(timeout=self._flush_interval)
            self._flush_batch()

    def _flush_remaining(self) -> None:
        self._flush_batch()

    def _flush_batch(self) -> None:
        if not self._db_enabled:
            return
        batch: list = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if not batch:
            return

        try:
            from superpower_workflow.db.engine import get_session_factory

            factory = get_session_factory(self._engine)
            session = factory()
            try:
                for event in batch:
                    self._write_event(session, event)
                session.commit()
            except Exception:
                session.rollback()
                logger.warning("DB flush failed", exc_info=True)
            finally:
                session.close()
        except Exception:
            logger.warning("DB session creation failed", exc_info=True)

    def _write_event(self, session: Session, event: TelemetryEvent) -> None:
        from superpower_workflow.db.models import SwEvent, SwMilestone, SwPhase, SwRun
        from superpower_workflow.db.queries import get_or_create_project

        event_dict = event.to_dict()
        event_type = event_dict.get("type", "")

        if event_type == "run_started":
            if self._project_name:
                proj = get_or_create_project(session, self._project_name, self._project_path)
                self._project_uuid = proj.id
            if self._project_uuid:
                run = SwRun(
                    id=uuid.uuid4(),
                    project_id=self._project_uuid,
                    run_id=event_dict.get("run_id", ""),
                    model=event_dict.get("model", ""),
                    milestone_count=event_dict.get("milestone_count", 0),
                    spec_sha=event_dict.get("spec_sha"),
                    status="running",
                )
                session.add(run)
                session.flush()
                self._run_uuid = run.id

        if event_type == "milestone_started":
            ms_name = event_dict.get("milestone", "")
            if self._run_uuid and ms_name and ms_name not in self._milestone_uuids:
                ms = SwMilestone(
                    id=uuid.uuid4(),
                    run_id=self._run_uuid,
                    name=ms_name,
                    status="running",
                )
                session.add(ms)
                session.flush()
                self._milestone_uuids[ms_name] = ms.id

        if event_type == "milestone_completed":
            ms_name = event_dict.get("milestone", "")
            ms_id = self._milestone_uuids.get(ms_name)
            if ms_id is not None:
                ms_obj = session.query(SwMilestone).filter(SwMilestone.id == ms_id).first()
                if ms_obj is not None:
                    ms_obj.status = event_dict.get("status", "completed")
                    ms_obj.cost_usd = event_dict.get("cost_usd", ms_obj.cost_usd)
                    ms_obj.duration_seconds = event_dict.get(
                        "duration_seconds", ms_obj.duration_seconds
                    )

        if event_type == "phase_started":
            ms_name = event_dict.get("milestone", "")
            phase_type = event_dict.get("phase", "")
            ms_id = self._milestone_uuids.get(ms_name)
            if ms_id is not None and phase_type:
                phase_key = (ms_id, phase_type)
                if phase_key not in self._phase_uuids:
                    phase = SwPhase(
                        id=uuid.uuid4(),
                        milestone_id=ms_id,
                        phase_type=phase_type,
                        status="running",
                        model=event_dict.get("model"),
                        session_id=event_dict.get("session_id"),
                    )
                    session.add(phase)
                    session.flush()
                    self._phase_uuids[phase_key] = phase.id

        if event_type == "phase_completed":
            ms_name = event_dict.get("milestone", "")
            phase_type = event_dict.get("phase", "")
            ms_id = self._milestone_uuids.get(ms_name)
            phase_id = self._phase_uuids.get((ms_id, phase_type)) if ms_id else None
            if phase_id is not None:
                phase_obj = session.query(SwPhase).filter(SwPhase.id == phase_id).first()
                if phase_obj is not None:
                    phase_obj.status = event_dict.get("status", "completed")
                    phase_obj.cost_usd = event_dict.get("cost_usd", phase_obj.cost_usd)
                    phase_obj.duration_ms = event_dict.get("duration_ms", phase_obj.duration_ms)
                    phase_obj.input_tokens = event_dict.get("input_tokens", phase_obj.input_tokens)
                    phase_obj.output_tokens = event_dict.get(
                        "output_tokens", phase_obj.output_tokens
                    )

        if event_type == "run_completed" and self._run_uuid:
            run_obj = session.query(SwRun).filter(SwRun.id == self._run_uuid).first()
            if run_obj is not None:
                run_obj.status = event_dict.get("status", "complete")
                run_obj.total_cost_usd = event_dict.get("total_cost_usd", 0.0)
                run_obj.completed_count = event_dict.get("completed_count", 0)
                run_obj.failed_count = event_dict.get("failed_count", 0)
                run_obj.skipped_count = event_dict.get("skipped_count", 0)
                run_obj.duration_seconds = event_dict.get("duration_seconds", 0.0)

        if self._run_uuid:
            evt = SwEvent(
                id=uuid.uuid4(),
                run_id=self._run_uuid,
                milestone_name=event_dict.get("milestone"),
                event_type=event_type,
                data_json=event_dict,
            )
            session.add(evt)
