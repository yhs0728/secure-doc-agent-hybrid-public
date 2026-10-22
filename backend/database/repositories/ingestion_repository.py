from __future__ import annotations

import hashlib
import mimetypes
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from langchain_core.documents import Document as LangChainDocument
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from config.settings import Settings
from database.models.content import (
    Document,
    DocumentArtifact,
    DocumentVersion,
    StorageObject,
)
from database.models.rag import DocumentChunk, IngestionJob
from database.repositories.outbox_repository import PostgresOutboxRepository


class PostgresIngestionRepository:
    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._workspace_id = settings.default_workspace_id
        self._user_id = settings.system_user_id

    def enqueue(self, file_path: Path, title: str | None = None) -> UUID:
        content = file_path.read_bytes()
        checksum = hashlib.sha256(content).hexdigest()
        existing_object = self._session.scalar(
            select(StorageObject).where(
                StorageObject.workspace_id == self._workspace_id,
                StorageObject.provider == "LOCAL",
                StorageObject.bucket == "data/source",
                StorageObject.object_key == file_path.name,
                StorageObject.version_id == "",
            )
        )
        if existing_object is not None:
            raise ValueError(f"이미 DB에 등록된 파일입니다: {file_path.name}")

        document = Document(
            workspace_id=self._workspace_id,
            created_by_user_id=self._user_id,
            title=(title or file_path.stem).strip(),
            lifecycle_status="ACTIVE",
        )
        self._session.add(document)
        self._session.flush()

        version = DocumentVersion(
            document_id=document.id,
            version_no=1,
            original_filename=file_path.name,
            normalized_filename=file_path.name,
            media_type=mimetypes.guess_type(file_path.name)[0]
            or "application/octet-stream",
            file_extension=file_path.suffix.lower(),
            size_bytes=len(content),
            page_count=1,
            checksum_sha256=checksum,
            processing_status="UPLOADED",
            parser_name="secure-doc-loader",
            parser_version="1",
            created_by_user_id=self._user_id,
        )
        external_storage = self._settings.object_storage_backend != "LOCAL"
        object_key = (
            f"{self._workspace_id}/{document.id}/{version.id}/{file_path.name}"
            if external_storage
            else file_path.name
        )
        storage_object = StorageObject(
            workspace_id=self._workspace_id,
            provider=self._settings.object_storage_backend,
            bucket=(
                self._settings.object_storage_bucket
                if external_storage
                else "data/source"
            ),
            object_key=object_key,
            region=(self._settings.object_storage_region if external_storage else None),
            size_bytes=len(content),
            checksum_sha256=checksum,
        )
        self._session.add_all((version, storage_object))
        self._session.flush()
        self._session.add(
            DocumentArtifact(
                document_version_id=version.id,
                storage_object_id=storage_object.id,
                artifact_type="SOURCE",
            )
        )
        job = IngestionJob(
            workspace_id=self._workspace_id,
            document_version_id=version.id,
            job_type="INGEST_DOCUMENT",
            status="RETRY_WAIT" if external_storage else "PENDING",
            available_at=(
                datetime.now(UTC) + timedelta(days=3650)
                if external_storage
                else datetime.now(UTC)
            ),
        )
        self._session.add(job)
        self._session.flush()
        if external_storage:
            PostgresOutboxRepository(self._session, self._workspace_id).enqueue(
                aggregate_type="DOCUMENT_VERSION",
                aggregate_id=version.id,
                event_type="OBJECT_UPLOAD_REQUESTED",
                dedupe_key=f"upload:{storage_object.id}:{checksum}",
                payload={
                    "storage_object_id": str(storage_object.id),
                    "document_version_id": str(version.id),
                    "ingestion_job_id": str(job.id),
                    "source_path": str(file_path.resolve()),
                    "object_key": object_key,
                    "checksum_sha256": checksum,
                },
            )
        return job.id

    def pending_job_ids(self, limit: int = 10) -> list[UUID]:
        now = datetime.now(UTC)
        return list(
            self._session.scalars(
                select(IngestionJob.id)
                .where(
                    IngestionJob.workspace_id == self._workspace_id,
                    IngestionJob.status.in_(("PENDING", "RETRY_WAIT")),
                    IngestionJob.available_at <= now,
                )
                .order_by(
                    IngestionJob.priority.desc(),
                    IngestionJob.available_at,
                    IngestionJob.created_at,
                )
                .limit(limit)
            )
        )

    def claim(self, job_id: UUID, worker_name: str) -> tuple[IngestionJob, DocumentVersion]:
        job = self._session.scalar(
            select(IngestionJob).where(IngestionJob.id == job_id).with_for_update()
        )
        if job is None:
            raise LookupError(f"인덱싱 작업을 찾을 수 없습니다: {job_id}")
        if job.status not in {"PENDING", "RETRY_WAIT"}:
            raise ValueError(f"실행할 수 없는 작업 상태입니다: {job.status}")
        if job.available_at > datetime.now(UTC):
            raise ValueError("아직 실행 가능한 시간이 아닌 작업입니다.")
        version = self._session.get(DocumentVersion, job.document_version_id)
        if version is None:
            raise LookupError("작업 대상 문서 버전을 찾을 수 없습니다.")
        now = datetime.now(UTC)
        job.status = "RUNNING"
        job.attempt_count += 1
        job.locked_at = now
        job.heartbeat_at = now
        job.locked_by = worker_name
        job.started_at = job.started_at or now
        version.processing_status = "PARSING"
        return job, version

    def claim_next(
        self, worker_name: str
    ) -> tuple[IngestionJob, DocumentVersion] | None:
        now = datetime.now(UTC)
        job = self._session.scalar(
            select(IngestionJob)
            .where(
                IngestionJob.workspace_id == self._workspace_id,
                IngestionJob.status.in_(("PENDING", "RETRY_WAIT")),
                IngestionJob.available_at <= now,
            )
            .order_by(
                IngestionJob.priority.desc(),
                IngestionJob.available_at,
                IngestionJob.created_at,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        version = self._session.get(DocumentVersion, job.document_version_id)
        if version is None:
            raise LookupError("작업 대상 문서 버전을 찾을 수 없습니다.")
        job.status = "RUNNING"
        job.attempt_count += 1
        job.locked_at = now
        job.heartbeat_at = now
        job.locked_by = worker_name
        job.started_at = job.started_at or now
        version.processing_status = "PARSING"
        return job, version

    def recover_stale(self, stale_after_seconds: int) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        jobs = list(
            self._session.scalars(
                select(IngestionJob).where(
                    IngestionJob.workspace_id == self._workspace_id,
                    IngestionJob.status == "RUNNING",
                    or_(
                        IngestionJob.locked_at.is_(None),
                        IngestionJob.locked_at < cutoff,
                    ),
                ).with_for_update(skip_locked=True)
            )
        )
        for job in jobs:
            job.status = "RETRY_WAIT"
            job.available_at = datetime.now(UTC)
            job.locked_at = None
            job.locked_by = None
            job.heartbeat_at = None
            job.error_code = "STALE_WORKER_RECOVERED"
            job.error_message = "stale ingestion lease recovered"
        return len(jobs)

    def source_path(self, version_id: UUID, source_directory: Path) -> Path:
        version = self._session.get(DocumentVersion, version_id)
        if version is None:
            raise LookupError("문서 버전을 찾을 수 없습니다.")
        return source_directory / version.original_filename

    def set_version_status(self, version_id: UUID, status: str) -> None:
        version = self._session.get(DocumentVersion, version_id)
        if version is None:
            raise LookupError("문서 버전을 찾을 수 없습니다.")
        version.processing_status = status

    def replace_chunks(
        self,
        version_id: UUID,
        chunks: list[LangChainDocument],
    ) -> None:
        self._session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_version_id == version_id)
        )
        for ordinal, chunk in enumerate(chunks):
            content = chunk.page_content.strip()
            metadata = dict(chunk.metadata)
            self._session.add(
                DocumentChunk(
                    document_version_id=version_id,
                    ordinal=ordinal,
                    page_start=_optional_int(metadata.get("page_start")),
                    page_end=_optional_int(metadata.get("page_end")),
                    content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    token_count=None,
                    heading=_optional_str(metadata.get("heading")),
                    extra_metadata={
                        "source": metadata.get("source"),
                        "chunk_id": metadata.get("chunk_id"),
                        "document_id": metadata.get("document_id"),
                    },
                )
            )

    def succeed(self, job_id: UUID, chunks: list[LangChainDocument]) -> None:
        job = self._session.get(IngestionJob, job_id)
        if job is None or job.document_version_id is None:
            raise LookupError("인덱싱 작업을 찾을 수 없습니다.")
        version = self._session.get(DocumentVersion, job.document_version_id)
        if version is None:
            raise LookupError("문서 버전을 찾을 수 없습니다.")
        self.replace_chunks(version.id, chunks)
        now = datetime.now(UTC)
        version.processing_status = "READY"
        version.ready_at = now
        version.failure_code = None
        version.failure_message = None
        document = self._session.get(Document, version.document_id)
        if document is None:
            raise LookupError("문서를 찾을 수 없습니다.")
        document.current_version_id = version.id
        job.status = "SUCCEEDED"
        job.completed_at = now
        job.locked_at = None
        job.locked_by = None
        job.heartbeat_at = None

    def fail(self, job_id: UUID, error: BaseException) -> None:
        job = self._session.get(IngestionJob, job_id)
        if job is None:
            return
        now = datetime.now(UTC)
        job.status = "FAILED" if job.attempt_count >= job.max_attempts else "RETRY_WAIT"
        job.error_code = error.__class__.__name__[:100]
        job.error_message = str(error)
        job.completed_at = now if job.status == "FAILED" else None
        job.locked_at = None
        job.locked_by = None
        job.heartbeat_at = None
        if job.document_version_id is not None:
            version = self._session.get(DocumentVersion, job.document_version_id)
            if version is not None:
                version.processing_status = "FAILED"
                version.failure_code = job.error_code
                version.failure_message = job.error_message
                version.failed_at = now


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
