from __future__ import annotations

import socket
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from config.settings import Settings
from database.models.content import Document, DocumentVersion, StorageObject
from database.models.rag import IngestionJob
from database.repositories.outbox_repository import PostgresOutboxRepository
from database.session import set_local_user_context, transaction
from integrations.object_storage import S3ObjectStore


def run_outbox_batch(
    settings: Settings,
    object_store: S3ObjectStore | None = None,
    limit: int | None = None,
) -> tuple[int, int]:
    if settings.object_storage_backend == "LOCAL":
        return 0, 0
    store = object_store or S3ObjectStore.from_settings(settings)
    worker_name = f"outbox:{socket.gethostname()}"
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        repository = PostgresOutboxRepository(session, settings.default_workspace_id)
        repository.recover_stale(settings.worker_stale_after_seconds)
        events = repository.claim_batch(
            worker_name,
            limit or settings.outbox_batch_size,
        )

    succeeded = 0
    failed = 0
    for event in events:
        try:
            if event.event_type == "OBJECT_UPLOAD_REQUESTED":
                _handle_upload(settings, store, event.id, event.payload)
            elif event.event_type == "OBJECT_DELETE_REQUESTED":
                _handle_delete(settings, store, event.id, event.payload)
            else:
                raise ValueError(f"지원하지 않는 Outbox 이벤트입니다: {event.event_type}")
            succeeded += 1
        except Exception as error:  # noqa: BLE001 - event failure is persisted
            with transaction() as session:
                set_local_user_context(session, settings.system_user_id)
                PostgresOutboxRepository(
                    session, settings.default_workspace_id
                ).fail(event.id, error)
            failed += 1
    return succeeded, failed


def _handle_upload(
    settings: Settings,
    store: S3ObjectStore,
    event_id: UUID,
    payload: dict,
) -> None:
    storage_object_id = UUID(str(payload["storage_object_id"]))
    job_id = UUID(str(payload["ingestion_job_id"]))
    stored = store.upload(
        Path(str(payload["source_path"])),
        str(payload["object_key"]),
        str(payload["checksum_sha256"]),
    )
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        storage_object = session.get(StorageObject, storage_object_id)
        job = session.get(IngestionJob, job_id)
        if storage_object is None or job is None:
            raise LookupError("Outbox 업로드 대상이 존재하지 않습니다.")
        storage_object.bucket = stored.bucket
        storage_object.object_key = stored.key
        storage_object.etag = stored.etag
        storage_object.version_id = stored.version_id
        storage_object.size_bytes = stored.size_bytes
        storage_object.verified_at = datetime.now(UTC)
        job.status = "PENDING"
        job.available_at = datetime.now(UTC)
        PostgresOutboxRepository(
            session, settings.default_workspace_id
        ).publish(event_id)


def _handle_delete(
    settings: Settings,
    store: S3ObjectStore,
    event_id: UUID,
    payload: dict,
) -> None:
    storage_object_id = UUID(str(payload["storage_object_id"]))
    document_id = UUID(str(payload["document_id"]))
    version_id = UUID(str(payload["document_version_id"]))
    store.delete(str(payload["object_key"]), str(payload.get("version_id") or ""))
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        storage_object = session.get(StorageObject, storage_object_id)
        document = session.get(Document, document_id)
        version = session.get(DocumentVersion, version_id)
        now = datetime.now(UTC)
        if storage_object is not None:
            storage_object.deleted_at = now
        if version is not None:
            version.processing_status = "DELETED"
        if document is not None:
            document.lifecycle_status = "DELETED"
            document.deleted_at = now
            document.current_version_id = None
        PostgresOutboxRepository(
            session, settings.default_workspace_id
        ).publish(event_id)
