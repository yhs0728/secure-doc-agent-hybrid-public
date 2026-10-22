from __future__ import annotations

import socket
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from config.settings import Settings
from database.models.content import Document, DocumentVersion
from database.repositories.ingestion_repository import PostgresIngestionRepository
from database.session import set_local_user_context, transaction
from ingestion.incremental_indexer import load_and_split_document


def enqueue_ingestion(file_path: Path, settings: Settings, title: str | None = None) -> UUID:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        return PostgresIngestionRepository(session, settings).enqueue(file_path, title)


def run_ingestion_job(job_id: UUID, settings: Settings, index_updater) -> None:
    worker_name = f"api-sync:{socket.gethostname()}"
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        repository = PostgresIngestionRepository(session, settings)
        _job, version = repository.claim(job_id, worker_name)
        version_id = version.id
        source_path = repository.source_path(
            version_id,
            Path(settings.source_directory),
        )

    _process_claimed_job(job_id, version_id, source_path, settings, index_updater)


def _process_claimed_job(
    job_id: UUID,
    version_id: UUID,
    source_path: Path,
    settings: Settings,
    index_updater,
) -> None:

    try:
        chunks = load_and_split_document(
            file_path=source_path,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        with transaction() as session:
            set_local_user_context(session, settings.system_user_id)
            PostgresIngestionRepository(session, settings).set_version_status(
                version_id, "CHUNKING"
            )

        with transaction() as session:
            set_local_user_context(session, settings.system_user_id)
            PostgresIngestionRepository(session, settings).set_version_status(
                version_id, "EMBEDDING"
            )
        index_updater(settings=settings)

        with transaction() as session:
            set_local_user_context(session, settings.system_user_id)
            repository = PostgresIngestionRepository(session, settings)
            repository.set_version_status(version_id, "INDEXING")
            repository.succeed(job_id, chunks)
    except Exception as error:
        with transaction() as session:
            set_local_user_context(session, settings.system_user_id)
            PostgresIngestionRepository(session, settings).fail(job_id, error)
        raise


def synchronize_ready_document_chunks(settings: Settings) -> int:
    """Backfill chunk metadata for already indexed legacy documents."""
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        rows = session.execute(
            select(DocumentVersion.id, DocumentVersion.original_filename)
            .join(Document, Document.current_version_id == DocumentVersion.id)
            .where(
                Document.workspace_id == settings.default_workspace_id,
                Document.deleted_at.is_(None),
                Document.lifecycle_status == "ACTIVE",
                DocumentVersion.processing_status == "READY",
            )
        ).all()

    synchronized = 0
    for version_id, file_name in rows:
        source_path = Path(settings.source_directory) / file_name
        if not source_path.is_file():
            continue
        chunks = load_and_split_document(
            file_path=source_path,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        with transaction() as session:
            set_local_user_context(session, settings.system_user_id)
            PostgresIngestionRepository(session, settings).replace_chunks(
                version_id, chunks
            )
        synchronized += 1
    return synchronized


def run_pending_ingestion_jobs(
    settings: Settings,
    index_updater,
    limit: int = 10,
) -> tuple[int, int]:
    succeeded = 0
    failed = 0
    worker_name = f"worker:{socket.gethostname()}"
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        PostgresIngestionRepository(session, settings).recover_stale(
            settings.worker_stale_after_seconds
        )
    for _ in range(limit):
        with transaction() as session:
            set_local_user_context(session, settings.system_user_id)
            repository = PostgresIngestionRepository(session, settings)
            claimed = repository.claim_next(worker_name)
            if claimed is None:
                break
            job, version = claimed
            job_id = job.id
            version_id = version.id
            source_path = repository.source_path(
                version_id,
                Path(settings.source_directory),
            )
        try:
            _process_claimed_job(
                job_id,
                version_id,
                source_path,
                settings,
                index_updater,
            )
            succeeded += 1
        except Exception:  # noqa: BLE001 - one failed job must not stop the worker
            failed += 1
    return succeeded, failed
