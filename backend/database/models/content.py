from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin
from database.ids import new_uuid7


class StorageObject(Base):
    __tablename__ = "storage_objects"
    __table_args__ = (
        UniqueConstraint("provider", "bucket", "object_key", "version_id"),
        CheckConstraint(
            "provider IN ('LOCAL', 'OCI', 'S3', 'MINIO')",
            name="valid_provider",
        ),
        {"schema": "content"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "identity.workspaces.id",
            ondelete="CASCADE",
            use_alter=True,
            name="fk_storage_objects_workspace_id_workspaces",
        ),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(String(100))
    etag: Mapped[str | None] = mapped_column(String(255))
    version_id: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default=""
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    encryption_type: Mapped[str | None] = mapped_column(String(50))
    provider_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "lifecycle_status IN ('ACTIVE', 'DELETING', 'DELETED')",
            name="valid_lifecycle_status",
        ),
        Index(
            "ix_documents_workspace_active",
            "workspace_id",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": "content"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="RESTRICT"), nullable=False
    )
    current_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "content.document_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_documents_current_version_id_document_versions",
        )
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    lifecycle_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_no"),
        CheckConstraint("version_no >= 1", name="positive_version_no"),
        CheckConstraint("size_bytes >= 0", name="nonnegative_size"),
        CheckConstraint("page_count >= 1", name="positive_page_count"),
        CheckConstraint(
            "processing_status IN ("
            "'PENDING', 'UPLOADING', 'UPLOADED', 'PARSING', 'CHUNKING', "
            "'EMBEDDING', 'INDEXING', 'READY', 'FAILED', 'DELETING', 'DELETED'"
            ")",
            name="valid_processing_status",
        ),
        Index("ix_document_versions_document", "document_id", "version_no"),
        {"schema": "content"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("content.documents.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(255), nullable=False)
    file_extension: Mapped[str] = mapped_column(String(20), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="PENDING"
    )
    parser_name: Mapped[str | None] = mapped_column(String(100))
    parser_version: Mapped[str | None] = mapped_column(String(50))
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="RESTRICT"), nullable=False
    )
    extra_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentArtifact(Base):
    __tablename__ = "document_artifacts"
    __table_args__ = (
        UniqueConstraint("document_version_id", "artifact_type"),
        CheckConstraint(
            "artifact_type IN ("
            "'SOURCE', 'EXTRACTED_TEXT', 'PREVIEW', 'THUMBNAIL', 'OCR_RESULT'"
            ")",
            name="valid_artifact_type",
        ),
        {"schema": "content"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("content.document_versions.id", ondelete="CASCADE"), nullable=False
    )
    storage_object_id: Mapped[UUID] = mapped_column(
        ForeignKey("content.storage_objects.id", ondelete="RESTRICT"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
