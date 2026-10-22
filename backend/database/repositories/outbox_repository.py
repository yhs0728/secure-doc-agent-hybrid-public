from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from database.models.ops import OutboxEvent


class PostgresOutboxRepository:
    def __init__(self, session: Session, workspace_id: UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    def enqueue(
        self,
        *,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        payload: dict,
        dedupe_key: str,
    ) -> OutboxEvent:
        existing = self._session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.workspace_id == self._workspace_id,
                OutboxEvent.event_type == event_type,
                OutboxEvent.dedupe_key == dedupe_key,
            )
        )
        if existing is not None:
            return existing
        event = OutboxEvent(
            workspace_id=self._workspace_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            dedupe_key=dedupe_key,
            payload=payload,
            status="PENDING",
        )
        self._session.add(event)
        self._session.flush()
        return event

    def claim_batch(self, worker_name: str, limit: int) -> list[OutboxEvent]:
        now = datetime.now(UTC)
        events = list(
            self._session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.workspace_id == self._workspace_id,
                    OutboxEvent.status.in_(("PENDING", "FAILED")),
                    OutboxEvent.available_at <= now,
                    OutboxEvent.attempt_count < OutboxEvent.max_attempts,
                )
                .order_by(OutboxEvent.available_at, OutboxEvent.created_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        )
        for event in events:
            event.status = "PROCESSING"
            event.attempt_count += 1
            event.locked_at = now
            event.locked_by = worker_name
            event.error_message = None
        return events

    def publish(self, event_id: UUID) -> None:
        event = self._session.get(OutboxEvent, event_id)
        if event is None:
            raise LookupError("Outbox 이벤트를 찾을 수 없습니다.")
        event.status = "PUBLISHED"
        event.published_at = datetime.now(UTC)
        event.locked_at = None
        event.locked_by = None
        event.error_message = None

    def fail(self, event_id: UUID, error: BaseException) -> None:
        event = self._session.get(OutboxEvent, event_id)
        if event is None:
            return
        event.status = "FAILED"
        event.locked_at = None
        event.locked_by = None
        event.error_message = str(error)[:4000]
        delay = min(300, 2 ** min(event.attempt_count, 8))
        event.available_at = datetime.now(UTC) + timedelta(seconds=delay)

    def recover_stale(self, stale_after_seconds: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        events = list(
            self._session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.workspace_id == self._workspace_id,
                    OutboxEvent.status == "PROCESSING",
                    or_(OutboxEvent.locked_at.is_(None), OutboxEvent.locked_at < cutoff),
                )
                .with_for_update(skip_locked=True)
            )
        )
        for event in events:
            event.status = "FAILED"
            event.locked_at = None
            event.locked_by = None
            event.error_message = "stale outbox lease recovered"
            event.available_at = datetime.now(UTC)
        return len(events)
