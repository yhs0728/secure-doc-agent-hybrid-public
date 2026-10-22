from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from database.models.content import Document as DocumentRow
from database.models.content import DocumentArtifact, DocumentVersion, StorageObject
from database.repositories.outbox_repository import PostgresOutboxRepository
from models.document import Document


@dataclass(frozen=True)
class DocumentSource:
    document_id: UUID
    document_version_id: UUID
    file_name: str
    storage_object_id: UUID
    storage_provider: str
    object_key: str
    object_version_id: str


class PostgresDocumentRepository:
    """Workspace-scoped document catalog backed by PostgreSQL."""

    def __init__(self, session: Session, workspace_id: UUID) -> None:
        self._session = session
        self._workspace_id = workspace_id

    def _base_query(self) -> Select:
        return (
            select(
                DocumentRow.id,
                DocumentRow.title,
                DocumentVersion.original_filename,
                DocumentVersion.page_count,
            )
            .join(DocumentVersion, DocumentVersion.id == DocumentRow.current_version_id)
            .join(
                DocumentArtifact,
                (DocumentArtifact.document_version_id == DocumentVersion.id)
                & (DocumentArtifact.artifact_type == "SOURCE"),
            )
            .join(StorageObject, StorageObject.id == DocumentArtifact.storage_object_id)
            .where(
                DocumentRow.workspace_id == self._workspace_id,
                DocumentRow.deleted_at.is_(None),
                DocumentRow.lifecycle_status == "ACTIVE",
                DocumentVersion.processing_status == "READY",
            )
        )

    def list(self, keyword: str | None = None) -> list[Document]:
        query = self._base_query()
        normalized_keyword = (keyword or "").strip()
        if normalized_keyword:
            pattern = f"%{normalized_keyword}%"
            query = query.where(
                or_(
                    DocumentRow.title.ilike(pattern),
                    DocumentVersion.original_filename.ilike(pattern),
                )
            )

        rows = self._session.execute(
            query.order_by(DocumentRow.created_at.desc())
        ).all()
        return [
            Document(
                document_id=str(row.id),
                title=row.title,
                file_name=row.original_filename,
                page_count=row.page_count,
            )
            for row in rows
        ]

    def get(self, document_id: UUID) -> Document | None:
        row = self._session.execute(
            self._base_query().where(DocumentRow.id == document_id)
        ).one_or_none()
        if row is None:
            return None
        return Document(
            document_id=str(row.id),
            title=row.title,
            file_name=row.original_filename,
            page_count=row.page_count,
        )

    def find_source(self, document_id: str) -> DocumentSource | None:
        """Resolve either the UUID API id or a legacy filename stem."""
        normalized_id = document_id.strip()
        try:
            uuid_value: UUID | None = UUID(normalized_id)
        except ValueError:
            uuid_value = None

        query = (
            select(
                DocumentRow.id,
                DocumentVersion.id.label("version_id"),
                DocumentVersion.original_filename,
                StorageObject.id.label("storage_object_id"),
                StorageObject.provider,
                StorageObject.object_key,
                StorageObject.version_id.label("object_version_id"),
            )
            .join(DocumentVersion, DocumentVersion.id == DocumentRow.current_version_id)
            .join(
                DocumentArtifact,
                (DocumentArtifact.document_version_id == DocumentVersion.id)
                & (DocumentArtifact.artifact_type == "SOURCE"),
            )
            .join(StorageObject, StorageObject.id == DocumentArtifact.storage_object_id)
            .where(
                DocumentRow.workspace_id == self._workspace_id,
                DocumentRow.deleted_at.is_(None),
                DocumentRow.lifecycle_status.in_(("ACTIVE", "DELETING")),
            )
        )
        if uuid_value is not None:
            query = query.where(DocumentRow.id == uuid_value)
        else:
            query = query.where(
                func.regexp_replace(
                    DocumentVersion.original_filename,
                    r"\.[^.]+$",
                    "",
                )
                == Path(normalized_id).stem
            )

        row = self._session.execute(query).one_or_none()
        if row is None:
            return None
        return DocumentSource(
            document_id=row.id,
            document_version_id=row.version_id,
            file_name=row.original_filename,
            storage_object_id=row.storage_object_id,
            storage_provider=row.provider,
            object_key=row.object_key,
            object_version_id=row.object_version_id,
        )

    def count_active(self) -> int:
        return int(
            self._session.scalar(
                select(func.count(DocumentRow.id)).where(
                    DocumentRow.workspace_id == self._workspace_id,
                    DocumentRow.deleted_at.is_(None),
                    DocumentRow.lifecycle_status == "ACTIVE",
                )
            )
            or 0
        )

    def mark_deleting(self, source: DocumentSource) -> None:
        document = self._session.get(DocumentRow, source.document_id)
        version = self._session.get(DocumentVersion, source.document_version_id)
        if document is None or version is None:
            raise LookupError("삭제할 문서를 찾을 수 없습니다.")
        document.lifecycle_status = "DELETING"
        version.processing_status = "DELETING"

    def enqueue_external_delete(self, source: DocumentSource) -> None:
        PostgresOutboxRepository(self._session, self._workspace_id).enqueue(
            aggregate_type="DOCUMENT",
            aggregate_id=source.document_id,
            event_type="OBJECT_DELETE_REQUESTED",
            dedupe_key=f"delete:{source.storage_object_id}:{source.object_version_id}",
            payload={
                "document_id": str(source.document_id),
                "document_version_id": str(source.document_version_id),
                "storage_object_id": str(source.storage_object_id),
                "object_key": source.object_key,
                "version_id": source.object_version_id,
            },
        )

    def complete_delete(self, source: DocumentSource) -> None:
        now = datetime.now(UTC)
        document = self._session.get(DocumentRow, source.document_id)
        version = self._session.get(DocumentVersion, source.document_version_id)
        if document is None or version is None:
            raise LookupError("삭제할 문서를 찾을 수 없습니다.")
        document.lifecycle_status = "DELETED"
        document.deleted_at = now
        document.current_version_id = None
        version.processing_status = "DELETED"
        storage_object = self._session.scalar(
            select(StorageObject).where(
                StorageObject.workspace_id == self._workspace_id,
                StorageObject.id == source.storage_object_id,
                StorageObject.deleted_at.is_(None),
            )
        )
        if storage_object is not None:
            storage_object.deleted_at = now

    def restore_active(self, source: DocumentSource) -> None:
        document = self._session.get(DocumentRow, source.document_id)
        version = self._session.get(DocumentVersion, source.document_version_id)
        if document is not None:
            document.lifecycle_status = "ACTIVE"
        if version is not None:
            version.processing_status = "READY"
